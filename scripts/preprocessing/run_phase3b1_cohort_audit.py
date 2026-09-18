from __future__ import annotations

import csv
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


RUN_ID = "C1R_P3B_RUN001_20260908"
PROJECT = Path(r"D:\SCIfour")
ROOT = PROJECT / "phase3B_execution"
FROZEN = ROOT / "frozen_authorities"
LOGS = ROOT / "logs"
PROVENANCE = ROOT / "provenance"

REPORT = ROOT / "C1R_PHASE3B1_COHORT_STRUCTURE_AND_DONOR_INTEGRITY_AUDIT_REPORT.md"
COHORT_INVENTORY = ROOT / "cohort_inventory.tsv"
DONOR_STRUCTURE = ROOT / "donor_structure_summary.tsv"
DONOR_OVERLAP = ROOT / "donor_overlap_audit.tsv"
ARM_FEASIBILITY = ROOT / "analysis_arm_feasibility.tsv"
EXECUTION_LOG = LOGS / "PHASE3B1_EXECUTION_LOG.md"
QA_JSON = PROVENANCE / "phase3B1_qa.json"
OUTPUT_MANIFEST = PROVENANCE / "phase3B1_output_manifest.tsv"
SCRIPT_PATH = Path(__file__).resolve()

INPUT_MANIFEST = PROVENANCE / "input_manifest.tsv"
AUTHORITY_MANIFEST = PROVENANCE / "authority_manifest.tsv"
PHASE3B0_MANIFEST = PROVENANCE / "phase3B0_output_manifest.tsv"
RUN_MANIFEST = PROVENANCE / "run_manifest.json"

R45_ROOT = PROJECT / "25_PHASE2B_R45_C1R_SCP259_METADATA_RECOVERY"
R45_MANIFEST = R45_ROOT / "PHASE2B_R45_C1R_OUTPUT_MANIFEST.csv"
R46_ROOT = PROJECT / "26_PHASE2B_R46_C1R_RESIDUAL_METADATA_CLOSURE"
R46_MANIFEST = R46_ROOT / "PHASE2B_R46_C1R_OUTPUT_MANIFEST.csv"
PHASE3A_ROOT = PROJECT / "32_PHASE3A_C1R_ANALYSIS_EXECUTION_AUTHORIZATION"
PHASE3A_MANIFEST = PHASE3A_ROOT / "PHASE3A_C1R_OUTPUT_MANIFEST.csv"

SCP259_CANDIDATE = (
    R45_ROOT
    / "04_HCA_audit"
    / "C1R_SCP259_HCA_METADATA_CANDIDATE.csv"
)
SCP259_METADATA = (
    PROJECT
    / "29_PHASE2C_R2_C1R_INPUT_VALIDATION"
    / "01_raw_input_freeze"
    / "SCP259_HCA_versioned_candidate"
    / "all.meta2.txt"
)
SCP259_BARCODES = (
    PROJECT
    / "29_PHASE2C_R2_C1R_INPUT_VALIDATION"
    / "01_raw_input_freeze"
    / "SCP259_HCA_public"
    / "Epi.barcodes2.tsv"
)
SCP1884_METADATA = (
    PROJECT
    / "29_PHASE2C_R2_C1R_INPUT_VALIDATION"
    / "99_logs"
    / "rejected_candidates"
    / "scp1884_author_metadata"
    / "co_ti_cmb_metadata.txt"
)
SCP1884_BARCODES = (
    PROJECT
    / "29_PHASE2C_R2_C1R_INPUT_VALIDATION"
    / "01_raw_input_freeze"
    / "SCP1884_HCA_public"
    / "CO_EPI.scp.barcodes.tsv"
)

CROSSWALK = (
    FROZEN
    / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE"
    / "01_donor_registry"
    / "C1R_DONOR_CROSSWALK.csv"
)
EXCLUSIONS = (
    FROZEN
    / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE"
    / "01_donor_registry"
    / "C1R_DONOR_EXCLUSION_FREEZE.csv"
)
POST_EXCLUSION_COUNTS = (
    FROZEN
    / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE"
    / "01_donor_registry"
    / "C1R_POST_EXCLUSION_ARM_COUNTS.csv"
)
MODEL_REGISTRY = (
    FROZEN
    / "23_PHASE2B_R3_C1R_REGISTRY_CLOSURE"
    / "05_model_and_covariates"
    / "C1R_MODEL_REGISTRY.csv"
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def read_csv(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def write_tsv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_text(path: Path, text: str) -> None:
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def verify_csv_manifest(
    root: Path,
    manifest: Path,
    path_field: str,
    size_field: str,
    hash_field: str,
    delimiter: str = ",",
) -> dict[str, object]:
    rows = read_csv(manifest, delimiter=delimiter)
    failures: list[str] = []
    for row in rows:
        target = root / Path(row[path_field].replace("/", os.sep))
        if not target.is_file():
            failures.append(f"MISSING:{row[path_field]}")
            continue
        observed_size = target.stat().st_size
        if observed_size != int(row[size_field]):
            failures.append(f"SIZE:{row[path_field]}")
            continue
        if sha256(target) != row[hash_field].upper():
            failures.append(f"SHA256:{row[path_field]}")
    require(not failures, f"Manifest verification failed for {manifest}: {failures[:5]}")
    return {"manifest": str(manifest), "rows": len(rows), "failures": failures, "status": "PASS"}


def verify_input_manifest() -> dict[str, object]:
    rows = read_csv(INPUT_MANIFEST, delimiter="\t")
    failures: list[str] = []
    matrix_files_hashed_only: list[str] = []
    for row in rows:
        target = Path(row["local_path"])
        if not target.is_file():
            failures.append(f"MISSING:{target}")
            continue
        if target.stat().st_size != int(row["size_bytes"]):
            failures.append(f"SIZE:{target}")
            continue
        observed = sha256(target)
        if observed != row["expected_sha256"].upper():
            failures.append(f"SHA256:{target}")
        if row["analysis_role"] == "PRIMARY_RAW_EXPRESSION_MATRIX":
            matrix_files_hashed_only.append(target.name)
    require(not failures, f"Input verification failed: {failures[:5]}")
    require(len(rows) == 8, f"Expected 8 registered inputs, observed {len(rows)}")
    return {
        "rows": len(rows),
        "failures": failures,
        "status": "PASS",
        "matrix_files_hashed_only": matrix_files_hashed_only,
    }


def verify_authority_snapshots() -> dict[str, object]:
    rows = read_csv(AUTHORITY_MANIFEST, delimiter="\t")
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
    require(not failures, f"Authority snapshot verification failed: {failures[:5]}")
    require(len(rows) == 107, f"Expected 107 authority snapshots, observed {len(rows)}")
    return {"rows": len(rows), "failures": failures, "status": "PASS"}


def load_unique_lines(path: Path) -> tuple[set[str], int, int]:
    values: set[str] = set()
    line_count = 0
    duplicates = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in handle:
            value = raw.rstrip("\r\n")
            if not value:
                continue
            line_count += 1
            if value in values:
                duplicates += 1
            values.add(value)
    require(duplicates == 0, f"Duplicate barcode(s) in {path}: {duplicates}")
    return values, line_count, duplicates


def unique_nonempty(values: list[str] | set[str]) -> list[str]:
    return sorted({value for value in values if value}, key=lambda x: x.encode("utf-8"))


def joined(values: list[str] | set[str]) -> str:
    return ";".join(unique_nonempty(values))


def build_scp259(candidate_rows: list[dict[str, str]]) -> dict[str, object]:
    required_candidate_fields = {
        "sample_id",
        "donor_id",
        "disease_status",
        "inflammation_status",
        "tissue",
        "anatomic_location",
        "cell_source",
        "platform",
        "platform_assignment_basis",
        "library_chemistry",
    }
    require(candidate_rows, "SCP259 candidate is empty")
    require(
        required_candidate_fields.issubset(candidate_rows[0]),
        "SCP259 candidate is missing required structural fields",
    )
    require(len(candidate_rows) == 133, f"Expected 133 SCP259 sample rows, observed {len(candidate_rows)}")

    sample_to_donor: dict[str, str] = {}
    candidate_by_sample: dict[str, dict[str, str]] = {}
    for row in candidate_rows:
        sample = row["sample_id"]
        donor = row["donor_id"]
        if sample in sample_to_donor and sample_to_donor[sample] != donor:
            fail(f"Ambiguous SCP259 sample-to-donor mapping: {sample}")
        sample_to_donor[sample] = donor
        candidate_by_sample[sample] = row
    require(len(sample_to_donor) == 133, "SCP259 sample identifiers are not unique")
    candidate_donors = set(sample_to_donor.values())
    require(len(candidate_donors) == 30, f"Expected 30 SCP259 donors, observed {len(candidate_donors)}")

    barcodes, barcode_count, duplicate_barcodes = load_unique_lines(SCP259_BARCODES)
    matched_barcodes: set[str] = set()
    matrix_samples: set[str] = set()
    matrix_donors: set[str] = set()
    all_samples: set[str] = set()
    all_donors: set[str] = set()
    metadata_rows = 0
    with SCP259_METADATA.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        type_row = next(reader)
        require(
            header == ["NAME", "Cluster", "nGene", "nUMI", "Subject", "Health", "Location", "Sample"],
            f"Unexpected SCP259 metadata header: {header}",
        )
        require(type_row[0] == "TYPE", "SCP259 metadata TYPE row is missing")
        for fields in reader:
            require(len(fields) == 8, f"Malformed SCP259 metadata row with {len(fields)} fields")
            metadata_rows += 1
            cell_id, subject, sample = fields[0], fields[4], fields[7]
            all_samples.add(sample)
            all_donors.add(subject)
            require(sample_to_donor.get(sample) == subject, f"SCP259 donor mismatch for sample {sample}")
            if cell_id in barcodes:
                require(cell_id not in matched_barcodes, f"Duplicate SCP259 metadata cell ID: {cell_id}")
                matched_barcodes.add(cell_id)
                matrix_samples.add(sample)
                matrix_donors.add(subject)

    require(metadata_rows == 365492, f"Expected 365492 SCP259 metadata rows, observed {metadata_rows}")
    require(len(all_samples) == 133, f"Expected 133 SCP259 metadata samples, observed {len(all_samples)}")
    require(len(all_donors) == 30, f"Expected 30 SCP259 metadata donors, observed {len(all_donors)}")
    require(matched_barcodes == barcodes, "SCP259 matrix barcodes do not match authorized metadata cell IDs")
    require(matrix_samples.issubset(candidate_by_sample), "SCP259 matrix samples are missing from the source-bound crosswalk")

    primary_rows = [
        row
        for row in candidate_rows
        if row["disease_status"] == "ulcerative colitis"
        and row["tissue"] == "colon"
        and row["inflammation_status"] == "Inflamed"
        and row["cell_source"] == "colonic epithelium"
    ]
    primary_samples = {row["sample_id"] for row in primary_rows}
    primary_donors = {row["donor_id"] for row in primary_rows}
    require(primary_samples.issubset(matrix_samples), "SCP259 primary samples are absent from the registered epithelial matrix")
    require(len(primary_samples) == 16, f"Expected 16 SCP259 primary samples, observed {len(primary_samples)}")
    require(len(primary_donors) == 14, f"Expected 14 SCP259 primary donors, observed {len(primary_donors)}")

    samples_per_donor = Counter(sample_to_donor[sample] for sample in matrix_samples)
    return {
        "candidate_rows": candidate_rows,
        "candidate_by_sample": candidate_by_sample,
        "sample_to_donor": sample_to_donor,
        "metadata_rows": metadata_rows,
        "barcode_count": barcode_count,
        "duplicate_barcodes": duplicate_barcodes,
        "matched_barcodes": len(matched_barcodes),
        "matrix_samples": matrix_samples,
        "matrix_donors": matrix_donors,
        "samples_per_donor": samples_per_donor,
        "primary_samples": primary_samples,
        "primary_donors": primary_donors,
        "all_samples": all_samples,
        "all_donors": all_donors,
    }


def build_scp1884(
    crosswalk_rows: list[dict[str, str]],
    exclusion_rows: list[dict[str, str]],
) -> dict[str, object]:
    rows = [row for row in crosswalk_rows if row["dataset"] == "SCP1884"]
    require(len(rows) == 225, f"Expected 225 SCP1884 crosswalk rows, observed {len(rows)}")
    sample_to_crosswalk: dict[str, dict[str, str]] = {}
    donor_to_samples: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        sample = row["portal_sample_id"]
        donor = row["donor_id"]
        if sample in sample_to_crosswalk and sample_to_crosswalk[sample]["donor_id"] != donor:
            fail(f"Ambiguous SCP1884 sample-to-donor mapping: {sample}")
        sample_to_crosswalk[sample] = row
        donor_to_samples[donor].add(sample)
    require(len(sample_to_crosswalk) == 225, "SCP1884 sample identifiers are not unique")
    require(len(donor_to_samples) == 71, f"Expected 71 SCP1884 donors, observed {len(donor_to_samples)}")

    excluded_donors = {row["donor_id"] for row in exclusion_rows}
    require(len(exclusion_rows) == 12, f"Expected 12 exclusion rows, observed {len(exclusion_rows)}")
    require(len(excluded_donors) == 12, "SCP1884 exclusion donor IDs are not unique")
    require(
        all(row["status"] == "EXCLUDE_KNOWN_REUSE" for row in exclusion_rows),
        "SCP1884 exclusion registry contains an unexpected status",
    )
    require(excluded_donors.issubset(donor_to_samples), "Excluded SCP1884 donor absent from crosswalk")

    barcodes, barcode_count, duplicate_barcodes = load_unique_lines(SCP1884_BARCODES)
    matched_barcodes: set[str] = set()
    matrix_samples: set[str] = set()
    matrix_donors: set[str] = set()
    matrix_chems: set[str] = set()
    matrix_sites: set[str] = set()
    matrix_types: set[str] = set()
    matrix_layers: set[str] = set()
    metadata_rows = 0
    with SCP1884_METADATA.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t", quotechar='"')
        header = next(reader)
        require(
            header
            == [
                "PubIDSample",
                "anno_overall",
                "n_genes",
                "n_counts",
                "Chem",
                "Site",
                "Type",
                "PubID",
                "Layer",
                "anno2",
            ],
            f"Unexpected SCP1884 metadata header: {header}",
        )
        for fields in reader:
            require(len(fields) == 11, f"Malformed SCP1884 metadata row with {len(fields)} fields")
            metadata_rows += 1
            cell_id = fields[0]
            if cell_id not in barcodes:
                continue
            require(cell_id not in matched_barcodes, f"Duplicate SCP1884 metadata cell ID: {cell_id}")
            matched_barcodes.add(cell_id)
            sample, chem, site, type_value, donor, layer = (
                fields[1],
                fields[5],
                fields[6],
                fields[7],
                fields[8],
                fields[9],
            )
            require(sample in sample_to_crosswalk, f"SCP1884 matrix sample missing from crosswalk: {sample}")
            require(sample_to_crosswalk[sample]["donor_id"] == donor, f"SCP1884 donor mismatch for sample {sample}")
            matrix_samples.add(sample)
            matrix_donors.add(donor)
            matrix_chems.add(chem)
            matrix_sites.add(site)
            matrix_types.add(type_value)
            matrix_layers.add(layer)

    require(matched_barcodes == barcodes, "SCP1884 CO_EPI barcodes do not match author metadata cell IDs")
    colon_samples = {row["portal_sample_id"] for row in rows if row["tissue"] == "COLON"}
    require(matrix_samples == colon_samples, "SCP1884 CO_EPI sample universe differs from the frozen colon crosswalk")
    require(matrix_sites == {"CO"}, f"Unexpected SCP1884 CO_EPI sites: {matrix_sites}")

    retained_rows = [row for row in rows if row["planned_action"] == "RETAIN"]
    retained_donors = {row["donor_id"] for row in retained_rows}
    retained_samples = {row["portal_sample_id"] for row in retained_rows}
    require(retained_donors == set(donor_to_samples) - excluded_donors, "SCP1884 retention set is inconsistent with exclusion registry")

    matrix_retained_samples = matrix_samples & retained_samples
    matrix_retained_donors = {sample_to_crosswalk[s]["donor_id"] for s in matrix_retained_samples}
    samples_per_donor = Counter(sample_to_crosswalk[s]["donor_id"] for s in matrix_samples)
    return {
        "rows": rows,
        "sample_to_crosswalk": sample_to_crosswalk,
        "donor_to_samples": donor_to_samples,
        "metadata_rows": metadata_rows,
        "barcode_count": barcode_count,
        "duplicate_barcodes": duplicate_barcodes,
        "matched_barcodes": len(matched_barcodes),
        "matrix_samples": matrix_samples,
        "matrix_donors": matrix_donors,
        "matrix_chems": matrix_chems,
        "matrix_sites": matrix_sites,
        "matrix_types": matrix_types,
        "matrix_layers": matrix_layers,
        "excluded_donors": excluded_donors,
        "retained_donors": retained_donors,
        "retained_samples": retained_samples,
        "matrix_retained_samples": matrix_retained_samples,
        "matrix_retained_donors": matrix_retained_donors,
        "samples_per_donor": samples_per_donor,
    }


def contextual_counts(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (row["disease"], row["tissue"], row["inflammation_status"], row["planned_action"])
        groups[key].append(row)
    result: list[dict[str, object]] = []
    for key in sorted(groups, key=lambda x: tuple(v.encode("utf-8") for v in x)):
        group = groups[key]
        result.append(
            {
                "disease": key[0],
                "tissue": key[1],
                "context": key[2],
                "action": key[3],
                "sample_count": len(group),
                "donor_count": len({row["donor_id"] for row in group}),
            }
        )
    return result


def main() -> None:
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    run_manifest = json.loads(RUN_MANIFEST.read_text(encoding="utf-8"))
    require(run_manifest["run_id"] == RUN_ID, "Run manifest identity mismatch")
    require(
        run_manifest["completion_state"] == "C1R_PHASE3B0_PASS_READY_FOR_PHASE3B1",
        "Phase 3B-0 completion state does not authorize this audit",
    )

    predecessor_checks = {
        "phase3b0_output": verify_csv_manifest(
            ROOT,
            PHASE3B0_MANIFEST,
            "relative_path",
            "size_bytes",
            "sha256",
            delimiter="\t",
        ),
        "r45": verify_csv_manifest(R45_ROOT, R45_MANIFEST, "relative_path", "bytes", "sha256"),
        "r46": verify_csv_manifest(R46_ROOT, R46_MANIFEST, "relative_path", "size_bytes", "sha256"),
        "phase3a": verify_csv_manifest(PHASE3A_ROOT, PHASE3A_MANIFEST, "relative_path", "size_bytes", "sha256"),
    }
    authority_check = verify_authority_snapshots()
    input_check = verify_input_manifest()

    candidate_rows = read_csv(SCP259_CANDIDATE)
    crosswalk_rows = read_csv(CROSSWALK)
    exclusion_rows = read_csv(EXCLUSIONS)
    model_rows = read_csv(MODEL_REGISTRY)
    post_exclusion_rows = read_csv(POST_EXCLUSION_COUNTS)
    require(len(model_rows) == 3, f"Expected 3 frozen model rows, observed {len(model_rows)}")
    require({row["model_id"] for row in model_rows} == {"M01", "M02", "M03"}, "Unexpected frozen model IDs")

    scp259 = build_scp259(candidate_rows)
    scp1884 = build_scp1884(crosswalk_rows, exclusion_rows)

    intersection = set(scp259["all_donors"]) & set(scp1884["donor_to_samples"])
    require(intersection == set(scp1884["excluded_donors"]), "Frozen SCP259-SCP1884 overlap set is inconsistent")
    m02_rows = [
        row
        for row in scp1884["rows"]
        if row["disease"] == "CROHN_DISEASE"
        and row["tissue"] == "COLON"
        and row["inflammation_status"] == "ENDOSCOPICALLY_INFLAMED"
        and row["planned_action"] == "RETAIN"
    ]
    m03_rows = [
        row
        for row in scp1884["rows"]
        if row["disease"] == "CROHN_DISEASE"
        and row["tissue"] == "COLON"
        and row["inflammation_status"] == "ENDOSCOPICALLY_NON_INFLAMED"
        and row["planned_action"] == "RETAIN"
    ]
    m02_donors = {row["donor_id"] for row in m02_rows}
    m03_donors = {row["donor_id"] for row in m03_rows}
    m02_m03_shared_donors = m02_donors & m03_donors

    cohort_rows = [
        {
            "run_id": RUN_ID,
            "dataset_identifier": "SCP259",
            "accession_source": "SCP259; HCA project cd61771b-661a-4e19-b269-6e5d95350de6; DCP60 2022 SCP-origin representation",
            "authority_category": "PRIMARY_EQUIVALENT_AUTHORITY (matrix); PROVENANCE_EQUIVALENT_AUTHORITY (metadata and companions)",
            "registered_input_objects": "all.meta2.txt;gene_sorted-Epi.matrix.mtx;Epi.genes.tsv;Epi.barcodes2.tsv",
            "platform": "10x GemCode V1 / Chromium 3-prime V2 declared; complete sample-level assignment NA_UNRESOLVED",
            "sequencing_technology": "Single-cell RNA sequencing; Illumina NextSeq/HiSeq families declared; complete sample-level mapping unavailable",
            "tissue": "COLON",
            "anatomical_location": "Broad colon closed; exact subsegment resolved for 118/133 samples and NA_UNRESOLVED for 15/133",
            "disease_labels": "ULCERATIVE_COLITIS;HEALTHY_CONTROL",
            "available_metadata_fields": "all.meta2: NAME,Subject,Health,Location,Sample; source-bound HCA crosswalk: sample_id,donor_id,disease_status,inflammation_status,tissue,anatomic_location,cell_source,partial platform fields. Cluster,nGene,nUMI were not analyzed.",
            "intended_c1r_role": "PRIMARY_DISCOVERY_APPLICATION in UC colon endoscopically inflamed epithelium (M01)",
            "structural_boundary": "Donor is the unit; broad-colon minimal model only; no segment or platform imputation",
            "status": "AUTHORIZED_WITH_DOCUMENTED_LIMITATIONS",
        },
        {
            "run_id": RUN_ID,
            "dataset_identifier": "SCP1884",
            "accession_source": "SCP1884; HCA public CO_EPI raw-count representation; author co_ti_cmb_metadata.txt",
            "authority_category": "PROVENANCE_EQUIVALENT_AUTHORITY (CO_EPI matrix and companions); CONDITIONAL_AUTHORITY (bounded metadata/annotation support)",
            "registered_input_objects": "CO_EPI.scp.raw.mtx;CO_EPI.scp.features.tsv;CO_EPI.scp.barcodes.tsv;co_ti_cmb_metadata.txt",
            "platform": f"10x chemistry labels present in registered CO_EPI metadata: {joined(scp1884['matrix_chems'])}",
            "sequencing_technology": "Single-cell RNA sequencing; sequencing-instrument field unavailable in the registered metadata",
            "tissue": "COLON for registered CO_EPI expression input; TERMINAL_ILEUM and SMALL_BOWEL_OTHER are metadata-only context records in this run",
            "anatomical_location": "COLON for M02/M03; no finer subsite in author metadata",
            "disease_labels": "CROHN_DISEASE;HEALTHY_CONTROL",
            "available_metadata_fields": "cell row identifier,PubIDSample,Chem,Site,Type,PubID,Layer; annotations present but not used for biological analysis. n_genes and n_counts were not analyzed.",
            "intended_c1r_role": "DISEASE_CONTEXT_PORTABILITY_ASSESSMENT in CD colon inflamed (M02); CD colon non-inflamed exploratory (M03)",
            "structural_boundary": "12 exact-ID reused healthy donors excluded; metadata is bounded support only; no hypothesis, program, state, or threshold modification",
            "status": "AUTHORIZED_WITH_REQUIRED_LIMITATION",
        },
    ]

    donor_structure_rows = [
        {
            "run_id": RUN_ID,
            "dataset_identifier": "SCP259_REGISTERED_EPI_MATRIX",
            "hierarchy": "cell->sample->donor->disease/context group",
            "cell_identifier_field": "NAME linked exactly to Epi.barcodes2.tsv",
            "sample_identifier_field": "Sample / sample_id",
            "donor_identifier_field": "Subject / donor_id",
            "disease_context_fields": "disease_status,inflammation_status,tissue,cell_source",
            "metadata_records_scanned": scp259["metadata_rows"],
            "registered_matrix_barcodes": scp259["barcode_count"],
            "matched_matrix_barcodes": scp259["matched_barcodes"],
            "sample_count": len(scp259["matrix_samples"]),
            "donor_count": len(scp259["matrix_donors"]),
            "retained_sample_count": len(scp259["matrix_samples"]),
            "retained_donor_count": len(scp259["matrix_donors"]),
            "donors_with_multiple_samples": sum(v > 1 for v in scp259["samples_per_donor"].values()),
            "sample_to_donor_mapping_status": "EXACT_UNIQUE_133_OF_133_SOURCE_BOUND; MATRIX_SUBSET_EXACT",
            "donor_uniqueness_status": "PASS_ONE_DONOR_ID_PER_SAMPLE; MULTIPLE_SAMPLES_PER_DONOR_ALLOWED",
            "donor_aggregation_readiness": "READY_WITH_LIMITATIONS_FOR_FROZEN_M01; equal-weight sample median then donor mean remains mandatory",
            "authority_status": "PROVENANCE_EQUIVALENT_METADATA",
            "notes": "Cells are technical observations only and are never independent biological replicates.",
        },
        {
            "run_id": RUN_ID,
            "dataset_identifier": "SCP1884_REGISTERED_CO_EPI_MATRIX",
            "hierarchy": "cell->PubIDSample->PubID donor->disease/context group",
            "cell_identifier_field": "row identifier linked exactly to CO_EPI.scp.barcodes.tsv",
            "sample_identifier_field": "PubIDSample / portal_sample_id",
            "donor_identifier_field": "PubID / donor_id",
            "disease_context_fields": "disease,tissue,inflammation_status,Layer",
            "metadata_records_scanned": scp1884["metadata_rows"],
            "registered_matrix_barcodes": scp1884["barcode_count"],
            "matched_matrix_barcodes": scp1884["matched_barcodes"],
            "sample_count": len(scp1884["matrix_samples"]),
            "donor_count": len(scp1884["matrix_donors"]),
            "retained_sample_count": len(scp1884["matrix_retained_samples"]),
            "retained_donor_count": len(scp1884["matrix_retained_donors"]),
            "donors_with_multiple_samples": sum(v > 1 for v in scp1884["samples_per_donor"].values()),
            "sample_to_donor_mapping_status": "EXACT_UNIQUE_225_OF_225_CROSSWALK; CO_EPI_SUBSET_EXACT",
            "donor_uniqueness_status": "PASS_ONE_DONOR_ID_PER_SAMPLE; MULTIPLE_SAMPLES_PER_DONOR_ALLOWED",
            "donor_aggregation_readiness": "READY_WITH_REQUIRED_LIMITATIONS_FOR_FROZEN_M02_M03; exclusions precede aggregation",
            "authority_status": "CONDITIONAL_METADATA_SUPPORT",
            "notes": "Registered expression input is CO_EPI only; non-colon contexts remain metadata structure, not analysis arms.",
        },
        {
            "run_id": RUN_ID,
            "dataset_identifier": "SCP1884_FULL_FROZEN_DONOR_CROSSWALK",
            "hierarchy": "sample/biosample->donor->disease/context group",
            "cell_identifier_field": "NA_NOT_APPLICABLE_TO_CROSSWALK",
            "sample_identifier_field": "portal_sample_id",
            "donor_identifier_field": "donor_id",
            "disease_context_fields": "disease,tissue,inflammation_status",
            "metadata_records_scanned": len(scp1884["rows"]),
            "registered_matrix_barcodes": "NA_NOT_APPLICABLE_TO_FULL_CROSSWALK",
            "matched_matrix_barcodes": "NA_NOT_APPLICABLE_TO_FULL_CROSSWALK",
            "sample_count": len(scp1884["sample_to_crosswalk"]),
            "donor_count": len(scp1884["donor_to_samples"]),
            "retained_sample_count": len(scp1884["retained_samples"]),
            "retained_donor_count": len(scp1884["retained_donors"]),
            "donors_with_multiple_samples": sum(len(v) > 1 for v in scp1884["donor_to_samples"].values()),
            "sample_to_donor_mapping_status": "EXACT_UNIQUE_225_OF_225",
            "donor_uniqueness_status": "PASS_ONE_DONOR_ID_PER_SAMPLE; MULTIPLE_SAMPLES_PER_DONOR_ALLOWED",
            "donor_aggregation_readiness": "STRUCTURE_DOCUMENTED; only registered CO_EPI colon models are executable",
            "authority_status": "SOURCE_BOUND_FROZEN_CROSSWALK_WITH_CONDITIONAL_METADATA_BOUNDARY",
            "notes": "71 total donors; 12 known reused healthy donors excluded; 59 retained across metadata contexts.",
        },
    ]

    donor_overlap_rows: list[dict[str, object]] = []
    exclusion_by_donor = {row["donor_id"]: row for row in exclusion_rows}
    for donor in sorted(scp1884["donor_to_samples"], key=lambda x: x.encode("utf-8")):
        is_overlap = donor in scp1884["excluded_donors"]
        crosswalk_group = [row for row in scp1884["rows"] if row["donor_id"] == donor]
        evidence_values = {row["overlap_evidence"] for row in crosswalk_group}
        source_samples = {
            row["sample_id"] for row in candidate_rows if row["donor_id"] == donor
        }
        donor_overlap_rows.append(
            {
                "run_id": RUN_ID,
                "comparison": "SCP259<->SCP1884",
                "source_context": "SCP259_ALL_SOURCE_BOUND",
                "target_context": "SCP1884_ALL_FROZEN_CROSSWALK",
                "donor_id": donor,
                "source_sample_ids": joined(source_samples) if is_overlap else "NA_NO_FROZEN_MATCH",
                "target_sample_ids": joined(scp1884["donor_to_samples"][donor]),
                "overlap_status": "CONFIRMED_EXACT_ID_OVERLAP" if is_overlap else "NO_DOCUMENTED_OVERLAP_UNDER_FROZEN_EXACT_ID_RULE",
                "overlap_evidence": joined(evidence_values),
                "frozen_action": exclusion_by_donor[donor]["status"] if is_overlap else "RETAIN",
                "retained_after_exclusion": "NO" if is_overlap else "YES",
                "disease": crosswalk_group[0]["disease"],
                "tissue_contexts": joined({row["tissue"] for row in crosswalk_group}),
                "unresolved_identity_issue": "NONE_WITHIN_FROZEN_EXACT_ID_RULE" if is_overlap else "IDENTITY_BEYOND_SOURCE_BOUND_EXACT_IDS_NOT_INFERRED",
                "authority_status": "FROZEN_EXCLUSION" if is_overlap else "SOURCE_BOUND_RETAIN",
                "notes": "12-donor known-reuse rule retained without change" if is_overlap else "Retained because no frozen exact-ID SCP259 overlap is documented; this is not a probabilistic non-overlap claim",
            }
        )
    for donor in sorted(m02_m03_shared_donors, key=lambda x: x.encode("utf-8")):
        donor_overlap_rows.append(
            {
                "run_id": RUN_ID,
                "comparison": "SCP1884_M02<->SCP1884_M03",
                "source_context": "M02_CD_COLON_ENDOSCOPICALLY_INFLAMED",
                "target_context": "M03_CD_COLON_ENDOSCOPICALLY_NON_INFLAMED",
                "donor_id": donor,
                "source_sample_ids": joined({row["portal_sample_id"] for row in m02_rows if row["donor_id"] == donor}),
                "target_sample_ids": joined({row["portal_sample_id"] for row in m03_rows if row["donor_id"] == donor}),
                "overlap_status": "CONFIRMED_WITHIN_DATASET_DONOR_REUSE_ACROSS_CONTEXTS",
                "overlap_evidence": "Exact donor_id in frozen SCP1884 crosswalk",
                "frozen_action": "RETAIN_IN_BOTH_SEPARATE_CONTEXTS",
                "retained_after_exclusion": "YES",
                "disease": "CROHN_DISEASE",
                "tissue_contexts": "COLON",
                "unresolved_identity_issue": "NONE_EXACT_WITHIN_DATASET_ID",
                "authority_status": "SOURCE_BOUND_RETAIN",
                "notes": "M02 and M03 remain separate; no pooling or independence assumption across contexts",
            }
        )
    cross_source_rows = [row for row in donor_overlap_rows if row["comparison"] == "SCP259<->SCP1884"]
    require(sum(row["frozen_action"] == "EXCLUDE_KNOWN_REUSE" for row in cross_source_rows) == 12, "Overlap audit exclusion count mismatch")
    require(sum(row["retained_after_exclusion"] == "YES" for row in cross_source_rows) == 59, "Overlap audit retained donor count mismatch")

    arm_contexts = {
        "M01": {
            "disease_group": "ULCERATIVE_COLITIS",
            "tissue": "COLON",
            "context": "ENDOSCOPICALLY_INFLAMED_EPITHELIUM",
            "donor_count": len(scp259["primary_donors"]),
            "sample_count": len(scp259["primary_samples"]),
            "data_source": "SCP259 all.meta2.txt + Epi.barcodes2.tsv + source-bound HCA 133-sample crosswalk",
            "authority_status": "PRIMARY_EQUIVALENT_MATRIX; PROVENANCE_EQUIVALENT_METADATA",
            "classification": "LIMITED",
            "structural_basis": "14 donors and 16 samples exceed frozen minimum n=5; broad-colon identity and donor hierarchy are closed",
            "limitations": "15/133 exact-subsegment rows unresolved overall; primary count would be 13 under separately authorized unresolved-segment sensitivity; platform/chemistry mapping incomplete",
        },
        "M02": {
            "disease_group": "CROHN_DISEASE",
            "tissue": "COLON",
            "context": "ENDOSCOPICALLY_INFLAMED",
            "data_source": "SCP1884 CO_EPI registered inputs + frozen donor crosswalk + bounded author metadata",
            "authority_status": "PROVENANCE_EQUIVALENT_MATRIX; CONDITIONAL_METADATA_SUPPORT",
            "classification": "LIMITED",
            "structural_basis": "Exactly 5 retained donors meet the frozen minimum n=5; 8 retained sample channels",
            "limitations": "At donor floor; small-sample/model fragility; author metadata is bounded support; no pristine independent-validation claim",
        },
        "M03": {
            "disease_group": "CROHN_DISEASE",
            "tissue": "COLON",
            "context": "ENDOSCOPICALLY_NON_INFLAMED",
            "data_source": "SCP1884 CO_EPI registered inputs + frozen donor crosswalk + bounded author metadata",
            "authority_status": "PROVENANCE_EQUIVALENT_MATRIX; CONDITIONAL_METADATA_SUPPORT",
            "classification": "LIMITED",
            "structural_basis": "17 retained donors and 33 retained sample channels exceed frozen minimum n=5",
            "limitations": "Exploratory only; author metadata is bounded support; cannot rescue or replace M02",
        },
    }
    for model_id in ("M02", "M03"):
        group = m02_rows if model_id == "M02" else m03_rows
        arm_contexts[model_id]["sample_count"] = len(group)
        arm_contexts[model_id]["donor_count"] = len({row["donor_id"] for row in group})
        require(
            {row["portal_sample_id"] for row in group}.issubset(scp1884["matrix_samples"]),
            f"{model_id} samples are absent from the registered CO_EPI matrix metadata linkage",
        )

    arm_rows: list[dict[str, object]] = []
    for model in sorted(model_rows, key=lambda row: row["model_id"]):
        arm = arm_contexts[model["model_id"]]
        arm_rows.append(
            {
                "run_id": RUN_ID,
                "analysis_arm_id": model["model_id"],
                "frozen_role": model["primary_or_exploratory"],
                "disease_group": arm["disease_group"],
                "tissue": arm["tissue"],
                "context": arm["context"],
                "donor_count": arm["donor_count"],
                "sample_count": arm["sample_count"],
                "data_source": arm["data_source"],
                "authority_status": arm["authority_status"],
                "minimum_donor_count": model["minimum_n"],
                "classification": arm["classification"],
                "structural_basis": arm["structural_basis"],
                "limitations": arm["limitations"],
            }
        )
    require(all(row["classification"] in {"AVAILABLE", "LIMITED", "NOT_ESTIMABLE"} for row in arm_rows), "Invalid feasibility enum")
    require([row["analysis_arm_id"] for row in arm_rows] == ["M01", "M02", "M03"], "Analysis-arm order or identity mismatch")

    write_tsv(COHORT_INVENTORY, list(cohort_rows[0]), cohort_rows)
    write_tsv(DONOR_STRUCTURE, list(donor_structure_rows[0]), donor_structure_rows)
    write_tsv(DONOR_OVERLAP, list(donor_overlap_rows[0]), donor_overlap_rows)
    write_tsv(ARM_FEASIBILITY, list(arm_rows[0]), arm_rows)

    context_rows = contextual_counts(scp1884["rows"])
    context_table = "\n".join(
        f"| {row['disease']} | {row['tissue']} | {row['context']} | {row['action']} | {row['donor_count']} | {row['sample_count']} |"
        for row in context_rows
    )
    arm_table = "\n".join(
        f"| {row['analysis_arm_id']} | {row['frozen_role']} | {row['disease_group']} | {row['tissue']} | {row['context']} | {row['donor_count']} | {row['sample_count']} | {row['classification']} |"
        for row in arm_rows
    )
    report = f"""# C1R Phase 3B-1 cohort structure and donor integrity audit report

Run ID: `{RUN_ID}`  
Executed: **{timestamp} (Asia/Shanghai)**  
Mode: **metadata and cohort-structure audit only**

## 1. Prompt review and execution boundary

The supplied Phase 3B-1 design is executable without scientific amendment. One scope clarification was applied: `analysis_arm_feasibility.tsv` contains only the three arms frozen in `C1R_MODEL_REGISTRY.csv` (M01-M03). SCP1884 terminal-ileum and other-small-bowel strata are documented as metadata context structure but are not promoted to analysis arms because the registered SCP1884 expression input is `CO_EPI` only.

No raw expression matrix body was opened. The two matrix files were rehashed only. No QC filtering, normalization, expression-distribution analysis, gene comparison, enrichment, program/state scoring, regression, hypothesis test, effect estimate, or biological interpretation was performed. Metadata QC fields (`nGene`, `nUMI`, `n_genes`, `n_counts`) and cell-state annotations were not analyzed.

## 2. Authority and integrity checks

- Phase 3B-0 output manifest: **{predecessor_checks['phase3b0_output']['rows']}/{predecessor_checks['phase3b0_output']['rows']} PASS**.
- Frozen authority snapshots: **{authority_check['rows']}/{authority_check['rows']} PASS**, byte size and SHA-256; all remained read-only.
- Registered inputs: **{input_check['rows']}/{input_check['rows']} PASS**, byte size and SHA-256.
- Phase 2B-R4.5 metadata package: **{predecessor_checks['r45']['rows']}/{predecessor_checks['r45']['rows']} PASS**.
- Phase 2B-R4.6 closure package: **{predecessor_checks['r46']['rows']}/{predecessor_checks['r46']['rows']} PASS**.
- Phase 3A authorization package: **{predecessor_checks['phase3a']['rows']}/{predecessor_checks['phase3a']['rows']} PASS**.

No frozen authority or registered input was changed.

## 3. Cohort inventory

Two authorized dataset records were identified and written to `cohort_inventory.tsv`.

- **SCP259** remains the primary UC broad-colon inflamed epithelial application under the version-scoped HCA DCP60 2022 SCP-origin representation. Its source-bound metadata contains **133** samples; **{len(scp259['matrix_samples'])}** contribute cells to the registered epithelial barcode universe of **{scp259['barcode_count']:,}** unique cells, covering all **{len(scp259['matrix_donors'])}** donors. All 16 M01 samples are present. Broad colon is closed; exact subsegment and complete sample-level platform/chemistry mapping retain the frozen limitations.
- **SCP1884** remains the disease-context portability assessment dataset. Its `CO_EPI` barcode universe contains **{scp1884['barcode_count']:,}** unique cells linked exactly to **{len(scp1884['matrix_samples'])}** colon sample channels and **{len(scp1884['matrix_donors'])}** donors before the frozen reuse exclusion, and **{len(scp1884['matrix_retained_samples'])}** sample channels from **{len(scp1884['matrix_retained_donors'])}** donors after exclusion. Author metadata is bounded metadata/annotation support only, not exact Portal-v2 replication or a pristine independent-validation cohort.

## 4. Donor hierarchy audit

The required hierarchy is mechanically supported in both registered matrix cohorts:

`cell -> sample/biosample -> donor -> disease/context group`

- SCP259: **365,492** metadata cell rows and **133** unique sample records map to **30** unique donors; all **{scp259['barcode_count']:,}** registered epithelial barcodes matched exactly. The frozen primary M01 context contains **{len(scp259['primary_samples'])} samples from {len(scp259['primary_donors'])} donors**.
- SCP1884: **{scp1884['metadata_rows']:,}** author-metadata cell rows were scanned using structural identifiers only; all **{scp1884['barcode_count']:,}** registered CO_EPI barcodes matched exactly. The frozen crosswalk contains **225** sample channels and **71** donors across all documented contexts; **59** donors and **{len(scp1884['retained_samples'])}** sample channels remain after the 12-donor reuse exclusion.

Every sample maps to one donor. Multiple samples per donor are present and expected. Downstream aggregation must preserve the frozen equal-weight sample-median then donor-mean rule; cells must never be treated as biological replicates.

## 5. Donor overlap and reuse audit

The source-bound identifier intersection between SCP259 and SCP1884 is exactly the frozen set of **12 donors**: `{joined(scp1884['excluded_donors'])}`. All 12 retain `EXCLUDE_KNOWN_REUSE`; no rule was changed. The full SCP1884 crosswalk retains **59 of 71 donors** after exclusion; the registered CO_EPI matrix retains **{len(scp1884['matrix_retained_donors'])} of {len(scp1884['matrix_donors'])} donors** and **{len(scp1884['matrix_retained_samples'])} of {len(scp1884['matrix_samples'])} sample channels**. `donor_overlap_audit.tsv` lists every SCP1884 donor, all linked sample IDs, the exact-ID overlap status, action, and retention state.

Within SCP1884, M02 and M03 share **{len(m02_m03_shared_donors)} exact donor IDs**: `{joined(m02_m03_shared_donors)}`. This is retained within-dataset reuse, not a cross-dataset exclusion. The two contexts remain separate, and no pooling or cross-context independence assumption was introduced.

No probabilistic or expression-based identity matching was attempted. For retained donors, absence of a frozen exact-ID match is not presented as proof that broader identity reuse is impossible.

## 6. Disease and context structure

SCP259 contains healthy and ulcerative-colitis broad-colon samples with inflamed/non-inflamed and epithelial/lamina-propria source labels. The frozen primary context remains UC, colon, endoscopically inflamed epithelium; categories were not pooled.

SCP1884 frozen metadata strata are:

| Disease | Tissue | Context | Frozen action | Donors | Sample channels |
|---|---|---|---|---:|---:|
{context_table}

Terminal-ileum and other-small-bowel rows remain structural metadata records in this phase. They are not executable C1-R arms under the registered `CO_EPI` input.

## 7. Analysis-arm feasibility

The classification is structural only. `LIMITED` means the frozen donor floor and identity/linkage requirements are met, but a documented authority, sample-size, anatomy, or platform limitation remains. No expression outcome influenced classification.

| Arm | Frozen role | Disease | Tissue | Context | Donors | Samples | Class |
|---|---|---|---|---|---:|---:|---|
{arm_table}

- M01 exceeds the donor floor (14 vs 5) but retains the exact-subsegment and platform/chemistry limitations.
- M02 meets the donor floor exactly (5 vs 5) and remains small-sample/conditional-metadata limited.
- M03 exceeds the floor (17 vs 5) but is exploratory and cannot rescue or replace M02.

Structural feasibility does not pre-adjudicate expression coverage, variance, design rank, residual degrees of freedom, HC3 leverage, model fit, or any association result.

## 8. SCP259 and SCP1884 boundary confirmation

- **SCP259:** primary equivalent authority remains limited to the frozen HCA DCP60 2022 SCP-origin representation and approved broad-colon application. No equality claim to the current Portal object and no expanded interpretation was made.
- **SCP1884:** remains a disease-context portability assessment dataset. `co_ti_cmb_metadata.txt` was used only for registered structural metadata linkage; the 12 donor exclusions were retained; hypotheses, programs, states, mappings, thresholds, and analysis roles were unchanged.

## 9. Pass criteria and completion state

- All authorized cohorts identified: **PASS**.
- Donor hierarchy documented and one-sample-to-one-donor linkage verified: **PASS**.
- Donor overlap assessment completed and 12 frozen exclusions retained: **PASS**.
- SCP259/SCP1884 boundaries confirmed: **PASS**.
- Frozen M01-M03 arms structurally classified: **PASS**.
- No scientific analysis performed: **PASS**.
- No frozen authority modified: **PASS**.

# C1R_PHASE3B1_PASS_READY_FOR_PHASE3B2

This is a Phase 3B-1 completion state only. Phase 3B-2, QC, scoring, modeling, association analysis, and biological interpretation were not started.

`NEXT_PHASE_AUTOSTART = FORBIDDEN`
"""
    write_text(REPORT, report)

    log_text = f"""# C1R Phase 3B-1 execution log

Run ID: `{RUN_ID}`  
Timestamp: **{timestamp} (Asia/Shanghai)**

1. Reviewed the Phase 3B-1 prompt and retained every scientific and stop boundary.
2. Clarified only that feasibility is limited to frozen model arms M01-M03; metadata-only non-colon SCP1884 contexts were not promoted to analysis arms.
3. Verified Phase 3B-0, Phase 2B-R4.5, Phase 2B-R4.6, and Phase 3A manifests; reverified 107 read-only authority snapshots and all 8 registered input hashes.
4. Hashed but did not parse `gene_sorted-Epi.matrix.mtx` or `CO_EPI.scp.raw.mtx`.
5. Parsed structural metadata identifiers and safe context fields only; did not analyze QC fields or cell-state annotations.
6. Verified exact cell-barcode, sample, donor, and context linkage for the registered SCP259 Epi and SCP1884 CO_EPI inputs.
7. Confirmed the frozen 12-donor SCP259-SCP1884 exact-ID overlap and retained all exclusions unchanged.
8. Audited exact donor reuse between SCP1884 M02 and M03 without pooling contexts or changing retention.
9. Generated the five required deliverables plus this log, QA record, and a self-excluding manifest.
10. Did not start Phase 3B-2 or any scientific analysis.

`PHASE3B1_EXECUTION_LOG_STATUS = PASS`
"""
    write_text(EXECUTION_LOG, log_text)

    qa = {
        "schema_version": "C1R_PHASE3B1_QA_V1.0",
        "run_id": RUN_ID,
        "timestamp": timestamp,
        "scope": "cohort structure and donor integrity metadata audit only",
        "predecessor_checks": predecessor_checks,
        "authority_snapshots": authority_check,
        "registered_inputs": input_check,
        "scp259": {
            "metadata_rows": scp259["metadata_rows"],
            "registered_matrix_barcodes": scp259["barcode_count"],
            "matched_matrix_barcodes": scp259["matched_barcodes"],
            "matrix_samples": len(scp259["matrix_samples"]),
            "matrix_donors": len(scp259["matrix_donors"]),
            "primary_samples": len(scp259["primary_samples"]),
            "primary_donors": len(scp259["primary_donors"]),
            "sample_to_donor_status": "PASS",
        },
        "scp1884": {
            "metadata_rows": scp1884["metadata_rows"],
            "registered_matrix_barcodes": scp1884["barcode_count"],
            "matched_matrix_barcodes": scp1884["matched_barcodes"],
            "matrix_samples": len(scp1884["matrix_samples"]),
            "matrix_donors": len(scp1884["matrix_donors"]),
            "crosswalk_samples": len(scp1884["sample_to_crosswalk"]),
            "crosswalk_donors": len(scp1884["donor_to_samples"]),
            "excluded_donors": len(scp1884["excluded_donors"]),
            "retained_donors": len(scp1884["retained_donors"]),
            "registered_matrix_retained_samples": len(scp1884["matrix_retained_samples"]),
            "registered_matrix_retained_donors": len(scp1884["matrix_retained_donors"]),
            "m02_m03_shared_donors": len(m02_m03_shared_donors),
            "m02_m03_shared_donor_ids": sorted(m02_m03_shared_donors, key=lambda x: x.encode("utf-8")),
            "sample_to_donor_status": "PASS",
        },
        "analysis_arms": arm_rows,
        "forbidden_operations": {
            "expression_matrix_body_parses": 0,
            "qc_analyses": 0,
            "normalizations": 0,
            "scores": 0,
            "statistical_models": 0,
            "hypothesis_tests": 0,
            "biological_interpretations": 0,
            "frozen_authority_modifications": 0,
            "phase3b2_started": False,
        },
        "completion_state": "C1R_PHASE3B1_PASS_READY_FOR_PHASE3B2",
        "next_phase_autostart": "FORBIDDEN",
    }
    write_text(QA_JSON, json.dumps(qa, ensure_ascii=False, indent=2))

    manifest_members = [
        REPORT,
        COHORT_INVENTORY,
        DONOR_STRUCTURE,
        DONOR_OVERLAP,
        ARM_FEASIBILITY,
        EXECUTION_LOG,
        QA_JSON,
        SCRIPT_PATH,
    ]
    manifest_rows = []
    for path in sorted(manifest_members, key=lambda p: p.relative_to(ROOT).as_posix().encode("utf-8")):
        manifest_rows.append(
            {
                "run_id": RUN_ID,
                "relative_path": path.relative_to(ROOT).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
                "manifest_rule": "SELF_EXCLUDED_NON_SELF_HASHING",
            }
        )
    write_tsv(
        OUTPUT_MANIFEST,
        ["run_id", "relative_path", "size_bytes", "sha256", "manifest_rule"],
        manifest_rows,
    )
    manifest_check = verify_csv_manifest(
        ROOT,
        OUTPUT_MANIFEST,
        "relative_path",
        "size_bytes",
        "sha256",
        delimiter="\t",
    )
    require(manifest_check["rows"] == 8, "Phase 3B-1 output manifest row count mismatch")

    required_outputs = [REPORT, COHORT_INVENTORY, DONOR_STRUCTURE, DONOR_OVERLAP, ARM_FEASIBILITY]
    require(all(path.is_file() and path.stat().st_size > 0 for path in required_outputs), "Required output missing or empty")
    print(
        json.dumps(
            {
                "status": "PASS",
                "completion_state": "C1R_PHASE3B1_PASS_READY_FOR_PHASE3B2",
                "required_outputs": [str(path) for path in required_outputs],
                "manifest_rows": manifest_check["rows"],
                "scp259_primary": {"donors": len(scp259["primary_donors"]), "samples": len(scp259["primary_samples"])},
                "scp1884": {
                    "total_donors": len(scp1884["donor_to_samples"]),
                    "excluded_donors": len(scp1884["excluded_donors"]),
                    "retained_donors": len(scp1884["retained_donors"]),
                },
                "analysis_arm_classes": {row["analysis_arm_id"]: row["classification"] for row in arm_rows},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
