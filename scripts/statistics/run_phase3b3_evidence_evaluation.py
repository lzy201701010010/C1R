from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from scipy.stats import norm


PROJECT = Path(r"D:\SCIfour")
P3B = PROJECT / "phase3B_execution"
P3B2 = P3B / "phase3b2_reexecution"
ROOT = P3B / "phase3b3_evidence_evaluation"
LOGS = ROOT / "logs"
WORK = ROOT / "work"
PROVENANCE = ROOT / "provenance"
FROZEN = P3B / "frozen_authorities"
RUN_ID = "C1R_P3B3_20260914"
AMENDMENT = ROOT / "C1R_PHASE3B3_PROMPT_REVIEW_AND_CONTROLLING_AMENDMENTS.md"
SCANNER_SOURCE = LOGS / "RankScoreScanner.cs"
MAPPING_AUDIT = P3B2 / "outputs" / "qc" / "phase3b2_reexec_feature_mapping_audit.tsv"
P3B2_MANIFEST = P3B2 / "provenance" / "phase3B2_reexec_output_manifest.tsv"
STATE_ROOT = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "03_state_freeze" / "states"
MASK_ROOT = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "04_anticoupling_registry" / "masks"
BASE_P3B2_SCRIPT = P3B / "logs" / "run_phase3b2_controlled_qc_audit.py"
ROUTE_ROOT = PROJECT / "34_PHASE3B2R2_C1R_ADVANCEMENT_ROUTE_ASSESSMENT"
ROUTE_GATE = ROUTE_ROOT / "03_route_a_remediation_refreeze"
NEW_SCP259_INPUT = ROUTE_ROOT / "02_incoming_portal_exact"
REPORT = ROOT / "C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md"
QA_JSON = PROVENANCE / "phase3B3_qa.json"
OUTPUT_MANIFEST = PROVENANCE / "phase3B3_output_manifest.tsv"
sys.dont_write_bytecode = True


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_rows(path: Path, delimiter: str = "\t") -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_rows(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    require(bool(rows), f"Refusing to write empty table: {path}")
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def verify_self_excluding_manifest(root: Path, manifest: Path) -> dict[str, object]:
    rows = read_rows(manifest)
    failures: list[str] = []
    for row in rows:
        target = root / Path(row["relative_path"].replace("/", os.sep))
        if not target.is_file():
            failures.append("MISSING:" + row["relative_path"])
        elif target.stat().st_size != int(row["size_bytes"]):
            failures.append("SIZE:" + row["relative_path"])
        elif sha256(target) != row["sha256"].upper():
            failures.append("SHA256:" + row["relative_path"])
    require(not failures, f"Manifest verification failed: {failures[:5]}")
    return {"rows": len(rows), "failures": failures, "status": "PASS"}


def verify_frozen_authorities() -> dict[str, object]:
    manifest = P3B / "provenance" / "authority_manifest.tsv"
    rows = read_rows(manifest)
    failures: list[str] = []
    for row in rows:
        target = P3B / Path(row["snapshot_relative_path"].replace("/", os.sep))
        if not target.is_file():
            failures.append("MISSING:" + row["snapshot_relative_path"])
        elif target.stat().st_size != int(row["size_bytes"]):
            failures.append("SIZE:" + row["snapshot_relative_path"])
        elif sha256(target) != row["snapshot_sha256"].upper():
            failures.append("SHA256:" + row["snapshot_relative_path"])
        elif not (target.stat().st_file_attributes & 1):
            failures.append("NOT_READ_ONLY:" + row["snapshot_relative_path"])
    require(len(rows) == 107 and not failures, f"Frozen authority verification failed: rows={len(rows)} failures={failures[:5]}")
    return {"rows": len(rows), "status": "PASS", "failures": failures}


def verify_current_inputs() -> tuple[dict[str, object], dict[str, str]]:
    route_manifest = read_rows(ROUTE_GATE / "C1R_PHASE3B2R_ROUTEA_OUTPUT_MANIFEST.tsv")
    route_failures: list[str] = []
    for row in route_manifest:
        target = ROUTE_GATE / Path(row["relative_path"].replace("/", os.sep))
        if not target.is_file() or target.stat().st_size != int(row["size_bytes"]) or sha256(target) != row["sha256"].upper():
            route_failures.append(row["relative_path"])
        elif not (target.stat().st_file_attributes & 1):
            route_failures.append("NOT_READ_ONLY:" + row["relative_path"])
    require(not route_failures, f"Route A manifest verification failed: {route_failures[:5]}")
    authority_rows = read_rows(ROUTE_GATE / "scp259_new_authority_manifest.tsv")
    current = [row for row in authority_rows if row["authority_snapshot_id"] == "C1R_SCP259_INPUT_REMEDIATION_V1"]
    require(len(current) == 4 and all(row["record_status"] == "FROZEN_PASS" for row in current), "Invalid current SCP259 authority")
    scp1884 = [row for row in read_rows(P3B / "provenance" / "input_manifest.tsv") if "SCP1884" in row["dataset"]]
    require(len(scp1884) == 4, "Expected four frozen SCP1884 inputs")
    failures: list[str] = []
    observed: dict[str, str] = {}
    for row in current:
        target = Path(row["local_path"])
        if not target.is_file() or target.stat().st_size != int(row["local_decoded_size_bytes"]):
            failures.append("MISSING_OR_SIZE:" + str(target)); continue
        digest = sha256(target); observed[str(target)] = digest
        if digest != row["sha256"].upper(): failures.append("SHA256:" + str(target))
        if not (target.stat().st_file_attributes & 1): failures.append("NOT_READ_ONLY:" + str(target))
    for row in scp1884:
        target = Path(row["local_path"])
        if not target.is_file() or target.stat().st_size != int(row["size_bytes"]):
            failures.append("MISSING_OR_SIZE:" + str(target)); continue
        digest = sha256(target); observed[str(target)] = digest
        if digest != row["expected_sha256"].upper(): failures.append("SHA256:" + str(target))
    require(not failures, f"Current input verification failed: {failures[:5]}")
    return ({"rows": 8, "status": "PASS", "failures": failures,
             "route_a_output_manifest": {"rows": len(route_manifest), "status": "PASS_SIZE_SHA256_READ_ONLY", "failures": []},
             "scp259_authority": "C1R_SCP259_INPUT_REMEDIATION_V1_FOUR_OF_FOUR_FROZEN_PASS",
             "historical_failed_matrix_analytical_use": "NONE"}, observed)


def load_authority_context():
    spec = importlib.util.spec_from_file_location("c1r_phase3b2_base_readonly", BASE_P3B2_SCRIPT)
    require(spec is not None and spec.loader is not None, "Cannot import Phase 3B-2 metadata implementation")
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    base.SCP259_MATRIX = NEW_SCP259_INPUT / "gene_sorted-Epi.matrix.mtx"
    base.SCP259_FEATURES = NEW_SCP259_INPUT / "Epi.genes.tsv"
    base.SCP259_BARCODES = NEW_SCP259_INPUT / "Epi.barcodes2.tsv"
    base.SCP259_METADATA = NEW_SCP259_INPUT / "all.meta2.txt"
    return SimpleNamespace(m=base, verify_authorities_from_historical_root=verify_frozen_authorities,
                           verify_current_inputs=verify_current_inputs)


def membership_genes(path: Path) -> list[str]:
    rows = read_rows(path)
    genes = [row["gene_symbol"] for row in rows]
    require(len(genes) == len(set(genes)) and len(genes) >= 3, f"Invalid membership: {path}")
    return genes


def build_score_memberships() -> tuple[list[dict[str, object]], dict[str, list[str]]]:
    definitions: dict[str, list[str]] = {}
    for state in [f"SP{i:02d}" for i in range(1, 8)]:
        definitions[f"STATE__{state}"] = membership_genes(STATE_ROOT / f"{state}_GENES.tsv")
    programs = ["GP_IBD_GCST004131_V1", "GP_CD_GCST004132_V1", "GP_UC_GCST004133_V1"]
    for program in programs:
        states = [f"SP{i:02d}" for i in range(1, 5)] if program.startswith("GP_IBD_") else [f"SP{i:02d}" for i in range(1, 8)]
        for state in states:
            definitions[f"PRED__{program}__{state}"] = membership_genes(MASK_ROOT / f"{program}__{state}__NONOVERLAP_MASK.tsv")
    rows = [{"score_id": score_id, "gene": gene} for score_id, genes in definitions.items() for gene in genes]
    return rows, definitions


def write_cell_map(path: Path, barcodes: list[str], metadata: list[dict[str, object]], selected_arm: str) -> int:
    rows = []
    for index, (barcode, item) in enumerate(zip(barcodes, metadata, strict=True), start=1):
        if item["arm"] != selected_arm:
            continue
        rows.append({"cell_index_1based": index, "barcode": barcode, "arm": selected_arm,
                     "sample": item["sample"], "donor": item["donor"]})
    write_rows(path, rows)
    return len(rows)


def invoke_scanner(matrix: Path, dataset: str, expected_hash: str, membership_path: Path,
                   cell_map_path: Path, output_path: Path, summary_path: Path) -> str:
    args = [str(matrix), str(MAPPING_AUDIT), dataset, str(membership_path), str(cell_map_path),
            str(output_path), str(summary_path), expected_hash]
    quoted = ",".join("'" + value.replace("'", "''") + "'" for value in args)
    command = f"Add-Type -Path '{SCANNER_SOURCE}'; [C1RRankScoreScanner]::Run({quoted})"
    completed = subprocess.run(["pwsh", "-NoProfile", "-Command", command], check=True, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(completed.stdout, flush=True)
    return completed.stdout.strip()


def run_scanner_self_test() -> dict[str, object]:
    test_root = WORK / "scanner_self_test"
    test_root.mkdir(parents=True, exist_ok=True)
    matrix = test_root / "toy.mtx"
    mapping = test_root / "mapping.tsv"
    membership = test_root / "membership.tsv"
    cell_map = test_root / "cells.tsv"
    output = test_root / "scores.tsv"
    summary = test_root / "summary.tsv"
    matrix.write_text("%%MatrixMarket matrix coordinate integer general\n3 2 3\n2 1 1\n3 1 2\n3 2 1\n", encoding="ascii")
    mapping.write_text(
        "dataset_identifier\tsource_row_index_1based\tcanonical_hgnc_symbol\tcanonical_collapse_group_size\n"
        "TOY\t1\tA\t1\nTOY\t2\tB\t1\nTOY\t3\tC\t1\n", encoding="utf-8")
    membership.write_text("score_id\tgene\nS\tA\nS\tB\nS\tC\n", encoding="utf-8")
    cell_map.write_text("cell_index_1based\tbarcode\tarm\tsample\tdonor\n1\tc1\tT\ts1\td1\n2\tc2\tT\ts2\td2\n", encoding="utf-8")
    args = [str(matrix), str(mapping), "TOY", str(membership), str(cell_map), str(output), str(summary), sha256(matrix)]
    quoted = ",".join("'" + value.replace("'", "''") + "'" for value in args)
    command = f"Add-Type -Path '{SCANNER_SOURCE}'; [C1RRankScoreScanner]::Run({quoted})"
    completed = subprocess.run(["pwsh", "-NoProfile", "-Command", command], check=True, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    scores = pd.read_csv(output, sep="\t")["S"].to_numpy(dtype=float)
    require(np.allclose(scores, np.array([0.5, 0.5]), atol=1e-15, rtol=0), f"Scanner self-test mismatch: {scores}")
    return {"status": "PASS", "expected_scores": [0.5, 0.5], "observed_scores": scores.tolist(),
            "scanner_output": completed.stdout.strip()}


def aggregate_scores(cell_score_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(cell_score_path, sep="\t")
    score_cols = [column for column in frame.columns if column.startswith("STATE__") or column.startswith("PRED__")]
    require(frame[score_cols].apply(np.isfinite).all().all(), "Nonfinite cell score")
    sample = frame.groupby(["arm", "sample", "donor"], sort=True, as_index=False)[score_cols].median()
    donor = sample.groupby(["arm", "donor"], sort=True, as_index=False)[score_cols].mean()
    return donor


def fit_hc3(x: np.ndarray, y: np.ndarray) -> dict[str, object]:
    complete = np.isfinite(x) & np.isfinite(y)
    x, y = x[complete].astype(float), y[complete].astype(float)
    n = len(x)
    base = {"n_complete_donors": n, "status": "NOT_ESTIMABLE", "failure_reason": ""}
    if n < 5:
        return base | {"failure_reason": "COMPLETE_CASE_DONORS_LT_5"}
    sx, sy = np.std(x, ddof=1), np.std(y, ddof=1)
    if not np.isfinite(sx) or sx <= 1e-12:
        return base | {"failure_reason": "PREDICTOR_SD_NONFINITE_OR_LE_1E_12"}
    if not np.isfinite(sy) or sy <= 1e-12:
        return base | {"failure_reason": "OUTCOME_SD_NONFINITE_OR_LE_1E_12"}
    zx, zy = (x - np.mean(x)) / sx, (y - np.mean(y)) / sy
    design = np.column_stack([np.ones(n), zx])
    if np.linalg.matrix_rank(design) < 2:
        return base | {"failure_reason": "DESIGN_RANK_LT_2"}
    if n - 2 <= 0:
        return base | {"failure_reason": "RESIDUAL_DF_LE_0"}
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
    except np.linalg.LinAlgError:
        return base | {"failure_reason": "MATRIX_INVERSION_FAILED"}
    leverage = np.sum((design @ xtx_inv) * design, axis=1)
    if np.any(1.0 - leverage <= 1e-8):
        return base | {"failure_reason": "HC3_LEVERAGE_1_MINUS_H_LE_1E_8"}
    beta_all = xtx_inv @ design.T @ zy
    residual = zy - design @ beta_all
    scaled = residual / (1.0 - leverage)
    meat = design.T @ ((scaled * scaled)[:, None] * design)
    covariance = xtx_inv @ meat @ xtx_inv
    variance = covariance[1, 1]
    if not np.isfinite(variance) or variance < 0:
        return base | {"failure_reason": "HC3_VARIANCE_NONFINITE_OR_NEGATIVE"}
    beta, se = float(beta_all[1]), float(math.sqrt(variance))
    if not np.isfinite(beta) or not np.isfinite(se) or se <= 0:
        return base | {"failure_reason": "BETA_OR_HC3_SE_NONFINITE_OR_SE_LE_0"}
    z_value = beta / se
    raw_p = float(2.0 * norm.sf(abs(z_value)))
    critical = 1.959963984540054
    centered_ss = float(np.sum(zx * zx))
    beta_closed = float(np.sum(zx * zy) / centered_ss)
    residual_closed = zy - beta_closed * zx
    leverage_closed = 1.0 / n + (zx * zx) / centered_ss
    se_closed = float(math.sqrt(np.sum((zx * residual_closed / (1.0 - leverage_closed)) ** 2) / (centered_ss ** 2)))
    p_closed = float(2.0 * norm.sf(abs(beta_closed / se_closed)))
    max_delta = max(abs(beta - beta_closed), abs(se - se_closed), abs(raw_p - p_closed))
    require(max_delta <= 1e-12, f"HC3 closed-form cross-check mismatch: {max_delta}")
    direction = "POSITIVE" if beta > 0 else "NEGATIVE" if beta < 0 else "ZERO"
    return base | {
        "status": "ESTIMABLE", "failure_reason": "NA_NONE", "beta": beta, "hc3_se": se,
        "ci95_lower": beta - critical * se, "ci95_upper": beta + critical * se,
        "wald_z": z_value, "raw_p": raw_p, "direction": direction,
        "max_statsmodels_crosscheck_delta": max_delta,
    }


def bh_adjust(values: list[float]) -> list[float]:
    p = np.asarray(values, dtype=float)
    require(np.isfinite(p).all() and ((p >= 0) & (p <= 1)).all(), "Invalid BH input")
    order = np.argsort(p, kind="mergesort")
    ranked = p[order]
    adjusted = np.minimum.accumulate((ranked * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    adjusted = np.minimum(adjusted, 1.0)
    result = np.empty_like(adjusted)
    result[order] = adjusted
    return result.tolist()


def bh_adjust_reference(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: (item[1], item[0]))
    result = [1.0] * len(values)
    running = 1.0
    for reverse_index in range(len(indexed) - 1, -1, -1):
        original_index, value = indexed[reverse_index]
        rank = reverse_index + 1
        running = min(running, value * len(values) / rank, 1.0)
        result[original_index] = running
    return result


def model_plan() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for program, states, family, role in [
        ("GP_IBD_GCST004131_V1", [f"SP{i:02d}" for i in range(1, 5)], "PRIMARY_8", "PRIMARY"),
        ("GP_CD_GCST004132_V1", [f"SP{i:02d}" for i in range(1, 8)], "E_CD_14", "EXPLORATORY"),
        ("GP_UC_GCST004133_V1", [f"SP{i:02d}" for i in range(1, 8)], "E_UC_14", "EXPLORATORY"),
    ]:
        for state in states:
            for arm in ("M01", "M02"):
                rows.append({"test_id": f"T_{arm}_{program}_{state}", "arm": arm, "program_id": program,
                             "state_id": state, "family": family, "role": role})
    require(len(rows) == 36 and Counter(row["family"] for row in rows) == {"PRIMARY_8": 8, "E_CD_14": 14, "E_UC_14": 14},
            "Frozen model plan mismatch")
    return rows


def format_number(value: object) -> object:
    if value is None or value == "":
        return "NA"
    if isinstance(value, (float, np.floating)):
        return format(float(value), ".17g") if np.isfinite(value) else "NA"
    return value


def main() -> None:
    for directory in (ROOT, LOGS, WORK, PROVENANCE):
        directory.mkdir(parents=True, exist_ok=True)
    require(AMENDMENT.is_file() and "MODIFY_THEN_EXECUTE" in AMENDMENT.read_text(encoding="utf-8"), "Missing controlling amendment")
    amendment_hash_before = sha256(AMENDMENT)
    source_hash_before = sha256(SCANNER_SOURCE)
    script_hash_before = sha256(Path(__file__))

    reexec = load_authority_context()
    qa2 = json.loads((P3B2 / "provenance" / "phase3B2_reexec_qa.json").read_text(encoding="utf-8"))
    require(qa2["completion_state"] == "C1R_PHASE3B2_REEXEC_PASS_READY_FOR_PHASE3B3", "Phase 3B-2 re-execution token mismatch")
    require(qa2["forbidden_operations"]["phase3b3_started"] is False, "Phase 3B-2 provenance claims Phase 3B-3 already started")
    predecessor_manifest = verify_self_excluding_manifest(P3B2, P3B2_MANIFEST)
    authority_pre = reexec.verify_authorities_from_historical_root()
    inputs_pre, input_hashes_pre = reexec.verify_current_inputs()
    require(authority_pre["status"] == "PASS" and inputs_pre["status"] == "PASS", "Pre-open authority/input verification failed")

    score_rows, definitions = build_score_memberships()
    membership_path = WORK / "authorized_score_memberships.tsv"
    write_rows(membership_path, score_rows)
    self_test = run_scanner_self_test()

    scp259_barcodes = reexec.m.load_lines(reexec.m.SCP259_BARCODES)
    scp259_metadata, _ = reexec.m.load_scp259_metadata(scp259_barcodes)
    scp1884_barcodes = reexec.m.load_lines(reexec.m.SCP1884_BARCODES)
    scp1884_metadata, _ = reexec.m.load_scp1884_metadata(scp1884_barcodes)
    cell_maps = {"SCP259": WORK / "SCP259_M01_cell_map.tsv", "SCP1884": WORK / "SCP1884_M02_cell_map.tsv"}
    selected_counts = {
        "SCP259": write_cell_map(cell_maps["SCP259"], scp259_barcodes, scp259_metadata, "M01"),
        "SCP1884": write_cell_map(cell_maps["SCP1884"], scp1884_barcodes, scp1884_metadata, "M02"),
    }
    require(selected_counts == {"SCP259": 11409, "SCP1884": 10174}, f"Selected cell counts changed: {selected_counts}")

    matrix_paths = {"SCP259": reexec.m.SCP259_MATRIX, "SCP1884": reexec.m.SCP1884_MATRIX}
    expected_hashes = {dataset: input_hashes_pre[str(path)] for dataset, path in matrix_paths.items()}
    score_paths = {dataset: WORK / f"{dataset}_authorized_cell_scores.tsv" for dataset in matrix_paths}
    scanner_summaries = {}
    for dataset in ("SCP259", "SCP1884"):
        scanner_summaries[dataset] = invoke_scanner(
            matrix_paths[dataset], dataset, expected_hashes[dataset], membership_path, cell_maps[dataset],
            score_paths[dataset], WORK / f"{dataset}_rank_score_summary.tsv")

    donors = pd.concat([aggregate_scores(score_paths["SCP259"]), aggregate_scores(score_paths["SCP1884"])], ignore_index=True)
    require(Counter(donors["arm"]) == {"M01": 14, "M02": 5}, f"Donor aggregation mismatch: {Counter(donors['arm'])}")
    donor_scores_path = WORK / "authorized_donor_score_matrix.tsv"
    donors.to_csv(donor_scores_path, sep="\t", index=False, float_format="%.17g", lineterminator="\n")

    effects: list[dict[str, object]] = []
    for item in model_plan():
        subset = donors.loc[donors["arm"] == item["arm"]]
        predictor = subset[f"PRED__{item['program_id']}__{item['state_id']}"].to_numpy(dtype=float)
        outcome = subset[f"STATE__{item['state_id']}"].to_numpy(dtype=float)
        fit = fit_hc3(predictor, outcome)
        effects.append(item | fit)

    for family in ("PRIMARY_8", "E_CD_14", "E_UC_14"):
        indices = [i for i, row in enumerate(effects) if row["family"] == family]
        bh_input = [float(effects[i]["raw_p"]) if effects[i]["status"] == "ESTIMABLE" else 1.0 for i in indices]
        adjusted = bh_adjust(bh_input)
        reference = bh_adjust_reference(bh_input)
        require(np.max(np.abs(np.asarray(adjusted) - np.asarray(reference))) <= 1e-15, "BH cross-check failed")
        for i, q, p_input in zip(indices, adjusted, bh_input, strict=True):
            effects[i]["p_for_bh"] = p_input
            effects[i]["bh_adjusted_p"] = q
            effects[i]["passes_family_bh_0_05"] = "YES" if effects[i]["status"] == "ESTIMABLE" and q <= 0.05 else "NO"
            effects[i]["multiplicity_note"] = "EXPLORATORY_NOT_CONFIRMATORY" if family != "PRIMARY_8" else "PRIMARY_COMPLETE_FAMILY"

    effect_fields = ["test_id", "arm", "program_id", "state_id", "family", "role", "status", "failure_reason",
                     "n_complete_donors", "beta", "hc3_se", "ci95_lower", "ci95_upper", "wald_z", "raw_p",
                     "p_for_bh", "bh_adjusted_p", "passes_family_bh_0_05", "direction", "multiplicity_note",
                     "max_statsmodels_crosscheck_delta"]
    effect_rows = [{field: format_number(row.get(field)) for field in effect_fields} for row in effects]
    write_rows(ROOT / "donor_level_effect_summary.tsv", effect_rows, effect_fields)

    effect_lookup = {(row["program_id"], row["state_id"], row["arm"]): row for row in effects}
    evidence_rows: list[dict[str, object]] = []
    programs = ["GP_IBD_GCST004131_V1", "GP_CD_GCST004132_V1", "GP_UC_GCST004133_V1"]
    for program in programs:
        for state in [f"SP{i:02d}" for i in range(1, 8)]:
            pair_role = "PRIMARY" if program.startswith("GP_IBD_") and state in {"SP01", "SP02", "SP03", "SP04"} else "EXPLORATORY"
            if program.startswith("GP_IBD_") and state in {"SP05", "SP06", "SP07"}:
                evidence_rows.append({
                    "program_id": program, "state_id": state, "pair_role": pair_role,
                    "evaluation_status": "NOT_EVALUATED_OUTSIDE_FROZEN_TEST_FAMILIES",
                    "m01_status": "NOT_EVALUATED", "m01_beta": "NA", "m01_bh_adjusted_p": "NA", "m01_direction": "NA",
                    "m02_status": "NOT_EVALUATED", "m02_beta": "NA", "m02_bh_adjusted_p": "NA", "m02_direction": "NA",
                    "m03_status": "NOT_EVALUATED_OUTSIDE_INITIAL_EXECUTION", "evidence_class": "NOT_EVALUATED",
                    "interpretation_ceiling": "MAPPING_ONLY_NO_SCIENTIFIC_EVIDENCE_CLASS",
                })
                continue
            left = effect_lookup[(program, state, "M01")]
            right = effect_lookup[(program, state, "M02")]
            if left["status"] != "ESTIMABLE" or right["status"] != "ESTIMABLE":
                classification = "NOT_ESTIMABLE"
            elif left["direction"] in {"POSITIVE", "NEGATIVE"} and left["direction"] == right["direction"]:
                classification = "PORTABILITY_SUPPORTED" if left["passes_family_bh_0_05"] == "YES" and right["passes_family_bh_0_05"] == "YES" else "DIRECTIONALLY_CONSISTENT_INSUFFICIENT"
            elif {left["direction"], right["direction"]} == {"POSITIVE", "NEGATIVE"}:
                classification = "DISCORDANT"
            else:
                classification = "NO_SUPPORT"
            evidence_rows.append({
                "program_id": program, "state_id": state, "pair_role": pair_role, "evaluation_status": "EVALUATED_UNDER_FROZEN_CONTRACT",
                "m01_status": left["status"], "m01_beta": format_number(left.get("beta")), "m01_bh_adjusted_p": format_number(left.get("bh_adjusted_p")), "m01_direction": left.get("direction", "NA"),
                "m02_status": right["status"], "m02_beta": format_number(right.get("beta")), "m02_bh_adjusted_p": format_number(right.get("bh_adjusted_p")), "m02_direction": right.get("direction", "NA"),
                "m03_status": "NOT_EVALUATED_OUTSIDE_INITIAL_EXECUTION", "evidence_class": classification,
                "interpretation_ceiling": "PRIMARY_BOUNDED" if pair_role == "PRIMARY" else "EXPLORATORY_NOT_CONFIRMATORY",
            })
    require(len(evidence_rows) == 21, "Evidence matrix must preserve all 21 frozen mappings")
    write_rows(ROOT / "program_state_evidence_matrix.tsv", evidence_rows)
    write_rows(ROOT / "evidence_hierarchy_table.tsv", evidence_rows)

    context_rows = [{
        "program_id": row["program_id"], "state_id": row["state_id"], "pair_role": row["pair_role"],
        "m01_role": "PRIMARY_DISCOVERY", "m01_status": row["m01_status"],
        "m02_role": "PRIMARY_PORTABILITY", "m02_status": row["m02_status"],
        "m03_role": "EXPLORATORY_OUTSIDE_INITIAL_EXECUTION", "m03_status": row["m03_status"],
        "cross_context_evidence_class": row["evidence_class"], "m03_can_rescue_m02": "NO",
    } for row in evidence_rows]
    write_rows(ROOT / "context_comparison_summary.tsv", context_rows)

    multiplicity_rows = []
    for family, expected_n, role in (("PRIMARY_8", 8, "PRIMARY"), ("E_CD_14", 14, "EXPLORATORY"), ("E_UC_14", 14, "EXPLORATORY")):
        subset = [row for row in effects if row["family"] == family]
        multiplicity_rows.append({
            "family": family, "role": role, "frozen_denominator": expected_n, "observed_rows": len(subset),
            "estimable_rows": sum(row["status"] == "ESTIMABLE" for row in subset),
            "not_estimable_rows": sum(row["status"] != "ESTIMABLE" for row in subset),
            "method": "BENJAMINI_HOCHBERG_ONCE_COMPLETE_FAMILY", "alpha": "0.05",
            "not_estimable_handling": "P_EQUALS_1_FOR_ADJUSTMENT_ONLY_STATUS_RETAINED",
            "rows_passing_bh": sum(row["passes_family_bh_0_05"] == "YES" for row in subset),
            "interpretation": "CONFIRMATORY_BOUNDED" if role == "PRIMARY" else "EXPLORATORY_NOT_CONFIRMATORY",
        })
    write_rows(ROOT / "multiplicity_control_summary.tsv", multiplicity_rows)

    sensitivity_rows = [{"analysis": name, "status": "NOT_RUN_NOT_AUTHORIZED", "reason": reason} for name, reason in [
        ("DONOR_LEAVE_ONE_OUT", "NOT_PROSPECTIVELY_FROZEN_FOR_THIS_EXECUTION"),
        ("ALTERNATIVE_DONOR_AGGREGATION", "WOULD_CHANGE_FROZEN_PRIMARY_SCORE_AGGREGATION"),
        ("SPEARMAN", "SENSITIVITY_ONLY_AND_NOT_SEPARATELY_ACTIVATED"),
        ("FULL_OVERLAPPING_PROGRAM", "REQUIRES_SEPARATE_AUTHORIZATION"),
        ("M01_UNRESOLVED_SEGMENT_EXCLUSION", "REQUIRES_SEPARATE_PRE_OUTCOME_AUTHORIZATION"),
        ("M03_EXPLORATORY_CONTEXT", "OUTSIDE_FROZEN_INITIAL_EXECUTION_PACKAGE"),
    ]]
    write_rows(ROOT / "sensitivity_analysis_summary.tsv", sensitivity_rows)

    class_counts = Counter(row["evidence_class"] for row in evidence_rows)
    primary_effects = [row for row in effects if row["family"] == "PRIMARY_8"]
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    primary_table = "\n".join(
        f"| {row['arm']} | {row['state_id']} | {row['status']} | {format_number(row.get('beta'))} | {format_number(row.get('ci95_lower'))}, {format_number(row.get('ci95_upper'))} | {format_number(row.get('bh_adjusted_p'))} | {row.get('direction', 'NA')} |"
        for row in primary_effects
    )
    class_text = ", ".join(f"`{key}`={value}" for key, value in sorted(class_counts.items()))
    report = f"""# C1-R Phase 3B-3 genetic program-state evidence evaluation report

Run ID: `{RUN_ID}`  
Executed: **{now} (Asia/Shanghai)**  
Prompt disposition: **MODIFY_THEN_EXECUTE**  
Mode: **frozen donor-level expression-score association and failure-aware portability classification**

## 1. Controlling scope

The submitted prompt was corrected before outcomes were opened. The controlling amendment is `C1R_PHASE3B3_PROMPT_REVIEW_AND_CONTROLLING_AMENDMENTS.md`. The run evaluated exactly 36 authorized models in M01 and M02: 8 primary, 14 E-CD exploratory, and 14 E-UC exploratory. M03, GP_IBD x SP05-SP07, and all sensitivity analyses were not run.

The 21-pair mapping registry was preserved in the evidence matrix. Rows outside the frozen test families are explicitly `NOT_EVALUATED`, not negative or non-estimable scientific findings.

## 2. Authority and integrity

- Phase 3B-2 re-execution manifest: **{predecessor_manifest['rows']}/{predecessor_manifest['rows']} PASS**.
- Phase 3B-2 completion token: **C1R_PHASE3B2_REEXEC_PASS_READY_FOR_PHASE3B3**.
- Frozen authority snapshots: **{authority_pre['rows']}/{authority_pre['rows']} PASS** before scoring.
- Registered inputs: **{inputs_pre['rows']}/{inputs_pre['rows']} PASS** before scoring.
- SCP259 analytical authority: **C1R_SCP259_INPUT_REMEDIATION_V1**; historical truncated input use: **NONE**.
- Exact selected cells: M01={selected_counts['SCP259']:,}; M02={selected_counts['SCP1884']:,}.
- Exact donor counts after frozen aggregation: M01=14; M02=5.

## 3. Frozen computation

Cell scores used exact SM02 within-cell full-background percentile ranks after the frozen canonical-gene collapse. State and state-specific non-overlap program scores were equal-cell medians within sample and equal-sample means within donor. Each test was standardized within context using `ddof=1` and fitted by OLS with an intercept and HC3 covariance. P values and 95% intervals used the frozen two-sided normal-reference Wald rule.

The scorer passed an exact synthetic fixture. Every estimable matrix-form HC3 result matched an independent centered closed-form implementation within `1e-12`; all three BH families matched an independent reverse-rank BH implementation within `1e-15`.

## 4. Primary family results

| Arm | State | Status | Standardized beta | 95% Wald CI | BH-adjusted P | Direction |
|---|---|---:|---:|---:|---:|---|
{primary_table}

These are donor-level expression-score associations. They are not PRS associations, inherited genetic effects, causal effects, mechanisms, or pristine independent replication.

## 5. Evidence landscape

Across the preserved 21 program-state mappings, the recorded classes were: {class_text}. `NOT_EVALUATED` rows were outside the authorized initial execution and are not included as evidence against an association.

Exploratory E-CD and E-UC adjusted P values remain non-confirmatory. M02 contains exactly five donors and retains the frozen small-sample/HC3 fragility and bounded-metadata limitation. M03 did not rescue or replace M02.

## 6. Required outputs and boundaries

The six requested structured outputs are present. `donor_level_effect_summary.tsv` contains 36 model rows; the evidence and context tables preserve all 21 frozen mappings; `multiplicity_control_summary.tsv` contains the three complete families; `sensitivity_analysis_summary.tsv` records every unexecuted sensitivity boundary.

No program, gene weight, state, mapping, cohort, exclusion, model, threshold, or frozen authority was modified. No biological interpretation or later phase was started.

# C1R_PHASE3B3_PASS_READY_FOR_BIOLOGICAL_INTERPRETATION

This token closes Phase 3B-3 only. `NEXT_PHASE_AUTOSTART = FORBIDDEN`.
"""
    REPORT.write_text(report, encoding="utf-8")

    authority_post = reexec.verify_authorities_from_historical_root()
    inputs_post, input_hashes_post = reexec.verify_current_inputs()
    require(input_hashes_post == input_hashes_pre, "Registered input hash stability failure")
    require(sha256(AMENDMENT) == amendment_hash_before and sha256(SCANNER_SOURCE) == source_hash_before and sha256(Path(__file__)) == script_hash_before,
            "Prospective amendment or implementation changed during execution")

    qa = {
        "schema_version": "C1R_PHASE3B3_QA_V1.0", "run_id": RUN_ID, "timestamp": now,
        "prompt_review": {"outcome": "MODIFY_THEN_EXECUTE", "controlling_amendment_sha256": amendment_hash_before},
        "prechecks": {"phase3b2_manifest": predecessor_manifest, "authority": authority_pre, "inputs": inputs_pre},
        "postchecks": {"authority": authority_post, "inputs": inputs_post, "input_hash_stability": "PASS_8_OF_8"},
        "prospective_code_freeze": {"scanner_sha256": source_hash_before, "runner_sha256": script_hash_before, "status": "PASS_UNCHANGED_DURING_EXECUTION"},
        "scanner_self_test": self_test, "scanner_runs": scanner_summaries,
        "counts": {"selected_cells": selected_counts, "donors": {"M01": 14, "M02": 5}, "models": 36,
                   "mapping_rows": 21, "multiplicity_families": {row["family"]: row["frozen_denominator"] for row in multiplicity_rows}},
        "model_status_counts": dict(Counter(row["status"] for row in effects)),
        "evidence_class_counts": dict(class_counts),
        "crosschecks": {"hc3_max_delta": max(float(row.get("max_statsmodels_crosscheck_delta", 0) or 0) for row in effects),
                        "bh_max_delta": "LE_1E-15"},
        "forbidden_operations": {"m03_models": 0, "gp_ibd_sp05_sp07_models": 0, "sensitivity_models": 0,
                                 "imputations": 0, "cell_level_inference": 0, "frozen_authority_modifications": 0,
                                 "biological_interpretation_started": False},
        "completion_state": "C1R_PHASE3B3_PASS_READY_FOR_BIOLOGICAL_INTERPRETATION",
        "next_phase_autostart": "FORBIDDEN",
    }
    QA_JSON.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    execution_log = f"""# C1-R Phase 3B-3 execution log

Run ID: `{RUN_ID}`  
Timestamp: {now}

1. Reviewed and amended the prompt before opening outcomes.
2. Verified the Phase 3B-2 re-execution manifest and exact completion token.
3. Verified 107 frozen authority snapshots and 8 registered inputs.
4. Passed an exact synthetic rank-score scanner fixture.
5. Scored only M01 and M02 using SM02 and authorized non-overlap masks.
6. Aggregated equal-cell median within sample and equal-sample mean within donor.
7. Fit exactly 36 frozen OLS-HC3 models and cross-checked each estimable fit.
8. Applied BH once to the complete 8, 14, and 14 member families and cross-checked adjustment.
9. Preserved all 21 mappings; recorded excluded tests and M03 as NOT_EVALUATED.
10. Reverified frozen authorities and registered inputs unchanged.
11. Did not start biological interpretation or any later phase.
"""
    (LOGS / "PHASE3B3_EXECUTION_LOG.md").write_text(execution_log, encoding="utf-8")

    manifest_rows = []
    for path in sorted(ROOT.rglob("*"), key=lambda p: p.relative_to(ROOT).as_posix().lower()):
        if not path.is_file() or path == OUTPUT_MANIFEST:
            continue
        relative = path.relative_to(ROOT).as_posix()
        manifest_rows.append({"run_id": RUN_ID, "relative_path": relative, "size_bytes": path.stat().st_size,
                              "sha256": sha256(path), "manifest_rule": "SELF_EXCLUDED_NON_SELF_HASHING"})
    write_rows(OUTPUT_MANIFEST, manifest_rows)
    final_manifest_check = verify_self_excluding_manifest(ROOT, OUTPUT_MANIFEST)
    print(json.dumps({"completion_state": qa["completion_state"], "manifest": final_manifest_check,
                      "model_status_counts": qa["model_status_counts"], "evidence_class_counts": qa["evidence_class_counts"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
