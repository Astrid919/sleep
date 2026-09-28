"""Independent audit and Bayesian sensitivity analysis for the NHANES manuscript.

This script intentionally uses only the Python standard library plus NumPy and
openpyxl from the bundled workspace runtime.  It is designed to make the key
checks reproducible even when an R runtime is not available.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from openpyxl import load_workbook


MISSING = {"", "NA", "NaN", ".", None}
SLEEP_LABELS = ("<6 h", "6-<7 h", "7-<8 h", "8-<9 h", ">=9 h")


def parse_number(value):
    if value in MISSING:
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def is_missing(value) -> bool:
    return value in MISSING or (isinstance(value, float) and math.isnan(value))


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_two_sided_p(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2.0))


def chi_square_survival(value: float, df: int) -> float:
    """Chi-square upper-tail probability for the small integer df used here."""
    if value < 0 or df < 1:
        return math.nan
    x = value / 2.0
    if df % 2 == 0:
        order = df // 2
        return math.exp(-x) * sum(x**k / math.factorial(k) for k in range(order))
    # Half-integer incomplete gamma recursion, starting at Q(1/2, x).
    shape = 0.5
    q_value = math.erfc(math.sqrt(x))
    while shape < df / 2.0:
        q_value += math.exp(-x) * x**shape / math.gamma(shape + 1.0)
        shape += 1.0
    return min(1.0, max(0.0, q_value))


def format_p(value: float) -> str:
    if not math.isfinite(value):
        return ""
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def write_tsv(path: Path, rows: Sequence[dict], fieldnames: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    names = list(fieldnames or rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_selected_tsv(path: Path, selected: Sequence[str]) -> dict[str, list]:
    selected_set = set(selected)
    output = {name: [] for name in selected}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing_columns = selected_set.difference(reader.fieldnames or [])
        if missing_columns:
            raise ValueError(f"Missing columns in {path}: {sorted(missing_columns)}")
        for row in reader:
            for name in selected:
                output[name].append(row[name])
    return output


def sleep_group(value: float) -> str | None:
    if not math.isfinite(value):
        return None
    if value < 6:
        return SLEEP_LABELS[0]
    if value < 7:
        return SLEEP_LABELS[1]
    if value < 8:
        return SLEEP_LABELS[2]
    if value < 9:
        return SLEEP_LABELS[3]
    return SLEEP_LABELS[4]


def categorical_value(value: float, mapping: dict[int, str]) -> str | None:
    if not math.isfinite(value):
        return None
    return mapping.get(int(value))


def load_strict_cvd(project_root: Path, keys: set[tuple[str, int]]) -> dict[tuple[str, int], str | None]:
    path = project_root / "工程文件" / "Heart" / "ImportNHANESData2_Py_189" / "NHANES_Data.tsv"
    wanted = ["year", "SEQN", "MCQ160B", "MCQ160C", "MCQ160D", "MCQ160E"]
    output: dict[tuple[str, int], str | None] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            seqn = parse_number(row["SEQN"])
            if not math.isfinite(seqn):
                continue
            key = (row["year"], int(seqn))
            if key not in keys or key in output:
                continue
            values = [parse_number(row[name]) for name in wanted[2:]]
            if any(value == 1 for value in values):
                output[key] = "Yes"
            elif all(value == 2 for value in values):
                output[key] = "No"
            else:
                output[key] = None
    return output


def load_expanded_adult_cohort(project_root: Path) -> list[dict]:
    """Rebuild the adult cohort before the legacy SII/SIRI complete-case filter."""
    path = project_root / "工程文件" / "Heart" / "DM_FilterRowNa_py_Plus_20" / "DM_FilterRowNa_py.tsv"
    selected = [
        "year", "SEQN", "Gender", "Age", "Race", "Education", "SDMVPSU", "SDMVSTRA",
        "PIR", "BMI", "Smoke", "WTMEC2YR", "Marital", "Sleeptime", "Hypertension",
        "Diabetes", "MORTSTAT", "Time", "UCOD_LEADING",
    ]
    columns = load_selected_tsv(path, selected)
    records: list[dict] = []
    for i in range(len(columns["SEQN"])):
        numeric = {name: parse_number(columns[name][i]) for name in selected if name != "year"}
        if not (
            math.isfinite(numeric["Age"])
            and numeric["Age"] >= 20
            and math.isfinite(numeric["Sleeptime"])
            and 3 <= numeric["Sleeptime"] <= 11
            and math.isfinite(numeric["MORTSTAT"])
            and math.isfinite(numeric["Time"])
            and numeric["Time"] > 0
            and math.isfinite(numeric["WTMEC2YR"])
            and numeric["WTMEC2YR"] > 0
            and math.isfinite(numeric["SDMVPSU"])
            and math.isfinite(numeric["SDMVSTRA"])
        ):
            continue
        key = (columns["year"][i], int(numeric["SEQN"]))
        # Keep the released NHANES masked design variables for auditability, but
        # use explicit pooled-cycle identifiers in every downstream variance
        # calculation.  The released SDMVSTRA values are already unique across
        # the seven cycles used here; the explicit nesting therefore leaves the
        # estimates unchanged while making that assumption mechanically visible.
        cycle_start = int(key[0].split("-")[0])
        cycle_index = (cycle_start - 2003) // 2
        strata_raw = int(numeric["SDMVSTRA"])
        psu_raw = int(numeric["SDMVPSU"])
        record = {
            "key": key,
            "year": key[0],
            "SEQN": key[1],
            "time": numeric["Time"],
            "event": int(numeric["MORTSTAT"] == 1 and numeric["UCOD_LEADING"] == 1),
            "weight": numeric["WTMEC2YR"] / 7.0,
            "psu_raw": psu_raw,
            "strata_raw": strata_raw,
            "psu": cycle_index * 100_000 + strata_raw * 10 + psu_raw,
            "strata": cycle_index * 1_000 + strata_raw,
            "sleep": numeric["Sleeptime"],
            "sleep_group": sleep_group(numeric["Sleeptime"]),
            "age": numeric["Age"],
            "pir_value": numeric["PIR"],
            "bmi_value": numeric["BMI"],
            "sex": categorical_value(numeric["Gender"], {1: "Male", 2: "Female"}),
            "race": categorical_value(
                numeric["Race"],
                {
                    1: "Mexican American",
                    2: "Other Hispanic",
                    3: "Non-Hispanic White",
                    4: "Non-Hispanic Black",
                    5: "Other race",
                },
            ),
            "education": categorical_value(
                numeric["Education"],
                {1: "<High school", 2: "<High school", 3: "High school/GED", 4: ">High school", 5: ">High school"},
            ),
            "pir": (
                None
                if not math.isfinite(numeric["PIR"])
                else "<1.30"
                if numeric["PIR"] < 1.30
                else "1.30-3.49"
                if numeric["PIR"] < 3.50
                else ">=3.50"
            ),
            "bmi": (
                None
                if not math.isfinite(numeric["BMI"])
                else "<25"
                if numeric["BMI"] < 25
                else "25-29.9"
                if numeric["BMI"] < 30
                else ">=30"
            ),
            "smoking": categorical_value(numeric["Smoke"], {1: "Ever smoker", 2: "Never smoker"}),
            "marital": categorical_value(
                numeric["Marital"],
                {
                    1: "Married/partner",
                    2: "Not married/partner",
                    3: "Not married/partner",
                    4: "Not married/partner",
                    5: "Not married/partner",
                    6: "Married/partner",
                },
            ),
            "hypertension": categorical_value(numeric["Hypertension"], {0: "No", 1: "Yes", 2: "No"}),
            "diabetes": categorical_value(numeric["Diabetes"], {0: "No", 1: "Yes", 2: "No", 3: "No"}),
        }
        records.append(record)
    # Repair two deterministic cross-cycle harmonization failures in the saved
    # workflow.  The legacy node omitted all 2015-2016 SMQ020 values and failed
    # to rename 2017-2018 DMDMARTL, even though both official components contain
    # these fields.  The XPT files are retained under data processing for audit.
    external_dir = project_root / "数据处理" / "external_raw_2015_2018"
    smoking_path = external_dir / "SMQ_I.xpt"
    marital_path = external_dir / "DEMO_J.xpt"
    if smoking_path.exists() and marital_path.exists():
        import pandas as pd

        smoking_frame = pd.read_sas(smoking_path, format="xport")[["SEQN", "SMQ020"]]
        marital_frame = pd.read_sas(marital_path, format="xport")[["SEQN", "DMDMARTL"]]
        smoking_map = {
            int(row.SEQN): ("Ever smoker" if row.SMQ020 == 1 else "Never smoker" if row.SMQ020 == 2 else None)
            for row in smoking_frame.itertuples(index=False)
        }
        marital_map = {
            int(row.SEQN): (
                "Married/partner"
                if row.DMDMARTL in (1, 6)
                else "Not married/partner"
                if row.DMDMARTL in (2, 3, 4, 5)
                else None
            )
            for row in marital_frame.itertuples(index=False)
        }
        for record in records:
            if record["year"] == "2015-2016" and record["smoking"] is None:
                record["smoking"] = smoking_map.get(record["SEQN"])
                record["smoking_repaired_from_official_component"] = record["smoking"] is not None
            if record["year"] == "2017-2018" and record["marital"] is None:
                record["marital"] = marital_map.get(record["SEQN"])
                record["marital_repaired_from_official_component"] = record["marital"] is not None

    cvd = load_strict_cvd(project_root, {record["key"] for record in records})
    for record in records:
        record["cvd"] = cvd.get(record["key"])
    return records


def upstream_missing_by_year(project_root: Path) -> None:
    path = project_root / "工程文件" / "Heart" / "DM_FilterRowNa_py_Plus_20" / "DM_FilterRowNa_py.tsv"
    variables = ["PIR", "BMI", "Smoke", "Marital", "Hypertension", "Diabetes"]
    counts: dict[str, Counter] = defaultdict(Counter)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            sleep = parse_number(row["Sleeptime"])
            mortality = parse_number(row["MORTSTAT"])
            followup = parse_number(row["Time"])
            if not (math.isfinite(sleep) and 3 <= sleep <= 11 and math.isfinite(mortality) and math.isfinite(followup) and followup > 0):
                continue
            year = row["year"]
            counts[year]["n"] += 1
            for variable in variables:
                if not math.isfinite(parse_number(row[variable])):
                    counts[year][f"missing_{variable}"] += 1
    print("year\t" + "\t".join(["n", *[f"missing_{variable}" for variable in variables]]))
    for year in sorted(counts):
        print(year, *[counts[year][name] for name in ["n", *[f"missing_{variable}" for variable in variables]]], sep="\t")


def find_headers(project_root: Path, patterns: Sequence[str]) -> None:
    for path in project_root.rglob("*"):
        if path.suffix.lower() not in {".tsv", ".csv"}:
            continue
        try:
            with path.open(encoding="utf-8-sig", errors="ignore") as handle:
                header = handle.readline()
        except OSError:
            continue
        matches = [pattern for pattern in patterns if pattern in header]
        if matches:
            print(path.relative_to(project_root), ",".join(matches), sep="\t")


def one_hot_column(records: Sequence[dict], variable: str, reference: str, missing_category: bool) -> tuple[list[str], np.ndarray]:
    values = [record.get(variable) for record in records]
    if missing_category:
        values = ["Missing" if value is None else value for value in values]
    levels = sorted({value for value in values if value is not None and value != reference})
    matrix = np.zeros((len(records), len(levels)), dtype=float)
    for j, level in enumerate(levels):
        matrix[:, j] = np.fromiter((value == level for value in values), dtype=float, count=len(values))
    return [f"{variable}[{level}]" for level in levels], matrix


def build_matrix(
    records: Sequence[dict],
    exposure: str,
    covariates: Sequence[str],
    missing_category: bool = False,
) -> tuple[list[dict], list[str], np.ndarray]:
    reference_levels = {
        "sleep_group": "7-<8 h",
        "sex": "Male",
        "race": "Non-Hispanic White",
        "education": ">High school",
        "pir": ">=3.50",
        "bmi": "<25",
        "smoking": "Never smoker",
        "marital": "Married/partner",
        "hypertension": "No",
        "diabetes": "No",
        "cvd": "No",
    }
    needed = list(covariates)
    if exposure not in needed:
        needed.insert(0, exposure)
    kept = []
    for record in records:
        if all(
            record.get(name) is not None
            and not (isinstance(record.get(name), float) and math.isnan(record.get(name)))
            for name in needed
            if not (missing_category and name not in {"sleep", "age"})
        ):
            kept.append(record)
    columns: list[np.ndarray] = []
    names: list[str] = []
    for variable in needed:
        if variable in {"sleep", "age"}:
            names.append(variable)
            columns.append(np.asarray([record[variable] for record in kept], dtype=float)[:, None])
        else:
            variable_names, matrix = one_hot_column(
                kept,
                variable,
                reference_levels[variable],
                missing_category=missing_category,
            )
            names.extend(variable_names)
            if matrix.shape[1]:
                columns.append(matrix)
    return kept, names, np.concatenate(columns, axis=1)


@dataclass
class CoxResult:
    beta: np.ndarray
    covariance: np.ndarray
    information: np.ndarray
    log_likelihood: float
    iterations: int
    converged: bool


def _group_moments(time: np.ndarray, event: np.ndarray, x: np.ndarray, w: np.ndarray, eta: np.ndarray):
    unique_time, group = np.unique(time, return_inverse=True)
    group_count = len(unique_time)
    p = x.shape[1]
    eta_shift = float(np.max(eta))
    risk_weight = w * np.exp(np.clip(eta - eta_shift, -700, 0))
    risk0_by_group = np.bincount(group, weights=risk_weight, minlength=group_count)
    risk0 = np.cumsum(risk0_by_group[::-1])[::-1]
    risk1_by_group = np.column_stack(
        [np.bincount(group, weights=risk_weight * x[:, j], minlength=group_count) for j in range(p)]
    )
    risk1 = np.cumsum(risk1_by_group[::-1], axis=0)[::-1]
    # Accumulate second moments with one BLAS cross-product per observed time
    # rather than rereading all participants once for every covariate pair.
    # This is algebraically identical to the former pairwise-bincount loop and
    # makes the 500-replicate absolute-risk bootstrap tractable.
    risk2_by_group = np.zeros((group_count, p, p), dtype=float)
    order = np.argsort(group, kind="stable")
    sorted_group = group[order]
    boundaries = np.flatnonzero(np.diff(sorted_group)) + 1
    for indices in np.split(order, boundaries):
        group_index = int(group[indices[0]])
        block = x[indices]
        risk2_by_group[group_index] = block.T @ (risk_weight[indices, None] * block)
    risk2 = np.cumsum(risk2_by_group[::-1], axis=0)[::-1]
    event_mask = event == 1
    death_weight = np.bincount(group[event_mask], weights=w[event_mask], minlength=group_count)
    death_count = np.bincount(group[event_mask], minlength=group_count).astype(int)
    death_x = np.column_stack(
        [np.bincount(group[event_mask], weights=w[event_mask] * x[event_mask, j], minlength=group_count) for j in range(p)]
    )
    return unique_time, group, risk_weight, risk0, risk1, risk2, death_weight, death_count, death_x, eta_shift


def cox_breslow(
    time: np.ndarray,
    event: np.ndarray,
    x: np.ndarray,
    weights: np.ndarray,
    strata: np.ndarray,
    psu: np.ndarray,
    max_iter: int = 40,
    tolerance: float = 1e-7,
) -> CoxResult:
    """Weighted Cox fit with a stratified-PSU sandwich covariance approximation."""
    w = np.asarray(weights, dtype=float)
    w = w / np.mean(w)
    beta = np.zeros(x.shape[1], dtype=float)
    log_likelihood = -math.inf
    converged = False
    information = np.eye(x.shape[1])
    for iteration in range(1, max_iter + 1):
        eta = x @ beta
        moments = _group_moments(time, event, x, w, eta)
        _, group, risk_weight, risk0, risk1, risk2, death_weight, _, death_x, eta_shift = moments
        event_groups = np.flatnonzero(death_weight > 0)
        means = risk1[event_groups] / risk0[event_groups, None]
        score = death_x[event_groups].sum(axis=0) - (death_weight[event_groups, None] * means).sum(axis=0)
        information = np.zeros((x.shape[1], x.shape[1]), dtype=float)
        for row_index, group_index in enumerate(event_groups):
            second = risk2[group_index] / risk0[group_index]
            information += death_weight[group_index] * (second - np.outer(means[row_index], means[row_index]))
        log_likelihood_new = float(
            np.sum(w[event == 1] * eta[event == 1])
            - np.sum(death_weight[event_groups] * (np.log(risk0[event_groups]) + eta_shift))
        )
        ridge = np.eye(x.shape[1]) * max(1e-10, np.trace(information) * 1e-12 / x.shape[1])
        step = np.linalg.solve(information + ridge, score)
        # Conservative step halving is useful for sparse factor levels.
        scale = 1.0
        while scale > 1 / 128:
            candidate = beta + scale * step
            candidate_eta = x @ candidate
            candidate_moments = _group_moments(time, event, x, w, candidate_eta)
            candidate_risk0 = candidate_moments[3]
            candidate_death_weight = candidate_moments[6]
            candidate_eta_shift = candidate_moments[9]
            candidate_event_groups = np.flatnonzero(candidate_death_weight > 0)
            candidate_loglik = float(
                np.sum(w[event == 1] * candidate_eta[event == 1])
                - np.sum(
                    candidate_death_weight[candidate_event_groups]
                    * (np.log(candidate_risk0[candidate_event_groups]) + candidate_eta_shift)
                )
            )
            if candidate_loglik >= log_likelihood_new - 1e-8:
                beta = candidate
                log_likelihood_new = candidate_loglik
                break
            scale /= 2
        if np.max(np.abs(scale * step)) < tolerance:
            converged = True
            log_likelihood = log_likelihood_new
            break
        log_likelihood = log_likelihood_new
    # Recompute moments at the converged coefficient for score-residual linearization.
    eta = x @ beta
    moments = _group_moments(time, event, x, w, eta)
    _, group, risk_weight, risk0, risk1, risk2, death_weight, _, death_x, _ = moments
    event_groups = np.flatnonzero(death_weight > 0)
    xbar = np.zeros((len(risk0), x.shape[1]), dtype=float)
    xbar[event_groups] = risk1[event_groups] / risk0[event_groups, None]
    information = np.zeros((x.shape[1], x.shape[1]), dtype=float)
    for group_index in event_groups:
        information += death_weight[group_index] * (
            risk2[group_index] / risk0[group_index] - np.outer(xbar[group_index], xbar[group_index])
        )
    hazard_increment = np.zeros(len(risk0), dtype=float)
    hazard_increment[event_groups] = death_weight[event_groups] / risk0[event_groups]
    cumulative_hazard = np.cumsum(hazard_increment)
    cumulative_hazard_xbar = np.cumsum(hazard_increment[:, None] * xbar, axis=0)
    score_rows = -risk_weight[:, None] * (
        x * cumulative_hazard[group, None] - cumulative_hazard_xbar[group]
    )
    event_mask = event == 1
    score_rows[event_mask] += w[event_mask, None] * (x[event_mask] - xbar[group[event_mask]])
    cluster_scores: dict[tuple[int, int], np.ndarray] = defaultdict(lambda: np.zeros(x.shape[1], dtype=float))
    for i in range(len(time)):
        cluster_scores[(int(strata[i]), int(psu[i]))] += score_rows[i]
    by_stratum: dict[int, list[np.ndarray]] = defaultdict(list)
    for (stratum, _), value in cluster_scores.items():
        by_stratum[stratum].append(value)
    meat = np.zeros_like(information)
    grand_mean = np.mean(np.stack(list(cluster_scores.values())), axis=0)
    for values in by_stratum.values():
        array = np.stack(values)
        if len(values) > 1:
            centered = array - np.mean(array, axis=0)
            meat += len(values) / (len(values) - 1) * centered.T @ centered
        else:
            centered = array[0] - grand_mean
            meat += np.outer(centered, centered)
    try:
        inverse_information = np.linalg.inv(information)
    except np.linalg.LinAlgError:
        # A generalized inverse preserves estimable contrasts when sparse or
        # highly correlated nuisance columns make the observed information
        # numerically singular. Full-rank primary models are unchanged.
        inverse_information = np.linalg.pinv(information, rcond=1e-10)
    covariance = inverse_information @ meat @ inverse_information
    covariance = (covariance + covariance.T) / 2.0
    return CoxResult(beta, covariance, information, log_likelihood, iteration, converged)


def result_rows(result: CoxResult, names: Sequence[str], model: str, n: int, events: int) -> list[dict]:
    standard_error = np.sqrt(np.maximum(np.diag(result.covariance), 0))
    rows = []
    for name, beta, se in zip(names, result.beta, standard_error):
        z = beta / se if se > 0 else math.nan
        p_value = normal_two_sided_p(z) if math.isfinite(z) else math.nan
        rows.append(
            {
                "model": model,
                "term": name,
                "beta": beta,
                "se": se,
                "HR": math.exp(beta),
                "lower_95": math.exp(beta - 1.959963984540054 * se),
                "upper_95": math.exp(beta + 1.959963984540054 * se),
                "p_value": p_value,
                "P": format_p(p_value),
                "n": n,
                "events": events,
                "converged": result.converged,
                "iterations": result.iterations,
            }
        )
    return rows


def fit_model(records: Sequence[dict], exposure: str, covariates: Sequence[str], missing_category: bool = False):
    kept, names, matrix = build_matrix(records, exposure, covariates, missing_category=missing_category)
    time = np.asarray([record["time"] for record in kept], dtype=float)
    event = np.asarray([record["event"] for record in kept], dtype=int)
    weight = np.asarray([record["weight"] for record in kept], dtype=float)
    strata = np.asarray([record["strata"] for record in kept], dtype=int)
    psu = np.asarray([record["psu"] for record in kept], dtype=int)
    result = cox_breslow(time, event, matrix, weight, strata, psu)
    return kept, names, result


def restricted_cubic_spline_basis(values: np.ndarray, knots: Sequence[float]) -> np.ndarray:
    x = np.asarray(values, dtype=float)
    knot_values = np.asarray(sorted(knots), dtype=float)
    if len(knot_values) < 3 or len(np.unique(knot_values)) != len(knot_values):
        raise ValueError("Restricted cubic spline knots must contain at least three distinct values.")
    denominator = (knot_values[-1] - knot_values[0]) ** 2
    columns = [x]
    for knot in knot_values[:-2]:
        nonlinear = (
            np.maximum(x - knot, 0) ** 3
            - np.maximum(x - knot_values[-2], 0) ** 3
            * (knot_values[-1] - knot)
            / (knot_values[-1] - knot_values[-2])
            + np.maximum(x - knot_values[-1], 0) ** 3
            * (knot_values[-2] - knot)
            / (knot_values[-1] - knot_values[-2])
        ) / denominator
        columns.append(nonlinear)
    return np.column_stack(columns)


def fit_rcs_model(records: Sequence[dict], covariates: Sequence[str], knots: Sequence[float]):
    kept, names, matrix = build_matrix(records, "sleep", covariates)
    sleep_values = np.asarray([record["sleep"] for record in kept], dtype=float)
    spline = restricted_cubic_spline_basis(sleep_values, knots)
    rcs_names = ["sleep_rcs_linear", *[f"sleep_rcs_nonlinear_{i}" for i in range(1, spline.shape[1])]]
    matrix = np.concatenate([spline, matrix[:, 1:]], axis=1)
    names = [*rcs_names, *names[1:]]
    time = np.asarray([record["time"] for record in kept], dtype=float)
    event = np.asarray([record["event"] for record in kept], dtype=int)
    weight = np.asarray([record["weight"] for record in kept], dtype=float)
    strata = np.asarray([record["strata"] for record in kept], dtype=int)
    psu = np.asarray([record["psu"] for record in kept], dtype=int)
    result = cox_breslow(time, event, matrix, weight, strata, psu)
    return kept, names, result


def wald_test(result: CoxResult, indices: Sequence[int]) -> tuple[float, float]:
    index = np.asarray(indices, dtype=int)
    beta = result.beta[index]
    covariance = result.covariance[np.ix_(index, index)]
    statistic = float(beta @ np.linalg.solve(covariance, beta))
    return statistic, chi_square_survival(statistic, len(index))


def bayesian_normal_update(beta: float, se: float, prior_sd: float) -> dict:
    likelihood_precision = 1.0 / se**2
    prior_precision = 1.0 / prior_sd**2
    posterior_variance = 1.0 / (likelihood_precision + prior_precision)
    posterior_mean = posterior_variance * likelihood_precision * beta
    posterior_sd = math.sqrt(posterior_variance)
    return {
        "posterior_beta": posterior_mean,
        "posterior_sd": posterior_sd,
        "posterior_HR": math.exp(posterior_mean),
        "credible_lower_95": math.exp(posterior_mean - 1.959963984540054 * posterior_sd),
        "credible_upper_95": math.exp(posterior_mean + 1.959963984540054 * posterior_sd),
        "probability_HR_gt_1": normal_cdf(posterior_mean / posterior_sd),
        "probability_HR_gt_1_10": normal_cdf((posterior_mean - math.log(1.10)) / posterior_sd),
        "probability_HR_gt_1_20": normal_cdf((posterior_mean - math.log(1.20)) / posterior_sd),
        "probability_HR_in_0_90_to_1_10": normal_cdf((math.log(1.10) - posterior_mean) / posterior_sd)
        - normal_cdf((math.log(0.90) - posterior_mean) / posterior_sd),
    }


def weighted_mean_sd(records: Sequence[dict], variable: str) -> tuple[float, float, int]:
    use = [
        record
        for record in records
        if record.get(variable) is not None
        and isinstance(record.get(variable), (int, float))
        and math.isfinite(float(record[variable]))
    ]
    if not use:
        return math.nan, math.nan, 0
    values = np.asarray([record[variable] for record in use], dtype=float)
    weights = np.asarray([record["weight"] for record in use], dtype=float)
    mean = float(np.sum(weights * values) / np.sum(weights))
    variance = float(np.sum(weights * (values - mean) ** 2) / np.sum(weights))
    return mean, math.sqrt(max(variance, 0.0)), len(use)


def weighted_category(records: Sequence[dict], variable: str, level: str) -> tuple[int, float, int]:
    observed = [record for record in records if record.get(variable) is not None]
    count = sum(record.get(variable) == level for record in observed)
    denominator = sum(record["weight"] for record in observed)
    numerator = sum(record["weight"] for record in observed if record.get(variable) == level)
    percent = 100.0 * numerator / denominator if denominator > 0 else math.nan
    return count, percent, len(observed)


def create_table1(records: Sequence[dict]) -> list[dict]:
    groups = {
        "Overall": list(records),
        "No heart disease death": [record for record in records if record["event"] == 0],
        "Heart disease death": [record for record in records if record["event"] == 1],
    }
    rows: list[dict] = []
    continuous = [
        ("Age, years", "age"),
        ("Sleep duration, h/night", "sleep"),
        ("Poverty-income ratio", "pir_value"),
        ("BMI, kg/m2", "bmi_value"),
    ]
    for label, variable in continuous:
        row = {"Characteristic": label}
        for group_label, group_records in groups.items():
            mean, sd, n_observed = weighted_mean_sd(group_records, variable)
            missing = len(group_records) - n_observed
            text = f"{mean:.2f} ({sd:.2f})"
            if missing:
                text += f"; missing {missing:,}"
            row[group_label] = text
        rows.append(row)
    categorical_variables = [
        ("Sleep-duration group", "sleep_group", list(SLEEP_LABELS)),
        ("Sex", "sex", ["Male", "Female"]),
        (
            "Race/ethnicity",
            "race",
            ["Mexican American", "Other Hispanic", "Non-Hispanic White", "Non-Hispanic Black", "Other race"],
        ),
        ("Education", "education", ["<High school", "High school/GED", ">High school"]),
        ("Poverty-income ratio group", "pir", ["<1.30", "1.30-3.49", ">=3.50"]),
        ("BMI group", "bmi", ["<25", "25-29.9", ">=30"]),
        ("Ever smoked 100 cigarettes", "smoking", ["Never smoker", "Ever smoker"]),
        ("Marital status", "marital", ["Married/partner", "Not married/partner"]),
        ("Hypertension history", "hypertension", ["No", "Yes"]),
        ("Diabetes history", "diabetes", ["No", "Yes"]),
        ("Prevalent CVD", "cvd", ["No", "Yes"]),
    ]
    for label, variable, levels in categorical_variables:
        header_row = {"Characteristic": label}
        for group_label, group_records in groups.items():
            missing = sum(record.get(variable) is None for record in group_records)
            header_row[group_label] = f"missing {missing:,}" if missing else ""
        rows.append(header_row)
        for level in levels:
            row = {"Characteristic": f"  {level}"}
            for group_label, group_records in groups.items():
                count, percent, _ = weighted_category(group_records, variable, level)
                row[group_label] = f"{count:,} ({percent:.1f}%)"
            rows.append(row)
    return rows


def run_reanalysis(project_root: Path, output_dir: Path) -> None:
    records = load_expanded_adult_cohort(project_root)
    repair_rows = []
    for record in records:
        if record.get("smoking_repaired_from_official_component"):
            repair_rows.append(
                {
                    "year": record["year"],
                    "SEQN": record["SEQN"],
                    "variable": "SMQ020 / smoking",
                    "repaired_value": record["smoking"],
                    "source_file": "SMQ_I.xpt",
                    "source_url": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2015/DataFiles/SMQ_I.xpt",
                }
            )
        if record.get("marital_repaired_from_official_component"):
            repair_rows.append(
                {
                    "year": record["year"],
                    "SEQN": record["SEQN"],
                    "variable": "DMDMARTL / marital status",
                    "repaired_value": record["marital"],
                    "source_file": "DEMO_J.xpt",
                    "source_url": "https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/DEMO_J.xpt",
                }
            )
    write_tsv(output_dir / "cycle_harmonization_repairs.tsv", repair_rows)
    write_tsv(output_dir / "table1_expanded_survey_weighted.tsv", create_table1(records))
    core_covariates = [
        "age", "sex", "race", "education", "pir", "bmi", "smoking", "marital",
        "hypertension", "diabetes", "cvd",
    ]
    model_specs = [
        ("Model1", []),
        ("Model2", ["age", "sex", "race"]),
        ("Model3_prespecified", core_covariates),
    ]
    all_rows: list[dict] = []
    fits: dict[tuple[str, str], tuple[list[dict], list[str], CoxResult]] = {}
    for exposure in ("sleep", "sleep_group"):
        for model_name, covariates in model_specs:
            kept, names, result = fit_model(records, exposure, covariates)
            fits[(model_name, exposure)] = (kept, names, result)
            all_rows.extend(result_rows(result, names, f"{model_name}_{exposure}", len(kept), sum(row["event"] for row in kept)))
    write_tsv(output_dir / "survey_cox_prespecified_expanded_cohort.tsv", all_rows)

    common_rows: list[dict] = []
    common_fits: dict[tuple[str, str], tuple[list[dict], list[str], CoxResult]] = {}
    common_records = fits[("Model3_prespecified", "sleep")][0]
    for exposure in ("sleep", "sleep_group"):
        for model_name, covariates in model_specs:
            if model_name == "Model3_prespecified":
                kept, names, result = fits[(model_name, exposure)]
            else:
                kept, names, result = fit_model(common_records, exposure, covariates)
            common_fits[(model_name, exposure)] = (kept, names, result)
            common_rows.extend(
                result_rows(
                    result,
                    names,
                    f"{model_name}_{exposure}_common_sample",
                    len(kept),
                    sum(row["event"] for row in kept),
                )
            )
    write_tsv(output_dir / "survey_cox_prespecified_common_sample.tsv", common_rows)

    common_summary_rows = []
    for (model_name, exposure), (kept, names, result) in common_fits.items():
        sleep_indices = [index for index, name in enumerate(names) if name == "sleep" or name.startswith("sleep_group[")]
        statistic, p_value = wald_test(result, sleep_indices)
        common_summary_rows.append(
            {
                "model": f"{model_name}_{exposure}_common_sample",
                "sleep_df": len(sleep_indices),
                "wald_chisq": statistic,
                "global_p": p_value,
                "global_P": format_p(p_value),
                "n": len(kept),
                "events": sum(row["event"] for row in kept),
            }
        )
    write_tsv(output_dir / "survey_cox_prespecified_common_sample_summary.tsv", common_summary_rows)

    model_summary_rows = []
    for (model_name, exposure), (kept, names, result) in fits.items():
        sleep_indices = [index for index, name in enumerate(names) if name == "sleep" or name.startswith("sleep_group[")]
        statistic, p_value = wald_test(result, sleep_indices)
        model_summary_rows.append(
            {
                "model": f"{model_name}_{exposure}",
                "sleep_df": len(sleep_indices),
                "wald_chisq": statistic,
                "global_p": p_value,
                "global_P": format_p(p_value),
                "n": len(kept),
                "events": sum(row["event"] for row in kept),
            }
        )
    write_tsv(output_dir / "survey_cox_prespecified_model_summary.tsv", model_summary_rows)

    # Survey-weighted spline on the prespecified complete-case analysis set.
    rcs_knots = (5.0, 6.0, 7.0, 8.0, 9.0)
    rcs_records, rcs_names, rcs_result = fit_rcs_model(records, core_covariates, rcs_knots)
    rcs_df = len(rcs_knots) - 1
    overall_stat, overall_p = wald_test(rcs_result, range(rcs_df))
    nonlinear_stat, nonlinear_p = wald_test(rcs_result, range(1, rcs_df))
    curve_sleep = np.linspace(3.0, 11.0, 161)
    curve_basis = restricted_cubic_spline_basis(curve_sleep, rcs_knots)
    reference_basis = restricted_cubic_spline_basis(np.asarray([7.0]), rcs_knots)[0]
    difference = curve_basis - reference_basis
    sleep_beta = rcs_result.beta[:rcs_df]
    sleep_covariance = rcs_result.covariance[:rcs_df, :rcs_df]
    linear_predictor = difference @ sleep_beta
    variance = np.einsum("ij,jk,ik->i", difference, sleep_covariance, difference)
    curve_rows = []
    for sleep_value, estimate, estimate_variance in zip(curve_sleep, linear_predictor, variance):
        se = math.sqrt(max(float(estimate_variance), 0.0))
        curve_rows.append(
            {
                "sleep_hours": sleep_value,
                "HR_vs_7h": math.exp(float(estimate)),
                "lower_95": math.exp(float(estimate) - 1.959963984540054 * se),
                "upper_95": math.exp(float(estimate) + 1.959963984540054 * se),
            }
        )
    write_tsv(output_dir / "survey_cox_prespecified_rcs_curve.tsv", curve_rows)
    minimum_row = min(curve_rows, key=lambda row: row["HR_vs_7h"])
    rcs_summary_rows = [
        {
            "model": "Model3_prespecified_RCS",
            "knots": ",".join(str(value) for value in rcs_knots),
            "reference_sleep_hours": 7,
            "n": len(rcs_records),
            "events": sum(row["event"] for row in rcs_records),
            "p_overall": overall_p,
            "P_overall": format_p(overall_p),
            "p_nonlinear": nonlinear_p,
            "P_nonlinear": format_p(nonlinear_p),
            "minimum_grid_sleep_hours": minimum_row["sleep_hours"],
            "converged": rcs_result.converged,
            "iterations": rcs_result.iterations,
        }
    ]
    write_tsv(output_dir / "survey_cox_prespecified_rcs_summary.tsv", rcs_summary_rows)

    # Missing-category sensitivity preserves all eligible adults without single-value imputation.
    rare_missing_variables = ["education", "smoking", "marital", "hypertension"]
    missing_sensitivity_records = [
        record
        for record in records
        if all(record.get(variable) is not None for variable in rare_missing_variables)
    ]
    kept_m, names_m, result_m = fit_model(
        missing_sensitivity_records,
        "sleep_group",
        core_covariates,
        missing_category=True,
    )
    missing_rows = result_rows(
        result_m,
        names_m,
        "Model3_prespecified_sleep_group_missing_category_sensitivity",
        len(kept_m),
        sum(row["event"] for row in kept_m),
    )
    write_tsv(output_dir / "survey_cox_prespecified_missing_category_sensitivity.tsv", missing_rows)

    # Bayesian design-based normal approximation for the four clinical sleep contrasts.
    kept, names, result = fits[("Model3_prespecified", "sleep_group")]
    standard_error = np.sqrt(np.maximum(np.diag(result.covariance), 0))
    bayes_rows = []
    for prior_sd in (0.20, 0.35):
        for name, beta, se in zip(names, result.beta, standard_error):
            if not name.startswith("sleep_group["):
                continue
            posterior = bayesian_normal_update(float(beta), float(se), prior_sd)
            bayes_rows.append(
                {
                    "term": name,
                    "prior": f"Normal(0, {prior_sd:.2f}^2) on log(HR)",
                    "prior_sd": prior_sd,
                    "design_based_beta": beta,
                    "design_based_se": se,
                    **posterior,
                    "n": len(kept),
                    "events": sum(row["event"] for row in kept),
                }
            )
    write_tsv(output_dir / "bayesian_sleep_contrasts.tsv", bayes_rows)

    # Reverse-causation and proportional-hazards sensitivity checks.
    sensitivity_rows: list[dict] = []
    lagged_records = []
    for record in records:
        if record["time"] <= 24:
            continue
        copied = dict(record)
        copied["time"] = record["time"] - 24
        lagged_records.append(copied)
    lag_kept, lag_names, lag_result = fit_model(lagged_records, "sleep_group", core_covariates)
    sensitivity_rows.extend(
        result_rows(
            lag_result,
            lag_names,
            "Model3_sleep_group_excluding_first_24_months",
            len(lag_kept),
            sum(row["event"] for row in lag_kept),
        )
    )
    early_records = []
    late_records = []
    for record in records:
        early = dict(record)
        early["event"] = int(record["event"] == 1 and record["time"] <= 60)
        early["time"] = min(record["time"], 60)
        early_records.append(early)
        if record["time"] > 60:
            late = dict(record)
            late["time"] = record["time"] - 60
            late_records.append(late)
    for label, interval_records in (("0_to_60_months", early_records), ("after_60_months", late_records)):
        interval_kept, interval_names, interval_result = fit_model(interval_records, "sleep", core_covariates)
        sensitivity_rows.extend(
            result_rows(
                interval_result,
                interval_names,
                f"Model3_continuous_{label}",
                len(interval_kept),
                sum(row["event"] for row in interval_kept),
            )
        )
    write_tsv(output_dir / "survey_cox_time_and_lag_sensitivity.tsv", sensitivity_rows)

    # Compact raw-data and selection audit.
    audit_rows = [
        {"metric": "adult_sleep_complete_mortality_linked_sleep_3_to_11_n", "value": len(records)},
        {"metric": "heart_disease_deaths", "value": sum(row["event"] for row in records)},
        {
            "metric": "smoking_2015_2016_repaired_from_official_component_n",
            "value": sum(row.get("smoking_repaired_from_official_component") is True for row in records),
        },
        {
            "metric": "marital_2017_2018_repaired_from_official_component_n",
            "value": sum(row.get("marital_repaired_from_official_component") is True for row in records),
        },
    ]
    for variable in core_covariates:
        audit_rows.append(
            {
                "metric": f"missing_{variable}",
                "value": sum(row.get(variable) is None for row in records),
            }
        )
    for model_name, exposure in fits:
        kept_for_model, _, _ = fits[(model_name, exposure)]
        audit_rows.append(
            {
                "metric": f"n_{model_name}_{exposure}",
                "value": len(kept_for_model),
            }
        )
        audit_rows.append(
            {
                "metric": f"events_{model_name}_{exposure}",
                "value": sum(row["event"] for row in kept_for_model),
            }
        )
    write_tsv(output_dir / "expanded_cohort_quality_control.tsv", audit_rows)


def workflow_summary(project_root: Path) -> None:
    path = project_root / "工程文件" / "Heart" / "Heart.dlproj"
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    nodes = document["StatsStreamPlan"]["StatsStreamNodes"]
    print("IDX\tPLANIDX\tIDPLAN\tMODULE\tPARENTS\tROW_COUNTS")
    for node in nodes:
        unit = node["StatsProcessingUnit"]
        result_files = ((unit.get("Result") or {}).get("ResultFiles") or [])
        rows = [
            (item.get("FileName"), item.get("RowCount"))
            for item in result_files
            if item.get("RowCount") is not None
        ]
        print(
            node.get("Index"),
            unit.get("IndexOfPlan"),
            unit.get("IdOfPlan"),
            (unit.get("ModuleInfo") or {}).get("Name"),
            node.get("ParentIndexs"),
            rows,
            sep="\t",
        )


def workflow_node_details(project_root: Path, plan_ids: Sequence[int]) -> None:
    path = project_root / "工程文件" / "Heart" / "Heart.dlproj"
    with path.open(encoding="utf-8") as handle:
        document = json.load(handle)
    nodes = document["StatsStreamPlan"]["StatsStreamNodes"]
    wanted = set(plan_ids)
    for node in nodes:
        unit = node["StatsProcessingUnit"]
        if unit.get("IndexOfPlan") not in wanted:
            continue
        print("\nNODE", unit.get("IndexOfPlan"), unit.get("IdOfPlan"))
        print("MODULE", (unit.get("ModuleInfo") or {}).get("Name"))
        print("PARENTS", node.get("ParentIndexs"))
        for parameter in unit.get("Parameters") or []:
            print(
                "PARAM",
                parameter.get("Binding"),
                "=",
                parameter.get("Value"),
                "[",
                parameter.get("DisplayText"),
                "]",
            )
        result_files = ((unit.get("Result") or {}).get("ResultFiles") or [])
        for item in result_files:
            print(
                "RESULT",
                item.get("FileName"),
                "rows=",
                item.get("RowCount"),
                "cols=",
                item.get("ColumnCount"),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--workflow-summary", action="store_true")
    parser.add_argument("--nodes", nargs="*", type=int)
    parser.add_argument("--run-reanalysis", action="store_true")
    parser.add_argument("--upstream-missing-by-year", action="store_true")
    parser.add_argument("--find-header", nargs="*")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.workflow_summary:
        workflow_summary(args.project_root)
    if args.nodes:
        workflow_node_details(args.project_root, args.nodes)
    if args.run_reanalysis:
        output_dir = args.output_dir or args.project_root / "outputs" / "independent_reanalysis_20260807"
        run_reanalysis(args.project_root, output_dir)
    if args.upstream_missing_by_year:
        upstream_missing_by_year(args.project_root)
    if args.find_header:
        find_headers(args.project_root, args.find_header)


if __name__ == "__main__":
    main()
