"""Reconstruct the frozen, single-target EV1 result from original GEO inputs.

This candidate script is a portability adaptation of the
frozen EV1 Stage A and Stage B code. It creates donor scores only in the
caller's output directory and must not be mistaken for a new analysis.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import norm

HERE = Path(__file__).resolve().parents[1]
EXPECTED = {
    "annotation": "70cfdaafa9613d20f5404f5b58a24cab506591a960daffb5d2f9bd3f6c120cfb",
    "counts": "57508fcb3045f08de37e4aacccf7dc994c4069408dd2733f2e3084b883c864ed",
    "hgnc": "6f43d6ff43aa9fdfa5fb2f20a20a7cace66e6e02e2a0dcf19d9b726e2e248d20",
}
LABELS = ("BEST4/OTOP2", "Cycling TA", "EEC", "Early Colonocyte", "Early Goblet",
          "Goblet Proliferating", "Intermediate Colonocyte", "LND", "Mature Colonocyte",
          "Mature Goblet", "Stem", "Tuft")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def table(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def score_cell(n, rows, values, targets):
    """Exact EV1 full-background average-tie percentile rank member mean."""
    positive = values[values > 0]
    sorted_positive = np.sort(positive)
    zeros = n - len(positive)
    lookup = dict(zip(rows.tolist(), values.tolist()))
    v = np.array([lookup.get(int(i), 0) for i in targets])
    lower = np.searchsorted(sorted_positive, v, side="left")
    upper = np.searchsorted(sorted_positive, v, side="right")
    ranks = zeros + (lower + 1 + upper) / 2.0
    ranks[v == 0] = (zeros + 1) / 2.0
    return float(np.mean((ranks - 1) / (n - 1)))


def fit(x, y):
    """Frozen EV1 OLS-HC3, two-sided normal-reference Wald estimator."""
    cc = np.isfinite(x) & np.isfinite(y)
    x = x[cc]
    y = y[cc]
    n = len(x)
    if n < 5:
        raise ValueError("Complete-case donor count below five")
    sx, sy = np.std(x, ddof=1), np.std(y, ddof=1)
    if not np.isfinite(sx) or sx <= 1e-12 or not np.isfinite(sy) or sy <= 1e-12:
        raise ValueError("Score SD gate failed")
    x = (x - x.mean()) / sx
    y = (y - y.mean()) / sy
    X = np.column_stack([np.ones(n), x])
    if np.linalg.matrix_rank(X) < 2:
        raise ValueError("Model rank gate failed")
    inv = np.linalg.inv(X.T @ X)
    leverage = np.sum((X @ inv) * X, axis=1)
    if np.any(1 - leverage <= 1e-8):
        raise ValueError("HC3 leverage gate failed")
    coef = inv @ X.T @ y
    residual = y - X @ coef
    weighted = residual / (1 - leverage)
    cov = inv @ (X.T @ ((weighted ** 2)[:, None] * X)) @ inv
    if not np.isfinite(cov[1, 1]) or cov[1, 1] < 0:
        raise ValueError("HC3 variance gate failed")
    beta, se = float(coef[1]), float(np.sqrt(cov[1, 1]))
    if not np.isfinite(beta) or not np.isfinite(se) or se <= 0:
        raise ValueError("Coefficient or SE gate failed")
    p = float(2 * norm.sf(abs(beta / se)))
    lo, hi = beta - 1.959963984540054 * se, beta + 1.959963984540054 * se
    classification = ("EXTERNAL_REPLICATION_SUPPORTED" if beta < 0 and hi < 0 else
                      "DIRECTIONALLY_CONSISTENT_INSUFFICIENT" if beta < 0 else
                      "DISCORDANT" if beta > 0 else "ZERO_ESTIMATE")
    return {"n_complete_donors": n, "beta": beta, "hc3_se": se, "ci95_lower": lo,
            "ci95_upper": hi, "raw_two_sided_p": p, "classification": classification,
            "predictor_sd": float(sx), "outcome_sd": float(sy)}


def reconstruct(annotation: Path, counts: Path, hgnc: Path, out: Path):
    for label, path in (("annotation", annotation), ("counts", counts), ("hgnc", hgnc)):
        actual = sha(path)
        if actual != EXPECTED[label]:
            raise ValueError(f"{label} SHA-256 mismatch: {actual}")
    mask_path = HERE / "definitions/GP_IBD_GCST004131_V1__SP02__NONOVERLAP_MASK.tsv"
    state_path = HERE / "definitions/SP02_GENES.tsv"
    mask = [r["gene_symbol"] for r in table(mask_path) if r["include_in_primary_view"] == "YES"]
    state = [r["gene_symbol"] for r in table(state_path)]
    if len(mask) != len(set(mask)) or len(mask) != 353 or set(state) != {"MUC6", "BPIFB1", "AQP5", "PGC"}:
        raise ValueError("Frozen definition mismatch")
    meta = pd.read_csv(annotation, sep="\t", dtype=str, keep_default_na=False)
    if meta.Barcodes.duplicated().any() or meta.eq("").any().any():
        raise ValueError("Annotation integrity failure")
    eligible = meta[(meta.Tissue == "Ascending Colon") & (meta.Source == "Endoscopy") &
                    meta.Histology.isin(["Mild", "Moderate", "Severe"]) &
                    meta.Celltypes.isin(LABELS)].copy()
    if (len(eligible), eligible.SampleID.nunique(), eligible.PatientID.nunique()) != (15989, 19, 18):
        raise ValueError("Frozen cohort count mismatch")
    if meta.groupby("SampleID").PatientID.nunique().max() != 1:
        raise ValueError("Ambiguous sample-to-donor mapping")
    hgnc_rows = table(hgnc)
    canonical, alias, ens = set(), defaultdict(set), defaultdict(set)
    for r in hgnc_rows:
        if r["status"] != "Approved":
            continue
        canonical.add(r["symbol"])
        for field in ("alias_symbol", "prev_symbol"):
            for value in r[field].split("|"):
                if value:
                    alias[value].add(r["symbol"])
        for value in r["ensembl_gene_id"].split("|"):
            if value:
                ens[re.sub(r"\.\d+$", "", value)].add(r["symbol"])
    features, rr, cc, vv = [], [], [], []
    with gzip.open(counts, "rt", encoding="utf-8-sig") as f:
        barcodes = f.readline().rstrip("\r\n").split("\t")
        if len(barcodes) != 72344 or len(set(barcodes)) != 72344 or set(barcodes) != set(meta.Barcodes):
            raise ValueError("Count-barcode linkage mismatch")
        selected = set(eligible.Barcodes)
        keep = np.array([i for i, barcode in enumerate(barcodes) if barcode in selected], dtype=np.int64)
        ordered = [barcodes[i] for i in keep]
        for index, line in enumerate(f):
            gene, sep, body = line.rstrip("\r\n").partition("\t")
            if not sep:
                raise ValueError("Malformed count row")
            features.append(gene)
            values = np.fromstring(body, sep="\t", dtype=np.float64)
            if len(values) != len(barcodes) or body.count("\t") != len(barcodes) - 1:
                raise ValueError("Count row field mismatch")
            if not np.isfinite(values).all() or (values < 0).any() or (values != np.floor(values)).any() or values.max() >= 2 ** 53:
                raise ValueError("Raw integer count semantics failure")
            selected_values = values[keep]
            nz = np.flatnonzero(selected_values)
            rr.append(np.full(len(nz), index, dtype=np.int32))
            cc.append(nz.astype(np.int32))
            vv.append(selected_values[nz])
    if len(features) != 25990 or len(set(features)) != 25990 or "" in features:
        raise ValueError("Count feature dimensions mismatch")
    mapped_symbols = []
    for gene in features:
        if gene.startswith("ENSG"):
            possibilities = ens.get(re.sub(r"\.\d+$", "", gene), set())
            target = next(iter(possibilities)) if len(possibilities) == 1 else ""
        elif gene in canonical:
            target = gene
        else:
            possibilities = alias.get(gene, set())
            target = next(iter(possibilities)) if len(possibilities) == 1 else ""
        mapped_symbols.append(target)
    tally = Counter(symbol for symbol in mapped_symbols if symbol)
    universe = sorted(tally)
    if len(universe) != 19471 or sum(gene in features and gene in canonical for gene in mask) != 324:
        raise ValueError("Frozen gene background or direct coverage mismatch")
    if sum(gene in tally for gene in mask) != 324 or sum(gene in tally for gene in state) != 4:
        raise ValueError("Frozen target coverage mismatch")
    raw = sparse.csr_matrix((np.concatenate(vv).astype(np.int64),
                             (np.concatenate(rr), np.concatenate(cc))),
                            shape=(len(features), len(ordered)))
    ui = {gene: i for i, gene in enumerate(universe)}
    valid = [i for i, symbol in enumerate(mapped_symbols) if symbol]
    collapse = sparse.csr_matrix((np.ones(len(valid), dtype=np.int64),
                                  ([ui[mapped_symbols[i]] for i in valid], valid)),
                                 shape=(len(universe), len(features)))
    matrix = (collapse @ raw).tocsc()
    matrix.sum_duplicates(); matrix.sort_indices()
    if not np.issubdtype(matrix.dtype, np.integer) or (matrix.data < 0).any():
        raise ValueError("Integer collapse failure")
    targets = [np.array([ui[g] for g in genes if g in ui]) for genes in (mask, state)]
    scores = np.empty((matrix.shape[1], 2), dtype=np.float64)
    for c in range(matrix.shape[1]):
        start, end = matrix.indptr[c:c + 2]
        for j, members in enumerate(targets):
            scores[c, j] = score_cell(matrix.shape[0], matrix.indices[start:end], matrix.data[start:end], members)
    if not np.isfinite(scores).all() or (scores < 0).any() or (scores > 1).any():
        raise ValueError("Score bounds failure")
    selected_meta = meta.set_index("Barcodes").loc[ordered].reset_index()
    selected_meta["GP_IBD_score"] = scores[:, 0]
    selected_meta["SP02_score"] = scores[:, 1]
    sample = selected_meta.groupby(["SampleID", "PatientID"], sort=True)[["GP_IBD_score", "SP02_score"]].median().reset_index()
    sample["contributing_cells"] = selected_meta.groupby(["SampleID", "PatientID"], sort=True).size().to_numpy()
    donor = sample.groupby("PatientID", sort=True)[["GP_IBD_score", "SP02_score"]].mean().reset_index()
    donor["contributing_samples"] = sample.groupby("PatientID", sort=True).size().to_numpy()
    donor["contributing_cells"] = sample.groupby("PatientID", sort=True).contributing_cells.sum().to_numpy()
    if len(donor) != 18 or donor.contributing_samples.sum() != 19 or donor.contributing_cells.sum() != 15989:
        raise ValueError("Frozen donor aggregation mismatch")
    result = fit(donor.GP_IBD_score.to_numpy(), donor.SP02_score.to_numpy())
    frozen = table(HERE / "results/C1R_EV1_PRIMARY_RESULT.tsv")[0]
    for key in ("beta", "hc3_se", "ci95_lower", "ci95_upper", "raw_two_sided_p"):
        if not np.isclose(result[key], float(frozen[key]), rtol=1e-9, atol=1e-12):
            raise ValueError(f"Frozen result mismatch: {key}")
    if result["classification"] != frozen["classification"]:
        raise ValueError("Frozen classification mismatch")
    out.mkdir(parents=True, exist_ok=False)
    donor.to_csv(out / "DONOR_SCORES_LOCAL_ONLY.tsv", sep="\t", index=False, float_format="%.17g")
    (out / "FROZEN_RESULT_COMPARISON.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("FROZEN_EV1_RECONSTRUCTION_MATCH; donor scores remain local", out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation", type=Path, required=True)
    parser.add_argument("--counts", type=Path, required=True)
    parser.add_argument("--hgnc", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reconstruct(args.annotation, args.counts, args.hgnc, args.output)


if __name__ == "__main__":
    main()
