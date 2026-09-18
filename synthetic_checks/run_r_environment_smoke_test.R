#!/usr/bin/env Rscript

# Synthetic-only R environment and OLS-HC3 test. No real samples, genes, or distributions.

args <- commandArgs(trailingOnly = FALSE)
file_arg <- sub("^--file=", "", args[grepl("^--file=", args)])
script_dir <- dirname(normalizePath(file_arg, winslash = "/", mustWork = TRUE))
output_path <- file.path(script_dir, "r_synthetic_smoke_test_results.json")

set.seed(20260907)
RNGkind("Mersenne-Twister", "Inversion", "Rejection")

required <- c(
  Matrix = "1.7.1",
  data.table = "1.18.4",
  sandwich = "3.1.1",
  lmtest = "0.9.40",
  jsonlite = "2.0.0",
  digest = "0.6.37",
  renv = "1.1.5",
  zoo = "1.8.14"
)
observed <- vapply(names(required), function(pkg) as.character(packageVersion(pkg)), character(1))
versions_match <- all(observed == required)

synthetic <- data.frame(
  donor = sprintf("SYN_DONOR_%02d", 1:6),
  predictor = c(-1.7, -1.0, -0.2, 0.5, 1.1, 1.8),
  outcome = c(-1.2, -0.8, -0.1, 0.4, 0.9, 1.5)
)
fit <- lm(scale(outcome) ~ scale(predictor), data = synthetic)
vcov_hc3 <- sandwich::vcovHC(fit, type = "HC3")
test <- lmtest::coeftest(fit, vcov. = vcov_hc3)
checks <- list(
  synthetic_identifiers_only = all(grepl("^SYN_", synthetic$donor)),
  six_donors = nrow(synthetic) == 6,
  design_rank_two = fit$rank == 2,
  finite_hc3 = all(is.finite(vcov_hc3)),
  finite_coefficient_test = all(is.finite(test)),
  exact_package_versions = versions_match
)
status <- if (all(unlist(checks))) "PASS" else "FAIL"
payload <- list(
  test_kind = "SYNTHETIC_ONLY_NO_REAL_SAMPLES_GENES_OR_DISTRIBUTIONS",
  seed = 20260907,
  R = R.version.string,
  packages = as.list(observed),
  expected_packages = as.list(required),
  checks = checks,
  synthetic_model = list(
    beta = unname(coef(fit)[2]),
    hc3_se = unname(sqrt(diag(vcov_hc3))[2]),
    p = unname(test[2, 4])
  ),
  status = status
)
jsonlite::write_json(payload, output_path, pretty = TRUE, auto_unbox = TRUE, digits = NA)
cat(jsonlite::toJSON(list(output = output_path, status = status), auto_unbox = TRUE), "\n")
quit(status = if (status == "PASS") 0 else 1)
