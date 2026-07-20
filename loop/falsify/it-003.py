# -*- coding: utf-8 -*-
"""it-003 firing predicate -- read-only, run by `run_phase.py p3 --iteration 3 --run`.

The proposed change (loop/proposals/it-003.md section 4): OCR the page's embedded-image
regions into core `Word`s -- engine geometry only, at each region's own native scale --
and hand them ONLY to the identity-closing paths (`verified.verify_page`,
`shredded.recover`). No acceptance rule changes; the license is the existing printed-
total-closed-by-arithmetic machinery. This file carries that conduct verbatim; P4
implements exactly this in `core/ocr_words.py` + `core/extract.py`.

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with the injection patched in at exactly the two call sites it will occupy (the
verified/shredded calls inside `extract_document`, which run once per page in page
order, so a per-call counter names the page even for a page whose text word list is
empty) -- and fires iff the emitted field set differs. `conflicts` joins every changed
field against that document's own truth, INCLUDING `expect_absent` / absent-state: an
invented value is exactly as fatal as a wrong one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGET_DOC = "ou_sample_check_stub.pdf"
TARGET_DOC_2 = "osu_sample_earnings_statement.pdf"

CROP_MARGIN_PT = 2.0  # border glyphs must not be clipped; a margin, it gates nothing


# --------------------------------------------------------------------------------------
# the candidate conduct, verbatim (proposal section 4, steps 1-5)
# --------------------------------------------------------------------------------------


def _native_scale(im: dict) -> float | None:
    """px per pt from the region's own placement statement, or None if unstated."""
    sw, sh = im.get("srcsize") or (None, None)
    w_pt = float(im["x1"]) - float(im["x0"])
    h_pt = float(im["bottom"]) - float(im["top"])
    if not sw or not sh or w_pt <= 0 or h_pt <= 0:
        return None
    return max(float(sw) / w_pt, float(sh) / h_pt)


def _intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _regions(plumber_page: Any) -> list[tuple[list[float], float]]:
    """Merged image placements: ([x0, top, x1, bottom] pt, render scale px/pt)."""
    items: list[list[Any]] = []
    for im in plumber_page.images:
        scale = _native_scale(im)
        if scale is None:
            continue
        items.append([[float(im["x0"]), float(im["top"]),
                       float(im["x1"]), float(im["bottom"])], scale])
    changed = True
    while changed:
        changed = False
        out: list[list[Any]] = []
        for rect, scale in items:
            for other in out:
                if _intersects(other[0], rect):
                    o = other[0]
                    other[0] = [min(o[0], rect[0]), min(o[1], rect[1]),
                                max(o[2], rect[2]), max(o[3], rect[3])]
                    other[1] = max(other[1], scale)
                    changed = True
                    break
            else:
                out.append([rect, scale])
        items = out
    items.sort(key=lambda it: (it[0][1], it[0][0]))
    return [(rect, scale) for rect, scale in items]


def _render_region(pdf_source: Any, page_number: int, rect: list[float], scale: float):
    import pypdfium2

    document = (pypdfium2.PdfDocument(bytes(pdf_source))
                if isinstance(pdf_source, (bytes, bytearray))
                else pypdfium2.PdfDocument(str(pdf_source)))
    try:
        page = document[page_number - 1]
        page_w, page_h = float(page.get_width()), float(page.get_height())
        x0 = max(0.0, rect[0] - CROP_MARGIN_PT)
        top = max(0.0, rect[1] - CROP_MARGIN_PT)
        x1 = min(page_w, rect[2] + CROP_MARGIN_PT)
        bottom = min(page_h, rect[3] + CROP_MARGIN_PT)
        if x1 - x0 <= 0 or bottom - top <= 0:
            return None, 0.0, 0.0
        crop = (x0, page_h - bottom, page_w - x1, top)
        image = page.render(scale=scale, crop=crop).to_pil().convert("RGB")
        return image, x0, top
    finally:
        document.close()


def _char_groups(item: Sequence[Any]) -> list[list[tuple[str, Any]]] | None:
    """Chars grouped into words at the ENGINE's own space characters, or None."""
    if len(item) < 6:
        return None
    _, text, _, char_boxes, chars, _ = item[:6]
    if (not isinstance(chars, (list, tuple)) or not isinstance(char_boxes, (list, tuple))
            or len(chars) != len(char_boxes) or not chars):
        return None
    groups: list[list[tuple[str, Any]]] = []
    current: list[tuple[str, Any]] = []
    for ch, box in zip(chars, char_boxes):
        if not str(ch).strip():
            if current:
                groups.append(current)
                current = []
            continue
        current.append((str(ch), box))
    if current:
        groups.append(current)
    joined = "".join(c for g in groups for c, _ in g)
    if joined != "".join(str(text).split()):
        return None  # boxes do not reconcile with the text; caller falls back
    return groups or None


def region_ocr_words(pdf_source: Any, plumber_page: Any, page_number: int,
                     text_words: Sequence[Any]) -> list[Any]:
    import numpy as np

    from core.extract import Word
    from ocr.ocr_extract import _engine, ocr_max_side

    page_h = float(plumber_page.height)
    out: list[Word] = []
    for rect, native in _regions(plumber_page):
        long_side = max(rect[2] - rect[0], rect[3] - rect[1]) + 2 * CROP_MARGIN_PT
        if long_side <= 0:
            continue
        scale = min(native, ocr_max_side() / long_side)
        if scale <= 0:
            continue
        image, x0_pt, top_pt = _render_region(pdf_source, page_number, rect, scale)
        if image is None or image.width < 2 or image.height < 2:
            continue
        result, _ = _engine()(np.array(image), return_word_box=True)
        for item in result or []:
            quad, text = item[0], str(item[1]).strip()
            if not text:
                continue
            pieces: list[tuple[str, float, float, float, float]] = []
            groups = _char_groups(item)
            if groups:
                for group in groups:
                    xs = [float(p[0]) for _, box in group for p in box]
                    ys = [float(p[1]) for _, box in group for p in box]
                    if xs and ys:
                        pieces.append(("".join(c for c, _ in group),
                                       min(xs), max(xs), min(ys), max(ys)))
            else:
                xs = [float(p[0]) for p in quad]
                ys = [float(p[1]) for p in quad]
                pieces.append((text, min(xs), max(xs), min(ys), max(ys)))
            for w_text, px0, px1, py0, py1 in pieces:
                if px1 <= px0 or py1 <= py0:
                    continue
                w_top = page_h - (top_pt + py0 / scale)
                w_bottom = page_h - (top_pt + py1 / scale)
                out.append(Word(
                    text=w_text,
                    x0=round(x0_pt + px0 / scale, 2),
                    x1=round(x0_pt + px1 / scale, 2),
                    baseline=round(w_bottom, 2),
                    glyph_bottom=round(w_bottom, 2),
                    glyph_top=round(w_top, 2),
                    size=round(max((w_top - w_bottom) - 4.0, 1.0), 2),
                    bold=False,
                    page=page_number,
                ))
    if text_words:
        boxes = [(tw.x0, tw.glyph_bottom, tw.x1, tw.glyph_top) for tw in text_words]

        def clashes(w: Any) -> bool:
            return any(not (w.x1 <= bx0 or bx1 <= w.x0
                            or w.glyph_top <= by0 or by1 <= w.glyph_bottom)
                       for bx0, by0, bx1, by1 in boxes)

        out = [w for w in out if not clashes(w)]
    return out


# --------------------------------------------------------------------------------------
# two extractions per document
# --------------------------------------------------------------------------------------

_OCR_MAP_CACHE: dict[str, dict[int, list[Any]]] = {}


def _ocr_map(doc: dict) -> dict[int, list[Any]]:
    if doc["doc"] not in _OCR_MAP_CACHE:
        import pdfplumber

        from core.extract import read_words

        ocr_map: dict[int, list[Any]] = {}
        with pdfplumber.open(str(doc["path"])) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = read_words(page, page_number)
                got = region_ocr_words(doc["path"], page, page_number, words)
                if got:
                    ocr_map[page_number] = got
        _OCR_MAP_CACHE[doc["doc"]] = ocr_map
    return _OCR_MAP_CACHE[doc["doc"]]


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """Every field the extractor emits for this doc, with or without the injection."""
    import core.extract as ex
    import core.shredded as shredded
    import core.verified as verified

    ocr_map = _ocr_map(doc) if with_rule else {}
    original_vp, original_sh = verified.verify_page, shredded.recover
    counters = {"vp": 0, "sh": 0}

    def patched_vp(words, doc_type, found, convention, wanted):
        counters["vp"] += 1
        return original_vp(list(words) + list(ocr_map.get(counters["vp"], [])),
                           doc_type, found, convention, wanted)

    def patched_sh(words, convention, wanted):
        counters["sh"] += 1
        return original_sh(list(words) + list(ocr_map.get(counters["sh"], [])),
                           convention, wanted)

    if ocr_map:
        verified.verify_page, shredded.recover = patched_vp, patched_sh
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
    finally:
        verified.verify_page, shredded.recover = original_vp, original_sh

    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def fires(doc: dict) -> dict | None:
    base = _emissions(doc, with_rule=False)
    ruled = _emissions(doc, with_rule=True)
    if base == ruled:
        return None
    changed = sorted(set(base) ^ set(ruled) | {
        k for k in set(base) & set(ruled) if base[k] != ruled[k]
    })
    return {
        "field": ", ".join(changed),
        "value": {k: {"without_rule": base.get(k), "with_rule": ruled.get(k)}
                  for k in changed},
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ruled[k] for k in changed if k in ruled},
    }


# ------------------------------------------------------------------------------------
# truth join -- design D.1: a firing whose would-be emission contradicts truth, or
# lands on a field truth lists as absent, is a conflict and kills the proposal.
# ------------------------------------------------------------------------------------


def _truth_for(corpus: str, doc_name: str) -> tuple[dict[str, Any], set[str]]:
    if corpus == "pack":
        gold = ROOT / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"
        for line in gold.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["file_name"] == doc_name:
                return {f["field"]: f["value"] for f in record["fields"]}, set()
        return {}, set()
    sources = {
        "uploads": ("testdata/uploads_manifest.json", "intended_fields"),
        "holdout": ("testdata/holdout_manifest.json", "intended_fields"),
        "external": ("testdata/external_truth.json", "expected"),
        "confirm": ("testdata/confirm_truth.json", "expected"),
    }
    rel, key = sources[corpus]
    data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    for record in data["documents"]:
        if record["file_name"] == doc_name:
            return dict(record.get(key, {})), set(record.get("expect_absent", []))
    return {}, set()


def _values_agree(field: str, truth_value: Any, emitted: Any) -> bool:
    """The same comparison the measuring harness makes, imported, not re-invented."""
    from measure_confirm_set import _matches  # type: ignore

    return bool(_matches(field, truth_value, emitted))


def conflicts(fired: list[dict]) -> list[dict]:
    out: list[dict] = []
    for firing in fired:
        if firing["corpus"] == "pack":
            out.append({
                "doc": firing["doc"], "field": firing.get("field"),
                "truth": "pack must never engage-and-fire",
                "rule_would_emit": firing.get("emitted_with_rule"),
            })
            continue
        expected, absent = _truth_for(firing["corpus"], firing["doc"])
        for field, value in (firing.get("emitted_with_rule") or {}).items():
            if field in absent:
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "absent", "rule_would_emit": value})
            elif field in expected and not _values_agree(field, expected[field], value):
                out.append({"doc": firing["doc"], "field": field,
                            "truth": expected[field], "rule_would_emit": value})
            elif field not in expected:
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "not in this document's truth at all",
                            "rule_would_emit": value})
    return out
