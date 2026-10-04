# C1R-EV1 frozen executable method lock

Created before any target score. Scientific sources and their hashes are listed below. Explicit EV0 single-target rules supersede the original multi-test families; all remaining method semantics are inherited. No scoring uses previous results.

## locked_at

2026-10-03T17:31:45.311169+08:00

## target

GP_IBD_GCST004131_V1_x_SP02_INFLARE

## cohort

GSE266546_AC_ENDOSCOPY_ACTIVE_CD_EPITHELIAL

## sources

{
  "C1R_STATE_SCORING_CONTRACT.md": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "c140048a3ab69a65a75800c628d3ae884c7cdf9dbe7db306a6f3e657acdea43e"
  },
  "C1R_GWAS_PROGRAM_SCORING_CONTRACT.md": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "0bfe495d6234a97d5e7a593b54496c734981e85acecebd9c8a2fc17fb002ae6b"
  },
  "C1R_EXPRESSION_LAYER_CONTRACT.md": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "3bd41f74f4a2cccf1d1f994d92a8560ea6db84cb6e50b5c6cf18cccec1b9f610"
  },
  "C1R_GENE_MAPPING_CONTRACT.md": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "c814f53bb94baf3892d14522aabfb33dbbb680264cc8611b9e0a1b91b0a7cc31"
  },
  "C1R_MODEL_EXECUTION_CONTRACT.md": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "0f88bd8d3e3a8386d85fabdab1649ee757fe2e5c72805baf6cffc330269a4f13"
  },
  "EV0_contract": {
    "path": "[HISTORICAL_LOCAL_PATH_REDACTED]",
    "sha256": "f84771ae207303496d1b3d798f296f4ea4dc9e25dbf846f674151922be4e2b63"
  }
}

## background_genes

19471

## method

SM02_WITHIN_CELL_PERCENTILE_RANK_MEAN_V1

## expression

finite non-negative raw integer counts; no normalization, log, gene centering/scaling or imputation

## mapping

approved HGNC exact; otherwise unique alias/previous or supplied Ensembl through frozen reference; ambiguous/unmapped dropped; duplicate canonical rows summed as integers

## ranking

all mapped canonical genes including zeros, ascending average ties, normalized (rank-1)/(N-1); N>=2

## membership

exact non-overlap mask and SP02; missing feature members excluded only under inherited coverage floor; structurally present zero genes retained in every cell

## coverage

{
  "GP_IBD_denominator": 353,
  "GP_IBD_min": 283,
  "GP_IBD_direct": 324,
  "GP_IBD_usable": 324,
  "SP02_denominator": 4,
  "SP02_min": 4
}

## weighting

unweighted member arithmetic mean; equal-cell median within sample; equal-sample arithmetic mean within donor

## repeat

[source donor ID redacted] contributes two sample medians, each weight 1/2, yielding one donor row

## standardization

complete-case restriction then each donor score centered and divided by sample SD ddof=1 within context

## model

z(SP02) ~ intercept + z(GP_IBD_nonoverlap); OLS; HC3 covariance; no covariates or weights

## coefficient

SP02 standardized outcome change per 1 sample-SD higher GP_IBD; expected beta<0; no score reversal

## inference

HC3 sandwich; two-sided normal-reference Wald P=2*norm.sf(abs(beta/SE)); CI=beta +/- 1.959963984540054*SE

## multiplicity

single prespecified external hypothesis; raw P; no new BH family; CI is primary classification criterion

## not_estimable

[
  "complete-case donors<5",
  "score SD nonfinite or <=1e-12",
  "design rank<2",
  "residual df<=0",
  "inversion failure",
  "any 1-h<=1e-8",
  "nonfinite beta or SE",
  "HC3 variance invalid/negative or SE<=0 (inherited executable guard)"
]

## classification

{
  "beta<0 and CI upper<0": "EXTERNAL_REPLICATION_SUPPORTED",
  "beta<0 and CI includes zero": "DIRECTIONALLY_CONSISTENT_INSUFFICIENT",
  "beta>0": "DISCORDANT",
  "valid beta exactly zero": "ZERO_ESTIMATE",
  "required source score model gate fails": "NOT_ESTIMABLE"
}

## technical_stop

any input integrity, mapping, coverage, cohort or numeric semantics failure; no substitute cohort/layer/method

## sensitivities

NO_POST_OUTCOME_SENSITIVITY_ANALYSES_AUTHORIZED

## plots

NONE_PRESPECIFIED

## randomness

NONE

## next_phase_autostart

FORBIDDEN

Exact 353 GP members and 4 SP02 members are in the JSON companion; their source registries are independently hashed in the authority registry. Structurally available target members include their zero values.
