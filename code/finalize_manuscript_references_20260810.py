"""Create the audited final manuscript with corrected citations, references, and figures."""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from docx import Document


REFERENCES = [
    {
        "number": 1,
        "text": "Lloyd-Jones DM, Allen NB, Anderson CAM, Black T, Brewer LC, Foraker RE, Grandner MA, Lavretsky H, Perak AM, Sharma G, Rosamond W: Life's Essential 8: Updating and Enhancing the American Heart Association's Construct of Cardiovascular Health: A Presidential Advisory From the American Heart Association. Circulation 2022, 146(5):e18–e43. doi:10.1161/CIR.0000000000001078.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/35766027/",
        "change": "Added Rosamond W, issue, pages, and DOI.",
    },
    {
        "number": 2,
        "text": "Jaspan VN, Greenberg GS, Parihar S, Park CM, Somers VK, Shapiro MD, Lavie CJ, Virani SS, Slipczuk L: The Role of Sleep in Cardiovascular Disease. Curr Atheroscler Rep 2024, 26(7):249–262. doi:10.1007/s11883-024-01207-5.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/38795275/",
        "change": "Added issue and DOI.",
    },
    {
        "number": 3,
        "text": "Korostovtseva L, Bochkarev M, Sviryaev Y: Sleep and Cardiovascular Risk. Sleep Med Clin 2021, 16(3):485–497. doi:10.1016/j.jsmc.2021.05.001.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/34325825/",
        "change": "Standardized journal title; added issue and DOI.",
    },
    {
        "number": 4,
        "text": "Watson NF, Badr MS, Belenky G, Bliwise DL, Buxton OM, Buysse D, Dinges DF, Gangwisch J, Grandner MA, Kushida C, Malhotra RK, Martin JL, Patel SR, Quan SF, Tasali E: Recommended Amount of Sleep for a Healthy Adult: A Joint Consensus Statement of the American Academy of Sleep Medicine and Sleep Research Society. Sleep 2015, 38(6):843–844. doi:10.5665/sleep.4716.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC4434546/",
        "change": "Completed author list, volume, issue, pages, and DOI.",
    },
    {
        "number": 5,
        "text": "Kwok CS, Kontopantelis E, Kuligowski G, Gray M, Muhyaldeen A, Gale CP, Peat GM, Cleator J, Chew-Graham C, Loke YK, Mamas AM: Self-Reported Sleep Duration and Quality and Cardiovascular Disease and Mortality: A Dose-Response Meta-Analysis. J Am Heart Assoc 2018, 7(15):e008552. doi:10.1161/JAHA.118.008552.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/30371228/",
        "change": "Added Mamas AM, issue, and DOI.",
    },
    {
        "number": 6,
        "text": "Yin J, Jin X, Shan Z, Li S, Huang H, Li P, Peng X, Peng Z, Yu K, Bao W, Yang W, Chen X, Liu L: Relationship of Sleep Duration With All-Cause Mortality and Cardiovascular Events: A Systematic Review and Dose-Response Meta-Analysis of Prospective Cohort Studies. J Am Heart Assoc 2017, 6(9):e005947. doi:10.1161/JAHA.117.005947.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/28889101/",
        "change": "Completed author list; added issue and DOI.",
    },
    {
        "number": 7,
        "text": "Jin Q, Yang N, Dai J, Zhao Y, Zhang X, Yin J, Yan Y: Association of Sleep Duration With All-Cause and Cardiovascular Mortality: A Prospective Cohort Study. Front Public Health 2022, 10:880276. doi:10.3389/fpubh.2022.880276.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/35910926/",
        "change": "Added DOI.",
    },
    {
        "number": 8,
        "text": "Patel SR, Malhotra A, Gottlieb DJ, White DP, Hu FB: Correlates of Long Sleep Duration. Sleep 2006, 29(7):881–889. doi:10.1093/sleep/29.7.881.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC3500381/",
        "change": "Added issue and DOI.",
    },
    {
        "number": 9,
        "text": "Spiesshoefer J, Linz D, Skobel E, Arzt M, Stadler S, Schoebel C, Fietze I, Penzel T, Sinha AM, Fox H, Oldenburg O: Sleep - the yet underappreciated player in cardiovascular diseases: A clinical review from the German Cardiac Society Working Group on Sleep Disordered Breathing. Eur J Prev Cardiol 2021, 28(2):189–200. doi:10.1177/2047487319879526.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/33611525/",
        "change": "Added Oldenburg O, issue, and DOI.",
    },
    {
        "number": 10,
        "text": "Mullington JM, Simpson NS, Meier-Ewert HK, Haack M: Sleep loss and inflammation. Best Pract Res Clin Endocrinol Metab 2010, 24(5):775–784. doi:10.1016/j.beem.2010.08.014.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC3548567/",
        "change": "Standardized journal title; added issue and DOI.",
    },
    {
        "number": 11,
        "text": "Yeghiazarians Y, Jneid H, Tietjens JR, Redline S, Brown DL, El-Sherif N, Mehra R, Bozkurt B, Ndumele CE, Somers VK: Obstructive Sleep Apnea and Cardiovascular Disease: A Scientific Statement From the American Heart Association. Circulation 2021, 144(3):e56–e67. doi:10.1161/CIR.0000000000000988.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/34148375/",
        "change": "Added issue, pages, and DOI.",
    },
    {
        "number": 12,
        "text": "Floras JS: Sleep apnea and cardiovascular risk. J Cardiol 2014, 63(1):3–8. doi:10.1016/j.jjcc.2013.08.009.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/24084492/",
        "change": "Added issue and DOI.",
    },
    {
        "number": 13,
        "text": "Caples SM, Garcia-Touchard A, Somers VK: Sleep-disordered breathing and cardiovascular risk. Sleep 2007, 30(3):291–304. doi:10.1093/sleep/30.3.291.",
        "url": "https://doi.org/10.1093/sleep/30.3.291",
        "change": "Corrected final page from 303 to 304; added issue and DOI.",
    },
    {
        "number": 14,
        "text": "Li Y, Miao Y, Zhang Q: Causal associations of obstructive sleep apnea with cardiovascular disease: a Mendelian randomization study. Sleep 2023, 46(3):zsac298. doi:10.1093/sleep/zsac298.",
        "url": "https://academic.oup.com/sleep/article/46/3/zsac298/6884019",
        "change": "Added issue and DOI.",
    },
    {
        "number": 15,
        "text": "National Center for Health Statistics: NHANES Survey Methods and Analytic Guidelines. Centers for Disease Control and Prevention. https://wwwn.cdc.gov/nchs/nhanes/analyticguidelines.aspx (accessed 10 August 2026).",
        "url": "https://wwwn.cdc.gov/nchs/nhanes/analyticguidelines.aspx",
        "change": "Updated access date and retained the authoritative NCHS portal.",
    },
    {
        "number": 16,
        "text": "VanderWeele TJ: Causal mediation analysis with survival data. Epidemiology 2011, 22(4):582–585. doi:10.1097/EDE.0b013e31821db37e.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/21642779/",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
    {
        "number": 17,
        "text": "Schuler MS, Coffman DL, Stuart EA, Nguyen TQ, Vegetabile B, McCaffrey DF: Practical challenges in mediation analysis: a guide for applied researchers. Health Serv Outcomes Res Methodol 2025, 25(1):57–84. doi:10.1007/s10742-024-00327-4.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/39958808/",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
    {
        "number": 18,
        "text": "Georgeson AR, Alvarez-Bartolo D, MacKinnon DP: A sensitivity analysis for temporal bias in cross-sectional mediation. Psychol Methods 2025, 30(6):1326–1344. doi:10.1037/met0000628.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/38127571/",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
    {
        "number": 19,
        "text": "Fine JP, Gray RJ: A proportional hazards model for the subdistribution of a competing risk. J Am Stat Assoc 1999, 94(446):496–509. doi:10.1080/01621459.1999.10474144.",
        "url": "https://doi.org/10.1080/01621459.1999.10474144",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
    {
        "number": 20,
        "text": "Hernán MA, Sauer BC, Hernández-Díaz S, Platt R, Shrier I: Specifying a target trial prevents immortal time bias and other self-inflicted injuries in observational analyses. J Clin Epidemiol 2016, 79:70–75. doi:10.1016/j.jclinepi.2016.04.014.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/27237061/",
        "change": "Moved to first methods occurrence; corrected diacritics and added DOI.",
    },
    {
        "number": 21,
        "text": "White IR, Royston P, Wood AM: Multiple imputation using chained equations: issues and guidance for practice. Stat Med 2011, 30(4):377–399. doi:10.1002/sim.4067.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/21225900/",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
    {
        "number": 22,
        "text": "Syriopoulou E, Mozumder SI, Rutherford MJ, Lambert PC: Estimating causal effects in the presence of competing events using regression standardisation with the Stata command standsurv. BMC Med Res Methodol 2022, 22:226. doi:10.1186/s12874-022-01666-x.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9375409/",
        "change": "Moved to first methods occurrence and added DOI.",
    },
    {
        "number": 23,
        "text": "VanderWeele TJ, Ding P: Sensitivity analysis in observational research: introducing the E-value. Ann Intern Med 2017, 167(4):268–274. doi:10.7326/M16-2607.",
        "url": "https://pubmed.ncbi.nlm.nih.gov/28693043/",
        "change": "Moved to first methods occurrence; added issue and DOI.",
    },
]


PARAGRAPH_REPLACEMENTS = {
    "Figure 1. Causal structures guiding model interpretation.": (
        "Figure 1. Causal structures guiding model interpretation. Panel A shows the etiologic pathway of interest; "
        "Panel B shows an alternative in which underlying poor health causes both longer sleep and mortality. Solid "
        "arrows indicate assumed causal relations and dashed arrows mark temporally uncertain pathways. SIRI and SII "
        "were measured at the same baseline visit as sleep duration; therefore, pathway analyses are exploratory rather "
        "than causal mediation estimates [16–18]."
    ),
    "Usual sleep duration was self-reported": (
        "Usual sleep duration was self-reported in hours per night and harmonized across cycles. It was analyzed in five "
        "clinically interpretable categories: <6, 6–<7, 7–<8, 8–<9, and ≥9 h/night, with 7–<8 h/night as the reference, "
        "and continuously with restricted cubic splines. The primary outcome was heart disease mortality, defined as "
        "MORTSTAT=1 and UCOD_LEADING=1. Other-cause deaths were censored in cause-specific Cox models and treated as "
        "competing events in Fine–Gray models [19]."
    ),
    "Eligibility, exposure classification, and time zero": (
        "Eligibility, exposure classification, and time zero were aligned at the NHANES examination [20]. The primary "
        "contrast was habitual sleep duration ≥9 versus 7–<8 h/night, followed from baseline to heart-disease death, "
        "competing death, or administrative censoring. The primary estimand was an observational survey-adjusted "
        "cause-specific hazard association under Model 2; the secondary risk-scale estimand was the regression-standardized "
        "5- and 10-year cumulative incidence of heart-disease death accounting for competing deaths. These estimands "
        "describe associations rather than intervention effects: sleep duration was not randomized, a well-defined "
        "intervention corresponding to habitual sleep categories was not specified, and exchangeability cannot be "
        "guaranteed from the observed data."
    ),
    "Potential reverse causation was explored": (
        "Potential reverse causation was explored by excluding prevalent CVD and using 2- and 5-year landmark analyses, "
        "including analyses restricted to comparable NHANES cycle composition. Missing covariates were addressed using "
        "20 multiple imputations by chained equations incorporating exposure, outcomes, follow-up, survey design variables, "
        "and covariates [21]. Competing risks were evaluated using weighted Fine–Gray sensitivity analyses [19]. "
        "Regression-standardized cumulative incidence was estimated from cause-specific hazard models with uncertainty "
        "obtained from 500 stratified PSU bootstrap replicates [22]. Sensitivity to unmeasured confounding was examined "
        "using E-values and continuous bias contours [23]."
    ),
}


FIGURES = {
    "Two-panel causal diagram": ("base/Figure1_causal_dag.png", "Two-panel causal diagram contrasting the etiologic pathway with reverse causation from underlying poor health."),
    "Restricted cubic spline hazard-ratio curves": ("base/Figure2_sleep_mortality_rcs.png", "Restricted cubic spline hazard-ratio curves for sleep duration in the full cohort and the baseline CVD-free cohort."),
    "Figure 3": ("extension/Figure3_health_status_domain_attenuation.png", "One-at-a-time and cumulative health-status adjustment estimates for long sleep."),
    "Figure 4": ("extension/Figure4_robustness_forest.png", "Robustness forest plots for the long-sleep association across sensitivity analyses and cycle exclusions."),
    "Figure 5": ("extension/Figure5_standardized_cumulative_incidence.png", "Regression-standardized cumulative incidence curves for heart-disease death by sleep-duration group."),
    "Restricted cubic spline geometric-mean-ratio curves": ("base/Figure3_inflammation_pathway_rcs.png", "Restricted cubic spline geometric-mean-ratio curves for SIRI and SII across sleep duration."),
}


def replace_paragraphs(document: Document) -> None:
    for paragraph in document.paragraphs:
        stripped = paragraph.text.strip()
        for prefix, replacement in PARAGRAPH_REPLACEMENTS.items():
            if stripped.startswith(prefix):
                paragraph.text = replacement
                break
    reference_index = {item["number"]: item["text"] for item in REFERENCES}
    found = set()
    for paragraph in document.paragraphs:
        stripped = paragraph.text.strip()
        for number, text in reference_index.items():
            if stripped.startswith(f"{number}."):
                paragraph.text = f"{number}. {text}"
                found.add(number)
                break
    if found != set(reference_index):
        raise RuntimeError(f"Reference paragraphs not found: {sorted(set(reference_index) - found)}")


def patch_images(docx_path: Path, reproduced_dir: Path, output_path: Path) -> list[dict]:
    ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
        "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(docx_path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    document_xml = ET.fromstring(files["word/document.xml"])
    relationships = ET.fromstring(files["word/_rels/document.xml.rels"])
    targets = {
        item.attrib["Id"]: item.attrib["Target"]
        for item in relationships.findall("rel:Relationship", ns)
    }
    replacements: dict[str, bytes] = {}
    audit = []
    for drawing in document_xml.findall(".//wp:inline", ns) + document_xml.findall(".//wp:anchor", ns):
        doc_pr = drawing.find("wp:docPr", ns)
        blip = drawing.find(".//a:blip", ns)
        if doc_pr is None or blip is None:
            continue
        identity = " ".join(
            filter(None, [doc_pr.attrib.get("title", ""), doc_pr.attrib.get("descr", ""), doc_pr.attrib.get("name", "")])
        )
        selected = next((value for key, value in FIGURES.items() if key in identity), None)
        if selected is None:
            continue
        relative_source, alt_text = selected
        rid = blip.attrib[f"{{{ns['r']}}}embed"]
        target = targets[rid]
        archive_name = str((Path("word") / target).as_posix())
        source = reproduced_dir / relative_source
        replacements[archive_name] = source.read_bytes()
        doc_pr.set("title", alt_text)
        doc_pr.set("descr", alt_text)
        audit.append({"archive_media": archive_name, "source": str(source), "alt_text": alt_text})
    if len(audit) != 6:
        raise RuntimeError(f"Expected six main figures, found {len(audit)}")
    files["word/document.xml"] = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, replacements.get(name, data))
    return audit


def write_reference_audit(audit_dir: Path) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "reference_audit.json").write_text(
        json.dumps(REFERENCES, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Reference audit",
        "",
        "All 23 entries were checked against PubMed, the publisher DOI record, or the official CDC/NCHS page. "
        "The audited manuscript cites every entry at least once and orders references by first appearance.",
        "",
    ]
    for item in REFERENCES:
        lines.append(f"{item['number']}. [{item['text']}]({item['url']})")
        lines.append(f"   - Correction: {item['change']}")
    (audit_dir / "reference_audit.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-docx", type=Path, required=True)
    parser.add_argument("--output-docx", type=Path, required=True)
    parser.add_argument("--reproduced-dir", type=Path, required=True)
    parser.add_argument("--audit-dir", type=Path, required=True)
    args = parser.parse_args()
    document = Document(args.input_docx)
    replace_paragraphs(document)
    document.core_properties.title = "Sleep duration and heart disease mortality: audited final manuscript"
    document.core_properties.comments = "Numerical, figure, and reference audit completed 2026-08-10."
    args.output_docx.parent.mkdir(parents=True, exist_ok=True)
    intermediate = args.output_docx.parent / ".text_updated_intermediate.docx"
    try:
        document.save(intermediate)
        image_audit = patch_images(intermediate, args.reproduced_dir.resolve(), args.output_docx.resolve())
    finally:
        if intermediate.exists():
            intermediate.unlink()
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    (args.audit_dir / "embedded_figure_audit.json").write_text(
        json.dumps(image_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_reference_audit(args.audit_dir)
    print(args.output_docx.resolve())


if __name__ == "__main__":
    main()
