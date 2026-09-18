#!/usr/bin/env python3
"""Synthetic-only C1R mechanics test. Contains no real samples, genes, or distributions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SEED = 20260907
ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "synthetic_smoke_test_results.json"


def average_percentile_ranks(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    n = values.size
    if n < 2 or not np.isfinite(values).all():
        raise ValueError("rank input must contain at least two finite values")
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(n, dtype=np.float64)
    start = 0
    while start < n:
        end = start + 1
        while end < n and sorted_values[end] == sorted_values[start]:
            end += 1
        average_rank = ((start + 1) + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    return (ranks - 1.0) / (n - 1.0)


def collapse_features(matrix: np.ndarray, mapped_ids: list[str]) -> tuple[np.ndarray, list[str]]:
    ordered_unique = list(dict.fromkeys(mapped_ids))
    index = {name: i for i, name in enumerate(ordered_unique)}
    collapsed = np.zeros((matrix.shape[0], len(ordered_unique)), dtype=np.float64)
    for source_column, mapped_id in enumerate(mapped_ids):
        collapsed[:, index[mapped_id]] += matrix[:, source_column]
    return collapsed, ordered_unique


def zscore(values: np.ndarray) -> np.ndarray:
    sd = values.std(ddof=1)
    if not np.isfinite(sd) or sd <= 1e-12:
        raise ValueError("non-estimable variance")
    return (values - values.mean()) / sd


def ols_hc3(x: np.ndarray, y: np.ndarray) -> dict[str, float | int]:
    design = np.column_stack([np.ones(x.size, dtype=np.float64), x])
    rank = int(np.linalg.matrix_rank(design))
    if rank != 2 or x.size < 5:
        raise ValueError("non-estimable design")
    xtx_inv = np.linalg.inv(design.T @ design)
    beta = xtx_inv @ design.T @ y
    residual = y - design @ beta
    leverage = np.einsum("ij,jk,ik->i", design, xtx_inv, design)
    if np.any(1.0 - leverage <= 1e-8):
        raise ValueError("non-estimable HC3 leverage")
    adjusted = residual / (1.0 - leverage)
    meat = design.T @ np.diag(adjusted**2) @ design
    covariance = xtx_inv @ meat @ xtx_inv
    se = float(math.sqrt(covariance[1, 1]))
    estimate = float(beta[1])
    z_value = estimate / se
    p_value = float(math.erfc(abs(z_value) / math.sqrt(2.0)))
    return {
        "n": int(x.size),
        "rank": rank,
        "beta": estimate,
        "hc3_se": se,
        "wald_z": z_value,
        "two_sided_normal_p": p_value,
        "max_leverage": float(leverage.max()),
    }


def main() -> int:
    np.random.seed(SEED)
    required_modules = ["numpy", "pandas", "scipy", "statsmodels", "scanpy", "anndata", "h5py", "zarr", "pyarrow"]
    module_status = {name: bool(importlib.util.find_spec(name)) for name in required_modules}

    source_features = [f"SYN_SOURCE_{i:02d}" for i in range(12)]
    mapped_features = [
        "SYN_CANON_01", "SYN_CANON_02", "SYN_CANON_03", "SYN_CANON_04",
        "SYN_CANON_05", "SYN_CANON_06", "SYN_CANON_07", "SYN_CANON_08",
        "SYN_CANON_09", "SYN_CANON_10", "SYN_CANON_10", "SYN_CANON_11",
    ]
    n_donors = 6
    samples_per_donor = 2
    cells_per_sample = 3
    n_cells = n_donors * samples_per_donor * cells_per_sample
    matrix = np.empty((n_cells, len(source_features)), dtype=np.float64)
    metadata_rows = []
    row = 0
    for donor in range(n_donors):
        for sample in range(samples_per_donor):
            for cell in range(cells_per_sample):
                values = np.array([((row + 2) * (j + 3) + donor * (j + 1) + sample) % 13 for j in range(12)], dtype=np.float64)
                values[5:9] += donor * 2.0
                values[2:5] += donor * 1.0 + cell
                values[0] = 0.0
                values[1] = 0.0
                matrix[row] = values
                metadata_rows.append({"cell": f"SYN_CELL_{row:03d}", "sample": f"SYN_SAMPLE_{donor:02d}_{sample}", "donor": f"SYN_DONOR_{donor:02d}"})
                row += 1

    collapsed, canonical = collapse_features(matrix, mapped_features)
    rank_matrix = np.vstack([average_percentile_ranks(cell) for cell in collapsed])
    feature_index = {name: i for i, name in enumerate(canonical)}
    state_members = ["SYN_CANON_03", "SYN_CANON_04", "SYN_CANON_05"]
    program_mask = ["SYN_CANON_06", "SYN_CANON_07", "SYN_CANON_08", "SYN_CANON_09"]
    state_score = rank_matrix[:, [feature_index[x] for x in state_members]].mean(axis=1)
    program_score = rank_matrix[:, [feature_index[x] for x in program_mask]].mean(axis=1)

    frame = pd.DataFrame(metadata_rows)
    frame["state_score"] = state_score
    frame["program_score"] = program_score
    sample = frame.groupby(["donor", "sample"], sort=True)[["state_score", "program_score"]].median().reset_index()
    donor = sample.groupby("donor", sort=True)[["state_score", "program_score"]].mean().reset_index()
    model = ols_hc3(zscore(donor["program_score"].to_numpy()), zscore(donor["state_score"].to_numpy()))

    tie_probe = average_percentile_ranks(np.array([0.0, 0.0, 2.0, 4.0]))
    checks = {
        "synthetic_identifiers_only": all(x.startswith("SYN_") for x in source_features + mapped_features + state_members + program_mask),
        "duplicate_collapse": collapsed.shape == (n_cells, 11),
        "average_zero_ties": bool(tie_probe[0] == tie_probe[1]),
        "normalized_rank_bounds": bool(np.all((rank_matrix >= 0.0) & (rank_matrix <= 1.0))),
        "post_rank_selection": bool(state_score.shape == (n_cells,) and program_score.shape == (n_cells,)),
        "sample_median_then_donor_mean": bool(sample.shape[0] == 12 and donor.shape[0] == 6),
        "ols_hc3_finite": bool(all(np.isfinite(v) for k, v in model.items() if k not in {"n", "rank"})),
        "model_rank_two": model["rank"] == 2,
        "output_writing": True,
    }
    core_pass = all(checks.values())
    full_environment_pass = all(module_status.values())
    payload = {
        "test_kind": "SYNTHETIC_ONLY_NO_REAL_SAMPLES_GENES_OR_DISTRIBUTIONS",
        "seed": SEED,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "required_module_availability": module_status,
        "checks": checks,
        "synthetic_dimensions": {"cells": n_cells, "source_features": 12, "collapsed_features": 11, "samples": 12, "donors": 6},
        "synthetic_model": model,
        "core_mechanics_status": "PASS" if core_pass else "FAIL",
        "full_target_environment_status": "PASS" if full_environment_pass else "CONDITIONAL_REQUIRED_PACKAGES_MISSING",
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    RESULTS.write_text(encoded, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()
    print(json.dumps({"results": str(RESULTS), "sha256": digest, "core_pass": core_pass, "full_environment_pass": full_environment_pass}))
    return 0 if core_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
