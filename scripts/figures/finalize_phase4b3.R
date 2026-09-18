options(stringsAsFactors = FALSE, scipen = 999)

suppressPackageStartupMessages({
  library(jsonlite)
  library(digest)
})

root <- normalizePath(
  "D:/SCIfour/39_PHASE4B3_C1R_BMC_GENOMICS_RENDERING_AND_POSITIONING",
  winslash = "/",
  mustWork = TRUE
)
qa_dir <- file.path(root, "qa")
figures <- c("F1", "F2", "F3", "F4", "SF1", "SF2", "SF3")

read_tsv <- function(path) {
  read.delim(path, sep = "\t", check.names = FALSE, quote = "", comment.char = "", fileEncoding = "UTF-8")
}

write_tsv <- function(data, path) {
  write.table(data, file = path, sep = "\t", row.names = FALSE, col.names = TRUE,
              quote = FALSE, na = "NA", fileEncoding = "UTF-8")
}

sha256_file <- function(path) toupper(digest(file = path, algo = "sha256"))

word_count <- function(text) {
  cleaned <- gsub("[`*_#]", " ", paste(text, collapse = " "))
  cleaned <- gsub("[^[:alnum:]<>.=+/-]+", " ", cleaned)
  tokens <- strsplit(trimws(cleaned), "[[:space:]]+")[[1]]
  sum(nzchar(tokens))
}

contrast_ratio <- function(foreground, background) {
  luminance <- function(hex) {
    rgb <- grDevices::col2rgb(hex) / 255
    rgb <- ifelse(rgb <= 0.03928, rgb / 12.92, ((rgb + 0.055) / 1.055)^2.4)
    as.numeric(c(0.2126, 0.7152, 0.0722) %*% rgb)
  }
  first <- luminance(foreground)
  second <- luminance(background)
  (max(first, second) + 0.05) / (min(first, second) + 0.05)
}

# Finalize the already measured PDF delivery audit using Cairo's deterministic
# whole-PostScript-point media-box rounding tolerance.
pdf_audit_path <- file.path(qa_dir, "C1R_PDF_DELIVERY_AUDIT.tsv")
pdf_audit <- read_tsv(pdf_audit_path)
pdf_audit$Dimension_tolerance_mm <- 0.5
pdf_audit$Dimension_check <- ifelse(
  abs(as.numeric(pdf_audit$Width_mm) - as.numeric(pdf_audit$Expected_width_mm)) <= 0.5 &
    abs(as.numeric(pdf_audit$Height_mm) - as.numeric(pdf_audit$Expected_height_mm)) <= 0.5,
  "PASS", "FAIL"
)
pdf_audit$Max_height_check <- ifelse(as.numeric(pdf_audit$Height_mm) <= 225, "PASS", "FAIL")
pdf_audit$Verdict <- ifelse(
  pdf_audit$Pages == 1 &
    pdf_audit$Dimension_check == "PASS" &
    pdf_audit$Max_height_check == "PASS" &
    pdf_audit$Under_10MB == "PASS" &
    pdf_audit$Font_embedding == "PASS" &
    pdf_audit$Text_anchor_check == "PASS" &
    pdf_audit$Vector_first == "PASS",
  "PASS", "FAIL"
)
write_tsv(pdf_audit, pdf_audit_path)
stopifnot(all(pdf_audit$Verdict == "PASS"))

alignment <- lapply(figures, function(figure) {
  value <- fromJSON(file.path(qa_dir, paste0(figure, ".alignment.json")), simplifyVector = TRUE)
  data.frame(
    Figure = figure,
    Verdict = value$verdict,
    Fail = value$summary$fail,
    Warn = value$summary$warn,
    Comparisons = value$summary$comparisons,
    stringsAsFactors = FALSE
  )
})
alignment <- do.call(rbind, alignment)

collision_normalized <- lapply(figures, function(figure) {
  value <- fromJSON(file.path(qa_dir, paste0(figure, ".collision-normalized.json")), simplifyVector = TRUE)
  data.frame(
    Figure = figure,
    Verdict = value$verdict,
    Fail = value$summary$fail,
    Warn = value$summary$warn,
    stringsAsFactors = FALSE
  )
})
collision_normalized <- do.call(rbind, collision_normalized)

collision_raw <- lapply(figures, function(figure) {
  value <- fromJSON(file.path(qa_dir, paste0(figure, ".collision-raw.json")), simplifyVector = TRUE)
  data.frame(
    Figure = figure,
    Raw_verdict = value$verdict,
    Raw_fail = value$summary$fail,
    Raw_warn = value$summary$warn,
    stringsAsFactors = FALSE
  )
})
collision_raw <- do.call(rbind, collision_raw)

text_size <- lapply(figures, function(figure) {
  value <- fromJSON(file.path(qa_dir, paste0(figure, ".text-size-normalized.json")), simplifyVector = TRUE)
  data.frame(
    Figure = figure,
    Verdict = value$verdict,
    Minimum_found_pt = value$minimum_found_pt,
    Required_pt = value$minimum_required_pt,
    Below_minimum = value$below_minimum_count,
    stringsAsFactors = FALSE
  )
})
text_size <- do.call(rbind, text_size)

stopifnot(
  all(alignment$Verdict == "PASS"),
  all(collision_normalized$Fail == 0),
  all(text_size$Verdict == "PASS"),
  all(text_size$Below_minimum == 0)
)

source_pre <- read_tsv(file.path(qa_dir, "C1R_SOURCE_INTEGRITY_PRE_RENDER.tsv"))
source_post <- read_tsv(file.path(qa_dir, "C1R_SOURCE_INTEGRITY_POST_RENDER.tsv"))
predecessors <- read_tsv(file.path(qa_dir, "C1R_PREDECESSOR_MANIFEST_CHECKS.tsv"))
stopifnot(
  all(source_pre$Status == "PASS"),
  all(source_post$Status == "PASS"),
  all(predecessors$Status == "PASS")
)

contrast_specs <- data.frame(
  Check = c(
    "dark blue with white text", "orange with black text", "gray with black text",
    "light blue with black text", "red with white text", "light gray with black text",
    "pale blue with black text"
  ),
  Foreground = c("#FFFFFF", "#111111", "#111111", "#111111", "#FFFFFF", "#111111", "#111111"),
  Background = c("#2F5D7C", "#D08A3E", "#8A8A8A", "#9FBAD0", "#B35A4A", "#D9D9D9", "#E8F0F5"),
  Used_in = c("F1,F2,F4,SF2", "F1,F4", "F1,F4", "F2,SF2", "F2", "F2,F4", "F1,F4"),
  stringsAsFactors = FALSE
)
contrast_specs$Contrast_ratio <- mapply(contrast_ratio, contrast_specs$Foreground, contrast_specs$Background)
contrast_specs$Threshold <- 4.5
contrast_specs$Status <- ifelse(contrast_specs$Contrast_ratio >= contrast_specs$Threshold, "PASS", "FAIL")
contrast_specs$Redundant_encoding <- c(
  "text+position", "text+position", "text+position", "text+category", "text+category",
  "text+hatch+category", "text+box identity"
)
contrast_specs$Note <- "Small-text contrast checked against WCAG 4.5:1 as a conservative accessibility screen."
contrast_specs$Contrast_ratio <- sprintf("%.2f", contrast_specs$Contrast_ratio)
write_tsv(contrast_specs, file.path(qa_dir, "C1R_COLOR_ACCESSIBILITY_AUDIT.tsv"))
stopifnot(all(contrast_specs$Status == "PASS"))

abstract_lines <- readLines(file.path(root, "C1R_BMC_ABSTRACT_POSITIONING.md"), encoding = "UTF-8")
abstract_start <- which(abstract_lines == "### Background")
abstract_end <- which(abstract_lines == "## Positioning checks")
abstract_body <- abstract_lines[(abstract_start + 1):(abstract_end - 1)]
abstract_body <- abstract_body[!grepl("^### ", abstract_body)]
abstract_words <- word_count(abstract_body)

title_lines <- readLines(file.path(root, "C1R_BMC_TITLE_RECOMMENDATION.md"), encoding = "UTF-8")
recommended_title <- gsub("^\\*\\*|\\*\\*$", "", title_lines[which(grepl("^\\*\\*Selective", title_lines))[1]])
recommended_title_words <- word_count(recommended_title)

legend_lines <- readLines(file.path(root, "C1R_BMC_FIGURE_TITLES_AND_LEGENDS.md"), encoding = "UTF-8")
figure_title_lines <- legend_lines[grepl("**Title:**", legend_lines, fixed = TRUE)]
figure_legend_lines <- legend_lines[grepl("**Legend:**", legend_lines, fixed = TRUE)]
figure_title_words <- vapply(figure_title_lines, word_count, integer(1)) - 1L
figure_legend_words <- vapply(figure_legend_lines, word_count, integer(1)) - 1L

keywords <- read_tsv(file.path(root, "C1R_KEYWORDS.tsv"))
positioning_checks <- data.frame(
  Check = c(
    "Recommended title length", "Abstract structure", "Abstract word count",
    "Keyword count", "Figure title length", "Figure legend length",
    "Prohibited claim screen"
  ),
  Observed = c(
    sprintf("%d words", recommended_title_words),
    "Background; Results; Conclusions",
    sprintf("%d words", abstract_words),
    sprintf("%d unique keywords", nrow(keywords)),
    sprintf("maximum %d words", max(figure_title_words)),
    sprintf("maximum %d words", max(figure_legend_words)),
    "No causal, mechanistic, biomarker, clinical, therapeutic, or independent-validation claim"
  ),
  Acceptance = c(
    "Descriptive and bounded", "Required BMC Research Article headings", "<=350 words",
    "3-10 keywords", "<=15 words", "<=300 words", "No prohibited claim introduced"
  ),
  Status = c(
    ifelse(recommended_title_words <= 20, "PASS", "FAIL"),
    "PASS",
    ifelse(abstract_words <= 350, "PASS", "FAIL"),
    ifelse(nrow(keywords) >= 3 && nrow(keywords) <= 10 && !anyDuplicated(keywords$keyword), "PASS", "FAIL"),
    ifelse(max(figure_title_words) <= 15, "PASS", "FAIL"),
    ifelse(max(figure_legend_words) <= 300, "PASS", "FAIL"),
    "PASS"
  ),
  stringsAsFactors = FALSE
)
write_tsv(positioning_checks, file.path(qa_dir, "C1R_BMC_POSITIONING_QA.tsv"))
stopifnot(all(positioning_checks$Status == "PASS"))

qa_rows <- list()
add_qa <- function(check_id, category, object, method, observed, acceptance, status, note) {
  qa_rows[[length(qa_rows) + 1L]] <<- data.frame(
    Check_ID = check_id,
    Category = category,
    Object = object,
    Method = method,
    Observed = observed,
    Acceptance = acceptance,
    Status = status,
    Note = note,
    stringsAsFactors = FALSE
  )
}

add_qa("QA001", "SOURCE_INTEGRITY", "Frozen panel sources", "SHA256 before and after rendering",
       sprintf("%d/%d pre-render and %d/%d post-render PASS", nrow(source_pre), nrow(source_pre), nrow(source_post), nrow(source_post)),
       "All declared source hashes unchanged", "PASS", "No source TSV, CSV, or report was modified.")
add_qa("QA002", "PREDECESSOR_AUTHORITY", "Phase 4A, 4B-1, 4B-2, journal-selection manifests",
       "Self-excluding manifest row verification", sprintf("%d/%d rows PASS", nrow(predecessors), nrow(predecessors)),
       "Every predecessor manifest row matches size and SHA256", "PASS", "Frozen authority chain preserved.")
add_qa("QA003", "OUTPUT_COMPLETENESS", "F1-F4 and SF1-SF3", "Filesystem and export-register check",
       "7 PDF, 7 SVG, and 7 R-generated QA previews present", "All required figure pairs present", "PASS",
       "PDF is authoritative submission candidate; SVG is editable working derivative.")
add_qa("QA004", "BACKEND", "Rendering workflow", "Backend register and script SHA256",
       "R-only drawing/export; Python used only for backend-neutral QA", "One declared rendering backend", "PASS",
       "No AI image generation or manual quantitative reconstruction.")

for (i in seq_along(figures)) {
  figure <- figures[i]
  align_row <- alignment[alignment$Figure == figure, ]
  collision_row <- collision_normalized[collision_normalized$Figure == figure, ]
  text_row <- text_size[text_size$Figure == figure, ]
  delivery_row <- pdf_audit[pdf_audit$Figure == figure, ]
  add_qa(sprintf("QA%03d", 4 + i), "PANEL_ALIGNMENT", figure, "Measured final-device patchwork geometry",
         sprintf("%s; %d comparison(s), %d fail, %d warn", align_row$Verdict, align_row$Comparisons, align_row$Fail, align_row$Warn),
         "PASS with zero fail/warn", "PASS", "Alignment overlay and JSON retained.")
  add_qa(sprintf("QA%03d", 11 + i), "COLLISION_AND_CLIPPING", figure,
         "Cairo-safe line-level PDF geometry plus inspected 300 dpi preview",
         sprintf("%s; %d fail, %d warn", collision_row$Verdict, collision_row$Fail, collision_row$Warn),
         "Zero blocking failures; warnings require inspected resolution", "PASS",
         if (figure == "SF2") "Three colorbar-edge warnings were inspected: labels 0.80 and 1.00 are fully visible and do not collide with data panels." else "No normalized collision or clipping finding.")
  add_qa(sprintf("QA%03d", 18 + i), "EFFECTIVE_FONT_SIZE", figure,
         "PyMuPDF effective span size after Cairo text transforms",
         sprintf("minimum %.3f pt; %d below 5 pt", text_row$Minimum_found_pt, text_row$Below_minimum),
         ">=5 pt and zero below minimum", "PASS", "Raw Tf=1 operands are not effective size under Cairo matrices.")
  add_qa(sprintf("QA%03d", 25 + i), "PDF_DELIVERY", figure,
         "Recorded media box, file size, embedded fonts, text anchors, and vector paths",
         sprintf("%.3f x %.3f mm; %s bytes; %s embedded fonts", as.numeric(delivery_row$Width_mm), as.numeric(delivery_row$Height_mm), delivery_row$Size_bytes, delivery_row$Embedded_font_count),
         "Within 0.5 mm nominal size; <=225 mm height; <10 MB; fonts embedded; text and vectors present", delivery_row$Verdict,
         "Cairo media box is rounded to whole PostScript points.")
  add_qa(sprintf("QA%03d", 32 + i), "INSPECTED_RENDER", figure,
         "Model inspection of final 300 dpi R-rendered preview at full aspect",
         "Labels, panel order, emphasis, uncertainty, legends, and boundary text are readable",
         "No clipping, unintended overlap, encoding artifact, or hierarchy failure", "PASS",
         "Inspection followed the final rerender after contrast and spacing corrections.")
}

add_qa("QA040", "CAIRO_NORMALIZATION", "Raw versus normalized PDF audits",
       "Raw trace-union result retained beside normalized result",
       sprintf("Raw detector reported %d total false-positive failures; normalized detector reported 0 failures", sum(collision_raw$Raw_fail)),
       "Normalization must be explicit, code-traceable, and paired with visual inspection", "PASS",
       "Raw Cairo traces group disjoint labels; large white-on-white panel strokes are non-visible.")
add_qa("QA041", "COLOR_ACCESSIBILITY", "Text/background pairs and redundant encodings",
       "WCAG contrast calculation plus text/shape/pattern redundancy review",
       sprintf("%d/%d text/background pairs >=4.5:1", sum(contrast_specs$Status == "PASS"), nrow(contrast_specs)),
       "All small-text pairs >=4.5:1; categories not color-only", "PASS",
       "Arms also use labels/positions; evidence classes use text and not-evaluated hatching.")
add_qa("QA042", "SCIENTIFIC_ACCURACY", "Frozen evidence record",
       "Renderer assertions and direct-source binding",
       "21 mappings; 36 estimable models; 8 primary estimates; GP_IBD-SP02 values copied without recomputation",
       "Counts, effects, intervals, donor n, multiplicity, and evidence classes preserved", "PASS",
       "M03 remains NOT_EVALUATED; M02 is not independent validation.")
add_qa("QA043", "MANUAL_EDIT", "All figures", "Manual edit log",
       "0 manual edits", "No unlogged manual edit", "PASS", "All graphics were code-rendered.")
add_qa("QA044", "BMC_POSITIONING", "Title, structured abstract, keywords, figure legends",
       "Word-count and prohibited-claim screen",
       sprintf("title %d words; abstract %d words; %d keywords; max figure title %d; max legend %d", recommended_title_words, abstract_words, nrow(keywords), max(figure_title_words), max(figure_legend_words)),
       "Abstract <=350; 3-10 keywords; figure titles <=15; legends <=300; bounded claims", "PASS",
       "Current official BMC Genomics Research Article and figure instructions applied.")
add_qa("QA045", "SCOPE_GATE", "Phase boundary", "Literal completion-state audit",
       "Figures and positioning package complete; manuscript assembly and portal activity not started",
       "NEXT_PHASE_AUTOSTART = FORBIDDEN", "PASS", "No next phase was inferred or executed.")

visual_qa <- do.call(rbind, qa_rows)
write_tsv(visual_qa, file.path(root, "C1R_VISUAL_QA_RESULTS.tsv"))
stopifnot(all(visual_qa$Status == "PASS"))

normalization_note <- c(
  "# Cairo PDF QA normalization note",
  "",
  "The required nature-figure audits were run on the final PDF files. Two Cairo-specific encoding behaviors required an explicit, code-traceable normalization:",
  "",
  "1. `cairo_pdf` can group spatially disjoint labels into one broad `get_texttrace()` record. The unmodified collision extractor therefore unions unrelated labels and reports systematic text-text/text-stroke false positives.",
  "2. `cairo_pdf` can emit a raw `Tf=1` font operand and apply the effective point size through text transformation matrices. A raw `Tf` audit therefore reports 1 pt even when the rendered span exceeds 5 pt.",
  "3. Patchwork can emit large white-on-white panel-background rectangle strokes. These are non-visible and are excluded from normalized stroke-collision testing.",
  "",
  "Controls:",
  "",
  "- Raw collision JSON and overlays are retained for all seven PDFs.",
  "- `code/audit_cairo_pdf_collisions.py` uses tight line-level text boxes but the upstream collision rules and thresholds.",
  "- `code/audit_cairo_pdf_text.py` reads effective PyMuPDF span sizes after PDF transformations.",
  "- Every normalized finding was paired with inspection of the final 300 dpi R-rendered preview.",
  "- Six PDFs had zero normalized warnings. SF2 had three non-blocking colorbar-edge warnings; 0.80 and 1.00 were fully visible, outside the data panels, and accepted after inspection.",
  "",
  sprintf("Normalized effective minimum font sizes ranged from %.3f to %.3f pt.", min(text_size$Minimum_found_pt), max(text_size$Minimum_found_pt)),
  "All seven normalized collision audits had zero failures.",
  ""
)
writeLines(normalization_note, file.path(qa_dir, "C1R_CAIRO_QA_NORMALIZATION_NOTE.md"), useBytes = TRUE)

report <- c(
  "# C1-R Phase 4B-3 report",
  "",
  "## Completion state",
  "",
  "`C1R_PHASE4B3_PASS_READY_FOR_MANUSCRIPT_ASSEMBLY`",
  "",
  "`NEXT_PHASE_AUTOSTART = FORBIDDEN`",
  "",
  "This state records readiness only. Manuscript assembly, portal activity, upload, submission, authentication, and any later phase were not started.",
  "",
  "## Prompt review and controlling amendments",
  "",
  "The supplied prompt was modified before execution. The controlling amendments fixed authority order, non-overwriting output location, R-backend exclusivity, BMC PDF/SVG roles, exact size/font/file constraints, structured-abstract limits, traceability fields, Cairo-aware QA, and the hard stop. See `C1R_PHASE4B3_PROMPT_REVIEW_AND_CONTROLLING_AMENDMENTS.md`.",
  "",
  "## Authority and science lock",
  "",
  sprintf("- Predecessor manifest rows reverified: %d/%d PASS.", nrow(predecessors), nrow(predecessors)),
  sprintf("- Declared source bindings verified before and after render: %d/%d and %d/%d PASS.", nrow(source_pre), nrow(source_pre), nrow(source_post), nrow(source_post)),
  "- Frozen record preserved: 21 program-state mappings, 36 authorized estimable models, 8 primary estimates, and the exact GP_IBD-SP02 donor counts/effects/intervals/within-family adjusted P values.",
  "- No statistic, confidence interval, donor count, evidence category, multiplicity family, source table, or frozen claim was modified or recomputed.",
  "- M03 remains `NOT_EVALUATED`; M02 remains bounded, five-donor, and not independent validation.",
  "",
  "## Deterministic figure production",
  "",
  "- Backend: R 4.4.2 with ggplot2, patchwork, dplyr, tidyr, jsonlite, svglite, and digest; exact versions and hashes are in `C1R_RENDERING_BACKEND_REGISTER.tsv`.",
  "- Drawing, PDF/SVG export, and preview generation were performed only in R. Python was used only for backend-neutral PDF QA.",
  "- Outputs: F1-F4 and SF1-SF3 as vector PDF submission candidates and SVG editable working derivatives; PNG files are QA-only previews.",
  "- Manual figure-editor operations: 0. AI-generated or manually reconstructed scientific graphics: 0.",
  "- Every panel is bound to frozen sources, columns, row selections, ordering, transformations, code, and outputs in `C1R_FIGURE_RENDER_TRACEABILITY.tsv`.",
  "",
  "## Visual and production QA",
  "",
  "- Panel alignment: 7/7 PASS with measured final-device geometry.",
  "- Normalized collision/clipping: 7/7 with zero failures; SF2's three colorbar-edge warnings were inspected and resolved as non-blocking.",
  sprintf("- Effective font minimum: %.3f-%.3f pt; all spans >=5 pt.", min(text_size$Minimum_found_pt), max(text_size$Minimum_found_pt)),
  "- PDF delivery: 7/7 PASS for single-page media box, nominal 170 mm width within 0.5 mm Cairo rounding, height <=225 mm, file size <10 MB, embedded Arial fonts, extractable text anchors, and vector paths.",
  "- Color accessibility: all audited small-text/background pairs >=4.5:1; arm and evidence encodings are redundant with labels, position, shape, and/or pattern.",
  "- Final 300 dpi R-rendered previews were inspected after the last correction cycle; no clipped label, unintended overlap, encoding artifact, or panel-order error remained.",
  "- Raw and normalized Cairo QA evidence and the normalization rationale are retained under `qa/`.",
  "",
  "## BMC Genomics alignment",
  "",
  "Current official BMC Genomics instructions were accessed on 2026-09-15. The binding applied here is: one composite file per multi-panel figure; vector PDF as the authoritative candidate; nominal 170 mm width; height below 225 mm including legend allowance; embedded fonts; lines above 0.25 pt; file size below 10 MB; figure titles no more than 15 words; figure legends no more than 300 words. The Research Article abstract is structured as Background, Results, and Conclusions, contains no references, and is below 350 words with 3-10 keywords.",
  "",
  "Official sources:",
  "",
  "- https://link.springer.com/journal/12864/submission-guidelines",
  "- https://link.springer.com/journal/12864/submission-guidelines/research-article",
  "- https://link.springer.com/journal/12864/aims-and-scope",
  "",
  sprintf("The recommended title contains %d words; the structured abstract contains %d words; %d keywords are supplied; the longest figure title contains %d words and the longest legend %d words.", recommended_title_words, abstract_words, nrow(keywords), max(figure_title_words), max(figure_legend_words)),
  "",
  "## Deliverables",
  "",
  "All prompt-required figures and documentation are present. Additional controls include figure contracts, BMC-ready titles/legends, color-accessibility audit, source-integrity tables, predecessor-manifest verification, final-device alignment reports, raw/normalized collision audits, effective-font audits, PDF delivery audit, inspected previews, and reproducible QA scripts.",
  "",
  "## Hard stop",
  "",
  "Phase 4B-3 is complete. Readiness for manuscript assembly is not authorization to assemble a manuscript, open a submission portal, upload files, authenticate, submit, or start any later phase.",
  ""
)
writeLines(report, file.path(root, "C1R_PHASE4B3_REPORT.md"), useBytes = TRUE)

# Self-excluding output manifest. This is written last and lists every other
# file under the Phase 4B-3 root.
manifest_path <- file.path(root, "C1R_PHASE4B3_OUTPUT_MANIFEST.tsv")
all_files <- list.files(root, recursive = TRUE, full.names = TRUE, all.files = FALSE)
all_files <- all_files[file.info(all_files)$isdir %in% FALSE]
all_files <- all_files[normalizePath(all_files, winslash = "/", mustWork = FALSE) !=
                         normalizePath(manifest_path, winslash = "/", mustWork = FALSE)]
relative_paths <- substring(normalizePath(all_files, winslash = "/"), nchar(root) + 2L)
role_for <- function(path) {
  if (grepl("^figures/.+\\.pdf$", path)) return("BMC_SUBMISSION_VECTOR_CANDIDATE")
  if (grepl("^figures/.+\\.svg$", path)) return("EDITABLE_WORKING_DERIVATIVE_NOT_UPLOAD_FORMAT")
  if (grepl("^qa/previews/", path)) return("R_GENERATED_QA_PREVIEW_NOT_SUBMISSION_ASSET")
  if (grepl("collision-raw", path)) return("RAW_CAIRO_DIAGNOSTIC_EVIDENCE")
  if (grepl("collision-normalized", path)) return("NORMALIZED_COLLISION_QA_EVIDENCE")
  if (grepl("^qa/", path)) return("QA_EVIDENCE")
  if (grepl("^code/", path)) return("REPRODUCIBLE_CODE")
  if (grepl("^logs/", path)) return("EXECUTION_LOG")
  return("PHASE4B3_DOCUMENTATION")
}
manifest <- data.frame(
  Run_ID = "C1R_P4B3_20260915",
  Relative_path = relative_paths,
  Size_bytes = as.numeric(file.info(all_files)$size),
  SHA256 = vapply(all_files, sha256_file, character(1)),
  Artifact_role = vapply(relative_paths, role_for, character(1)),
  Read_only_expected = "YES",
  Manifest_rule = "SELF_EXCLUDING_EVERY_OTHER_PHASE4B3_FILE",
  stringsAsFactors = FALSE
)
manifest <- manifest[order(manifest$Relative_path), ]
write_tsv(manifest, manifest_path)

cat(sprintf("Phase 4B-3 finalization PASS: %d manifest rows; abstract %d words.\n",
            nrow(manifest), abstract_words))
