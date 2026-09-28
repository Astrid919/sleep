from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "outputs" / "final_submission_package_20260810"
SOURCE_OUTPUT = ROOT / "outputs" / "manuscript_survey_validated_20260808"


def copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    manuscript_copies = {
        SOURCE_OUTPUT / "Manuscript_survey_validated_20260808.docx": PACKAGE / "manuscript" / "Manuscript_source_designated_20260808.docx",
        SOURCE_OUTPUT / "Supplementary_methods_results_survey_validated_20260808.docx": PACKAGE / "manuscript" / "Supplementary_methods_results_20260808.docx",
        SOURCE_OUTPUT / "Supplementary_methods_results_survey_validated_20260808.pdf": PACKAGE / "manuscript" / "Supplementary_methods_results_20260808.pdf",
    }

    code_names = [
        "audit_and_bayesian_reanalysis.py",
        "causal_reanalysis_20260808.py",
        "advanced_causal_extension_20260808.py",
        "survey_validated_extension_20260808.py",
        "create_causal_figures_20260808.py",
        "create_advanced_causal_figures_20260808.py",
        "create_survey_validated_figures_20260808.py",
        "revise_manuscript_causal_20260808.py",
        "revise_manuscript_causal_extension_20260808.py",
        "revise_manuscript_survey_validated_20260808.py",
        "validate_causal_revision_20260808.py",
        "validate_causal_extension_20260808.py",
        "validate_survey_validated_revision_20260808.py",
        "audit_final_manuscript_20260810.py",
        "regenerate_final_figures_20260810.py",
        "compare_reproduced_outputs_20260810.py",
        "finalize_manuscript_references_20260810.py",
        "validate_final_package_20260810.py",
        "create_cover_letter_highlights_20260810.py",
        "build_final_submission_package_20260810.py",
    ]

    data_copies = {
        ROOT / "工程文件" / "Heart" / "DM_FilterRowNa_py_Plus_20" / "DM_FilterRowNa_py.tsv": PACKAGE / "data" / "analysis_input" / "DM_FilterRowNa_py.tsv",
        ROOT / "工程文件" / "Heart" / "ImportNHANESData2_Py_189" / "NHANES_Data.tsv": PACKAGE / "data" / "analysis_input" / "NHANES_Data.tsv",
        ROOT / "数据处理" / "external_raw_2015_2018" / "SMQ_I.xpt": PACKAGE / "data" / "external_raw_2015_2018" / "SMQ_I.xpt",
        ROOT / "数据处理" / "external_raw_2015_2018" / "DEMO_J.xpt": PACKAGE / "data" / "external_raw_2015_2018" / "DEMO_J.xpt",
    }

    figure_copies = {
        PACKAGE / "reproduced_outputs" / "base" / "Figure1_causal_dag.png": PACKAGE / "figures" / "main" / "Figure1_causal_dag.png",
        PACKAGE / "reproduced_outputs" / "base" / "Figure2_sleep_mortality_rcs.png": PACKAGE / "figures" / "main" / "Figure2_sleep_mortality_rcs.png",
        PACKAGE / "reproduced_outputs" / "extension" / "Figure3_health_status_domain_attenuation.png": PACKAGE / "figures" / "main" / "Figure3_health_status_domain_attenuation.png",
        PACKAGE / "reproduced_outputs" / "extension" / "Figure4_robustness_forest.png": PACKAGE / "figures" / "main" / "Figure4_robustness_forest.png",
        PACKAGE / "reproduced_outputs" / "extension" / "Figure5_standardized_cumulative_incidence.png": PACKAGE / "figures" / "main" / "Figure5_standardized_cumulative_incidence.png",
        PACKAGE / "reproduced_outputs" / "base" / "Figure3_inflammation_pathway_rcs.png": PACKAGE / "figures" / "main" / "Figure6_inflammation_pathway_rcs.png",
        PACKAGE / "reproduced_outputs" / "extension" / "FigureS_bias_contour.png": PACKAGE / "figures" / "supplementary" / "FigureS1_bias_contour.png",
        PACKAGE / "reproduced_outputs" / "extension" / "FigureS_PH_time_specific_HR.png": PACKAGE / "figures" / "supplementary" / "FigureS2_PH_time_specific_HR.png",
    }

    audit_copies = {
        SOURCE_OUTPUT / "analysis_decision_log_20260808.md": PACKAGE / "audit" / "analysis_decision_log_20260808.md",
    }

    for mapping in (manuscript_copies, data_copies, figure_copies, audit_copies):
        for source, destination in mapping.items():
            copy_file(source, destination)

    for name in code_names:
        copy_file(ROOT / "数据处理" / name, PACKAGE / "code" / name)

    table_sources = {
        "Table 1": ["reproduced_outputs/table1_source/table1_expanded_survey_weighted.tsv"],
        "Table 2": ["reproduced_outputs/base/causal_models_sleep_categories_summary.tsv"],
        "Table 3": [
            "reproduced_outputs/extension/reverse_causation_lag_2y_5y.tsv",
            "reproduced_outputs/base/multiple_imputation_summary.tsv",
            "reproduced_outputs/base/competing_risk_fine_gray_summary.tsv",
        ],
        "Table 4": [
            "reproduced_outputs/extension/standardized_absolute_risk_horizons.tsv",
            "reproduced_outputs/extension/standardized_absolute_risk_contrasts.tsv",
            "reproduced_outputs/extension/standardized_cif_bootstrap_diagnostics.tsv",
        ],
        "Supplementary tables": [
            "reproduced_outputs/base",
            "reproduced_outputs/extension",
            "reproduced_outputs/table1_source",
        ],
    }
    (PACKAGE / "tables").mkdir(parents=True, exist_ok=True)
    (PACKAGE / "tables" / "manuscript_table_sources.json").write_text(
        json.dumps(table_sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    distributions = {}
    for name in ["numpy", "pandas", "scipy", "statsmodels", "python-docx", "Pillow", "matplotlib"]:
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            distributions[name] = None
    environment = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": distributions,
    }
    (PACKAGE / "audit" / "runtime_environment.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest_path = PACKAGE / "audit" / "file_manifest_sha256.tsv"
    rows = ["relative_path\tsize_bytes\tsha256"]
    for path in sorted(p for p in PACKAGE.rglob("*") if p.is_file() and p != manifest_path):
        rows.append(f"{path.relative_to(PACKAGE).as_posix()}\t{path.stat().st_size}\t{sha256(path)}")
    manifest_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Package complete: {PACKAGE}")
    print(f"Manifest entries: {len(rows) - 1}")


if __name__ == "__main__":
    main()
