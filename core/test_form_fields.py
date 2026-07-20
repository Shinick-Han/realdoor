# -*- coding: utf-8 -*-
"""What `core/form_fields.py` reads out of interactive form widgets -- and what it refuses.

The module adds no acceptance rule: widget values become ordinary `Word`s and the
existing printed-label rules bind them. So what is pinned here is the license (the
widget's internal field NAME is never consulted, however tempting this carrier's names
are), the geometry (a value's box is its typeset box, never its widget rect), the guards
(double-read, buttons, rotation), and the flag.

Falsification for the rule these pin: loop/falsification/it-012.json -- fired on 0 of 77
manifest documents, 1 of 3 filled dev documents and 6 of the unsealed scenario sets,
zero conflicts anywhere.

The AcroForm-backed tests skip when the untracked filled/confirm PDFs are absent, like
the existing confirm-set tests.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from core import extract as ex
from core import form_fields as ff

ROOT = Path(__file__).resolve().parent.parent
FILLED = ROOT / "testdata" / "filled" / "wa_dshs_14252_employment_verification_filled.pdf"
BLANK = ROOT / "testdata" / "confirm_raw" / "wa_dshs_14252_employment_verification.pdf"

filled_only = pytest.mark.skipif(not FILLED.exists(), reason="filled carrier not present")
blank_only = pytest.mark.skipif(not BLANK.exists(), reason="blank carrier not present")


def _word(text, x0, x1, baseline, size=12.0):
    return ex.Word(text=text, x0=x0, x1=x1, baseline=baseline, glyph_bottom=baseline,
                   glyph_top=baseline + size, size=size, bold=False, page=1)


def _all_words():
    return [w for page in ff.widget_words_by_page(str(FILLED)) for w in page]


# ----------------------------------------------------------------------------------
# the values are read at all -- the defect this module exists for
# ----------------------------------------------------------------------------------


@filled_only
def test_widget_values_are_invisible_to_the_text_layer():
    """The defect, pinned: the page's own content stream contains neither value."""
    import pdfplumber

    with pdfplumber.open(str(FILLED)) as pdf:
        text = pdf.pages[0].extract_text() or ""
    assert "Terrence" not in text
    assert "1,283.15" not in text


@filled_only
def test_every_filled_text_widget_is_read():
    words = _all_words()
    joined = " ".join(w.text for w in words)
    # one from each shape of value on the carrier: a name, money, a date, a bare number
    for expected in ("Terrence", "Boyd", "$17.10", "1,283.15", "02/03/2025", "38"):
        assert expected in joined, f"{expected!r} missing from {joined!r}"


@blank_only
def test_a_blank_form_reads_nothing():
    """67 fields, none filled: the module must engage and emit nothing."""
    assert ff.has_form_values(str(BLANK)) is False
    assert ff.widget_words_by_page(str(BLANK)) == []


def test_a_document_with_no_acroform_reads_nothing():
    plain = ROOT / "pack" / "synthetic_documents" / "documents"
    candidates = sorted(plain.glob("*.pdf")) if plain.exists() else []
    if not candidates:
        pytest.skip("pack PDFs not present")
    assert ff.has_form_values(str(candidates[0])) is False


# ----------------------------------------------------------------------------------
# the license: the widget's internal NAME is never consulted
# ----------------------------------------------------------------------------------


@filled_only
def test_widget_names_are_never_read_as_labels():
    """The carrier names a widget `RATE OF PAY OR SALARY HOURLY DAILY OR PIECE RATE` and
    fills it with `$17.10 hourly`. Binding by that name would light `hourly_rate` up
    immediately, and is refused: the name is not printed on the page. The value IS read
    -- it is in the word stream -- and the field abstains because the page prints no
    label the ordinary rules recognise. That abstention is the correct answer, and it is
    T21's to close, not this module's."""
    from pypdf import PdfReader

    names = {str(k) for k in (PdfReader(str(FILLED)).get_fields() or {})}
    assert "RATE OF PAY OR SALARY HOURLY DAILY OR PIECE RATE" in names, "carrier changed"

    assert any(w.text == "$17.10" for w in _all_words()), "the value must be read"

    view = ex.extract_document(str(FILLED), document_type="pay_stub")
    rate = next(f for f in view["fields"] if f["field"] == "hourly_rate")
    assert rate["certainty"] == "abstain"
    assert rate["value"] is None


@filled_only
def test_a_printed_label_does_bind_its_widget_value():
    """The other half: where the page DOES print a label the vocabulary knows, the
    ordinary rules bind the widget value exactly as they bind drawn text."""
    view = ex.extract_document(str(FILLED), document_type="pay_stub")
    name = next(f for f in view["fields"] if f["field"] == "person_name")
    assert name["value"] == "Terrence Boyd"
    assert name["certainty"] != "abstain"


# ----------------------------------------------------------------------------------
# geometry: the typeset box, never the widget rect; and the /DR zero-width regression
# ----------------------------------------------------------------------------------


@filled_only
def test_value_geometry_is_the_typeset_box_not_the_widget_rect():
    """`EMPLOYEES NAME` has a 210.7 x 21.5pt rect holding a string that sets to ~72 x
    12pt. Using the rect would hand every downstream rule a box three times too wide."""
    words = [w for w in _all_words() if w.text in ("Terrence", "Boyd")]
    assert words, "the name must be read"
    span = max(w.x1 for w in words) - min(w.x0 for w in words)
    assert 60.0 < span < 90.0, f"name spans {span}pt; the widget rect is 210.7pt"
    for w in words:
        assert w.size == pytest.approx(12.0), "size is the font's, read from the stream"


@filled_only
def test_no_word_is_zero_width():
    """The /DR regression. When the AcroForm's default resources are not merged under an
    appearance's own, pdfminer resolves no font and returns correct text at zero width --
    silently. Every downstream rule is geometric, so a zero-width word is a coordinate
    that lies."""
    for w in _all_words():
        assert w.x1 > w.x0, f"{w.text!r} has zero width"
        assert w.glyph_top > w.glyph_bottom, f"{w.text!r} has zero height"


@filled_only
def test_words_carry_bottom_left_origin_coordinates():
    """Same convention as `read_words`: y grows upward, inside the page box."""
    import pdfplumber

    with pdfplumber.open(str(FILLED)) as pdf:
        height = float(pdf.pages[0].height)
    for w in _all_words():
        assert 0.0 <= w.baseline <= height
        assert w.page == 1


# ----------------------------------------------------------------------------------
# the double-read guard, in both directions
# ----------------------------------------------------------------------------------


def test_an_exact_duplicate_at_the_same_place_is_dropped():
    """A flattened form prints the value AND keeps it in /V. Reading both doubles it."""
    printed = [_word("1,283.15", 87.3, 134.0, 336.1)]
    derived = [_word("1,283.15", 87.3, 134.0, 336.1)]
    assert ff._drop_double_read(derived, printed) == []


def test_an_adjacent_line_is_kept():
    """The measured failure that forced this guard away from `ocr_words.drop_overlapping`:
    `$17.10` sits one line below the printed caption `DAILY OR PIECE RATE)`, and their em
    boxes graze by 1.4pt -- 7% of the value's area. Adjacency is not duplication."""
    printed = [_word("DAILY", 204.8, 228.5, 487.8, size=8.0)]
    derived = [_word("$17.10", 201.7, 238.4, 477.2)]
    kept = ff._drop_double_read(derived, printed)
    assert [w.text for w in kept] == ["$17.10"]


def test_heavy_coverage_is_duplication_whatever_the_strings_say():
    printed = [_word("1,283.15", 87.0, 134.0, 336.0)]
    derived = [_word("1283.15", 87.3, 133.0, 336.1)]
    assert ff._drop_double_read(derived, printed) == []


def test_the_guard_is_the_only_thing_that_removes_a_word():
    printed = [_word("EMPLOYEE", 70.0, 130.0, 600.0)]
    derived = [_word("Terrence", 74.7, 117.4, 571.1), _word("Boyd", 120.4, 146.4, 571.1)]
    assert len(ff._drop_double_read(derived, printed)) == 2


@filled_only
def test_merging_leaves_printed_words_untouched_when_nothing_is_read():
    printed = [_word("EMPLOYEE", 70.0, 130.0, 600.0)]
    assert ff.merged_with_printed(printed, []) is printed


def test_merged_stream_is_in_reading_order():
    printed = [_word("TOP", 70.0, 100.0, 700.0), _word("BOTTOM", 70.0, 110.0, 100.0)]
    derived = [_word("middle", 70.0, 120.0, 400.0)]
    merged = ff.merged_with_printed(printed, derived)
    assert [w.text for w in merged] == ["TOP", "middle", "BOTTOM"]


# ----------------------------------------------------------------------------------
# what is deliberately not read
# ----------------------------------------------------------------------------------


@filled_only
def test_buttons_contribute_no_words():
    """The carrier has 10 checkbox/radio widgets, several switched on -- including
    `Every two weeks` = /On, a real pay_frequency statement. Their appearances are
    ZapfDingbats glyphs (a '4' that draws a checkmark) which would enter the word stream
    as a numeral. Nothing is emitted for them; the statement is filed, not smuggled."""
    from pypdf import PdfReader

    fields = PdfReader(str(FILLED)).get_fields() or {}
    buttons = {k: v for k, v in fields.items() if v.get("/FT") == "/Btn"}
    assert buttons, "carrier changed"
    assert ff.TEXT_FIELD_TYPES == ("/Tx",)

    words = _all_words()
    text_values = " ".join(
        str(v.get("/V")) for v in fields.values()
        if v.get("/FT") == "/Tx" and v.get("/V") not in (None, "")
    )
    for w in words:
        assert w.text in text_values, f"{w.text!r} came from no text field"


@filled_only
def test_a_rotated_page_reads_nothing():
    """A widget's appearance may be rotated relative to its page independently of
    /Rotate, and no corpus document composes the two -- so the composition is
    unfalsifiable here and is refused whole."""
    from pypdf import PdfWriter
    from pypdf.generic import NameObject, NumberObject

    writer = PdfWriter(clone_from=str(FILLED))
    writer.pages[0][NameObject("/Rotate")] = NumberObject(90)
    buffer = io.BytesIO()
    writer.write(buffer)
    rotated = buffer.getvalue()

    assert _all_words(), "the unrotated carrier must read, or this pins nothing"
    assert ff.widget_words_by_page(rotated) == []


def test_an_unreadable_document_reads_nothing_rather_than_raising():
    assert ff.widget_words_by_page(b"not a pdf at all") == []
    assert ff.has_form_values(b"not a pdf at all") is False


# ----------------------------------------------------------------------------------
# the flag
# ----------------------------------------------------------------------------------


@filled_only
def test_flag_off_restores_the_blank_reading(monkeypatch):
    """G5's contract, at the field level: with the flag off the carrier reads exactly as
    it did before the module existed -- which is to say, blank."""
    monkeypatch.setenv("REALDOOR_FORM_FIELDS", "0")
    assert ex._form_fields_enabled() is False
    view = ex.extract_document(str(FILLED), document_type="pay_stub")
    assert all(f["certainty"] == "abstain" for f in view["fields"])

    monkeypatch.setenv("REALDOOR_FORM_FIELDS", "1")
    assert ex._form_fields_enabled() is True


def test_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("REALDOOR_FORM_FIELDS", raising=False)
    assert ex._form_fields_enabled() is True
