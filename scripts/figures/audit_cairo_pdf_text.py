#!/usr/bin/env python3
"""Measure effective text sizes in Cairo PDFs with PyMuPDF.

The nature-figure content-stream audit reads raw ``Tf`` operands.  Cairo uses a
1 pt font operand together with text transformation matrices, so the raw check
systematically reports 1 pt even when the effective rendered size exceeds the
required floor.  This adapter records the effective span sizes from the final
PDF text dictionary.  Raw audit results remain documented in the phase report.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf as fitz


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--min-pt", type=float, default=5.0)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()

    document = fitz.open(args.pdf)
    rows: list[dict[str, object]] = []
    try:
        for page_number, page in enumerate(document, 1):
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = str(span.get("text", "")).strip()
                        if not text:
                            continue
                        rows.append(
                            {
                                "page": page_number,
                                "text": text,
                                "font": span.get("font"),
                                "size_pt": float(span["size"]),
                                "bbox": [float(value) for value in span["bbox"]],
                            }
                        )
    finally:
        document.close()

    below = [row for row in rows if float(row["size_pt"]) + 1e-6 < args.min_pt]
    result = {
        "pdf": str(args.pdf),
        "method": "PYMUPDF_EFFECTIVE_SPAN_SIZE",
        "raw_tf_limitation": (
            "Cairo emits Tf=1 with text transformation matrices; raw Tf alone "
            "does not equal the effective rendered point size."
        ),
        "auditable": bool(rows),
        "minimum_required_pt": args.min_pt,
        "minimum_found_pt": min((float(row["size_pt"]) for row in rows), default=None),
        "maximum_found_pt": max((float(row["size_pt"]) for row in rows), default=None),
        "text_span_count": len(rows),
        "below_minimum_count": len(below),
        "below_minimum": below,
        "verdict": "PASS" if rows and not below else "FIX BEFORE DELIVERY",
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"{args.pdf.name}: {result['verdict']} spans={len(rows)} "
        f"minimum={result['minimum_found_pt']} pt"
    )
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
