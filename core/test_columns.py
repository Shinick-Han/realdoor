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
CONFIRM = ROOT / "testdata" / "confirm_raw"
PACK = ROOT / "pack" / "synthetic_documents"


# The flags default ON now, so "off" has to be said out loud: only the literal `0`
# disables a path. The arithmetic flag is pinned off in both fixtures for the same reason
# it always was -- these tests measure what the *column* path does, so what the arithmetic
# chain would add has to be held fixed.
@pytest.fixture()
def flag_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_COLUMNS", "1")
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    yield


@pytest.fixture()
def flag_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_COLUMNS", "0")
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    yield


def _fields(pdf: Path, document_type: str) -> dict:
    view = ex.extract_document(pdf, document_type=document_type)
    return {f["field"]: f for f in view["fields"]}


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Promoted from opt-in: with the variable unset the column path runs. The promotion
    measurement is recorded in `core.extract._arithmetic_enabled`."""
    monkeypatch.delenv("REALDOOR_COLUMNS", raising=False)
    assert ex._columns_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2", "1 "])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off has to be said out loud. Anything that is not the literal `0` leaves the shipped
    default in force, so a typo in the variable cannot silently turn the path off."""
    monkeypatch.setenv("REALDOOR_COLUMNS", value)
    assert ex._columns_enabled() is (value.strip() != "0")


PACK_SAMPLES = sorted(PACK.rglob("*.pdf"))[:6]


@pytest.mark.parametrize("pdf", PACK_SAMPLES, ids=lambda p: p.name)
def test_the_flag_moves_nothing_on_the_pack(pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pack is what the 159/159 gold and the bbox IoU were measured against. Every field
    there is already answered by the label geometry, so this path finds no blank to fill and
    must leave the document byte-for-byte as it was."""
    document_type = ex.infer_document_type(pdf)
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    monkeypatch.setenv("REALDOOR_COLUMNS", "0")
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
    the same reason. This module's refusal is about *label-row* column attribution: the LES
    earnings matrix must never hand `net_pay` a number by lining a label's row up with a
    header. That refusal is intact -- `net_pay`'s value comes from the ordinary
    label-anchored read of the `$960.50` page 3 prints, and carries no attribution note.

    `gross_pay` was narrowed a second time when the two-axis rule landed: page 3 prints
    `Gross 1813.00 29739.00` under the header row `Current | YTD`, which is exactly the
    row-word-crosses-header-cell layout `table_cell_value` reads. The page states the
    answer, so asserting an abstention here would be pinning a limitation, not a refusal.
    What must still never happen is a *label* acquiring a value through `column_value`'s
    header attribution on this matrix, and that is asserted on the note text.
    """
    got = _fields(EXTERNAL / "ext_les.pdf", "pay_stub")
    gross = got["gross_pay"]
    assert gross["value"] == pytest.approx(1813.00)
    assert gross["certainty"] == "low"
    assert "row's first cell 'Gross'" in (gross.get("notes") or "")
    for name in ("net_pay", "gross_pay"):
        note = (got[name].get("notes") or "")
        assert "in the column the page's own header row names" not in note, (
            f"{name} was attributed to a label by a column header on a page whose matrix "
            f"does not support it: {note!r}"
        )
    assert got["net_pay"]["value"] == pytest.approx(960.50)


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
    """UNC prints `Pay Rate: $45,000.00 Annual` against a true hourly rate of 20.346846.
    Reading the labelled figure would be a confident wrong answer, and it must stay
    unreadable through every rule. The two-axis rule now reads the true rate instead --
    UNC's earnings matrix prints `Regular 20.346846 74.50 ...` under a header row whose
    `Rate` cell sits over the first number -- so the assertion is two-sided: 45,000.00
    never, and any value that does appear is the one the page's own Rate column prints."""
    got = _fields(EXTERNAL / "ext_unc.pdf", "pay_stub")["hourly_rate"]
    assert got["value"] != pytest.approx(45000.0), "the annual salary was read as an hourly rate"
    assert got["value"] == pytest.approx(20.346846)
    assert got["certainty"] == "low"
    assert "row's first cell 'Regular'" in (got.get("notes") or "")


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


# ────────────────────────────────────── the two-axis table cell, and what it must refuse


def test_adp_hours_come_from_the_hours_header_not_from_adjacency(flag_on) -> None:
    """The hazard that makes the naive version of this rule unsafe, pinned exactly.

    ADP's row is `Regular 14.9000 40.00 596.00`, and the first number right of "Regular"
    is the RATE. A side-by-side REGULAR -> regular_hours rule -- one axis, plus proximity
    -- would confidently emit 14.90 as the hours. The two-axis rule answers 40.00 because
    the header cell the page prints above it says `Hours`, and 14.9000 becomes the rate
    for the same reason: the cell above it says `Rate`."""
    got = _fields(EXTERNAL / "ext_adp.pdf", "pay_stub")
    hours = got["regular_hours"]
    assert hours["value"] == 40
    assert hours["value"] != pytest.approx(14.9), "the rate was read as the hours"
    assert hours["certainty"] == "low"
    assert "'Hours'" in (hours["notes"] or "")
    rate = got["hourly_rate"]
    assert rate["value"] == pytest.approx(14.9)
    assert rate["certainty"] == "low"
    assert "'Rate'" in (rate["notes"] or "")


def test_utep_hours_come_from_the_current_hours_column(flag_on) -> None:
    """UTEP's `Regular` row puts 74.25 under `Current Hours` and 1,596 under `YTD Hours`.
    The cumulative marker is what tells them apart, exactly as it does for amounts."""
    got = _fields(EXTERNAL / "ext_utep.pdf", "pay_stub")["regular_hours"]
    assert got["value"] == pytest.approx(74.25)
    assert got["certainty"] == "low"
    assert "'Current Hours'" in (got["notes"] or "")


def test_les_hours_come_from_the_hours_header(flag_on) -> None:
    """The LES prints `Regular 21.38 80.00 1710.00` under `TYPE | RATE | ADJUSTED |
    ADJ HOURS | HOURS | CURRENT | YTD`. The ADJ HOURS column is empty for this row, so
    exactly one candidate sits under a cell that names the axis, and it is 80.00."""
    got = _fields(EXTERNAL / "ext_les.pdf", "pay_stub")["regular_hours"]
    assert got["value"] == 80
    assert got["certainty"] == "low"
    assert "'HOURS'" in (got["notes"] or "")


def test_unc_twin_hours_headers_refuse(flag_on) -> None:
    """UNC's earnings matrix prints two bare `Hours` headers in one row -- the current
    column and the year-to-date column, distinguished only by a second header tier this
    rule does not read. Two cells name the axis, the page has not said which one is meant
    on the row itself, and the honest answer is an abstention -- not 855.00, the YTD
    figure that a nearest-cell tie-break would have picked."""
    got = _fields(EXTERNAL / "ext_unc.pdf", "pay_stub")["regular_hours"]
    assert got["certainty"] == "abstain"


def test_the_row_word_must_be_the_rows_first_cell(flag_on) -> None:
    """The bonita certificated check prints `C M | REGULAR | 9/30/2018 | 6,333.00 | 23.00
    | 6,333.00` under a header row that includes `RATE` -- and the 6,333.00 in the RATE
    column is a monthly figure on a document whose truth records hourly_rate as absent.
    "REGULAR appears in the row" would read it; "REGULAR is the row's name cell" refuses
    it, because that row's first cell is `C M`."""
    pdf = CONFIRM / "bonita_certificated_check_sample.pdf"
    got = _fields(pdf, "pay_stub")
    assert got["hourly_rate"]["certainty"] == "abstain"
    assert got["regular_hours"]["certainty"] == "abstain"


# Synthetic refusal geometry for `table_cell_value`, one hazard per test. `_word` and the
# header/value row builder mirror the `_attribute` fixtures above.


def _table_lines(*rows: tuple[float, list[tuple[str, float, float]]]):
    return [[_word(t, a, b, base) for t, a, b in cells] for base, cells in rows]


_CONV = ex.LineBoxConvention()


def test_a_second_matching_row_refuses() -> None:
    """The LES layout prints adjustment rows under the same row word as the period's own
    row, and nothing printed says which is which. Two rows, no reading."""
    lines = _table_lines(
        (100.0, [("Hours", 200.0, 260.0), ("Rate", 300.0, 360.0)]),
        (80.0, [("Regular", 20.0, 60.0), ("40.00", 210.0, 240.0)]),
        (60.0, [("Regular", 20.0, 60.0), ("8.00", 210.0, 240.0)]),
    )
    assert col.table_cell_value(lines, "regular_hours", _CONV) is None


def test_a_cumulative_axis_cell_refuses() -> None:
    """A `YTD Hours` header names the axis word and the wrong period. The unchanged
    `CUMULATIVE_MARKERS` is what refuses it -- there is no list of current-column names."""
    lines = _table_lines(
        (100.0, [("YTD Hours", 200.0, 260.0), ("Amount", 300.0, 360.0)]),
        (80.0, [("Regular", 20.0, 60.0), ("1596", 210.0, 240.0), ("24422.76", 310.0, 350.0)]),
    )
    assert col.table_cell_value(lines, "regular_hours", _CONV) is None


def test_a_candidate_under_no_header_cell_refuses() -> None:
    """A number that shares ink with no header cell is a number the header row does not
    describe, and one such number disqualifies the whole row -- the page's own header has
    failed to account for what the row prints."""
    lines = _table_lines(
        (100.0, [("Hours", 200.0, 260.0), ("Amount", 300.0, 360.0)]),
        (80.0, [("Regular", 20.0, 60.0), ("40.00", 210.0, 240.0), ("596.00", 500.0, 540.0)]),
    )
    assert col.table_cell_value(lines, "regular_hours", _CONV) is None


def test_a_candidate_under_two_header_cells_refuses() -> None:
    """A candidate straddling two header cells belongs to neither of them plainly."""
    lines = _table_lines(
        (100.0, [("Adj Hours", 200.0, 260.0), ("Hours", 255.0, 320.0)]),
        (80.0, [("Regular", 20.0, 60.0), ("40.00", 240.0, 270.0)]),
    )
    assert col.table_cell_value(lines, "regular_hours", _CONV) is None


def test_no_header_row_above_refuses() -> None:
    """A bare `Regular 40.00` with no header row above it is exactly the one-axis layout
    this rule exists to refuse: nothing printed says what the number is."""
    lines = _table_lines(
        (80.0, [("Regular", 20.0, 60.0), ("40.00", 210.0, 240.0)]),
    )
    assert col.table_cell_value(lines, "regular_hours", _CONV) is None


def test_an_unlisted_field_is_never_read_from_a_table() -> None:
    """The row-name table is closed. A field without an entry cannot be resolved this way,
    however suggestive the page's geometry."""
    lines = _table_lines(
        (100.0, [("Hours", 200.0, 260.0), ("Rate", 300.0, 360.0)]),
        (80.0, [("Regular", 20.0, 60.0), ("40.00", 210.0, 240.0)]),
    )
    assert col.table_cell_value(lines, "net_pay", _CONV) is None


def test_bare_row_words_are_still_not_labels() -> None:
    """The two-axis rule is precisely why REGULAR, RATE and HOURS stay out of the label
    vocabulary: as labels they would resolve one-axis, first-number-wins. If someone adds
    them, this fails before a measurement has to catch the wrong value."""
    for table in (ex.LABEL_MAP, ex.LABEL_SYNONYMS):
        for mapping in table.values():
            for banned in ("REGULAR", "RATE", "HOURS", "GROSS", "CURRENT"):
                assert banned not in mapping


# ─────────────────────────────────────────────────────────── flag off changes nothing


@pytest.mark.parametrize(
    "file_name,document_type",
    [("ext_adp.pdf", "pay_stub"), ("ext_utep.pdf", "pay_stub"),
     ("ext_unc.pdf", "pay_stub"), ("ext_les.pdf", "pay_stub"),
     ("ext_nydol.pdf", "benefit_letter"), ("ext_va.pdf", "employment_letter")],
)
def test_the_default_is_byte_for_byte_the_explicit_on(
    file_name: str, document_type: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not "the same values" -- the same bytes. An unset variable and an explicit `1` must
    be the same configuration, so the shipped default is exactly the measured one and there
    is no third, accidental state between on and off."""
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    monkeypatch.delenv("REALDOOR_COLUMNS", raising=False)
    default = json.dumps(
        ex.extract_document(EXTERNAL / file_name, document_type=document_type),
        sort_keys=True,
    )
    monkeypatch.setenv("REALDOOR_COLUMNS", "1")
    explicit_on = json.dumps(
        ex.extract_document(EXTERNAL / file_name, document_type=document_type),
        sort_keys=True,
    )
    assert default == explicit_on


def test_the_recovered_fields_are_abstentions_with_the_flag_off(flag_off) -> None:
    """Every field the column path recovers -- label-row headers and two-axis table cells
    alike -- pinned as an abstention when the flag is explicitly `0`."""
    adp = _fields(EXTERNAL / "ext_adp.pdf", "pay_stub")
    utep = _fields(EXTERNAL / "ext_utep.pdf", "pay_stub")
    les = _fields(EXTERNAL / "ext_les.pdf", "pay_stub")
    assert adp["gross_pay"]["certainty"] == "abstain"
    assert adp["net_pay"]["certainty"] == "abstain"
    assert utep["gross_pay"]["certainty"] == "abstain"
    assert adp["regular_hours"]["certainty"] == "abstain"
    assert adp["hourly_rate"]["certainty"] == "abstain"
    assert utep["regular_hours"]["certainty"] == "abstain"
    assert les["regular_hours"]["certainty"] == "abstain"
    assert les["gross_pay"]["certainty"] == "abstain"


# ────────────────────────────────────── the EARNINGS table's own END DATE column


def _w(text, x0, x1, baseline, size=7.3, bold=False, page=1):
    return ex.Word(
        text=text, x0=x0, x1=x1, baseline=baseline,
        glyph_bottom=baseline - 0.2 * size, glyph_top=baseline + 0.8 * size,
        size=size, bold=bold, page=page,
    )


def _bonita_like(*, titled=True, extra=()):
    """The bonita layout, reduced: a titled EARNINGS block over a headed table row."""
    words = [
        _w("BASIS", 14.0, 31.0, 640.0),
        _w("DESCRIPTION", 60.0, 100.0, 640.0),
        _w("END", 118.4, 131.0, 640.0),
        _w("DATE", 133.0, 148.8, 640.0),
        _w("RATE", 162.0, 177.3, 640.0),
        _w("AMOUNT", 227.5, 255.9, 640.0),
        _w("9/30/2018", 118.7, 150.3, 631.0),
    ]
    if titled:
        words += [
            _w("EARNINGS", 2.2, 40.0, 649.0),
            _w("-", 43.0, 45.0, 649.0),
            _w("COMPENSATION", 47.0, 88.5, 649.0),
        ]
    return list(words) + list(extra)


class TestEarningsEndDateColumn:
    """`pay_period_end` from an END DATE header cell inside a page-titled EARNINGS table.
    "END DATE" alone is the kind of compound the synonym table refuses (the end date of
    *what*?), so the section word is a hard requirement, not decoration."""

    CONVENTION = ex.LineBoxConvention()

    def _run(self, words):
        return col.earnings_end_date_value(ex.group_lines(words), self.CONVENTION)

    def test_the_bonita_shape_is_read(self) -> None:
        got = self._run(_bonita_like())
        assert got is not None
        assert got["value"] == "2018-09-30"
        assert got["certainty"] == "low"
        assert "END DATE" in got["notes"] and "EARNINGS" in got["notes"]

    def test_without_the_earnings_title_nothing_is_read(self) -> None:
        """The same table under any other section title could be an employment history,
        and its END DATE would be the end of the job, not of the pay period."""
        assert self._run(_bonita_like(titled=False)) is None

    def test_disagreeing_dates_under_the_cell_refuse(self) -> None:
        extra = [_w("9/15/2018", 118.7, 150.3, 620.0)]
        assert self._run(_bonita_like(extra=extra)) is None

    def test_agreeing_dates_under_the_cell_are_one_answer(self) -> None:
        extra = [_w("9/30/2018", 118.7, 150.3, 620.0)]
        got = self._run(_bonita_like(extra=extra))
        assert got is not None and got["value"] == "2018-09-30"

    def test_a_non_date_in_the_column_refuses(self) -> None:
        extra = [_w("PENDING", 118.7, 150.3, 620.0)]
        assert self._run(_bonita_like(extra=extra)) is None

    def test_a_far_away_date_is_outside_the_headers_reach(self) -> None:
        """bonita's own hazard: `AS OF DATE 8/31/2018` sits 259pt below the header in the
        same x-band. `HEADER_SEARCH_BAND` is what keeps the column from claiming it."""
        extra = [_w("8/31/2018", 118.7, 150.3, 640.0 - col.HEADER_SEARCH_BAND - 10.0)]
        got = self._run(_bonita_like(extra=extra))
        assert got is not None and got["value"] == "2018-09-30"

    def test_a_lone_form_caption_is_not_a_header_row(self) -> None:
        """`End Date:` beside a fill-in blank must never fire this rule: one caption is
        not a row that names columns."""
        words = [
            _w("EARNINGS", 100.0, 140.0, 649.0),
            _w("End", 100.0, 113.0, 640.0),
            _w("Date:", 115.0, 133.0, 640.0),
            _w("6/30/2018", 160.0, 195.0, 631.0),
        ]
        assert self._run(words) is None

    def test_bonita_end_to_end(self, flag_on) -> None:
        got = _fields(CONFIRM / "bonita_certificated_check_sample.pdf", "pay_stub")
        assert got["pay_period_end"]["value"] == "2018-09-30"
        assert got["pay_period_end"]["certainty"] == "low"

    def test_bonita_abstains_with_the_flag_off(self, flag_off) -> None:
        got = _fields(CONFIRM / "bonita_certificated_check_sample.pdf", "pay_stub")
        assert got["pay_period_end"]["certainty"] == "abstain"


# ─────────────────────────────────────── a titled hours block with a REGULAR row


def _hours_block(*, title=True, value="40.00", second_run=None, gap_x0=490.0, extra=()):
    """The CA DLSE piece-rate layout, reduced: `Total Hours in Pay Period` over
    `Regular: <value>`."""
    words = []
    if title:
        words += [
            _w("Total", 401.4, 419.0, 595.4, size=7.7, bold=True),
            _w("Hours", 421.0, 441.0, 595.4, size=7.7, bold=True),
            _w("in", 443.0, 449.0, 595.4, size=7.7, bold=True),
            _w("Pay", 451.0, 464.0, 595.4, size=7.7, bold=True),
            _w("Period", 466.0, 481.6, 595.4, size=7.7, bold=True),
        ]
    words += [
        _w("Regular:", 430.6, 456.5, 586.0, size=7.7, bold=True),
        _w(value, gap_x0, gap_x0 + 17.0, 586.0, size=7.7),
    ]
    if second_run is not None:
        words.append(_w(second_run, gap_x0 + 40.0, gap_x0 + 57.0, 586.0, size=7.7))
    return words + list(extra)


class TestHoursBlock:
    """`regular_hours` from a REGULAR row under a printed hours-block title. Bare REGULAR
    stays out of every vocabulary; the page's own title is what names the quantity."""

    CONVENTION = ex.LineBoxConvention()

    def _run(self, words):
        return col.hours_block_value(ex.group_lines(words), self.CONVENTION)

    def test_the_piecerate_shape_is_read(self) -> None:
        got = self._run(_hours_block())
        assert got is not None
        assert got["value"] == 40
        assert got["certainty"] == "low"
        assert "Total Hours in Pay Period" in got["notes"]

    def test_without_the_title_nothing_is_read(self) -> None:
        assert self._run(_hours_block(title=False)) is None

    def test_more_hours_than_a_month_holds_refuses(self) -> None:
        """The bonita hazard in this rule's terms: a REGULAR row whose number is a monthly
        amount, not hours. 744 = 31 days x 24 hours is a physical ceiling, not a knob."""
        assert self._run(_hours_block(value="6333.00")) is None

    def test_two_runs_beside_the_row_refuse(self) -> None:
        assert self._run(_hours_block(second_run="15.00")) is None

    def test_a_word_space_is_prose_not_a_column(self) -> None:
        assert self._run(_hours_block(gap_x0=460.0)) is None

    def test_two_regular_rows_refuse(self) -> None:
        extra = [
            _w("Regular:", 430.6, 456.5, 576.0, size=7.7, bold=True),
            _w("38.00", 490.0, 507.0, 576.0, size=7.7),
        ]
        assert self._run(_hours_block(extra=extra)) is None

    def test_piecerate_end_to_end(self, flag_on) -> None:
        got = _fields(CONFIRM / "ca_dlse_paystub_piecerate.pdf", "pay_stub")
        assert got["regular_hours"]["value"] == 40
        assert got["regular_hours"]["certainty"] == "low"

    def test_piecerate_abstains_with_the_flag_off(self, flag_off) -> None:
        got = _fields(CONFIRM / "ca_dlse_paystub_piecerate.pdf", "pay_stub")
        assert got["regular_hours"]["certainty"] == "abstain"
