from __future__ import annotations

import csv
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import scipy
from scipy.io import mmread
from scipy.sparse import isspmatrix_coo


RUN_ID = "C1R_P3B_RUN001_20260908"
PROJECT = Path(r"D:\SCIfour")
ROOT = PROJECT / "phase3B_execution"
FROZEN = ROOT / "frozen_authorities"
LOGS = ROOT / "logs"
PROVENANCE = ROOT / "provenance"
QC_OUTPUT = ROOT / "outputs" / "qc"

REPORT = ROOT / "C1R_PHASE3B2_CONTROLLED_QC_AND_REPRESENTATION_AUDIT_REPORT.md"
MATRIX_SUMMARY = ROOT / "matrix_integrity_summary.tsv"
CELL_QC = ROOT / "cell_qc_characteristics.tsv"
STATE_SUMMARY = ROOT / "state_representation_summary.tsv"
PROGRAM_SUMMARY = ROOT / "genetic_program_coverage_summary.tsv"
DONOR_PRECHECK = ROOT / "donor_feasibility_precheck.tsv"
FEATURE_AUDIT = QC_OUTPUT / "phase3b2_feature_mapping_audit.tsv"
EXECUTION_LOG = LOGS / "PHASE3B2_EXECUTION_LOG.md"
QA_JSON = PROVENANCE / "phase3B2_qa.json"
OUTPUT_MANIFEST = PROVENANCE / "phase3B2_output_manifest.tsv"
SCRIPT_PATH = Path(__file__).resolve()

INPUT_MANIFEST = PROVENANCE / "input_manifest.tsv"
AUTHORITY_MANIFEST = PROVENANCE / "authority_manifest.tsv"
PHASE3B1_MANIFEST = PROVENANCE / "phase3B1_output_manifest.tsv"
PHASE3B1_QA = PROVENANCE / "phase3B1_qa.json"
RUN_MANIFEST = PROVENANCE / "run_manifest.json"

PHASE3A_ROOT = PROJECT / "32_PHASE3A_C1R_ANALYSIS_EXECUTION_AUTHORIZATION"
PHASE3A_MANIFEST = PHASE3A_ROOT / "PHASE3A_C1R_OUTPUT_MANIFEST.csv"

R45_ROOT = PROJECT / "25_PHASE2B_R45_C1R_SCP259_METADATA_RECOVERY"
SCP259_CANDIDATE = R45_ROOT / "04_HCA_audit" / "C1R_SCP259_HCA_METADATA_CANDIDATE.csv"

SCP259_METADATA = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP259_HCA_versioned_candidate" / "all.meta2.txt"
SCP259_MATRIX = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP259_HCA_versioned_candidate" / "gene_sorted-Epi.matrix.mtx"
SCP259_FEATURES = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP259_HCA_public" / "Epi.genes.tsv"
SCP259_BARCODES = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP259_HCA_public" / "Epi.barcodes2.tsv"

SCP1884_METADATA = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "99_logs" / "rejected_candidates" / "scp1884_author_metadata" / "co_ti_cmb_metadata.txt"
SCP1884_MATRIX = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP1884_HCA_public" / "CO_EPI.scp.raw.mtx"
SCP1884_FEATURES = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP1884_HCA_public" / "CO_EPI.scp.features.tsv"
SCP1884_BARCODES = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze" / "SCP1884_HCA_public" / "CO_EPI.scp.barcodes.tsv"

HGNC_REFERENCE = FROZEN / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "02_gene_mapping_freeze" / "hgnc_complete_set_2026-09-07.txt"
STATE_ROOT = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "03_state_freeze"
STATE_REGISTRY = STATE_ROOT / "C1R_STATE_REGISTRY.csv"
PROGRAM_ROOT = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "02_genetic_program_freeze"
PROGRAM_REGISTRY = PROGRAM_ROOT / "C1R_GENETIC_PROGRAM_REGISTRY.csv"
MASK_ROOT = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "04_anticoupling_registry" / "masks"
CROSSWALK = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "01_donor_registry" / "C1R_DONOR_CROSSWALK.csv"
EXCLUSIONS = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "01_donor_registry" / "C1R_DONOR_EXCLUSION_FREEZE.csv"
MODEL_REGISTRY = FROZEN / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE" / "05_model_and_covariates" / "C1R_MODEL_REGISTRY.csv"

EXPECTED_PACKAGES = {
    "numpy": "2.3.5",
    "scipy": "1.16.2",
    "pandas": "3.0.1",
    "statsmodels": "0.14.5",
    "scanpy": "1.11.4",
    "anndata": "0.12.2",
    "h5py": "3.14.0",
    "zarr": "3.1.2",
    "pyarrow": "21.0.0",
    "matplotlib": "3.10.6",
    "seaborn": "0.13.2",
}


def fail(message: str) -> None:
    raise RuntimeError(message)


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def verify_manifest(
    root: Path,
    manifest: Path,
    path_field: str,
    size_field: str,
    hash_field: str,
    delimiter: str,
) -> dict[str, object]:
    rows = read_csv(manifest, delimiter)
    failures: list[str] = []
    for row in rows:
        target = root / Path(row[path_field].replace("/", os.sep))
        if not target.is_file():
            failures.append(f"MISSING:{row[path_field]}")
            continue
        if target.stat().st_size != int(row[size_field]):
            failures.append(f"SIZE:{row[path_field]}")
            continue
        if sha256(target) != row[hash_field].upper():
            failures.append(f"SHA256:{row[path_field]}")
    require(not failures, f"Manifest verification failed for {manifest}: {failures[:5]}")
    return {"manifest": str(manifest), "rows": len(rows), "failures": failures, "status": "PASS"}


def verify_inputs() -> tuple[dict[str, object], dict[str, str]]:
    rows = read_csv(INPUT_MANIFEST, "\t")
    failures: list[str] = []
    observed: dict[str, str] = {}
    for row in rows:
        target = Path(row["local_path"])
        if not target.is_file():
            failures.append(f"MISSING:{target}")
            continue
        if target.stat().st_size != int(row["size_bytes"]):
            failures.append(f"SIZE:{target}")
            continue
        digest = sha256(target)
        observed[str(target)] = digest
        if digest != row["expected_sha256"].upper():
            failures.append(f"SHA256:{target}")
    require(len(rows) == 8, f"Expected 8 input records, observed {len(rows)}")
    require(not failures, f"Input verification failed: {failures[:5]}")
    return ({"rows": len(rows), "failures": failures, "status": "PASS"}, observed)


def verify_authorities() -> dict[str, object]:
    rows = read_csv(AUTHORITY_MANIFEST, "\t")
    failures: list[str] = []
    for row in rows:
        target = ROOT / Path(row["snapshot_relative_path"].replace("/", os.sep))
        if not target.is_file():
            failures.append(f"MISSING:{row['snapshot_relative_path']}")
            continue
        if target.stat().st_size != int(row["size_bytes"]):
            failures.append(f"SIZE:{row['snapshot_relative_path']}")
            continue
        if sha256(target) != row["snapshot_sha256"].upper():
            failures.append(f"SHA256:{row['snapshot_relative_path']}")
        if not (target.stat().st_file_attributes & 1):
            failures.append(f"NOT_READ_ONLY:{row['snapshot_relative_path']}")
    require(len(rows) == 107, f"Expected 107 frozen authorities, observed {len(rows)}")
    require(not failures, f"Frozen authority verification failed: {failures[:5]}")
    return {"rows": len(rows), "failures": failures, "status": "PASS"}


def verify_environment() -> dict[str, object]:
    expected_python = str(PROJECT / "28_PHASE2C_R1_C1R_PREOUTCOME_READINESS" / "_work" / "python_env" / "Scripts" / "python.exe")
    require(Path(sys.executable).resolve() == Path(expected_python).resolve(), f"Unexpected Python executable: {sys.executable}")
    require(sys.version_info[:3] == (3, 12, 14), f"Unexpected Python version: {sys.version.split()[0]}")
    versions = {name: importlib.metadata.version(name) for name in EXPECTED_PACKAGES}
    require(versions == EXPECTED_PACKAGES, f"Package lock mismatch: {versions}")
    thread_vars = {name: os.environ.get(name) for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "BLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
    require(all(value == "1" for value in thread_vars.values()), f"Thread lock mismatch: {thread_vars}")
    free_bytes = shutil.disk_usage(PROJECT.anchor).free
    require(free_bytes >= 50 * 1024**3, f"Storage floor failed: {free_bytes} bytes free")
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "scipy_version": scipy.__version__,
        "package_versions": versions,
        "thread_variables": thread_vars,
        "free_space_bytes_D": free_bytes,
        "minimum_free_space_bytes": 50 * 1024**3,
        "status": "PASS",
    }


def split_pipe(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def load_hgnc() -> dict[str, object]:
    rows = read_csv(HGNC_REFERENCE, "\t")
    canonical: set[str] = set()
    ensembl_targets: dict[str, set[str]] = defaultdict(set)
    alias_targets: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row["status"] != "Approved" or not row["symbol"]:
            continue
        symbol = row["symbol"]
        canonical.add(symbol)
        for ensembl_id in split_pipe(row["ensembl_gene_id"]):
            ensembl_targets[re.sub(r"\.\d+$", "", ensembl_id)].add(symbol)
        for field in ("alias_symbol", "prev_symbol"):
            for alias in split_pipe(row[field]):
                alias_targets[alias].add(symbol)
    return {
        "rows": len(rows),
        "sha256": sha256(HGNC_REFERENCE),
        "canonical": canonical,
        "ensembl_targets": ensembl_targets,
        "alias_targets": alias_targets,
    }


def map_features(dataset: str, path: Path, hgnc: dict[str, object]) -> dict[str, object]:
    raw_features: list[tuple[str, str]] = []
    if dataset == "SCP259":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw_features = [(line.rstrip("\r\n"), line.rstrip("\r\n")) for line in handle if line.rstrip("\r\n")]
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            for fields in reader:
                require(len(fields) >= 2, f"Malformed feature row in {path}")
                raw_features.append((fields[0], fields[1]))

    canonical = hgnc["canonical"]
    ensembl_targets = hgnc["ensembl_targets"]
    alias_targets = hgnc["alias_targets"]
    mapped: list[str | None] = []
    bases: list[str] = []
    ambiguous_ensembl: list[str] = []
    for source_id, source_symbol in raw_features:
        stripped = re.sub(r"\.\d+$", "", source_id) if source_id.startswith("ENSG") else ""
        target: str | None = None
        basis = "UNMAPPED"
        if stripped:
            targets = ensembl_targets.get(stripped, set())
            if len(targets) == 1:
                target = next(iter(targets))
                basis = "ENSEMBL_TO_HGNC_EXACT_FROZEN_REFERENCE"
            elif len(targets) > 1:
                ambiguous_ensembl.append(stripped)
                basis = "AMBIGUOUS_ENSEMBL_MULTITARGET_UNMAPPED"
        elif source_symbol in canonical:
            target = source_symbol
            basis = "EXACT_CANONICAL_HGNC_SYMBOL"
        else:
            targets = alias_targets.get(source_symbol, set())
            if len(targets) == 1:
                target = next(iter(targets))
                basis = "UNIQUE_ALIAS_OR_PREVIOUS_SYMBOL_TO_HGNC"
            elif len(targets) > 1:
                basis = "AMBIGUOUS_ALIAS_UNMAPPED"
        mapped.append(target)
        bases.append(basis)
    group_sizes = Counter(symbol for symbol in mapped if symbol)
    audit_rows: list[dict[str, object]] = []
    for index, ((source_id, source_symbol), target, basis) in enumerate(zip(raw_features, mapped, bases, strict=True), start=1):
        audit_rows.append({
            "run_id": RUN_ID,
            "dataset_identifier": dataset,
            "source_row_index_1based": index,
            "source_gene_id": source_id,
            "source_gene_symbol": source_symbol,
            "stripped_ensembl_id": re.sub(r"\.\d+$", "", source_id) if source_id.startswith("ENSG") else "NA_NOT_PROVIDED",
            "canonical_hgnc_symbol": target or "NA_UNMAPPED",
            "mapping_status": "MAPPED" if target else "UNMAPPED",
            "mapping_basis": basis,
            "canonical_collapse_group_size": group_sizes.get(target, 0) if target else 0,
            "duplicate_collapse_required": "YES" if target and group_sizes[target] > 1 else "NO",
            "mitochondrial_feature": "YES" if target and target.startswith("MT-") else "NO",
        })
    return {
        "raw_features": raw_features,
        "mapped": mapped,
        "mapped_universe": {symbol for symbol in mapped if symbol},
        "audit_rows": audit_rows,
        "source_feature_count": len(raw_features),
        "mapped_source_rows": sum(symbol is not None for symbol in mapped),
        "canonical_feature_count": len(group_sizes),
        "unmapped_source_rows": sum(symbol is None for symbol in mapped),
        "ambiguous_ensembl_source_rows": len(ambiguous_ensembl),
        "duplicate_canonical_groups": {k: v for k, v in group_sizes.items() if v > 1},
        "mitochondrial_source_rows": sum(bool(symbol and symbol.startswith("MT-")) for symbol in mapped),
    }


def load_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        values = [line.rstrip("\r\n") for line in handle if line.rstrip("\r\n")]
    require(len(values) == len(set(values)), f"Duplicate barcode in {path}")
    return values


def load_scp259_metadata(barcodes: list[str]) -> tuple[list[dict[str, object]], dict[str, object]]:
    candidate_rows = read_csv(SCP259_CANDIDATE)
    primary_samples = {
        row["sample_id"] for row in candidate_rows
        if row["disease_status"] == "ulcerative colitis"
        and row["tissue"] == "colon"
        and row["inflammation_status"] == "Inflamed"
        and row["cell_source"] == "colonic epithelium"
    }
    candidate_by_sample = {row["sample_id"]: row for row in candidate_rows}
    wanted = set(barcodes)
    info: dict[str, dict[str, object]] = {}
    total_rows = 0
    with SCP259_METADATA.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        type_row = next(reader)
        require(header == ["NAME", "Cluster", "nGene", "nUMI", "Subject", "Health", "Location", "Sample"], f"Unexpected SCP259 header: {header}")
        require(type_row[0] == "TYPE", "Missing SCP259 TYPE row")
        for fields in reader:
            require(len(fields) == 8, "Malformed SCP259 metadata row")
            total_rows += 1
            cell, donor, sample = fields[0], fields[4], fields[7]
            if cell not in wanted:
                continue
            require(cell not in info, f"Duplicate SCP259 cell metadata: {cell}")
            require(sample in candidate_by_sample, f"SCP259 sample absent from crosswalk: {sample}")
            require(candidate_by_sample[sample]["donor_id"] == donor, f"SCP259 donor mismatch for {sample}")
            info[cell] = {
                "sample": sample,
                "donor": donor,
                "metadata_detected_genes": int(float(fields[2])),
                "metadata_total_counts": int(float(fields[3])),
                "arm": "M01" if sample in primary_samples else "OUTSIDE_REGISTERED_ARMS",
            }
    require(set(info) == wanted, "SCP259 barcode-to-metadata universe mismatch")
    ordered = [info[barcode] for barcode in barcodes]
    arm_samples = {item["sample"] for item in ordered if item["arm"] == "M01"}
    arm_donors = {item["donor"] for item in ordered if item["arm"] == "M01"}
    require((len(arm_samples), len(arm_donors)) == (16, 14), "Unexpected M01 sample/donor counts")
    return ordered, {"metadata_rows": total_rows, "matched_rows": len(info), "arm_samples": {"M01": arm_samples}, "arm_donors": {"M01": arm_donors}}


def load_scp1884_metadata(barcodes: list[str]) -> tuple[list[dict[str, object]], dict[str, object]]:
    crosswalk_rows = [row for row in read_csv(CROSSWALK) if row["dataset"] == "SCP1884"]
    exclusions = {row["donor_id"] for row in read_csv(EXCLUSIONS)}
    sample_rows = {row["portal_sample_id"]: row for row in crosswalk_rows}
    m02_samples = {
        row["portal_sample_id"] for row in crosswalk_rows
        if row["disease"] == "CROHN_DISEASE" and row["tissue"] == "COLON"
        and row["inflammation_status"] == "ENDOSCOPICALLY_INFLAMED" and row["planned_action"] == "RETAIN"
    }
    m03_samples = {
        row["portal_sample_id"] for row in crosswalk_rows
        if row["disease"] == "CROHN_DISEASE" and row["tissue"] == "COLON"
        and row["inflammation_status"] == "ENDOSCOPICALLY_NON_INFLAMED" and row["planned_action"] == "RETAIN"
    }
    wanted = set(barcodes)
    info: dict[str, dict[str, object]] = {}
    total_rows = 0
    with SCP1884_METADATA.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quotechar='"')
        header = next(reader)
        require(header == ["PubIDSample", "anno_overall", "n_genes", "n_counts", "Chem", "Site", "Type", "PubID", "Layer", "anno2"], f"Unexpected SCP1884 header: {header}")
        for fields in reader:
            require(len(fields) == 11, "Malformed SCP1884 metadata row")
            total_rows += 1
            cell = fields[0]
            if cell not in wanted:
                continue
            require(cell not in info, f"Duplicate SCP1884 cell metadata: {cell}")
            sample, donor = fields[1], fields[8]
            require(sample in sample_rows, f"SCP1884 sample absent from crosswalk: {sample}")
            require(sample_rows[sample]["donor_id"] == donor, f"SCP1884 donor mismatch for {sample}")
            arm = "OUTSIDE_REGISTERED_ARMS"
            if sample in m02_samples:
                arm = "M02"
            elif sample in m03_samples:
                arm = "M03"
            require(not (arm in {"M02", "M03"} and donor in exclusions), f"Excluded donor entered {arm}: {donor}")
            info[cell] = {
                "sample": sample,
                "donor": donor,
                "metadata_detected_genes": int(float(fields[3])),
                "metadata_total_counts": int(float(fields[4])),
                "arm": arm,
            }
    require(set(info) == wanted, "SCP1884 barcode-to-metadata universe mismatch")
    ordered = [info[barcode] for barcode in barcodes]
    arm_samples = {arm: {item["sample"] for item in ordered if item["arm"] == arm} for arm in ("M02", "M03")}
    arm_donors = {arm: {item["donor"] for item in ordered if item["arm"] == arm} for arm in ("M02", "M03")}
    require((len(arm_samples["M02"]), len(arm_donors["M02"])) == (8, 5), "Unexpected M02 sample/donor counts")
    require((len(arm_samples["M03"]), len(arm_donors["M03"])) == (33, 17), "Unexpected M03 sample/donor counts")
    return ordered, {"metadata_rows": total_rows, "matched_rows": len(info), "arm_samples": arm_samples, "arm_donors": arm_donors}


def matrix_header(path: Path) -> tuple[str, int, int, int]:
    with path.open("r", encoding="ascii", newline="") as handle:
        banner = handle.readline().strip()
        require(banner == "%%MatrixMarket matrix coordinate integer general", f"Unexpected Matrix Market banner in {path}: {banner}")
        while True:
            line = handle.readline()
            require(line != "", f"Missing dimensions in {path}")
            if not line.startswith("%"):
                fields = line.split()
                require(len(fields) == 3, f"Malformed dimensions in {path}")
                return banner, int(fields[0]), int(fields[1]), int(fields[2])


def fmt(value: float | int) -> str:
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if not math.isfinite(float(value)):
        return "NA_NONFINITE"
    return format(float(value), ".12g")


def summarize_metric(
    dataset: str,
    scope: str,
    values: np.ndarray,
    scope_mask: np.ndarray,
    metric: str,
    unit: str,
    metadata_values: np.ndarray | None,
    metadata_field: str,
) -> dict[str, object]:
    selected = np.asarray(values[scope_mask], dtype=np.float64)
    finite = np.isfinite(selected)
    finite_values = selected[finite]
    require(finite_values.size > 0, f"No finite {metric} values for {dataset} {scope}")
    q1, median, q3 = np.quantile(finite_values, [0.25, 0.5, 0.75])
    if metadata_values is None:
        compared = "NA_NOT_AVAILABLE"
        mismatches = "NA_NOT_AVAILABLE"
        comparison = "NA_NOT_AVAILABLE"
    else:
        meta = np.asarray(metadata_values[scope_mask], dtype=np.int64)
        raw = np.asarray(np.rint(selected), dtype=np.int64)
        compared = str(len(meta))
        mismatches_n = int(np.count_nonzero(meta != raw))
        mismatches = str(mismatches_n)
        comparison = "PASS_EXACT" if mismatches_n == 0 else "DESCRIPTIVE_MISMATCH_RECORDED"
    return {
        "run_id": RUN_ID,
        "dataset_identifier": dataset,
        "analysis_scope": scope,
        "metric": metric,
        "unit": unit,
        "cell_count_in_scope": int(scope_mask.sum()),
        "finite_value_count": int(finite.sum()),
        "missing_or_nonfinite_count": int((~finite).sum()),
        "minimum": fmt(float(finite_values.min())),
        "q1": fmt(float(q1)),
        "median": fmt(float(median)),
        "mean": fmt(float(finite_values.mean())),
        "q3": fmt(float(q3)),
        "maximum": fmt(float(finite_values.max())),
        "raw_matrix_source": "REGISTERED_RAW_INTEGER_COUNT_MATRIX",
        "metadata_comparison_field": metadata_field,
        "metadata_cells_compared": compared,
        "metadata_mismatch_count": mismatches,
        "metadata_comparison_status": comparison,
        "threshold_or_filter_applied": "NONE_DESCRIPTIVE_ONLY",
    }


def audit_matrix(
    dataset: str,
    matrix_path: Path,
    barcodes: list[str],
    feature_map: dict[str, object],
    metadata: list[dict[str, object]],
    metadata_summary: dict[str, object],
    expected_hash: str,
) -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
    banner, n_features, n_cells, header_nnz = matrix_header(matrix_path)
    require(n_features == feature_map["source_feature_count"], f"{dataset} matrix-feature dimension mismatch")
    require(n_cells == len(barcodes), f"{dataset} matrix-barcode dimension mismatch")
    print(f"[{dataset}] loading sparse Matrix Market object", flush=True)
    matrix = mmread(matrix_path)
    require(isspmatrix_coo(matrix), f"{dataset} did not load as sparse COO")
    require(matrix.shape == (n_features, n_cells), f"{dataset} loaded shape mismatch")
    raw_nnz = int(matrix.nnz)
    require(raw_nnz == header_nnz, f"{dataset} header nnz mismatch")
    require(np.issubdtype(matrix.data.dtype, np.integer), f"{dataset} data are not integer typed")
    require(np.isfinite(matrix.data).all(), f"{dataset} contains nonfinite stored values")
    require((matrix.data >= 0).all(), f"{dataset} contains negative counts")
    raw_zero_entries = int(np.count_nonzero(matrix.data == 0))
    matrix.sum_duplicates()
    duplicate_coordinate_count = raw_nnz - int(matrix.nnz)
    require((matrix.data >= 0).all(), f"{dataset} duplicate collapse created negative values")
    positive = matrix.data > 0
    rows = matrix.row[positive]
    cols = matrix.col[positive]
    data = matrix.data[positive]
    total_counts_float = np.bincount(cols, weights=data, minlength=n_cells)
    require(np.all(total_counts_float <= np.iinfo(np.int64).max), f"{dataset} count overflow")
    total_counts = np.rint(total_counts_float).astype(np.int64)
    detected_genes = np.bincount(cols, minlength=n_cells).astype(np.int64)
    mito_source_rows = np.array([bool(symbol and symbol.startswith("MT-")) for symbol in feature_map["mapped"]], dtype=bool)
    mito_selector = mito_source_rows[rows]
    mito_counts_float = np.bincount(cols[mito_selector], weights=data[mito_selector], minlength=n_cells)
    mito_counts = np.rint(mito_counts_float).astype(np.int64)
    mito_prop = np.full(n_cells, np.nan, dtype=np.float64)
    nonzero_total = total_counts > 0
    mito_prop[nonzero_total] = mito_counts[nonzero_total] / total_counts[nonzero_total]

    metadata_detected = np.array([int(item["metadata_detected_genes"]) for item in metadata], dtype=np.int64)
    metadata_total = np.array([int(item["metadata_total_counts"]) for item in metadata], dtype=np.int64)
    scopes = ["REGISTERED_MATRIX_ALL"] + sorted({str(item["arm"]) for item in metadata if str(item["arm"]).startswith("M")})
    qc_rows: list[dict[str, object]] = []
    for scope in scopes:
        scope_mask = np.ones(n_cells, dtype=bool) if scope == "REGISTERED_MATRIX_ALL" else np.array([item["arm"] == scope for item in metadata], dtype=bool)
        require(scope_mask.any(), f"No cells in {dataset} {scope}")
        qc_rows.extend([
            summarize_metric(dataset, scope, detected_genes, scope_mask, "detected_genes_per_cell", "source_feature_rows_with_positive_raw_count", metadata_detected, "nGene" if dataset == "SCP259" else "n_genes"),
            summarize_metric(dataset, scope, total_counts, scope_mask, "total_counts_per_cell", "raw_integer_counts", metadata_total, "nUMI" if dataset == "SCP259" else "n_counts"),
            summarize_metric(dataset, scope, mito_prop, scope_mask, "mitochondrial_proportion_per_cell", "fraction_of_raw_counts_mapped_to_canonical_MT_prefix", None, "NA_NOT_AVAILABLE_IN_REGISTERED_METADATA"),
        ])

    integrity = {
        "run_id": RUN_ID,
        "dataset_identifier": dataset,
        "matrix_filename": matrix_path.name,
        "object_type": "MATRIX_MARKET_COORDINATE_INTEGER_GENERAL_SPARSE",
        "matrix_orientation": "FEATURES_X_CELLS",
        "matrix_dimensions": f"{n_features}x{n_cells}",
        "feature_count": n_features,
        "barcode_count": n_cells,
        "metadata_row_count": metadata_summary["metadata_rows"],
        "matched_metadata_barcode_count": metadata_summary["matched_rows"],
        "header_nonzero_entries": header_nnz,
        "loaded_nonzero_entries_before_duplicate_sum": raw_nnz,
        "loaded_nonzero_entries_after_duplicate_sum": int(matrix.nnz),
        "duplicate_coordinate_count": duplicate_coordinate_count,
        "explicit_zero_entry_count": raw_zero_entries,
        "minimum_stored_count": int(matrix.data.min()) if matrix.nnz else 0,
        "maximum_stored_count": int(matrix.data.max()) if matrix.nnz else 0,
        "count_semantics_status": "PASS_FINITE_NONNEGATIVE_INTEGER",
        "barcode_identifier_status": "PASS_EXACT_UNIQUE_METADATA_UNIVERSE",
        "feature_identifier_status": "PASS_FROZEN_HGNC_MAPPING_AUDITED",
        "mapped_source_feature_rows": feature_map["mapped_source_rows"],
        "canonical_feature_count_after_declared_collapse": feature_map["canonical_feature_count"],
        "unmapped_source_feature_rows": feature_map["unmapped_source_rows"],
        "duplicate_canonical_groups": len(feature_map["duplicate_canonical_groups"]),
        "expected_sha256": expected_hash,
        "observed_sha256_preopen": expected_hash,
        "integrity_status": "PASS",
    }
    small = {
        "total_counts": total_counts,
        "detected_genes": detected_genes,
        "mitochondrial_proportion": mito_prop,
        "zero_total_cells": int((total_counts == 0).sum()),
        "raw_detected_gene_metadata_mismatches": int(np.count_nonzero(metadata_detected != detected_genes)),
        "raw_total_count_metadata_mismatches": int(np.count_nonzero(metadata_total != total_counts)),
    }
    del matrix, rows, cols, data, positive, total_counts_float, mito_counts_float, mito_counts, mito_source_rows, mito_selector
    gc.collect()
    print(f"[{dataset}] sparse audit complete", flush=True)
    return integrity, qc_rows, small


def membership_genes(path: Path) -> list[str]:
    rows = read_csv(path, "\t")
    require(rows and "gene_symbol" in rows[0], f"Missing gene_symbol in {path}")
    genes = [row["gene_symbol"] for row in rows]
    require(len(genes) == len(set(genes)), f"Duplicate registered gene in {path}")
    return genes


def build_representation_outputs(
    datasets: dict[str, dict[str, object]],
    arm_counts: dict[str, dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    state_registry = read_csv(STATE_REGISTRY)
    program_registry = read_csv(PROGRAM_REGISTRY)
    model_registry = {row["model_id"]: row for row in read_csv(MODEL_REGISTRY)}
    require([row["state_id"] for row in state_registry] == [f"SP{i:02d}" for i in range(1, 8)], "Unexpected state registry")
    require(len(program_registry) == 3, "Unexpected program registry")
    state_memberships: dict[str, list[str]] = {}
    for state in state_registry:
        path = STATE_ROOT / Path(state["membership_file"]).name
        genes = membership_genes(path)
        require(len(genes) == int(state["n_genes"]), f"State size mismatch: {state['state_id']}")
        state_memberships[state["state_id"]] = genes
    program_memberships: dict[str, list[str]] = {}
    for program in program_registry:
        path = PROGRAM_ROOT / "programs" / Path(program["membership_file"]).name
        genes = membership_genes(path)
        require(len(genes) == int(program["n_genes"]), f"Program size mismatch: {program['program_id']}")
        program_memberships[program["program_id"]] = genes

    arm_to_dataset = {"M01": "SCP259", "M02": "SCP1884", "M03": "SCP1884"}
    state_rows: list[dict[str, object]] = []
    state_pass_by_arm: dict[str, list[bool]] = defaultdict(list)
    for arm in ("M01", "M02", "M03"):
        dataset = arm_to_dataset[arm]
        universe = datasets[dataset]["feature_map"]["mapped_universe"]
        counts = arm_counts[arm]
        for state in state_registry:
            genes = state_memberships[state["state_id"]]
            mapped = [gene for gene in genes if gene in universe]
            missing = [gene for gene in genes if gene not in universe]
            threshold = max(3, math.ceil(0.80 * len(genes)))
            coverage_pass = len(mapped) >= threshold
            state_pass_by_arm[arm].append(coverage_pass)
            if not coverage_pass or counts["cell_count"] == 0:
                classification = "NOT_REPRESENTED"
                represented_cells = 0
                represented_samples = 0
                represented_donors = 0
            else:
                represented_cells = counts["cell_count"]
                represented_samples = counts["sample_count"]
                represented_donors = counts["donor_count"]
                if len(mapped) < len(genes) or dataset == "SCP1884" or counts["donor_count"] == int(model_registry[arm]["minimum_n"]):
                    classification = "LIMITED"
                else:
                    classification = "AVAILABLE"
            state_rows.append({
                "run_id": RUN_ID,
                "analysis_arm_id": arm,
                "dataset_identifier": dataset,
                "state_id": state["state_id"],
                "state_name": state["state_name"],
                "state_role": state["primary_or_exploratory"],
                "registered_gene_count": len(genes),
                "mapped_gene_count": len(mapped),
                "missing_gene_count": len(missing),
                "mapped_genes": ";".join(mapped) if mapped else "NA_NONE",
                "missing_genes": ";".join(missing) if missing else "NA_NONE",
                "coverage_proportion": fmt(len(mapped) / len(genes)),
                "frozen_coverage_requirement": f">=max(3,ceiling(0.80*{len(genes)}))={threshold}",
                "coverage_status": "PASS" if coverage_pass else "FAIL_NOT_ESTIMABLE_FOR_AFFECTED_TESTS",
                "represented_cell_count": represented_cells,
                "represented_sample_count": represented_samples,
                "represented_donor_count": represented_donors,
                "representation_count_definition": "FROZEN_ELIGIBLE_LINKED_CELLS_SAMPLES_DONORS_FOR_WHICH_SCORE_WOULD_BE_STRUCTURALLY_COMPUTABLE; NOT_STATE_ASSIGNMENT_OR_SCORE_POSITIVITY",
                "classification": classification,
                "classification_rule": "NOT_REPRESENTED if frozen coverage fails or zero eligible cells; LIMITED if coverage passes with partial gene coverage, bounded SCP1884 metadata, or donor count at floor; otherwise AVAILABLE",
                "scientific_computation_performed": "NONE_NO_STATE_SCORE_NO_CELL_CLASSIFICATION",
            })

    program_rows: list[dict[str, object]] = []
    mask_pass: dict[tuple[str, str], list[bool]] = defaultdict(list)
    mask_coverages: dict[tuple[str, str], list[float]] = defaultdict(list)
    for dataset in ("SCP259", "SCP1884"):
        universe = datasets[dataset]["feature_map"]["mapped_universe"]
        for program in program_registry:
            program_id = program["program_id"]
            genes = program_memberships[program_id]
            mapped = [gene for gene in genes if gene in universe]
            missing = [gene for gene in genes if gene not in universe]
            full_threshold = max(3, math.ceil(0.80 * len(genes)))
            full_pass = len(mapped) >= full_threshold
            passed_masks = 0
            failed_masks: list[str] = []
            min_mask_coverage = 1.0
            for state in state_registry:
                state_id = state["state_id"]
                mask_path = MASK_ROOT / f"{program_id}__{state_id}__NONOVERLAP_MASK.tsv"
                mask_genes = membership_genes(mask_path)
                mapped_mask = sum(gene in universe for gene in mask_genes)
                mask_threshold = max(3, math.ceil(0.80 * len(mask_genes)))
                passed = mapped_mask >= mask_threshold
                mask_pass[(dataset, program_id)].append(passed)
                mask_coverages[(dataset, program_id)].append(mapped_mask / len(mask_genes))
                min_mask_coverage = min(min_mask_coverage, mapped_mask / len(mask_genes))
                if passed:
                    passed_masks += 1
                else:
                    failed_masks.append(state_id)
            if not full_pass or passed_masks == 0:
                classification = "NOT_REPRESENTED"
            elif passed_masks < 7 or len(mapped) < len(genes) or dataset == "SCP1884":
                classification = "LIMITED"
            else:
                classification = "AVAILABLE"
            program_rows.append({
                "run_id": RUN_ID,
                "dataset_identifier": dataset,
                "program_id": program_id,
                "program_role": program["primary_or_exploratory"],
                "total_registered_genes": len(genes),
                "successfully_mapped_genes": len(mapped),
                "missing_gene_count": len(missing),
                "missing_genes": ";".join(missing) if missing else "NA_NONE",
                "coverage_proportion": fmt(len(mapped) / len(genes)),
                "frozen_full_program_coverage_requirement": f">=max(3,ceiling(0.80*{len(genes)}))={full_threshold}",
                "full_program_coverage_status": "PASS" if full_pass else "FAIL",
                "state_specific_nonoverlap_masks_passing": passed_masks,
                "state_specific_nonoverlap_masks_total": 7,
                "minimum_nonoverlap_mask_coverage_proportion": fmt(min_mask_coverage),
                "failed_nonoverlap_mask_state_ids": ";".join(failed_masks) if failed_masks else "NA_NONE",
                "dataset_specific_availability": classification,
                "gene_replacement_or_reweighting": "NONE",
                "program_score_calculated": "NO",
            })

    donor_rows: list[dict[str, object]] = []
    for arm in ("M01", "M02", "M03"):
        dataset = arm_to_dataset[arm]
        counts = arm_counts[arm]
        state_passes = sum(state_pass_by_arm[arm])
        program_full_passes = sum(row["full_program_coverage_status"] == "PASS" for row in program_rows if row["dataset_identifier"] == dataset)
        masks = [passed for key, values in mask_pass.items() if key[0] == dataset for passed in values]
        mask_passes = sum(masks)
        donor_floor = int(model_registry[arm]["minimum_n"])
        if counts["donor_count"] < donor_floor or counts["cell_count"] == 0 or state_passes == 0 or mask_passes == 0:
            classification = "NOT_ESTIMABLE"
        else:
            prior_limited = True
            incomplete_coverage = state_passes < 7 or program_full_passes < 3 or mask_passes < 21
            classification = "LIMITED" if prior_limited or incomplete_coverage else "FEASIBLE"
        donor_rows.append({
            "run_id": RUN_ID,
            "analysis_arm_id": arm,
            "dataset_identifier": dataset,
            "frozen_role": model_registry[arm]["primary_or_exploratory"],
            "donor_count": counts["donor_count"],
            "sample_count": counts["sample_count"],
            "represented_cell_count": counts["cell_count"],
            "minimum_donor_count": donor_floor,
            "states_passing_coverage": state_passes,
            "states_total": 7,
            "full_programs_passing_coverage": program_full_passes,
            "full_programs_total": 3,
            "program_state_nonoverlap_masks_passing": mask_passes,
            "program_state_nonoverlap_masks_total": 21,
            "state_coverage_status": "PASS_ALL" if state_passes == 7 else "PARTIAL_NOT_ESTIMABLE_ROWS_RETAINED",
            "program_coverage_status": "PASS_ALL" if program_full_passes == 3 and mask_passes == 21 else "PARTIAL_NOT_ESTIMABLE_ROWS_RETAINED",
            "classification": classification,
            "structural_basis": "Frozen donor floor, exact cell-sample-donor linkage, cohort feature coverage, and all 21 prespecified non-overlap masks assessed before scoring",
            "limitations": arm_counts[arm]["limitations"],
            "model_fit_or_hypothesis_test_performed": "NONE",
        })

    details = {
        "state_registry_rows": len(state_registry),
        "program_registry_rows": len(program_registry),
        "state_rows": len(state_rows),
        "program_rows": len(program_rows),
        "donor_rows": len(donor_rows),
    }
    return state_rows, program_rows, donor_rows, details


def main() -> None:
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    run_manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    phase3b1_qa = json.loads(PHASE3B1_QA.read_text(encoding="utf-8"))
    require(run_manifest["run_id"] == RUN_ID, "Run identity mismatch")
    require(phase3b1_qa["completion_state"] == "C1R_PHASE3B1_PASS_READY_FOR_PHASE3B2", "Phase 3B-1 readiness token absent")

    prompt_clarifications = [
        "Represented cell count is the exact frozen eligible linked cell universe for which a score would be structurally computable when coverage passes; it is not a state assignment, score threshold, or positive-cell count.",
        "Coverage and feasibility labels use only frozen >=80% and >=3-gene coverage, exact barcode/sample/donor linkage, the n>=5 donor floor, and inherited authority limitations; no threshold was selected after inspection.",
        "Phase PASS means the controlled audit completed without a source/companion/count/barcode/mapping hard stop. It does not assert biological adequacy and does not authorize Phase 3B-3.",
    ]

    prechecks = {
        "phase3b1_manifest": verify_manifest(ROOT, PHASE3B1_MANIFEST, "relative_path", "size_bytes", "sha256", "\t"),
        "phase3a_manifest": verify_manifest(PHASE3A_ROOT, PHASE3A_MANIFEST, "relative_path", "size_bytes", "sha256", ","),
        "frozen_authorities": verify_authorities(),
        "environment": verify_environment(),
    }
    input_precheck, input_hashes_before = verify_inputs()
    prechecks["registered_inputs"] = input_precheck

    hgnc = load_hgnc()
    dataset_specs = {
        "SCP259": {"matrix": SCP259_MATRIX, "features": SCP259_FEATURES, "barcodes": SCP259_BARCODES},
        "SCP1884": {"matrix": SCP1884_MATRIX, "features": SCP1884_FEATURES, "barcodes": SCP1884_BARCODES},
    }
    for dataset, spec in dataset_specs.items():
        spec["barcodes_list"] = load_lines(spec["barcodes"])
        spec["feature_map"] = map_features(dataset, spec["features"], hgnc)
        if dataset == "SCP259":
            spec["metadata"], spec["metadata_summary"] = load_scp259_metadata(spec["barcodes_list"])
        else:
            spec["metadata"], spec["metadata_summary"] = load_scp1884_metadata(spec["barcodes_list"])

    feature_audit_rows = dataset_specs["SCP259"]["feature_map"]["audit_rows"] + dataset_specs["SCP1884"]["feature_map"]["audit_rows"]
    write_tsv(FEATURE_AUDIT, list(feature_audit_rows[0]), feature_audit_rows)

    matrix_rows: list[dict[str, object]] = []
    qc_rows: list[dict[str, object]] = []
    scan_details: dict[str, object] = {}
    for dataset in ("SCP259", "SCP1884"):
        spec = dataset_specs[dataset]
        integrity, dataset_qc, small = audit_matrix(
            dataset,
            spec["matrix"],
            spec["barcodes_list"],
            spec["feature_map"],
            spec["metadata"],
            spec["metadata_summary"],
            input_hashes_before[str(spec["matrix"])],
        )
        matrix_rows.append(integrity)
        qc_rows.extend(dataset_qc)
        scan_details[dataset] = {
            "zero_total_cells": small["zero_total_cells"],
            "raw_detected_gene_metadata_mismatches": small["raw_detected_gene_metadata_mismatches"],
            "raw_total_count_metadata_mismatches": small["raw_total_count_metadata_mismatches"],
        }
        del small
        gc.collect()

    arm_counts: dict[str, dict[str, object]] = {}
    arm_limitations = {
        "M01": "Broad-colon primary context; exact subsegment unresolved for 15/133 source samples overall; complete platform/chemistry mapping unavailable.",
        "M02": "Exactly at n=5 donor floor; bounded SCP1884 author metadata support; small-sample/model fragility; not pristine independent validation.",
        "M03": "Exploratory role; bounded SCP1884 author metadata support; cannot rescue or replace M02.",
    }
    for arm, dataset in (("M01", "SCP259"), ("M02", "SCP1884"), ("M03", "SCP1884")):
        metadata = dataset_specs[dataset]["metadata"]
        selected = [item for item in metadata if item["arm"] == arm]
        arm_counts[arm] = {
            "dataset": dataset,
            "cell_count": len(selected),
            "sample_count": len({item["sample"] for item in selected}),
            "donor_count": len({item["donor"] for item in selected}),
            "limitations": arm_limitations[arm],
        }

    state_rows, program_rows, donor_rows, representation_details = build_representation_outputs(dataset_specs, arm_counts)

    # Prove read-only execution by rehashing all registered inputs and frozen snapshots after inspection.
    input_postcheck, input_hashes_after = verify_inputs()
    require(input_hashes_before == input_hashes_after, "Registered input hashes changed during Phase 3B-2")
    authority_postcheck = verify_authorities()
    for row in matrix_rows:
        matrix_path = dataset_specs[row["dataset_identifier"]]["matrix"]
        row["observed_sha256_postaudit"] = input_hashes_after[str(matrix_path)]
        row["read_only_hash_stability"] = "PASS_UNCHANGED"

    write_tsv(MATRIX_SUMMARY, list(matrix_rows[0]), matrix_rows)
    write_tsv(CELL_QC, list(qc_rows[0]), qc_rows)
    write_tsv(STATE_SUMMARY, list(state_rows[0]), state_rows)
    write_tsv(PROGRAM_SUMMARY, list(program_rows[0]), program_rows)
    write_tsv(DONOR_PRECHECK, list(donor_rows[0]), donor_rows)

    matrix_table = "\n".join(
        f"| {row['dataset_identifier']} | {row['matrix_dimensions']} | {int(row['header_nonzero_entries']):,} | {row['count_semantics_status']} | {row['integrity_status']} |"
        for row in matrix_rows
    )
    state_table = "\n".join(
        f"| {arm} | {sum(row['analysis_arm_id'] == arm and row['coverage_status'] == 'PASS' for row in state_rows)}/7 | "
        f"{Counter(row['classification'] for row in state_rows if row['analysis_arm_id'] == arm)} |"
        for arm in ("M01", "M02", "M03")
    )
    program_table = "\n".join(
        f"| {dataset} | {sum(row['dataset_identifier'] == dataset and row['full_program_coverage_status'] == 'PASS' for row in program_rows)}/3 | "
        f"{sum(int(row['state_specific_nonoverlap_masks_passing']) for row in program_rows if row['dataset_identifier'] == dataset)}/21 |"
        for dataset in ("SCP259", "SCP1884")
    )
    donor_table = "\n".join(
        f"| {row['analysis_arm_id']} | {row['donor_count']} | {row['sample_count']} | {row['represented_cell_count']} | {row['classification']} |"
        for row in donor_rows
    )
    report = f"""# C1R Phase 3B-2 controlled QC and representation audit report

Run ID: `{RUN_ID}`  
Executed: **{timestamp} (Asia/Shanghai)**  
Mode: **descriptive technical QC and structural representation audit only**

## 1. Prompt review and minimal execution clarifications

The Phase 3B-2 prompt is scientifically bounded and authorized by the live Phase 3A execution rules plus the exact Phase 3B-1 completion token. It was executed after three non-scientific clarifications; no program, state, mapping, cohort, exclusion, model, or threshold changed.

1. {prompt_clarifications[0]}
2. {prompt_clarifications[1]}
3. {prompt_clarifications[2]}

## 2. Pre-open authority and environment controls

- Phase 3B-1 manifest: **{prechecks['phase3b1_manifest']['rows']}/{prechecks['phase3b1_manifest']['rows']} PASS**.
- Phase 3A authorization manifest: **{prechecks['phase3a_manifest']['rows']}/{prechecks['phase3a_manifest']['rows']} PASS**.
- Frozen authority snapshots: **{prechecks['frozen_authorities']['rows']}/{prechecks['frozen_authorities']['rows']} PASS**, read-only, byte-size and SHA-256.
- Registered inputs: **8/8 PASS** before opening and **8/8 PASS** after audit; hashes were unchanged.
- Exact environment: Python **{prechecks['environment']['python_version']}**, SciPy **{prechecks['environment']['scipy_version']}**, locked direct packages and one-thread variables PASS.
- D: free space: **{prechecks['environment']['free_space_bytes_D'] / 1024**3:.2f} GiB**, above the frozen 50 GiB floor.
- Processing was one cohort at a time. Each Matrix Market object remained sparse; no complete matrix was densified or written back.

## 3. Matrix and object integrity audit

| Dataset | Dimensions | Header stored entries | Count semantics | Integrity |
|---|---:|---:|---|---|
{matrix_table}

Both feature companions and barcode companions matched the declared matrix orientation and dimensions. Every registered barcode matched exactly one authorized metadata row. The frozen HGNC reference was used deterministically, and every source feature row is exposed in `outputs/qc/phase3b2_feature_mapping_audit.tsv`. Duplicate canonical symbols were audited under the frozen sparse-sum collapse rule; no score or transformed matrix was produced.

## 4. Descriptive cell-level QC

`cell_qc_characteristics.tsv` contains **{len(qc_rows)}** prespecified summary rows across the full registered matrices and M01-M03 scopes. It reports raw detected source-feature counts, total raw counts, and mitochondrial raw-count proportions (canonical `MT-` prefix after frozen mapping), with minimum, quartiles, mean, median, and maximum.

SCP259 raw-matrix versus registered metadata mismatches were **{scan_details['SCP259']['raw_detected_gene_metadata_mismatches']:,}** cells for detected genes and **{scan_details['SCP259']['raw_total_count_metadata_mismatches']:,}** for total counts. SCP1884 mismatches were **{scan_details['SCP1884']['raw_detected_gene_metadata_mismatches']:,}** and **{scan_details['SCP1884']['raw_total_count_metadata_mismatches']:,}**, respectively. These are recorded descriptively and were not used to filter, remove, reassign, or reweight any cell, sample, donor, gene, program, state, or arm.

## 5. Frozen epithelial-state representation

| Arm | States passing frozen coverage | Classification counts |
|---|---:|---|
{state_table}

All seven SP01-SP07 definitions were assessed only by exact frozen membership against each cohort's mapped feature universe and exact eligible cell/sample/donor linkage. `represented_cell_count` is structural eligibility, not a score-derived state label. No state score, threshold, positive-cell call, clustering, or biological interpretation was generated.

## 6. Frozen genetic-program coverage

| Dataset | Full programs passing | State-specific non-overlap masks passing |
|---|---:|---:|
{program_table}

The primary IBD and exploratory CD/UC programs were assessed without replacement or reweighting. The output records full-program coverage plus all 21 frozen program-state non-overlap masks per dataset because those masks, rather than overlapping full programs, control downstream estimability.

## 7. Donor-level analytical feasibility precheck

| Arm | Donors | Samples | Structurally represented cells | Class |
|---|---:|---:|---:|---|
{donor_table}

This classification is structural only. It does not pre-adjudicate score variance, complete cases, model rank, residual degrees of freedom, HC3 leverage, effect estimates, P values, or biological evidence. M01 remains the broad-colon UC primary application; M02 remains the bounded CD-colon inflamed portability assessment; M03 remains exploratory and cannot rescue M02.

## 8. Pass criteria and prohibited-operation audit

- Matrix integrity verified: **PASS**.
- QC characteristics documented: **PASS**.
- State representation assessed: **PASS**.
- Genetic-program and non-overlap-mask coverage assessed: **PASS**.
- Donor feasibility documented: **PASS**.
- Filtering/removal/redefinition: **0 operations**.
- Normalization, batch correction, integration, dimensional reduction: **0 operations**.
- State/program scoring, enrichment, association tests, regression, hypothesis tests, effect estimation: **0 operations**.
- Frozen authority modifications: **0; 8/8 inputs and 107/107 snapshots reverified unchanged after audit**.

# C1R_PHASE3B2_PASS_READY_FOR_PHASE3B3

This is a Phase 3B-2 completion state only. Phase 3B-3, scoring, modeling, association analysis, biological interpretation, and any later phase were not started.

`NEXT_PHASE_AUTOSTART = FORBIDDEN`
"""
    write_text(REPORT, report)

    log_text = f"""# C1R Phase 3B-2 execution log

Run ID: `{RUN_ID}`  
Timestamp: **{timestamp} (Asia/Shanghai)**

1. Reviewed the supplied prompt against live Phase 3A execution rules and the exact Phase 3B-1 readiness token.
2. Applied only three mechanical clarifications recorded in the main report; no scientific authority changed.
3. Verified Phase 3B-1 and Phase 3A manifests, 107 frozen read-only snapshots, eight registered inputs, exact Python/package locks, thread limits, and storage floor.
4. Audited SCP259 then SCP1884, one sparse cohort at a time, without full-matrix densification.
5. Verified complete Matrix Market shape, stored-entry count, finite nonnegative integer semantics, companion rows, barcode-to-metadata linkage, and pre/post hashes.
6. Computed descriptive raw-count QC summaries only; no thresholds or removals were applied.
7. Applied the frozen HGNC mapping for feature coverage and wrote a complete source-row mapping audit.
8. Assessed SP01-SP07, the three frozen programs, all 21 program-state masks per dataset, and M01-M03 structural feasibility without scoring or modeling.
9. Reverified all inputs and frozen snapshots after inspection and generated a self-excluding output manifest.
10. Did not start Phase 3B-3 or any downstream inference.

`PHASE3B2_EXECUTION_LOG_STATUS = PASS`
"""
    write_text(EXECUTION_LOG, log_text)

    qa = {
        "schema_version": "C1R_PHASE3B2_QA_V1.0",
        "run_id": RUN_ID,
        "timestamp": timestamp,
        "prompt_review": {"outcome": "EXECUTED_WITH_MINIMAL_NONSCIENTIFIC_CLARIFICATIONS", "clarifications": prompt_clarifications},
        "prechecks": prechecks,
        "postchecks": {"registered_inputs": input_postcheck, "frozen_authorities": authority_postcheck, "input_hash_stability": "PASS_8_OF_8"},
        "hgnc_reference": {"path": str(HGNC_REFERENCE), "rows": hgnc["rows"], "sha256": hgnc["sha256"]},
        "matrix_integrity": matrix_rows,
        "matrix_scan_details": scan_details,
        "feature_mapping": {
            dataset: {
                "source_feature_count": dataset_specs[dataset]["feature_map"]["source_feature_count"],
                "mapped_source_rows": dataset_specs[dataset]["feature_map"]["mapped_source_rows"],
                "canonical_feature_count": dataset_specs[dataset]["feature_map"]["canonical_feature_count"],
                "unmapped_source_rows": dataset_specs[dataset]["feature_map"]["unmapped_source_rows"],
                "ambiguous_ensembl_source_rows": dataset_specs[dataset]["feature_map"]["ambiguous_ensembl_source_rows"],
                "duplicate_canonical_groups": dataset_specs[dataset]["feature_map"]["duplicate_canonical_groups"],
                "mitochondrial_source_rows": dataset_specs[dataset]["feature_map"]["mitochondrial_source_rows"],
            }
            for dataset in ("SCP259", "SCP1884")
        },
        "output_row_counts": {"matrix_integrity_summary": len(matrix_rows), "cell_qc_characteristics": len(qc_rows), "state_representation_summary": len(state_rows), "genetic_program_coverage_summary": len(program_rows), "donor_feasibility_precheck": len(donor_rows), "feature_mapping_audit": len(feature_audit_rows)},
        "representation_details": representation_details,
        "analysis_arm_counts": arm_counts,
        "forbidden_operations": {
            "filtering_or_removal": 0,
            "normalization": 0,
            "batch_correction_or_integration": 0,
            "dimensional_reduction": 0,
            "state_scores": 0,
            "program_scores": 0,
            "enrichments": 0,
            "associations_or_regressions": 0,
            "hypothesis_tests": 0,
            "effect_estimates": 0,
            "biological_interpretations": 0,
            "frozen_authority_modifications": 0,
            "phase3b3_started": False,
        },
        "completion_state": "C1R_PHASE3B2_PASS_READY_FOR_PHASE3B3",
        "next_phase_autostart": "FORBIDDEN",
    }
    write_text(QA_JSON, json.dumps(qa, ensure_ascii=False, indent=2))

    manifest_members = [REPORT, MATRIX_SUMMARY, CELL_QC, STATE_SUMMARY, PROGRAM_SUMMARY, DONOR_PRECHECK, FEATURE_AUDIT, EXECUTION_LOG, QA_JSON, SCRIPT_PATH]
    manifest_rows = []
    for path in sorted(manifest_members, key=lambda p: p.relative_to(ROOT).as_posix().encode("utf-8")):
        manifest_rows.append({
            "run_id": RUN_ID,
            "relative_path": path.relative_to(ROOT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "manifest_rule": "SELF_EXCLUDED_NON_SELF_HASHING",
        })
    write_tsv(OUTPUT_MANIFEST, ["run_id", "relative_path", "size_bytes", "sha256", "manifest_rule"], manifest_rows)
    manifest_check = verify_manifest(ROOT, OUTPUT_MANIFEST, "relative_path", "size_bytes", "sha256", "\t")
    require(manifest_check["rows"] == 10, "Unexpected Phase 3B-2 manifest row count")
    require(all(path.is_file() and path.stat().st_size > 0 for path in (REPORT, MATRIX_SUMMARY, CELL_QC, STATE_SUMMARY, PROGRAM_SUMMARY, DONOR_PRECHECK)), "Required output missing or empty")
    print(json.dumps({
        "status": "PASS",
        "completion_state": "C1R_PHASE3B2_PASS_READY_FOR_PHASE3B3",
        "required_outputs": [str(path) for path in (REPORT, MATRIX_SUMMARY, CELL_QC, STATE_SUMMARY, PROGRAM_SUMMARY, DONOR_PRECHECK)],
        "manifest_rows": manifest_check["rows"],
        "matrix_rows": len(matrix_rows),
        "cell_qc_rows": len(qc_rows),
        "state_rows": len(state_rows),
        "program_rows": len(program_rows),
        "donor_classes": {row["analysis_arm_id"]: row["classification"] for row in donor_rows},
        "next_phase_autostart": "FORBIDDEN",
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
