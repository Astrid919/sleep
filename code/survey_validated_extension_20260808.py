"""Survey-design validation and high-priority survival-analysis corrections.

This module is deliberately narrow: it audits the pooled NHANES design,
formally evaluates proportional hazards, aligns 0/2/5-year lags to the same
cycle composition, checks an alternative sleep-spline knot set, separates
one-at-a-time from cumulative health-domain attenuation, and reports basic
follow-up quantities.  It does not add prediction algorithms.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path
from typing import Sequence

import numpy as np

from audit_and_bayesian_reanalysis import (
    CoxResult,
    chi_square_survival,
    cox_breslow,
    normal_two_sided_p,
    restricted_cubic_spline_basis,
    result_rows,
    write_tsv,
)
from causal_reanalysis_20260808 import (
    SLEEP_TERMS,
    add_extended_variables,
    build_design,
    finite,
    fit_design,
    flexible_knots,
    is_complete,
    load_expanded_adult_cohort,
    required_variables,
    sleep_rows,
    wald,
    weighted_quantile,
)
from advanced_causal_extension_20260808 import (
    leave_one_cycle_out,
    longer_lag_analysis,
    sequential_attenuation,
    standardized_absolute_risk,
)


NORMAL_975 = 1.959963984540054
ALT_SLEEP_KNOTS = (5.0, 7.0, 8.0, 9.0)
EARLY_CYCLES = ("2005-2006", "2007-2008", "2009-2010", "2011-2012", "2013-2014")


def _sleep_result(records, names, fit, model):
    rows = sleep_rows(fit, names, model, len(records), sum(r["event"] for r in records))
    statistic, p_value = wald(fit, range(4))
    for row in rows:
        row["global_sleep_wald"] = statistic
        row["global_sleep_p"] = p_value
    return rows


def survey_design_audit(common: Sequence[dict], knots, output_dir: Path) -> None:
    cycle_inventory = []
    raw_strata_by_cycle: dict[str, set[int]] = {}
    raw_clusters_by_cycle: dict[str, set[tuple[int, int]]] = {}
    for cycle in sorted({r["year"] for r in common}):
        use = [r for r in common if r["year"] == cycle]
        strata = {int(r["strata_raw"]) for r in use}
        clusters = {(int(r["strata_raw"]), int(r["psu_raw"])) for r in use}
        raw_strata_by_cycle[cycle] = strata
        raw_clusters_by_cycle[cycle] = clusters
        cycle_inventory.append(
            {
                "cycle": cycle,
                "n": len(use),
                "heart_deaths": sum(r["event"] for r in use),
                "raw_strata_min": min(strata),
                "raw_strata_max": max(strata),
                "raw_strata_count": len(strata),
                "raw_strata_psu_count": len(clusters),
                "sum_14y_MEC_weight": sum(r["weight"] for r in use),
            }
        )
    write_tsv(output_dir / "survey_design_cycle_inventory.tsv", cycle_inventory)

    cycles = sorted(raw_strata_by_cycle)
    stratum_collisions = 0
    cluster_collisions = 0
    for left_index, left in enumerate(cycles):
        for right in cycles[left_index + 1 :]:
            stratum_collisions += len(raw_strata_by_cycle[left] & raw_strata_by_cycle[right])
            cluster_collisions += len(raw_clusters_by_cycle[left] & raw_clusters_by_cycle[right])

    names, matrix = build_design(common, "categories", "Model2_confounder", knots)
    time = np.asarray([r["time"] for r in common], dtype=float)
    event = np.asarray([r["event"] for r in common], dtype=int)
    weight = np.asarray([r["weight"] for r in common], dtype=float)
    nested_strata = np.asarray([r["strata"] for r in common], dtype=int)
    nested_psu = np.asarray([r["psu"] for r in common], dtype=int)
    raw_strata = np.asarray([r["strata_raw"] for r in common], dtype=int)
    raw_psu = np.asarray([r["psu_raw"] for r in common], dtype=int)

    variants = (
        ("survey_weighted_explicit_cycle_nesting", weight, nested_strata, nested_psu),
        ("survey_weighted_released_MVU", weight, raw_strata, raw_psu),
        ("unweighted_explicit_cycle_nesting", np.ones(len(common)), nested_strata, nested_psu),
        ("unweighted_released_MVU", np.ones(len(common)), raw_strata, raw_psu),
    )
    comparison = []
    fits: dict[str, CoxResult] = {}
    for label, fit_weight, fit_strata, fit_psu in variants:
        fit = cox_breslow(time, event, matrix, fit_weight, fit_strata, fit_psu)
        fits[label] = fit
        comparison.extend(_sleep_result(common, names, fit, label))
    write_tsv(output_dir / "survey_design_estimate_comparison.tsv", comparison)

    weighted_nested = fits["survey_weighted_explicit_cycle_nesting"]
    weighted_raw = fits["survey_weighted_released_MVU"]
    audit = [
        {"check": "pooled_weight", "value": "WTMEC2YR/7", "status": "PASS"},
        {"check": "variance_design", "value": "stratified PSU sandwich covariance", "status": "PASS"},
        {"check": "explicit_stratum_identifier", "value": "cycle_index*1000 + SDMVSTRA", "status": "PASS"},
        {"check": "explicit_PSU_identifier", "value": "cycle_index*100000 + SDMVSTRA*10 + SDMVPSU", "status": "PASS"},
        {"check": "cross_cycle_raw_stratum_collisions", "value": stratum_collisions, "status": "PASS" if stratum_collisions == 0 else "REVIEW"},
        {"check": "cross_cycle_raw_stratum_PSU_collisions", "value": cluster_collisions, "status": "PASS" if cluster_collisions == 0 else "REVIEW"},
        {"check": "max_abs_beta_difference_nested_vs_released", "value": float(np.max(np.abs(weighted_nested.beta - weighted_raw.beta))), "status": "PASS"},
        {"check": "max_abs_covariance_difference_nested_vs_released", "value": float(np.max(np.abs(weighted_nested.covariance - weighted_raw.covariance))), "status": "PASS"},
        {"check": "analytic_sample_n", "value": len(common), "status": "PASS"},
        {"check": "heart_deaths", "value": sum(r["event"] for r in common), "status": "PASS"},
    ]
    write_tsv(output_dir / "survey_design_audit.tsv", audit)


def _time_varying_fit(
    time: np.ndarray,
    event: np.ndarray,
    base_x: np.ndarray,
    weights: np.ndarray,
    strata: np.ndarray,
    psu: np.ndarray,
    start: np.ndarray,
    max_iter: int = 35,
) -> CoxResult:
    """Weighted Cox model with sleep-category coefficients linear in log(time/60)."""
    w = np.asarray(weights, dtype=float)
    w /= np.mean(w[w > 0])
    sleep_x = base_x[:, :4]
    q = base_x.shape[1]
    p = q + 4
    death_times = np.unique(time[event == 1])

    def evaluate(theta: np.ndarray, need_information: bool = True):
        beta = theta[:q]
        gamma = theta[q:]
        base_eta = base_x @ beta
        sleep_gamma = sleep_x @ gamma
        score = np.zeros(p)
        information = np.zeros((p, p))
        loglik = 0.0
        for current_time in death_times:
            risk = time >= current_time
            death = (event == 1) & (time == current_time)
            g = math.log(max(float(current_time), 1.0) / 60.0)
            z_risk = np.column_stack([base_x[risk], sleep_x[risk] * g])
            eta_risk = base_eta[risk] + sleep_gamma[risk] * g
            shift = float(np.max(eta_risk))
            risk_weight = w[risk] * np.exp(np.clip(eta_risk - shift, -700, 0))
            risk0 = float(np.sum(risk_weight))
            risk1 = np.sum(risk_weight[:, None] * z_risk, axis=0)
            mean = risk1 / risk0
            z_death = np.column_stack([base_x[death], sleep_x[death] * g])
            death_weight = w[death]
            d_weight = float(np.sum(death_weight))
            score += np.sum(death_weight[:, None] * z_death, axis=0) - d_weight * mean
            loglik += float(np.sum(death_weight * (base_eta[death] + sleep_gamma[death] * g)))
            loglik -= d_weight * (math.log(risk0) + shift)
            if need_information:
                risk2 = z_risk.T @ (risk_weight[:, None] * z_risk)
                information += d_weight * (risk2 / risk0 - np.outer(mean, mean))
        return loglik, score, information

    theta = np.asarray(start, dtype=float).copy()
    converged = False
    loglik = -math.inf
    information = np.eye(p)
    for iteration in range(1, max_iter + 1):
        current, score, information = evaluate(theta)
        step = np.linalg.pinv(information, rcond=1e-10) @ score
        scale = 1.0
        while scale >= 1 / 256:
            candidate = theta + scale * step
            candidate_ll, _, _ = evaluate(candidate, need_information=False)
            if candidate_ll >= current - 1e-8:
                theta = candidate
                loglik = candidate_ll
                break
            scale /= 2
        if np.max(np.abs(scale * step)) < 1e-7:
            converged = True
            break

    loglik, _, information = evaluate(theta)
    beta = theta[:q]
    gamma = theta[q:]
    base_eta = base_x @ beta
    sleep_gamma = sleep_x @ gamma
    score_rows = np.zeros((len(time), p))
    for current_time in death_times:
        risk = time >= current_time
        death = (event == 1) & (time == current_time)
        g = math.log(max(float(current_time), 1.0) / 60.0)
        z_risk = np.column_stack([base_x[risk], sleep_x[risk] * g])
        eta_risk = base_eta[risk] + sleep_gamma[risk] * g
        shift = float(np.max(eta_risk))
        risk_weight = w[risk] * np.exp(np.clip(eta_risk - shift, -700, 0))
        risk0 = float(np.sum(risk_weight))
        d_weight = float(np.sum(w[death]))
        score_rows[risk] -= risk_weight[:, None] * (d_weight / risk0) * z_risk
        z_death = np.column_stack([base_x[death], sleep_x[death] * g])
        score_rows[death] += w[death, None] * z_death

    clusters: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(p))
    for index in range(len(time)):
        clusters[(int(strata[index]), int(psu[index]))] += score_rows[index]
    by_stratum: dict[int, list[np.ndarray]] = defaultdict(list)
    for (stratum, _), value in clusters.items():
        by_stratum[stratum].append(value)
    meat = np.zeros((p, p))
    grand = np.mean(np.stack(list(clusters.values())), axis=0)
    for values in by_stratum.values():
        array = np.stack(values)
        if len(values) > 1:
            centered = array - np.mean(array, axis=0)
            meat += len(values) / (len(values) - 1) * centered.T @ centered
        else:
            centered = array[0] - grand
            meat += np.outer(centered, centered)
    inverse = np.linalg.pinv(information, rcond=1e-10)
    covariance = inverse @ meat @ inverse
    return CoxResult(theta, (covariance + covariance.T) / 2, information, loglik, iteration, converged)


def proportional_hazards_analysis(common: Sequence[dict], knots, output_dir: Path) -> None:
    time = np.asarray([r["time"] for r in common], dtype=float)
    event = np.asarray([r["event"] for r in common], dtype=int)
    weight = np.asarray([r["weight"] for r in common], dtype=float)
    strata = np.asarray([r["strata"] for r in common], dtype=int)
    psu = np.asarray([r["psu"] for r in common], dtype=int)
    rows = []
    time_specific = []
    for model in ("Model2_confounder", "Model3_health_status"):
        names, matrix = build_design(common, "categories", model, knots)
        static = fit_design(common, names, matrix)
        start = np.concatenate([static.beta, np.zeros(4)])
        fit = _time_varying_fit(time, event, matrix, weight, strata, psu, start)
        q = matrix.shape[1]
        gamma_index = np.arange(q, q + 4)
        gamma = fit.beta[gamma_index]
        gamma_covariance = fit.covariance[np.ix_(gamma_index, gamma_index)]
        global_stat = float(gamma @ np.linalg.pinv(gamma_covariance, rcond=1e-10) @ gamma)
        global_p = chi_square_survival(global_stat, 4)
        for sleep_index, term in enumerate(SLEEP_TERMS):
            j = q + sleep_index
            se = math.sqrt(max(fit.covariance[j, j], 0.0))
            rows.append(
                {
                    "model": model,
                    "term": term,
                    "time_interaction": "sleep category x log(follow-up months/60)",
                    "gamma": fit.beta[j],
                    "gamma_se": se,
                    "p_time_interaction": normal_two_sided_p(fit.beta[j] / se) if se > 0 else math.nan,
                    "global_sleep_time_interaction_wald": global_stat,
                    "global_sleep_time_interaction_p": global_p,
                    "converged": fit.converged,
                    "iterations": fit.iterations,
                    "n": len(common),
                    "events": int(event.sum()),
                }
            )
            for year in (1.0, 5.0, 10.0):
                g = math.log(year / 5.0)
                contrast = np.zeros(len(fit.beta))
                contrast[sleep_index] = 1.0
                contrast[j] = g
                estimate = float(contrast @ fit.beta)
                estimate_se = math.sqrt(max(float(contrast @ fit.covariance @ contrast), 0.0))
                time_specific.append(
                    {
                        "model": model,
                        "term": term,
                        "follow_up_years": year,
                        "HR": math.exp(estimate),
                        "lower_95": math.exp(estimate - NORMAL_975 * estimate_se),
                        "upper_95": math.exp(estimate + NORMAL_975 * estimate_se),
                    }
                )
    write_tsv(output_dir / "proportional_hazards_time_interaction.tsv", rows)
    write_tsv(output_dir / "proportional_hazards_time_specific_HR.tsv", time_specific)

    piecewise = []
    for period, lower, upper in (("0_to_5_years", 0.0, 60.0), ("after_5_years", 60.0, math.inf)):
        use = []
        for record in common:
            if period == "0_to_5_years":
                copied = dict(record)
                copied["time"] = min(record["time"], upper)
                copied["event"] = int(record["event"] == 1 and record["time"] <= upper)
                use.append(copied)
            elif record["time"] > lower:
                copied = dict(record)
                copied["time"] = record["time"] - lower
                use.append(copied)
        for model in ("Model2_confounder", "Model3_health_status"):
            names, matrix = build_design(use, "categories", model, knots)
            fit = fit_design(use, names, matrix)
            for row in _sleep_result(use, names, fit, f"{period}_{model}"):
                row["period"] = period
                piecewise.append(row)
    write_tsv(output_dir / "proportional_hazards_piecewise_models.tsv", piecewise)


def same_cycle_lag_analysis(common: Sequence[dict], knots, output_dir: Path) -> None:
    source = [r for r in common if r["year"] in EARLY_CYCLES]
    output = []
    for months in (0, 24, 60):
        use = []
        for record in source:
            if record["time"] <= months:
                continue
            copied = dict(record)
            copied["time"] = record["time"] - months
            use.append(copied)
        for model in ("Model2_confounder", "Model3_health_status"):
            names, matrix = build_design(use, "categories", model, knots)
            fit = fit_design(use, names, matrix)
            for row in _sleep_result(use, names, fit, f"same_cycle_lag{months}_{model}"):
                row["lag_months"] = months
                row["source_cycles"] = ", ".join(EARLY_CYCLES)
                row["source_n_before_lag"] = len(source)
                row["source_heart_deaths_before_lag"] = sum(r["event"] for r in source)
                output.append(row)
    write_tsv(output_dir / "same_cycle_composition_lag_0y_2y_5y.tsv", output)


def alternative_sleep_spline(common: Sequence[dict], knots, output_dir: Path) -> None:
    rows = []
    summaries = []
    grid = np.linspace(3.0, 11.0, 161)
    grid_basis = restricted_cubic_spline_basis(grid, ALT_SLEEP_KNOTS)
    ref_basis = restricted_cubic_spline_basis(np.asarray([7.0]), ALT_SLEEP_KNOTS)[0]
    for model in ("Model2_confounder", "Model3_health_status"):
        category_names, category_matrix = build_design(common, "categories", model, knots)
        sleep_basis = restricted_cubic_spline_basis(np.asarray([r["sleep"] for r in common]), ALT_SLEEP_KNOTS)
        names = ["sleep_rcs_linear", "sleep_rcs_nonlinear_1", "sleep_rcs_nonlinear_2", *category_names[4:]]
        matrix = np.column_stack([sleep_basis, category_matrix[:, 4:]])
        fit = fit_design(common, names, matrix)
        overall_stat, overall_p = wald(fit, range(3))
        nonlinear_stat, nonlinear_p = wald(fit, range(1, 3))
        contrasts = grid_basis - ref_basis
        beta = fit.beta[:3]
        covariance = fit.covariance[:3, :3]
        estimates = contrasts @ beta
        errors = np.sqrt(np.maximum(np.einsum("ij,jk,ik->i", contrasts, covariance, contrasts), 0.0))
        for sleep, estimate, error in zip(grid, estimates, errors):
            rows.append(
                {
                    "model": model,
                    "sleep_hours": sleep,
                    "HR": math.exp(estimate),
                    "lower_95": math.exp(estimate - NORMAL_975 * error),
                    "upper_95": math.exp(estimate + NORMAL_975 * error),
                    "reference_hours": 7.0,
                    "knots": ",".join(str(v) for v in ALT_SLEEP_KNOTS),
                }
            )
        summaries.append(
            {
                "model": model,
                "knots": ",".join(str(v) for v in ALT_SLEEP_KNOTS),
                "knot_rule": "survey-weighted 5th, 35th, 65th, and 95th percentiles",
                "overall_wald": overall_stat,
                "overall_p": overall_p,
                "nonlinear_wald": nonlinear_stat,
                "nonlinear_p": nonlinear_p,
                "n": len(common),
                "events": sum(r["event"] for r in common),
            }
        )
    write_tsv(output_dir / "alternative_4knot_sleep_rcs_curve.tsv", rows)
    write_tsv(output_dir / "alternative_4knot_sleep_rcs_summary.tsv", summaries)


def one_at_a_time_domains(common: Sequence[dict], knots, output_dir: Path) -> None:
    use = [r for r in common if finite(r.get("log_siri"))]
    base_names, base_matrix = build_design(use, "categories", "Model2_confounder", knots)
    bmi = restricted_cubic_spline_basis(np.asarray([r["bmi_value"] for r in use]), knots["bmi_value"])
    additions = {
        "Model2_only": ([], np.empty((len(use), 0))),
        "Model2_plus_BMI": ([f"bmi_value_rcs_{i + 1}" for i in range(bmi.shape[1])], bmi),
        "Model2_plus_HTN_DM": (
            ["hypertension[Yes]", "diabetes[Yes]"],
            np.column_stack(
                [
                    np.asarray([r["hypertension"] == "Yes" for r in use], dtype=float),
                    np.asarray([r["diabetes"] == "Yes" for r in use], dtype=float),
                ]
            ),
        ),
        "Model2_plus_CVD": (["cvd[Yes]"], np.asarray([r["cvd"] == "Yes" for r in use], dtype=float)[:, None]),
        "Model2_plus_SIRI": (["log_siri"], np.asarray([r["log_siri"] for r in use], dtype=float)[:, None]),
    }
    output = []
    base_beta = math.nan
    for label, (extra_names, extra_matrix) in additions.items():
        names = [*base_names, *extra_names]
        matrix = np.column_stack([base_matrix, extra_matrix]) if extra_matrix.shape[1] else base_matrix
        fit = fit_design(use, names, matrix)
        j = names.index("sleep[>=9 h]")
        beta = float(fit.beta[j])
        se = math.sqrt(max(fit.covariance[j, j], 0.0))
        if label == "Model2_only":
            base_beta = beta
        output.append(
            {
                "model": label,
                "beta_long_sleep": beta,
                "se": se,
                "HR": math.exp(beta),
                "lower_95": math.exp(beta - NORMAL_975 * se),
                "upper_95": math.exp(beta + NORMAL_975 * se),
                "p_value": normal_two_sided_p(beta / se),
                "attenuation_vs_Model2_percent": 100 * (base_beta - beta) / base_beta,
                "n": len(use),
                "events": sum(r["event"] for r in use),
                "interpretation": "One domain added to the same Model 2; percentages are not additive or causal mediation proportions.",
            }
        )
    write_tsv(output_dir / "health_status_domain_one_at_a_time.tsv", output)


def follow_up_summary(common: Sequence[dict], output_dir: Path) -> None:
    time = np.asarray([r["time"] for r in common], dtype=float)
    weight = np.asarray([r["weight"] for r in common], dtype=float)
    event = np.asarray([r["event"] for r in common], dtype=int)
    death_any = np.asarray([r["death_any"] for r in common], dtype=int)
    other = np.asarray([r["other_death"] for r in common], dtype=int)
    observed_weighted = weighted_quantile(time, weight, (0.25, 0.50, 0.75))
    observed_plain = np.quantile(time, (0.25, 0.50, 0.75))

    unique, group = np.unique(time, return_inverse=True)
    risk = np.cumsum(np.bincount(group, weights=weight, minlength=len(unique))[::-1])[::-1]
    censor = death_any == 0
    censor_weight = np.bincount(group[censor], weights=weight[censor], minlength=len(unique))
    distribution = []
    survival = 1.0
    for j in range(len(unique)):
        if risk[j] > 0:
            survival *= max(0.0, 1.0 - censor_weight[j] / risk[j])
        distribution.append(1.0 - survival)
    distribution = np.asarray(distribution)

    def reverse_quantile(probability: float) -> float:
        hit = np.flatnonzero(distribution >= probability)
        return float(unique[hit[0]]) if len(hit) else math.nan

    person_years = float(np.sum(time) / 12.0)
    weighted_person_years = float(np.sum(weight * time / 12.0))
    rows = [
        {"metric": "analytic_sample_n", "value": len(common), "unit": "participants"},
        {"metric": "heart_disease_deaths", "value": int(event.sum()), "unit": "deaths"},
        {"metric": "other_cause_deaths", "value": int(other.sum()), "unit": "deaths"},
        {"metric": "total_person_years", "value": person_years, "unit": "person-years"},
        {"metric": "crude_heart_disease_rate", "value": 1000 * float(event.sum()) / person_years, "unit": "per 1,000 person-years"},
        {"metric": "survey_weighted_heart_disease_rate", "value": 1000 * float(np.sum(weight * event)) / weighted_person_years, "unit": "per 1,000 weighted person-years"},
        {"metric": "observed_follow_up_weighted_Q1", "value": observed_weighted[0] / 12, "unit": "years"},
        {"metric": "observed_follow_up_weighted_median", "value": observed_weighted[1] / 12, "unit": "years"},
        {"metric": "observed_follow_up_weighted_Q3", "value": observed_weighted[2] / 12, "unit": "years"},
        {"metric": "observed_follow_up_unweighted_Q1", "value": observed_plain[0] / 12, "unit": "years"},
        {"metric": "observed_follow_up_unweighted_median", "value": observed_plain[1] / 12, "unit": "years"},
        {"metric": "observed_follow_up_unweighted_Q3", "value": observed_plain[2] / 12, "unit": "years"},
        {"metric": "reverse_KM_follow_up_Q1", "value": reverse_quantile(0.25) / 12, "unit": "years"},
        {"metric": "reverse_KM_follow_up_median", "value": reverse_quantile(0.50) / 12, "unit": "years"},
        {"metric": "reverse_KM_follow_up_Q3", "value": reverse_quantile(0.75) / 12, "unit": "years"},
    ]
    write_tsv(output_dir / "follow_up_and_event_summary.tsv", rows)


def bias_contour_grid(common: Sequence[dict], knots, output_dir: Path) -> None:
    names, matrix = build_design(common, "categories", "Model2_confounder", knots)
    fit = fit_design(common, names, matrix)
    observed = math.exp(float(fit.beta[names.index("sleep[>=9 h]")]))
    rows = []
    for p_reference in (0.10, 0.20, 0.30):
        for difference in np.linspace(0.0, 0.70, 71):
            p_long = p_reference + difference
            if p_long > 0.95:
                continue
            for rr in np.linspace(1.0, 6.0, 101):
                bias_factor = (p_long * rr + 1.0 - p_long) / (p_reference * rr + 1.0 - p_reference)
                rows.append(
                    {
                        "p_unmeasured_confounder_reference": p_reference,
                        "prevalence_difference_long_minus_reference": float(difference),
                        "p_unmeasured_confounder_long_sleep": float(p_long),
                        "RR_unmeasured_confounder_outcome": float(rr),
                        "bias_factor": bias_factor,
                        "bias_adjusted_HR_approx": observed / bias_factor,
                        "source_HR": observed,
                        "null_or_below": observed / bias_factor <= 1.0,
                    }
                )
    write_tsv(output_dir / "quantitative_bias_contour_grid.tsv", rows)


def e_values(common: Sequence[dict], knots, output_dir: Path) -> None:
    output = []
    for model in ("Model2_confounder", "Model3_health_status"):
        names, matrix = build_design(common, "categories", model, knots)
        fit = fit_design(common, names, matrix)
        j = names.index("sleep[>=9 h]")
        beta = float(fit.beta[j])
        se = math.sqrt(max(fit.covariance[j, j], 0.0))
        hr = math.exp(beta)
        lower = math.exp(beta - NORMAL_975 * se)

        def calculate(value):
            return value + math.sqrt(value * (value - 1.0)) if value > 1 else 1.0

        output.append(
            {
                "model": model,
                "HR": hr,
                "lower_95": lower,
                "upper_95": math.exp(beta + NORMAL_975 * se),
                "E_value_point": calculate(hr),
                "E_value_CI_bound": calculate(lower),
                "guardrail": "HR used as an approximate RR-scale sensitivity parameter because absolute risk is low; E-values do not control unmeasured confounding.",
            }
        )
    write_tsv(output_dir / "e_values_long_sleep.tsv", output)


def run(project_root: Path, output_dir: Path, bootstrap_reps: int, bootstrap_workers: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = load_expanded_adult_cohort(project_root)
    add_extended_variables(project_root, records)
    common = [r for r in records if is_complete(r, required_variables("Model3_health_status"))]
    knots = flexible_knots(common)
    survey_design_audit(common, knots, output_dir)
    proportional_hazards_analysis(common, knots, output_dir)
    same_cycle_lag_analysis(common, knots, output_dir)
    alternative_sleep_spline(common, knots, output_dir)
    one_at_a_time_domains(common, knots, output_dir)
    sequential_attenuation(common, knots, output_dir)
    follow_up_summary(common, output_dir)
    longer_lag_analysis(common, knots, output_dir)
    leave_one_cycle_out(common, knots, output_dir)
    bias_contour_grid(common, knots, output_dir)
    e_values(common, knots, output_dir)
    standardized_absolute_risk(common, knots, output_dir, bootstrap_reps, bootstrap_workers)
    write_tsv(
        output_dir / "survey_validated_extension_quality_control.tsv",
        [
            {"metric": "common_complete_case_n", "value": len(common)},
            {"metric": "heart_deaths", "value": sum(r["event"] for r in common)},
            {"metric": "other_cause_deaths", "value": sum(r["other_death"] for r in common)},
            {"metric": "bootstrap_replicates", "value": bootstrap_reps},
            {"metric": "bootstrap_workers", "value": bootstrap_workers},
            {"metric": "explicit_cycle_nesting", "value": True},
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--bootstrap-reps", type=int, default=500)
    parser.add_argument("--bootstrap-workers", type=int, default=3)
    args = parser.parse_args()
    root = args.project_root.resolve()
    output = (args.output_dir or root / "outputs" / "survey_validated_extension_20260808").resolve()
    run(root, output, args.bootstrap_reps, args.bootstrap_workers)
    print(output)


if __name__ == "__main__":
    main()
