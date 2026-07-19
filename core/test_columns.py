# -*- coding: utf-8 -*-
"""What `core/columns.py` reads, and -- mostly -- what it refuses to read.

The interesting assertions here are the refusals. A rule that turns abstentions into values
is only worth having if it abstains everywhere the page does not plainly say the answer, so
most of this file pins geometry that must keep producing nothing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import columns as col
from core import extract as ex

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL = ROOT / "testdata" / "external_raw"
PACK = ROOT / "pack" / "synthetic_documents"


@pytest.fixture()
def flag_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_COLUMNS", "1")
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    yield


@pytest.fixture()
def flag_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REALDOOR_COLUMNS", raising=False)
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    yield


def _fields(pdf: Path, document_type: str) -> dict:
    view = ex.extract_document(pdf, document_type=document_type)
    return {f["field"]: f for f in view["fields"]}


# ───────────────────────────────────────────────────────────────── the flag itself


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2", "1 "])
def test_only_the_literal_one_switches_it_on(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALDOOR_COLUMNS", value)
    assert ex._columns_enabled() is (value.strip() == "1")


PACK_SAMPLES = sorted(PACK.rglob("*.pdf"))[:6]


@pytest.mark.parametrize("pdf", PACK_SAMPLES, ids=lambda p: p.name)
def test_the_flag_moves_nothing_on_the_pack(pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pack is what the 159/159 gold and the bbox IoU were measured against. Every field
    there is already answered by the label geometry, so this path finds no blank to fill and
    must leave the document byte-for-byte as it was."""
    document_type = ex.infer_document_type(pdf)
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    monkeypatch.delenv("REALDOOR_COLUMNS", raising=False)
    off = json.dumps(ex.extract_document(pdf, document_type=document_type), sort_keys=True)
    monkeypatch.setenv("REALDOOR_COLUMNS", "1")
    on = json.dumps(ex.extract_document(pdf, document_type=document_type), sort_keys=True)
    assert off == on


# ───────────────────────────────────────────────────────── what it newly reads, and why


def test_a_lone_currency_symbol_is_not_a_rival_value(flag_on) -> None:
    """ADP's `Net Pay` row is `Net Pay | $ | 532.76`. The dollar sign sits in the column rule
    as its own run, so the side-by-side rule counted two candidates and called the cell
    ambiguous. It is not ambiguous; one of the two is not a value anybody could mean."""
    got = _fields(EXTERNAL / "ext_adp.pdf", "pay_stub")["net_pay"]
    assert got["value"] == pytest.approx(532.76)
    assert got["source_text"] == "532.76"
    assert got["bbox"] is not None and got["page"] == 1


def test_the_header_row_says_which_column_is_this_period(flag_on) -> None:
    """ADP's `Gross Pay` row carries 707.75 and 0.00, and along the row alone there is no way
    to choose. The page's own header row puts 707.75 under `This Period` and 0.00 under
    `Year to Date`, and their x-spans agree to a third of a point."""
    got = _fields(EXTERNAL / "ext_adp.pdf", "pay_stub")["gross_pay"]
    assert got["value"] == pytest.approx(707.75)
    assert "This Period" in (got["notes"] or "")


def test_the_same_rule_reads_a_plain_summary_table(flag_on) -> None:
    """UTEP prints `Gross Wages | $1,227.36 | $27,308.42` under `Current Amount | YTD Amount`.
    Different publisher, different wording, same mechanism and no new vocabulary."""
    got = _fields(EXTERNAL / "ext_utep.pdf", "pay_stub")["gross_pay"]
    assert got["value"] == pytest.approx(1227.36)
    assert "Current Amount" in (got["notes"] or "")


@pytest.mark.parametrize(
    "text,bare",
    [("$", True), ("€", True), ("$ $", True), ("$943.45", False), ("0.00", False),
     ("USD", False), ("-", False)],
)
def test_bare_currency_is_narrow(text: str, bare: bool) -> None:
    """It drops a run that is *only* a currency mark. It never strips a symbol out of a value."""
    words = [
        ex.Word(text=t, x0=0.0, x1=1.0, baseline=0.0, glyph_bottom=0.0, glyph_top=1.0,
                size=7.0, bold=False, page=1)
        for t in text.split(" ")
    ]
    assert col._is_bare_currency(words) is bare


# ───────────────────────────────────────────────────────────────── what it must refuse


def test_a_tall_glyph_clipping_the_row_is_not_in_the_row() -> None:
    """The federal LES sets its form item-number callouts in 12pt, offset between rows, so
    `3` clips the bottom of the `Net Pay` header. Judged against the shorter box it scores
    54% and `Net Pay` read as 3.0 -- the one wrong value this work produced. By IoU it scores
    0.33 and is refused, while the ADP rows this rule exists to join score 0.73."""
    # 'Net Pay' label ink, and the 12pt callout that must not join it.
    assert col._shares_row(
        ex.Word(text="3", x0=560.04, x1=566.12, baseline=533.64, glyph_bottom=531.31,
                glyph_top=543.31, size=12.0, bold=False, page=3),
        537.90, 547.86,
    ) is False
    # The ADP value, 7pt beside a 9pt label, which must join it.
    assert col._shares_row(
        ex.Word(text="532.76", x0=231.84, x1=257.04, baseline=474.53, glyph_bottom=473.17,
                glyph_top=480.17, size=7.0, bold=False, page=1),
        470.91, 479.91,
    ) is True


def test_the_les_net_pay_is_never_attributed_by_this_module(flag_on) -> None:
    """The regression that guards the above, end to end and through the real file.

    Narrowed alongside `core/test_arithmetic.py::test_les_gross_and_net_stay_refused`, and for
    the same reason. This module's refusal is about *column attribution*: the LES earnings
    matrix must never hand `net_pay` a number by lining it up with a header. That refusal is
    intact. What changed is elsewhere -- page 3 prints `$960.50` in the column under a net-pay
    label, and `TYPED_VALUE_X_TOLERANCE` now reaches it through the ordinary label-anchored
    read, which is a different rule with a different guarantee. So the assertion is made on
    this module's own note rather than on the field being empty.
    """
    got = _fields(EXTERNAL / "ext_les.pdf", "pay_stub")
    assert got["gross_pay"]["certainty"] == "abstain"
    for name in ("net_pay", "gross_pay"):
        assert "header" not in (got[name].get("notes") or "").lower(), (
            f"{name} was attributed by a column header on a page whose matrix does not "
            f"support it: {got[name].get('notes')!r}"
        )


@pytest.mark.parametrize(
    "file_name,document_type",
    [("ext_nydol.pdf", "benefit_letter"), ("ext_va.pdf", "employment_letter")],
)
def test_blank_forms_stay_blank(file_name: str, document_type: str, flag_on) -> None:
    """Two blank government forms, and the VA one has bare `$` glyphs sitting in its empty
    money boxes -- exactly the run this change teaches the extractor to skip past. Skipping it
    must leave nothing behind, not uncover something further right."""
    view = ex.extract_document(EXTERNAL / file_name, document_type=document_type)
    answered = [f["field"] for f in view["fields"] if f["certainty"] != "abstain"]
    assert answered == [], f"{file_name} invented {answered} out of a blank form"


def test_the_empty_pay_rate_column_stays_empty(flag_on) -> None:
    """UTEP's `Pay Rate` column is a header with nothing under it. `PAY RATE` maps to
    hourly_rate, so this is the trap where a column rule invents a number from the neighbours."""
    got = _fields(EXTERNAL / "ext_utep.pdf", "pay_stub")["hourly_rate"]
    assert got["certainty"] == "abstain"


def test_the_unc_annual_salary_trap_stays_refused(flag_on) -> None:
    """UNC prints `Pay Rate: $45,000.00 Annual` against a true hourly rate of 20.35. Reading
    the labelled figure would be a confident wrong answer."""
    got = _fields(EXTERNAL / "ext_unc.pdf", "pay_stub")["hourly_rate"]
    assert got["certainty"] == "abstain"


def test_a_row_of_numbers_is_not_a_header_row() -> None:
    """Directly above ADP's `Gross Pay` row sit two earnings rows whose numbers occupy exactly
    the same columns -- `111.75` shares an x-span with `707.75`, because it is the same
    column. Matching against those would attribute the value to another row of the matrix
    instead of the row that names the columns."""
    def run(text: str):
        return [ex.Word(text=text, x0=0.0, x1=1.0, baseline=0.0, glyph_bottom=0.0,
                        glyph_top=1.0, size=7.0, bold=False, page=1)]

    assert col._is_header_cell(run("This Period")) is True
    assert col._is_header_cell(run("111.75")) is False
    assert col._is_header_cell(run("401(k)")) is False


@pytest.mark.parametrize(
    "text,cumulative",
    [("Year to Date", True), ("YTD", True), ("YTD Amount", True), ("ytd hours", True),
     ("This Period", False), ("Current", False), ("Current Amount", False),
     ("Earnings", False), ("Rate", False)],
)
def test_only_the_cumulative_column_is_named(text: str, cumulative: bool) -> None:
    """The distinction is derived from one concept the pages print -- an amount accumulated
    *to a date* -- and its own abbreviation. There is deliberately no list of period-column
    names; a column is the current one by not being the cumulative one."""
    assert col._is_cumulative(text) is cumulative


def _word(text: str, x0: float, x1: float, baseline: float):
    return ex.Word(text=text, x0=x0, x1=x1, baseline=baseline, glyph_bottom=baseline,
                   glyph_top=baseline + 7.0, size=7.0, bold=False, page=1)


def _synthetic(headers: list[tuple[str, float, float]],
               values: list[tuple[str, float, float]]):
    """One header row at y=100 and one value row at y=80, built from spans."""
    header_line = [_word(t, a, b, 100.0) for t, a, b in headers]
    value_line = [_word(t, a, b, 80.0) for t, a, b in values]
    candidates = [[w] for w in value_line]
    return [header_line, value_line], candidates


def test_the_only_current_column_wins() -> None:
    lines, candidates = _synthetic(
        [("This Period", 200.0, 260.0), ("Year to Date", 270.0, 330.0)],
        [("707.75", 231.0, 257.0), ("0.00", 305.0, 321.0)],
    )
    chosen = col._attribute(lines, candidates)
    assert chosen is not None and ex._join_run(chosen[0]) == "707.75"


def test_two_current_columns_abstain() -> None:
    """`Current Hours` and `Current Amount` are both non-cumulative. The page has not said
    which one this label wants, so neither is reported."""
    lines, candidates = _synthetic(
        [("Current Hours", 200.0, 260.0), ("Current Amount", 270.0, 330.0)],
        [("79.75", 231.0, 257.0), ("1227.36", 305.0, 321.0)],
    )
    assert col._attribute(lines, candidates) is None


def test_all_cumulative_columns_abstain() -> None:
    lines, candidates = _synthetic(
        [("YTD Hours", 200.0, 260.0), ("YTD Amount", 270.0, 330.0)],
        [("1596", 231.0, 257.0), ("24422.76", 305.0, 321.0)],
    )
    assert col._attribute(lines, candidates) is None


def test_two_candidates_in_one_cell_abstain() -> None:
    """Two numbers inside a single header cell means the row is not describing these columns,
    whatever the words in it say."""
    lines, candidates = _synthetic(
        [("This Period", 200.0, 330.0), ("Year to Date", 340.0, 400.0)],
        [("707.75", 231.0, 257.0), ("0.00", 305.0, 321.0)],
    )
    assert col._attribute(lines, candidates) is None


def test_a_candidate_matching_no_cell_abstains() -> None:
    lines, candidates = _synthetic(
        [("This Period", 200.0, 260.0), ("Year to Date", 270.0, 330.0)],
        [("707.75", 231.0, 257.0), ("0.00", 500.0, 520.0)],
    )
    assert col._attribute(lines, candidates) is None


def test_no_header_row_at_all_abstains() -> None:
    lines, candidates = _synthetic([], [("707.75", 231.0, 257.0), ("0.00", 305.0, 321.0)])
    assert col._attribute(lines, candidates) is None


# ─────────────────────────────────────────────────────────── flag off changes nothing


@pytest.mark.parametrize(
    "file_name,document_type",
    [("ext_adp.pdf", "pay_stub"), ("ext_utep.pdf", "pay_stub"),
     ("ext_unc.pdf", "pay_stub"), ("ext_les.pdf", "pay_stub"),
     ("ext_nydol.pdf", "benefit_letter"), ("ext_va.pdf", "employment_letter")],
)
def test_flag_off_is_byte_for_byte_the_old_behaviour(
    file_name: str, document_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not "the same values" -- the same bytes. The whole document view is compared, so a
    changed note, box, page or certainty would fail this too."""
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    monkeypatch.delenv("REALDOOR_COLUMNS", raising=False)
    off = json.dumps(
        ex.extract_document(EXTERNAL / file_name, document_type=document_type),
        sort_keys=True,
    )
    monkeypatch.setenv("REALDOOR_COLUMNS", "0")
    also_off = json.dumps(
        ex.extract_document(EXTERNAL / file_name, document_type=document_type),
        sort_keys=True,
    )
    assert off == also_off


def test_the_recovered_fields_are_abstentions_with_the_flag_off(flag_off) -> None:
    """The three fields this change recovers, pinned as abstentions in the shipped default."""
    adp = _fields(EXTERNAL / "ext_adp.pdf", "pay_stub")
    utep = _fields(EXTERNAL / "ext_utep.pdf", "pay_stub")
    assert adp["gross_pay"]["certainty"] == "abstain"
    assert adp["net_pay"]["certainty"] == "abstain"
    assert utep["gross_pay"]["certainty"] == "abstain"
