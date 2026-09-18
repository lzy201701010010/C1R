#!/usr/bin/env python3
"""Run the nature-figure collision rules with Cairo-safe text boxes.

R's cairo_pdf device can place many spatially disjoint labels in one
``get_texttrace()`` record.  The upstream nature-figure extractor unions such
traces with otherwise tight PDF lines, creating page-wide boxes and systematic
false text/text and text/stroke failures.  This adapter retains the upstream
geometry rules and thresholds but supplies tight line-level boxes from
PyMuPDF's text dictionary and excludes large white-on-white panel-background
strokes that have no visible collision.  It records the upstream raw result
separately; this normalized audit is only valid together with final-size
visual review.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pymupdf as fitz


def load_upstream(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("nature_collision", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load upstream collision auditor: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def extract_cairo_safe_geometry(pdf_path: Path, audit: Any) -> list[Any]:
    document = fitz.open(pdf_path)
    pages: list[Any] = []
    try:
        for page_index, page in enumerate(document, 1):
            geometry = audit.PageGeometry(
                page=page_index,
                bbox=audit.normalize_rect(tuple(page.rect)),
            )

            text_index = 0
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = [span for span in line.get("spans", []) if span.get("text", "").strip()]
                    if not spans:
                        continue
                    bbox = audit.union_rects(audit.normalize_rect(span["bbox"]) for span in spans)
                    if bbox is None:
                        continue
                    text = "".join(span.get("text", "") for span in spans).strip()
                    geometry.texts.append(audit.TextBox(index=text_index, text=text, bbox=bbox))
                    geometry.traces.append(audit.TraceBox(index=text_index, text=text, bbox=bbox))
                    text_index += 1

            for drawing_index, drawing in enumerate(page.get_drawings()):
                drawing_type = str(drawing.get("type", ""))
                drawing_bbox = audit.normalize_rect(tuple(drawing["rect"]))
                stroke_color = drawing.get("color")
                is_white_large_background_stroke = (
                    stroke_color is not None
                    and all(abs(float(channel) - 1.0) < 1e-9 for channel in stroke_color)
                    and audit.rect_area(drawing_bbox) / max(audit.rect_area(geometry.bbox), 1.0) >= 0.01
                )
                if (
                    "s" in drawing_type
                    and drawing.get("stroke_opacity", 1.0) not in (None, 0)
                    and not is_white_large_background_stroke
                ):
                    segments = audit._segments_from_items(drawing.get("items", ()))
                    if segments:
                        geometry.strokes.append(
                            audit.StrokePath(
                                index=drawing_index,
                                bbox=drawing_bbox,
                                width=float(drawing.get("width") or 0.0),
                                segments=segments,
                            )
                        )
                if "f" in drawing_type and drawing.get("fill_opacity", 1.0) not in (None, 0):
                    rectangle_items = [
                        item for item in drawing.get("items", ()) if item and item[0] == "re"
                    ]
                    if rectangle_items:
                        for offset, item in enumerate(rectangle_items):
                            geometry.fills.append(
                                audit.FilledRegion(
                                    index=drawing_index * 1000 + offset,
                                    bbox=audit.normalize_rect(tuple(item[1])),
                                    source="fill",
                                )
                            )
                    else:
                        geometry.fills.append(
                            audit.FilledRegion(index=drawing_index, bbox=drawing_bbox, source="fill")
                        )

            image_index = 0
            seen_images: set[tuple[int, int, int, int]] = set()
            for image in page.get_images(full=True):
                for image_rect in page.get_image_rects(int(image[0])):
                    bbox = audit.normalize_rect(tuple(image_rect))
                    key = tuple(round(value * 10) for value in bbox)
                    if key in seen_images:
                        continue
                    seen_images.add(key)
                    geometry.images.append(
                        audit.FilledRegion(index=image_index, bbox=bbox, source="image")
                    )
                    image_index += 1
            pages.append(geometry)
    finally:
        document.close()
    return pages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--overlay-pdf", type=Path, required=True)
    parser.add_argument("--text-inset-pt", type=float, default=0.6)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.05)
    parser.add_argument("--clipping-tolerance-pt", type=float, default=0.5)
    args = parser.parse_args()

    audit = load_upstream(args.upstream)
    pages = extract_cairo_safe_geometry(args.pdf, audit)
    result = {
        "pdf": str(args.pdf),
        "extractor": "CAIRO_SAFE_LINE_LEVEL_TEXT_DICTIONARY",
        "upstream_rule_source": str(args.upstream),
        "rationale": (
            "R cairo_pdf groups spatially disjoint labels into broad text traces; "
            "tight line-level boxes prevent trace-union false positives, and large "
            "white-on-white panel-background strokes are non-visible."
        ),
        **audit.audit_geometries(
            pages,
            text_inset_pt=args.text_inset_pt,
            min_overlap_ratio=args.min_overlap_ratio,
            clipping_tolerance_pt=args.clipping_tolerance_pt,
        ),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    audit.write_overlay_pdf(args.pdf, args.overlay_pdf, result["findings"])
    print(
        f"{args.pdf.name}: {result['verdict']} "
        f"fail={result['summary']['fail']} warn={result['summary']['warn']}"
    )
    return audit.exit_code(result, strict=False)


if __name__ == "__main__":
    raise SystemExit(main())
