# C1-R publication reproducibility release

This repository contains author-generated code and publication reproducibility materials. It does not redistribute third-party source datasets or restricted human data.

## Scientific objective

The frozen C1-R study evaluates donor-level associations between three GWAS-linked expression programs and seven epithelial-state scores in two IBD contexts. The five-donor M02 context provides bounded evidence and is not independent validation. See the publication for exact claims.

## Datasets and access

SCP259 and SCP1884 identify source transcriptomic studies; GCST004131, GCST004132 and GCST004133 identify GWAS study origins. See `DATA_SOURCES.md`. Exact analyzed source-object versions and permitted access paths require source-specific verification. No raw matrices, controlled metadata, donor-identifying information, or donor-level score matrix is distributed here.

## Contents and expected outputs

`scripts/` contains historical preprocessing, scoring, statistics, contextualization, table and figure code. `results/` contains the frozen publication table and supplementary result tables, including the full tested exploratory ORA family. These are inspection outputs, not a complete analytical input set. `synthetic_checks/` contains historical synthetic-only Python and R tests, their recorded outputs, and the original Phase 2C report; they do not establish reproduction of the real-data analysis. File identities are recorded in `RELEASE_FILE_MANIFEST.tsv`.

## Environment and execution

`config/` contains historical Python and R environment records; the top-level `environment.yml` is a proposed combined specification that has not been solved or run. The historical scripts embed local project paths and frozen input contracts. A clean installation or one-command rerun is not established. Do not run these scripts against arbitrary current portal downloads or infer that a new execution reproduces the frozen outputs. See `REPRODUCIBILITY_STATUS.md`.

## Citation and rights

Cite the versioned GitHub release and its verified Zenodo version DOI once the archive exists. See `CITATION.cff` and `RIGHTS_AND_SCOPE.md`. The MIT License covers author-owned code and documentation only. Third-party datasets remain governed by their original repositories.
