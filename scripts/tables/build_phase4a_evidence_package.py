from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


RUN_ID = "C1R_P4A_20260914"
PROJECT = Path(r"D:\SCIfour")
SOURCE = PROJECT / "phase3B_execution"
OUT = PROJECT / "35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE"
LOGS = OUT / "logs"
TABLES = OUT / "tables"

P3B2 = SOURCE / "phase3b2_reexecution"
P3B3 = SOURCE / "phase3b3_evidence_evaluation"
P3B4 = SOURCE / "phase3b4_biological_contextualization"

P3B3_MANIFEST = P3B3 / "provenance" / "phase3B3_output_manifest.tsv"
P3B4_MANIFEST = P3B4 / "provenance" / "phase3B4_output_manifest.tsv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def verify_manifest(root: Path, manifest: Path) -> dict[str, object]:
    rows = read_tsv(manifest)
    failures: list[dict[str, str]] = []
    for row in rows:
        candidate = root / Path(row["relative_path"].replace("/", os.sep))
        if not candidate.is_file():
            failures.append({"relative_path": row["relative_path"], "reason": "MISSING"})
            continue
        observed_size = candidate.stat().st_size
        observed_hash = sha256(candidate)
        if observed_size != int(row["size_bytes"]) or observed_hash != row["sha256"].upper():
            failures.append(
                {
                    "relative_path": row["relative_path"],
                    "reason": "SIZE_OR_SHA256_MISMATCH",
                    "expected_size": row["size_bytes"],
                    "observed_size": str(observed_size),
                    "expected_sha256": row["sha256"].upper(),
                    "observed_sha256": observed_hash,
                }
            )
    return {
        "manifest": str(manifest),
        "manifest_sha256": sha256(manifest),
        "rows": len(rows),
        "failures": failures,
        "status": "PASS" if not failures else "FAIL",
    }


def rel(path: Path) -> str:
    return path.relative_to(PROJECT).as_posix()


def fmt_num(value: str, digits: int = 4) -> str:
    if value in {"", "NA"}:
        return value
    number = float(value)
    if abs(number) < 0.0001 and number != 0:
        return f"{number:.4g}"
    return f"{number:.{digits}f}"


for directory in (OUT, LOGS, TABLES):
    directory.mkdir(parents=True, exist_ok=True)

protected_outputs = [
    OUT / "C1R_PHASE4A_PROMPT_REVIEW_AND_CONTROLLING_AMENDMENTS.md",
    OUT / "C1R_PHASE4A_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE_REPORT.md",
    OUT / "C1R_CLAIM_INVENTORY.tsv",
    OUT / "C1R_EVIDENCE_TRACEABILITY_MATRIX.tsv",
    OUT / "C1R_MANUSCRIPT_LIMITATION_REGISTER.tsv",
    OUT / "C1R_FIGURE_BLUEPRINT.tsv",
    OUT / "C1R_TABLE_BLUEPRINT.tsv",
    OUT / "C1R_EVIDENCE_PACKAGE_MANIFEST.tsv",
    LOGS / "C1R_PHASE4A_QA.json",
    LOGS / "PHASE4A_EXECUTION_LOG.md",
]
rebuild = sys.argv[1:] == ["--rebuild"]
if any(path.exists() for path in protected_outputs) and not rebuild:
    existing = [str(path) for path in protected_outputs if path.exists()]
    raise SystemExit("Refusing to overwrite Phase 4A outputs: " + "; ".join(existing))

source_pre = {
    "phase3b3": verify_manifest(P3B3, P3B3_MANIFEST),
    "phase3b4": verify_manifest(P3B4, P3B4_MANIFEST),
}
if any(item["status"] != "PASS" for item in source_pre.values()):
    raise SystemExit("Source manifest verification failed; Phase 4A not executed")

evidence_rows = read_tsv(P3B3 / "evidence_hierarchy_table.tsv")
effects = read_tsv(P3B3 / "donor_level_effect_summary.tsv")
arms = read_tsv(P3B2 / "donor_feasibility_precheck.tsv")
state_context = read_tsv(P3B4 / "state_feature_context_summary.tsv")
sp02_annotations = read_tsv(P3B4 / "sp02_biological_annotation_summary.tsv")
literature = read_tsv(P3B4 / "literature_evidence_registry.tsv")
exploratory = read_tsv(P3B4 / "exploratory_analysis_registry.tsv")
cell_qc = read_tsv(P3B2 / "cell_qc_characteristics.tsv")
state_representation = read_tsv(P3B2 / "state_representation_summary.tsv")
program_coverage = read_tsv(P3B2 / "genetic_program_coverage_summary.tsv")
sensitivity = read_tsv(P3B3 / "sensitivity_analysis_summary.tsv")

if len(evidence_rows) != 21:
    raise SystemExit(f"Expected 21 evidence rows; found {len(evidence_rows)}")
if len(effects) != 36:
    raise SystemExit(f"Expected 36 model rows; found {len(effects)}")
if len(arms) != 3:
    raise SystemExit(f"Expected 3 analysis arms; found {len(arms)}")

evidence_counts = Counter(row["evidence_class"] for row in evidence_rows)
expected_counts = {
    "PORTABILITY_SUPPORTED": 3,
    "DIRECTIONALLY_CONSISTENT_INSUFFICIENT": 12,
    "DISCORDANT": 3,
    "NOT_EVALUATED": 3,
}
if dict(evidence_counts) != expected_counts:
    raise SystemExit(f"Unexpected evidence class counts: {dict(evidence_counts)}")

primary_sp02 = next(
    row
    for row in evidence_rows
    if row["program_id"] == "GP_IBD_GCST004131_V1" and row["state_id"] == "SP02"
)
if primary_sp02["evidence_class"] != "PORTABILITY_SUPPORTED":
    raise SystemExit("Primary GP_IBD-SP02 evidence class changed")

m02 = next(row for row in arms if row["analysis_arm_id"] == "M02")
if m02["donor_count"] != "5":
    raise SystemExit("M02 donor count is not the frozen five-donor floor")

prompt_review = f"""# C1-R Phase 4A prompt review and controlling amendments

Review date: 2026-09-14 (Asia/Shanghai)  
Disposition: `MODIFY_THEN_EXECUTE`  
Review timing: completed before Phase 4A manuscript-facing claims or table selections were written

## Review conclusion

The submitted Prompt has a valid purpose, preserves frozen scientific objects, requires negative evidence and limitations, prohibits new analysis, names the core deliverables, and supplies a fail-closed completion state. It required bounded non-scientific amendments before execution because the output root and schemas were unspecified, the relationship between evidence level and claim status was ambiguous, the phrase "demonstrates portability-supported" could be read more strongly than the frozen evidence class, the 21-pair completeness rule was not explicit, and Section 9 requested tables without naming their files.

## Controlling amendments

1. **Activation and source authority.** The present user instruction expressly activates Phase 4A. The Phase 3B-3 and Phase 3B-4 readiness tokens are eligibility conditions only. Their self-excluding manifests must verify before and after this phase.
2. **Non-overwriting output root.** All outputs are new derivatives under `{OUT}`. Phase 3B-2 re-execution, Phase 3B-3, Phase 3B-4, frozen authorities, inputs, scientific objects, evidence classes, and source manifests remain unchanged.
3. **Two-axis claim schema.** `evidence_level` records `LEVEL_1_DIRECT`, `LEVEL_2_EXTERNAL_CONTEXT`, `LEVEL_3_FUTURE_HYPOTHESIS`, or `PROHIBITED`. `claim_status` independently records only `SUPPORTED`, `CONTEXT_ONLY`, `HYPOTHESIS_ONLY`, or `NOT_ALLOWED`. Frozen Phase 3B-3 evidence classes are copied verbatim into `frozen_evidence_class` and are never reclassified.
4. **Primary wording.** The controlling main claim is: under the frozen donor-level expression-score contract, GP_IBD-SP02 was negative in M01 and M02 and was classified `PORTABILITY_SUPPORTED`. This does not demonstrate a PRS association, inherited genetic effect, causality, mechanism, independent validation, biomarker utility, or therapeutic relevance.
5. **Complete landscape.** The claim inventory and Table 2 preserve all 21 program-state mappings: 3 `PORTABILITY_SUPPORTED`, 12 `DIRECTIONALLY_CONSISTENT_INSUFFICIENT`, 3 `DISCORDANT`, and 3 `NOT_EVALUATED`. `NOT_EVALUATED` is not negative evidence. Exploratory program families remain non-confirmatory.
6. **Manuscript-facing tables.** Section 9 is implemented as four frozen TSV derivatives under `tables/`, plus a table blueprint. These are selections or copies of frozen outputs; no statistic is recalculated.
7. **Figure scope.** Phase 4A freezes figure logic only. It does not render figures, choose post-result thresholds, derive new panels, or run any analysis.
8. **External context.** Level 2 statements use only the frozen Phase 3B-4 literature and annotation registries. No new literature search or claim upgrade occurs in this phase.
9. **Mechanical traceability.** Every claim-inventory row has exactly one traceability row and a declared manuscript/figure/table destination or an explicit exclusion destination.
10. **Hard stop.** `C1R_PHASE4A_PASS_READY_FOR_FIGURE_DESIGN_AND_MANUSCRIPT_DRAFTING` closes Phase 4A only. Figure production, manuscript drafting, new analysis, portal activity, or any later phase must not autostart.

`PHASE4A_PROMPT_REVIEW = MODIFY_THEN_EXECUTE`
"""
write_text(OUT / "C1R_PHASE4A_PROMPT_REVIEW_AND_CONTROLLING_AMENDMENTS.md", prompt_review)


claims: list[dict[str, object]] = []


def add_claim(
    claim_id: str,
    package_id: str,
    claim_text: str,
    evidence_level: str,
    claim_status: str,
    frozen_evidence_class: str,
    claim_function: str,
    supporting_analysis: str,
    supporting_file: str,
    source_anchor: str,
    allowed_section: str,
    figure_id: str,
    table_id: str,
    limitation: str,
) -> None:
    claims.append(
        {
            "claim_id": claim_id,
            "package_id": package_id,
            "claim_text": claim_text,
            "evidence_level": evidence_level,
            "claim_status": claim_status,
            "frozen_evidence_class": frozen_evidence_class,
            "claim_function": claim_function,
            "supporting_analysis": supporting_analysis,
            "supporting_file": supporting_file,
            "source_anchor": source_anchor,
            "allowed_section": allowed_section,
            "figure_id": figure_id,
            "table_id": table_id,
            "limitation": limitation,
        }
    )


add_claim(
    "C001",
    "A_CORE_FINDINGS",
    "C1-R evaluated predefined GWAS-linked expression programs against predefined epithelial-state scores using donor-level aggregation in the frozen M01 discovery and M02 portability contexts.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "NA_DESIGN_STATEMENT",
    "APPROACH",
    "PHASE3B2_REEXEC;PHASE3B3",
    f"{rel(P3B2 / 'donor_feasibility_precheck.tsv')};{rel(P3B3 / 'C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md')}",
    "all arm rows; Sections 1-3",
    "ABSTRACT;INTRODUCTION;METHODS;RESULTS",
    "F1",
    "T1",
    "Programs are expression-gene-set scores, not donor PRS or inherited-risk measurements; M03 was outside the initial execution.",
)

add_claim(
    "C002",
    "A_CORE_FINDINGS",
    f"Under the frozen donor-level expression-score contract, GP_IBD-SP02 was negative in M01 (beta {fmt_num(primary_sp02['m01_beta'])}; BH-adjusted P {fmt_num(primary_sp02['m01_bh_adjusted_p'])}) and M02 (beta {fmt_num(primary_sp02['m02_beta'])}; BH-adjusted P {fmt_num(primary_sp02['m02_bh_adjusted_p'])}) and was classified PORTABILITY_SUPPORTED.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "PORTABILITY_SUPPORTED",
    "CORE_DISCOVERY",
    "PHASE3B3",
    rel(P3B3 / "evidence_hierarchy_table.tsv"),
    "GP_IBD_GCST004131_V1 x SP02",
    "ABSTRACT;RESULTS;DISCUSSION;CONCLUSION",
    "F2;F3",
    "T2;T3",
    "M02 has exactly five donors and bounded metadata; association is between expression scores and is not causal, mechanistic, clinical, or independent validation.",
)

add_claim(
    "C003",
    "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES",
    "The program-state evidence landscape was selective rather than universal: 3 of 21 mappings were PORTABILITY_SUPPORTED, 12 were DIRECTIONALLY_CONSISTENT_INSUFFICIENT, 3 were DISCORDANT, and 3 were NOT_EVALUATED.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "MIXED_COMPLETE_LANDSCAPE",
    "SYNTHESIS_AND_QUALIFICATION",
    "PHASE3B3",
    rel(P3B3 / "evidence_hierarchy_table.tsv"),
    "all 21 rows",
    "ABSTRACT;RESULTS;DISCUSSION;CONCLUSION",
    "F2",
    "T2",
    "NOT_EVALUATED mappings are outside the frozen test families and must not be interpreted as negative evidence; exploratory families are not confirmatory.",
)

add_claim(
    "C004",
    "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES",
    "M02 contained exactly five donors, the frozen minimum donor floor, and therefore retains small-sample and HC3 fragility.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "NA_LIMITATION_STATEMENT",
    "QUALIFICATION",
    "PHASE3B2_REEXEC;PHASE3B3",
    f"{rel(P3B2 / 'donor_feasibility_precheck.tsv')};{rel(P3B3 / 'donor_level_effect_summary.tsv')}",
    "M02 row; all M02 model rows",
    "RESULTS;DISCUSSION;LIMITATIONS",
    "F3;SF1",
    "T1;T3",
    "At-floor inference does not establish broad or independent portability.",
)

add_claim(
    "C005",
    "B_BIOLOGICAL_INTERPRETATION",
    "SP02 is the frozen INFLARE epithelial state defined by the unchanged four-gene set MUC6, BPIFB1, AQP5, and PGC.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "NA_FROZEN_STATE_IDENTITY",
    "IDENTITY",
    "PHASE3B4",
    rel(P3B4 / "state_feature_context_summary.tsv"),
    "SP02 row",
    "METHODS;RESULTS;DISCUSSION",
    "F4",
    "T4",
    "A four-gene definition is a bounded marker program, not a measured function or state-frequency estimate.",
)

add_claim(
    "C006",
    "B_BIOLOGICAL_INTERPRETATION",
    "Published human evidence places the SP02 marker combination in a gastric/pyloric or Brunner-gland-neck-like metaplastic context in inflammatory intestinal disease.",
    "LEVEL_2_EXTERNAL_CONTEXT",
    "CONTEXT_ONLY",
    "NA_EXTERNAL_CONTEXT",
    "INTERPRETATION",
    "PHASE3B4",
    f"{rel(P3B4 / 'literature_evidence_registry.tsv')};{rel(P3B4 / 'sp02_biological_annotation_summary.tsv')}",
    "LIT01-LIT03; SP02_AGGREGATE",
    "DISCUSSION",
    "F4",
    "T4",
    "The defining atlas is source-proximal and includes SCP1884; this is context, not independent validation of the C1-R association.",
)

add_claim(
    "C007",
    "B_BIOLOGICAL_INTERPRETATION",
    "The corrected exploratory local ORA found one reportable annotation term, digestion, in a 13,362-term combined GO:BP/Reactome family.",
    "LEVEL_2_EXTERNAL_CONTEXT",
    "CONTEXT_ONLY",
    "NA_EXPLORATORY_ANNOTATION",
    "SUPPORTING_CONTEXT",
    "PHASE3B4",
    f"{rel(P3B4 / 'pathway_context_summary.tsv')};{rel(P3B4 / 'exploratory_analysis_registry.tsv')}",
    "GO:0007586; EX01",
    "DISCUSSION;SUPPLEMENTARY_INFORMATION",
    "SF4",
    "T4",
    "Annotation-dependent four-gene ORA supports only marker-set coherence; the first-pass 20-term BH result is superseded and must not be cited.",
)

add_claim(
    "C008",
    "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES",
    "No authorized sensitivity analysis, M03 model, state-frequency estimate, perturbational test, or spatial causal test was performed in Phases 3B-3 or 3B-4.",
    "LEVEL_1_DIRECT",
    "SUPPORTED",
    "NA_EXECUTION_BOUNDARY",
    "BOUNDARY",
    "PHASE3B3;PHASE3B4",
    f"{rel(P3B3 / 'sensitivity_analysis_summary.tsv')};{rel(P3B4 / 'exploratory_analysis_registry.tsv')}",
    "all rows; EX05-EX06",
    "METHODS;RESULTS;DISCUSSION;LIMITATIONS",
    "SF4",
    "T2",
    "Absence of these analyses limits robustness, state-abundance, spatial, experimental, and mechanistic conclusions.",
)


for index, row in enumerate(evidence_rows, start=1):
    program = row["program_id"]
    state = row["state_id"]
    pair = f"{program} x {state}"
    if row["evidence_class"] == "NOT_EVALUATED":
        text = (
            f"{pair} was NOT_EVALUATED outside the frozen test families and must not be treated as evidence for or against an association."
        )
    else:
        role_note = "primary" if row["pair_role"] == "PRIMARY" else "exploratory and non-confirmatory"
        text = (
            f"Under the frozen {role_note} contract, {pair} was classified {row['evidence_class']} across M01 and M02; "
            f"M01 direction was {row['m01_direction']} and M02 direction was {row['m02_direction']}."
        )
    package = (
        "A_CORE_FINDINGS"
        if row["evidence_class"] == "PORTABILITY_SUPPORTED"
        else "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES"
    )
    destination = "RESULTS;SUPPLEMENTARY_INFORMATION"
    if row["pair_role"] == "PRIMARY":
        destination = "RESULTS"
    add_claim(
        f"P{index:03d}",
        package,
        text,
        "LEVEL_1_DIRECT",
        "SUPPORTED",
        row["evidence_class"],
        "PAIRWISE_EVIDENCE_RECORD",
        "PHASE3B3",
        rel(P3B3 / "evidence_hierarchy_table.tsv"),
        pair,
        destination,
        "F2" if row["pair_role"] == "PRIMARY" else "F2;SF3",
        "T2" if row["pair_role"] == "PRIMARY" else "T2;ST3",
        "M03 was not evaluated; exploratory program-family results are non-confirmatory; retain the source interpretation ceiling.",
    )


hypotheses = [
    (
        "H001",
        "Future studies could test whether SP02 abundance or function changes with intestinal injury.",
        "C1-R did not estimate SP02 frequency or function.",
    ),
    (
        "H002",
        "A larger source-independent donor cohort could test the generalizability of the GP_IBD-SP02 association.",
        "M02 has five donors and source-proximal metadata and literature context.",
    ),
    (
        "H003",
        "Perturbational or spatial experiments could test whether any SP02-associated pathway is mechanistically active.",
        "C1-R performed annotation-based contextualization without causal or spatial testing.",
    ),
]
for claim_id, text, limitation in hypotheses:
    add_claim(
        claim_id,
        "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES",
        text,
        "LEVEL_3_FUTURE_HYPOTHESIS",
        "HYPOTHESIS_ONLY",
        "NA_FUTURE_HYPOTHESIS",
        "FUTURE_DIRECTION",
        "PHASE3B4",
        rel(P3B4 / "C1R_PHASE3B4_EPITHELIAL_STATE_BIOLOGICAL_CONTEXTUALIZATION_REPORT.md"),
        "Section 5",
        "DISCUSSION_FUTURE_DIRECTIONS_ONLY",
        "NA",
        "NA",
        limitation,
    )


not_allowed = [
    ("N001", "Genetic variants cause SP02."),
    ("N002", "Inherited IBD risk directly creates SP02."),
    ("N003", "A causal GP_IBD-to-SP02 pathway was established."),
    ("N004", "SP02 drives intestinal inflammation."),
    ("N005", "SP02 mediates disease progression."),
    ("N006", "SP02 is a diagnostic marker."),
    ("N007", "SP02 is a prognostic marker."),
    ("N008", "SP02 or the GP_IBD-SP02 association is a therapeutic target."),
    ("N009", "M02 provides independent biological validation or direct replication."),
    ("N010", "The exploratory ORA experimentally confirms a digestive mechanism in SP02."),
]
for claim_id, text in not_allowed:
    add_claim(
        claim_id,
        "C_NEGATIVE_EVIDENCE_AND_BOUNDARIES",
        text,
        "PROHIBITED",
        "NOT_ALLOWED",
        "NA_PROHIBITED",
        "EXCLUDED_CLAIM",
        "PHASE3B_PRE;PHASE3B3;PHASE3B4",
        f"{rel(P3B3 / 'C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md')};{rel(P3B4 / 'C1R_PHASE3B4_EPITHELIAL_STATE_BIOLOGICAL_CONTEXTUALIZATION_REPORT.md')}",
        "claim ceilings and limitations",
        "NOT_IN_MANUSCRIPT",
        "NA",
        "NA",
        "The study design does not measure inherited risk, causality, mechanism, clinical utility, or independent experimental validation.",
    )


claim_fields = [
    "claim_id",
    "package_id",
    "claim_text",
    "evidence_level",
    "claim_status",
    "frozen_evidence_class",
    "claim_function",
    "supporting_analysis",
    "supporting_file",
    "source_anchor",
    "allowed_section",
    "figure_id",
    "table_id",
    "limitation",
]
write_tsv(OUT / "C1R_CLAIM_INVENTORY.tsv", claims, claim_fields)


trace_rows = []
for claim in claims:
    trace_rows.append(
        {
            "claim_id": claim["claim_id"],
            "claim_text": claim["claim_text"],
            "claim_status": claim["claim_status"],
            "evidence_level": claim["evidence_level"],
            "analysis_output": claim["supporting_analysis"],
            "source_file": claim["supporting_file"],
            "source_anchor": claim["source_anchor"],
            "figure_id": claim["figure_id"],
            "table_id": claim["table_id"],
            "manuscript_destination": claim["allowed_section"],
            "trace_status": "TRACEABLE_EXCLUDED" if claim["claim_status"] == "NOT_ALLOWED" else "TRACEABLE",
            "limitation": claim["limitation"],
        }
    )
trace_fields = [
    "claim_id",
    "claim_text",
    "claim_status",
    "evidence_level",
    "analysis_output",
    "source_file",
    "source_anchor",
    "figure_id",
    "table_id",
    "manuscript_destination",
    "trace_status",
    "limitation",
]
write_tsv(OUT / "C1R_EVIDENCE_TRACEABILITY_MATRIX.tsv", trace_rows, trace_fields)


limitations = [
    {
        "limitation_id": "L001",
        "limitation_text": "M02 contains exactly five donors, the frozen minimum donor floor.",
        "affected_claim_ids": "C002;C004;P001-P021",
        "affected_scope": "PORTABILITY_AND_ALL_M02_ESTIMATES",
        "interpretation_consequence": "HC3 inference is fragile and does not support broad generalization.",
        "what_remains_supported": "The frozen within-design M02 estimates and Phase 3B-3 evidence classes remain reportable with this limitation.",
        "required_resolution": "A larger source-independent donor cohort.",
        "main_text_visibility": "MANDATORY_RESULTS_AND_DISCUSSION",
        "supporting_file": rel(P3B2 / "donor_feasibility_precheck.tsv"),
    },
    {
        "limitation_id": "L002",
        "limitation_text": "SCP1884 metadata has a bounded author-metadata role and is not exact Portal-v2 metadata.",
        "affected_claim_ids": "C001;C002;C004;P001-P021",
        "affected_scope": "M02_AND_M03_CONTEXT",
        "interpretation_consequence": "M02 is not pristine independent validation or direct replication.",
        "what_remains_supported": "Bounded donor-level portability assessment under the frozen authority framework.",
        "required_resolution": "Source-bound exact metadata and an independent cohort.",
        "main_text_visibility": "MANDATORY_METHODS_AND_LIMITATIONS",
        "supporting_file": rel(P3B2 / "donor_feasibility_precheck.tsv"),
    },
    {
        "limitation_id": "L003",
        "limitation_text": "The defining SP02/INFLARE literature is source-proximal and includes SCP1884 among integrated datasets.",
        "affected_claim_ids": "C005;C006",
        "affected_scope": "SP02_BIOLOGICAL_CONTEXT",
        "interpretation_consequence": "The literature supports context only and cannot independently validate the C1-R association.",
        "what_remains_supported": "Gastric/pyloric or Brunner-like metaplastic contextual similarity.",
        "required_resolution": "Independent marker and tissue validation in a non-overlapping cohort.",
        "main_text_visibility": "MANDATORY_DISCUSSION",
        "supporting_file": rel(P3B4 / "literature_evidence_registry.tsv"),
    },
    {
        "limitation_id": "L004",
        "limitation_text": "SP02 is defined by the frozen four-gene set MUC6, BPIFB1, AQP5, and PGC.",
        "affected_claim_ids": "C005;C006;C007",
        "affected_scope": "SP02_IDENTITY_AND_ANNOTATION",
        "interpretation_consequence": "The compact marker definition cannot establish full state function, heterogeneity, or abundance.",
        "what_remains_supported": "The exact frozen state identity and its bounded annotation context.",
        "required_resolution": "Independent state characterization without redefining the current frozen object.",
        "main_text_visibility": "MANDATORY_METHODS_AND_DISCUSSION",
        "supporting_file": rel(P3B4 / "sp02_biological_annotation_summary.tsv"),
    },
    {
        "limitation_id": "L005",
        "limitation_text": "No causal or inherited-risk validation was performed.",
        "affected_claim_ids": "C001;C002;N001-N005",
        "affected_scope": "GENETIC_CAUSALITY_AND_DISEASE_MECHANISM",
        "interpretation_consequence": "Expression-score associations cannot be described as genetic causality or mechanism.",
        "what_remains_supported": "Donor-level association evidence under the frozen expression-score contract.",
        "required_resolution": "Appropriately designed genetic, longitudinal, or perturbational causal analyses.",
        "main_text_visibility": "MANDATORY_ABSTRACT_RESULTS_DISCUSSION",
        "supporting_file": rel(P3B3 / "C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md"),
    },
    {
        "limitation_id": "L006",
        "limitation_text": "C1-R lacks spatial and experimental validation of the association.",
        "affected_claim_ids": "C006;C008;H003;N009-N010",
        "affected_scope": "BIOLOGICAL_AND_MECHANISTIC_INTERPRETATION",
        "interpretation_consequence": "Localization and mechanism remain untested within C1-R.",
        "what_remains_supported": "External source-supported context and frozen donor-level association evidence.",
        "required_resolution": "Independent spatial localization and perturbational experiments.",
        "main_text_visibility": "MANDATORY_DISCUSSION_AND_LIMITATIONS",
        "supporting_file": rel(P3B4 / "C1R_PHASE3B4_EPITHELIAL_STATE_BIOLOGICAL_CONTEXTUALIZATION_REPORT.md"),
    },
    {
        "limitation_id": "L007",
        "limitation_text": "GP_IBD is a frozen GWAS-linked expression-gene set score, not a donor PRS or measured inherited-risk exposure.",
        "affected_claim_ids": "C001;C002;N001-N003",
        "affected_scope": "GENETIC_PROGRAM_INTERPRETATION",
        "interpretation_consequence": "The score cannot be described as individual genetic burden.",
        "what_remains_supported": "Association between two donor-aggregated expression scores.",
        "required_resolution": "A prospectively designed donor-genotype analysis.",
        "main_text_visibility": "MANDATORY_METHODS_RESULTS_DISCUSSION",
        "supporting_file": rel(P3B3 / "C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md"),
    },
    {
        "limitation_id": "L008",
        "limitation_text": "M03 was outside the frozen initial execution and cannot rescue or replace M02.",
        "affected_claim_ids": "C001;C008;P001-P021",
        "affected_scope": "EXPLORATORY_CONTEXT",
        "interpretation_consequence": "No inference may be upgraded using M03.",
        "what_remains_supported": "M01 and M02 results only.",
        "required_resolution": "Separate prospective authorization and frozen analysis contract.",
        "main_text_visibility": "METHODS_OR_LIMITATIONS",
        "supporting_file": rel(P3B3 / "sensitivity_analysis_summary.tsv"),
    },
    {
        "limitation_id": "L009",
        "limitation_text": "Donor leave-one-out, alternative aggregation, Spearman, full-program, segment-exclusion, and M03 sensitivities were not authorized or run.",
        "affected_claim_ids": "C002;C003;C008",
        "affected_scope": "ROBUSTNESS",
        "interpretation_consequence": "Robustness beyond the frozen primary specification is not established.",
        "what_remains_supported": "The exact prespecified primary specification and its audited outputs.",
        "required_resolution": "Prospectively freeze and authorize sensitivity analyses.",
        "main_text_visibility": "DISCUSSION_AND_SUPPLEMENTARY_METHODS",
        "supporting_file": rel(P3B3 / "sensitivity_analysis_summary.tsv"),
    },
    {
        "limitation_id": "L010",
        "limitation_text": "GP_IBD-SP05, GP_IBD-SP06, and GP_IBD-SP07 were not evaluated outside the frozen primary test family.",
        "affected_claim_ids": "C003;P005-P007",
        "affected_scope": "COMPLETE_21_PAIR_LANDSCAPE",
        "interpretation_consequence": "These mappings are neither positive nor negative evidence.",
        "what_remains_supported": "The mapping inventory and the evaluated 18-pair evidence record.",
        "required_resolution": "Separate prospective test-family authorization.",
        "main_text_visibility": "MANDATORY_FIGURE2_AND_TABLE2",
        "supporting_file": rel(P3B3 / "evidence_hierarchy_table.tsv"),
    },
    {
        "limitation_id": "L011",
        "limitation_text": "No SP02 state-frequency or abundance estimate was produced.",
        "affected_claim_ids": "C005;C008;H001",
        "affected_scope": "STATE_ABUNDANCE",
        "interpretation_consequence": "The association cannot be reframed as a change in SP02 cell abundance.",
        "what_remains_supported": "Association between donor-level expression scores.",
        "required_resolution": "A prospectively defined state-assignment and abundance analysis.",
        "main_text_visibility": "MANDATORY_RESULTS_AND_DISCUSSION",
        "supporting_file": rel(P3B4 / "exploratory_analysis_registry.tsv"),
    },
    {
        "limitation_id": "L012",
        "limitation_text": "The SP02 ORA is exploratory, annotation-dependent, and based on four query genes.",
        "affected_claim_ids": "C007;H003;N010",
        "affected_scope": "PATHWAY_CONTEXT",
        "interpretation_consequence": "The single reportable term cannot establish pathway activity, direction, or mechanism.",
        "what_remains_supported": "A bounded annotation-coherence observation after full-family BH correction.",
        "required_resolution": "Independent functional or perturbational evidence.",
        "main_text_visibility": "DISCUSSION_OR_SUPPLEMENTARY_INFORMATION",
        "supporting_file": rel(P3B4 / "exploratory_analysis_registry.tsv"),
    },
    {
        "limitation_id": "L013",
        "limitation_text": "M01 is a broad-colon UC context; exact subsegment is unresolved for 15 of 133 source samples overall and platform/chemistry mapping is incomplete.",
        "affected_claim_ids": "C001;C002;P001-P021",
        "affected_scope": "M01_CONTEXT_AND_GENERALIZATION",
        "interpretation_consequence": "Anatomical and technical heterogeneity limits fine-grained localization of the M01 result.",
        "what_remains_supported": "The frozen broad-colon M01 donor-level association analysis.",
        "required_resolution": "Complete source-bound subsegment and platform metadata.",
        "main_text_visibility": "METHODS_AND_LIMITATIONS",
        "supporting_file": rel(P3B2 / "donor_feasibility_precheck.tsv"),
    },
    {
        "limitation_id": "L014",
        "limitation_text": "Exploratory GP_CD and GP_UC multiplicity families are non-confirmatory even when classified PORTABILITY_SUPPORTED.",
        "affected_claim_ids": "P008-P021",
        "affected_scope": "EXPLORATORY_PROGRAMS",
        "interpretation_consequence": "Exploratory relationships cannot be promoted to confirmatory conclusions.",
        "what_remains_supported": "Their exact frozen evidence classes as exploratory results.",
        "required_resolution": "Independent prospectively powered confirmatory testing.",
        "main_text_visibility": "MANDATORY_TABLE2_AND_SUPPLEMENTARY_RESULTS",
        "supporting_file": rel(P3B3 / "multiplicity_control_summary.tsv"),
    },
]
limitation_fields = [
    "limitation_id",
    "limitation_text",
    "affected_claim_ids",
    "affected_scope",
    "interpretation_consequence",
    "what_remains_supported",
    "required_resolution",
    "main_text_visibility",
    "supporting_file",
]
write_tsv(OUT / "C1R_MANUSCRIPT_LIMITATION_REGISTER.tsv", limitations, limitation_fields)


figure_rows = [
    {
        "figure_id": "F1",
        "figure_title": "Study framework and frozen analytical design",
        "panel_id": "F1A",
        "panel_content": "Three predefined genetic programs, seven predefined epithelial states, and frozen non-overlap masks.",
        "evidence_role": "APPROACH",
        "source_file": rel(P3B3 / "C1R_PHASE3B3_GENETIC_PROGRAM_STATE_EVIDENCE_EVALUATION_REPORT.md"),
        "source_fields_or_anchor": "Sections 1 and 3",
        "claim_ids": "C001",
        "allowed_transformation": "Diagrammatic layout of frozen objects only.",
        "forbidden_elements": "No new pathway, causal arrow, cell-state discovery, or weighting.",
        "mandatory_limitation_display": "Programs are expression-gene-set scores, not PRS.",
    },
    {
        "figure_id": "F1",
        "figure_title": "Study framework and frozen analytical design",
        "panel_id": "F1B",
        "panel_content": "M01 discovery, M02 bounded portability, M03 outside initial execution; donor-level aggregation hierarchy.",
        "evidence_role": "APPROACH_AND_BOUNDARY",
        "source_file": rel(P3B2 / "donor_feasibility_precheck.tsv"),
        "source_fields_or_anchor": "all arm rows",
        "claim_ids": "C001;C004;C008",
        "allowed_transformation": "Counts and role labels copied exactly.",
        "forbidden_elements": "No pooling of contexts and no M03 rescue arrow.",
        "mandatory_limitation_display": "M02 n=5; M03 not evaluated.",
    },
    {
        "figure_id": "F2",
        "figure_title": "Complete genetic program-epithelial state evidence landscape",
        "panel_id": "F2A",
        "panel_content": "All 21 mappings displayed by frozen evidence class.",
        "evidence_role": "CORE_DISCOVERY_AND_NEGATIVE_EVIDENCE",
        "source_file": rel(P3B3 / "evidence_hierarchy_table.tsv"),
        "source_fields_or_anchor": "all rows; evidence_class",
        "claim_ids": "C003;P001-P021",
        "allowed_transformation": "Categorical matrix with fixed legend and full row/column inventory.",
        "forbidden_elements": "No omission of discordant, insufficient, or not-evaluated cells; no reclassification.",
        "mandatory_limitation_display": "NOT_EVALUATED is not negative evidence; exploratory families non-confirmatory.",
    },
    {
        "figure_id": "F2",
        "figure_title": "Complete genetic program-epithelial state evidence landscape",
        "panel_id": "F2B",
        "panel_content": "M01 and M02 standardized beta direction and BH-adjusted P for evaluated mappings.",
        "evidence_role": "DECISIVE_SUPPORT",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "source_fields_or_anchor": "36 model rows",
        "claim_ids": "C002;C003;P001-P021",
        "allowed_transformation": "Display existing beta, interval, and family-adjusted P values only.",
        "forbidden_elements": "No new threshold, combined effect, meta-analysis, or cross-family multiplicity.",
        "mandatory_limitation_display": "Primary and exploratory families must be visually distinct.",
    },
    {
        "figure_id": "F3",
        "figure_title": "Donor-level evidence for the primary GP_IBD associations",
        "panel_id": "F3A",
        "panel_content": "Forest display of the eight frozen primary-family estimates across SP01-SP04 in M01 and M02.",
        "evidence_role": "PRIMARY_NUMERIC_EVIDENCE",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "source_fields_or_anchor": "family=PRIMARY_8",
        "claim_ids": "C002;C004;P001-P004",
        "allowed_transformation": "Plot beta and existing 95% Wald interval; annotate existing BH-adjusted P.",
        "forbidden_elements": "No raw-cell inference, pooled estimate, new confidence interval, or post-hoc subgroup.",
        "mandatory_limitation_display": "M01 n=14; M02 n=5; HC3 and bounded portability wording.",
    },
    {
        "figure_id": "F3",
        "figure_title": "Donor-level evidence for the primary GP_IBD associations",
        "panel_id": "F3B",
        "panel_content": "Focused M01/M02 GP_IBD-SP02 estimate pair with exact negative direction and uncertainty.",
        "evidence_role": "CORE_DISCOVERY",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "source_fields_or_anchor": "program=GP_IBD_GCST004131_V1; state=SP02",
        "claim_ids": "C002;C004",
        "allowed_transformation": "Direct display of frozen donor-level estimates.",
        "forbidden_elements": "No causal arrows, PRS label, abundance label, or independent-validation label.",
        "mandatory_limitation_display": "Association between expression scores only.",
    },
    {
        "figure_id": "F4",
        "figure_title": "SP02 biological contextualization and evidence hierarchy",
        "panel_id": "F4A",
        "panel_content": "Exact frozen SP02 four-gene membership and descriptive marker annotations.",
        "evidence_role": "IDENTITY_AND_CONTEXT",
        "source_file": rel(P3B4 / "sp02_biological_annotation_summary.tsv"),
        "source_fields_or_anchor": "all five rows",
        "claim_ids": "C005;C006",
        "allowed_transformation": "Label-only schematic separating frozen identity from external context.",
        "forbidden_elements": "No expression heatmap, inferred function, cell frequency, or marker expansion.",
        "mandatory_limitation_display": "Four-gene definition; functions not measured in C1-R.",
    },
    {
        "figure_id": "F4",
        "figure_title": "SP02 biological contextualization and evidence hierarchy",
        "panel_id": "F4B",
        "panel_content": "Level 1 association, Level 2 source-proximal context, and Level 3 future-validation boundary.",
        "evidence_role": "INTERPRETATION_HIERARCHY",
        "source_file": rel(P3B4 / "evidence_to_biology_linkage_table.tsv"),
        "source_fields_or_anchor": "GP_IBD_GCST004131_V1 x SP02",
        "claim_ids": "C002;C006;H001-H003",
        "allowed_transformation": "Three-level evidence ladder with explicit source class.",
        "forbidden_elements": "No claim-level upgrade and no future hypothesis in conclusions.",
        "mandatory_limitation_display": "Context is not validation; hypotheses are future directions only.",
    },
    {
        "figure_id": "SF1",
        "figure_title": "Supplementary cohort structure and descriptive QC",
        "panel_id": "SF1",
        "panel_content": "Frozen arm counts and descriptive cell-level QC characteristics.",
        "evidence_role": "PROVENANCE_AND_DESCRIPTIVE_QC",
        "source_file": f"{rel(P3B2 / 'donor_feasibility_precheck.tsv')};{rel(P3B2 / 'cell_qc_characteristics.tsv')}",
        "source_fields_or_anchor": "all frozen rows",
        "claim_ids": "C001;C004",
        "allowed_transformation": "Descriptive visualization of existing counts and summaries.",
        "forbidden_elements": "No filtering, state assignment, or cell-level inference.",
        "mandatory_limitation_display": "QC is descriptive; M02 n=5.",
    },
    {
        "figure_id": "SF2",
        "figure_title": "Supplementary state representation and program coverage",
        "panel_id": "SF2",
        "panel_content": "Complete frozen state-representation and program-coverage audits.",
        "evidence_role": "STRUCTURAL_ESTIMABILITY",
        "source_file": f"{rel(P3B2 / 'state_representation_summary.tsv')};{rel(P3B2 / 'genetic_program_coverage_summary.tsv')}",
        "source_fields_or_anchor": "all frozen rows",
        "claim_ids": "C001;C008",
        "allowed_transformation": "Descriptive visualization of existing coverage and representation fields.",
        "forbidden_elements": "No state-positive calls, reweighting, or inferred biological adequacy.",
        "mandatory_limitation_display": "Representation and coverage are structural only.",
    },
    {
        "figure_id": "SF3",
        "figure_title": "Supplementary complete donor-level evidence record",
        "panel_id": "SF3",
        "panel_content": "All 36 authorized donor-level models, including exploratory, insufficient, and discordant evidence.",
        "evidence_role": "COMPLETE_EVIDENCE_RECORD",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "source_fields_or_anchor": "all 36 frozen model rows",
        "claim_ids": "C002;C003;P001-P021",
        "allowed_transformation": "Display existing estimates, intervals, directions, and family-adjusted P values.",
        "forbidden_elements": "No omitted adverse evidence, pooled estimate, reclassification, or cross-family multiplicity.",
        "mandatory_limitation_display": "Exploratory families are non-confirmatory; M03 not evaluated.",
    },
    {
        "figure_id": "SF4",
        "figure_title": "Supplementary exploratory annotation and unexecuted-sensitivity boundaries",
        "panel_id": "SF4",
        "panel_content": "Corrected ORA result and registry of analyses not run or scope-bound.",
        "evidence_role": "CONTEXT_AND_BOUNDARY",
        "source_file": f"{rel(P3B4 / 'pathway_context_summary.tsv')};{rel(P3B3 / 'sensitivity_analysis_summary.tsv')};{rel(P3B4 / 'exploratory_analysis_registry.tsv')}",
        "source_fields_or_anchor": "GO:0007586; all sensitivity rows; EX01-EX06",
        "claim_ids": "C007;C008",
        "allowed_transformation": "Show corrected full-family result and explicit not-run statuses.",
        "forbidden_elements": "Do not cite superseded three-term first pass or imply mechanism.",
        "mandatory_limitation_display": "Four-gene, annotation-dependent, exploratory result.",
    },
]
figure_fields = [
    "figure_id",
    "figure_title",
    "panel_id",
    "panel_content",
    "evidence_role",
    "source_file",
    "source_fields_or_anchor",
    "claim_ids",
    "allowed_transformation",
    "forbidden_elements",
    "mandatory_limitation_display",
]
write_tsv(OUT / "C1R_FIGURE_BLUEPRINT.tsv", figure_rows, figure_fields)


table1_fields = [
    "analysis_arm_id",
    "dataset_identifier",
    "frozen_role",
    "donor_count",
    "sample_count",
    "represented_cell_count",
    "states_passing_coverage",
    "states_total",
    "full_programs_passing_coverage",
    "full_programs_total",
    "program_state_nonoverlap_masks_passing",
    "program_state_nonoverlap_masks_total",
    "classification",
    "limitations",
]
write_tsv(TABLES / "Table1_study_cohorts_and_analytical_framework.tsv", arms, table1_fields)

table2_fields = list(evidence_rows[0].keys())
write_tsv(TABLES / "Table2_program_state_evidence_hierarchy.tsv", evidence_rows, table2_fields)

primary_effects = [row for row in effects if row["family"] == "PRIMARY_8"]
if len(primary_effects) != 8:
    raise SystemExit(f"Expected 8 primary effect rows; found {len(primary_effects)}")
table3_fields = [
    "test_id",
    "arm",
    "program_id",
    "state_id",
    "family",
    "role",
    "status",
    "failure_reason",
    "n_complete_donors",
    "beta",
    "hc3_se",
    "ci95_lower",
    "ci95_upper",
    "wald_z",
    "raw_p",
    "bh_adjusted_p",
    "passes_family_bh_0_05",
    "direction",
    "multiplicity_note",
]
write_tsv(TABLES / "Table3_primary_donor_level_association_results.tsv", primary_effects, table3_fields)

table4_fields = list(sp02_annotations[0].keys())
write_tsv(TABLES / "Table4_biological_contextualization_summary.tsv", sp02_annotations, table4_fields)

write_tsv(
    TABLES / "SupplementaryTable1_cell_qc_characteristics.tsv",
    cell_qc,
    list(cell_qc[0].keys()),
)
write_tsv(
    TABLES / "SupplementaryTable2A_state_representation_summary.tsv",
    state_representation,
    list(state_representation[0].keys()),
)
write_tsv(
    TABLES / "SupplementaryTable2B_genetic_program_coverage_summary.tsv",
    program_coverage,
    list(program_coverage[0].keys()),
)
write_tsv(
    TABLES / "SupplementaryTable3_complete_donor_level_results.tsv",
    effects,
    list(effects[0].keys()),
)
write_tsv(
    TABLES / "SupplementaryTable4A_sensitivity_analysis_summary.tsv",
    sensitivity,
    list(sensitivity[0].keys()),
)
write_tsv(
    TABLES / "SupplementaryTable4B_exploratory_analysis_registry.tsv",
    exploratory,
    list(exploratory[0].keys()),
)


table_blueprint = [
    {
        "table_id": "T1",
        "table_title": "Study cohorts and analytical framework",
        "output_file": "tables/Table1_study_cohorts_and_analytical_framework.tsv",
        "row_granularity": "ONE_ROW_PER_FROZEN_ANALYSIS_ARM",
        "source_file": rel(P3B2 / "donor_feasibility_precheck.tsv"),
        "included_fields": ";".join(table1_fields),
        "row_filter": "NONE_ALL_M01_M02_M03",
        "order_rule": "M01;M02;M03",
        "claim_ids": "C001;C004;C008",
        "claim_ceiling": "DESIGN_AND_STRUCTURAL_FEASIBILITY_ONLY",
        "mandatory_limitation": "M02 n=5; M03 outside initial execution; represented cells are structural, not state-positive cells.",
    },
    {
        "table_id": "T2",
        "table_title": "Complete program-state evidence hierarchy",
        "output_file": "tables/Table2_program_state_evidence_hierarchy.tsv",
        "row_granularity": "ONE_ROW_PER_FROZEN_PROGRAM_STATE_MAPPING",
        "source_file": rel(P3B3 / "evidence_hierarchy_table.tsv"),
        "included_fields": ";".join(table2_fields),
        "row_filter": "NONE_ALL_21_MAPPINGS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C002;C003;P001-P021",
        "claim_ceiling": "COPY_FROZEN_EVIDENCE_CLASS_AND_INTERPRETATION_CEILING",
        "mandatory_limitation": "NOT_EVALUATED is not negative evidence; exploratory relationships remain non-confirmatory.",
    },
    {
        "table_id": "T3",
        "table_title": "Primary donor-level association results",
        "output_file": "tables/Table3_primary_donor_level_association_results.tsv",
        "row_granularity": "ONE_ROW_PER_PRIMARY_MODEL",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "included_fields": ";".join(table3_fields),
        "row_filter": "family=PRIMARY_8",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C002;C004;P001-P004",
        "claim_ceiling": "DONOR_LEVEL_EXPRESSION_SCORE_ASSOCIATION_ONLY",
        "mandatory_limitation": "M02 n=5; HC3; no PRS, causality, mechanism, or independent validation.",
    },
    {
        "table_id": "T4",
        "table_title": "SP02 biological contextualization summary",
        "output_file": "tables/Table4_biological_contextualization_summary.tsv",
        "row_granularity": "ONE_ROW_PER_FROZEN_MARKER_PLUS_AGGREGATE",
        "source_file": rel(P3B4 / "sp02_biological_annotation_summary.tsv"),
        "included_fields": ";".join(table4_fields),
        "row_filter": "SP02_ONLY_ALL_5_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C005;C006;C007",
        "claim_ceiling": "LEVEL_1_IDENTITY_PLUS_LEVEL_2_CONTEXT_ONLY",
        "mandatory_limitation": "Functions not measured in C1-R; source-proximal context is not independent validation.",
    },
    {
        "table_id": "ST1",
        "table_title": "Descriptive cell-level QC characteristics",
        "output_file": "tables/SupplementaryTable1_cell_qc_characteristics.tsv",
        "row_granularity": "ONE_ROW_PER_DATASET_SCOPE_AND_QC_METRIC",
        "source_file": rel(P3B2 / "cell_qc_characteristics.tsv"),
        "included_fields": ";".join(cell_qc[0].keys()),
        "row_filter": "NONE_ALL_FROZEN_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C001;C004",
        "claim_ceiling": "DESCRIPTIVE_QC_ONLY",
        "mandatory_limitation": "No filtering, state assignment, or inferential claim was based on these cell-level summaries.",
    },
    {
        "table_id": "ST2A",
        "table_title": "Frozen epithelial-state representation summary",
        "output_file": "tables/SupplementaryTable2A_state_representation_summary.tsv",
        "row_granularity": "ONE_ROW_PER_ARM_AND_STATE",
        "source_file": rel(P3B2 / "state_representation_summary.tsv"),
        "included_fields": ";".join(state_representation[0].keys()),
        "row_filter": "NONE_ALL_FROZEN_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C001;C008",
        "claim_ceiling": "STRUCTURAL_REPRESENTATION_ONLY",
        "mandatory_limitation": "Represented cells are structurally eligible and are not score-derived state-positive cells.",
    },
    {
        "table_id": "ST2B",
        "table_title": "Frozen genetic-program coverage summary",
        "output_file": "tables/SupplementaryTable2B_genetic_program_coverage_summary.tsv",
        "row_granularity": "ONE_ROW_PER_DATASET_AND_PROGRAM",
        "source_file": rel(P3B2 / "genetic_program_coverage_summary.tsv"),
        "included_fields": ";".join(program_coverage[0].keys()),
        "row_filter": "NONE_ALL_FROZEN_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C001",
        "claim_ceiling": "COVERAGE_AND_ESTIMABILITY_ONLY",
        "mandatory_limitation": "Coverage does not establish association or biological adequacy.",
    },
    {
        "table_id": "ST3",
        "table_title": "Complete donor-level model results",
        "output_file": "tables/SupplementaryTable3_complete_donor_level_results.tsv",
        "row_granularity": "ONE_ROW_PER_AUTHORIZED_MODEL",
        "source_file": rel(P3B3 / "donor_level_effect_summary.tsv"),
        "included_fields": ";".join(effects[0].keys()),
        "row_filter": "NONE_ALL_36_AUTHORIZED_MODELS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C002;C003;C004;P001-P021",
        "claim_ceiling": "PRIMARY_BOUNDED_OR_EXPLORATORY_NON_CONFIRMATORY_AS_FROZEN",
        "mandatory_limitation": "M03 and unauthorized sensitivities absent; exploratory families non-confirmatory.",
    },
    {
        "table_id": "ST4A",
        "table_title": "Unexecuted sensitivity-analysis boundary",
        "output_file": "tables/SupplementaryTable4A_sensitivity_analysis_summary.tsv",
        "row_granularity": "ONE_ROW_PER_PRESPECIFIED_SENSITIVITY",
        "source_file": rel(P3B3 / "sensitivity_analysis_summary.tsv"),
        "included_fields": ";".join(sensitivity[0].keys()),
        "row_filter": "NONE_ALL_FROZEN_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C008;H002",
        "claim_ceiling": "NOT_RUN_BOUNDARY_ONLY",
        "mandatory_limitation": "A not-run row is not evidence of robustness or failure.",
    },
    {
        "table_id": "ST4B",
        "table_title": "Biological contextualization execution registry",
        "output_file": "tables/SupplementaryTable4B_exploratory_analysis_registry.tsv",
        "row_granularity": "ONE_ROW_PER_CONTEXTUALIZATION_ACTION",
        "source_file": rel(P3B4 / "exploratory_analysis_registry.tsv"),
        "included_fields": ";".join(exploratory[0].keys()),
        "row_filter": "NONE_ALL_FROZEN_ROWS",
        "order_rule": "FROZEN_SOURCE_ORDER",
        "claim_ids": "C007;C008;H001;H003",
        "claim_ceiling": "EXPLORATORY_CONTEXT_AND_SCOPE_BOUNDARIES_ONLY",
        "mandatory_limitation": "The superseded first-pass ORA result must not be cited; no mechanism is established.",
    },
]
table_blueprint_fields = [
    "table_id",
    "table_title",
    "output_file",
    "row_granularity",
    "source_file",
    "included_fields",
    "row_filter",
    "order_rule",
    "claim_ids",
    "claim_ceiling",
    "mandatory_limitation",
]
write_tsv(OUT / "C1R_TABLE_BLUEPRINT.tsv", table_blueprint, table_blueprint_fields)


status_counts = Counter(str(row["claim_status"]) for row in claims)
package_counts = Counter(str(row["package_id"]) for row in claims)
direct_claims = [row for row in claims if row["evidence_level"] == "LEVEL_1_DIRECT"]

terminology_rows = [
    ("C1-R", "The governed study/workflow identifier; do not expand without author authority."),
    ("GP_IBD", "GP_IBD_GCST004131_V1, a frozen GWAS-linked expression-gene set score; not a PRS."),
    ("SP02 (INFLARE)", "Frozen four-gene epithelial state MUC6/BPIFB1/AQP5/PGC."),
    ("M01", "Primary discovery context, SCP259 broad-colon UC, 14 donors."),
    ("M02", "Primary bounded portability context, SCP1884 CD-colon inflamed, 5 donors."),
    ("M03", "Exploratory SCP1884 context outside the initial Phase 3B-3 execution; cannot rescue M02."),
    ("PORTABILITY_SUPPORTED", "Exact frozen Phase 3B-3 evidence class; not independent validation or causality."),
    ("Level 1/2/3", "Direct C1-R evidence / external context / future-validation hypothesis."),
]
term_table = "\n".join(f"| {term} | {definition} |" for term, definition in terminology_rows)

report = f"""# C1-R Phase 4A manuscript evidence package freeze report

Run ID: `{RUN_ID}`  
Executed: **{datetime.now().astimezone().isoformat(timespec='seconds')}**  
Prompt disposition: **MODIFY_THEN_EXECUTE**  
Mode: **manuscript evidence freeze only; no new scientific analysis**

## 1. Outcome

The Phase 3B-3 and Phase 3B-4 source packages were mechanically verified before manuscript-facing extraction. All {source_pre['phase3b3']['rows']} Phase 3B-3 manifest rows and all {source_pre['phase3b4']['rows']} Phase 3B-4 manifest rows passed presence, byte-size, and SHA-256 checks. No source object or frozen scientific classification was modified.

The evidence package contains {len(claims)} controlled claim records and the same number of traceability records. Claim statuses are: {dict(status_counts)}. The complete 21-pair landscape is preserved as {expected_counts}; `NOT_EVALUATED` remains outside the evidence denominator and is never treated as a negative result.

## 2. One-sentence manuscript argument

In predefined IBD-related epithelial contexts, C1-R shows that donor-level correspondence between frozen GWAS-linked expression programs and frozen epithelial-state scores is selective, with a negative GP_IBD-SP02 association classified `PORTABILITY_SUPPORTED` across M01 and the bounded five-donor M02 context, while causal, mechanistic, clinical, abundance, and independent-validation interpretations remain unsupported.

## 3. Terminology ledger

| Canonical term | Locked meaning |
|---|---|
{term_table}

## 4. Core findings package

- GP_IBD-SP02 is the central primary result. Its exact frozen values are M01 beta {fmt_num(primary_sp02['m01_beta'])}, BH-adjusted P {fmt_num(primary_sp02['m01_bh_adjusted_p'])}; M02 beta {fmt_num(primary_sp02['m02_beta'])}, BH-adjusted P {fmt_num(primary_sp02['m02_bh_adjusted_p'])}. Both directions are negative.
- The exact evidence label is `PORTABILITY_SUPPORTED` under the frozen donor-level expression-score contract.
- Table 3 retains all eight primary-family rows, not only the positive evidentiary result.
- Figure 2 and Table 2 retain the full 21-pair landscape to prevent positive-result selection.

## 5. Biological interpretation package

- SP02 remains the frozen four-gene INFLARE state: MUC6, BPIFB1, AQP5, and PGC.
- External human literature supports gastric/pyloric or Brunner-gland-neck-like metaplastic similarity in inflammatory intestinal disease.
- This literature is source-proximal and includes SCP1884, so it is `CONTEXT_ONLY`, not independent validation.
- The corrected exploratory ORA has one reportable term after BH across 13,362 eligible GO:BP/Reactome terms. It supports annotation coherence only and is not a pathway mechanism.

## 6. Negative evidence and boundary package

- Twelve mappings are `DIRECTIONALLY_CONSISTENT_INSUFFICIENT`, three are `DISCORDANT`, and three are `NOT_EVALUATED`.
- M02 contains exactly five donors and retains small-sample/HC3 and bounded-metadata limitations.
- M03, the frozen sensitivity analyses, state-frequency estimation, perturbational testing, and spatial causal testing were not run.
- Ten explicit claim forms are excluded from manuscript use, including genetic causality, disease-mechanism, biomarker, therapeutic-target, independent-validation, and experimental-confirmation claims.

## 7. Figure logic freeze

- **Figure 1:** frozen framework, cohort roles, donor-level aggregation, and explicit M03 boundary.
- **Figure 2:** all 21 program-state mappings and their exact evidence classes, with primary/exploratory separation.
- **Figure 3:** all eight primary-family donor-level estimates, with a focused GP_IBD-SP02 panel and M02 n=5 displayed.
- **Figure 4:** SP02 frozen identity and a Level 1/2/3 evidence ladder; no expression heatmap or mechanistic arrows.
- **Supplementary figures:** cohort/QC/representation, complete exploratory evidence, corrected ORA, and unexecuted-sensitivity registry.

No figure was rendered and no new analysis, threshold, statistic, or panel-generating transformation was performed.

## 8. Result table freeze

- `Table1_study_cohorts_and_analytical_framework.tsv`: 3 frozen arm rows.
- `Table2_program_state_evidence_hierarchy.tsv`: all 21 program-state mappings.
- `Table3_primary_donor_level_association_results.tsv`: all 8 primary-family model rows.
- `Table4_biological_contextualization_summary.tsv`: 4 frozen SP02 marker rows plus 1 aggregate context row.
- Supplementary Table 1: all descriptive cell-level QC rows.
- Supplementary Tables 2A-2B: complete frozen state representation and genetic-program coverage rows.
- Supplementary Table 3: all 36 authorized donor-level model rows, including exploratory and adverse evidence.
- Supplementary Tables 4A-4B: unexecuted sensitivity boundaries and the complete contextualization action registry.

These tables are manuscript-facing selections or copies of existing frozen outputs. They are not recomputed analyses.

## 9. Traceability and limitations

Every claim inventory row maps to its source analysis, source file and anchor, manuscript destination, and figure/table destination or explicit exclusion. The limitation register contains {len(limitations)} claim-specific boundaries, including all six items required by the reviewed Prompt.

The manuscript should use the shortest sufficient evidence chain: design and cohort boundary (Figure 1/Table 1), full landscape (Figure 2/Table 2), primary numeric evidence (Figure 3/Table 3), and bounded biological context (Figure 4/Table 4). Provenance detail, exploratory estimates, corrected ORA detail, and unexecuted sensitivities belong in Supplementary Information unless they materially change the central interpretation.

## 10. Prohibited-operation audit

- New scientific analysis: **0**
- Source or frozen-object modification: **0**
- Evidence-class changes: **0**
- New dataset access: **0**
- Figure rendering: **0**
- Manuscript prose drafting beyond the frozen argument and claim inventory: **0**
- Positive-result-only selection: **0**
- Limitation removal: **0**

## 11. Completion and hard stop

All required claims are traceable, evidence levels and claim statuses are separated, unsupported claims are excluded, negative evidence is retained, figure and table logic are frozen, limitations are preserved, and no new analysis was performed.

# C1R_PHASE4A_PASS_READY_FOR_FIGURE_DESIGN_AND_MANUSCRIPT_DRAFTING

This token closes Phase 4A only. `NEXT_PHASE_AUTOSTART = FORBIDDEN`. Figure design, figure production, manuscript drafting, submission preparation, portal activity, and any later phase require a new explicit instruction.
"""
write_text(OUT / "C1R_PHASE4A_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE_REPORT.md", report)


source_post = {
    "phase3b3": verify_manifest(P3B3, P3B3_MANIFEST),
    "phase3b4": verify_manifest(P3B4, P3B4_MANIFEST),
}
if any(item["status"] != "PASS" for item in source_post.values()):
    raise SystemExit("Source manifest verification failed after Phase 4A extraction")
if source_pre != source_post:
    raise SystemExit("Source manifest verification record changed during Phase 4A")

claim_ids = [str(row["claim_id"]) for row in claims]
trace_ids = [str(row["claim_id"]) for row in trace_rows]
qa_checks = {
    "source_manifests_pass": all(item["status"] == "PASS" for item in source_post.values()),
    "source_manifest_hashes_stable": all(
        source_pre[key]["manifest_sha256"] == source_post[key]["manifest_sha256"]
        for key in source_pre
    ),
    "claim_ids_unique": len(claim_ids) == len(set(claim_ids)),
    "claim_traceability_one_to_one": claim_ids == trace_ids,
    "claim_status_enum_valid": set(status_counts) <= {"SUPPORTED", "CONTEXT_ONLY", "HYPOTHESIS_ONLY", "NOT_ALLOWED"},
    "evidence_level_enum_valid": {str(row["evidence_level"]) for row in claims}
    <= {"LEVEL_1_DIRECT", "LEVEL_2_EXTERNAL_CONTEXT", "LEVEL_3_FUTURE_HYPOTHESIS", "PROHIBITED"},
    "evidence_landscape_21_rows": len(evidence_rows) == 21,
    "evidence_class_counts_exact": dict(evidence_counts) == expected_counts,
    "primary_sp02_frozen_class": primary_sp02["evidence_class"] == "PORTABILITY_SUPPORTED",
    "m02_donor_count_five": m02["donor_count"] == "5",
    "table1_rows_three": len(arms) == 3,
    "table2_rows_twenty_one": len(evidence_rows) == 21,
    "table3_rows_eight": len(primary_effects) == 8,
    "table4_rows_five": len(sp02_annotations) == 5,
    "figure_blueprint_rows_twelve": len(figure_rows) == 12,
    "table_blueprint_rows_ten": len(table_blueprint) == 10,
    "required_limitations_present": all(
        item in {row["limitation_id"] for row in limitations}
        for item in {"L001", "L002", "L003", "L004", "L005", "L006"}
    ),
}
if not all(qa_checks.values()):
    raise SystemExit("Phase 4A QA failed: " + json.dumps(qa_checks, ensure_ascii=False))

qa = {
    "schema_version": "C1R_PHASE4A_QA_V1.0",
    "run_id": RUN_ID,
    "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
    "prompt_review": "MODIFY_THEN_EXECUTE",
    "source_verification_pre": source_pre,
    "source_verification_post": source_post,
    "source_inputs": {
        "phase3b3_manifest_sha256": source_pre["phase3b3"]["manifest_sha256"],
        "phase3b4_manifest_sha256": source_pre["phase3b4"]["manifest_sha256"],
    },
    "counts": {
        "claim_inventory_rows": len(claims),
        "claim_status_counts": dict(status_counts),
        "package_counts": dict(package_counts),
        "level1_direct_claim_rows": len(direct_claims),
        "traceability_rows": len(trace_rows),
        "limitation_rows": len(limitations),
        "figure_blueprint_rows": len(figure_rows),
        "table_blueprint_rows": len(table_blueprint),
        "table_rows": {
            "T1": len(arms),
            "T2": len(evidence_rows),
            "T3": len(primary_effects),
            "T4": len(sp02_annotations),
            "ST1": len(cell_qc),
            "ST2A": len(state_representation),
            "ST2B": len(program_coverage),
            "ST3": len(effects),
            "ST4A": len(sensitivity),
            "ST4B": len(exploratory),
        },
        "evidence_class_counts": dict(evidence_counts),
        "frozen_literature_registry_rows": len(literature),
        "frozen_exploratory_registry_rows": len(exploratory),
        "frozen_state_context_rows": len(state_context),
    },
    "checks": qa_checks,
    "forbidden_operations": {
        "new_scientific_analysis": 0,
        "source_modifications": 0,
        "frozen_object_modifications": 0,
        "evidence_class_changes": 0,
        "new_dataset_access": 0,
        "new_literature_search": 0,
        "figure_rendering": 0,
        "manuscript_drafting_started": False,
        "next_phase_started": False,
    },
    "completion_state": "C1R_PHASE4A_PASS_READY_FOR_FIGURE_DESIGN_AND_MANUSCRIPT_DRAFTING",
    "next_phase_autostart": "FORBIDDEN",
}
write_text(LOGS / "C1R_PHASE4A_QA.json", json.dumps(qa, ensure_ascii=False, indent=2))


execution_log = f"""# C1-R Phase 4A execution log

- Run ID: `{RUN_ID}`
- Timestamp: `{datetime.now().astimezone().isoformat(timespec='seconds')}`
- Prompt review: `MODIFY_THEN_EXECUTE`
- Phase 3B-3 source manifest: {source_pre['phase3b3']['rows']}/{source_pre['phase3b3']['rows']} PASS; SHA-256 `{source_pre['phase3b3']['manifest_sha256']}`
- Phase 3B-4 source manifest: {source_pre['phase3b4']['rows']}/{source_pre['phase3b4']['rows']} PASS; SHA-256 `{source_pre['phase3b4']['manifest_sha256']}`
- Claim inventory rows: {len(claims)}
- Traceability rows: {len(trace_rows)}
- Limitation rows: {len(limitations)}
- Figure blueprint rows: {len(figure_rows)}
- Table blueprint rows: {len(table_blueprint)}
- Manuscript-facing table rows: T1={len(arms)}, T2={len(evidence_rows)}, T3={len(primary_effects)}, T4={len(sp02_annotations)}, ST1={len(cell_qc)}, ST2A={len(state_representation)}, ST2B={len(program_coverage)}, ST3={len(effects)}, ST4A={len(sensitivity)}, ST4B={len(exploratory)}
- New scientific analysis: 0
- Frozen source modifications: 0
- Completion: `C1R_PHASE4A_PASS_READY_FOR_FIGURE_DESIGN_AND_MANUSCRIPT_DRAFTING`
- `NEXT_PHASE_AUTOSTART = FORBIDDEN`
"""
write_text(LOGS / "PHASE4A_EXECUTION_LOG.md", execution_log)


manifest_path = OUT / "C1R_EVIDENCE_PACKAGE_MANIFEST.tsv"
manifest_rows = []
for path in sorted(item for item in OUT.rglob("*") if item.is_file() and item != manifest_path):
    manifest_rows.append(
        {
            "run_id": RUN_ID,
            "relative_path": path.relative_to(OUT).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "artifact_role": (
                "MANUSCRIPT_FACING_TABLE"
                if path.parent == TABLES
                else "EXECUTION_AND_QA"
                if path.parent == LOGS
                else "REQUIRED_PHASE4A_OUTPUT"
            ),
            "read_only_expected": "YES",
            "manifest_rule": "SELF_EXCLUDED_NON_SELF_HASHING",
        }
    )
manifest_fields = [
    "run_id",
    "relative_path",
    "size_bytes",
    "sha256",
    "artifact_role",
    "read_only_expected",
    "manifest_rule",
]
write_tsv(manifest_path, manifest_rows, manifest_fields)


for path in OUT.rglob("*"):
    if path.is_file():
        os.chmod(path, 0o444)

print(
    json.dumps(
        {
            "run_id": RUN_ID,
            "output_root": str(OUT),
            "source_manifest_rows": {"phase3b3": source_pre["phase3b3"]["rows"], "phase3b4": source_pre["phase3b4"]["rows"]},
            "claim_rows": len(claims),
            "trace_rows": len(trace_rows),
            "limitation_rows": len(limitations),
            "manifest_rows": len(manifest_rows),
            "completion_state": "C1R_PHASE4A_PASS_READY_FOR_FIGURE_DESIGN_AND_MANUSCRIPT_DRAFTING",
            "next_phase_autostart": "FORBIDDEN",
        },
        indent=2,
    )
)
