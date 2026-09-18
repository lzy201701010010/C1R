import csv
import hashlib
import json
import pathlib
import urllib.error
import urllib.request


ROOT = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b4_biological_contextualization")
P3B3 = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b3_evidence_evaluation")
STATE_ROOT = pathlib.Path(r"D:\SCIfour\phase3B_execution\frozen_authorities\23_PHASE2B_R3_C1R_REGISTRY_CLOSURE\03_state_freeze")
MAPPING = pathlib.Path(r"D:\SCIfour\phase3B_execution\phase3b2_reexecution\outputs\qc\phase3b2_reexec_feature_mapping_audit.tsv")

EXPECTED = {
    P3B3 / "provenance" / "phase3B3_output_manifest.tsv": "6819F0600CBC0E1A6C3D891088F9C69773605B0583424856B9C5560D861A0C41",
    P3B3 / "provenance" / "phase3B3_qa.json": "CA1310EF5B5CD5B4DF1022C2ABD29DBE0A50D6448B9D90C434B9479223EC4A52",
    STATE_ROOT / "C1R_STATE_REGISTRY.csv": "F9DCCD28317FEFDE050DBF9D250C0E5254EEC964AA5E4354B599C9AD3872AA1D",
    STATE_ROOT / "states" / "SP02_GENES.tsv": "F87E55324FF00CCFBA3AB7A9E808257F60FE95BA8560152B6FDD0C70DD186FDA",
    MAPPING: "723EEC43E6EA4F1D83857F7651F5CDABD9AF68C1FF59A86BBCFD1001ACD07FDC",
}
QUERY = ["MUC6", "BPIFB1", "AQP5", "PGC"]


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def verify_manifest():
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
    return len(rows), failures


def main():
    ROOT.joinpath("work").mkdir(parents=True, exist_ok=True)
    ROOT.joinpath("provenance").mkdir(parents=True, exist_ok=True)
    fixed_failures = [str(path) for path, expected in EXPECTED.items() if sha256(path) != expected]
    manifest_rows, manifest_failures = verify_manifest()
    qa = json.loads((P3B3 / "provenance" / "phase3B3_qa.json").read_text(encoding="utf-8-sig"))
    if fixed_failures or manifest_failures or manifest_rows != 26:
        raise RuntimeError(f"PREDECESSOR_HASH_FAILURE fixed={fixed_failures} manifest={manifest_failures} rows={manifest_rows}")
    if qa.get("completion_state") != "C1R_PHASE3B3_PASS_READY_FOR_BIOLOGICAL_INTERPRETATION":
        raise RuntimeError("PHASE3B3_COMPLETION_TOKEN_MISSING")

    by_dataset = {"SCP259": set(), "SCP1884": set()}
    with MAPPING.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["mapping_status"] == "MAPPED" and row["dataset_identifier"] in by_dataset:
                by_dataset[row["dataset_identifier"]].add(row["canonical_hgnc_symbol"])
    background = sorted(by_dataset["SCP259"] & by_dataset["SCP1884"])
    if len(background) != 15851 or not set(QUERY).issubset(background):
        raise RuntimeError(f"BACKGROUND_CONTRACT_FAILURE n={len(background)} query_present={sorted(set(QUERY) & set(background))}")

    with (ROOT / "work" / "sp02_ora_background.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["gene_symbol", "background_basis"])
        writer.writerows((gene, "MAPPED_IN_BOTH_SCP259_AND_SCP1884") for gene in background)

    payload = {
        "organism": "hsapiens",
        "query": QUERY,
        "sources": ["GO:BP", "REAC"],
        "user_threshold": 0.05,
        "all_results": True,
        "ordered": False,
        "combined": False,
        "measure_underrepresentation": False,
        "no_iea": False,
        "domain_scope": "custom_annotated",
        "significance_threshold_method": "g_SCS",
        "background": background,
        "output": "json",
        "no_evidences": False,
        "highlight": False,
    }
    request_path = ROOT / "work" / "gprofiler_sp02_request.json"
    request_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    endpoint = "https://biit.cs.ut.ee/gprofiler/api/gost/profile/"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "C1R-Phase3B4/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        (ROOT / "work" / "gprofiler_sp02_error.txt").write_bytes(raw)
        raise RuntimeError(f"GPROFILER_HTTP_ERROR:{status}") from exc
    except Exception as exc:
        (ROOT / "work" / "gprofiler_sp02_error.txt").write_text(repr(exc) + "\n", encoding="utf-8")
        raise
    if status != 200:
        raise RuntimeError(f"GPROFILER_NON_200:{status}")
    parsed = json.loads(raw.decode("utf-8"))
    response_path = ROOT / "work" / "gprofiler_sp02_response.json"
    response_path.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    precheck = {
        "phase3b3_manifest_rows": manifest_rows,
        "phase3b3_manifest_failures": manifest_failures,
        "fixed_authority_hash_failures": fixed_failures,
        "phase3b3_completion_state": qa["completion_state"],
        "phase3b3_next_phase_autostart": qa["next_phase_autostart"],
        "scp259_mapped_genes": len(by_dataset["SCP259"]),
        "scp1884_mapped_genes": len(by_dataset["SCP1884"]),
        "intersection_background_genes": len(background),
        "query_genes_present": sorted(set(QUERY) & set(background)),
        "gprofiler_http_status": status,
        "gprofiler_result_rows": len(parsed.get("result", [])),
        "status": "PASS",
    }
    (ROOT / "provenance" / "phase3B4_precheck.json").write_text(
        json.dumps(precheck, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(precheck, indent=2))


if __name__ == "__main__":
    main()
