options(stringsAsFactors = FALSE, scipen = 999, warn = 1)

suppressPackageStartupMessages({
  library(ggplot2)
  library(patchwork)
  library(dplyr)
  library(tidyr)
  library(jsonlite)
  library(svglite)
  library(digest)
})

project_root <- normalizePath("D:/SCIfour", winslash = "/", mustWork = TRUE)
out_root <- file.path(project_root, "39_PHASE4B3_C1R_BMC_GENOMICS_RENDERING_AND_POSITIONING")
figure_dir <- file.path(out_root, "figures")
qa_dir <- file.path(out_root, "qa")
preview_dir <- file.path(qa_dir, "previews")
log_dir <- file.path(out_root, "logs")
code_dir <- file.path(out_root, "code")
script_path <- normalizePath(file.path(code_dir, "render_phase4b3_figures.R"), winslash = "/", mustWork = TRUE)

dir.create(figure_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(preview_dir, recursive = TRUE, showWarnings = FALSE)
dir.create(log_dir, recursive = TRUE, showWarnings = FALSE)

skill_dir <- Sys.getenv("NATURE_FIGURE_SKILL_DIR", unset = "")
python_exe <- Sys.getenv("C1R_PYTHON", unset = "")
if (!nzchar(skill_dir) || !dir.exists(skill_dir)) {
  stop("NATURE_FIGURE_SKILL_DIR must point to the active nature-figure skill directory", call. = FALSE)
}
if (!nzchar(python_exe) || !file.exists(python_exe)) {
  stop("C1R_PYTHON must point to the backend-neutral audit Python executable", call. = FALSE)
}
alignment_helper <- file.path(skill_dir, "scripts", "panel_alignment.R")
alignment_auditor <- file.path(skill_dir, "scripts", "audit_panel_alignment.py")
if (!file.exists(alignment_helper) || !file.exists(alignment_auditor)) {
  stop("Required alignment helper or auditor is unavailable", call. = FALSE)
}
source(alignment_helper)

# patchwork 1.3.x retains flexible layout tracks as `null` units. The upstream
# helper's direct unit conversion returns zero for those tracks outside a grid
# layout viewport. Resolve the final track lengths from the actual export size
# in R, then pass the measured rectangles to the unchanged backend-neutral
# auditor. Fixed tracks remain device-measured; only the remaining physical
# extent is allocated in proportion to the declared null weights.
resolve_track_points <- function(track_units, total_pt, axis = c("width", "height")) {
  axis <- match.arg(axis)
  indices <- seq_along(track_units)
  types <- vapply(indices, function(i) grid::unitType(track_units[i]), character(1))
  values <- vapply(indices, function(i) as.numeric(track_units[i]), numeric(1))
  resolved <- numeric(length(indices))
  fixed <- types != "null"
  if (any(fixed)) {
    resolved[fixed] <- vapply(indices[fixed], function(i) {
      if (axis == "width") {
        grid::convertWidth(track_units[i], "pt", valueOnly = TRUE)
      } else {
        grid::convertHeight(track_units[i], "pt", valueOnly = TRUE)
      }
    }, numeric(1))
  }
  remaining <- total_pt - sum(resolved[fixed])
  if (!is.finite(remaining) || remaining <= 0) {
    stop(sprintf("No positive physical extent remains for patchwork %s null tracks", axis), call. = FALSE)
  }
  if (any(!fixed)) {
    null_total <- sum(values[!fixed])
    if (!is.finite(null_total) || null_total <= 0) {
      stop(sprintf("Invalid patchwork %s null-track weights", axis), call. = FALSE)
    }
    resolved[!fixed] <- remaining * values[!fixed] / null_total
  }
  if (any(!is.finite(resolved)) || any(resolved < 0)) {
    stop(sprintf("Patchwork %s tracks could not be resolved", axis), call. = FALSE)
  }
  resolved
}

write_patchwork_panel_layout <- function(
  plot,
  manifest_path,
  width_in,
  height_in,
  panel_ids = NULL,
  row_groups = NULL,
  column_groups = NULL,
  exemptions = list()
) {
  grob <- patchwork::patchworkGrob(plot)
  panel_rows <- grob$layout[
    grepl("^panel(?:-[0-9]+)?$", grob$layout$name, perl = TRUE) |
      grepl("^panel;", grob$layout$name, perl = TRUE),
    , drop = FALSE
  ]
  if (nrow(panel_rows) < 2L) {
    stop("At least two patchwork panel cells are required for alignment QA", call. = FALSE)
  }
  panel_rows <- panel_rows[order(panel_rows$t, panel_rows$l), , drop = FALSE]
  if (is.null(panel_ids)) panel_ids <- letters[seq_len(nrow(panel_rows))]
  panel_ids <- as.character(panel_ids)
  if (length(panel_ids) != nrow(panel_rows) || anyDuplicated(panel_ids) || any(!nzchar(panel_ids))) {
    stop("panel_ids must be unique, non-empty, and match the measured patchwork panels", call. = FALSE)
  }
  width_pt <- width_in * 72
  height_pt <- height_in * 72
  widths_pt <- resolve_track_points(grob$widths, width_pt, "width")
  heights_pt <- resolve_track_points(grob$heights, height_pt, "height")
  x_edges <- c(0, cumsum(widths_pt))
  top_edges <- c(0, cumsum(heights_pt))
  panels <- lapply(seq_len(nrow(panel_rows)), function(index) {
    row <- panel_rows[index, ]
    list(
      id = panel_ids[index],
      bbox_pt = unname(c(
        x_edges[row$l],
        height_pt - top_edges[row$b + 1],
        x_edges[row$r + 1],
        height_pt - top_edges[row$t]
      )),
      grid_id = "patchwork-grid-1",
      row_start = as.integer(row$t - 1),
      row_stop = as.integer(row$b),
      col_start = as.integer(row$l - 1),
      col_stop = as.integer(row$r)
    )
  })
  manifest <- list(
    schema_version = 1L,
    backend = "r-patchwork",
    figure = list(width_pt = width_pt, height_pt = height_pt),
    panels = panels,
    exemptions = exemptions
  )
  normalized_rows <- .nature_alignment_groups(row_groups)
  normalized_columns <- .nature_alignment_groups(column_groups)
  if (!is.null(normalized_rows)) manifest$row_groups <- normalized_rows
  if (!is.null(normalized_columns)) manifest$column_groups <- normalized_columns
  dir.create(dirname(manifest_path), recursive = TRUE, showWarnings = FALSE)
  jsonlite::write_json(manifest, manifest_path, auto_unbox = TRUE, pretty = TRUE, digits = NA)
  invisible(manifest)
}

sha256_file <- function(path) {
  toupper(digest::digest(file = path, algo = "sha256"))
}

read_tsv <- function(path) {
  read.delim(path, sep = "\t", check.names = FALSE, quote = "", comment.char = "", fileEncoding = "UTF-8")
}

write_tsv <- function(data, path) {
  write.table(data, file = path, sep = "\t", row.names = FALSE, col.names = TRUE,
              quote = FALSE, na = "NA", fileEncoding = "UTF-8")
}

rel_path <- function(path) {
  path <- normalizePath(path, winslash = "/", mustWork = FALSE)
  prefix <- paste0(project_root, "/")
  if (startsWith(path, prefix)) substring(path, nchar(prefix) + 1L) else path
}

verify_manifest <- function(root_rel, manifest_name, label) {
  root <- file.path(project_root, root_rel)
  manifest_path <- file.path(root, manifest_name)
  manifest <- read_tsv(manifest_path)
  rows <- lapply(seq_len(nrow(manifest)), function(i) {
    source_path <- file.path(root, manifest$relative_path[i])
    exists <- file.exists(source_path)
    observed_size <- if (exists) file.info(source_path)$size else NA_real_
    observed_sha <- if (exists) sha256_file(source_path) else "NA_MISSING"
    expected_size <- as.numeric(manifest$size_bytes[i])
    expected_sha <- toupper(manifest$sha256[i])
    status <- if (exists && identical(as.numeric(observed_size), expected_size) && identical(observed_sha, expected_sha)) "PASS" else "FAIL"
    data.frame(
      Package = label,
      `Manifest file` = file.path(root_rel, manifest_name),
      `Relative path` = manifest$relative_path[i],
      `Expected size bytes` = expected_size,
      `Observed size bytes` = observed_size,
      `Expected SHA256` = expected_sha,
      `Observed SHA256` = observed_sha,
      Status = status,
      check.names = FALSE
    )
  })
  result <- bind_rows(rows)
  if (any(result$Status != "PASS")) {
    stop(sprintf("Predecessor manifest verification failed for %s", label), call. = FALSE)
  }
  result
}

manifest_checks <- bind_rows(
  verify_manifest(
    "35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE",
    "C1R_EVIDENCE_PACKAGE_MANIFEST.tsv",
    "Phase 4A"
  ),
  verify_manifest(
    "36_PHASE4B1_C1R_FIGURE_ARCHITECTURE_AND_PANEL_DESIGN_FREEZE",
    "C1R_FIGURE_DESIGN_MANIFEST.tsv",
    "Phase 4B-1"
  ),
  verify_manifest(
    "37_PHASE4B2_C1R_FIGURE_PRODUCTION_SPECIFICATION_AND_RENDERING_GATE",
    "C1R_PHASE4B2_OUTPUT_MANIFEST.tsv",
    "Phase 4B-2"
  ),
  verify_manifest(
    "38_C1R_TARGET_JOURNAL_SELECTION_AND_FIGURE_REQUIREMENT_ALIGNMENT",
    "C1R_JOURNAL_SELECTION_MANIFEST.tsv",
    "Target journal selection"
  )
)
write_tsv(manifest_checks, file.path(qa_dir, "C1R_PREDECESSOR_MANIFEST_CHECKS.tsv"))

binding_path <- file.path(
  project_root,
  "37_PHASE4B2_C1R_FIGURE_PRODUCTION_SPECIFICATION_AND_RENDERING_GATE",
  "C1R_PANEL_DATA_BINDING.tsv"
)
bindings <- read_tsv(binding_path)
required_binding_columns <- c(
  "Figure", "Panel", "Source file", "Source SHA256", "Source table", "Columns used",
  "Row selection", "Ordering", "Transformation", "Missing/unavailable handling",
  "Visualization object", "Source authority", "Binding status"
)
if (!all(required_binding_columns %in% names(bindings))) {
  stop("Phase 4B-2 panel binding schema is incomplete", call. = FALSE)
}
if (!setequal(unique(bindings$Panel), c("F1A", "F1B", "F1C", "F2A", "F2B", "F3A", "F3B", "F4A", "F4B", "F4C", "SF1A", "SF1B", "SF2A", "SF2B", "SF3A"))) {
  stop("Frozen panel set does not match the required 15-panel architecture", call. = FALSE)
}

source_integrity <- lapply(seq_len(nrow(bindings)), function(i) {
  source_path <- file.path(project_root, bindings$`Source file`[i])
  observed_sha <- if (file.exists(source_path)) sha256_file(source_path) else "NA_MISSING"
  expected_sha <- toupper(bindings$`Source SHA256`[i])
  status <- if (file.exists(source_path) && identical(observed_sha, expected_sha)) "PASS" else "FAIL"
  data.frame(
    Figure = bindings$Figure[i],
    Panel = bindings$Panel[i],
    `Source file` = bindings$`Source file`[i],
    `Expected SHA256` = expected_sha,
    `Observed SHA256` = observed_sha,
    `Size bytes` = if (file.exists(source_path)) file.info(source_path)$size else NA_real_,
    Status = status,
    check.names = FALSE
  )
}) |> bind_rows()
if (any(source_integrity$Status != "PASS")) {
  stop("Frozen panel source verification failed", call. = FALSE)
}
write_tsv(transform(source_integrity, `Check stage` = "PRE_RENDER"), file.path(qa_dir, "C1R_SOURCE_INTEGRITY_PRE_RENDER.tsv"))

read_source_tsv <- function(rel) read_tsv(file.path(project_root, rel))
read_source_csv <- function(rel) read.csv(file.path(project_root, rel), check.names = FALSE, stringsAsFactors = FALSE)

programs <- read_source_csv("phase3B_execution/frozen_authorities/23_PHASE2B_R3_C1R_REGISTRY_CLOSURE/02_genetic_program_freeze/C1R_GENETIC_PROGRAM_REGISTRY.csv")
states <- read_source_csv("phase3B_execution/frozen_authorities/23_PHASE2B_R3_C1R_REGISTRY_CLOSURE/03_state_freeze/C1R_STATE_REGISTRY.csv")
cohorts <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/Table1_study_cohorts_and_analytical_framework.tsv")
evidence <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/Table2_program_state_evidence_hierarchy.tsv")
primary <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/Table3_primary_donor_level_association_results.tsv")
context <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/Table4_biological_contextualization_summary.tsv")
qc <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/SupplementaryTable1_cell_qc_characteristics.tsv")
state_coverage <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/SupplementaryTable2A_state_representation_summary.tsv")
program_coverage <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/SupplementaryTable2B_genetic_program_coverage_summary.tsv")
all_effects <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/tables/SupplementaryTable3_complete_donor_level_results.tsv")
claims <- read_source_tsv("35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/C1R_CLAIM_INVENTORY.tsv")
biology_linkage <- read_source_tsv("phase3B_execution/phase3b4_biological_contextualization/evidence_to_biology_linkage_table.tsv")

stopifnot(
  nrow(programs) == 3L,
  nrow(states) == 7L,
  nrow(cohorts) == 3L,
  nrow(evidence) == 21L,
  nrow(primary) == 8L,
  nrow(context) == 5L,
  nrow(qc) == 15L,
  nrow(state_coverage) == 21L,
  nrow(program_coverage) == 6L,
  nrow(all_effects) == 36L,
  all(all_effects$status == "ESTIMABLE"),
  sum(claims$claim_id %in% c("H001", "H002", "H003")) == 3L,
  sum(biology_linkage$genetic_program == "GP_IBD_GCST004131_V1" & biology_linkage$epithelial_state == "SP02") == 1L
)
if (anyDuplicated(paste(evidence$program_id, evidence$state_id))) {
  stop("Duplicate program-state mapping detected", call. = FALSE)
}

numeric_columns <- c("n_complete_donors", "beta", "hc3_se", "ci95_lower", "ci95_upper", "bh_adjusted_p")
for (column in intersect(numeric_columns, names(primary))) primary[[column]] <- as.numeric(primary[[column]])
for (column in intersect(numeric_columns, names(all_effects))) all_effects[[column]] <- as.numeric(all_effects[[column]])
for (column in c("donor_count", "sample_count", "represented_cell_count")) cohorts[[column]] <- as.numeric(cohorts[[column]])
for (column in c("minimum", "q1", "median", "mean", "q3", "maximum", "missing_or_nonfinite_count")) qc[[column]] <- as.numeric(qc[[column]])
for (column in c("registered_gene_count", "mapped_gene_count", "coverage_proportion")) state_coverage[[column]] <- as.numeric(state_coverage[[column]])
for (column in c("total_registered_genes", "successfully_mapped_genes", "coverage_proportion", "state_specific_nonoverlap_masks_passing", "state_specific_nonoverlap_masks_total")) program_coverage[[column]] <- as.numeric(program_coverage[[column]])

program_map <- c(
  GP_IBD_GCST004131_V1 = "GP_IBD",
  GP_CD_GCST004132_V1 = "GP_CD",
  GP_UC_GCST004133_V1 = "GP_UC"
)
state_map <- setNames(paste(states$state_id, states$state_name, sep = " | "), states$state_id)
arm_colors <- c(M01 = "#2F5D7C", M02 = "#D08A3E", M03 = "#8A8A8A")
evidence_colors <- c(
  PORTABILITY_SUPPORTED = "#2F5D7C",
  DIRECTIONALLY_CONSISTENT_INSUFFICIENT = "#9FBAD0",
  DISCORDANT = "#B35A4A",
  NOT_EVALUATED = "#D9D9D9"
)
evidence_labels <- c(
  PORTABILITY_SUPPORTED = "Portability\nsupported",
  DIRECTIONALLY_CONSISTENT_INSUFFICIENT = "Directionally\nconsistent; insufficient",
  DISCORDANT = "Discordant",
  NOT_EVALUATED = "Not evaluated"
)

theme_pub <- function(base_size = 7) {
  theme_classic(base_size = base_size, base_family = "sans") +
    theme(
      axis.line = element_line(linewidth = 0.35, colour = "#333333"),
      axis.ticks = element_line(linewidth = 0.35, colour = "#333333"),
      axis.title = element_text(size = 7, colour = "#222222"),
      axis.text = element_text(size = 6.5, colour = "#222222"),
      axis.text.x = element_text(margin = margin(t = 2.5)),
      legend.title = element_text(size = 6.5, face = "bold"),
      legend.text = element_text(size = 6.2),
      strip.text = element_text(size = 6.5, face = "bold"),
      plot.title = element_text(size = 7.5, face = "bold", colour = "#222222", margin = margin(b = 3, l = 6)),
      plot.subtitle = element_text(size = 6.2, colour = "#4D4D4D", margin = margin(b = 4)),
      panel.grid = element_blank(),
      plot.margin = margin(5, 6, 5, 6)
    )
}

theme_schematic <- function() {
  theme_void(base_family = "sans", base_size = 7) +
    theme(
      plot.title = element_text(size = 7.5, face = "bold", colour = "#222222", margin = margin(b = 3, l = 6)),
      plot.subtitle = element_text(size = 6.2, colour = "#4D4D4D", margin = margin(b = 4)),
      plot.margin = margin(5, 6, 5, 6)
    )
}

panel_tag_theme <- theme(
  plot.tag = element_text(family = "sans", size = 8, face = "bold", colour = "#111111"),
  plot.tag.position = c(0, 1)
)

format_int <- function(x) format(x, big.mark = ",", scientific = FALSE, trim = TRUE)
format_q <- function(x) ifelse(x < 0.001, formatC(x, format = "e", digits = 2), formatC(x, format = "f", digits = 4))

programs$short <- unname(program_map[programs$program_id])
programs$display <- sprintf(
  "%s\n%s genes | %s",
  programs$short,
  programs$n_genes,
  ifelse(programs$primary_or_exploratory == "PRIMARY", "primary", "exploratory")
)
programs$xmin <- 0.25
programs$xmax <- 3.35
programs$y <- c(7.7, 5.0, 2.3)
programs$ymin <- programs$y - 0.82
programs$ymax <- programs$y + 0.82

states$display <- sprintf("%s | %s\n%s genes", states$state_id, states$state_name, states$n_genes)
states$xmin <- 6.55
states$xmax <- 9.75
states$y <- seq(8.6, 1.4, length.out = 7)
states$ymin <- states$y - 0.50
states$ymax <- states$y + 0.50

p1a <- ggplot() +
  geom_rect(data = programs, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax,
                                 fill = primary_or_exploratory), colour = "#4A4A4A", linewidth = 0.35) +
  geom_text(data = programs, aes(x = 1.8, y = y, label = display), size = 2.05, lineheight = 0.95, family = "sans") +
  geom_rect(data = states, aes(xmin = xmin, xmax = xmax, ymin = ymin, ymax = ymax,
                               fill = primary_or_exploratory), colour = "#4A4A4A", linewidth = 0.35) +
  geom_text(data = states, aes(x = 8.15, y = y, label = display), size = 1.95, lineheight = 0.92, family = "sans") +
  annotate("text", x = 5.0, y = 5.0, label = "3 x 7 = 21\nfrozen mappings", size = 2.35,
           fontface = "bold", family = "sans", lineheight = 1.0, colour = "#2F5D7C") +
  annotate("text", x = 1.8, y = 9.5, label = "GWAS-linked expression programs", size = 2.2,
           fontface = "bold", family = "sans") +
  annotate("text", x = 8.15, y = 9.5, label = "Frozen epithelial states", size = 2.2,
           fontface = "bold", family = "sans") +
  scale_fill_manual(values = c(PRIMARY = "#DCE8F0", EXPLORATORY = "#F0F0F0"), guide = "none") +
  coord_cartesian(xlim = c(0, 10), ylim = c(0.6, 10), clip = "off") +
  labs(title = "Frozen program and state objects",
       subtitle = "Expression-gene-set scores are not polygenic risk scores") +
  theme_schematic()

cohorts$role_display <- c("Primary discovery", "Bounded portability", "Exploratory | NOT EVALUATED")
cohorts$box_text <- sprintf(
  "%s\n%s\n%s donors | %s samples\n%s represented cells",
  cohorts$analysis_arm_id,
  cohorts$role_display,
  cohorts$donor_count,
  cohorts$sample_count,
  format_int(cohorts$represented_cell_count)
)
cohorts$box_text_colour <- ifelse(cohorts$analysis_arm_id == "M01", "white", "#111111")
cohorts$x <- 1:3
cohorts$xmin <- cohorts$x - 0.43
cohorts$xmax <- cohorts$x + 0.43

p1b <- ggplot(cohorts) +
  geom_rect(aes(xmin = xmin, xmax = xmax, ymin = 0.2, ymax = 0.86, fill = analysis_arm_id),
            colour = "#4A4A4A", linewidth = 0.35) +
  geom_text(aes(x = x, y = 0.53, label = box_text, colour = box_text_colour),
            size = 2.05, lineheight = 0.96, family = "sans") +
  annotate("text", x = 2, y = 0.07, label = "Contexts are not pooled; M03 cannot rescue or replace M02",
           size = 2.05, family = "sans", colour = "#4D4D4D") +
  scale_fill_manual(values = arm_colors, guide = "none") +
  scale_colour_identity() +
  coord_cartesian(xlim = c(0.5, 3.5), ylim = c(0, 1), clip = "off") +
  labs(title = "Cohort roles and structural scope") +
  theme_schematic()

workflow <- data.frame(
  x = 1:7,
  label = c(
    "Frozen cell\nscores",
    "Equal-cell\nsample median",
    "Equal-sample\ndonor mean",
    "Within-context\nstandardization",
    "OLS + HC3",
    "Two-sided\nWald CI and P",
    "Within-family BH\nand evidence class"
  )
)
workflow$xmin <- workflow$x - 0.40
workflow$xmax <- workflow$x + 0.40
arrow_data <- data.frame(x = 1:6 + 0.42, xend = 2:7 - 0.42)

p1c <- ggplot() +
  geom_segment(data = arrow_data, aes(x = x, xend = xend, y = 0.52, yend = 0.52),
               linewidth = 0.38, colour = "#6D6D6D", arrow = arrow(length = unit(2.1, "mm"), type = "closed")) +
  geom_rect(data = workflow, aes(xmin = xmin, xmax = xmax, ymin = 0.24, ymax = 0.80),
            fill = "#E8F0F5", colour = "#2F5D7C", linewidth = 0.4) +
  geom_text(data = workflow, aes(x = x, y = 0.52, label = label), size = 1.95,
            lineheight = 0.94, family = "sans") +
  annotate("text", x = 4, y = 0.09,
           label = "Donor is the inferential unit; no cell-level hypothesis test or cross-context pooling",
           size = 2.0, family = "sans", colour = "#4D4D4D") +
  coord_cartesian(xlim = c(0.5, 7.5), ylim = c(0, 1), clip = "off") +
  labs(title = "Frozen donor-level analytical workflow") +
  theme_schematic()

F1 <- (p1a / p1b / p1c) +
  plot_layout(heights = c(1.4, 0.82, 0.88)) +
  plot_annotation(tag_levels = "a") & panel_tag_theme

evidence$program_short <- unname(program_map[evidence$program_id])
evidence$x <- match(evidence$state_id, sprintf("SP%02d", 1:7))
evidence$y <- unname(c(GP_IBD = 3, GP_CD = 2, GP_UC = 1)[evidence$program_short])
evidence$cell_label <- unname(evidence_labels[evidence$evidence_class])
hatch_cells <- evidence[evidence$evidence_class == "NOT_EVALUATED", c("x", "y")]
hatch <- bind_rows(lapply(seq_len(nrow(hatch_cells)), function(i) {
  data.frame(
    x = hatch_cells$x[i] + c(-0.42, -0.10, 0.20, -0.42, -0.10, 0.20),
    xend = hatch_cells$x[i] + c(-0.20, 0.12, 0.42, -0.20, 0.12, 0.42),
    y = hatch_cells$y[i] + c(rep(-0.38, 3), rep(0.17, 3)),
    yend = hatch_cells$y[i] + c(rep(-0.17, 3), rep(0.38, 3))
  )
}))

p2a <- ggplot(evidence, aes(x = x, y = y)) +
  geom_tile(aes(fill = evidence_class), width = 0.94, height = 0.82,
            colour = "white", linewidth = 0.45) +
  geom_segment(data = hatch, aes(x = x, xend = xend, y = y, yend = yend),
               inherit.aes = FALSE, linewidth = 0.25, colour = "#777777") +
  geom_text(data = evidence[evidence$evidence_class %in% c("PORTABILITY_SUPPORTED", "DISCORDANT"), ],
            aes(label = cell_label), size = 1.85, lineheight = 0.9, family = "sans",
            colour = "white") +
  geom_text(data = evidence[!evidence$evidence_class %in% c("NOT_EVALUATED", "PORTABILITY_SUPPORTED", "DISCORDANT"), ],
            aes(label = cell_label), size = 1.85, lineheight = 0.9, family = "sans",
            colour = "#1F1F1F") +
  geom_label(data = evidence[evidence$evidence_class == "NOT_EVALUATED", ],
             aes(label = cell_label), size = 1.85, lineheight = 0.9, family = "sans",
             colour = "#1F1F1F", fill = "#D9D9D9", linewidth = 0,
             label.padding = unit(0.45, "mm")) +
  geom_hline(yintercept = 2.5, linetype = "dashed", linewidth = 0.35, colour = "#5A5A5A") +
  scale_x_continuous(breaks = 1:7, labels = sprintf("SP%02d", 1:7), expand = expansion(add = 0.05)) +
  scale_y_continuous(breaks = 1:3, labels = c("GP_UC\nexploratory", "GP_CD\nexploratory", "GP_IBD\nprimary"),
                     expand = expansion(add = 0.05)) +
  scale_fill_manual(values = evidence_colors, guide = "none") +
  coord_cartesian(xlim = c(0.5, 7.5), ylim = c(0.5, 3.5), clip = "off") +
  labs(title = "Complete 21-mapping evidence landscape",
       subtitle = "Text plus color/pattern encoding; not evaluated is not negative evidence",
       x = "Frozen epithelial state", y = NULL) +
  theme_pub() +
  theme(axis.line = element_blank(), axis.ticks = element_blank(), panel.border = element_rect(fill = NA, linewidth = 0.35))

family_order <- c("PRIMARY_8", "E_CD_14", "E_UC_14")
all_effects$program_short <- unname(program_map[all_effects$program_id])
row_spec <- bind_rows(
  data.frame(family = "PRIMARY_8", state_id = sprintf("SP%02d", 1:4)),
  data.frame(family = "E_CD_14", state_id = sprintf("SP%02d", 1:7)),
  data.frame(family = "E_UC_14", state_id = sprintf("SP%02d", 1:7))
)
row_spec$row_index <- seq_len(nrow(row_spec))
row_spec$y_base <- nrow(row_spec) + 1 - row_spec$row_index
row_spec$label <- paste(
  c(rep("GP_IBD", 4), rep("GP_CD", 7), rep("GP_UC", 7)),
  row_spec$state_id,
  sep = " | "
)
all_effects <- left_join(all_effects, row_spec, by = c("family", "state_id"))
if (any(is.na(all_effects$y_base))) stop("Effect ordering join failed", call. = FALSE)
all_effects$y <- all_effects$y_base + ifelse(all_effects$arm == "M01", 0.14, -0.14)
all_effects$bh_pass <- all_effects$passes_family_bh_0_05 == "YES"

p2b <- ggplot(all_effects) +
  geom_vline(xintercept = 0, linewidth = 0.35, colour = "#777777") +
  geom_hline(yintercept = c(14.5, 7.5), linewidth = 0.3, linetype = "dashed", colour = "#B0B0B0") +
  geom_segment(aes(x = ci95_lower, xend = ci95_upper, y = y, yend = y, colour = arm), linewidth = 0.42) +
  geom_point(aes(x = beta, y = y, colour = arm, fill = bh_pass), shape = 21, size = 1.7, stroke = 0.5) +
  scale_colour_manual(values = arm_colors[c("M01", "M02")], name = "Context") +
  scale_fill_manual(values = c(`TRUE` = "#222222", `FALSE` = "white"), name = "Within-family BH",
                    labels = c(`TRUE` = "Adjusted P < 0.05", `FALSE` = "Adjusted P >= 0.05")) +
  scale_y_continuous(breaks = row_spec$y_base, labels = row_spec$label, expand = expansion(add = 0.65)) +
  scale_x_continuous(limits = c(-2.0, 2.2), breaks = seq(-2, 2, by = 1), expand = expansion(mult = c(0.01, 0.02))) +
  labs(title = "Arm-specific standardized effects",
       subtitle = "Frozen 95% Wald intervals; exploratory families are non-confirmatory",
       x = "Standardized beta (95% CI)", y = NULL) +
  theme_pub() +
  theme(legend.position = "bottom", legend.box = "horizontal") +
  guides(colour = guide_legend(order = 1), fill = guide_legend(order = 2))

F2 <- (p2a / p2b) +
  plot_layout(heights = c(0.78, 1.55)) +
  plot_annotation(tag_levels = "a") & panel_tag_theme

primary$state_order <- match(primary$state_id, sprintf("SP%02d", 1:4))
primary$y_base <- 5 - primary$state_order
primary$y <- primary$y_base + ifelse(primary$arm == "M01", 0.13, -0.13)
primary$bh_pass <- primary$passes_family_bh_0_05 == "YES"

p3a <- ggplot(primary) +
  geom_vline(xintercept = 0, linewidth = 0.35, colour = "#777777") +
  geom_segment(aes(x = ci95_lower, xend = ci95_upper, y = y, yend = y, colour = arm), linewidth = 0.5) +
  geom_point(aes(x = beta, y = y, colour = arm, fill = bh_pass), shape = 21, size = 2.1, stroke = 0.55) +
  scale_colour_manual(values = arm_colors[c("M01", "M02")], name = "Context") +
  scale_fill_manual(values = c(`TRUE` = "#222222", `FALSE` = "white"), guide = "none") +
  scale_y_continuous(breaks = 4:1, labels = unname(state_map[sprintf("SP%02d", 1:4)]), expand = expansion(add = 0.55)) +
  scale_x_continuous(limits = c(-2.0, 2.1), breaks = seq(-2, 2, by = 1)) +
  labs(title = "a  All eight primary-family estimates",
       subtitle = "M01 n = 14 donors; M02 n = 5 donors",
       x = "Standardized beta (95% CI)", y = NULL) +
  theme_pub() +
  theme(legend.position = "bottom")

hero <- primary[primary$program_id == "GP_IBD_GCST004131_V1" & primary$state_id == "SP02", ]
if (nrow(hero) != 2L) stop("Focused GP_IBD-SP02 rows are incomplete", call. = FALSE)
hero$y <- ifelse(hero$arm == "M01", 2, 1)
hero$annotation <- sprintf(
  "beta = %.3f [%.3f, %.3f]\nBH-adjusted P = %s | n = %d",
  hero$beta, hero$ci95_lower, hero$ci95_upper, format_q(hero$bh_adjusted_p), hero$n_complete_donors
)

p3b <- ggplot(hero) +
  geom_vline(xintercept = 0, linewidth = 0.35, colour = "#777777") +
  geom_segment(aes(x = ci95_lower, xend = ci95_upper, y = y, yend = y, colour = arm), linewidth = 0.75) +
  geom_point(aes(x = beta, y = y, colour = arm), size = 2.8) +
  geom_text(aes(x = 0.18, y = y, label = annotation), hjust = 0, size = 2.05,
            lineheight = 0.96, family = "sans", colour = "#222222") +
  annotate("label", x = 1.75, y = 2.65, label = "PORTABILITY_SUPPORTED\nunder the frozen contract",
           size = 2.05, family = "sans", fontface = "bold", linewidth = 0.3,
           fill = "#E8F0F5", colour = "#2F5D7C") +
  scale_colour_manual(values = arm_colors[c("M01", "M02")], guide = "none") +
  scale_y_continuous(breaks = c(2, 1), labels = c("M01 | discovery", "M02 | bounded portability"),
                     limits = c(0.45, 2.85)) +
  scale_x_continuous(limits = c(-1.45, 3.5), breaks = c(-1, 0, 1, 2, 3)) +
  labs(title = "b  Focused GP_IBD-SP02 evidence",
       subtitle = "Negative donor-level expression-score association\nin both contexts",
       x = "Standardized beta (95% CI)", y = NULL,
       caption = "M02 is not independent validation") +
  theme_pub() +
  theme(plot.caption = element_text(size = 5.8, colour = "#4D4D4D", hjust = 0))

F3 <- (p3a | p3b) +
  plot_layout(widths = c(1.0, 1.22))

f4a <- cohorts
f4a$x <- 1:3
f4a$label <- c(
  "M01\nPrimary discovery\nn = 14 donors",
  "M02\nBounded portability\nn = 5 donors\nNot independent validation",
  "M03\nExploratory\nNOT EVALUATED\nNo result mark"
)
p4a <- ggplot(f4a) +
  geom_rect(aes(xmin = x - 0.42, xmax = x + 0.42, ymin = 0.22, ymax = 0.84, fill = analysis_arm_id),
            colour = "#4A4A4A", linewidth = 0.4) +
  geom_text(aes(x = x, y = 0.53, label = label, colour = box_text_colour),
            size = 2.0, lineheight = 0.94, family = "sans") +
  annotate("text", x = 2, y = 0.08, label = "No pooling, validation badge, or rescue path",
           size = 2.0, family = "sans", colour = "#4D4D4D") +
  scale_fill_manual(values = arm_colors, guide = "none") +
  scale_colour_identity() +
  coord_cartesian(xlim = c(0.5, 3.5), ylim = c(0, 1), clip = "off") +
  labs(title = "Evidence roles and failure boundary",
       subtitle = "M01 discovery; M02 bounded portability; M03 not evaluated") +
  theme_schematic()

gene_context <- context[context$gene_symbol != "SP02_AGGREGATE", ]
gene_context$x <- 1:4
gene_context$label <- gene_context$gene_symbol
p4b <- ggplot() +
  geom_rect(data = gene_context, aes(xmin = x - 0.38, xmax = x + 0.38, ymin = 1.55, ymax = 2.15),
            fill = "#E8F0F5", colour = "#2F5D7C", linewidth = 0.4) +
  geom_text(data = gene_context, aes(x = x, y = 1.85, label = label), size = 2.25,
            fontface = "bold", family = "sans") +
  geom_hline(yintercept = 1.35, linewidth = 0.55, colour = "#444444") +
  annotate("rect", xmin = 0.35, xmax = 4.65, ymin = 0.28, ymax = 1.15,
           fill = "#F2F2F2", colour = "#777777", linewidth = 0.35) +
  annotate("text", x = 2.5, y = 0.77,
           label = "LEVEL 2 CONTEXT ONLY\nGastric/pyloric or Brunner-gland-neck-like metaplastic context\nSource-proximal literature; not independent validation",
           size = 1.95, lineheight = 0.96, family = "sans", colour = "#333333") +
  coord_cartesian(xlim = c(0.2, 4.8), ylim = c(0.1, 2.35), clip = "off") +
  labs(title = "Frozen SP02 identity and external context",
       subtitle = "MUC6, BPIFB1, AQP5, and PGC; marker functions were not measured") +
  theme_schematic()

tiers <- data.frame(
  x = 1:3,
  level = c("Level 1", "Level 2", "Level 3"),
  label = c(
    "Direct association\nObserved | estimated\nunder frozen contract",
    "External context\nConsistent with | contextualizes\nnot validation",
    "Future hypotheses only\nCould test | may examine\nnot a current conclusion"
  ),
  fill = c("#2F5D7C", "#C9DCE8", "#E5E5E5"),
  text = c("white", "#222222", "#444444"),
  line = c("solid", "solid", "dashed")
)
p4c <- ggplot() +
  geom_rect(data = tiers, aes(xmin = x - 0.43, xmax = x + 0.43, ymin = 0.2, ymax = 0.82,
                              fill = fill, linetype = line), colour = "#4A4A4A", linewidth = 0.4) +
  geom_text(data = tiers, aes(x = x, y = 0.51, label = paste(level, label, sep = "\n"), colour = text),
            size = 1.9, lineheight = 0.93, family = "sans") +
  annotate("segment", x = 2.5, xend = 2.5, y = 0.05, yend = 0.84,
           linewidth = 0.55, colour = "#B35A4A") +
  annotate("label", x = 2.5, y = 0.94, label = "current-conclusion ceiling", size = 2.0,
           family = "sans", fontface = "bold", colour = "#B35A4A", fill = "white",
           linewidth = 0, label.padding = unit(0.35, "mm")) +
  scale_fill_identity() +
  scale_colour_identity() +
  scale_linetype_identity() +
  coord_cartesian(xlim = c(0.5, 3.5), ylim = c(0.05, 1.02), clip = "off") +
  labs(title = "Evidence ceiling",
       subtitle = "Current conclusions stop at Level 1 association plus Level 2 context") +
  theme_schematic()

F4 <- (p4a / p4b / p4c) +
  plot_layout(heights = c(0.8, 1.08, 0.9)) +
  plot_annotation(tag_levels = "a") & panel_tag_theme

count_long <- cohorts |>
  select(analysis_arm_id, donor_count, sample_count, represented_cell_count) |>
  pivot_longer(cols = c(donor_count, sample_count, represented_cell_count), names_to = "measure", values_to = "value")
count_long$measure <- factor(
  count_long$measure,
  levels = c("donor_count", "sample_count", "represented_cell_count"),
  labels = c("Donors", "Samples", "Represented cells")
)
count_long$analysis_arm_id <- factor(count_long$analysis_arm_id, levels = c("M03", "M02", "M01"))
pSF1a <- ggplot(count_long, aes(x = value, y = analysis_arm_id, colour = analysis_arm_id)) +
  geom_segment(aes(x = 0, xend = value, yend = analysis_arm_id), linewidth = 0.35, colour = "#D0D0D0") +
  geom_point(size = 2.2) +
  geom_text(aes(label = format_int(value)), hjust = 0.5, vjust = -1.0,
            size = 2.0, family = "sans", colour = "#222222", show.legend = FALSE) +
  facet_wrap(~measure, scales = "free_x", nrow = 1) +
  scale_colour_manual(values = arm_colors, guide = "none") +
  scale_x_continuous(expand = expansion(mult = c(0.02, 0.35))) +
  labs(title = "Frozen cohort counts by measurement unit",
       subtitle = "Represented cells are structural counts, not inferential sample size or state abundance",
       x = NULL, y = NULL) +
  theme_pub() +
  theme(strip.background = element_rect(fill = "#F2F2F2", colour = NA), panel.spacing.x = unit(5, "mm"))

scope_map <- c(
  REGISTERED_MATRIX_ALL = "All registered cells",
  M01 = "M01",
  M02 = "M02",
  M03 = "M03"
)
metric_map <- c(
  detected_genes_per_cell = "Detected genes per cell",
  total_counts_per_cell = "Total counts per cell",
  mitochondrial_proportion_per_cell = "Mitochondrial proportion"
)
qc$scope_label <- unname(scope_map[qc$analysis_scope])
qc$y_label <- paste(qc$dataset_identifier, qc$scope_label, sep = " | ")
qc$metric_label <- unname(metric_map[qc$metric])
qc$y_label <- factor(qc$y_label, levels = rev(unique(qc$y_label)))
pSF1b <- ggplot(qc) +
  geom_segment(aes(x = minimum, xend = maximum, y = y_label, yend = y_label), linewidth = 0.35, colour = "#9A9A9A") +
  geom_segment(aes(x = q1, xend = q3, y = y_label, yend = y_label), linewidth = 1.25, colour = "#9FBAD0") +
  geom_point(aes(x = median, y = y_label), shape = 21, fill = "#2F5D7C", colour = "white", size = 2.0, stroke = 0.35) +
  geom_point(aes(x = mean, y = y_label), shape = 21, fill = "white", colour = "#B35A4A", size = 1.65, stroke = 0.55) +
  geom_text(aes(x = maximum, y = y_label, label = paste0("missing=", missing_or_nonfinite_count)),
            hjust = -0.08, size = 1.9, family = "sans", colour = "#4D4D4D") +
  facet_wrap(~metric_label, scales = "free_x", nrow = 1) +
  scale_x_continuous(expand = expansion(mult = c(0.03, 0.32))) +
  labs(title = "Frozen descriptive cell-level summaries",
       subtitle = "Thin line: range; thick line: interquartile range; blue: median; open red: mean",
       x = "Frozen descriptive value", y = NULL,
       caption = "Descriptive only; no filtering, state assignment, or cell-level hypothesis test") +
  theme_pub() +
  theme(strip.background = element_rect(fill = "#F2F2F2", colour = NA),
        panel.spacing.x = unit(5, "mm"), plot.caption = element_text(size = 5.8, hjust = 0, colour = "#4D4D4D"))

SF1 <- (pSF1a / pSF1b) +
  plot_layout(heights = c(0.72, 1.38)) +
  plot_annotation(tag_levels = "a") & panel_tag_theme

state_coverage$state_id <- factor(state_coverage$state_id, levels = sprintf("SP%02d", 1:7))
state_coverage$analysis_arm_id <- factor(state_coverage$analysis_arm_id, levels = c("M03", "M02", "M01"))
state_coverage$cell_label <- sprintf("%d/%d\n%s", state_coverage$mapped_gene_count,
                                     state_coverage$registered_gene_count, state_coverage$coverage_status)
state_coverage$text_colour <- ifelse(state_coverage$coverage_proportion >= 0.95, "white", "#1F1F1F")
pSF2a <- ggplot(state_coverage, aes(x = state_id, y = analysis_arm_id, fill = coverage_proportion)) +
  geom_tile(colour = "white", linewidth = 0.45) +
  geom_text(aes(label = cell_label, colour = text_colour), size = 2.0, lineheight = 0.92, family = "sans") +
  scale_fill_gradient(low = "#E9EFF3", high = "#2F5D7C", limits = c(0.8, 1), name = "Coverage",
                      guide = guide_colourbar(ticks = FALSE)) +
  labs(title = "Frozen epithelial-state coverage",
       subtitle = "Mapped/registered genes and frozen coverage status",
       x = "State", y = "Analysis arm") +
  theme_pub() +
  theme(axis.line = element_blank(), axis.ticks = element_blank(), legend.position = "bottom",
        panel.border = element_rect(fill = NA, linewidth = 0.35)) +
  scale_colour_identity()

program_coverage$program_short <- unname(program_map[program_coverage$program_id])
program_coverage$program_short <- factor(program_coverage$program_short, levels = c("GP_IBD", "GP_CD", "GP_UC"))
program_coverage$dataset_identifier <- factor(program_coverage$dataset_identifier, levels = c("SCP1884", "SCP259"))
program_coverage$cell_label <- sprintf(
  "%d/%d genes\n%d/%d masks\n%s",
  program_coverage$successfully_mapped_genes,
  program_coverage$total_registered_genes,
  program_coverage$state_specific_nonoverlap_masks_passing,
  program_coverage$state_specific_nonoverlap_masks_total,
  program_coverage$full_program_coverage_status
)
program_coverage$text_colour <- ifelse(program_coverage$coverage_proportion >= 0.95, "white", "#1F1F1F")
pSF2b <- ggplot(program_coverage, aes(x = program_short, y = dataset_identifier, fill = coverage_proportion)) +
  geom_tile(colour = "white", linewidth = 0.45) +
  geom_text(aes(label = cell_label, colour = text_colour), size = 1.95, lineheight = 0.92, family = "sans") +
  scale_fill_gradient(low = "#E9EFF3", high = "#2F5D7C", limits = c(0.8, 1), name = "Coverage",
                      guide = guide_colourbar(ticks = FALSE)) +
  labs(title = "Frozen program and non-overlap-mask coverage",
       subtitle = "No gene replacement or reweighting",
       x = "Expression program", y = "Dataset") +
  theme_pub() +
  theme(axis.line = element_blank(), axis.ticks = element_blank(), legend.position = "bottom",
        panel.border = element_rect(fill = NA, linewidth = 0.35)) +
  scale_colour_identity()

SF2 <- (pSF2a | pSF2b) +
  plot_layout(widths = c(1.08, 0.92), guides = "collect") +
  plot_annotation(tag_levels = "a") & panel_tag_theme & theme(legend.position = "bottom")

family_plot <- function(data, family_id, title_text, subtitle_text, show_x = FALSE) {
  subset <- data[data$family == family_id, , drop = FALSE]
  state_levels <- unique(row_spec$state_id[row_spec$family == family_id])
  subset$state_order <- match(subset$state_id, state_levels)
  subset$y_base <- length(state_levels) + 1 - subset$state_order
  subset$y <- subset$y_base + ifelse(subset$arm == "M01", 0.13, -0.13)
  plot <- ggplot(subset) +
    geom_vline(xintercept = 0, linewidth = 0.35, colour = "#777777") +
    geom_segment(aes(x = ci95_lower, xend = ci95_upper, y = y, yend = y, colour = arm), linewidth = 0.45) +
    geom_point(aes(x = beta, y = y, colour = arm), size = 1.8) +
    scale_colour_manual(values = arm_colors[c("M01", "M02")], name = "Context") +
    scale_y_continuous(breaks = rev(seq_along(state_levels)), labels = unname(state_map[state_levels]),
                       expand = expansion(add = 0.5)) +
    scale_x_continuous(limits = c(-2.0, 2.2), breaks = seq(-2, 2, by = 1)) +
    labs(title = title_text, subtitle = subtitle_text,
         x = if (show_x) "Standardized beta (95% CI)" else NULL, y = NULL) +
    theme_pub() +
    theme(legend.position = "bottom")
  if (!show_x) plot <- plot + theme(axis.title.x = element_blank())
  plot
}

pSF3_primary <- family_plot(all_effects, "PRIMARY_8", "a  Primary family (GP_IBD)",
                            "Eight prespecified estimates", show_x = FALSE)
pSF3_cd <- family_plot(all_effects, "E_CD_14", "Exploratory GP_CD family",
                       "Fourteen estimates; non-confirmatory", show_x = FALSE)
pSF3_uc <- family_plot(all_effects, "E_UC_14", "Exploratory GP_UC family",
                       "Fourteen estimates; non-confirmatory", show_x = TRUE)

SF3 <- (pSF3_primary / pSF3_cd / pSF3_uc) +
  plot_layout(heights = c(0.78, 1.18, 1.18), guides = "collect") &
  theme(legend.position = "bottom")

figure_specs <- data.frame(
  Figure = c("F1", "F2", "F3", "F4", "SF1", "SF2", "SF3"),
  `Width mm` = rep(170, 7),
  `Height mm` = c(150, 180, 110, 142, 180, 118, 180),
  `PDF role` = rep("BMC_SUBMISSION_VECTOR_CANDIDATE", 7),
  `SVG role` = rep("EDITABLE_WORKING_DERIVATIVE_NOT_UPLOAD_FORMAT", 7),
  `PNG role` = rep("R_GENERATED_QA_PREVIEW_NOT_SUBMISSION_ASSET", 7),
  check.names = FALSE
)

plots <- list(F1 = F1, F2 = F2, F3 = F3, F4 = F4, SF1 = SF1, SF2 = SF2, SF3 = SF3)
alignment_ids <- list(
  F1 = c("F1A", "F1B", "F1C"),
  F2 = c("F2A", "F2B"),
  F3 = c("F3A", "F3B"),
  F4 = c("F4A", "F4B", "F4C"),
  SF1 = c("SF1A", "SF1B"),
  SF2 = c("SF2A", "SF2B"),
  SF3 = c("SF3A_PRIMARY_STRATUM", "SF3A_E_CD_STRATUM", "SF3A_E_UC_STRATUM")
)

save_figure <- function(figure_id, plot, width_mm, height_mm) {
  width_in <- width_mm / 25.4
  height_in <- height_mm / 25.4
  base <- file.path(figure_dir, figure_id)
  align_layout <- file.path(qa_dir, paste0(figure_id, ".alignment-layout.json"))
  align_report <- file.path(qa_dir, paste0(figure_id, ".alignment.json"))
  align_overlay <- file.path(qa_dir, paste0(figure_id, ".alignment.svg"))
  ids <- alignment_ids[[figure_id]]
  if (length(ids) > 1L) {
    require_patchwork_panel_alignment(
      plot = plot,
      manifest_path = align_layout,
      report_path = align_report,
      width_in = width_in,
      height_in = height_in,
      panel_ids = ids,
      audit_script = alignment_auditor,
      python = python_exe,
      overlay_svg = align_overlay,
      tolerance_pt = 1.5,
      gutter_tolerance_pt = 1.5,
      strict = TRUE
    )
  }

  svglite::svglite(paste0(base, ".svg"), width = width_in, height = height_in,
                   bg = "white")
  print(plot)
  dev.off()

  grDevices::cairo_pdf(paste0(base, ".pdf"), width = width_in, height = height_in,
                       family = "sans", onefile = TRUE, bg = "white")
  print(plot)
  dev.off()

  grDevices::png(file.path(preview_dir, paste0(figure_id, "_preview.png")),
                 width = round(width_in * 300), height = round(height_in * 300),
                 units = "px", res = 300, type = "cairo", bg = "white")
  print(plot)
  dev.off()
}

for (i in seq_len(nrow(figure_specs))) {
  figure_id <- figure_specs$Figure[i]
  message(sprintf("Rendering %s", figure_id))
  save_figure(
    figure_id,
    plots[[figure_id]],
    figure_specs$`Width mm`[i],
    figure_specs$`Height mm`[i]
  )
}

write_tsv(figure_specs, file.path(qa_dir, "C1R_FIGURE_EXPORT_REGISTER.tsv"))

traceability <- bindings
traceability$`Rendering script` <- rel_path(script_path)
traceability$`Output file` <- paste0("figures/", traceability$Figure, ".pdf;figures/", traceability$Figure, ".svg")
traceability$`Preview file` <- paste0("qa/previews/", traceability$Figure, "_preview.png")
traceability$`Render binding status` <- "RENDERED_FROM_VERIFIED_SOURCE"
write_tsv(traceability, file.path(out_root, "C1R_FIGURE_RENDER_TRACEABILITY.tsv"))

manifest_hashes <- c(
  Phase4A = sha256_file(file.path(project_root, "35_PHASE4A_C1R_MANUSCRIPT_EVIDENCE_PACKAGE_FREEZE/C1R_EVIDENCE_PACKAGE_MANIFEST.tsv")),
  Phase4B1 = sha256_file(file.path(project_root, "36_PHASE4B1_C1R_FIGURE_ARCHITECTURE_AND_PANEL_DESIGN_FREEZE/C1R_FIGURE_DESIGN_MANIFEST.tsv")),
  Phase4B2 = sha256_file(file.path(project_root, "37_PHASE4B2_C1R_FIGURE_PRODUCTION_SPECIFICATION_AND_RENDERING_GATE/C1R_PHASE4B2_OUTPUT_MANIFEST.tsv")),
  JournalSelection = sha256_file(file.path(project_root, "38_C1R_TARGET_JOURNAL_SELECTION_AND_FIGURE_REQUIREMENT_ALIGNMENT/C1R_JOURNAL_SELECTION_MANIFEST.tsv"))
)
package_names <- c("R", "ggplot2", "patchwork", "dplyr", "tidyr", "jsonlite", "svglite", "digest")
package_versions <- c(
  R = paste(R.version$major, R.version$minor, sep = "."),
  ggplot2 = as.character(packageVersion("ggplot2")),
  patchwork = as.character(packageVersion("patchwork")),
  dplyr = as.character(packageVersion("dplyr")),
  tidyr = as.character(packageVersion("tidyr")),
  jsonlite = as.character(packageVersion("jsonlite")),
  svglite = as.character(packageVersion("svglite")),
  digest = as.character(packageVersion("digest"))
)
backend_register <- data.frame(
  `Run ID` = "C1R_P4B3_20260915",
  Language = "R",
  Version = R.version.string,
  Platform = R.version$platform,
  Locale = Sys.getlocale(),
  Packages = paste(package_names, collapse = ";"),
  `Package versions` = paste(sprintf("%s=%s", names(package_versions), package_versions), collapse = ";"),
  `Rendering script path` = rel_path(script_path),
  `Rendering script SHA256` = sha256_file(script_path),
  `Input files` = paste(unique(bindings$`Source file`), collapse = ";"),
  `Input manifest SHA256` = paste(sprintf("%s=%s", names(manifest_hashes), manifest_hashes), collapse = ";"),
  `Output files` = paste(c(paste0("figures/", figure_specs$Figure, ".pdf"), paste0("figures/", figure_specs$Figure, ".svg")), collapse = ";"),
  `Font family` = "sans; actual embedded PDF font recorded by final font audit",
  `PDF device` = "grDevices::cairo_pdf",
  `SVG device` = "svglite::svglite",
  `Preview device` = "grDevices::png(type=cairo);QA_ONLY",
  `Backend exclusivity` = "R_ONLY_FOR_DRAWING_PREVIEW_EXPORT;PYTHON_BACKEND_NEUTRAL_AUDIT_ONLY",
  `Target journal` = "BMC Genomics",
  `Policy access date` = "2026-09-15",
  `Execution time` = format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z"),
  check.names = FALSE
)
write_tsv(backend_register, file.path(out_root, "C1R_RENDERING_BACKEND_REGISTER.tsv"))

manual_edit_log <- data.frame(
  `Edit ID` = "NONE",
  Figure = "ALL",
  Panel = "ALL",
  Editor = "NONE",
  Action = "NONE",
  `Scientific data affected` = "NO",
  Status = "NO_MANUAL_EDITS",
  Note = "All scientific and schematic graphics were code-rendered in R; no Illustrator or manual figure editor was used.",
  check.names = FALSE
)
write_tsv(manual_edit_log, file.path(out_root, "C1R_MANUAL_EDIT_LOG.tsv"))

figure_contracts <- data.frame(
  Figure = figure_specs$Figure,
  `Core conclusion` = c(
    "The frozen objects, cohort roles, and donor-level workflow define the bounded C1-R evaluation.",
    "The complete 21-mapping landscape is selective and contains supported, insufficient, discordant, and not-evaluated states.",
    "GP_IBD-SP02 is the decisive primary association across M01 and bounded M02, within the frozen donor-level contract.",
    "Interpretation stops at direct association plus source-proximal context; future mechanisms remain hypotheses.",
    "Cohort and cell-level QC counts delimit data scope without changing the donor-level inferential unit.",
    "All frozen state and program objects meet their recorded structural coverage contracts.",
    "All 36 authorized donor-level model estimates remain visible, including adverse and exploratory evidence."
  ),
  `Results-level question` = c(
    "What objects, contexts, and operations define the evaluation?",
    "How complete and heterogeneous is the frozen evidence landscape?",
    "What is the primary numeric evidence and its small-sample boundary?",
    "What interpretation is supported and where does it stop?",
    "What structural cohort and QC information bounds the analysis?",
    "Were the frozen gene sets structurally represented without substitution?",
    "What is the complete authorized quantitative record?"
  ),
  Archetype = c("schematic-led composite", "asymmetric quantitative grid", "quantitative grid", "schematic-led composite", "quantitative grid", "quantitative grid", "quantitative grid"),
  `Hero panel` = c("F1C", "F2A", "F3B", "F4A", "SF1A", "SF2A", "SF3A"),
  `Final size` = sprintf("170 x %d mm", figure_specs$`Height mm`),
  `Reviewer risk` = c(
    "Expression programs could be mistaken for PRS; donor aggregation and M03 boundary must remain explicit.",
    "Positive-result selection or conflation of not evaluated with negative evidence.",
    "M02 has five donors and is not independent validation; no pooled estimate is allowed.",
    "Source-proximal context could be mistaken for mechanism or validation.",
    "Represented cells could be misread as inferential n or state abundance.",
    "Structural coverage could be mistaken for biological adequacy or association.",
    "Exploratory families could be misread as confirmatory or adverse evidence omitted."
  ),
  check.names = FALSE
)
write_tsv(figure_contracts, file.path(out_root, "C1R_FIGURE_CONTRACTS.tsv"))

source_integrity_post <- source_integrity
for (i in seq_len(nrow(source_integrity_post))) {
  source_path <- file.path(project_root, source_integrity_post$`Source file`[i])
  source_integrity_post$`Observed SHA256`[i] <- if (file.exists(source_path)) sha256_file(source_path) else "NA_MISSING"
  source_integrity_post$`Size bytes`[i] <- if (file.exists(source_path)) file.info(source_path)$size else NA_real_
  source_integrity_post$Status[i] <- if (identical(source_integrity_post$`Observed SHA256`[i], source_integrity_post$`Expected SHA256`[i])) "PASS" else "FAIL"
}
source_integrity_post$`Check stage` <- "POST_RENDER"
write_tsv(source_integrity_post, file.path(qa_dir, "C1R_SOURCE_INTEGRITY_POST_RENDER.tsv"))
if (any(source_integrity_post$Status != "PASS")) {
  stop("Frozen source changed during rendering", call. = FALSE)
}

capture.output(sessionInfo(), file = file.path(log_dir, "R_SESSION_INFO.txt"))
writeLines(
  c(
    "# C1-R Phase 4B-3 rendering log",
    "",
    sprintf("Executed: %s", format(Sys.time(), "%Y-%m-%dT%H:%M:%S%z")),
    "Backend: R only for drawing, preview, and export",
    "Figures rendered: F1-F4 and SF1-SF3",
    "Predecessor manifest rows verified: 42/42",
    sprintf("Panel-source bindings verified pre/post: %d/%d", nrow(bindings), nrow(bindings)),
    "Manual edits: 0",
    "Scientific recalculations or source modifications: 0",
    "Completion pending: PDF/text/collision/font/dimension and inspected-render QA"
  ),
  con = file.path(log_dir, "PHASE4B3_RENDER_EXECUTION_LOG.md"),
  useBytes = TRUE
)

message("R rendering completed; external QA remains required before PASS")
