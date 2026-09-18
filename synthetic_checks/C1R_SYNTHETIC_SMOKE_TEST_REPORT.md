# C1R synthetic smoke-test report

- Execution date: 2026-09-07 (Asia/Shanghai)
- Scope: synthetic mechanics and environment only
- Real samples: 0
- Real genes: 0
- Real expression distributions: 0
- Real matrices/H5AD/RDS/MTX opened: 0

## Python validation

An isolated Python 3.12.14 environment was created under excluded `_work`. All direct pins in `requirements.txt` resolved and imported at the specified versions: NumPy 2.3.5, pandas 3.0.1, SciPy 1.16.2, statsmodels 0.14.5, scanpy 1.11.4, anndata 0.12.2, h5py 3.14.0, zarr 3.1.2, pyarrow 21.0.0, matplotlib 3.10.6, and seaborn 0.13.2. The full transitive set is frozen in `python_resolved_freeze.txt`.

The deterministic synthetic test covered:

- one-to-many source-row duplicate collapse by sparse sum;
- ascending average ranks with explicit zero ties;
- `(rank-1)/(N-1)` normalization;
- post-rank state and program-mask selection;
- equal-cell sample median and equal-sample donor mean;
- donor z-standardization;
- OLS with HC3 covariance, rank and leverage checks;
- deterministic file-path and JSON output writing.

All nine core checks passed. The six-donor synthetic design had rank 2 and finite HC3 output. The test result SHA-256 is `3253AC600AE6012DC8D6DB9C3BF72284A33A0D77B660D00BD4396AC50FB3FE34`.

## R validation

An isolated R 4.4.2 library was created under excluded `_work`. Exact targets were validated: Matrix 1.7-1, data.table 1.18.4, sandwich 3.1-1, lmtest 0.9-40, jsonlite 2.0.0, digest 0.6.37, renv 1.1.5, and zoo 1.8-14.

The first CRAN install selected newer renv 1.2.4 and zoo 1.9-0. This version drift was not accepted; the exact locked releases were installed from CRAN Archive and rechecked. A six-donor synthetic OLS-HC3 test then passed package-version, design-rank, covariance, coefficient, and output-writing checks. The R result SHA-256 is `EE7837FB0919D0F63851289B8DCE64F69122FA083C49C2A9E51C56EDA8375EF7`.

Locale startup warnings reported unavailable `C.UTF-8` categories on Windows. No locale-sensitive parsing or sorting was used in the smoke test. Future execution must record and explicitly set an available locale before real metadata parsing.

## Verdict

`SYNTHETIC_CORE_MECHANICS = PASS`

`PYTHON_TARGET_ENVIRONMENT = PASS_ISOLATED_VALIDATION`

`R_TARGET_ENVIRONMENT = PASS_ISOLATED_VALIDATION`

This test does not validate real input identity, matrix dimensions, count semantics, barcode mapping, gene coverage, score variance, or biological estimability.

`REAL_PIPELINE_EXECUTION = NOT_RUN`

`NEXT_PHASE_AUTOSTART = FORBIDDEN`
