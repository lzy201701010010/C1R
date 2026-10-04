# Portable adaptation of frozen EV2A drawing: no fitting or rescoring.
# Usage: Rscript render_sf4_from_reconstructed_scores.R DONOR_TSV RESULT_TSV OUTPUT_PREFIX
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 3L) stop("Expected donor TSV, frozen aggregate result TSV, output prefix")
donor_path <- args[[1]]
result_path <- args[[2]]
stem <- args[[3]]
if (!file.exists(donor_path) || !file.exists(result_path)) stop("Input file missing")
dir.create(dirname(stem), recursive=TRUE, showWarnings=FALSE)
d <- read.delim(donor_path, check.names=FALSE, stringsAsFactors=FALSE)
r <- read.delim(result_path, check.names=FALSE, stringsAsFactors=FALSE)
stopifnot(nrow(d)==18L, length(unique(d$PatientID))==18L, nrow(r)==1L,
          sum(d$contributing_samples)==19L, sum(d$contributing_cells)==15989L,
          identical(r$classification[[1]], "EXTERNAL_REPLICATION_SUPPORTED"),
          all(is.finite(d$GP_IBD_score)), all(is.finite(d$SP02_score)))
# Conversion of the frozen standardized model line to raw-score coordinates.
xbar <- mean(d$GP_IBD_score)
ybar <- mean(d$SP02_score)
raw_slope <- r$beta[[1]] * (r$outcome_sd[[1]] / r$predictor_sd[[1]])
line_x <- seq(min(d$GP_IBD_score), max(d$GP_IBD_score), length.out=101L)
line_y <- ybar + raw_slope * (line_x - xbar)
source_data <- data.frame(source_row_1based=seq_len(nrow(d)),
                          PatientID=d$PatientID,
                          GP_IBD_score=d$GP_IBD_score,
                          SP02_score=d$SP02_score)
options(digits=17)
write.table(source_data, paste0(stem,"_POINTS_LOCAL_ONLY.tsv"), sep="\t",
            row.names=FALSE, quote=FALSE)
width_mm <- 170
height_mm <- 125
dpi <- 600
donor_colour <- "#377A98"
line_colour <- "#3A4148"
text_colour <- "#202B33"
xlim <- c(0.5095,0.5282)
ylim <- c(0.439,0.485)
stopifnot(all(d$GP_IBD_score > xlim[1] & d$GP_IBD_score < xlim[2]),
          all(d$SP02_score > ylim[1] & d$SP02_score < ylim[2]))
draw_figure <- function() {
  par(family="sans", mar=c(5.2,5.5,7.3,1.2), mgp=c(3,0.8,0))
  plot(d$GP_IBD_score, d$SP02_score, type="n", xlim=xlim, ylim=ylim,
       xlab="Donor-level GP_IBD score (SP02 non-overlap mask)",
       ylab="Donor-level SP02 / INFLARE score", xaxt="n", yaxt="n",
       bty="l", col.axis=text_colour, col.lab=text_colour)
  axis(1, at=c(0.510,0.515,0.520,0.525), col=text_colour, col.axis=text_colour)
  axis(2, at=c(0.44,0.45,0.46,0.47,0.48), las=1,
       col=text_colour, col.axis=text_colour)
  lines(line_x, line_y, col=line_colour, lwd=1.2)
  points(d$GP_IBD_score, d$SP02_score, pch=21, bg=donor_colour,
         col="white", cex=0.85, lwd=0.5)
  mtext("External validation in GSE266546", side=3, line=5.7,
        adj=0, font=2, cex=1.1, col=text_colour)
  mtext("Active Crohn disease; ascending-colon endoscopic biopsies", side=3,
        line=4.4, adj=0, cex=0.85, col="#515D66")
  mtext("n = 18 donors     Standardized beta = -0.873", side=3,
        line=3.0, adj=0, cex=0.9, col=text_colour)
  mtext("95% CI [-1.116, -0.630]     P = 1.84 x 10^-12", side=3,
        line=1.7, adj=0, cex=0.9, col=text_colour)
}
grDevices::cairo_pdf(paste0(stem,".pdf"),
                     width=round(width_mm/25.4*72)/72,
                     height=round(height_mm/25.4*72)/72,
                     family="sans",onefile=TRUE)
draw_figure(); dev.off()
grDevices::png(paste0(stem,".png"),width=width_mm,height=height_mm,
               units="mm",res=dpi,type="cairo",bg="white")
draw_figure(); dev.off()
cat("SF4_RECONSTRUCTED: 18 points; no model fit\n")

