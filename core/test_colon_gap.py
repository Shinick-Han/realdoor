# -*- coding: utf-8 -*-
"""The colon-line fill-in license (`REALDOOR_COLON_GAP`).

Fill-in-the-line forms print `Label: value` -- the value a word space after the label's
own colon, inside the 12pt column gap `_side_by_side_run` demands of a bare label, and
(when the line's runs are all letters) inside a false `_header_row_words` classification
that makes the value its own barrier. The license reads the colon as the page's own
punctuation for "what follows me on my line is my value" and reaches exactly those two
refusals; every other refusal is pinned here as standing.

The motivating page is the seattle filled employment verification: `Employee Name:`
[71.9-133.3] `Marisol Vega`[138.3-185.0] `Job Title:`[311.7-344.1] `Prep Cook` on one
8pt baseline, truth `Marisol Vega`, an abstention before this license.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex

ROOT = Path(__file__).resolve().parent.parent
SEATTLE_FILLED = ROOT / "testdata" / "filled" / "seattle_housing_employment_verification_filled.pdf"
SEATTLE_BLANK = ROOT / "testdata" / "confirm_raw" / "seattle_housing_employment_verification_blank.pdf"


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_COLON_GAP", raising=False)
    assert ex._colon_gap_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_COLON_GAP", value)
    assert ex._colon_gap_enabled() is (value.strip() != "0")


# ──────────────────────────────────────────────── the mechanism, on hand-built geometry
#
# The seattle line, rebuilt to measure: 8pt type, word gaps of ~2pt (under the 0.6 x size
# run-split threshold of 4.8pt), a 5pt gap between the colon label and the value, and the
# next colon caption far to the right closing the cell.


def _w(text: str, x0: float, baseline: float, size: float = 8.0,
       bold: bool = False, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x0 + 4.0 * max(len(text), 1), baseline=baseline,
                   glyph_bottom=baseline, glyph_top=baseline + size, size=size,
                   bold=bold, page=page)


def _seattle_line(cell: list[ex.Word], label_text: str = "Name:") -> list[ex.Word]:
    """`Employee <label_text>` at 50, the cell content, then `Job Title: Prep Cook`.

    `Title:` ends at x1 = 338; `Prep` starts at 344, a 6pt gap over the 4.8pt split
    threshold, so `Job Title:` is its own colon-terminated run -- the real page's
    shape (measured gap there: 5.0pt)."""
    return ([_w("Employee", 50.0, 700.0), _w(label_text, 86.0, 700.0)]
            + cell
            + [_w("Job", 300.0, 700.0), _w("Title:", 314.0, 700.0),
               _w("Prep", 344.0, 700.0), _w("Cook", 362.0, 700.0)])


def _person_name(words: list[ex.Word]) -> dict | None:
    found, _ = ex.extract_fields_from_page(
        words, "pay_stub", ex.LineBoxConvention(),
        field_mapper=ex.deterministic_mapper, fallback_mapper=ex.synonym_mapper,
    )
    return found.get("person_name")


#: `Employee Name:` ends at x1 = 86 + 4*5 = 106; the value starts a 5pt word space later.
VALUE_AT_WORD_SPACE = [_w("Marisol", 111.0, 700.0), _w("Vega", 141.0, 700.0)]


@pytest.fixture()
def license_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REALDOOR_COLON_GAP", raising=False)
    yield


def test_the_colon_label_reads_its_fill_at_a_word_space(license_on) -> None:
    """The whole license in one page: sub-12pt gap, all-letters line (a false header
    row), the next colon caption closing the cell -- and the value reads."""
    got = _person_name(_seattle_line(VALUE_AT_WORD_SPACE))
    assert got is not None and got["certainty"] == "low"
    assert got["value"] == "Marisol Vega"


def test_flag_off_restores_the_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """The G5 contract, pinned on the exact geometry that motivated the license."""
    monkeypatch.setenv("REALDOOR_COLON_GAP", "0")
    got = _person_name(_seattle_line(VALUE_AT_WORD_SPACE))
    assert got is None or got["certainty"] == "abstain"


def test_a_bare_label_keeps_the_twelve_point_gap(license_on) -> None:
    """No colon, no license: the same 5pt gap stays refused, so prose that opens with
    a known label still cannot read its own tail as a value."""
    got = _person_name(_seattle_line(VALUE_AT_WORD_SPACE, label_text="Name"))
    assert got is None or got["certainty"] == "abstain"


def test_the_empty_cell_between_two_colon_labels_reads_nothing(license_on) -> None:
    """The blank-form shape: `Employee Name:` directly followed by the next colon
    caption. The barrier leaves zero runs; the abstention stands."""
    got = _person_name(_seattle_line([]))
    assert got is None or got["certainty"] == "abstain"


def test_two_runs_in_the_cell_still_tie_and_refuse(license_on) -> None:
    """A second run in the cell (a column gap between the two) is two things in one
    cell; the license never chooses."""
    cell = [_w("Marisol", 111.0, 700.0), _w("Vega", 141.0, 700.0),
            _w("Interim", 200.0, 700.0)]
    got = _person_name(_seattle_line(cell))
    assert got is None or got["certainty"] == "abstain"


def test_a_colon_candidate_is_still_never_a_value(license_on) -> None:
    """A colon-terminated run in the cell is a caption whatever the gap; it acts as
    the barrier and the cell before it is empty."""
    got = _person_name(_seattle_line([_w("Pending:", 111.0, 700.0)]))
    assert got is None or got["certainty"] == "abstain"


def test_a_merged_caption_pair_is_refused_by_its_interior_colon(license_on) -> None:
    """The amnesty's own hazard, pinned: on a line the header-row test classifies (three
    caption runs), the committed conduct refuses everything as header cells. When the
    NEXT caption merges with its fill into one run (`Job Title: Prep Cook`, the colon
    mid-run, a 3pt word space), the amnesty strips that refusal and no colon-terminated
    run remains before it to act as barrier -- the merged pair becomes the sole
    candidate. The interior-colon refusal keeps the licensed read empty: a licensed
    read is a clean fill or nothing."""
    words = ([_w("Employee", 50.0, 700.0), _w("Name:", 86.0, 700.0)]
             + [_w("Job", 300.0, 700.0), _w("Title:", 314.0, 700.0),
                _w("Prep", 341.0, 700.0), _w("Cook", 359.0, 700.0)]  # 3pt gap: merged
             + [_w("Manager", 500.0, 700.0), _w("Name:", 530.0, 700.0)])
    got = _person_name(words)
    assert got is None or got["certainty"] == "abstain"


def test_another_lines_header_row_still_refuses(license_on) -> None:
    """The amnesty reaches exactly the label's own line: a candidate that is a cell of
    a real column-header row on ANOTHER line keeps its refusal. Here `Marisol` sits in
    a three-caption header row one line below; reading it beneath the label is still
    refused as a header cell."""
    words = [_w("Employee", 50.0, 700.0), _w("Name:", 86.0, 700.0)]
    # a real (colon-free) header row on the next line, first cell under the label
    words += [_w("Marisol", 50.0, 686.0), _w("Dept", 200.0, 686.0),
              _w("Rate", 350.0, 686.0)]
    got = _person_name(words)
    assert got is None or got["certainty"] == "abstain"


def test_the_parallel_caption_refusal_survives_the_license(license_on) -> None:
    """it-009's twin test still fires under it-010's license: a curly twin caption at a
    word-space gap after the colon label is refused, not read."""
    words = ([_w("Employee’s", 50.0, 700.0), _w("Name:", 92.0, 700.0)]
             + [_w("Employer’s", 121.0, 700.0), _w("Name", 163.0, 700.0)])
    got = _person_name(words)
    assert got is None or got["certainty"] == "abstain"


# ─────────────────────────────────────────────────────── the documents themselves


def test_seattle_filled_end_to_end(license_on) -> None:
    """The target flip, and only the target flip: person_name reads `Marisol Vega`;
    every other field of the document stays exactly as measured before the license."""
    view = ex.extract_document(SEATTLE_FILLED, document_type="pay_stub",
                               fallback_mapper=ex.synonym_mapper)
    fields = {f["field"]: f for f in view["fields"]}
    got = fields["person_name"]
    assert got["certainty"] == "low"
    assert got["value"] == "Marisol Vega"
    others = {name: f["certainty"] for name, f in fields.items() if name != "person_name"}
    assert all(certainty == "abstain" for certainty in others.values()), others


def test_seattle_blank_end_to_end_stays_all_abstain(license_on) -> None:
    """The empty cells refuse (the barrier leaves nothing to read); the blank form's
    every field stays an abstention, exactly as its truth expects."""
    view = ex.extract_document(SEATTLE_BLANK, document_type="pay_stub",
                               fallback_mapper=ex.synonym_mapper)
    for field in view["fields"]:
        assert field["certainty"] == "abstain", field["field"]
