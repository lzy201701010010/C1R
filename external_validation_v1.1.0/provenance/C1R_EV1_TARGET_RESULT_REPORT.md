# C1R-EV1 targeted external result

Execution: `C1R_EV1_ANALYSIS_COMPLETE`. Biological classification: `EXTERNAL_REPLICATION_SUPPORTED`.

Only GP_IBD_GCST004131_V1 non-overlap mask x SP02/INFLARE was evaluated. Input gate passed before any score. All 18 eligible donors were complete cases. SP02 coverage: 4/4; GP direct and final usable coverage: 324/353 (91.78470254957507%; minimum 283). No alias conversion added GP members. Background: 19,471 mapped canonical genes, after 41 duplicate canonical groups were collapsed by integer sum. The full 25,990 x 72,344 source matrix passed numeric validation (1,880,220,560 entries).

| Statistic | Frozen-method result |
|---|---:|
| Eligible / complete donors | 18 / 18 |
| Samples / epithelial cells | 19 / 15,989 |
| Standardized beta | -0.87334271107715811 |
| HC3 standard error | 0.12395291225025699 |
| 95% Wald CI lower | -1.1162859548665156 |
| 95% Wald CI upper | -0.63039946728780072 |
| Raw two-sided normal-reference Wald P | 1.8444937631118763e-12 |
| Wald z | -7.0457619367095381 |
| Residual df | 16 |

Model: standardized SP02 outcome ~ intercept + standardized GP_IBD predictor; OLS-HC3, no covariates, no weights. The sign is negative and concordant with original C1-R. The entire prespecified CI lies below zero, meeting the exact frozen success rule. No multiplicity correction applies to this one prespecified validation target. No other relationship was tested. The same estimator's independent algebraic QA differed by at most 7.91e-16; this is numerical verification, not a second biological model.

The external cohort is source-lineage-independent with no documented overlap with SCP259/SCP1884. Pseudonymized records cannot establish zero participant overlap. GSE266546 was used previously for other epithelial-state work in the related SCItwo project; those outcomes were not inspected in EV0/EV1. This is not a previously untouched cohort.

The result applies to donor-level expression-score association in the frozen active-CD ascending-colon endoscopic epithelial arm. It does not establish inherited genetic risk, PRS, mechanism, causality, clinical utility, state abundance, or universal portability. There are 18 complete donors, not 19 independent samples or 15,989 independent observations. [source donor ID redacted] contributes two sample medians averaged with equal weights.

The frozen normal-reference HC3 Wald procedure is an approximation with a small-sample limitation. Its small P value does not establish untested robustness. No sensitivity, influence-driven exclusion, alternative model or plot was authorized. GP coverage is 324/353; 29 frozen members are unavailable and were handled solely by the existing coverage rule. The 4-gene SP02 score remains exactly frozen.

Whole-study provenance limitations remain: 202,013 downloaded annotation rows versus GEO's 202,359 cells; 85 literal PatientID values versus GEO's 83 participants; conflicting Source=Endoscopy in AC_Surgical. The exact frozen AC_Endoscopy arm was reconstructed and its full count-barcode set matches metadata. No other compartment was used. Selected-donor adult status was not independently established and no adult-only claim is made.

The existing C1-R PORTABILITY_SUPPORTED classification and submission-candidate evidence remain historical and unchanged. EXTERNAL_REPLICATION_SUPPORTED is the prespecified EV0 category for this additive external layer, bounded by source-lineage and participant-identity limits. It does not automatically authorize manuscript integration, publication or submission.

`NO_POST_OUTCOME_SENSITIVITY_ANALYSES_AUTHORIZED`

`NEXT_PHASE_AUTOSTART = FORBIDDEN`
