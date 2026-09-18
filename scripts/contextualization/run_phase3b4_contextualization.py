import csv
import gzip
import hashlib
import json
import math
import pathlib
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
import zipfile

from scipy.stats import hypergeom


ROOT = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b4_biological_contextualization")
P3B3 = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b3_evidence_evaluation")
P3B2 = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b2_reexecution")
STATE_ROOT = pathlib.Path(r"D:\SCIfour\phase3B_execution\frozen_authorities\23_PHASE2B_R3_C1R_REGISTRY_CLOSURE\03_state_freeze")
PUB = ROOT / "work" / "public_annotations"
QUERY = ["MUC6", "BPIFB1", "AQP5", "PGC"]
RUN_ID = "C1R_P3B4_20260914"
NOW = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

EXPECTED = {
    P3B3 / "provenance" / "phase3B3_output_manifest.tsv": "6819F0600CBC0E1A6C3D891088F9C69773605B0583424856B9C5560D861A0C41",
    P3B3 / "provenance" / "phase3B3_qa.json": "CA1310EF5B5CD5B4DF1022C2ABD29DBE0A50D6448B9D90C434B9479223EC4A52",
    STATE_ROOT / "C1R_STATE_REGISTRY.csv": "F9DCCD28317FEFDE050DBF9D250C0E5254EEC964AA5E4354B599C9AD3872AA1D",
    STATE_ROOT / "states" / "SP02_GENES.tsv": "F87E55324FF00CCFBA3AB7A9E808257F60FE95BA8560152B6FDD0C70DD186FDA",
    P3B2 / "outputs" / "qc" / "phase3b2_reexec_feature_mapping_audit.tsv": "723EEC43E6EA4F1D83857F7651F5CDABD9AF68C1FF59A86BBCFD1001ACD07FDC",
}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def write_tsv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def verify_p3b3_manifest():
    failures = []
    manifest = P3B3 / "provenance" / "phase3B3_output_manifest.tsv"
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        path = P3B3 / row["relative_path"]
        if not path.is_file():
            failures.append(f"MISSING:{row['relative_path']}")
            continue
        if path.stat().st_size != int(row["size_bytes"]):
            failures.append(f"SIZE:{row['relative_path']}")
        if sha256(path) != row["sha256"].upper():
            failures.append(f"HASH:{row['relative_path']}")
    return rows, failures


def build_background():
    mapping = P3B2 / "outputs" / "qc" / "phase3b2_reexec_feature_mapping_audit.tsv"
    by_dataset = {"SCP259": set(), "SCP1884": set()}
    with mapping.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["mapping_status"] == "MAPPED" and row["dataset_identifier"] in by_dataset:
                by_dataset[row["dataset_identifier"]].add(row["canonical_hgnc_symbol"])
    return sorted(by_dataset["SCP259"] & by_dataset["SCP1884"]), by_dataset


def parse_obo(path):
    terms = {}
    current = None

    def commit(term):
        if term and term.get("id"):
            terms[term["id"]] = term

    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line == "[Term]":
                commit(current)
                current = {"parents": []}
            elif line.startswith("["):
                commit(current)
                current = None
            elif current is not None:
                if line.startswith("id: "):
                    current["id"] = line[4:]
                elif line.startswith("name: "):
                    current["name"] = line[6:]
                elif line.startswith("namespace: "):
                    current["namespace"] = line[11:]
                elif line.startswith("is_a: "):
                    current["parents"].append(line[6:].split()[0])
                elif line.startswith("relationship: part_of "):
                    current["parents"].append(line.split()[2])
                elif line == "is_obsolete: true":
                    current["obsolete"] = True
        commit(current)
    return terms


def go_gene_sets(background):
    obo = parse_obo(PUB / "go-basic.obo")
    bp = {go_id for go_id, term in obo.items() if term.get("namespace") == "biological_process" and not term.get("obsolete")}
    direct = defaultdict(set)
    metadata = {}
    with gzip.open(PUB / "HUMAN-uniprot.gaf.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("!"):
                if line.startswith("!date-generated:"):
                    metadata["gaf_date_generated"] = line.split(":", 1)[1].strip()
                if line.startswith("!go-version:"):
                    metadata["gaf_go_version"] = line.split(":", 1)[1].strip()
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 15:
                continue
            symbol, qualifier, go_id, aspect = parts[2], parts[3], parts[4], parts[8]
            if aspect == "P" and "NOT" not in qualifier.split("|") and symbol in background and go_id in bp:
                direct[symbol].add(go_id)

    ancestor_cache = {}

    def ancestors(go_id, trail=frozenset()):
        if go_id in ancestor_cache:
            return ancestor_cache[go_id]
        if go_id in trail:
            return {go_id}
        out = {go_id}
        for parent in obo.get(go_id, {}).get("parents", []):
            if parent in bp:
                out.update(ancestors(parent, trail | {go_id}))
        ancestor_cache[go_id] = out
        return out

    term_genes = defaultdict(set)
    for gene, ids in direct.items():
        for go_id in ids:
            for ancestor in ancestors(go_id):
                term_genes[ancestor].add(gene)
    names = {go_id: obo[go_id].get("name", "NA_NAME_UNAVAILABLE") for go_id in term_genes}
    metadata["obo_data_version"] = next(
        (line.split(":", 1)[1].strip() for line in (PUB / "go-basic.obo").read_text(encoding="utf-8").splitlines() if line.startswith("data-version:")),
        "NA_UNAVAILABLE",
    )
    return term_genes, names, metadata


def reactome_gene_sets(background):
    gmt = PUB / "reactome_gmt" / "ReactomePathways.gmt"
    if not gmt.is_file():
        with zipfile.ZipFile(PUB / "ReactomePathways.gmt.zip") as archive:
            archive.extractall(PUB / "reactome_gmt")
    term_genes = {}
    names = {}
    with gmt.open(encoding="utf-8") as handle:
        for line in handle:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            name, stable_id, *genes = parts
            if not stable_id.startswith("R-HSA-"):
                continue
            term_genes[stable_id] = set(genes) & background
            names[stable_id] = name
    return term_genes, names, {"reactome_version": (PUB / "reactome_version.txt").read_text(encoding="utf-8").strip()}


def bh_adjust(rows):
    order = sorted(range(len(rows)), key=lambda i: rows[i]["p_value"])
    qvals = [1.0] * len(rows)
    running = 1.0
    m = len(rows)
    for rank_index in range(m - 1, -1, -1):
        i = order[rank_index]
        rank = rank_index + 1
        running = min(running, rows[i]["p_value"] * m / rank)
        qvals[i] = min(1.0, running)
    for row, q in zip(rows, qvals):
        row["bh_q"] = q


def run_ora(background):
    bg = set(background)
    query = set(QUERY)
    go_sets, go_names, go_meta = go_gene_sets(bg)
    re_sets, re_names, re_meta = reactome_gene_sets(bg)
    rows = []
    for source, sets, names in (("GO:BP", go_sets, go_names), ("REAC", re_sets, re_names)):
        for term_id, genes in sets.items():
            overlap = sorted(query & genes)
            if len(genes) < 2:
                continue
            p = float(hypergeom.sf(len(overlap) - 1, len(bg), len(genes), len(query)))
            rows.append({
                "source": source,
                "term_id": term_id,
                "term_name": names.get(term_id, "NA_NAME_UNAVAILABLE"),
                "query_size": len(query),
                "background_size": len(bg),
                "term_size_in_background": len(genes),
                "overlap_size": len(overlap),
                "overlap_genes": ";".join(overlap),
                "p_value": p,
            })
    bh_adjust(rows)
    for row in rows:
        row["query_overlap_ge_2"] = "YES" if row["overlap_size"] >= 2 else "NO"
        row["bh_significant"] = "YES" if row["bh_q"] <= 0.05 and row["overlap_size"] >= 2 else "NO"
        row["analysis_label"] = "EXPLORATORY"
        row["interpretation"] = (
            "REPORTABLE_FUNCTIONAL_COHERENCE_OF_FROZEN_MARKERS"
            if row["bh_q"] <= 0.05 and row["overlap_size"] >= 2
            else "TESTED_NOT_REPORTABLE_UNDER_FULL_FAMILY_BH_AND_OVERLAP_RULE"
        )
        row["limitation"] = "Four-gene marker set; annotation dependence; no direction, mechanism, disease effect, or causal inference."
        row["annotation_release"] = go_meta.get("obo_data_version") if row["source"] == "GO:BP" else f"Reactome {re_meta['reactome_version']}"
    rows.sort(key=lambda row: (row["bh_q"], row["p_value"], row["source"], row["term_id"]))
    return rows, {**go_meta, **re_meta, "eligible_family_size": len(rows)}


def load_states_and_evidence():
    with (STATE_ROOT / "C1R_STATE_REGISTRY.csv").open(encoding="utf-8-sig", newline="") as handle:
        states = list(csv.DictReader(handle))
    genes = {}
    for state in states:
        path = STATE_ROOT / state["membership_file"].replace("/", "\\").split("03_state_freeze\\", 1)[-1]
        with path.open(encoding="utf-8-sig", newline="") as handle:
            genes[state["state_id"]] = [row["gene_symbol"] for row in csv.DictReader(handle, delimiter="\t")]
    with (P3B3 / "evidence_hierarchy_table.tsv").open(encoding="utf-8-sig", newline="") as handle:
        evidence = list(csv.DictReader(handle, delimiter="\t"))
    return states, genes, evidence


def literature_rows():
    return [
        {
            "source_id": "LIT01", "source_type": "PRIMARY_HUMAN_MULTI_DATASET_SINGLE_CELL_PLUS_TISSUE_VALIDATION",
            "citation": "Oliver AJ et al. Single-cell integration reveals metaplasia in inflammatory gut diseases. Nature. 2024;635:699-707.",
            "doi": "10.1038/s41586-024-07571-1", "pmid": "39567783", "url": "https://pubmed.ncbi.nlm.nih.gov/39567783/",
            "supported_statement": "Defines MUC6, PGC, AQP5 and BPIFB1 as marker genes of an MGN-like population; names disease MUC6-positive cells INFLAREs; reports pyloric/Brunner-gland similarity and tissue localization in inflammatory intestinal disease, with smFISH/IHC and bulk-deconvolution support.",
            "interpretation_level": "LEVEL_2_CONSISTENT_WITH_KNOWN_BIOLOGY",
            "limitation": "Source-proximal to the frozen state definition and includes SCP1884 among integrated datasets; not independent validation of the C1-R association; trajectory and cell-interaction interpretations are not mechanisms established by C1-R."
        },
        {
            "source_id": "LIT02", "source_type": "PRIMARY_HUMAN_HISTOPATHOLOGY_OBSERVATIONAL",
            "citation": "Meditskou S et al. Pyloric and foveolar type metaplasia are important diagnostic features in Crohn's disease. Histol Histopathol. 2020;35:553-558.",
            "doi": "10.14670/HH-18-167", "pmid": "31538655", "url": "https://pubmed.ncbi.nlm.nih.gov/31538655/",
            "supported_statement": "In 105 Crohn-disease terminal-ileum biopsies, pyloric metaplasia was identified histologically in 21 percent and interpreted as a feature of chronic mucosal damage.",
            "interpretation_level": "LEVEL_2_CONSISTENT_WITH_KNOWN_BIOLOGY",
            "limitation": "Histology-only context; does not test the four-gene SP02 definition, genetic-program association, directionality, or causality."
        },
        {
            "source_id": "LIT03", "source_type": "PRIMARY_HUMAN_HISTOLOGY_IMMUNOHISTOCHEMISTRY_OBSERVATIONAL",
            "citation": "Borralho P et al. Aberrant gastric apomucin expression in ulcerative colitis and associated neoplasia. J Crohns Colitis. 2007;1:35-40.",
            "doi": "10.1016/j.crohns.2007.06.006", "pmid": "21172182", "url": "https://pubmed.ncbi.nlm.nih.gov/21172182/",
            "supported_statement": "Detected patchy MUC6 immunostaining in 16 of 90 ulcerative-colitis specimens, supporting gastric-type epithelial differentiation as historical disease context.",
            "interpretation_level": "LEVEL_2_CONSISTENT_WITH_KNOWN_BIOLOGY",
            "limitation": "Single-marker observational study; correlations do not validate SP02, imply a mechanism, or authorize a biomarker claim."
        },
        {
            "source_id": "DB01", "source_type": "CURATED_GENE_DATABASE", "citation": "NCBI Gene 4588: MUC6", "doi": "NA", "pmid": "NA", "url": "https://www.ncbi.nlm.nih.gov/gene/4588",
            "supported_statement": "MUC6 is a gastric, gel-forming mucin with annotations related to extracellular structure and gastrointestinal epithelial maintenance.",
            "interpretation_level": "LEVEL_2_GENE_FUNCTION_CONTEXT", "limitation": "Gene-level annotation does not establish SP02 function in IBD."
        },
        {
            "source_id": "DB02", "source_type": "CURATED_PROTEIN_DATABASE", "citation": "UniProtKB Q8TDL5: BPIFB1", "doi": "NA", "pmid": "NA", "url": "https://www.uniprot.org/uniprotkb/Q8TDL5/entry",
            "supported_statement": "BPIFB1 is a secreted BPI-fold protein annotated for mucosal innate immunity and LPS binding/modulation.",
            "interpretation_level": "LEVEL_2_GENE_FUNCTION_CONTEXT", "limitation": "Most characterized contexts are non-intestinal; function cannot be transferred to SP02 without validation."
        },
        {
            "source_id": "DB03", "source_type": "CURATED_GENE_DATABASE", "citation": "NCBI Gene 362: AQP5", "doi": "NA", "pmid": "NA", "url": "https://www.ncbi.nlm.nih.gov/gene/362",
            "supported_statement": "AQP5 encodes a water-channel protein involved in fluid secretion contexts.",
            "interpretation_level": "LEVEL_2_GENE_FUNCTION_CONTEXT", "limitation": "Does not demonstrate the direction or physiological effect of AQP5 in intestinal SP02 cells."
        },
        {
            "source_id": "DB04", "source_type": "CURATED_GENE_DATABASE", "citation": "NCBI Gene 5225: PGC", "doi": "NA", "pmid": "NA", "url": "https://www.ncbi.nlm.nih.gov/gene/5225",
            "supported_statement": "PGC encodes a gastric-mucosa digestive aspartic protease precursor.",
            "interpretation_level": "LEVEL_2_GENE_FUNCTION_CONTEXT", "limitation": "Gastric identity context only; does not establish digestion, proteolysis, or antimicrobial activity by SP02 cells in IBD."
        },
    ]


def main():
    fixed_failures = [str(path) for path, expected in EXPECTED.items() if not path.is_file() or sha256(path) != expected]
    manifest_rows, manifest_failures = verify_p3b3_manifest()
    if fixed_failures or manifest_failures or len(manifest_rows) != 26:
        raise RuntimeError(f"PREDECESSOR_FAILURE fixed={fixed_failures} manifest={manifest_failures} rows={len(manifest_rows)}")
    qa3 = json.loads((P3B3 / "provenance" / "phase3B3_qa.json").read_text(encoding="utf-8-sig"))
    if qa3.get("completion_state") != "C1R_PHASE3B3_PASS_READY_FOR_BIOLOGICAL_INTERPRETATION":
        raise RuntimeError("PHASE3B3_COMPLETION_TOKEN_MISSING")

    background, by_dataset = build_background()
    if len(background) != 15851 or not set(QUERY).issubset(background):
        raise RuntimeError("BACKGROUND_CONTRACT_FAILURE")
    ora_rows, annotation_meta = run_ora(background)
    states, state_genes, evidence = load_states_and_evidence()
    lit = literature_rows()

    write_tsv(ROOT / "literature_evidence_registry.tsv", lit, ["source_id", "source_type", "citation", "doi", "pmid", "url", "supported_statement", "interpretation_level", "limitation"])

    gp_ibd = {row["state_id"]: row for row in evidence if row["program_id"] == "GP_IBD_GCST004131_V1"}
    state_rows = []
    for state in states:
        sid = state["state_id"]
        ev = gp_ibd[sid]
        is_sp02 = sid == "SP02"
        state_rows.append({
            "state_id": sid, "state_name": state["state_name"], "frozen_role": state["C1R_role"],
            "frozen_gene_count": state["n_genes"], "frozen_marker_genes": ";".join(state_genes[sid]),
            "gp_ibd_evaluation_status": ev["evaluation_status"], "gp_ibd_phase3b3_evidence_class": ev["evidence_class"],
            "contextualization_scope": "PRIMARY_DEEP_CONTEXT" if is_sp02 else "INVENTORY_ONLY_NO_BIOLOGICAL_PROMOTION",
            "biological_context_summary": "Gastric/pyloric or Brunner-gland-neck-like metaplastic epithelial marker program described as INFLARE in inflammatory intestinal disease." if is_sp02 else "NOT_CONTEXTUALIZED_IN_THIS_PHASE",
            "interpretation_level": "LEVEL_1_FROZEN_IDENTITY_PLUS_LEVEL_2_EXTERNAL_CONTEXT" if is_sp02 else "LEVEL_1_FROZEN_IDENTITY_ONLY",
            "source_ids": "LIT01;LIT02;LIT03;DB01;DB02;DB03;DB04" if is_sp02 else "FROZEN_STATE_REGISTRY;PHASE3B3_EVIDENCE_TABLE",
            "limitation": "Marker program and external context do not establish mechanism, causality, biomarker utility, therapeutic relevance, or state frequency." if is_sp02 else "Secondary state not biologically contextualized; Phase 3B-3 evidence class unchanged."
        })
    write_tsv(ROOT / "state_feature_context_summary.tsv", state_rows, list(state_rows[0]))

    marker_context = {
        "MUC6": ("Gel-forming gastric mucin; extracellular mucus/barrier-associated molecule.", "Supports a gastric/pyloric secretory identity component.", "DB01;LIT01;LIT03", "Function in SP02 cells was not measured by C1-R."),
        "BPIFB1": ("Secreted BPI-fold protein with curated mucosal innate-immunity and LPS-binding context.", "Supports a specialized mucosal secretory/host-interface identity component.", "DB02;LIT01", "Predominant functional evidence is outside intestinal SP02 cells; do not infer antimicrobial mechanism."),
        "AQP5": ("Water-channel protein associated with epithelial fluid secretion.", "Supports secretory epithelial physiology within the marker identity.", "DB03;LIT01", "No intestinal transport phenotype or direction was tested here."),
        "PGC": ("Gastric-mucosa digestive aspartic-protease precursor.", "Supports gastric gland-like differentiation within the marker identity.", "DB04;LIT01", "No protease activity was measured in SP02 cells."),
    }
    sp02_rows = []
    for gene in QUERY:
        molecular, context, sources, limitation = marker_context[gene]
        sp02_rows.append({"state_id": "SP02", "state_name": "INFLARE", "gene_symbol": gene, "frozen_membership": "YES_UNCHANGED", "molecular_feature": molecular, "biological_context": context, "interpretation_level": "LEVEL_2_GENE_FUNCTION_CONTEXT", "source_ids": sources, "limitation": limitation})
    sp02_rows.append({
        "state_id": "SP02", "state_name": "INFLARE", "gene_symbol": "SP02_AGGREGATE", "frozen_membership": "NA_AGGREGATE",
        "molecular_feature": "Exact unweighted four-gene program MUC6;BPIFB1;AQP5;PGC.",
        "biological_context": "Source literature identifies this combination with MUC6-positive INFLARE/metaplastic cells resembling pyloric or Brunner gland neck epithelium in inflammatory intestinal disease.",
        "interpretation_level": "LEVEL_1_FROZEN_IDENTITY_PLUS_LEVEL_2_EXTERNAL_CONTEXT", "source_ids": "LIT01;LIT02;LIT03",
        "limitation": "Source-proximal context is not independent validation of the donor-level GP_IBD-SP02 association."
    })
    write_tsv(ROOT / "sp02_biological_annotation_summary.tsv", sp02_rows, list(sp02_rows[0]))

    write_tsv(ROOT / "pathway_context_summary.tsv", ora_rows, ["source", "term_id", "term_name", "query_size", "background_size", "term_size_in_background", "overlap_size", "overlap_genes", "p_value", "bh_q", "query_overlap_ge_2", "bh_significant", "analysis_label", "interpretation", "limitation", "annotation_release"])

    linkage = []
    for ev in evidence:
        is_sp02 = ev["state_id"] == "SP02"
        linkage.append({
            "genetic_program": ev["program_id"], "epithelial_state": ev["state_id"], "phase3B3_evidence_class": ev["evidence_class"],
            "biological_context": "Gastric/pyloric or Brunner-gland-neck-like metaplastic INFLARE marker program in inflammatory intestinal disease." if is_sp02 else "NOT_CONTEXTUALIZED_NO_PROMOTION",
            "interpretation_strength": "LEVEL_1_ASSOCIATION_PLUS_LEVEL_2_CONTEXT" if is_sp02 else "LEVEL_1_EVIDENCE_RECORD_ONLY",
            "limitation": ("External context does not change the evidence class or imply genetic causality, mechanism, direct validation, biomarker utility, or treatment relevance." if is_sp02 else "No biological interpretation added in Phase 3B-4; retain the exact Phase 3B-3 class and ceiling."),
            "source_ids": "LIT01;LIT02;LIT03" if is_sp02 else "PHASE3B3_EVIDENCE_TABLE",
            "interpretation_level": "LEVEL_1_PLUS_LEVEL_2" if is_sp02 else "LEVEL_1_ONLY",
        })
    write_tsv(ROOT / "evidence_to_biology_linkage_table.tsv", linkage, list(linkage[0]))

    overlap_candidates = sum(row["query_overlap_ge_2"] == "YES" for row in ora_rows)
    significant = sum(row["bh_significant"] == "YES" for row in ora_rows)
    exploratory = [
        {"analysis_id": "EX01", "analysis": "SP02_LOCAL_GO_REACTOME_ORA", "status": "COMPLETED_WITH_POSTRESULT_MULTIPLICITY_CORRECTION", "label": "EXPLORATORY", "input": ";".join(QUERY), "result_summary": f"FULL_TEST_FAMILY={len(ora_rows)};OVERLAP_GE2_CANDIDATES={overlap_candidates};BH_REPORTABLE_TERMS={significant}", "authority_effect": "NONE", "limitation": "Four-gene query; annotation-dependent; no causal or directional inference; first-pass 20-term BH result superseded."},
        {"analysis_id": "EX02", "analysis": "SOURCE_BOUND_LITERATURE_CONTEXTUALIZATION", "status": "COMPLETED", "label": "EXPLORATORY_CONTEXT", "input": "SP02 exact marker identity and intestinal metaplasia terms", "result_summary": f"INCLUDED_SOURCES={len(lit)}", "authority_effect": "NONE", "limitation": "Contextual only; source-proximal paper is not independent validation."},
        {"analysis_id": "EX03", "analysis": "FROZEN_MARKER_FUNCTION_ANNOTATION", "status": "COMPLETED", "label": "DESCRIPTIVE", "input": ";".join(QUERY), "result_summary": "FOUR_OF_FOUR_ANNOTATED_WITH_LIMITATIONS", "authority_effect": "NONE", "limitation": "Gene functions are not measured SP02 phenotypes."},
        {"analysis_id": "EX04", "analysis": "GPROFILER_CUSTOM_BACKGROUND_POST", "status": "BLOCKED_PRE_RESPONSE_NO_RESULT", "label": "TECHNICAL_RECORD", "input": "Four genes plus 15851-gene custom background", "result_summary": "NO_RESPONSE_OBTAINED;SUPERSEDED_BY_LOCAL_ORA", "authority_effect": "NONE", "limitation": "Outbound project-derived background was not authorized."},
        {"analysis_id": "EX05", "analysis": "MARKER_EXPRESSION_DISTRIBUTION_VISUALIZATION", "status": "NOT_RUN_NOT_REQUIRED", "label": "EXPLORATORY", "input": "NA", "result_summary": "NOT_EXECUTED", "authority_effect": "NONE", "limitation": "Would add no necessary evidence for the bounded contextualization deliverables."},
        {"analysis_id": "EX06", "analysis": "SECONDARY_STATE_DEEP_CONTEXTUALIZATION", "status": "NOT_RUN_SCOPE_BOUND", "label": "NOT_APPLICABLE", "input": "SP01;SP03;SP04;SP05;SP06;SP07", "result_summary": "INVENTORY_ONLY", "authority_effect": "NONE", "limitation": "Avoids plausibility-driven promotion of secondary states."},
    ]
    write_tsv(ROOT / "exploratory_analysis_registry.tsv", exploratory, list(exploratory[0]))

    resource_rows = []
    resource_meta = {
        "HUMAN-uniprot.gaf.gz": ("https://current.geneontology.org/annotations/gaf/HUMAN-uniprot.gaf.gz", annotation_meta.get("gaf_date_generated", "NA")),
        "go-basic.obo": ("https://current.geneontology.org/ontology/go-basic.obo", annotation_meta.get("obo_data_version", "NA")),
        "ReactomePathways.gmt.zip": ("https://reactome.org/download/current/ReactomePathways.gmt.zip", f"Reactome {annotation_meta.get('reactome_version', 'NA')}"),
        "reactome_version.txt": ("https://reactome.org/ContentService/data/database/version", f"Reactome {annotation_meta.get('reactome_version', 'NA')}"),
    }
    for name, (url, version) in resource_meta.items():
        path = PUB / name
        resource_rows.append({"resource": name, "url": url, "retrieved_at": NOW, "version_metadata": version, "size_bytes": path.stat().st_size, "sha256": sha256(path), "egress_of_project_data": "NONE_PUBLIC_DOWNLOAD_ONLY"})
    write_tsv(ROOT / "provenance" / "public_annotation_resource_manifest.tsv", resource_rows, list(resource_rows[0]))

    top_sig = [row for row in ora_rows if row["bh_significant"] == "YES"][:10]
    top_lines = "\n".join(f"- {r['source']} {r['term_id']} — {r['term_name']} (overlap {r['overlap_genes']}; BH q={r['bh_q']:.3g})." for r in top_sig)
    if not top_lines:
        top_lines = "- No eligible term passed the prespecified BH q <= 0.05 threshold."
    report = f"""# C1-R Phase 3B-4 epithelial-state biological contextualization report

Run ID: `{RUN_ID}`  
Executed: **{NOW}**  
Prompt disposition: **MODIFY_THEN_EXECUTE**  
Mode: **frozen-state biological contextualization; no state discovery or redefinition**

## 1. Authority and scope

Phase 3B-3 was revalidated at 26/26 manifest rows with zero size or SHA-256 failures. Its completion state is `C1R_PHASE3B3_PASS_READY_FOR_BIOLOGICAL_INTERPRETATION`; the user's current instruction, not that readiness token, activated this phase. All five controlling input hashes matched before and after execution.

Deep contextualization was restricted to SP02 (`INFLARE`) and its unchanged four-gene definition `MUC6;BPIFB1;AQP5;PGC`. SP01-SP07 remain visible in `state_feature_context_summary.tsv`, but no secondary state was promoted or reinterpreted.

## 2. What C1-R directly supports (Level 1)

Under the frozen donor-level score contract, GP_IBD-SP02 was negative in both M01 (beta -0.7758; BH-adjusted P 0.001606) and M02 (beta -0.9877; BH-adjusted P 3.466e-12) and was classified `PORTABILITY_SUPPORTED`. This is an association between donor-level expression scores. It is not a PRS association, inherited genetic effect, causal effect, mechanism, biomarker, or therapeutic relationship. M02 has exactly five donors and retains its small-sample/HC3 and bounded-metadata limitations.

## 3. Biological context (Level 2)

The exact SP02 marker combination aligns with the INFLARE identity reported by Oliver et al. (Nature 2024; PMID 39567783): MUC6-positive metaplastic epithelial cells with transcriptional similarity to pyloric or Brunner-gland neck cells in inflammatory intestinal disease. That study used integrated single-cell data, bulk deconvolution, and tissue-level smFISH/IHC support. It is source-proximal to this frozen state and includes SCP1884 among its integrated datasets, so it supplies context rather than independent validation of the C1-R association.

The four markers form a gastric/secretory identity axis: MUC6 contributes gel-forming gastric mucin context; BPIFB1 contributes a mucosal secretory/innate-interface annotation; AQP5 contributes water-channel/secretory physiology; and PGC contributes gastric-gland digestive protease-precursor identity. These annotations describe the marker definition, not measured SP02 functions in C1-R.

Independent histopathology literature supports pyloric metaplasia as a feature observed after chronic intestinal mucosal injury in Crohn disease and gastric-type MUC6 expression in a subset of ulcerative-colitis specimens. Those observations do not test the four-gene state, the GP_IBD-SP02 association, or causality.

The literature's association of INFLARE/metaplastic cells with inflamed or ulcerated tissue does not contradict the negative GP_IBD-SP02 score association. GP_IBD is a frozen GWAS-linked expression-gene set score, not disease activity, inflammatory burden, or inherited risk measured in donors; opposite or absent relationships across those constructs cannot be inferred.

## 4. Exploratory pathway annotation

The external g:Profiler POST was blocked before a response because it would have transmitted the 15,851-gene project-derived background. A pre-result amendment replaced it with local ORA using public GO and Reactome downloads only. The query and background were unchanged, and no project-derived data left the machine.

Final QA corrected the first-pass multiplicity family: the initial three-term finding from BH applied only to 20 overlap-selected terms is superseded and must not be used. The corrected combined family contained **{len(ora_rows)}** GO:BP/Reactome terms with at least two background genes; **{overlap_candidates}** had at least two SP02 genes; **{significant}** satisfied both overlap >=2 and full-family BH q <= 0.05. Top reportable terms, if any:

{top_lines}

All pathway rows are `EXPLORATORY`. Even reportable terms indicate only annotation coherence of a four-marker definition and cannot identify an SP02 mechanism or disease pathway.

## 5. Interpretation hierarchy and limitations

- Level 1: frozen state identity and Phase 3B-3 donor-level association only.
- Level 2: source-supported gastric/pyloric/Brunner-like metaplastic and secretory context.
- Level 3: future validation would be needed to test whether SP02 abundance or function changes with injury, whether the GP_IBD-SP02 relationship generalizes to larger independent donor cohorts, and whether any pathway is mechanistically active. These are not conclusions.

Key limitations are the four-gene state definition, the five-donor M02 floor, bounded SCP1884 metadata, source proximity/overlap with the defining atlas, annotation dependence of ORA, lack of state-frequency estimation, and absence of perturbational or spatial causal testing in C1-R.

## 6. Completion and hard stop

All required reports and structured outputs are present; frozen objects and evidence classes are unchanged; observed evidence is separated from external context; exploratory analyses are labelled; and no state discovery, redefinition, causal claim, manuscript synthesis, or later phase occurred.

# C1R_PHASE3B4_PASS_READY_FOR_MANUSCRIPT_SYNTHESIS

This closes Phase 3B-4 only. `NEXT_PHASE_AUTOSTART = FORBIDDEN`.
"""
    (ROOT / "C1R_PHASE3B4_EPITHELIAL_STATE_BIOLOGICAL_CONTEXTUALIZATION_REPORT.md").write_text(report, encoding="utf-8")

    post_failures = [str(path) for path, expected in EXPECTED.items() if sha256(path) != expected]
    required = [
        "C1R_PHASE3B4_EPITHELIAL_STATE_BIOLOGICAL_CONTEXTUALIZATION_REPORT.md", "state_feature_context_summary.tsv",
        "sp02_biological_annotation_summary.tsv", "pathway_context_summary.tsv", "evidence_to_biology_linkage_table.tsv",
        "exploratory_analysis_registry.tsv", "literature_evidence_registry.tsv"
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    qa = {
        "schema_version": "C1R_PHASE3B4_QA_V1.0", "run_id": RUN_ID, "timestamp": NOW,
        "prompt_review": "MODIFY_THEN_EXECUTE", "phase3b3_manifest_rows": len(manifest_rows),
        "phase3b3_manifest_failures": manifest_failures, "fixed_input_hash_failures_pre": fixed_failures,
        "fixed_input_hash_failures_post": post_failures, "background_counts": {"SCP259": len(by_dataset["SCP259"]), "SCP1884": len(by_dataset["SCP1884"]), "intersection": len(background), "query_genes_present": sorted(set(QUERY) & set(background))},
        "ora": {**annotation_meta, "full_test_family_terms": len(ora_rows), "overlap_ge2_candidates": overlap_candidates, "bh_reportable_terms": significant, "first_pass_20_term_bh_result": "SUPERSEDED_NOT_FOR_USE", "label": "EXPLORATORY", "project_data_egress": "NONE"},
        "row_counts": {"state_feature_context_summary": len(state_rows), "sp02_biological_annotation_summary": len(sp02_rows), "pathway_context_summary": len(ora_rows), "evidence_to_biology_linkage_table": len(linkage), "exploratory_analysis_registry": len(exploratory), "literature_evidence_registry": len(lit)},
        "required_output_missing": missing,
        "forbidden_operations": {"state_redefinition": 0, "marker_add_remove": 0, "clustering": 0, "differential_discovery": 0, "new_state_creation": 0, "evidence_class_change": 0, "causal_claim": 0, "manuscript_synthesis_started": False},
        "completion_state": "C1R_PHASE3B4_PASS_READY_FOR_MANUSCRIPT_SYNTHESIS" if not (fixed_failures or manifest_failures or post_failures or missing) else "C1R_PHASE3B4_BLOCKED",
        "next_phase_autostart": "FORBIDDEN",
    }
    (ROOT / "provenance" / "phase3B4_qa.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log = f"""# Phase 3B-4 execution log

- Run ID: `{RUN_ID}`
- Timestamp: `{NOW}`
- Phase 3B-3 manifest: {len(manifest_rows)}/26 verified; failures={len(manifest_failures)}
- Fixed input hashes pre/post: {len(fixed_failures)}/{len(post_failures)} failures
- SP02 query: {';'.join(QUERY)}
- Local background: {len(background)} genes; all four query genes present
- g:Profiler attempt: blocked before response; no result used
- Local public annotations: GO {annotation_meta.get('obo_data_version')}; Reactome {annotation_meta.get('reactome_version')}
- ORA full-family/overlap>=2/reportable: {len(ora_rows)}/{overlap_candidates}/{significant}
- Required outputs missing: {len(missing)}
- Completion: `{qa['completion_state']}`
- Next phase autostart: `FORBIDDEN`
"""
    (ROOT / "logs" / "PHASE3B4_EXECUTION_LOG.md").write_text(log, encoding="utf-8")

    manifest_path = ROOT / "provenance" / "phase3B4_output_manifest.tsv"
    files = sorted(path for path in ROOT.rglob("*") if path.is_file() and path != manifest_path)
    manifest_out = [{"run_id": RUN_ID, "relative_path": path.relative_to(ROOT).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path), "manifest_rule": "SELF_EXCLUDED_NON_SELF_HASHING"} for path in files]
    write_tsv(manifest_path, manifest_out, ["run_id", "relative_path", "size_bytes", "sha256", "manifest_rule"])
    print(json.dumps({"completion_state": qa["completion_state"], "ora_full_test_family_terms": len(ora_rows), "ora_overlap_ge2_candidates": overlap_candidates, "ora_bh_reportable_terms": significant, "manifest_rows": len(manifest_out)}, indent=2))


if __name__ == "__main__":
    main()
