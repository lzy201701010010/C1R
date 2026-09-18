#!/usr/bin/env python3
"""Audit final PDF dimensions, size, fonts, vector content, and text anchors."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pymupdf as fitz


ROOT = Path(r"D:\SCIfour\39_PHASE4B3_C1R_BMC_GENOMICS_RENDERING_AND_POSITIONING")
FIGURE_DIR = ROOT / "figures"
OUTPUT = ROOT / "qa" / "C1R_PDF_DELIVERY_AUDIT.tsv"

SPECS = {
    "F1": (170.0, 150.0, ["Frozen program and state objects", "M03", "Donor is the inferential unit"]),
    "F2": (170.0, 180.0, ["Complete 21-mapping evidence landscape", "Not evaluated", "GP_IBD | SP02"]),
    "F3": (170.0, 110.0, ["PORTABILITY_SUPPORTED", "beta = -0.776", "M02 is not independent validation"]),
    "F4": (170.0, 142.0, ["MUC6", "BPIFB1", "AQP5", "PGC", "current-conclusion ceiling"]),
    "SF1": (170.0, 180.0, ["43,050", "missing=0", "Descriptive only"]),
    "SF2": (170.0, 118.0, ["3/3", "307/353 genes", "No gene replacement or reweighting"]),
    "SF3": (170.0, 180.0, ["Eight prespecified estimates", "Fourteen estimates; non-confirmatory"]),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    rows: list[dict[str, object]] = []
    for figure, (expected_width, expected_height, anchors) in SPECS.items():
        path = FIGURE_DIR / f"{figure}.pdf"
        document = fitz.open(path)
        try:
            page_count = len(document)
            page = document[0]
            width_mm = page.rect.width * 25.4 / 72.0
            height_mm = page.rect.height * 25.4 / 72.0
            text = "\n".join(page.get_text("text") for page in document)
            anchor_status = [anchor in text for anchor in anchors]
            font_xrefs = sorted({font[0] for page in document for font in page.get_fonts(full=True)})
            embedded = []
            font_names = []
            for xref in font_xrefs:
                name, extension, font_type, content = document.extract_font(xref)
                font_names.append(f"{name}:{extension}:{font_type}")
                embedded.append(bool(content))
            vector_paths = sum(len(page.get_drawings()) for page in document)
            raster_images = sum(len(page.get_images(full=True)) for page in document)
        finally:
            document.close()

        size_bytes = path.stat().st_size
        checks = {
            "one_page": page_count == 1,
            # Cairo stores the media box in whole PostScript points.  A 0.5 mm
            # tolerance covers that deterministic rounding at these sizes.
            "width": abs(width_mm - expected_width) <= 0.5,
            "height": abs(height_mm - expected_height) <= 0.5,
            "max_height": height_mm <= 225.0,
            "size": size_bytes < 10 * 1024 * 1024,
            "fonts": bool(font_xrefs) and all(embedded),
            "text": bool(text.strip()) and all(anchor_status),
            "vector": vector_paths > 0,
        }
        rows.append(
            {
                "Figure": figure,
                "PDF": str(path.relative_to(ROOT)).replace("\\", "/"),
                "SHA256": sha256(path),
                "Pages": page_count,
                "Width_mm": f"{width_mm:.3f}",
                "Expected_width_mm": f"{expected_width:.1f}",
                "Height_mm": f"{height_mm:.3f}",
                "Expected_height_mm": f"{expected_height:.1f}",
                "Dimension_tolerance_mm": "0.5",
                "Size_bytes": size_bytes,
                "Under_10MB": "PASS" if checks["size"] else "FAIL",
                "Font_count": len(font_xrefs),
                "Embedded_font_count": sum(embedded),
                "Fonts": ";".join(font_names),
                "Font_embedding": "PASS" if checks["fonts"] else "FAIL",
                "Extracted_text_characters": len(text),
                "Text_anchors": ";".join(anchors),
                "Text_anchor_check": "PASS" if checks["text"] else "FAIL",
                "Vector_path_count": vector_paths,
                "Raster_image_count": raster_images,
                "Vector_first": "PASS" if checks["vector"] else "FAIL",
                "Verdict": "PASS" if all(checks.values()) else "FAIL",
            }
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    failures = [row["Figure"] for row in rows if row["Verdict"] != "PASS"]
    print(f"PDF delivery audit: {len(rows) - len(failures)}/{len(rows)} PASS")
    if failures:
        print("FAIL: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
