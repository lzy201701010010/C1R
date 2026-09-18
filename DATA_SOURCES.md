# Data sources and release scope

| Source | Public study identifier | Role | Release note |
| --- | --- | --- | --- |
| Ulcerative colitis transcriptomics | SCP259 | M01 broad-colon context | Exact analyzed HCA-distributed objects require a version-specific access record. |
| Crohn disease transcriptomics | SCP1884 | M02 inflamed-colon context | Exact analyzed HCA-distributed objects require a version-specific access record. |
| GWAS study origins | GCST004131; GCST004132; GCST004133 | Frozen expression gene sets | Study identifiers alone do not reconstruct every gene-set derivation step. |

No raw count matrices, directly identifiable data, donor-level score matrix, or third-party source files are in this candidate. `results/supplementary_tables/` contains frozen reported summaries, and `results/exploratory_ora/pathway_context_summary.tsv` contains the full 13,362-term tested exploratory ORA family. The ORA result is annotation dependent and does not establish pathway activation or mechanism. SHA-256 file identities are in `RELEASE_FILE_MANIFEST.tsv`.

Before public release, record exact source-object versions and access conditions, check whether donor-level derivatives may be deposited, and connect all necessary derivative files to a C1-R-specific public or controlled-access location. The manuscript Data Availability paragraph must then be updated to the verified location and terms.
