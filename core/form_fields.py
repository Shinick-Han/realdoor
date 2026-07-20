# -*- coding: utf-8 -*-
"""Values typed into a PDF's interactive form widgets, read as ordinary printed `Word`s.

WHY THIS EXISTS
---------------
pdfplumber reads the page *content stream*. A value typed into an AcroForm text field
does not live there: it lives in a widget annotation, and its glyphs live in that
annotation's appearance stream. So a properly filled interactive form -- the thing a
renter gets when they download an agency form, type into it and upload it -- reads
BLANK to us. Measured, not assumed:
`testdata/filled/wa_dshs_14252_employment_verification_filled.pdf` carries 17 filled
text widgets (name "Terrence Boyd", current-month gross "1,283.15") and
`page.extract_text()` contains neither string; all 7 of its expected fields abstain.

This is not a corner case. Of the 11 real blank forms collected from public agencies
(`testdata/blank_carriers_raw/carriers_manifest.json`) 7 are AcroForms.

This module recovers those values as ordinary `core.extract.Word`s so the EXISTING
field machinery rules on them. It adds no acceptance rule of its own -- the same shape
`core/ocr_words.py` established for pixels.

THE LICENSE, STATED ONCE
------------------------
A widget value is **what the page prints**. Print the filled form on paper and the
value is on the paper, in a specific place, in a specific font -- that is the whole of
the house rule's requirement, and it is why these words are full citizens here where
`core/ocr_words.py`'s are not. OCR words are a *guess at* what the page prints and are
therefore confined to identity-closing paths; a widget value is the page's own typed
statement of its glyphs and their positions, so it may be bound by the ordinary printed
-label rules exactly as drawn text is.

What is NOT licensed, and is not used anywhere below: the widget's internal field NAME.
This document's names are seductive -- `EMPLOYEES NAME`, `AVERAGE HOURS PER WEEK`,
`RATE OF PAY OR SALARY HOURLY DAILY OR PIECE RATE` -- and binding values by them would
"work" on this carrier immediately. It is refused. An internal name is not printed on
the page; it is an authoring artefact that no rule may rest on, it varies per carrier
with no vocabulary anyone controls (`Text12` is as legal as `EMPLOYEES NAME`), and a
name that is merely *stale* -- a field duplicated and retitled in the form editor --
binds a real value to the wrong field with an exact coordinate attached, which is the
most convincing kind of wrong. Only `/V` and the widget's geometry are read. If the
page does not print a label the ordinary rules can bind, the value is not read, and
that abstention is the correct answer.

GEOMETRY COMES FROM THE SAME READER AS PRINTED TEXT
---------------------------------------------------
The naive implementation takes the widget's `/Rect` as the value's box. That is wrong
and it is wrong in the dangerous direction: the rect is the *field's* box, not the
*text's*. On the filled carrier `EMPLOYEES NAME` has a 210.7 x 21.5pt rect holding
"Terrence Boyd", which typesets to 71.6 x 12pt inside it -- a value box three times too
wide, on a baseline nobody measured, with a size nobody read. Every downstream rule is
geometric. Feeding it a fabricated box is a layout guess in the exact sense
`core/ocr_words.py` refuses.

So instead: each filled widget's appearance stream (`/AP /N`) is drawn onto a derived
copy of its page at the position PDF 32000-1 12.5.5 puts it (the form's `/BBox` through
its `/Matrix`, fitted to `/Rect`) -- the identical construction a viewer performs to
display it -- and that derived page is read by **`core.extract.read_words`**, the same
function, through the same pdfminer, under the same watermark filter. Fonts, advance
widths, text matrices and baselines are then resolved by the engine that resolves them
for printed text. Nothing is estimated: no character width, no baseline, no size.

The AcroForm's `/DR` default resources are merged under each appearance form's own
`/Resources` before the read, because a filled widget's appearance routinely names a
font (`/Helv`, `/TiRo`) that only `/DR` defines. Without it pdfminer resolves no font
and every word comes back **zero-width** -- silently, with correct text. That failure
was observed before this module existed and is why `/DR` is merged rather than trusted
to be absent.

APPEARANCE STREAMS AND THE DOUBLE-READ QUESTION
-----------------------------------------------
Every filled text widget on the corpus carrier has an appearance stream with the value
baked into it as a `Tj`. Today that can never be double-read: pdfplumber does not
descend into annotation appearance streams, proven by the blank `extract_text()` above.
But a form that has been **flattened** -- appearances merged into the content stream,
widgets sometimes left behind -- would print the value and carry it in `/V`, and reading
both would put the same number on the page twice, which is how a column sum doubles. So
a guard is required, and `_drop_double_read` below is it.

It is NOT `core.ocr_words.drop_overlapping`, and the difference was forced by
measurement. That guard drops a word whose glyph box intersects any printed word's at
all, which is right for OCR quads -- they are tight boxes around ink. A typeset glyph
box is an em box: it carries the font's full ascent and descent whether or not the
glyphs use them, so on a tightly-set government form the boxes of ADJACENT LINES graze.
Applied here it silently deleted five of the filled carrier's seventeen values,
including the two the iteration exists for -- `$17.10 hourly` (em box overlapping the
printed caption `DAILY OR PIECE RATE)` one line above it by 1.4pt, 7% of its area) and
`1,283.15` (against `CURRENT MONTH:`). Adjacency is not duplication.

The criterion is therefore what a double-read actually is: **the same string printed at
the same place.** A derived word is dropped when a printed word on its page carries an
equal string and their boxes intersect, or when a printed word covers at least half the
derived word's box area -- co-location so heavy it is duplication whatever the strings
say. On the corpus the first leg fires only on genuinely flattened input and the second
never fires at all (the worst real adjacency measures 0.075). Both legs are structural
and refusal-biased; neither is a tuned threshold standing between a value and a field.

WHAT IS DELIBERATELY NOT READ
------------------------------
* **Checkboxes and radio buttons** (`/FT /Btn`). They carry on/off states, not text;
  their appearances are ZapfDingbats glyphs (a "4" that draws a checkmark), which would
  enter the word stream as a numeral. Nothing is emitted for them this iteration. The
  filled carrier has 10 of them, including `Every two weeks` = `/On` -- which is a real
  `pay_frequency` statement this module cannot make. Filed, not smuggled.
* **Choice and signature fields** (`/FT /Ch`, `/Sig`): out of scope for the same reason
  -- no corpus instance carries a value, so nothing here is falsifiable against them.
* **Rotated pages.** A widget's appearance may itself be rotated relative to its page
  (`/MK /R`), independently of `/Rotate`. No corpus document combines a non-zero
  `/Rotate` with an AcroForm -- the one rotated document, `il_dol_day_labor_wage_notice
  _sample.pdf` (confirm, `/Rotate 90`), has no form fields at all -- so the composition
  is unfalsifiable here. Pages with non-zero `/Rotate` emit nothing.

`REALDOOR_FORM_FIELDS=0` means `core.extract` never imports this module and its output
is byte-identical to the tree without it (gate G5's contract).
"""
from __future__ import annotations

from typing import Any

#: Field types whose `/V` is text a page prints. Everything else emits nothing; see the
#: module docstring's "what is deliberately not read".
TEXT_FIELD_TYPES = ("/Tx",)


def _resolve(node: Any) -> Any:
    """Follow an indirect reference, if that is what this is."""
    getter = getattr(node, "get_object", None)
    return getter() if getter is not None else node


def _inherited(widget: Any, key: str, depth: int = 8) -> Any:
    """A field attribute, which may sit on the widget or on any ancestor field.

    `/V` and `/FT` are inheritable through the field tree (PDF 32000-1 12.7.3.1): a
    widget that is a kid of a named field carries neither itself. Walking is depth-
    bounded so a malformed document with a parent cycle cannot hang the extractor.
    """
    node = _resolve(widget)
    for _ in range(depth):
        if node is None:
            return None
        if key in node:
            return _resolve(node[key])
        node = _resolve(node.get("/Parent"))
    return None


def _placement(rect: list[float], bbox: list[float], matrix: list[float]):
    """The `cm` that puts an appearance form where the viewer puts it.

    PDF 32000-1 12.5.5: transform `/BBox` by `/Matrix`, take the result's bounding box,
    and map that box onto `/Rect` by scale-and-translate. Returns (sx, sy, tx, ty), or
    None when either box is degenerate and no mapping is defined.
    """
    rx0, rx1 = sorted((float(rect[0]), float(rect[2])))
    ry0, ry1 = sorted((float(rect[1]), float(rect[3])))
    a, b, c, d, e, f = (float(v) for v in matrix)
    corners = [(float(bbox[0]), float(bbox[1])), (float(bbox[2]), float(bbox[1])),
               (float(bbox[2]), float(bbox[3])), (float(bbox[0]), float(bbox[3]))]
    xs = [a * x + c * y + e for x, y in corners]
    ys = [b * x + d * y + f for x, y in corners]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    if bw <= 0 or bh <= 0 or rx1 - rx0 <= 0 or ry1 - ry0 <= 0:
        return None
    sx, sy = (rx1 - rx0) / bw, (ry1 - ry0) / bh
    return sx, sy, rx0 - min(xs) * sx, ry0 - min(ys) * sy


def has_form_values(pdf_source: Any) -> bool:
    """Whether any page carries a text widget with a non-empty value.

    The cheap gate: a document with no AcroForm, or a blank one (every real blank form
    in the corpus -- ext_nydol, ext_va, the unfilled wa_dshs), never builds a derived
    document and never reaches pdfplumber a second time.
    """
    try:
        return bool(_filled_widgets_exist(pdf_source))
    except Exception:
        return False


def _open_reader(pdf_source: Any):
    import io

    from pypdf import PdfReader

    if isinstance(pdf_source, (bytes, bytearray)):
        return PdfReader(io.BytesIO(bytes(pdf_source)))
    return PdfReader(str(pdf_source))


def _filled_widgets_exist(pdf_source: Any) -> bool:
    reader = _open_reader(pdf_source)
    root = reader.trailer.get("/Root")
    root = _resolve(root) if root is not None else None
    if root is None or "/AcroForm" not in root:
        return False
    for page in reader.pages:
        for widget in _resolve(page.get("/Annots")) or []:
            widget = _resolve(widget)
            if widget is None or widget.get("/Subtype") != "/Widget":
                continue
            if str(_inherited(widget, "/FT")) not in TEXT_FIELD_TYPES:
                continue
            value = _inherited(widget, "/V")
            if value is not None and str(value).strip():
                return True
    return False


def _derived_document(pdf_source: Any) -> bytes | None:
    """A copy of the document whose pages PRINT their filled text widgets, and nothing else.

    Each page keeps its size and loses its content, its annotations and its own
    resources; what is drawn is exactly the appearance streams of its filled text
    widgets, each at the place PDF 12.5.5 puts it. Reading this document therefore
    yields the widget values and cannot yield anything already on the original page --
    the two word sets are disjoint by construction, and `drop_overlapping` then handles
    the flattened-form case where they should not have been.

    Returns None when nothing would be drawn.
    """
    import io

    from pypdf import PdfWriter
    from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                               IndirectObject, NameObject, NumberObject)

    writer = PdfWriter(clone_from=(io.BytesIO(bytes(pdf_source))
                                   if isinstance(pdf_source, (bytes, bytearray))
                                   else str(pdf_source)))
    acroform = _resolve(writer._root_object.get("/AcroForm"))
    defaults = _resolve(acroform.get("/DR")) if acroform else None
    drawn_any = False

    for page in writer.pages:
        widgets = _resolve(page.get("/Annots")) or []
        operators: list[str] = []
        xobjects = DictionaryObject()
        # A page whose display is rotated: refused whole, see the module docstring.
        rotated = int(_resolve(page.get("/Rotate")) or 0) % 360 != 0
        for widget in ([] if rotated else widgets):
            reference = widget
            widget = _resolve(widget)
            if widget is None or widget.get("/Subtype") != "/Widget":
                continue
            if str(_inherited(widget, "/FT")) not in TEXT_FIELD_TYPES:
                continue
            value = _inherited(widget, "/V")
            if value is None or not str(value).strip():
                continue
            appearance = _resolve(widget.get("/AP"))
            # The RAW entry, not the resolved one: a form XObject is a stream, and a
            # stream may only appear as an indirect object. Inlining the resolved
            # dictionary into `/Resources` writes a direct stream -- a file pypdf reads
            # back happily and pdfminer refuses whole, reporting zero pages. Observed.
            normal_ref = appearance.raw_get("/N") if appearance and "/N" in appearance else None
            normal = _resolve(normal_ref)
            # A dictionary of per-state appearances is a button's shape, not a text
            # field's; a text field with no appearance stream has no glyphs to read.
            if normal is None or "/BBox" not in normal:
                continue
            rect = _resolve(widget.get("/Rect"))
            if rect is None or len(rect) != 4:
                continue
            placed = _placement([float(v) for v in rect],
                                [float(v) for v in _resolve(normal["/BBox"])],
                                [float(v) for v in
                                 (_resolve(normal.get("/Matrix")) or [1, 0, 0, 1, 0, 0])])
            if placed is None:
                continue
            _merge_defaults(normal, defaults)
            name = NameObject(f"/RDFF{len(operators)}")
            xobjects[name] = (normal_ref if isinstance(normal_ref, IndirectObject)
                              else writer._add_object(normal))
            sx, sy, tx, ty = placed
            operators.append(f"q {sx:.6f} 0 0 {sy:.6f} {tx:.4f} {ty:.4f} cm {name} Do Q")

        resources = DictionaryObject()
        if operators:
            resources[NameObject("/XObject")] = xobjects
            drawn_any = True
        page[NameObject("/Resources")] = resources
        page[NameObject("/Annots")] = ArrayObject()
        page[NameObject("/Rotate")] = NumberObject(0)
        stream = DecodedStreamObject()
        stream.set_data("\n".join(operators).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(stream)

    if not drawn_any:
        return None
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _merge_defaults(form: Any, defaults: Any) -> None:
    """Put the AcroForm `/DR` under an appearance form's own `/Resources`.

    Under, never over: a resource the appearance names itself wins. Without this the
    engine resolves no font and returns correct text at zero width -- see the module
    docstring.
    """
    from pypdf.generic import DictionaryObject, NameObject

    if not defaults:
        return
    own = _resolve(form.get("/Resources")) or DictionaryObject()
    merged = DictionaryObject()
    for key, value in defaults.items():
        merged[NameObject(key)] = value
    for key, value in own.items():
        if key == "/Font" and "/Font" in merged:
            fonts = DictionaryObject()
            for sub, entry in _resolve(merged["/Font"]).items():
                fonts[NameObject(sub)] = entry
            for sub, entry in _resolve(value).items():
                fonts[NameObject(sub)] = entry
            merged[NameObject("/Font")] = fonts
        else:
            merged[NameObject(key)] = value
    form[NameObject("/Resources")] = merged


#: Fraction of a derived word's box a single printed word must cover for the read to be
#: called duplication regardless of what either string says. See the module docstring:
#: the heaviest real adjacency on the corpus measures 0.075, so this leg is dormant
#: there and exists for flatteners that re-typeset rather than copy.
COVERAGE_IS_DUPLICATION = 0.5


def _drop_double_read(derived: list[Any], printed: Any) -> list[Any]:
    """The flattened-form guard: printed text wins over its own duplicate. See docstring."""
    boxes = [(w.x0, w.glyph_bottom, w.x1, w.glyph_top, w.text) for w in printed]
    if not boxes:
        return derived

    def duplicated(word: Any) -> bool:
        area = max(word.x1 - word.x0, 0.0) * max(word.glyph_top - word.glyph_bottom, 0.0)
        for bx0, by0, bx1, by1, text in boxes:
            overlap_x = min(word.x1, bx1) - max(word.x0, bx0)
            overlap_y = min(word.glyph_top, by1) - max(word.glyph_bottom, by0)
            if overlap_x <= 0 or overlap_y <= 0:
                continue
            if text == word.text:
                return True
            if area > 0 and (overlap_x * overlap_y) / area >= COVERAGE_IS_DUPLICATION:
                return True
        return False

    return [w for w in derived if not duplicated(w)]


def widget_words_by_page(pdf_source: Any) -> list[list[Any]]:
    """Every page's filled text-widget values as `Word`s, one list per page, UNGUARDED.

    These depend on nothing but the document, so the whole document is derived and read
    once, before the caller's own page loop begins; `merged_with_printed` then applies
    the flattened-form guard page by page as the printed words become available.

    Any failure to build or read the derived document yields an empty result: a document
    we cannot re-render is a document we read exactly as we always did.
    """
    import io

    import pdfplumber

    from core.extract import read_words

    try:
        derived = _derived_document(pdf_source)
        if derived is None:
            return []
        with pdfplumber.open(io.BytesIO(derived)) as pdf:
            return [read_words(page, number)
                    for number, page in enumerate(pdf.pages, start=1)]
    except Exception:
        return []


def merged_with_printed(printed: list[Any], widget: list[Any]) -> list[Any]:
    """One page's printed words and its widget values, as a single word stream.

    The guard runs here (see the module docstring); what survives is appended and the
    stream re-sorted into reading order, so every downstream rule sees one page of words
    and cannot tell -- or need to tell -- which glyphs a viewer drew from an annotation.
    That is the whole point: no rule below is aware this module exists.
    """
    kept = _drop_double_read(widget, printed) if widget else []
    if not kept:
        return printed
    return sorted([*printed, *kept], key=lambda w: (-w.baseline, w.x0))
