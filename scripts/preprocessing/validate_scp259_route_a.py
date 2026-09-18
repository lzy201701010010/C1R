from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


PROJECT = Path(r"D:\SCIfour")
ROUTE_ROOT = PROJECT / "34_PHASE3B2R2_C1R_ADVANCEMENT_ROUTE_ASSESSMENT"
INPUT_ROOT = ROUTE_ROOT / "02_incoming_portal_exact"
OUTPUT_ROOT = ROUTE_ROOT / "03_route_a_remediation_refreeze"
HEADER_AUDIT = OUTPUT_ROOT / "portal_download_headers.tsv"
MATRIX_SCAN_JSON = OUTPUT_ROOT / "matrix_scan_result.json"

MATRIX = INPUT_ROOT / "gene_sorted-Epi.matrix.mtx"
FEATURES = INPUT_ROOT / "Epi.genes.tsv"
BARCODES = INPUT_ROOT / "Epi.barcodes2.tsv"
METADATA = INPUT_ROOT / "all.meta2.txt"

OLD_ROOT = PROJECT / "29_PHASE2C_R2_C1R_INPUT_VALIDATION" / "01_raw_input_freeze"
OLD_MATRIX = OLD_ROOT / "SCP259_HCA_versioned_candidate" / "gene_sorted-Epi.matrix.mtx"
OLD_FEATURES = OLD_ROOT / "SCP259_HCA_public" / "Epi.genes.tsv"
OLD_BARCODES = OLD_ROOT / "SCP259_HCA_public" / "Epi.barcodes2.tsv"
OLD_METADATA = OLD_ROOT / "SCP259_HCA_versioned_candidate" / "all.meta2.txt"

REPORT = OUTPUT_ROOT / "C1R_PHASE3B2R_SCP259_INPUT_REMEDIATION_GATE_REPORT.md"
SOURCE_AUDIT = OUTPUT_ROOT / "scp259_remediation_source_audit.tsv"
MATRIX_AUDIT = OUTPUT_ROOT / "scp259_matrix_integrity_validation.tsv"
COMPANION_AUDIT = OUTPUT_ROOT / "scp259_companion_consistency.tsv"
AUTHORITY_MANIFEST = OUTPUT_ROOT / "scp259_new_authority_manifest.tsv"

RUN_ID = "C1R_P3B2R_ROUTEA_20260913"
AUTHORITY_ID = "C1R_SCP259_INPUT_REMEDIATION_V1"
STUDY_URL = "https://singlecell.broadinstitute.org/single_cell/study/SCP259/intra-and-inter-cellular-rewiring-"
EXPECTED_BANNER = "%%MatrixMarket matrix coordinate integer general"
EXPECTED_ROWS = 20_028
EXPECTED_COLUMNS = 123_006
EXPECTED_NNZ = 174_423_911
EXPECTED_LOCAL_SIZES = {
    "gene_sorted-Epi.matrix.mtx": 2_384_706_723,
    "Epi.genes.tsv": 154_607,
    "Epi.barcodes2.tsv": 3_104_379,
    "all.meta2.txt": 26_391_092,
}
EXPECTED_STORED_SIZES = {
    "gene_sorted-Epi.matrix.mtx": 2_384_706_723,
    "Epi.genes.tsv": 154_607,
    "Epi.barcodes2.tsv": 3_104_379,
    "all.meta2.txt": 4_548_868,
}
EXPECTED_OLD = {
    "gene_sorted-Epi.matrix.mtx": (
        1_208_630_015,
        "FEE3A48BD1C833F4A9A2F97843E0E35EE476971E0C72EBA96CC0F0D8628B4A13",
    ),
    "Epi.genes.tsv": (
        154_607,
        "16AAF68C66C86AED9993B76231F2F268C9F5B1AE4EE21706D713D3042E7995E1",
    ),
    "Epi.barcodes2.tsv": (
        3_104_379,
        "E9F0407A8F663103EFB0598DA4F2189C95F2095F7536F2E77436C39E291555CC",
    ),
    "all.meta2.txt": (
        26_391_092,
        "AC09198B7ACF05C28CA9BAA4FC20CD8C6E39FD797E6D321B42B4FDF07CEAB23D",
    ),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path, chunk_size: int = 32 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def iso_utc_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    require(bool(rows), f"No rows supplied for {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def read_single_column(path: Path) -> list[str]:
    values: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, raw in enumerate(handle, start=1):
            value = raw.rstrip("\r\n")
            require(value != "", f"Blank identifier at {path.name}:{line_number}")
            require("\t" not in value, f"Unexpected extra field at {path.name}:{line_number}")
            values.append(value)
    require(len(values) == len(set(values)), f"Duplicate identifiers in {path.name}")
    return values


def read_header_audit() -> dict[str, dict[str, str]]:
    with HEADER_AUDIT.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows) == 4, f"Expected four object-header rows, observed {len(rows)}")
    by_name = {row["filename"]: row for row in rows}
    require(set(by_name) == set(EXPECTED_STORED_SIZES), "Header audit filenames do not match the four-file package")
    for name, row in by_name.items():
        require(row["http_status"] == "HTTP/1.1 200 OK", f"Header request did not pass for {name}")
        require(int(row["stored_content_length"]) == EXPECTED_STORED_SIZES[name], f"Stored length mismatch for {name}")
        require(row["generation"] not in {"", "NA"}, f"Missing GCS generation for {name}")
    require(by_name["all.meta2.txt"]["stored_content_encoding"].lower() == "gzip", "Metadata object is not registered as gzip")
    for name in ("gene_sorted-Epi.matrix.mtx", "Epi.genes.tsv", "Epi.barcodes2.tsv"):
        require(by_name[name]["stored_content_encoding"].lower() == "identity", f"Unexpected stored encoding for {name}")
    return by_name


def read_matrix_scan() -> dict[str, object]:
    require(MATRIX_SCAN_JSON.is_file(), f"Compiled matrix scan result missing: {MATRIX_SCAN_JSON}")
    raw = json.loads(MATRIX_SCAN_JSON.read_text(encoding="utf-8"))
    key_map = {
        "Banner": "banner",
        "DeclaredRows": "declared_rows",
        "DeclaredColumns": "declared_columns",
        "DeclaredCoordinateRecords": "declared_coordinate_records",
        "ObservedCompleteCoordinateRecords": "observed_complete_coordinate_records",
        "CoordinateDeficit": "coordinate_deficit",
        "MalformedCoordinateRows": "malformed_coordinate_rows",
        "HeaderLineCount": "header_line_count",
        "TotalLineCount": "total_line_count",
        "EofHadTerminalNewline": "eof_had_terminal_newline",
        "RowBoundsValid": "row_bounds_valid",
        "ColumnBoundsValid": "column_bounds_valid",
        "IntegerValuesValid": "integer_values_valid",
        "MinRow": "min_row",
        "MaxRow": "max_row",
        "MinCol": "min_col",
        "MaxCol": "max_col",
        "MinValue": "min_value",
        "MaxValue": "max_value",
        "FirstCoordinate": "first_coordinate",
        "LastCoordinate": "last_coordinate",
        "Sha256": "sha256",
        "IntegrityStatus": "integrity_status",
    }
    require(set(key_map).issubset(raw), "Compiled matrix scan result is missing required fields")
    return {destination: raw[source] for source, destination in key_map.items()}


def inspect_metadata(path: Path, barcodes: list[str]) -> dict[str, object]:
    expected_header = ["NAME", "Cluster", "nGene", "nUMI", "Subject", "Health", "Location", "Sample"]
    expected_types = ["TYPE", "group", "numeric", "numeric", "group", "group", "group", "group"]
    all_names: set[str] = set()
    all_samples: set[str] = set()
    all_donors: set[str] = set()
    barcode_set = set(barcodes)
    epi_names: list[str] = []
    epi_samples: set[str] = set()
    epi_donors: set[str] = set()
    m01_samples: set[str] = set()
    m01_donors: set[str] = set()
    sample_to_donor: dict[str, str] = {}
    malformed_rows = 0
    row_count = 0

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        types = next(reader)
        require(header == expected_header, f"Unexpected metadata header: {header}")
        require(types == expected_types, f"Unexpected metadata TYPE row: {types}")
        for line_number, row in enumerate(reader, start=3):
            row_count += 1
            if len(row) != len(expected_header):
                malformed_rows += 1
                continue
            name, _cluster, _ngene, _numi, subject, health, location, sample = row
            require(name != "", f"Blank metadata NAME at line {line_number}")
            require(subject != "" and sample != "", f"Blank donor/sample identifier at line {line_number}")
            require(name not in all_names, f"Duplicate metadata NAME at line {line_number}: {name}")
            all_names.add(name)
            all_samples.add(sample)
            all_donors.add(subject)
            previous = sample_to_donor.setdefault(sample, subject)
            require(previous == subject, f"Sample maps to multiple donors: {sample}")
            # The matrix universe is defined by the exact registered barcode list,
            # not by the author's broad Location label. Some matrix barcodes have
            # Location=LP in the full metadata and must not be silently discarded.
            if name in barcode_set:
                epi_names.append(name)
                epi_samples.add(sample)
                epi_donors.add(subject)
                if health == "Inflamed" and location == "Epi":
                    m01_samples.add(sample)
                    m01_donors.add(subject)

    require(malformed_rows == 0, f"Malformed metadata rows: {malformed_rows}")
    epi_name_set = set(epi_names)
    return {
        "header": header,
        "types": types,
        "row_count": row_count,
        "unique_name_count": len(all_names),
        "sample_count": len(all_samples),
        "donor_count": len(all_donors),
        "epi_row_count": len(epi_names),
        "epi_unique_name_count": len(epi_name_set),
        "epi_sample_count": len(epi_samples),
        "epi_donor_count": len(epi_donors),
        "m01_sample_count": len(m01_samples),
        "m01_donor_count": len(m01_donors),
        "barcode_set_match": barcode_set == epi_name_set,
        "barcode_order_match": barcodes == epi_names,
        "malformed_rows": malformed_rows,
        "sample_to_donor_conflicts": 0,
    }


def inspect_matrix_market(path: Path, chunk_size: int = 64 * 1024 * 1024) -> dict[str, object]:
    digest = hashlib.sha256()
    header_line_count = 0
    coordinate_records = 0
    malformed_coordinate_rows = 0
    min_row: int | None = None
    max_row: int | None = None
    min_col: int | None = None
    max_col: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    first_coordinate: tuple[int, int, int] | None = None
    last_coordinate: tuple[int, int, int] | None = None
    allowed = b"0123456789+- \t\r\n"

    def consume_region(region: bytes, expected_lines: int) -> None:
        nonlocal coordinate_records, malformed_coordinate_rows
        nonlocal min_row, max_row, min_col, max_col, min_value, max_value
        nonlocal first_coordinate, last_coordinate
        if not region:
            return
        invalid = region.translate(None, allowed)
        if invalid:
            malformed_coordinate_rows += expected_lines
            return
        values = np.fromstring(region, dtype=np.int64, sep=" ")
        if values.size != expected_lines * 3:
            malformed_coordinate_rows += expected_lines
            return
        triples = values.reshape((-1, 3))
        rows = triples[:, 0]
        cols = triples[:, 1]
        vals = triples[:, 2]
        count = int(triples.shape[0])
        coordinate_records += count
        if first_coordinate is None:
            first_coordinate = tuple(int(x) for x in triples[0])
        last_coordinate = tuple(int(x) for x in triples[-1])
        chunk_min_row, chunk_max_row = int(rows.min()), int(rows.max())
        chunk_min_col, chunk_max_col = int(cols.min()), int(cols.max())
        chunk_min_value, chunk_max_value = int(vals.min()), int(vals.max())
        min_row = chunk_min_row if min_row is None else min(min_row, chunk_min_row)
        max_row = chunk_max_row if max_row is None else max(max_row, chunk_max_row)
        min_col = chunk_min_col if min_col is None else min(min_col, chunk_min_col)
        max_col = chunk_max_col if max_col is None else max(max_col, chunk_max_col)
        min_value = chunk_min_value if min_value is None else min(min_value, chunk_min_value)
        max_value = chunk_max_value if max_value is None else max(max_value, chunk_max_value)

    with path.open("rb") as handle:
        banner_raw = handle.readline()
        digest.update(banner_raw)
        header_line_count += 1
        banner = banner_raw.rstrip(b"\r\n").decode("ascii")
        require(banner == EXPECTED_BANNER, f"Unexpected Matrix Market banner: {banner!r}")

        while True:
            raw = handle.readline()
            require(raw != b"", "EOF reached before Matrix Market dimensions")
            digest.update(raw)
            header_line_count += 1
            if raw.startswith(b"%"):
                continue
            dim_fields = raw.split()
            require(len(dim_fields) == 3, "Malformed Matrix Market dimension line")
            n_rows, n_cols, declared_records = map(int, dim_fields)
            break

        carry = b""
        processed_bytes = handle.tell()
        next_progress = 10
        file_size = path.stat().st_size
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
            processed_bytes += len(block)
            data = carry + block
            newline_index = data.rfind(b"\n")
            if newline_index < 0:
                carry = data
                continue
            region = data[: newline_index + 1]
            carry = data[newline_index + 1 :]
            consume_region(region, region.count(b"\n"))
            percent = int(processed_bytes * 100 / file_size)
            if percent >= next_progress:
                print(f"MATRIX_PARSE_PROGRESS={percent}% records={coordinate_records}", flush=True)
                next_progress += 10

        eof_had_terminal_newline = carry == b""
        if carry.strip():
            consume_region(carry, 1)

    row_bounds_valid = min_row is not None and min_row >= 1 and max_row is not None and max_row <= n_rows
    column_bounds_valid = min_col is not None and min_col >= 1 and max_col is not None and max_col <= n_cols
    integer_values_valid = min_value is not None and min_value >= 0
    coordinate_count_match = coordinate_records == declared_records
    integrity_pass = all(
        (
            n_rows == EXPECTED_ROWS,
            n_cols == EXPECTED_COLUMNS,
            declared_records == EXPECTED_NNZ,
            coordinate_count_match,
            malformed_coordinate_rows == 0,
            row_bounds_valid,
            column_bounds_valid,
            integer_values_valid,
        )
    )
    return {
        "banner": banner,
        "declared_rows": n_rows,
        "declared_columns": n_cols,
        "declared_coordinate_records": declared_records,
        "observed_complete_coordinate_records": coordinate_records,
        "coordinate_deficit": declared_records - coordinate_records,
        "malformed_coordinate_rows": malformed_coordinate_rows,
        "header_line_count": header_line_count,
        "total_line_count": header_line_count + coordinate_records + malformed_coordinate_rows,
        "eof_had_terminal_newline": eof_had_terminal_newline,
        "row_bounds_valid": row_bounds_valid,
        "column_bounds_valid": column_bounds_valid,
        "integer_values_valid": integer_values_valid,
        "min_row": min_row,
        "max_row": max_row,
        "min_col": min_col,
        "max_col": max_col,
        "min_value": min_value,
        "max_value": max_value,
        "first_coordinate": first_coordinate,
        "last_coordinate": last_coordinate,
        "sha256": digest.hexdigest().upper(),
        "integrity_status": "PASS" if integrity_pass else "FAIL",
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    audit_time = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

    inputs = [MATRIX, FEATURES, BARCODES, METADATA]
    for path in inputs:
        require(path.is_file(), f"Required current input missing: {path}")
        require(path.stat().st_size == EXPECTED_LOCAL_SIZES[path.name], f"Local byte-size mismatch for {path.name}")

    headers = read_header_audit()
    features = read_single_column(FEATURES)
    barcodes = read_single_column(BARCODES)
    require(len(features) == EXPECTED_ROWS, f"Feature count mismatch: {len(features)}")
    require(len(barcodes) == EXPECTED_COLUMNS, f"Barcode count mismatch: {len(barcodes)}")
    metadata = inspect_metadata(METADATA, barcodes)
    require(metadata["row_count"] == 365_492, f"Metadata row count mismatch: {metadata['row_count']}")
    require(metadata["unique_name_count"] == 365_492, "Metadata NAME values are not unique")
    require(metadata["sample_count"] == 133, f"Metadata sample universe mismatch: {metadata['sample_count']}")
    require(metadata["donor_count"] == 30, f"Metadata donor universe mismatch: {metadata['donor_count']}")
    require(metadata["epi_row_count"] == EXPECTED_COLUMNS, f"Epithelial metadata row count mismatch: {metadata['epi_row_count']}")
    require(metadata["epi_unique_name_count"] == EXPECTED_COLUMNS, "Epithelial metadata identifiers are not unique")
    require(metadata["epi_sample_count"] == 131, f"Epithelial sample count mismatch: {metadata['epi_sample_count']}")
    require(metadata["epi_donor_count"] == 30, f"Epithelial donor count mismatch: {metadata['epi_donor_count']}")
    require(metadata["m01_sample_count"] == 16, f"M01 sample count mismatch: {metadata['m01_sample_count']}")
    require(metadata["m01_donor_count"] == 14, f"M01 donor count mismatch: {metadata['m01_donor_count']}")
    require(bool(metadata["barcode_set_match"]), "Barcode-to-metadata set linkage failed")
    require(bool(metadata["barcode_order_match"]), "Barcode-to-metadata order linkage failed")

    small_hashes = {
        FEATURES.name: sha256_file(FEATURES),
        BARCODES.name: sha256_file(BARCODES),
        METADATA.name: sha256_file(METADATA),
    }
    matrix = read_matrix_scan()
    require(matrix["integrity_status"] == "PASS", f"Matrix integrity failed: {matrix}")
    current_hashes = {MATRIX.name: matrix["sha256"], **small_hashes}

    old_paths = [OLD_MATRIX, OLD_FEATURES, OLD_BARCODES, OLD_METADATA]
    old_hashes: dict[str, str] = {}
    for path in old_paths:
        expected_size, expected_hash = EXPECTED_OLD[path.name]
        require(path.is_file(), f"Historical authority missing: {path}")
        require(path.stat().st_size == expected_size, f"Historical authority size changed: {path.name}")
        observed_hash = sha256_file(path)
        require(observed_hash == expected_hash, f"Historical authority hash changed: {path.name}")
        old_hashes[path.name] = observed_hash

    generations = ";".join(f"{name}:{headers[name]['generation']}" for name in sorted(headers))
    package_status = "PASS"

    source_rows: list[dict[str, object]] = []
    for path, relation in (
        (MATRIX, "EXACT_CURRENT_OFFICIAL_MATRIX"),
        (FEATURES, "EXACT_CURRENT_OFFICIAL_FEATURE_COMPANION"),
        (BARCODES, "EXACT_CURRENT_OFFICIAL_BARCODE_COMPANION"),
        (METADATA, "EXACT_CURRENT_OFFICIAL_METADATA"),
    ):
        header = headers[path.name]
        source_rows.append(
            {
                "candidate_id": f"PORTAL_CURRENT_{path.name}",
                "source_repository_location": STUDY_URL,
                "accession": "SCP259",
                "release_or_version": f"CURRENT_PORTAL_OBJECT_GENERATION_{header['generation']}",
                "filename": path.name,
                "source_relation": relation,
                "portal_stored_size_bytes": header["stored_content_length"],
                "portal_stored_content_encoding": header["stored_content_encoding"],
                "acquired_decoded_size_bytes": path.stat().st_size,
                "sha256_of_local_decoded_bytes": current_hashes[path.name],
                "download_timestamp_utc": iso_utc_from_mtime(path),
                "audit_timestamp_asia_shanghai": audit_time,
                "same_release_acquisition_status": "PASS_SINGLE_AUTHENTICATED_PORTAL_BULK_CONFIG_SESSION",
                "object_generation": header["generation"],
                "acquisition_status": "ACQUIRED_AND_FULLY_VALIDATED",
                "eligibility_status": "ELIGIBLE_NEW_AUTHORITY",
                "evidence": "Authenticated SCP259 bulk-download config; signed URL not retained; object headers captured without credentials",
                "decision": "ACCEPT_IN_C1R_SCP259_INPUT_REMEDIATION_V1",
            }
        )
    source_rows.append(
        {
            "candidate_id": "HISTORICAL_HCA_DCP60_MATRIX",
            "source_repository_location": "https://explore.data.humancellatlas.org/projects/cd61771b-661a-4e19-b269-6e5d95350de6",
            "accession": "SCP259 / cd61771b-661a-4e19-b269-6e5d95350de6",
            "release_or_version": "2022-01-13T10:05:10.443000Z",
            "filename": OLD_MATRIX.name,
            "source_relation": "HISTORICAL_VERSIONED_SCP_ORIGIN_OBJECT",
            "portal_stored_size_bytes": EXPECTED_OLD[OLD_MATRIX.name][0],
            "portal_stored_content_encoding": "NA_HISTORICAL_RECORD",
            "acquired_decoded_size_bytes": OLD_MATRIX.stat().st_size,
            "sha256_of_local_decoded_bytes": old_hashes[OLD_MATRIX.name],
            "download_timestamp_utc": "2026-09-07T15:40:40Z",
            "audit_timestamp_asia_shanghai": audit_time,
            "same_release_acquisition_status": "PASS_HISTORICAL_VERSION_SCOPED_RELATIONSHIP",
            "object_generation": "NA_HISTORICAL_HCA_VERSION",
            "acquisition_status": "PRESERVED_SIZE_AND_SHA256_REVERIFIED",
            "eligibility_status": "INELIGIBLE_STRUCTURAL_TRUNCATION",
            "evidence": "Original 91,725,162-complete-coordinate failure record remains unchanged",
            "decision": "PRESERVE_AS_HISTORICAL_FAILURE_ONLY",
        }
    )
    write_tsv(SOURCE_AUDIT, source_rows)

    matrix_rows = [
        {
            "candidate_id": "PORTAL_CURRENT_2026-09-13",
            "source_accession_release": f"SCP259 / current Portal / {generations}",
            "filename": MATRIX.name,
            "local_path": str(MATRIX),
            "size_bytes": MATRIX.stat().st_size,
            "sha256": current_hashes[MATRIX.name],
            "matrix_market_banner": matrix["banner"],
            "declared_rows": matrix["declared_rows"],
            "declared_columns": matrix["declared_columns"],
            "declared_coordinate_records": matrix["declared_coordinate_records"],
            "observed_complete_coordinate_records": matrix["observed_complete_coordinate_records"],
            "coordinate_deficit": matrix["coordinate_deficit"],
            "malformed_coordinate_rows": matrix["malformed_coordinate_rows"],
            "row_coordinate_range": f"{matrix['min_row']}..{matrix['max_row']}",
            "column_coordinate_range": f"{matrix['min_col']}..{matrix['max_col']}",
            "value_range": f"{matrix['min_value']}..{matrix['max_value']}",
            "eof_completeness": "PASS_COMPLETE_FINAL_COORDINATE" if matrix["last_coordinate"] else "FAIL_NO_FINAL_COORDINATE",
            "terminal_newline_present": matrix["eof_had_terminal_newline"],
            "all_coordinate_rows_parse": "PASS" if matrix["malformed_coordinate_rows"] == 0 else "FAIL",
            "integer_values_valid": "PASS" if matrix["integer_values_valid"] else "FAIL",
            "coordinate_bounds_valid": "PASS" if matrix["row_bounds_valid"] and matrix["column_bounds_valid"] else "FAIL",
            "integrity_status": matrix["integrity_status"],
            "notes": "Entire immutable Matrix Market body streamed and parsed; no repair, reconstruction, conversion, QC, or scientific computation",
        },
        {
            "candidate_id": "HISTORICAL_HCA_DCP60_2022_PRESERVED",
            "source_accession_release": "SCP259 / HCA cd61771b-661a-4e19-b269-6e5d95350de6 / 2022-01-13T10:05:10.443000Z",
            "filename": OLD_MATRIX.name,
            "local_path": str(OLD_MATRIX),
            "size_bytes": OLD_MATRIX.stat().st_size,
            "sha256": old_hashes[OLD_MATRIX.name],
            "matrix_market_banner": EXPECTED_BANNER,
            "declared_rows": EXPECTED_ROWS,
            "declared_columns": EXPECTED_COLUMNS,
            "declared_coordinate_records": EXPECTED_NNZ,
            "observed_complete_coordinate_records": 91_725_162,
            "coordinate_deficit": 82_698_749,
            "malformed_coordinate_rows": 1,
            "row_coordinate_range": "HISTORICAL_FAILURE_RECORD",
            "column_coordinate_range": "HISTORICAL_FAILURE_RECORD",
            "value_range": "HISTORICAL_FAILURE_RECORD",
            "eof_completeness": "FAIL_FINAL_FRAGMENT_1028",
            "terminal_newline_present": "HISTORICAL_FAILURE_RECORD",
            "all_coordinate_rows_parse": "FAIL_FINAL_ROW_HAS_ONE_FIELD",
            "integer_values_valid": "FAIL_INCOMPLETE_TERMINAL_RECORD",
            "coordinate_bounds_valid": "NA_NOT_REPARSED_THIS_RUN",
            "integrity_status": "FAIL_PRESERVED_HISTORICAL_AUTHORITY",
            "notes": "Size and SHA-256 reverified; prior structural failure record retained without mutation",
        },
    ]
    write_tsv(MATRIX_AUDIT, matrix_rows)

    companion_rows = [
        {
            "candidate_package": "PORTAL_CURRENT_ROUTE_A_2026-09-13",
            "matrix_file": MATRIX.name,
            "feature_file": FEATURES.name,
            "barcode_file": BARCODES.name,
            "metadata_or_crosswalk": METADATA.name,
            "matrix_rows": matrix["declared_rows"],
            "feature_count": len(features),
            "row_dimension_status": "PASS",
            "matrix_columns": matrix["declared_columns"],
            "barcode_count": len(barcodes),
            "column_dimension_status": "PASS",
            "feature_identifier_status": f"PASS_{len(features)}_NONEMPTY_UNIQUE",
            "barcode_identifier_status": f"PASS_{len(barcodes)}_NONEMPTY_UNIQUE",
            "metadata_row_count": metadata["row_count"],
            "metadata_unique_name_count": metadata["unique_name_count"],
            "metadata_linkage_status": "PASS_EXACT_SET_AND_ORDER_123006_OF_123006_EPI_BARCODES",
            "full_metadata_sample_count": metadata["sample_count"],
            "full_metadata_donor_count": metadata["donor_count"],
            "epithelial_sample_count": metadata["epi_sample_count"],
            "epithelial_donor_count": metadata["epi_donor_count"],
            "m01_sample_count": metadata["m01_sample_count"],
            "m01_donor_count": metadata["m01_donor_count"],
            "sample_to_donor_status": "PASS_ONE_DONOR_PER_SAMPLE",
            "same_release_acquisition_status": "PASS_SINGLE_AUTHENTICATED_PORTAL_BULK_CONFIG_SESSION",
            "overall_status": package_status,
            "notes": "All four objects acquired together; all.meta2.txt stored gzip length 4548868 and decoded local length 26391092 are both registered",
        }
    ]
    write_tsv(COMPANION_AUDIT, companion_rows)

    manifest_rows: list[dict[str, object]] = []
    historical_specs = (
        (OLD_MATRIX, "HISTORICAL_FAILED_INPUT", "PRESERVED_STRUCTURAL_FAIL"),
        (OLD_FEATURES, "HISTORICAL_COMPANION", "PRESERVED_COMPANION"),
        (OLD_BARCODES, "HISTORICAL_COMPANION", "PRESERVED_COMPANION"),
        (OLD_METADATA, "HISTORICAL_METADATA", "PRESERVED_METADATA"),
    )
    for path, scope, status in historical_specs:
        manifest_rows.append(
            {
                "authority_snapshot_id": "HISTORICAL_PHASE3B0_AUTHORITY_PRESERVED",
                "record_scope": scope,
                "dataset": "SCP259",
                "accession": "SCP259 / HCA cd61771b-661a-4e19-b269-6e5d95350de6",
                "source_release": "HCA_DCP60_2022_VERSION_SCOPED",
                "filename": path.name,
                "local_path": str(path),
                "portal_stored_size_bytes": EXPECTED_OLD[path.name][0],
                "local_decoded_size_bytes": path.stat().st_size,
                "sha256": old_hashes[path.name],
                "filesystem_read_only": bool(getattr(path.stat(), "st_file_attributes", 0) & 1),
                "observed_or_download_timestamp_utc": "2026-09-08T06:53:49Z",
                "object_generation": "NA_HISTORICAL_HCA_VERSION",
                "companion_relationship": "HISTORICAL_SCP259_MATRIX_GROUP",
                "record_status": status,
                "notes": "Original historical authority remains unchanged and is not overwritten by the additive refreeze",
            }
        )
    for path, scope in (
        (MATRIX, "REMEDIATED_MATRIX_INPUT"),
        (FEATURES, "REMEDIATED_FEATURE_COMPANION"),
        (BARCODES, "REMEDIATED_BARCODE_COMPANION"),
        (METADATA, "REMEDIATED_METADATA"),
    ):
        if path == METADATA:
            authority_note = "Official gzip object decoded by the Portal-generated curl --compressed configuration; decoded bytes frozen without manual editing"
        else:
            authority_note = "Official identity-encoded Portal object frozen byte-for-byte without manual editing"
        manifest_rows.append(
            {
                "authority_snapshot_id": AUTHORITY_ID,
                "record_scope": scope,
                "dataset": "SCP259",
                "accession": "SCP259",
                "source_release": "CURRENT_PORTAL_SAME_SESSION_OBJECT_GENERATION_FROZEN",
                "filename": path.name,
                "local_path": str(path),
                "portal_stored_size_bytes": headers[path.name]["stored_content_length"],
                "local_decoded_size_bytes": path.stat().st_size,
                "sha256": current_hashes[path.name],
                "filesystem_read_only": bool(getattr(path.stat(), "st_file_attributes", 0) & 1),
                "observed_or_download_timestamp_utc": iso_utc_from_mtime(path),
                "object_generation": headers[path.name]["generation"],
                "companion_relationship": "PORTAL_CURRENT_ROUTE_A_FOUR_FILE_MATRIX_GROUP",
                "record_status": "FROZEN_PASS",
                "notes": authority_note,
            }
        )
    write_tsv(AUTHORITY_MANIFEST, manifest_rows)

    report = f"""# C1-R Phase 3B-2R SCP259 input remediation gate report

Run ID: `{RUN_ID}`  
Executed: **{audit_time} (Asia/Shanghai)**  
Authority created: `{AUTHORITY_ID}`

## 1. Outcome

Route A succeeded. The complete current official SCP259 epithelial Matrix Market package was acquired through one authenticated Single Cell Portal bulk-download configuration and passed the source, matrix-body, companion, identifier-linkage, and donor-universe gates.

The original HCA DCP60 matrix remains preserved as a historical structural failure. It was neither repaired nor overwritten. Its byte size and frozen SHA-256 were reverified during this run.

No QC, normalization, score calculation, cell-state analysis, association testing, enrichment, modeling, or biological interpretation was performed.

## 2. Source binding and retrieved bytes

The four objects came from the current official `{STUDY_URL}` inventory in one logged-in Portal session. The one-use configuration was used only for retrieval; signed URLs and authentication material are excluded from all authority records. After object-header capture, both temporary signed-URL configuration files were deleted, and the four validated inputs were marked read-only.

| File | Portal stored bytes | Stored encoding | Local decoded bytes | Object generation |
|---|---:|---|---:|---|
| `{MATRIX.name}` | {headers[MATRIX.name]['stored_content_length']} | {headers[MATRIX.name]['stored_content_encoding']} | {MATRIX.stat().st_size} | `{headers[MATRIX.name]['generation']}` |
| `{FEATURES.name}` | {headers[FEATURES.name]['stored_content_length']} | {headers[FEATURES.name]['stored_content_encoding']} | {FEATURES.stat().st_size} | `{headers[FEATURES.name]['generation']}` |
| `{BARCODES.name}` | {headers[BARCODES.name]['stored_content_length']} | {headers[BARCODES.name]['stored_content_encoding']} | {BARCODES.stat().st_size} | `{headers[BARCODES.name]['generation']}` |
| `{METADATA.name}` | {headers[METADATA.name]['stored_content_length']} | {headers[METADATA.name]['stored_content_encoding']} | {METADATA.stat().st_size} | `{headers[METADATA.name]['generation']}` |

The metadata size difference is expected and mechanically explained: GCS registers `all.meta2.txt` as a {headers[METADATA.name]['stored_content_length']}-byte gzip object, while the Portal-generated `curl --compressed` configuration writes the decoded {METADATA.stat().st_size}-byte text. The SHA-256 authority is over the local decoded bytes actually frozen for use.

## 3. Matrix structural validation

- Banner: `{matrix['banner']}`.
- Declared dimensions: **{matrix['declared_rows']:,} rows × {matrix['declared_columns']:,} columns**.
- Declared coordinate records: **{matrix['declared_coordinate_records']:,}**.
- Observed complete coordinate records: **{matrix['observed_complete_coordinate_records']:,}**.
- Coordinate deficit: **{matrix['coordinate_deficit']:,}**.
- Malformed coordinate rows: **{matrix['malformed_coordinate_rows']:,}**.
- Coordinate bounds: rows `{matrix['min_row']}..{matrix['max_row']}`, columns `{matrix['min_col']}..{matrix['max_col']}` — **PASS**.
- Integer value validation: range `{matrix['min_value']}..{matrix['max_value']}` — **PASS**.
- EOF: final coordinate `{matrix['last_coordinate']}` is complete — **PASS**.
- Whole-file SHA-256: `{current_hashes[MATRIX.name]}`.

Matrix structural status: **PASS**.

## 4. Companion consistency and donor universe

- Features: **{len(features):,}** non-empty unique identifiers; equals matrix rows — **PASS**.
- Barcodes: **{len(barcodes):,}** non-empty unique identifiers; equals matrix columns — **PASS**.
- Metadata: **{metadata['row_count']:,}** data rows and **{metadata['unique_name_count']:,}** unique `NAME` values — **PASS**.
- Epithelial linkage: all **{len(barcodes):,}/{len(barcodes):,}** barcodes match the epithelial metadata subset in exact set and order — **PASS**.
- Full metadata universe: **{metadata['sample_count']} samples, {metadata['donor_count']} donors**.
- Epithelial matrix universe: **{metadata['epi_sample_count']} samples, {metadata['epi_donor_count']} donors**.
- Frozen M01 structural context: **{metadata['m01_sample_count']} samples, {metadata['m01_donor_count']} donors**.
- Sample-to-donor mapping: one donor per sample — **PASS**.
- Same-session companion acquisition: **PASS**.

Companion consistency status: **PASS**.

## 5. Additive authority refreeze

`{AUTHORITY_ID}` is created additively in `scp259_new_authority_manifest.tsv`. It contains the four current Portal objects with local byte sizes, SHA-256 hashes, download timestamps, GCS object generations, and companion relationships. The four historical Phase 3B-0 rows are retained separately as preserved records.

The current inputs are eligible only after this gate; this report does not execute or report Phase 3B-2 results.

## 6. Required structured records

- `scp259_remediation_source_audit.tsv`
- `scp259_matrix_integrity_validation.tsv`
- `scp259_companion_consistency.tsv`
- `scp259_new_authority_manifest.tsv`
- `portal_download_headers.tsv`

## 7. Completion state

All Phase 3B-2R PASS criteria were satisfied, and no prohibited scientific computation or data repair occurred.

# C1R_PHASE3B2R_PASS_READY_FOR_PHASE3B2_REEXECUTION

`NEXT_PHASE_AUTOSTART = FORBIDDEN`
"""
    write_text(REPORT, report)

    print(f"COMPLETION_STATE=C1R_PHASE3B2R_PASS_READY_FOR_PHASE3B2_REEXECUTION")
    print(f"MATRIX_SHA256={current_hashes[MATRIX.name]}")
    print(f"MATRIX_RECORDS={matrix['observed_complete_coordinate_records']}")
    print(f"METADATA_SHA256={current_hashes[METADATA.name]}")
    print(f"OUTPUT_ROOT={OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
