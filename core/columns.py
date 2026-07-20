# -*- coding: utf-8 -*-
"""Read the column headers the document prints about itself.

On by default; ``REALDOOR_COLUMNS=0`` switches it off. With the flag off nothing in this
module is imported and `core.extract` behaves bit-for-bit as it did before it existed. It
shipped opt-in and was promoted after the measurement recorded in
`core.extract._arithmetic_enabled`: zero wrong values in every corpus under all four flag
combinations, and the pack bit-identical.

WHY THIS EXISTS
---------------
On the six published PDFs the extractor reads dates and almost nothing else. Three separate
things were stopping it, and only the third is interesting:

**1. The label and its value are not on the same `group_lines` line.** `group_lines` groups
by typographic baseline within 1.5pt. On the ADP statement the label is 9pt and the value
beside it is 7pt, and smaller type set to look vertically centred in the same ruled row
lands on a baseline 1.69pt higher::

    'Net Pay'   baseline 472.86   ink 470.91 - 479.91   (9pt)
    '$'         baseline 474.55   ink 473.03 - 480.03   (7pt)
    '532.76'    baseline 474.53   ink 473.17 - 480.17   (7pt)

Those are one row on the page and two lines in the model, so `_side_by_side_value` -- which
only ever looks along the label's own line -- found nothing to the right of `Net Pay` at all.
`_row` below asks the question the baseline cannot answer: **is the ink at the same height?**
Two words share a row when their glyph boxes overlap vertically by at least half the shorter
one's height. That is a statement about how type sits in a row, not a tuned number, and it
is measured on the glyph boxes `read_words` already carries.

**2. A bare currency symbol was counting as a rival value.** Still ADP::

    Net(91.4)  Pay(107.2)   $(195.9)   532.76(231.8)

Two runs to the right of the label, so the side-by-side rule calls the cell ambiguous and
abstains -- and one of the two is a lone dollar sign in the column rule, which is not a
value anybody could mean. `_is_bare_currency` drops a run whose **entire** text is currency
marks. Deliberately narrow: it never strips a symbol from inside a value, so "$943.45" is
untouched and still parses through `parse_value` exactly as before.

**3. The page states which column each number is in.** Also ADP, `Gross Pay`::

    Gross(91.4) Pay(116.2)   $(195.9)   707.75(231.8-257.0)   0.00(305.0-321.8)

Two numbers, and along the row alone there is no way to tell them apart -- correctly, the
first-number-wins convention was refused earlier in this project. But 38pt above sits the
row the document prints to say what its own columns are::

    Earnings(26.6-65.5)  Rate(111.8-131.8)  Hours(167.8-194.4)
    This Period(207.0-256.7)   Year to Date(274.6-329.0)

`707.75` spans 231.8-257.0 and `This Period` spans 207.0-256.7. `0.00` spans 305.0-321.8 and
`Year to Date` spans 274.6-329.0. The spans agree to within a third of a point. This is not a
layout convention we are imposing; it is a label the document prints about itself, read the
same way a person reads it.

WHY IT CANNOT PRODUCE A WRONG VALUE
-----------------------------------
The strong guarantee is structural rather than argumentative. `_scan_page` calls
`column_value` **only when the existing three-rule chain produced no value** -- neither
`_resolve_value`, nor `_side_by_side_value`, nor `_caption_value` returned an answer. So the
worst this module can do to a field that reads correctly today is nothing at all: there is no
code path by which it can replace, move or re-box an existing value. It converts abstentions,
or it does nothing.

That leaves one question -- can it convert an abstention into a *wrong* value -- and every
test below is a refusal:

* the run must sit right of the label, past `SIDE_BY_SIDE_MIN_GAP`, so prose that opens with
  a known label cannot read as a label-value pair;
* it must sit left of the next label, where "next label" now includes labels found anywhere
  on the visual row rather than only on the baseline group, which is **stricter** than the
  rule it replaces;
* with one candidate left, that is the answer -- exactly the existing side-by-side rule,
  reached over a row instead of a line;
* with more than one, a header row must be found, every candidate must fall inside exactly
  one header cell, no two candidates may claim the same cell, and exactly one of the matched
  headers may be a non-cumulative column. Any other reading and we abstain;
* and the value must still parse as the field's type, through the unchanged `parse_value`.

Nothing here widens the label vocabulary, and nothing here relaxes `parse_value`.
"""
from __future__ import annotations

from typing import Any, Sequence

from core.extract import (
    SIDE_BY_SIDE_MIN_GAP,
    Word,
    LineBoxConvention,
    _build_value_field,
    _join_run,
    _split_runs,
    normalize_label,
)

# --------------------------------------------------------------------------------------
# Constants, each with the measurement it came from
# --------------------------------------------------------------------------------------

#: Two words share a visual row when their glyph boxes agree vertically at **IoU >= 0.5** --
#: the same measure and the same threshold this repository already uses to decide whether an
#: extracted box agrees with the gold box (`verify.py`: "IoU>0.5 159/159"). Reusing the
#: project's own standing definition of "these two boxes are the same thing" is the reason
#: this number is not a knob fitted to the files in hand.
#:
#: It was first written as "half the *shorter* box", and that produced a wrong value, which
#: is worth recording because it is the only wrong value this work generated. On page 3 of
#: the federal LES the form's item-number callouts are set in 12pt and offset between rows::
#:
#:     'Net Pay'  ink 537.90 - 547.86  (9.96pt)      <- the label
#:     '3'        ink 531.31 - 543.31  (12pt)        <- a callout marker, not a value
#:
#: They overlap by 5.41pt, which is 54% of the shorter box and clears a shorter-box test --
#: so `Net Pay` read as 3.0, confidently and with an honest box drawn around the wrong glyph.
#: By IoU the same pair scores 5.41/16.55 = 0.33 and is refused, while the ADP rows this
#: rule exists to join score 0.73. A tall glyph that merely clips the edge of a row is not
#: in the row, and IoU is what says so; a shorter-box test cannot.
ROW_INK_OVERLAP = 0.5

#: How far above a value row we are willing to look for the header row that names its
#: columns. The ADP earnings header sits 35.7pt above the `Gross Pay` row with two data rows
#: in between; this reaches it without reaching the next block of the form.
HEADER_SEARCH_BAND = 60.0

#: A candidate's x-span must fall inside a header cell's x-span, allowing this much overhang.
#: The worst real overhang measured is 0.30pt (ADP `707.75` right edge 257.04 against
#: `This Period` right edge 256.74). Uniqueness, not this number, is what does the work.
COLUMN_SPAN_TOLERANCE = 2.0

#: Characters that are a currency mark and nothing else.
CURRENCY_MARKS = frozenset("$€£¥₩¢₹₪₫₱฿")

#: What makes a column a *cumulative* one rather than the current period. Derived from the
#: header text the documents themselves print: ADP writes "Year to Date", UNC and UTEP write
#: "YTD". Those are one concept and its own abbreviation, not two vocabulary entries, and
#: they are the only thing recognised here. Everything else is simply "not cumulative" --
#: there is deliberately no list of period-column names ("This Period", "Current", ...),
#: because such a list would be a convention we invented rather than a word the page prints.
CUMULATIVE_MARKERS = ("to date", "ytd")


# --------------------------------------------------------------------------------------
# The visual row
# --------------------------------------------------------------------------------------


def _ink_band(run: Sequence[Word]) -> tuple[float, float]:
    return min(w.glyph_bottom for w in run), max(w.glyph_top for w in run)


def _shares_row(word: Word, low: float, high: float) -> bool:
    """Does this word's ink sit at the same height as the band [low, high]?

    Vertical intersection-over-union, so a tall glyph that overlaps the row's edge is judged
    on how much of the *combined* extent the two share rather than on how much of the smaller
    one is covered. See `ROW_INK_OVERLAP`.
    """
    intersection = min(word.glyph_top, high) - max(word.glyph_bottom, low)
    if intersection <= 0:
        return False
    union = max(word.glyph_top, high) - min(word.glyph_bottom, low)
    if union <= 0:
        return False
    return intersection / union >= ROW_INK_OVERLAP


def _row(lines: Sequence[Sequence[Word]], label_run: Sequence[Word]) -> list[Word]:
    """Every word on the label's page whose ink sits at the label's own height."""
    low, high = _ink_band(label_run)
    page = label_run[0].page
    words = [
        w
        for line in lines
        for w in line
        if w.page == page and _shares_row(w, low, high)
    ]
    return sorted(words, key=lambda w: w.x0)


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


def _is_bare_currency(run: Sequence[Word]) -> bool:
    """Is this run nothing but a currency mark?

    Narrow on purpose. `'$'` is dropped; `'$943.45'` is not touched, and neither is any run
    that carries a digit or a letter anywhere in it.
    """
    text = _join_run(run).replace(" ", "")
    return bool(text) and all(character in CURRENCY_MARKS for character in text)


def _barrier(row: Sequence[Word], label_words: frozenset[int], label_end: float) -> float:
    """x0 of the first label word on this row to the right of our label, else infinity.

    `_scan_page` computes the column's right edge from the labels on the *baseline group*.
    Reading across the visual row can see labels that group did not, so the boundary is
    recomputed here and only ever narrows: a header row such as
    `EMPLOYEE | PAY DATE | REGULAR HOURS` still leaves an empty span between neighbours and
    still produces no candidate at all.
    """
    starts = [w.x0 for w in row if id(w) in label_words and w.x0 > label_end]
    return min(starts) if starts else float("inf")


def _candidates(
    row: Sequence[Word],
    label_run: Sequence[Word],
    column_right: float,
    label_words: frozenset[int],
) -> list[list[Word]]:
    label_end = max(w.x1 for w in label_run)
    right_edge = min(column_right, _barrier(row, label_words, label_end))
    inside = [
        w
        for w in row
        if w.x0 >= label_end and w.x0 < right_edge and id(w) not in label_words
    ]
    if not inside:
        return []
    return [run for run in _split_runs(inside) if not _is_bare_currency(run)]


# --------------------------------------------------------------------------------------
# Header attribution
# --------------------------------------------------------------------------------------


def _is_header_cell(run: Sequence[Word]) -> bool:
    """A header cell is words. A row of numbers is data, however well it lines up.

    Without this the ADP earnings rows above `Gross Pay` would qualify -- `111.75` sits at
    exactly the x-span of `707.75`, because they are the same column -- and the "header" we
    matched against would be another row of the matrix rather than the row that names it.
    """
    text = _join_run(run)
    return any(c.isalpha() for c in text) and not any(c.isdigit() for c in text)


def _span(run: Sequence[Word]) -> tuple[float, float]:
    return min(w.x0 for w in run), max(w.x1 for w in run)


def _contained(inner: tuple[float, float], outer: tuple[float, float]) -> bool:
    return (
        inner[0] >= outer[0] - COLUMN_SPAN_TOLERANCE
        and inner[1] <= outer[1] + COLUMN_SPAN_TOLERANCE
    )


def _is_cumulative(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in CUMULATIVE_MARKERS)


def _attribute(
    lines: Sequence[Sequence[Word]],
    candidates: Sequence[Sequence[Word]],
) -> tuple[list[Word], str] | None:
    """Pick the candidate the page's own header row puts in the current-period column.

    Returns `(run, header_text)`, or None -- meaning abstain -- if the page does not say
    plainly enough which column is which.
    """
    baseline = max(run[0].baseline for run in candidates)
    page = candidates[0][0].page
    above = sorted(
        (
            line
            for line in lines
            if line
            and line[0].page == page
            and 0 < (line[0].baseline - baseline) <= HEADER_SEARCH_BAND
        ),
        key=lambda line: line[0].baseline - baseline,
    )

    for line in above:
        cells = [run for run in _split_runs(line) if _is_header_cell(run)]
        if len(cells) < 2:
            continue
        matched: list[tuple[int, str]] = []
        for run in candidates:
            hits = [i for i, cell in enumerate(cells) if _contained(_span(run), _span(cell))]
            if len(hits) != 1:
                matched = []
                break
            matched.append((hits[0], _join_run(cells[hits[0]])))
        if not matched:
            continue  # this row does not describe these columns; try the next one up
        if len({index for index, _ in matched}) != len(matched):
            return None  # two candidates in one cell: the row is not a column header
        current = [
            (run, text)
            for run, (_, text) in zip(candidates, matched)
            if not _is_cumulative(text)
        ]
        if len(current) != 1:
            return None  # no current-period column, or more than one. Abstain.
        return current[0]
    return None


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def column_value(
    lines: Sequence[Sequence[Word]],
    label_run: Sequence[Word],
    column_right: float,
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
    label_words: frozenset[int],
    header_words: frozenset[int] = frozenset(),
) -> dict[str, Any] | None:
    """The value beside this label, read across the visual row. None means abstain.

    Called only for fields the ordinary rules left without a value -- see `_scan_page`.

    `header_words` is passed straight through to `_build_value_field`, which refuses a
    caption-shaped run for a free-text field -- see `core.extract._caption_refusal`. This
    module therefore inherits the refusal rather than restating it.
    """
    row = _row(lines, label_run)
    candidates = _candidates(row, label_run, column_right, label_words)
    if not candidates:
        return None

    label_end = max(w.x1 for w in label_run)
    if candidates[0][0].x0 - label_end < SIDE_BY_SIDE_MIN_GAP:
        return None

    if len(candidates) == 1:
        return _build_value_field(
            candidates[0], field_name, convention, is_exact,
            "value read from the same row as its label, in the column to its right",
            header_words=header_words,
        )

    attributed = _attribute(lines, candidates)
    if attributed is None:
        return None
    run, header = attributed
    return _build_value_field(
        run, field_name, convention, is_exact,
        f"value read from the same row as its label, in the column the page's own header "
        f"row names {header!r}",
        header_words=header_words,
    )


# --------------------------------------------------------------------------------------
# The two-axis table cell: a field with no label of its own anywhere on the page
# --------------------------------------------------------------------------------------
# Everything above starts from a label the vocabulary recognises. An earnings matrix names
# some fields differently: no cell says "REGULAR HOURS", but the page prints a row word and
# a column header whose crossing *is* the field's name, read the same way a person reads a
# table. ADP prints the header row `Earnings | Rate | Hours | This Period | Year to Date`
# and under it the row `Regular 14.9000 40.00 596.00`; UTEP prints `Regular 74.25 ...`
# under `Description | Pay Rate | Current Hours | ...`; the federal LES prints
# `Gross 1813.00 29739.00` under `Current | YTD`.
#
# The rule reads a cell ONLY when both axes are printed by the page:
#
#   (a) the row's **first** cell matches a small closed table of row names, and
#   (b) the candidate sits under exactly one cell of a header row whose text names the
#       axis the field needs (HOURS, RATE, CURRENT).
#
# Neither axis alone may resolve anything, and that is why the deliberate exclusion of
# bare RATE / HOURS / REGULAR from the *label* vocabulary stays exactly as it is: a bare
# row word beside a number is the "first number wins" rule this project already refused.
# The ADP row above is the measured proof: the first number right of "Regular" is the
# RATE, 14.9000, and a side-by-side REGULAR -> regular_hours rule would confidently emit
# 14.90 as the hours. This rule answers 40.00 because the header cell above 40.00 says
# `Hours`, which is the page's own word for that column.
#
# Why the row word must be the row's FIRST cell: the bonita certificated check prints
# `C M | REGULAR | 9/30/2018 | 6,333.00 | 23.00 | 6,333.00` under a header row that
# includes `RATE` -- and 6,333.00 in the RATE column is a *monthly* figure on a document
# whose truth records hourly_rate as absent. "REGULAR appears somewhere in the row" would
# read it; "REGULAR is the row's name cell" refuses it, because the row's name cell there
# is `C M`. The il_dol client rows (`342 | Regular | ...`) are refused the same way.
#
# Every other test is a refusal, each pinned to a document that exhibits the hazard:
#   * more than one row on the page carries the row name -> refuse (the LES layout prints
#     adjustment rows under the same row word, and the page has not said which is which);
#   * the header cell over the candidate is cumulative -> not the current period, via the
#     unchanged `CUMULATIVE_MARKERS` (UTEP's `YTD Hours` next to `Current Hours`);
#   * the candidate sits under no header cell, or under two -> refuse (UNC prints two bare
#     `Hours` headers -- current and YTD -- in one row, so its hours column abstains);
#   * two candidates under one cell -> the row above is not describing these columns.
#
# Certainty is capped at "low" whatever parses: no label of the field's own names it, so
# like the arithmetic path this rule never earns the "high" that belongs to the geometry
# the gold was measured against.

#: field -> (row name, axis word). Closed and hand-written, like the label tables. The row
#: name is what the page prints in the row's first cell; the axis word is what the header
#: row prints over the value. Both are compared through `normalize_label`, so `Regular`
#: and `REGULAR:` are one word. `gross_pay`'s axis is CURRENT because a summary row names
#: the quantity itself (`Gross`) and the column names the period -- the LES prints
#: `Current | YTD` over `Gross 1813.00 29739.00`.
TABLE_ROW_AXES: dict[str, tuple[str, str]] = {
    "regular_hours": ("REGULAR", "HOURS"),
    "hourly_rate": ("REGULAR", "RATE"),
    "gross_pay": ("GROSS", "CURRENT"),
}


def _is_numeric_run(run: Sequence[Word]) -> bool:
    """Is this run one number, allowing the currency mark and thousands commas it wears?

    A matrix cell candidate has to be a number before any header can name it. This keeps
    ADP's `Sample Check` watermark text and the LES's `Status | Withholding` prose out of
    the candidate set entirely -- they are not readings this rule could ever emit, so they
    are not allowed to trigger its refusals either.
    """
    text = _join_run(run).replace("$", "").replace(",", "").strip()
    if not text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _x_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > 0.0


def _attribute_axis(
    lines: Sequence[Sequence[Word]],
    candidates: Sequence[Sequence[Word]],
    axis_word: str,
) -> tuple[list[Word], str] | None:
    """Pick the candidate whose header cell prints the axis word. None means abstain.

    Same shape as `_attribute` -- the same header-row search band, the same
    `_is_header_cell` test, the same one-candidate-one-cell uniqueness, the same
    `CUMULATIVE_MARKERS` -- with two deliberate differences:

    * **A candidate claims a cell by sharing ink with it, not by fitting inside it.**
      `_attribute`'s containment test was measured against amount columns, where the
      header (`This Period`) is wider than the value under it. A matrix's quantity
      columns are the other way round: ADP sets `40.00` at 178.4-199.4 under a `Hours`
      header at 167.8-194.4, five points of overhang, because the column is aligned on
      the decimal rather than on the header's edges. Requiring containment there refuses
      the exact cells this rule exists to read. Sharing x-extent with exactly one header
      cell -- and refusing on zero or two -- is the same "the page says which column"
      question asked in a way a decimal-aligned column can answer.
    * **The winning cell must print the axis word** (and still must not be cumulative).
      `_attribute` wants the only non-cumulative column; here several non-cumulative
      columns coexist (`Rate`, `Hours`, `This Period`) and the axis word is what picks
      one. If no candidate sits under a cell printing the word, or two do (UNC's twin
      bare `Hours` headers, current beside YTD), the page has not said which cell is
      meant, and we abstain.
    """
    baseline = max(run[0].baseline for run in candidates)
    page = candidates[0][0].page
    above = sorted(
        (
            line
            for line in lines
            if line
            and line[0].page == page
            and 0 < (line[0].baseline - baseline) <= HEADER_SEARCH_BAND
        ),
        key=lambda line: line[0].baseline - baseline,
    )

    for line in above:
        cells = [run for run in _split_runs(line) if _is_header_cell(run)]
        if len(cells) < 2:
            continue
        matched: list[tuple[int, str]] = []
        for run in candidates:
            hits = [i for i, cell in enumerate(cells) if _x_overlap(_span(run), _span(cell))]
            if len(hits) != 1:
                matched = []
                break
            matched.append((hits[0], _join_run(cells[hits[0]])))
        if not matched:
            continue  # this row does not describe these columns; try the next one up
        if len({index for index, _ in matched}) != len(matched):
            return None  # two candidates in one cell: the row is not a column header
        named = [
            (run, text)
            for run, (_, text) in zip(candidates, matched)
            if axis_word in normalize_label(text) and not _is_cumulative(text)
        ]
        if len(named) != 1:
            return None  # the axis word names no cell here, or more than one. Abstain.
        return named[0]
    return None


def table_cell_value(
    lines: Sequence[Sequence[Word]],
    field_name: str,
    convention: LineBoxConvention,
) -> dict[str, Any] | None:
    """The value in the table cell both axes name, or None -- meaning abstain.

    Called only for fields every label-anchored rule left blank -- see the gate in
    `core.extract.extract_fields_from_page`. Like `column_value`, there is no code path by
    which this can replace, move or re-box a value something else found.
    """
    axes = TABLE_ROW_AXES.get(field_name)
    if axes is None:
        return None
    row_word, axis_word = axes

    rows = [
        runs
        for line in lines
        for runs in [_split_runs(line)]
        if runs and normalize_label(_join_run(runs[0])) == row_word
    ]
    # Zero rows: the page prints no such row. Two or more: the LES-style adjustment
    # layout, where the same row word appears once per adjustment and nothing printed
    # says which row is the period's own. Either way, abstain.
    if len(rows) != 1:
        return None

    candidates = [run for run in rows[0][1:] if _is_numeric_run(run)]
    if not candidates:
        return None

    named = _attribute_axis(lines, candidates, axis_word)
    if named is None:
        return None
    run, header = named
    field = _build_value_field(
        run, field_name, convention, True,
        f"value read from a table cell named jointly by its row's first cell "
        f"{row_word.title()!r} and the header cell {header!r} the page prints above it",
    )
    if field is None:
        return None
    # No label of this field's own exists anywhere on the page, so however cleanly the
    # value parses, this is never the geometry the gold measured -- cap it like the
    # arithmetic path caps its own answers.
    field["certainty"] = "low"
    return field
