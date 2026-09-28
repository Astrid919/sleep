"""Compare independently reproduced tabular/figure outputs with final sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    return (rows[0] if rows else []), rows[1:]


def number(value: str) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def compare_tsv(reference: Path, reproduced: Path, tolerance: float = 1e-10) -> dict:
    ref_header, ref_rows = read_tsv(reference)
    new_header, new_rows = read_tsv(reproduced)
    result = {
        "file": reference.name,
        "reference_sha256": digest(reference),
        "reproduced_sha256": digest(reproduced),
        "exact_bytes": reference.read_bytes() == reproduced.read_bytes(),
        "same_header": ref_header == new_header,
        "same_shape": len(ref_rows) == len(new_rows) and all(
            len(a) == len(b) for a, b in zip(ref_rows, new_rows)
        ),
        "max_abs_numeric_difference": 0.0,
        "text_mismatches": 0,
        "numeric_mismatches_over_tolerance": 0,
    }
    if not result["same_header"] or not result["same_shape"]:
        result["status"] = "FAIL"
        return result
    for old_row, new_row in zip(ref_rows, new_rows):
        for old, new in zip(old_row, new_row):
            old_number, new_number = number(old), number(new)
            if old_number is not None and new_number is not None:
                difference = abs(old_number - new_number)
                result["max_abs_numeric_difference"] = max(
                    result["max_abs_numeric_difference"], difference
                )
                if difference > tolerance:
                    result["numeric_mismatches_over_tolerance"] += 1
            elif old != new:
                result["text_mismatches"] += 1
    result["status"] = (
        "PASS"
        if result["numeric_mismatches_over_tolerance"] == 0 and result["text_mismatches"] == 0
        else "FAIL"
    )
    return result


def compare_folder(reference: Path, reproduced: Path) -> list[dict]:
    output = []
    for ref in sorted(reference.glob("*.tsv")):
        candidate = reproduced / ref.name
        if not candidate.exists():
            output.append({"file": ref.name, "status": "MISSING_REPRODUCED"})
        else:
            output.append(compare_tsv(ref, candidate))
    return output


def compare_figures(reference_files: list[Path], reproduced_dirs: list[Path]) -> list[dict]:
    reproduced = {path.name: path for directory in reproduced_dirs for path in directory.glob("*.png")}
    output = []
    for ref in reference_files:
        candidate = reproduced.get(ref.name)
        result = {
            "file": ref.name,
            "reference_sha256": digest(ref),
            "reproduced_sha256": digest(candidate) if candidate else "",
        }
        if not candidate:
            result["status"] = "MISSING_REPRODUCED"
        else:
            old = np.asarray(Image.open(ref).convert("RGBA"), dtype=np.int16)
            new = np.asarray(Image.open(candidate).convert("RGBA"), dtype=np.int16)
            result["same_dimensions"] = old.shape == new.shape
            if old.shape == new.shape:
                difference = np.abs(old - new)
                result["max_channel_difference"] = int(difference.max())
                result["rms_channel_difference"] = float(np.sqrt(np.mean(difference.astype(float) ** 2)))
                result["different_pixel_fraction"] = float(np.mean(np.any(difference != 0, axis=2)))
                result["status"] = "PASS" if result["max_channel_difference"] == 0 else "REVIEW"
            else:
                result["status"] = "FAIL"
        output.append(result)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    package = args.package_dir.resolve()
    reproduced_base = package / "reproduced_outputs" / "base"
    reproduced_extension = package / "reproduced_outputs" / "extension"
    base_results = compare_folder(root / "outputs" / "survey_validated_reanalysis_20260808", reproduced_base)
    extension_results = compare_folder(root / "outputs" / "survey_validated_extension_20260808", reproduced_extension)
    figure_refs = [
        root / "outputs" / "causal_reanalysis_20260808" / "Figure1_causal_dag.png",
        root / "outputs" / "causal_reanalysis_20260808" / "Figure2_sleep_mortality_rcs.png",
        root / "outputs" / "causal_reanalysis_20260808" / "Figure3_inflammation_pathway_rcs.png",
        root / "outputs" / "survey_validated_extension_20260808" / "Figure3_health_status_domain_attenuation.png",
        root / "outputs" / "survey_validated_extension_20260808" / "Figure4_robustness_forest.png",
        root / "outputs" / "survey_validated_extension_20260808" / "Figure5_standardized_cumulative_incidence.png",
        root / "outputs" / "survey_validated_extension_20260808" / "FigureS_bias_contour.png",
        root / "outputs" / "survey_validated_extension_20260808" / "FigureS_PH_time_specific_HR.png",
    ]
    figures = compare_figures(figure_refs, [reproduced_base, reproduced_extension])
    report = {
        "base_tsv": base_results,
        "extension_tsv": extension_results,
        "figures": figures,
        "summary": {
            "base_pass": sum(row["status"] == "PASS" for row in base_results),
            "base_total": len(base_results),
            "extension_pass": sum(row["status"] == "PASS" for row in extension_results),
            "extension_total": len(extension_results),
            "figures_pass": sum(row["status"] == "PASS" for row in figures),
            "figures_total": len(figures),
        },
    }
    audit_dir = package / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    json_path = audit_dir / "reproduction_comparison.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Reproduction comparison", "", json.dumps(report["summary"], ensure_ascii=False), ""]
    for section in ("base_tsv", "extension_tsv", "figures"):
        lines.extend([f"## {section}", ""])
        for row in report[section]:
            detail = ""
            if "max_abs_numeric_difference" in row:
                detail = f"; max numeric difference={row['max_abs_numeric_difference']:.3g}; exact bytes={row['exact_bytes']}"
            lines.append(f"- {row['status']}: {row['file']}{detail}")
        lines.append("")
    (audit_dir / "reproduction_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    print(json_path)
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
