"""Fit and verify every constant in ocr_extract.py -- on the READABLE documents only.

The 8 rasterized documents are what this module is scored on, so they are never used to
choose a threshold here. The 16 readable documents give us OCR detections AND gold boxes
for the same pages, which is exactly the supervision needed to calibrate:

  1. the geometry offsets that turn a detection quad into gold's line-box convention, and
  2. the confidence -> certainty thresholds, by measuring recognition accuracy per band.

Run: python ocr/calibrate.py
"""

from __future__ import annotations

import json
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from eval.score_extraction import normalize  # noqa: E402
from ocr.ocr_extract import (  # noqa: E402
    LABEL_LOOKUP,
    VALUE_Y_WINDOW,
    VALUE_X_TOLERANCE,
    _clean_value_text,
    normalize_label,
    read_detections,
)
from core.extract import ParseError, parse_value, infer_document_type  # noqa: E402

GOLD = REPO / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"
DOCS = REPO / "pack" / "synthetic_documents" / "documents"


def label_anchored_pairs(record: dict) -> list[tuple[str, object, object]]:
    """(field, gold_field, detection) for every field we can anchor by label on this page."""
    path = DOCS / record["file_name"]
    doc_type = infer_document_type(path)
    detections = read_detections(path, 1)
    lookup = LABEL_LOOKUP.get(doc_type, {})
    near, far = VALUE_Y_WINDOW

    labels = [
        (lookup[normalize_label(d.text)], d)
        for d in detections
        if normalize_label(d.text) in lookup
    ]
    gold_by_name = {f["field"]: f for f in record["fields"]}

    pairs = []
    seen = set()
    for field_name, label in labels:
        if field_name in seen or field_name not in gold_by_name:
            continue
        column_right = float("inf")
        for _, other in labels:
            if other is not label and abs(other.y0 - label.y0) <= 4.0 and other.x0 > label.x0 + 1.0:
                column_right = min(column_right, other.x0)
        candidates = [
            d
            for d in detections
            if near <= (label.y0 - d.y0) <= far
            and abs(d.x0 - label.x0) <= VALUE_X_TOLERANCE
            and d.x0 < column_right - VALUE_X_TOLERANCE
        ]
        if not candidates:
            continue
        candidates.sort(key=lambda d: label.y0 - d.y0)
        seen.add(field_name)
        pairs.append((field_name, gold_by_name[field_name], candidates[0]))
    return pairs


def is_correct(field_name: str, detection, gold_field: dict) -> bool:
    """Would this detection have produced the gold value, under the eval scorer's rules?"""
    try:
        value, _ = parse_value(field_name, _clean_value_text(field_name, detection.text))
    except ParseError:
        return False
    return normalize(field_name, value) == normalize(field_name, gold_field.get("value"))


def main() -> int:
    gold = [json.loads(line) for line in GOLD.open(encoding="utf-8") if line.strip()]
    readable = [r for r in gold if not r.get("rasterized")]
    print(f"calibrating on {len(readable)} readable documents "
          f"({sum(len(r['fields']) for r in readable)} gold fields)\n")

    pairs = []
    for record in readable:
        pairs.extend(label_anchored_pairs(record))
    print(f"label-anchored detections: {len(pairs)}\n")

    # --- geometry ---------------------------------------------------------------------
    correct = [(f, g, d) for f, g, d in pairs if is_correct(f, d, g)]
    dx0 = [g["bbox"][0] - d.x0 for _, g, d in correct]
    dy0 = [g["bbox"][1] - d.y0 for _, g, d in correct]
    wide = [(g, d) for _, g, d in correct if g["bbox"][2] - g["bbox"][0] > 24.5]
    dw = [g["bbox"][2] - g["bbox"][0] - (d.x1 - d.x0) for g, d in wide]

    print("GEOMETRY (fitted on correctly-read detections)")
    print(f"  X_OFFSET        mean {st.mean(dx0):+.3f}  sd {st.pstdev(dx0):.3f}  n={len(dx0)}")
    print(f"  BASELINE_Y_OFF  mean {st.mean(dy0):+.3f}  sd {st.pstdev(dy0):.3f}  n={len(dy0)}")
    print(f"  WIDTH_PAD       mean {st.mean(dw):+.3f}  sd {st.pstdev(dw):.3f}  n={len(dw)}")

    heights = {}
    for _, g, d in correct:
        heights.setdefault(round(g["bbox"][3] - g["bbox"][1]), []).append(d.y1 - d.y0)
    print("  gold box height -> detection height range (why size is not guessed):")
    for h in sorted(heights):
        v = heights[h]
        print(f"    gold h={h}: n={len(v)} detection h {min(v):.2f}..{max(v):.2f}")

    # --- confidence bands -------------------------------------------------------------
    bands = [(0.99, 1.01), (0.95, 0.99), (0.90, 0.95), (0.80, 0.90), (0.0, 0.80)]
    print("\nCONFIDENCE BANDS (recognition accuracy vs gold)")
    for lo, hi in bands:
        band = [(f, g, d) for f, g, d in pairs if lo <= d.confidence < hi]
        if not band:
            print(f"  [{lo:.2f}, {hi:.2f}) : n=0")
            continue
        ok = sum(1 for f, g, d in band if is_correct(f, d, g))
        print(f"  [{lo:.2f}, {hi:.2f}) : {ok}/{len(band)} correct = {ok / len(band):6.1%}")
        for f, g, d in band:
            if not is_correct(f, d, g):
                print(f"        MISREAD {f}: read {d.text!r} want {g.get('value')!r} "
                      f"conf={d.confidence:.3f}")

    total_ok = sum(1 for f, g, d in pairs if is_correct(f, d, g))
    print(f"\n  overall: {total_ok}/{len(pairs)} = {total_ok / len(pairs):.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
