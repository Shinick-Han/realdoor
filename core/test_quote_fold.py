# -*- coding: utf-8 -*-
"""The curly-quote fold and its parallel-caption refusal (`REALDOOR_QUOTE_FOLD`).

Real forms print the typographer's apostrophe: wa_dshs's caption is `EMPLOYEE’S NAME`
(U+2019), while `LABEL_SYNONYMS` holds the ASCII `EMPLOYEE'S NAME` -- and the frozen
scorer (`eval/score_extraction._fold`) already folds the curly family to ASCII before
comparing, so the extractor was refusing a string its own scorer reads as identical.
`normalize_label` now folds the scorer's four quote glyphs, and nothing else.

The fold's measured hazard travels with it: on wa_dshs's row `EMPLOYEE’S NAME |
EMPLOYER’S NAME` the newly recognised label's row readers took the neighbouring caption
as a person_name value. `_parallel_caption_refusal` refuses a candidate that is
caption-shaped and repeats the label's own final token -- the page printing the same
slot-naming construction twice. As everywhere in this codebase, the interesting
assertions are the refusals.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex

ROOT = Path(__file__).resolve().parent.parent
WA_DSHS_BLANK = ROOT / "testdata" / "confirm_raw" / "wa_dshs_14252_employment_verification.pdf"
SEATTLE_BLANK = ROOT / "testdata" / "confirm_raw" / "seattle_housing_employment_verification_blank.pdf"


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_QUOTE_FOLD", raising=False)
    assert ex._quote_fold_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_QUOTE_FOLD", value)
    assert ex._quote_fold_enabled() is (value.strip() != "0")


def test_flag_off_restores_the_old_normalize_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The G5 contract: with the flag at `0` the curly caption stays a total miss."""
    monkeypatch.setenv("REALDOOR_QUOTE_FOLD", "0")
    assert ex.normalize_label("EMPLOYEE’S NAME") == "EMPLOYEE’S NAME"
    assert ex.synonym_mapper("pay_stub", "EMPLOYEE’S NAME") is None


# ─────────────────────────────────────────────────────────── the fold, enumerated


def test_the_curly_caption_folds_onto_the_ascii_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_QUOTE_FOLD", raising=False)
    assert ex.normalize_label("EMPLOYEE’S NAME") == "EMPLOYEE'S NAME"
    assert ex.synonym_mapper("pay_stub", "EMPLOYEE’S NAME") == "person_name"
    assert ex.synonym_mapper("employment_letter", "Employee’s Name") == "person_name"


def test_the_fold_set_is_the_scorers_own_quote_rows_verbatim() -> None:
    """Symmetry is the license, so it is pinned by importing both sides: every quote
    entry of the scorer's `_QUOTE_MAP` folds here identically, and the dash entries
    (which the scorer folds but labels must distinguish) are exactly the ones absent."""
    import sys

    sys.path.insert(0, str(ROOT / "eval"))
    from score_extraction import _QUOTE_MAP  # type: ignore

    quote_rows = {k: v for k, v in _QUOTE_MAP.items() if v in ("'", '"')}
    assert quote_rows == {"‘": "'", "’": "'", "“": '"', "”": '"'}
    for bad, good in quote_rows.items():
        assert bad.translate(ex._QUOTE_FOLD_TABLE) == good
    dash_rows = {k for k, v in _QUOTE_MAP.items() if v == "-"}
    assert dash_rows == {"–", "—", "−"}
    for dash in dash_rows:
        assert dash.translate(ex._QUOTE_FOLD_TABLE) == dash  # NOT folded


def test_dashes_and_the_hyphen_glyph_are_not_folded(monkeypatch: pytest.MonkeyPatch) -> None:
    """`TAKE-HOME PAY` is a table key and orangeusd prints U+2010; folding dash glyphs
    would widen what a key can match, which is the over-folding hazard by name."""
    monkeypatch.delenv("REALDOOR_QUOTE_FOLD", raising=False)
    assert ex.normalize_label("TAKE‐HOME PAY") == "TAKE‐HOME PAY"  # U+2010 stays
    assert ex.normalize_label("TAKE–HOME PAY") == "TAKE–HOME PAY"  # U+2013 stays
    assert ex.synonym_mapper("pay_stub", "TAKE–HOME PAY") is None


# ──────────────────────────────── the parallel-caption refusal, on hand-built geometry


def _w(text: str, x0: float, baseline: float, size: float = 8.0,
       bold: bool = False, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x0 + 4.0 * max(len(text), 1), baseline=baseline,
                   glyph_bottom=baseline, glyph_top=baseline + size, size=size,
                   bold=bold, page=page)


def _wa_dshs_row(right_cell: list[ex.Word]) -> list[ex.Word]:
    """The measured shape: a recognised curly label with one run to its right, gap
    beyond `SIDE_BY_SIDE_MIN_GAP`, no colon, only two cells on the row. Intra-run word
    gaps stay at 2pt, under the 0.6 x size run-split threshold."""
    return [_w("EMPLOYEE’S", 50.0, 700.0), _w("NAME", 92.0, 700.0)] + right_cell


def _person_name(words: list[ex.Word]) -> dict | None:
    found, _ = ex.extract_fields_from_page(
        words, "pay_stub", ex.LineBoxConvention(),
        field_mapper=ex.deterministic_mapper, fallback_mapper=ex.synonym_mapper,
    )
    return found.get("person_name")


@pytest.fixture()
def fold_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REALDOOR_QUOTE_FOLD", raising=False)
    yield


def test_the_twin_caption_is_refused_not_read(fold_on) -> None:
    """The wa_dshs misread, pinned: `EMPLOYER’S NAME` beside the recognised label must
    never emerge as anyone's name."""
    got = _person_name(_wa_dshs_row([_w("EMPLOYER’S", 290.0, 700.0), _w("NAME", 332.0, 700.0)]))
    assert got is None or got["certainty"] == "abstain"


def test_a_genuine_value_after_a_curly_label_still_emits(fold_on) -> None:
    """The fold must not over-refuse: a real filled-in name in the same geometry reads."""
    got = _person_name(_wa_dshs_row([_w("Marisol", 290.0, 700.0), _w("Vega", 322.0, 700.0)]))
    assert got is not None and got["certainty"] == "low"
    assert got["value"] == "Marisol Vega"


def test_the_refusal_needs_the_final_token_to_match(fold_on) -> None:
    """A caption-shaped run with a different head noun is not the label's twin; it is
    left to the existing rules (here it reads, exactly as it would have before)."""
    got = _person_name(_wa_dshs_row([_w("Baker", 290.0, 700.0), _w("Street", 312.0, 700.0)]))
    assert got is not None and got["value"] == "Baker Street"


def test_the_refusal_needs_the_caption_shape(fold_on) -> None:
    """A run with a digit is data however its last word reads: `_is_caption_cell` says
    no, so the twin test never fires on it."""
    words = [_w("PAY", 50.0, 700.0), _w("RATE", 66.0, 700.0),
             _w("18.00", 290.0, 700.0)]
    found, _ = ex.extract_fields_from_page(
        words, "pay_stub", ex.LineBoxConvention(),
        field_mapper=ex.deterministic_mapper, fallback_mapper=ex.synonym_mapper,
    )
    got = found.get("hourly_rate")
    assert got is not None and got["value"] == pytest.approx(18.0)


def test_helper_is_inert_with_the_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALDOOR_QUOTE_FOLD", "0")
    label = [_w("EMPLOYEE'S", 50.0, 700.0), _w("NAME", 92.0, 700.0)]
    twin = [_w("EMPLOYER'S", 290.0, 700.0), _w("NAME", 332.0, 700.0)]
    assert ex._parallel_caption_refusal(label, twin) is False


# ─────────────────────────────────────────────────────── the documents themselves


def test_wa_dshs_blank_end_to_end(fold_on) -> None:
    """The engagement without a flip: the caption is recognised, the blank cell and the
    twin caption both refuse, and nothing on the whole form emits `EMPLOYER’S NAME`."""
    view = ex.extract_document(WA_DSHS_BLANK, document_type="pay_stub",
                               fallback_mapper=ex.synonym_mapper)
    fields = {f["field"]: f for f in view["fields"]}
    person = fields.get("person_name")
    assert person is None or person["certainty"] == "abstain"
    for field in view["fields"]:
        assert field.get("value") != "EMPLOYER’S NAME"


def test_seattle_blank_end_to_end_unchanged(fold_on) -> None:
    """`Employer’s Signature` / `Employer’s Printed Name` fold onto no table key: the
    seattle blank stays all-abstain exactly as measured before the fold."""
    view = ex.extract_document(SEATTLE_BLANK, document_type="pay_stub",
                               fallback_mapper=ex.synonym_mapper)
    for field in view["fields"]:
        assert field["certainty"] == "abstain"
