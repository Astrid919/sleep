"""Causal-structure reanalysis of sleep duration and heart-disease mortality.

This analysis separates baseline confounders from cardiometabolic/health-status
markers, treats prevalent CVD exclusion as a central reverse-causation check,
uses flexible continuous adjustment, performs stochastic multiple imputation
with Rubin pooling, and adds competing-risk and exploratory inflammatory-
pathway analyses.  It intentionally does not use penalized selection to define
the etiologic adjustment set.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from audit_and_bayesian_reanalysis import (
    CoxResult,
    bayesian_normal_update,
    chi_square_survival,
    cox_breslow,
    format_p,
    is_missing,
    load_expanded_adult_cohort,
    normal_two_sided_p,
    parse_number,
    restricted_cubic_spline_basis,
    result_rows,
    write_tsv,
)


SLEEP_TERMS = ("sleep[<6 h]", "sleep[6-<7 h]", "sleep[8-<9 h]", "sleep[>=9 h]")
SLEEP_KNOTS = (5.0, 6.0, 7.0, 8.0, 9.0)
NORMAL_975 = 1.959963984540054


def finite(value) -> bool:
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def add_extended_variables(project_root: Path, records: list[dict]) -> None:
    """Attach inflammation and competing-event fields from the upstream node."""
    path = project_root / "工程文件" / "Heart" / "DM_FilterRowNa_py_Plus_20" / "DM_FilterRowNa_py.tsv"
    wanted = {record["key"] for record in records}
    mapped: dict[tuple[str, int], dict] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            seqn = parse_number(row.get("SEQN"))
            if not math.isfinite(seqn):
                continue
            key = (row.get("year", ""), int(seqn))
            if key not in wanted or key in mapped:
                continue
            mortstat = parse_number(row.get("MORTSTAT"))
            cause = parse_number(row.get("UCOD_LEADING"))
            mapped[key] = {
                "siri": parse_number(row.get("SIRI")),
                "sii": parse_number(row.get("SII")),
                "death_any": int(mortstat == 1),
                "other_death": int(mortstat == 1 and cause != 1),
            }
    for record in records:
        extra = mapped.get(record["key"], {})
        record.update(extra)
        for mediator in ("siri", "sii"):
            value = record.get(mediator, math.nan)
            record[f"log_{mediator}"] = math.log(value) if finite(value) and value > 0 else math.nan


def weighted_quantile(values: np.ndarray, weights: np.ndarray, probabilities: Sequence[float]) -> np.ndarray:
    order = np.argsort(values)
    x = values[order]
    w = weights[order]
    cumulative = np.cumsum(w) - 0.5 * w
    cumulative /= np.sum(w)
    return np.interp(np.asarray(probabilities, dtype=float), cumulative, x)


def flexible_knots(records: Sequence[dict]) -> dict[str, tuple[float, ...]]:
    output: dict[str, tuple[float, ...]] = {}
    for name in ("age", "pir_value", "bmi_value"):
        use = [record for record in records if finite(record.get(name))]
        values = np.asarray([record[name] for record in use], dtype=float)
        weights = np.asarray([record["weight"] for record in use], dtype=float)
        knots = weighted_quantile(values, weights, (0.05, 0.35, 0.65, 0.95))
        output[name] = tuple(float(value) for value in knots)
    return output


def required_variables(model: str, include_cvd: bool = True) -> list[str]:
    variables = ["age", "sex", "race"]
    if model in {"Model2_confounder", "Model3_health_status"}:
        variables += ["education", "pir_value", "marital", "smoking"]
    if model == "Model3_health_status":
        variables += ["bmi_value", "hypertension", "diabetes"]
        if include_cvd:
            variables.append("cvd")
    return variables


def is_complete(record: dict, variables: Iterable[str]) -> bool:
    return all(finite(record.get(name)) for name in variables)


def _append_binary(columns: list[np.ndarray], names: list[str], records: Sequence[dict], variable: str, level: str) -> None:
    columns.append(np.asarray([record[variable] == level for record in records], dtype=float)[:, None])
    names.append(f"{variable}[{level}]")


def _append_rcs(
    columns: list[np.ndarray],
    names: list[str],
    records: Sequence[dict],
    variable: str,
    knots: Sequence[float],
) -> None:
    basis = restricted_cubic_spline_basis(
        np.asarray([record[variable] for record in records], dtype=float), knots
    )
    columns.append(basis)
    names.extend([f"{variable}_rcs_{i + 1}" for i in range(basis.shape[1])])


def build_design(
    records: Sequence[dict],
    exposure: str,
    model: str,
    knots: dict[str, tuple[float, ...]],
    include_cvd: bool = True,
) -> tuple[list[str], np.ndarray]:
    columns: list[np.ndarray] = []
    names: list[str] = []
    if exposure == "categories":
        for level, label in zip(("<6 h", "6-<7 h", "8-<9 h", ">=9 h"), SLEEP_TERMS):
            columns.append(np.asarray([record["sleep_group"] == level for record in records], dtype=float)[:, None])
            names.append(label)
    elif exposure == "rcs":
        basis = restricted_cubic_spline_basis(np.asarray([record["sleep"] for record in records]), SLEEP_KNOTS)
        columns.append(basis)
        names.extend(["sleep_rcs_linear", *[f"sleep_rcs_nonlinear_{i}" for i in range(1, basis.shape[1])]])
    else:
        raise ValueError(exposure)

    _append_rcs(columns, names, records, "age", knots["age"])
    _append_binary(columns, names, records, "sex", "Female")
    for level in ("Mexican American", "Other Hispanic", "Non-Hispanic Black", "Other race"):
        _append_binary(columns, names, records, "race", level)

    if model in {"Model2_confounder", "Model3_health_status"}:
        for level in ("<High school", "High school/GED"):
            _append_binary(columns, names, records, "education", level)
        _append_rcs(columns, names, records, "pir_value", knots["pir_value"])
        _append_binary(columns, names, records, "marital", "Not married/partner")
        _append_binary(columns, names, records, "smoking", "Ever smoker")

    if model == "Model3_health_status":
        _append_rcs(columns, names, records, "bmi_value", knots["bmi_value"])
        _append_binary(columns, names, records, "hypertension", "Yes")
        _append_binary(columns, names, records, "diabetes", "Yes")
        if include_cvd:
            _append_binary(columns, names, records, "cvd", "Yes")
    return names, np.concatenate(columns, axis=1)


def fit_design(records: Sequence[dict], names: Sequence[str], matrix: np.ndarray, event_name: str = "event") -> CoxResult:
    return cox_breslow(
        np.asarray([record["time"] for record in records], dtype=float),
        np.asarray([record[event_name] for record in records], dtype=int),
        matrix,
        np.asarray([record["weight"] for record in records], dtype=float),
        np.asarray([record["strata"] for record in records], dtype=int),
        np.asarray([record["psu"] for record in records], dtype=int),
    )


def fit_named_model(
    records: Sequence[dict], exposure: str, model: str, knots: dict[str, tuple[float, ...]], include_cvd: bool = True
) -> tuple[list[str], np.ndarray, CoxResult]:
    names, matrix = build_design(records, exposure, model, knots, include_cvd)
    return names, matrix, fit_design(records, names, matrix)


def wald(result: CoxResult, indices: Sequence[int]) -> tuple[float, float]:
    index = np.asarray(list(indices), dtype=int)
    beta = result.beta[index]
    covariance = result.covariance[np.ix_(index, index)]
    statistic = float(beta @ np.linalg.pinv(covariance, rcond=1e-10) @ beta)
    return statistic, chi_square_survival(statistic, len(index))


def sleep_rows(result: CoxResult, names: Sequence[str], model: str, n: int, events: int) -> list[dict]:
    rows = result_rows(result, names, model, n, events)
    return [row for row in rows if row["term"].startswith("sleep[")]


def rcs_curve(
    result: CoxResult,
    model: str,
    n: int,
    events: int,
    reference: float = 7.0,
) -> tuple[list[dict], dict]:
    spline_df = len(SLEEP_KNOTS) - 1
    overall_stat, overall_p = wald(result, range(spline_df))
    nonlinear_stat, nonlinear_p = wald(result, range(1, spline_df))
    grid = np.linspace(3.0, 11.0, 161)
    basis = restricted_cubic_spline_basis(grid, SLEEP_KNOTS)
    ref_basis = restricted_cubic_spline_basis(np.asarray([reference]), SLEEP_KNOTS)[0]
    contrasts = basis - ref_basis
    beta = result.beta[:spline_df]
    covariance = result.covariance[:spline_df, :spline_df]
    log_hr = contrasts @ beta
    variance = np.einsum("ij,jk,ik->i", contrasts, covariance, contrasts)
    se = np.sqrt(np.maximum(variance, 0))
    rows = [
        {
            "model": model,
            "sleep_hours": float(value),
            "HR": math.exp(effect),
            "lower_95": math.exp(effect - NORMAL_975 * error),
            "upper_95": math.exp(effect + NORMAL_975 * error),
            "reference_hours": reference,
        }
        for value, effect, error in zip(grid, log_hr, se)
    ]
    summary = {
        "model": model,
        "knots": ",".join(str(value) for value in SLEEP_KNOTS),
        "reference_hours": reference,
        "n": n,
        "events": events,
        "overall_wald": overall_stat,
        "overall_p": overall_p,
        "overall_P": format_p(overall_p),
        "nonlinear_wald": nonlinear_stat,
        "nonlinear_p": nonlinear_p,
        "nonlinear_P": format_p(nonlinear_p),
        "curve_nadir_hours": float(grid[int(np.argmin(log_hr))]),
        "converged": result.converged,
    }
    return rows, summary


@dataclass
class LinearResult:
    beta: np.ndarray
    covariance: np.ndarray


def survey_linear(
    y: np.ndarray,
    x: np.ndarray,
    weights: np.ndarray,
    strata: np.ndarray,
    psu: np.ndarray,
) -> LinearResult:
    w = np.asarray(weights, dtype=float)
    w /= np.mean(w)
    bread = x.T @ (w[:, None] * x)
    inverse = np.linalg.pinv(bread, rcond=1e-10)
    beta = inverse @ (x.T @ (w * y))
    residual = y - x @ beta
    score_rows = w[:, None] * x * residual[:, None]
    clusters: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(x.shape[1]))
    for i in range(len(y)):
        clusters[(int(strata[i]), int(psu[i]))] += score_rows[i]
    by_stratum: dict[int, list[np.ndarray]] = defaultdict(list)
    for (stratum, _), value in clusters.items():
        by_stratum[stratum].append(value)
    meat = np.zeros_like(bread)
    grand = np.mean(np.stack(list(clusters.values())), axis=0)
    for values in by_stratum.values():
        array = np.stack(values)
        if len(values) > 1:
            centered = array - np.mean(array, axis=0)
            meat += len(values) / (len(values) - 1) * centered.T @ centered
        else:
            centered = array[0] - grand
            meat += np.outer(centered, centered)
    covariance = inverse @ meat @ inverse
    return LinearResult(beta, (covariance + covariance.T) / 2)


def linear_wald(result: LinearResult, indices: Sequence[int]) -> tuple[float, float]:
    index = np.asarray(list(indices), dtype=int)
    beta = result.beta[index]
    covariance = result.covariance[np.ix_(index, index)]
    statistic = float(beta @ np.linalg.pinv(covariance, rcond=1e-10) @ beta)
    return statistic, chi_square_survival(statistic, len(index))


def inflammation_pathway(
    records: Sequence[dict], knots: dict[str, tuple[float, ...]], output_dir: Path
) -> None:
    association_rows: list[dict] = []
    rcs_rows: list[dict] = []
    rcs_summaries: list[dict] = []
    outcome_rows: list[dict] = []
    required = required_variables("Model2_confounder")
    for mediator in ("siri", "sii"):
        log_name = f"log_{mediator}"
        use = [record for record in records if is_complete(record, [*required, log_name])]
        weights = np.asarray([record["weight"] for record in use])
        strata = np.asarray([record["strata"] for record in use])
        psu = np.asarray([record["psu"] for record in use])
        y = np.asarray([record[log_name] for record in use])

        names_cat, matrix_cat = build_design(use, "categories", "Model2_confounder", knots)
        names_cat = ["intercept", *names_cat]
        matrix_cat = np.column_stack([np.ones(len(use)), matrix_cat])
        linear_cat = survey_linear(y, matrix_cat, weights, strata, psu)
        global_stat, global_p = linear_wald(linear_cat, range(1, 5))
        for j in range(1, 5):
            beta = linear_cat.beta[j]
            se = math.sqrt(max(0.0, linear_cat.covariance[j, j]))
            p_value = normal_two_sided_p(beta / se) if se > 0 else math.nan
            association_rows.append(
                {
                    "mediator": mediator.upper(),
                    "term": names_cat[j],
                    "geometric_mean_ratio": math.exp(beta),
                    "lower_95": math.exp(beta - NORMAL_975 * se),
                    "upper_95": math.exp(beta + NORMAL_975 * se),
                    "p_value": p_value,
                    "global_sleep_p": global_p,
                    "n": len(use),
                    "heart_deaths": sum(record["event"] for record in use),
                }
            )

        names_rcs, matrix_rcs = build_design(use, "rcs", "Model2_confounder", knots)
        names_rcs = ["intercept", *names_rcs]
        matrix_rcs = np.column_stack([np.ones(len(use)), matrix_rcs])
        linear_rcs = survey_linear(y, matrix_rcs, weights, strata, psu)
        overall_stat, overall_p = linear_wald(linear_rcs, range(1, 5))
        nonlinear_stat, nonlinear_p = linear_wald(linear_rcs, range(2, 5))
        grid = np.linspace(3.0, 11.0, 161)
        basis = restricted_cubic_spline_basis(grid, SLEEP_KNOTS)
        ref = restricted_cubic_spline_basis(np.asarray([7.0]), SLEEP_KNOTS)[0]
        contrast = basis - ref
        beta = linear_rcs.beta[1:5]
        covariance = linear_rcs.covariance[1:5, 1:5]
        effect = contrast @ beta
        variance = np.einsum("ij,jk,ik->i", contrast, covariance, contrast)
        error = np.sqrt(np.maximum(variance, 0))
        for value, estimate, se in zip(grid, effect, error):
            rcs_rows.append(
                {
                    "mediator": mediator.upper(),
                    "sleep_hours": float(value),
                    "geometric_mean_ratio": math.exp(estimate),
                    "lower_95": math.exp(estimate - NORMAL_975 * se),
                    "upper_95": math.exp(estimate + NORMAL_975 * se),
                    "reference_hours": 7.0,
                }
            )
        rcs_summaries.append(
            {
                "mediator": mediator.upper(),
                "n": len(use),
                "heart_deaths": sum(record["event"] for record in use),
                "overall_p": overall_p,
                "overall_P": format_p(overall_p),
                "nonlinear_p": nonlinear_p,
                "nonlinear_P": format_p(nonlinear_p),
            }
        )

        cox_names, cox_matrix = build_design(use, "categories", "Model2_confounder", knots)
        cox_without = fit_design(use, cox_names, cox_matrix)
        with_matrix = np.column_stack([cox_matrix, y])
        with_names = [*cox_names, f"log_{mediator}"]
        cox_with = fit_design(use, with_names, with_matrix)
        for label, fit, fit_names in (
            ("without_inflammation_marker", cox_without, cox_names),
            ("with_inflammation_marker", cox_with, with_names),
        ):
            for row in sleep_rows(fit, fit_names, f"{mediator}_{label}", len(use), sum(r["event"] for r in use)):
                row["mediator"] = mediator.upper()
                row["adjustment"] = label
                outcome_rows.append(row)
        j = len(with_names) - 1
        beta_m = cox_with.beta[j] * math.log(2.0)
        se_m = math.sqrt(max(0.0, cox_with.covariance[j, j])) * math.log(2.0)
        outcome_rows.append(
            {
                "model": f"{mediator}_with_inflammation_marker",
                "term": f"{mediator.upper()} per doubling",
                "beta": beta_m,
                "se": se_m,
                "HR": math.exp(beta_m),
                "lower_95": math.exp(beta_m - NORMAL_975 * se_m),
                "upper_95": math.exp(beta_m + NORMAL_975 * se_m),
                "p_value": normal_two_sided_p(beta_m / se_m) if se_m > 0 else math.nan,
                "n": len(use),
                "events": sum(r["event"] for r in use),
                "mediator": mediator.upper(),
                "adjustment": "with_inflammation_marker",
            }
        )
    write_tsv(output_dir / "inflammation_sleep_categories.tsv", association_rows)
    write_tsv(output_dir / "inflammation_sleep_rcs_curve.tsv", rcs_rows)
    write_tsv(output_dir / "inflammation_sleep_rcs_summary.tsv", rcs_summaries)
    write_tsv(output_dir / "inflammation_outcome_pathway.tsv", outcome_rows)


def _initial_fill(records: Sequence[dict], rng: np.random.Generator) -> list[dict]:
    output = [dict(record) for record in records]
    variables = ("pir_value", "bmi_value", "education", "smoking", "marital", "hypertension", "diabetes", "cvd")
    for variable in variables:
        observed = [record for record in output if finite(record.get(variable))]
        values = np.asarray([record[variable] for record in observed], dtype=object)
        probability = np.asarray([record["weight"] for record in observed], dtype=float)
        probability /= probability.sum()
        for record in output:
            if not finite(record.get(variable)):
                record[variable] = rng.choice(values, p=probability)
    return output


def _predictor_matrix(records: Sequence[dict], target: str) -> np.ndarray:
    columns = [np.ones(len(records))]
    continuous = {
        "age": (50.0, 18.0),
        "sleep": (7.0, 1.5),
        "pir_value": (2.5, 1.6),
        "bmi_value": (28.0, 7.0),
        "time": (100.0, 55.0),
        "nelson_aalen_heart": (0.02, 0.03),
    }
    for variable, (center, scale) in continuous.items():
        if variable != target:
            columns.append((np.asarray([record[variable] for record in records], dtype=float) - center) / scale)
    columns.append(np.asarray([record["event"] for record in records], dtype=float))
    columns.append(np.asarray([record.get("other_death", 0) for record in records], dtype=float))
    # Include sampling-design information in the imputation model.  Cycle is
    # represented below by indicators; log-weight, released stratum, and PSU
    # enter here as additional design predictors.
    log_weight = np.log(np.maximum(np.asarray([record["weight"] for record in records], dtype=float), 1e-12))
    columns.append((log_weight - np.mean(log_weight)) / max(np.std(log_weight), 1e-8))
    raw_strata = np.asarray([record.get("strata_raw", record["strata"]) for record in records], dtype=float)
    columns.append((raw_strata - np.mean(raw_strata)) / max(np.std(raw_strata), 1e-8))
    raw_psu = np.asarray([record.get("psu_raw", record["psu"]) for record in records], dtype=float)
    for level in sorted(set(raw_psu))[1:]:
        columns.append(np.asarray(raw_psu == level, dtype=float))
    for variable, levels in (
        ("sex", ("Female",)),
        ("race", ("Mexican American", "Other Hispanic", "Non-Hispanic Black", "Other race")),
        ("education", ("<High school", "High school/GED")),
        ("smoking", ("Ever smoker",)),
        ("marital", ("Not married/partner",)),
        ("hypertension", ("Yes",)),
        ("diabetes", ("Yes",)),
        ("cvd", ("Yes",)),
    ):
        if variable == target:
            continue
        for level in levels:
            columns.append(np.asarray([record[variable] == level for record in records], dtype=float))
    years = sorted({record["year"] for record in records})
    for year in years[1:]:
        columns.append(np.asarray([record["year"] == year for record in records], dtype=float))
    return np.column_stack(columns)


def _sample_regression_beta(
    x: np.ndarray, y: np.ndarray, w: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, float]:
    w = w / np.mean(w)
    information = x.T @ (w[:, None] * x)
    ridge = np.eye(x.shape[1]) * 1e-6
    inverse = np.linalg.pinv(information + ridge, rcond=1e-10)
    beta = inverse @ (x.T @ (w * y))
    residual = y - x @ beta
    df = max(10, len(y) - x.shape[1])
    sigma2 = float(np.sum(w * residual**2) / max(1, len(y) - x.shape[1]))
    sigma2_draw = sigma2 * df / rng.chisquare(df)
    draw = rng.multivariate_normal(beta, sigma2_draw * inverse, check_valid="ignore")
    return draw, sigma2_draw


def _pmm_update(
    filled: list[dict], original: Sequence[dict], target: str, rng: np.random.Generator, donors: int = 7
) -> None:
    missing = np.asarray([not finite(record.get(target)) for record in original])
    if not np.any(missing):
        return
    observed = ~missing
    x = _predictor_matrix(filled, target)
    sample_value = next(record[target] for record in filled if finite(record.get(target)))
    if isinstance(sample_value, str):
        # Predictive mean matching can be used as a donor model for a small
        # amount of nominal missingness; the fitted scores only order donors,
        # while the imputed value itself is always an observed category.
        levels = sorted({record[target] for record in filled if finite(record.get(target))})
        level_code = {level: index for index, level in enumerate(levels)}
        y = np.asarray([level_code[record[target]] for record in filled], dtype=float)
    else:
        y = np.asarray([record[target] for record in filled], dtype=float)
    w = np.asarray([record["weight"] for record in filled], dtype=float)
    beta, _ = _sample_regression_beta(x[observed], y[observed], w[observed], rng)
    prediction = x @ beta
    observed_index = np.flatnonzero(observed)
    order = np.argsort(prediction[observed])
    sorted_index = observed_index[order]
    sorted_prediction = prediction[sorted_index]
    for index in np.flatnonzero(missing):
        position = int(np.searchsorted(sorted_prediction, prediction[index]))
        left = max(0, position - donors)
        right = min(len(sorted_index), position + donors + 1)
        candidates = sorted_index[left:right]
        distance = np.abs(prediction[candidates] - prediction[index])
        nearest = candidates[np.argsort(distance)[:donors]]
        probability = w[nearest] / np.sum(w[nearest])
        filled[index][target] = filled[int(rng.choice(nearest, p=probability))][target]


def _logistic_update(
    filled: list[dict], original: Sequence[dict], target: str, rng: np.random.Generator
) -> None:
    missing = np.asarray([not finite(record.get(target)) for record in original])
    if not np.any(missing):
        return
    observed = ~missing
    x = _predictor_matrix(filled, target)
    y = np.asarray([record[target] == "Yes" for record in filled], dtype=float)
    w = np.asarray([record["weight"] for record in filled], dtype=float)
    w /= np.mean(w[observed])
    beta = np.zeros(x.shape[1])
    prior = np.eye(x.shape[1]) / 2.5**2
    prior[0, 0] = 1e-6
    for _ in range(30):
        eta = np.clip(x[observed] @ beta, -25, 25)
        probability = 1.0 / (1.0 + np.exp(-eta))
        variance = np.maximum(probability * (1.0 - probability), 1e-6)
        score = x[observed].T @ (w[observed] * (y[observed] - probability)) - prior @ beta
        information = x[observed].T @ ((w[observed] * variance)[:, None] * x[observed]) + prior
        step = np.linalg.pinv(information, rcond=1e-10) @ score
        beta += step
        if np.max(np.abs(step)) < 1e-6:
            break
    covariance = np.linalg.pinv(information, rcond=1e-10)
    draw = rng.multivariate_normal(beta, covariance, check_valid="ignore")
    probability_missing = 1.0 / (1.0 + np.exp(-np.clip(x[missing] @ draw, -25, 25)))
    for index, probability in zip(np.flatnonzero(missing), probability_missing):
        filled[index][target] = "Yes" if rng.random() < probability else "No"


def _multinomial_update(
    filled: list[dict], original: Sequence[dict], target: str, rng: np.random.Generator
) -> None:
    """Weighted Bayesian multinomial-logit draw for unordered/ordinal categories.

    Education has three collapsed categories.  A multinomial model avoids
    treating their integer labels as a continuous outcome, while still drawing
    model parameters so between-imputation uncertainty is propagated.
    """
    missing = np.asarray([not finite(record.get(target)) for record in original])
    if not np.any(missing):
        return
    observed = ~missing
    x = _predictor_matrix(filled, target)
    levels = [">High school", "High school/GED", "<High school"]
    nonreference = levels[:-1]
    y = np.column_stack(
        [np.asarray([record[target] == level for record in filled], dtype=float) for level in nonreference]
    )
    w = np.asarray([record["weight"] for record in filled], dtype=float)
    w /= np.mean(w[observed])
    p = x.shape[1]
    k = len(nonreference)
    beta = np.zeros((k, p))
    prior = np.eye(k * p) / 2.5**2
    for block in range(k):
        prior[block * p, block * p] = 1e-6
    x_obs = x[observed]
    w_obs = w[observed]
    y_obs = y[observed]
    information = np.eye(k * p)
    for _ in range(35):
        eta = np.clip(x_obs @ beta.T, -25, 25)
        exp_eta = np.exp(eta)
        denominator = 1.0 + np.sum(exp_eta, axis=1, keepdims=True)
        probability = exp_eta / denominator
        beta_vector = beta.reshape(-1)
        score_blocks = [
            x_obs.T @ (w_obs * (y_obs[:, block] - probability[:, block]))
            for block in range(k)
        ]
        score = np.concatenate(score_blocks) - prior @ beta_vector
        information = prior.copy()
        for left in range(k):
            for right in range(k):
                variance = probability[:, left] * (
                    (1.0 if left == right else 0.0) - probability[:, right]
                )
                block_information = x_obs.T @ ((w_obs * variance)[:, None] * x_obs)
                information[left * p : (left + 1) * p, right * p : (right + 1) * p] += block_information
        step = np.linalg.pinv(information, rcond=1e-10) @ score
        beta += step.reshape(k, p)
        if np.max(np.abs(step)) < 1e-6:
            break
    covariance = np.linalg.pinv(information, rcond=1e-10)
    draw = rng.multivariate_normal(beta.reshape(-1), covariance, check_valid="ignore").reshape(k, p)
    eta_missing = np.clip(x[missing] @ draw.T, -25, 25)
    exp_eta = np.exp(eta_missing)
    probability = np.column_stack([exp_eta, np.ones(len(eta_missing))])
    probability /= np.sum(probability, axis=1, keepdims=True)
    for index, row_probability in zip(np.flatnonzero(missing), probability):
        filled[index][target] = levels[int(rng.choice(len(levels), p=row_probability))]


def impute_dataset(records: Sequence[dict], seed: int, iterations: int = 5) -> list[dict]:
    rng = np.random.default_rng(seed)
    filled = _initial_fill(records, rng)
    for _ in range(iterations):
        _pmm_update(filled, records, "pir_value", rng)
        _pmm_update(filled, records, "bmi_value", rng)
        _multinomial_update(filled, records, "education", rng)
        for variable in ("smoking", "marital", "hypertension", "diabetes", "cvd"):
            if variable in {"smoking", "marital"}:
                # Recode the two-level variables temporarily for the common logistic updater.
                yes_level = "Ever smoker" if variable == "smoking" else "Not married/partner"
                for current in filled:
                    current[f"_{variable}_saved"] = current[variable]
                    current[variable] = "Yes" if current[variable] == yes_level else "No"
                original_binary = []
                for current in records:
                    copied = dict(current)
                    copied[variable] = None if not finite(current.get(variable)) else (
                        "Yes" if current[variable] == yes_level else "No"
                    )
                    original_binary.append(copied)
                _logistic_update(filled, original_binary, variable, rng)
                for current in filled:
                    current[variable] = yes_level if current[variable] == "Yes" else (
                        "Never smoker" if variable == "smoking" else "Married/partner"
                    )
                    current.pop(f"_{variable}_saved", None)
            else:
                _logistic_update(filled, records, variable, rng)
    return filled


def rubin_pool(results: Sequence[CoxResult], names: Sequence[str], model: str, n: int, events: int) -> tuple[list[dict], dict]:
    betas = np.stack([result.beta for result in results])
    covariances = np.stack([result.covariance for result in results])
    m = len(results)
    qbar = np.mean(betas, axis=0)
    ubar = np.mean(covariances, axis=0)
    between = np.cov(betas, rowvar=False, ddof=1)
    total = ubar + (1.0 + 1.0 / m) * between
    rows = []
    for j, name in enumerate(names):
        if not name.startswith("sleep["):
            continue
        se = math.sqrt(max(total[j, j], 0))
        p_value = normal_two_sided_p(qbar[j] / se) if se > 0 else math.nan
        fmi = (1.0 + 1.0 / m) * between[j, j] / total[j, j] if total[j, j] > 0 else math.nan
        rows.append(
            {
                "model": model,
                "term": name,
                "beta": qbar[j],
                "se": se,
                "HR": math.exp(qbar[j]),
                "lower_95": math.exp(qbar[j] - NORMAL_975 * se),
                "upper_95": math.exp(qbar[j] + NORMAL_975 * se),
                "p_value_normal_approx": p_value,
                "P": format_p(p_value),
                "fraction_missing_information": fmi,
                "imputations": m,
                "n": n,
                "events": events,
            }
        )
    sleep_index = [i for i, name in enumerate(names) if name.startswith("sleep[")]
    beta_sleep = qbar[sleep_index]
    covariance_sleep = total[np.ix_(sleep_index, sleep_index)]
    statistic = float(beta_sleep @ np.linalg.pinv(covariance_sleep, rcond=1e-10) @ beta_sleep)
    summary = {
        "model": model,
        "imputations": m,
        "n": n,
        "events": events,
        "global_sleep_wald": statistic,
        "global_sleep_p": chi_square_survival(statistic, len(sleep_index)),
    }
    return rows, summary


def multiple_imputation_analysis(
    records: Sequence[dict], knots: dict[str, tuple[float, ...]], output_dir: Path, m: int
) -> None:
    # White/Royston-compatible survival information: the heart-disease event
    # indicator plus the Nelson-Aalen cumulative hazard evaluated at each
    # participant's follow-up time.  Other-cause death is also retained.
    time = np.asarray([record["time"] for record in records], dtype=float)
    event = np.asarray([record["event"] for record in records], dtype=int)
    weight = np.asarray([record["weight"] for record in records], dtype=float)
    unique_time, group = np.unique(time, return_inverse=True)
    risk_weight = np.cumsum(np.bincount(group, weights=weight, minlength=len(unique_time))[::-1])[::-1]
    death_weight = np.bincount(group[event == 1], weights=weight[event == 1], minlength=len(unique_time))
    cumulative_hazard = np.cumsum(np.divide(death_weight, risk_weight, out=np.zeros_like(death_weight), where=risk_weight > 0))
    for record, value in zip(records, cumulative_hazard[group]):
        record["nelson_aalen_heart"] = float(value)
    results: dict[str, list[CoxResult]] = {"Model2_confounder": [], "Model3_health_status": []}
    per_imputation: list[dict] = []
    names_by_model: dict[str, list[str]] = {}
    for imputation in range(1, m + 1):
        filled = impute_dataset(records, seed=20260808 + 1009 * imputation)
        for model in results:
            names, matrix = build_design(filled, "categories", model, knots)
            fit = fit_design(filled, names, matrix)
            results[model].append(fit)
            names_by_model[model] = names
            for row in sleep_rows(fit, names, f"MI_{model}", len(filled), sum(r["event"] for r in filled)):
                row["imputation"] = imputation
                per_imputation.append(row)
    pooled_rows: list[dict] = []
    summary_rows: list[dict] = []
    for model, fits in results.items():
        rows, summary = rubin_pool(fits, names_by_model[model], f"MI_{model}", len(records), sum(r["event"] for r in records))
        pooled_rows.extend(rows)
        summary_rows.append(summary)
    write_tsv(output_dir / "multiple_imputation_individual_estimates.tsv", per_imputation)
    write_tsv(output_dir / "multiple_imputation_rubin_pooled.tsv", pooled_rows)
    write_tsv(output_dir / "multiple_imputation_summary.tsv", summary_rows)
    write_tsv(
        output_dir / "multiple_imputation_specification.tsv",
        [
            {"component": "Imputations", "specification": m},
            {"component": "Continuous variables", "specification": "Weighted Bayesian linear draws with predictive mean matching (PIR and BMI)."},
            {"component": "Education", "specification": "Weighted Bayesian multinomial logistic draws for the three collapsed categories."},
            {"component": "Binary variables", "specification": "Weighted Bayesian logistic draws."},
            {"component": "Survival information", "specification": "Heart-disease event indicator, other-cause-death indicator, follow-up time, and weighted Nelson-Aalen cumulative heart-disease hazard."},
            {"component": "Survey information", "specification": "MEC 14-year weight, released masked stratum and PSU, and NHANES cycle indicators included as predictors; completed datasets analyzed with cycle-nested stratified-PSU covariance."},
        ],
    )


def censoring_survival(time: np.ndarray, death_any: np.ndarray, weights: np.ndarray) -> np.ndarray:
    unique, group = np.unique(time, return_inverse=True)
    risk = np.cumsum(np.bincount(group, weights=weights, minlength=len(unique))[::-1])[::-1]
    censored = death_any == 0
    censor_weight = np.bincount(group[censored], weights=weights[censored], minlength=len(unique))
    survival_before = np.ones(len(unique))
    current = 1.0
    for j in range(len(unique)):
        survival_before[j] = current
        if risk[j] > 0:
            current *= max(1e-10, 1.0 - censor_weight[j] / risk[j])
    return survival_before[group]


def fine_gray(
    time: np.ndarray,
    event1: np.ndarray,
    competing: np.ndarray,
    death_any: np.ndarray,
    x: np.ndarray,
    weights: np.ndarray,
    strata: np.ndarray,
    psu: np.ndarray,
    max_iter: int = 40,
) -> CoxResult:
    """Weighted Fine-Gray fit with a stratified-PSU sandwich approximation."""
    w = np.asarray(weights, dtype=float)
    w /= np.mean(w)
    unique, group = np.unique(time, return_inverse=True)
    k = len(unique)
    p = x.shape[1]
    g_subject = censoring_survival(time, death_any, w)
    g_group = np.ones(k)
    for j in range(k):
        g_group[j] = g_subject[np.flatnonzero(group == j)[0]]
    death_weight = np.bincount(group[event1 == 1], weights=w[event1 == 1], minlength=k)
    death_x = np.column_stack([
        np.bincount(group[event1 == 1], weights=w[event1 == 1] * x[event1 == 1, j], minlength=k)
        for j in range(p)
    ])

    def moments(beta: np.ndarray):
        eta = x @ beta
        shift = float(np.max(eta))
        risk_weight = w * np.exp(np.clip(eta - shift, -700, 0))
        all0 = np.cumsum(np.bincount(group, weights=risk_weight, minlength=k)[::-1])[::-1]
        all1_group = np.column_stack([
            np.bincount(group, weights=risk_weight * x[:, j], minlength=k) for j in range(p)
        ])
        all1 = np.cumsum(all1_group[::-1], axis=0)[::-1]
        all2_group = np.zeros((k, p, p))
        for j in range(p):
            for ell in range(j, p):
                value = np.bincount(group, weights=risk_weight * x[:, j] * x[:, ell], minlength=k)
                all2_group[:, j, ell] = value
                all2_group[:, ell, j] = value
        all2 = np.cumsum(all2_group[::-1], axis=0)[::-1]
        comp_scale = np.zeros(len(time))
        comp_scale[competing == 1] = risk_weight[competing == 1] / np.maximum(g_subject[competing == 1], 1e-10)
        comp0_group = np.bincount(group, weights=comp_scale, minlength=k)
        comp1_group = np.column_stack([
            np.bincount(group, weights=comp_scale * x[:, j], minlength=k) for j in range(p)
        ])
        comp2_group = np.zeros((k, p, p))
        for j in range(p):
            for ell in range(j, p):
                value = np.bincount(group, weights=comp_scale * x[:, j] * x[:, ell], minlength=k)
                comp2_group[:, j, ell] = value
                comp2_group[:, ell, j] = value
        prefix0 = np.concatenate([[0.0], np.cumsum(comp0_group)[:-1]])
        prefix1 = np.vstack([np.zeros((1, p)), np.cumsum(comp1_group, axis=0)[:-1]])
        prefix2 = np.concatenate([np.zeros((1, p, p)), np.cumsum(comp2_group, axis=0)[:-1]], axis=0)
        risk0 = all0 + g_group * prefix0
        risk1 = all1 + g_group[:, None] * prefix1
        risk2 = all2 + g_group[:, None, None] * prefix2
        return eta, shift, risk_weight, risk0, risk1, risk2

    beta = np.zeros(p)
    loglik = -math.inf
    converged = False
    information = np.eye(p)
    for iteration in range(1, max_iter + 1):
        eta, shift, _, risk0, risk1, risk2 = moments(beta)
        event_groups = np.flatnonzero(death_weight > 0)
        means = risk1[event_groups] / risk0[event_groups, None]
        score = death_x[event_groups].sum(axis=0) - (death_weight[event_groups, None] * means).sum(axis=0)
        information = np.zeros((p, p))
        for row, j in enumerate(event_groups):
            information += death_weight[j] * (risk2[j] / risk0[j] - np.outer(means[row], means[row]))
        current = float(np.sum(w[event1 == 1] * eta[event1 == 1]) - np.sum(death_weight[event_groups] * (np.log(risk0[event_groups]) + shift)))
        step = np.linalg.pinv(information, rcond=1e-10) @ score
        scale = 1.0
        while scale > 1 / 128:
            candidate = beta + scale * step
            c_eta, c_shift, _, c_risk0, _, _ = moments(candidate)
            candidate_ll = float(np.sum(w[event1 == 1] * c_eta[event1 == 1]) - np.sum(death_weight[event_groups] * (np.log(c_risk0[event_groups]) + c_shift)))
            if candidate_ll >= current - 1e-8:
                beta = candidate
                loglik = candidate_ll
                break
            scale /= 2
        if np.max(np.abs(scale * step)) < 1e-7:
            converged = True
            break

    eta, shift, risk_weight, risk0, risk1, risk2 = moments(beta)
    event_groups = np.flatnonzero(death_weight > 0)
    xbar = np.zeros((k, p))
    xbar[event_groups] = risk1[event_groups] / risk0[event_groups, None]
    information = np.zeros((p, p))
    for j in event_groups:
        information += death_weight[j] * (risk2[j] / risk0[j] - np.outer(xbar[j], xbar[j]))
    a0 = np.zeros(k)
    a1 = np.zeros((k, p))
    a0[event_groups] = death_weight[event_groups] / risk0[event_groups]
    a1[event_groups] = a0[event_groups, None] * xbar[event_groups]
    cumulative0 = np.cumsum(a0)
    cumulative1 = np.cumsum(a1, axis=0)
    score_rows = -risk_weight[:, None] * (x * cumulative0[group, None] - cumulative1[group])
    weighted0 = a0 * g_group
    weighted1 = a1 * g_group[:, None]
    suffix0 = np.cumsum(weighted0[::-1])[::-1]
    suffix1 = np.cumsum(weighted1[::-1], axis=0)[::-1]
    for i in np.flatnonzero(competing == 1):
        next_group = group[i] + 1
        if next_group < k:
            factor = risk_weight[i] / max(g_subject[i], 1e-10)
            score_rows[i] -= factor * (x[i] * suffix0[next_group] - suffix1[next_group])
    for i in np.flatnonzero(event1 == 1):
        score_rows[i] += w[i] * (x[i] - xbar[group[i]])
    clusters: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(p))
    for i in range(len(time)):
        clusters[(int(strata[i]), int(psu[i]))] += score_rows[i]
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
    return CoxResult(beta, (covariance + covariance.T) / 2, information, loglik, iteration, converged)


def competing_risk_analysis(
    records: Sequence[dict], knots: dict[str, tuple[float, ...]], output_dir: Path
) -> None:
    rows: list[dict] = []
    summary: list[dict] = []
    for model in ("Model2_confounder", "Model3_health_status"):
        names, matrix = build_design(records, "categories", model, knots)
        fit = fine_gray(
            np.asarray([record["time"] for record in records]),
            np.asarray([record["event"] for record in records]),
            np.asarray([record["other_death"] for record in records]),
            np.asarray([record["death_any"] for record in records]),
            matrix,
            np.asarray([record["weight"] for record in records]),
            np.asarray([record["strata"] for record in records]),
            np.asarray([record["psu"] for record in records]),
        )
        model_name = f"FineGray_{model}"
        model_rows = sleep_rows(fit, names, model_name, len(records), sum(r["event"] for r in records))
        for row in model_rows:
            row["estimate_type"] = "subdistribution_hazard_ratio"
            row["competing_deaths"] = sum(r["other_death"] for r in records)
        rows.extend(model_rows)
        statistic, p_value = wald(fit, range(4))
        summary.append(
            {
                "model": model_name,
                "n": len(records),
                "heart_deaths": sum(r["event"] for r in records),
                "competing_deaths": sum(r["other_death"] for r in records),
                "global_sleep_wald": statistic,
                "global_sleep_p": p_value,
                "global_sleep_P": format_p(p_value),
                "converged": fit.converged,
                "iterations": fit.iterations,
            }
        )
    write_tsv(output_dir / "competing_risk_fine_gray.tsv", rows)
    write_tsv(output_dir / "competing_risk_fine_gray_summary.tsv", summary)


def run(project_root: Path, output_dir: Path, imputations: int, stages: set[str] | None = None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stages = stages or {"main", "inflammation", "mi", "competing", "bayes"}
    records = load_expanded_adult_cohort(project_root)
    add_extended_variables(project_root, records)

    model3_variables = required_variables("Model3_health_status")
    common = [record for record in records if is_complete(record, model3_variables)]
    knots = flexible_knots(common)
    knot_rows = [
        {"variable": variable, "percentiles": "5,35,65,95", "knots": ",".join(f"{value:.4g}" for value in values)}
        for variable, values in knots.items()
    ]
    write_tsv(output_dir / "flexible_covariate_knots.tsv", knot_rows)

    category_rows: list[dict] = []
    category_summaries: list[dict] = []
    rcs_rows: list[dict] = []
    rcs_summaries: list[dict] = []
    for model in (("Model1_demographic", "Model2_confounder", "Model3_health_status") if "main" in stages else ()):
        names, _, fit = fit_named_model(common, "categories", model, knots)
        category_rows.extend(sleep_rows(fit, names, model, len(common), sum(r["event"] for r in common)))
        statistic, p_value = wald(fit, range(4))
        category_summaries.append(
            {"cohort": "full_common_sample", "model": model, "n": len(common), "events": sum(r["event"] for r in common), "global_sleep_wald": statistic, "global_sleep_p": p_value, "global_sleep_P": format_p(p_value)}
        )
    for model in (("Model2_confounder", "Model3_health_status") if "main" in stages else ()):
        _, _, fit = fit_named_model(common, "rcs", model, knots)
        curve, summary = rcs_curve(fit, f"full_{model}_RCS", len(common), sum(r["event"] for r in common))
        rcs_rows.extend(curve)
        rcs_summaries.append(summary)

    cvd_free_required = required_variables("Model3_health_status", include_cvd=False)
    cvd_free = [record for record in records if record.get("cvd") == "No" and is_complete(record, cvd_free_required)]
    for model in (("Model2_confounder", "Model3_health_status") if "main" in stages else ()):
        names, matrix = build_design(cvd_free, "categories", model, knots, include_cvd=False)
        fit = fit_design(cvd_free, names, matrix)
        label = f"CVD_free_{model}"
        category_rows.extend(sleep_rows(fit, names, label, len(cvd_free), sum(r["event"] for r in cvd_free)))
        statistic, p_value = wald(fit, range(4))
        category_summaries.append(
            {"cohort": "baseline_CVD_free", "model": label, "n": len(cvd_free), "events": sum(r["event"] for r in cvd_free), "global_sleep_wald": statistic, "global_sleep_p": p_value, "global_sleep_P": format_p(p_value)}
        )
        names_rcs, matrix_rcs = build_design(cvd_free, "rcs", model, knots, include_cvd=False)
        fit_rcs = fit_design(cvd_free, names_rcs, matrix_rcs)
        curve, summary = rcs_curve(fit_rcs, f"CVD_free_{model}_RCS", len(cvd_free), sum(r["event"] for r in cvd_free))
        rcs_rows.extend(curve)
        rcs_summaries.append(summary)

    if "main" in stages:
        write_tsv(output_dir / "causal_models_sleep_categories.tsv", category_rows)
        write_tsv(output_dir / "causal_models_sleep_categories_summary.tsv", category_summaries)
        write_tsv(output_dir / "causal_models_sleep_rcs_curve.tsv", rcs_rows)
        write_tsv(output_dir / "causal_models_sleep_rcs_summary.tsv", rcs_summaries)
        lagged = []
        for record in common:
            if record["time"] <= 24:
                continue
            copied = dict(record)
            copied["time"] = record["time"] - 24
            lagged.append(copied)
        lag_rows: list[dict] = []
        for model in ("Model2_confounder", "Model3_health_status"):
            names, matrix = build_design(lagged, "categories", model, knots)
            fit = fit_design(lagged, names, matrix)
            label = f"lag24_{model}"
            lag_rows.extend(sleep_rows(fit, names, label, len(lagged), sum(r["event"] for r in lagged)))
        write_tsv(output_dir / "reverse_causation_lag_24_months.tsv", lag_rows)

    if "inflammation" in stages:
        inflammation_pathway(records, knots, output_dir)
    if "mi" in stages:
        multiple_imputation_analysis(records, knots, output_dir, imputations)
    if "competing" in stages:
        competing_risk_analysis(common, knots, output_dir)

    # Bayesian shrinkage is retained as an inferential sensitivity analysis,
    # not as a remedy for confounding or a device to obtain significance.
    bayes_rows: list[dict] = []
    if "bayes" in stages and not category_rows and (output_dir / "causal_models_sleep_categories.tsv").exists():
        with (output_dir / "causal_models_sleep_categories.tsv").open(encoding="utf-8-sig", newline="") as handle:
            category_rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in category_rows if "bayes" in stages else []:
        if row["term"] != "sleep[>=9 h]" or row["model"] not in {
            "Model2_confounder", "Model3_health_status", "CVD_free_Model2_confounder", "CVD_free_Model3_health_status"
        }:
            continue
        for prior_sd in (0.20, 0.35, 0.70):
            posterior = bayesian_normal_update(float(row["beta"]), float(row["se"]), prior_sd)
            bayes_rows.append({"source_model": row["model"], "term": row["term"], "prior": f"Normal(0,{prior_sd}^2)", **posterior})
    if "bayes" in stages:
        write_tsv(output_dir / "bayesian_shrinkage_sensitivity.tsv", bayes_rows)

    quality = [
        {"metric": "expanded_cohort_n", "value": len(records)},
        {"metric": "expanded_cohort_heart_deaths", "value": sum(r["event"] for r in records)},
        {"metric": "expanded_cohort_competing_deaths", "value": sum(r["other_death"] for r in records)},
        {"metric": "common_complete_case_n", "value": len(common)},
        {"metric": "common_complete_case_heart_deaths", "value": sum(r["event"] for r in common)},
        {"metric": "strict_CVD_free_complete_case_n", "value": len(cvd_free)},
        {"metric": "strict_CVD_free_complete_case_heart_deaths", "value": sum(r["event"] for r in cvd_free)},
        {"metric": "SIRI_observed", "value": sum(finite(r.get("log_siri")) for r in records)},
        {"metric": "SII_observed", "value": sum(finite(r.get("log_sii")) for r in records)},
        {"metric": "multiple_imputations", "value": imputations},
    ]
    write_tsv(output_dir / "causal_reanalysis_quality_control.tsv", quality)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--imputations", type=int, default=20)
    parser.add_argument(
        "--stages",
        default="main,inflammation,mi,competing,bayes",
        help="Comma-separated subset of main,inflammation,mi,competing,bayes",
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    output_dir = (args.output_dir or project_root / "outputs" / "causal_reanalysis_20260808").resolve()
    stages = {value.strip() for value in args.stages.split(",") if value.strip()}
    invalid = stages.difference({"main", "inflammation", "mi", "competing", "bayes"})
    if invalid:
        raise ValueError(f"Unknown stages: {sorted(invalid)}")
    run(project_root, output_dir, args.imputations, stages)
    print(output_dir)


if __name__ == "__main__":
    main()
