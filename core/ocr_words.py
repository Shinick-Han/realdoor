# -*- coding: utf-8 -*-
"""Words read by OCR out of a page's embedded-image regions, for the identity paths only.

WHY THIS EXISTS
---------------
Four of the confirm documents are hybrids: a prose text layer with the actual pay stub
embedded as a raster image. Their values exist only in pixels, so the text path
correctly abstains -- and the existing `ocr/ocr_extract.py` never runs on them, because
it is a caller-routed, page-1-only, pack-geometry-fitted path for fully rasterized
documents. This module recovers the pixels as ordinary `core.extract.Word`s so that the
EXISTING acceptance machinery can rule on them. It adds no acceptance rule of its own.

THE LICENSE, STATED ONCE
------------------------
An OCR-read word may serve as an operand, but it may only be *emitted* as a field value
by an identity-closing path (`core.verified`, `core.shredded`): the page's own printed
arithmetic must close over it. `extract_document` enforces that structurally -- injected
words are appended to the page's word list ONLY for the verified/shredded calls; the
label/column/header-cell value paths never see them, so no adjacency rule can ever emit
an OCR reading. Confidence gates nothing here: an illegible scan's garbage detections
are refused because nothing closes over them, not because a threshold said so
(`loop/proposals/it-003.md`, falsified over all 77 corpus documents first --
`loop/falsification/it-003.json`).

THE ONE RULE WE DO NOT BEND (inherited from ocr/ocr_extract.py)
---------------------------------------------------------------
Geometry comes from the OCR engine's own detections, never from a layout guess. Word
granularity uses the engine's per-character boxes (`return_word_box=True`) grouped at
the engine's own space characters; a detection whose character boxes do not reconcile
with its text falls back to one Word per detection quad. Nothing is ever split
proportionally. None of `ocr/ocr_extract.py`'s pack-fitted box constants
(BASELINE_Y_OFFSET, X_OFFSET, WIDTH_PAD, NOMINAL_FONT_SIZE, VALUE_Y_WINDOW) are used:
they carry pack-generator provenance by their own comments, and confirm scoring has no
IoU leg -- engine-quad boxes are correct and sufficient.

RENDER SCALE IS THE PAGE'S OWN STATEMENT
----------------------------------------
Each region is rasterised at its native resolution -- max(source_px / placed_pt) per
axis, i.e. the resolution the PDF itself embeds -- not at a fitted render constant. The
only cap is the OCR engine's existing input cap (`REALDOOR_OCR_MAX_SIDE`, already part
of the extraction cache key): pixels beyond it would be discarded by the engine's own
resize anyway. Only the region is rendered (pypdfium2 crop render), so peak memory is
bounded by that cap by construction.

TWO STRUCTURAL GUARDS
---------------------
* Region merge: intersecting image placements are unioned before OCR (keeping the max
  native scale), so a stub and its backing frame -- or two overlapping stub instances,
  as on hi_ags page 2 -- can never be OCR'd twice into one word stream and double a
  number into a column sum.
* Overlap drop: an OCR word whose box intersects any text-layer word's glyph box on the
  same page is dropped. The page's printed words take precedence; a scanned duplicate
  of printed text can never enter the arithmetic beside its original.

`REALDOOR_OCR_WORDS=0` means `extract_document` never imports this module and its
output is byte-identical to the tree without it (gate G5's contract).
"""
from __future__ import annotations

from typing import Any, Sequence

#: Rendering margin around a region so border glyphs are not clipped by the crop. A
#: margin only -- it widens what the engine may see and gates nothing.
CROP_MARGIN_PT = 2.0


def _native_scale(im: dict) -> float | None:
    """px per pt from the region's own placement statement, or None if unstated.

    `srcsize` is the embedded bitmap's pixel size; the placement rect is where the page
    puts it. Their ratio is the resolution the document itself chose per axis; the max
    is taken so a non-uniformly stretched placement (ou: 197x165 dpi) is not
    undersampled on either axis.
    """
    sw, sh = im.get("srcsize") or (None, None)
    w_pt = float(im["x1"]) - float(im["x0"])
    h_pt = float(im["bottom"]) - float(im["top"])
    if not sw or not sh or w_pt <= 0 or h_pt <= 0:
        return None
    return max(float(sw) / w_pt, float(sh) / h_pt)


def _intersects(a: list[float], b: list[float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def regions(plumber_page: Any) -> list[tuple[list[float], float]]:
    """Merged image placements of one page: ([x0, top, x1, bottom] pt, scale px/pt).

    Placements that intersect are unioned to a fixpoint (see the module docstring's
    first structural guard); the merged region renders at the max member scale. Sorted
    by position so the injected word order is deterministic.
    """
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
        merged: list[list[Any]] = []
        for rect, scale in items:
            for other in merged:
                if _intersects(other[0], rect):
                    o = other[0]
                    other[0] = [min(o[0], rect[0]), min(o[1], rect[1]),
                                max(o[2], rect[2]), max(o[3], rect[3])]
                    other[1] = max(other[1], scale)
                    changed = True
                    break
            else:
                merged.append([rect, scale])
        items = merged
    items.sort(key=lambda it: (it[0][1], it[0][0]))
    return [(rect, scale) for rect, scale in items]


def _render_region(pdf_source: Any, page_number: int, rect: list[float], scale: float):
    """Rasterise ONE region at `scale` px/pt. Returns (PIL image, x0_pt, top_pt).

    pypdfium2's crop render cuts the page down to the region before rasterising, so the
    bitmap allocated is the region's, not the page's -- the memory bound of the module
    docstring. The returned origin is the page point the bitmap's (0,0) pixel maps to.
    """
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
        crop = (x0, page_h - bottom, page_w - x1, top)  # cut: left, bottom, right, top
        image = page.render(scale=scale, crop=crop).to_pil().convert("RGB")
        return image, x0, top
    finally:
        document.close()


def _char_groups(item: Sequence[Any]) -> list[list[tuple[str, Any]]] | None:
    """One detection's characters grouped into words at the ENGINE's own spaces.

    Returns None when the engine's per-character output does not reconcile with the
    detection's text (spaces removed) -- the caller then falls back to one Word per
    detection quad rather than guessing a segmentation.
    """
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
        return None
    return groups or None


def drop_overlapping(ocr_words: list[Any], text_words: Sequence[Any]) -> list[Any]:
    """The overlap guard: printed words take precedence over their scanned duplicates."""
    if not text_words:
        return ocr_words
    boxes = [(tw.x0, tw.glyph_bottom, tw.x1, tw.glyph_top) for tw in text_words]

    def clashes(w: Any) -> bool:
        return any(not (w.x1 <= bx0 or bx1 <= w.x0
                        or w.glyph_top <= by0 or by1 <= w.glyph_bottom)
                   for bx0, by0, bx1, by1 in boxes)

    return [w for w in ocr_words if not clashes(w)]


def region_ocr_words(
    pdf_source: Any,
    plumber_page: Any,
    page_number: int,
    text_words: Sequence[Any],
) -> list[Any]:
    """OCR every embedded-image region of one page into `Word`s, guards applied.

    `pdf_source` is a path or raw bytes (an upload held in memory); `plumber_page` is
    the already-open pdfplumber page (region discovery reads its `images`);
    `text_words` are the page's own printed words, which the overlap guard protects.
    """
    import numpy as np

    from core.extract import Word
    from ocr.ocr_extract import _engine, ocr_max_side

    page_h = float(plumber_page.height)
    out: list[Word] = []
    for rect, native in regions(plumber_page):
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
                    baseline=round(w_bottom, 2),  # the quad bottom; see module docstring
                    glyph_bottom=round(w_bottom, 2),
                    glyph_top=round(w_top, 2),
                    size=round(max((w_top - w_bottom) - 4.0, 1.0), 2),
                    bold=False,
                    page=page_number,
                ))
    return drop_overlapping(out, text_words)
