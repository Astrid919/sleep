"""High-value extensions: longer lag, bias analysis, absolute risks, and robustness."""

from __future__ import annotations

import argparse
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from audit_and_bayesian_reanalysis import (
    _group_moments,
    normal_cdf,
    normal_two_sided_p,
    restricted_cubic_spline_basis,
    write_tsv,
)
from causal_reanalysis_20260808 import (
    add_extended_variables,
    build_design,
    finite,
    fit_design,
    flexible_knots,
    is_complete,
    load_expanded_adult_cohort,
    required_variables,
    result_rows,
    sleep_rows,
)


NORMAL_975 = 1.959963984540054
SLEEP_LEVELS = ("<6 h", "6-<7 h", "7-<8 h", "8-<9 h", ">=9 h")
SLEEP_TERMS = ("sleep[<6 h]", "sleep[6-<7 h]", "sleep[8-<9 h]", "sleep[>=9 h]")


def fit_sleep_models(records: Sequence[dict], knots, label: str) -> list[dict]:
    output: list[dict] = []
    for model in ("Model2_confounder", "Model3_health_status"):
        names, matrix = build_design(records, "categories", model, knots)
        fit = fit_design(records, names, matrix)
        output.extend(sleep_rows(fit, names, f"{label}_{model}", len(records), sum(r["event"] for r in records)))
    return output


def longer_lag_analysis(common: Sequence[dict], knots, output_dir: Path) -> list[dict]:
    all_rows: list[dict] = []
    for months, label in ((24, "lag2y"), (60, "lag5y")):
        lagged = []
        for record in common:
            if record["time"] <= months:
                continue
            copied = dict(record)
            copied["time"] = record["time"] - months
            lagged.append(copied)
        all_rows.extend(fit_sleep_models(lagged, knots, label))
    write_tsv(output_dir / "reverse_causation_lag_2y_5y.tsv", all_rows)
    return all_rows


def staged_design(records: Sequence[dict], knots, stage: str):
    if stage == "A_demographic":
        return build_design(records, "categories", "Model1_demographic", knots)
    names, matrix = build_design(records, "categories", "Model2_confounder", knots)
    if stage == "B_confounder":
        return names, matrix
    bmi = restricted_cubic_spline_basis(np.asarray([r["bmi_value"] for r in records]), knots["bmi_value"])
    names = [*names, *[f"bmi_value_rcs_{i + 1}" for i in range(bmi.shape[1])]]
    matrix = np.column_stack([matrix, bmi])
    if stage == "C_plus_BMI":
        return names, matrix
    htn_dm = np.column_stack([
        np.asarray([r["hypertension"] == "Yes" for r in records], dtype=float),
        np.asarray([r["diabetes"] == "Yes" for r in records], dtype=float),
    ])
    names.extend(["hypertension[Yes]", "diabetes[Yes]"])
    matrix = np.column_stack([matrix, htn_dm])
    if stage == "D_plus_HTN_DM":
        return names, matrix
    cvd = np.asarray([r["cvd"] == "Yes" for r in records], dtype=float)[:, None]
    names.append("cvd[Yes]")
    matrix = np.column_stack([matrix, cvd])
    if stage == "E_plus_CVD":
        return names, matrix
    if stage == "F_plus_SIRI":
        names.append("log_siri")
        matrix = np.column_stack([matrix, np.asarray([r["log_siri"] for r in records])])
        return names, matrix
    raise ValueError(stage)


def sequential_attenuation(common: Sequence[dict], knots, output_dir: Path) -> list[dict]:
    stages = (
        ("A_demographic", "Demographics"),
        ("B_confounder", "+ socioeconomic/lifestyle confounders"),
        ("C_plus_BMI", "+ BMI"),
        ("D_plus_HTN_DM", "+ hypertension/diabetes"),
        ("E_plus_CVD", "+ prevalent CVD"),
        ("F_plus_SIRI", "+ log-SIRI"),
    )
    use = [record for record in common if finite(record.get("log_siri"))]
    output: list[dict] = []
    reference_beta = math.nan
    for stage, description in stages:
        names, matrix = staged_design(use, knots, stage)
        fit = fit_design(use, names, matrix)
        j = names.index("sleep[>=9 h]")
        beta = float(fit.beta[j])
        se = math.sqrt(max(0.0, fit.covariance[j, j]))
        if stage == "B_confounder":
            reference_beta = beta
        attenuation = (
            100.0 * (reference_beta - beta) / reference_beta
            if math.isfinite(reference_beta) and reference_beta != 0
            else math.nan
        )
        output.append(
            {
                "stage": stage,
                "description": description,
                "beta_long_sleep": beta,
                "se": se,
                "HR": math.exp(beta),
                "lower_95": math.exp(beta - NORMAL_975 * se),
                "upper_95": math.exp(beta + NORMAL_975 * se),
                "p_value": normal_two_sided_p(beta / se),
                "attenuation_vs_confounder_percent": attenuation,
                "n": len(use),
                "events": sum(r["event"] for r in use),
                "common_sample_includes_SIRI": True,
            }
        )
    write_tsv(output_dir / "health_status_sequential_attenuation.tsv", output)
    return output


def leave_one_cycle_out(common: Sequence[dict], knots, output_dir: Path) -> list[dict]:
    output: list[dict] = []
    years = sorted({record["year"] for record in common})
    for excluded in years:
        use = [record for record in common if record["year"] != excluded]
        for model in ("Model2_confounder", "Model3_health_status"):
            names, matrix = build_design(use, "categories", model, knots)
            fit = fit_design(use, names, matrix)
            row = result_rows(fit, names, f"leave_out_{excluded}_{model}", len(use), sum(r["event"] for r in use))[names.index("sleep[>=9 h]")]
            row["excluded_cycle"] = excluded
            row["adjustment_model"] = model
            output.append(row)
    write_tsv(output_dir / "leave_one_cycle_out_long_sleep.tsv", output)
    return output


def e_value(estimate: float) -> float:
    if not math.isfinite(estimate) or estimate < 1:
        return math.nan
    return estimate + math.sqrt(estimate * (estimate - 1.0))


def quantitative_bias_analysis(project_root: Path, lag_rows: list[dict], output_dir: Path) -> list[dict]:
    primary = []
    for filename in (
        project_root / "outputs" / "causal_reanalysis_20260808" / "causal_models_sleep_categories.tsv",
        project_root / "outputs" / "causal_reanalysis_20260808" / "multiple_imputation_rubin_pooled.tsv",
    ):
        import csv

        with filename.open(encoding="utf-8-sig", newline="") as handle:
            primary.extend(csv.DictReader(handle, delimiter="\t"))
    primary.extend(lag_rows)
    wanted = {
        "Model2_confounder",
        "Model3_health_status",
        "CVD_free_Model2_confounder",
        "CVD_free_Model3_health_status",
        "MI_Model2_confounder",
        "MI_Model3_health_status",
        "lag2y_Model2_confounder",
        "lag2y_Model3_health_status",
        "lag5y_Model2_confounder",
        "lag5y_Model3_health_status",
    }
    output: list[dict] = []
    for row in primary:
        if row.get("model") not in wanted or row.get("term") != "sleep[>=9 h]":
            continue
        estimate = float(row["HR"])
        lower = float(row["lower_95"])
        output.append(
            {
                "model": row["model"],
                "term": row["term"],
                "HR": estimate,
                "lower_95": lower,
                "upper_95": float(row["upper_95"]),
                "E_value_point": e_value(estimate),
                "E_value_CI_bound": e_value(lower) if lower > 1 else 1.0,
                "interpretation": "Minimum risk-ratio associations with exposure and outcome needed for an unmeasured confounder to explain the point estimate or move the CI to the null, conditional on measured covariates.",
            }
        )
    write_tsv(output_dir / "e_values_long_sleep.tsv", output)

    observed = next(row for row in output if row["model"] == "Model2_confounder")["HR"]
    scenarios: list[dict] = []
    for p_ref in (0.10, 0.20, 0.30):
        for p_long in (0.30, 0.50, 0.70):
            if p_long <= p_ref:
                continue
            for rr_uy in (1.5, 2.0, 3.0, 4.0):
                bias_factor = (p_long * rr_uy + 1 - p_long) / (p_ref * rr_uy + 1 - p_ref)
                corrected = observed / bias_factor
                scenarios.append(
                    {
                        "p_unmeasured_confounder_reference": p_ref,
                        "p_unmeasured_confounder_long_sleep": p_long,
                        "RR_unmeasured_confounder_outcome": rr_uy,
                        "bias_factor": bias_factor,
                        "bias_adjusted_HR_approx": corrected,
                        "moves_point_estimate_to_null": corrected <= 1.0,
                        "source_estimate": observed,
                        "guardrail": "Deterministic binary-confounder scenario; HR treated approximately as a risk-ratio scale sensitivity parameter.",
                    }
                )
    write_tsv(output_dir / "deterministic_bias_factor_scenarios.tsv", scenarios)
    return output


@dataclass
class PointCox:
    beta: np.ndarray
    converged: bool
    iterations: int


_BOOTSTRAP_CONTEXT = None


def cox_point(time, event, x, weights, max_iter=35) -> PointCox:
    w = np.asarray(weights, dtype=float)
    positive_mean = np.mean(w[w > 0])
    w = w / positive_mean
    beta = np.zeros(x.shape[1])
    converged = False
    for iteration in range(1, max_iter + 1):
        eta = x @ beta
        moments = _group_moments(time, event, x, w, eta)
        _, _, _, risk0, risk1, risk2, death_weight, _, death_x, shift = moments
        groups = np.flatnonzero(death_weight > 0)
        means = risk1[groups] / risk0[groups, None]
        score = death_x[groups].sum(axis=0) - (death_weight[groups, None] * means).sum(axis=0)
        information = np.zeros((x.shape[1], x.shape[1]))
        for row, group in enumerate(groups):
            information += death_weight[group] * (risk2[group] / risk0[group] - np.outer(means[row], means[row]))
        step = np.linalg.pinv(information, rcond=1e-10) @ score
        current = float(np.sum(w[event == 1] * eta[event == 1]) - np.sum(death_weight[groups] * (np.log(risk0[groups]) + shift)))
        scale = 1.0
        while scale > 1 / 128:
            candidate = beta + scale * step
            candidate_eta = x @ candidate
            candidate_moments = _group_moments(time, event, x, w, candidate_eta)
            candidate_risk0 = candidate_moments[3]
            candidate_shift = candidate_moments[9]
            candidate_ll = float(np.sum(w[event == 1] * candidate_eta[event == 1]) - np.sum(death_weight[groups] * (np.log(candidate_risk0[groups]) + candidate_shift)))
            if candidate_ll >= current - 1e-8:
                beta = candidate
                break
            scale /= 2
        if np.max(np.abs(scale * step)) < 1e-7:
            converged = True
            break
    return PointCox(beta, converged, iteration)


def baseline_hazard(time, event, x, weights, beta):
    w = np.asarray(weights, dtype=float)
    w = w / np.mean(w[w > 0])
    eta = x @ beta
    moments = _group_moments(time, event, x, w, eta)
    unique, _, _, risk0, _, _, death_weight, _, _, shift = moments
    increment = np.zeros(len(unique))
    use = death_weight > 0
    increment[use] = death_weight[use] / (risk0[use] * math.exp(shift))
    return unique, increment


def forced_design(base_matrix: np.ndarray, sleep_level: str) -> np.ndarray:
    matrix = base_matrix.copy()
    matrix[:, :4] = 0.0
    mapping = {"<6 h": 0, "6-<7 h": 1, "8-<9 h": 2, ">=9 h": 3}
    if sleep_level in mapping:
        matrix[:, mapping[sleep_level]] = 1.0
    return matrix


def standardized_cif_curves(time, x, weights, beta1, beta2, base1, base2, max_month=120):
    unique = np.unique(time)
    d1_by_time = dict(zip(unique, base1))
    d2_by_time = dict(zip(unique, base2))
    event_times = [value for value in unique if value <= max_month]
    grid = np.arange(0, max_month + 1, dtype=int)
    output: dict[str, np.ndarray] = {}
    population_weight = np.asarray(weights, dtype=float)
    population_weight = population_weight / population_weight.sum()
    for level in SLEEP_LEVELS:
        x_cf = forced_design(x, level)
        risk1 = np.exp(np.clip(x_cf @ beta1, -30, 30))
        risk2 = np.exp(np.clip(x_cf @ beta2, -30, 30))
        survival = np.ones(len(time))
        cif = np.zeros(len(time))
        curve = np.zeros(len(grid))
        time_index = 0
        for month in grid:
            while time_index < len(event_times) and event_times[time_index] <= month:
                current = event_times[time_index]
                d_h1 = risk1 * d1_by_time[current]
                d_h2 = risk2 * d2_by_time[current]
                cif += survival * d_h1
                survival *= np.exp(-(d_h1 + d_h2))
                time_index += 1
            curve[month] = float(np.sum(population_weight * cif))
        output[level] = curve
    return grid, output


def bootstrap_multipliers(records: Sequence[dict], rng: np.random.Generator) -> np.ndarray:
    multiplier = np.zeros(len(records))
    strata_map: dict[int, list[int]] = {}
    for record in records:
        strata_map.setdefault(int(record["strata"]), [])
        if int(record["psu"]) not in strata_map[int(record["strata"])]:
            strata_map[int(record["strata"])].append(int(record["psu"]))
    sampled_counts: dict[tuple[int, int], int] = {}
    for stratum, psus in strata_map.items():
        sampled = rng.choice(psus, size=len(psus), replace=True)
        for psu in psus:
            sampled_counts[(stratum, psu)] = int(np.sum(sampled == psu))
    for i, record in enumerate(records):
        multiplier[i] = sampled_counts[(int(record["strata"]), int(record["psu"]))]
    return multiplier


def _initialize_absolute_risk_worker(time, event1, event2, x, weights):
    global _BOOTSTRAP_CONTEXT
    _BOOTSTRAP_CONTEXT = (time, event1, event2, x, weights)


def _absolute_risk_bootstrap_worker(task):
    replicate, multipliers = task
    time, event1, event2, x, weights = _BOOTSTRAP_CONTEXT
    replicate_weights = weights * multipliers
    fit1 = cox_point(time, event1, x, replicate_weights)
    fit2 = cox_point(time, event2, x, replicate_weights)
    _, replicate_d1 = baseline_hazard(time, event1, x, replicate_weights, fit1.beta)
    _, replicate_d2 = baseline_hazard(time, event2, x, replicate_weights, fit2.beta)
    _, replicate_curves = standardized_cif_curves(
        time, x, replicate_weights, fit1.beta, fit2.beta, replicate_d1, replicate_d2
    )
    diagnostic = {
        "replicate": replicate,
        "heart_model_converged": fit1.converged,
        "other_model_converged": fit2.converged,
        "heart_iterations": fit1.iterations,
        "other_iterations": fit2.iterations,
    }
    return replicate_curves, diagnostic


def standardized_absolute_risk(
    common: Sequence[dict], knots, output_dir: Path, bootstrap_reps: int, bootstrap_workers: int = 1
):
    names, x = build_design(common, "categories", "Model2_confounder", knots)
    time = np.asarray([record["time"] for record in common], dtype=float)
    event1 = np.asarray([record["event"] for record in common], dtype=int)
    event2 = np.asarray([record["other_death"] for record in common], dtype=int)
    weights = np.asarray([record["weight"] for record in common], dtype=float)
    point1 = cox_point(time, event1, x, weights)
    point2 = cox_point(time, event2, x, weights)
    unique1, d1 = baseline_hazard(time, event1, x, weights, point1.beta)
    unique2, d2 = baseline_hazard(time, event2, x, weights, point2.beta)
    assert np.array_equal(unique1, unique2)
    grid, point_curves = standardized_cif_curves(time, x, weights, point1.beta, point2.beta, d1, d2)

    rng = np.random.default_rng(2026080817)
    bootstrap = {level: [] for level in SLEEP_LEVELS}
    diagnostics = []
    tasks = ((replicate, bootstrap_multipliers(common, rng)) for replicate in range(1, bootstrap_reps + 1))
    if bootstrap_workers > 1:
        executor = ProcessPoolExecutor(
            max_workers=bootstrap_workers,
            initializer=_initialize_absolute_risk_worker,
            initargs=(time, event1, event2, x, weights),
        )
        results = executor.map(_absolute_risk_bootstrap_worker, tasks, chunksize=1)
    else:
        _initialize_absolute_risk_worker(time, event1, event2, x, weights)
        executor = None
        results = map(_absolute_risk_bootstrap_worker, tasks)
    try:
        for replicate_curves, diagnostic in results:
            for level in SLEEP_LEVELS:
                bootstrap[level].append(replicate_curves[level])
            diagnostics.append(diagnostic)
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    curve_rows: list[dict] = []
    arrays = {level: np.stack(values) for level, values in bootstrap.items()}
    for level in SLEEP_LEVELS:
        lower = np.quantile(arrays[level], 0.025, axis=0)
        upper = np.quantile(arrays[level], 0.975, axis=0)
        for month in grid:
            curve_rows.append(
                {
                    "model": "Model2_confounder_standardized_CIF",
                    "sleep_group": level,
                    "month": int(month),
                    "years": month / 12.0,
                    "risk": point_curves[level][month],
                    "lower_95_bootstrap": lower[month],
                    "upper_95_bootstrap": upper[month],
                    "bootstrap_replicates": bootstrap_reps,
                }
            )
    write_tsv(output_dir / "standardized_cumulative_incidence_curve.tsv", curve_rows)
    write_tsv(output_dir / "standardized_cif_bootstrap_diagnostics.tsv", diagnostics)

    horizon_rows: list[dict] = []
    contrast_rows: list[dict] = []
    reference = "7-<8 h"
    for month in (60, 120):
        for level in SLEEP_LEVELS:
            values = arrays[level][:, month]
            horizon_rows.append(
                {
                    "sleep_group": level,
                    "horizon_years": month / 12,
                    "standardized_risk": point_curves[level][month],
                    "risk_percent": 100 * point_curves[level][month],
                    "lower_95_bootstrap": float(np.quantile(values, 0.025)),
                    "upper_95_bootstrap": float(np.quantile(values, 0.975)),
                    "n": len(common),
                    "heart_deaths": int(event1.sum()),
                    "other_deaths": int(event2.sum()),
                }
            )
            if level == reference:
                continue
            rd_point = point_curves[level][month] - point_curves[reference][month]
            rd_boot = arrays[level][:, month] - arrays[reference][:, month]
            rr_point = point_curves[level][month] / point_curves[reference][month]
            rr_boot = arrays[level][:, month] / arrays[reference][:, month]
            contrast_rows.append(
                {
                    "sleep_group": level,
                    "reference": reference,
                    "horizon_years": month / 12,
                    "risk_difference": rd_point,
                    "risk_difference_percentage_points": 100 * rd_point,
                    "rd_lower_95_bootstrap": float(np.quantile(rd_boot, 0.025)),
                    "rd_upper_95_bootstrap": float(np.quantile(rd_boot, 0.975)),
                    "risk_ratio": rr_point,
                    "rr_lower_95_bootstrap": float(np.quantile(rr_boot, 0.025)),
                    "rr_upper_95_bootstrap": float(np.quantile(rr_boot, 0.975)),
                    "bootstrap_replicates": bootstrap_reps,
                }
            )
    write_tsv(output_dir / "standardized_absolute_risk_horizons.tsv", horizon_rows)
    write_tsv(output_dir / "standardized_absolute_risk_contrasts.tsv", contrast_rows)
    return curve_rows, horizon_rows, contrast_rows


def bayesian_thresholds(project_root: Path, output_dir: Path):
    import csv

    path = project_root / "outputs" / "causal_reanalysis_20260808" / "bayesian_shrinkage_sensitivity.tsv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        source = list(csv.DictReader(handle, delimiter="\t"))
    output = []
    for row in source:
        mean = float(row["posterior_beta"])
        sd = float(row["posterior_sd"])
        output.append(
            {
                **row,
                "probability_HR_gt_1_50": normal_cdf((mean - math.log(1.50)) / sd),
            }
        )
    write_tsv(output_dir / "bayesian_threshold_probabilities.tsv", output)


def target_estimand_table(output_dir: Path):
    rows = [
        {"component": "Eligibility", "specification": "NHANES 2005-2018 adults aged >=20 years with eligible linked mortality follow-up and reported sleep duration 3-11 h/night."},
        {"component": "Exposure strategies", "specification": "Habitual sleep >=9 h/night versus 7-<8 h/night; other categories and continuous spline are secondary contrasts."},
        {"component": "Time zero", "specification": "NHANES mobile examination center visit."},
        {"component": "Outcome", "specification": "Death from diseases of heart (MORTSTAT=1 and UCOD_LEADING=1)."},
        {"component": "Follow-up", "specification": "From examination to heart-disease death, competing death, or administrative censoring."},
        {"component": "Primary estimand", "specification": "Survey-adjusted cause-specific hazard association under the designated baseline confounder model."},
        {"component": "Risk-scale estimand", "specification": "Regression-standardized 5-year and 10-year cumulative incidence in the presence of competing deaths, and the absolute risk difference."},
        {"component": "Interpretation guardrail", "specification": "Not an intervention effect: sleep is not randomized or necessarily well defined as a manipulable treatment, is measured once, and residual confounding and reverse causation remain possible."},
    ]
    write_tsv(output_dir / "target_estimand_framework.tsv", rows)


def run(project_root: Path, output_dir: Path, bootstrap_reps: int, bootstrap_workers: int = 1):
    output_dir.mkdir(parents=True, exist_ok=True)
    records = load_expanded_adult_cohort(project_root)
    add_extended_variables(project_root, records)
    common = [record for record in records if is_complete(record, required_variables("Model3_health_status"))]
    knots = flexible_knots(common)
    lag_rows = longer_lag_analysis(common, knots, output_dir)
    sequential_attenuation(common, knots, output_dir)
    leave_one_cycle_out(common, knots, output_dir)
    quantitative_bias_analysis(project_root, lag_rows, output_dir)
    standardized_absolute_risk(common, knots, output_dir, bootstrap_reps, bootstrap_workers)
    bayesian_thresholds(project_root, output_dir)
    target_estimand_table(output_dir)
    write_tsv(
        output_dir / "advanced_extension_quality_control.tsv",
        [
            {"metric": "common_complete_case_n", "value": len(common)},
            {"metric": "common_complete_case_heart_deaths", "value": sum(r["event"] for r in common)},
            {"metric": "common_complete_case_other_deaths", "value": sum(r["other_death"] for r in common)},
            {"metric": "bootstrap_replicates", "value": bootstrap_reps},
        ],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--bootstrap-reps", type=int, default=100)
    parser.add_argument("--bootstrap-workers", type=int, default=1)
    args = parser.parse_args()
    root = args.project_root.resolve()
    output = (args.output_dir or root / "outputs" / "causal_extension_20260808").resolve()
    run(root, output, args.bootstrap_reps, args.bootstrap_workers)
    print(output)


if __name__ == "__main__":
    main()
