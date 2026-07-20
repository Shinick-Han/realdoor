# -*- coding: utf-8 -*-
"""shredded.py -- amounts the text layer breaks into digit groups, read back only when
the page's own arithmetic closes over them.

THE LAYOUT THIS READS
---------------------
The Illinois DOL wage-notice sample prints its current-period amounts in a ruled grid,
and the text layer hands each amount back as separated digit groups::

    342  Regular  10 8 10 8 10 8   |2 40|   3,322.00     <- rate/hours day columns, then
    541  Regular  12 8 13 8        |2 00|   2,104.00        the This Period amount
    Gross Pay:                     |4 40|   5,426.00
    Total Deductions:              |1 78|   2,353.36
    Net Pay:                       |2 62|   3,072.64

`|4 40|` is one run of two all-digit words. The page prints 440; the text layer prints
its digits, in order, with a gap. `parse_value` rightly refuses "4 40" as money, so every
one of these fields abstains -- and no ordinary widening can fix that, because accepting
digit-space-digit as a number in general would read a rate column beside an hours column
("10 8") as 108.

WHAT LICENSES JOINING THE DIGITS
--------------------------------
Concatenation adds no digit and no separator: the only candidate reading of `4 40` this
module ever forms is 440. Whether that reading is *the page's own* is then decided the
way `core/verified.py` decides everything -- by identities the document prints about
itself, anchored at a quantity whose tokens are NOT shredded:

  A1 scale anchor   every earnings row's joined amount equals the sum of rate x hours
                    products formed from that row's own intact tokens, paired under the
                    header cells the page prints (`Rate` | `Hours`). 10x8+10x8+10x8 = 240
                    = `2 40`. This is the one identity that is not scale-invariant: the
                    rates and hours print all their digits, so their product pins the
                    magnitude that mere ratios cannot.
  A2 column sum     the joined earnings amounts, stacked in one x-aligned column, sum to
                    the joined amount on the row labelled GROSS PAY: 240 + 200 = 440.
  A3 total band     joined gross = joined TOTAL DEDUCTIONS + joined NET PAY, all three
                    labels printed by the page: 440 = 178 + 262.
  A4 cumulative     a joined amount may not exceed the intact amount printed beside it
     bound          under a column the page marks cumulative (`Year to Date`): a current
                    period is part of its year. 440 <= 5,426.00.

Any one failing kills the whole reading; there is no partial acceptance.

THE HAZARD, NAMED
-----------------
The wrong value this could manufacture is a mis-grouped magnitude: a form that boxes
dollars and cents (`4 40 | 00` meaning $440.00, or a drawn decimal rule the text layer
does not carry) concatenates to a number 100x the truth -- and A2 and A3 are ratios, so
they close at any uniform scale. A1 is the refusal: the products are computed from intact,
fully-printed rates and hours, and 100x the true amount does not equal 10x8+10x8+10x8.
A4 refuses the same error a second, independent way wherever a cumulative column is
printed. Falsification, measured before this was written: across all 77 corpus documents
(pack 24, uploads 26, wording hold-out 7, external 6, confirmation 14), a run of two or
more all-digit words occurs on exactly one document, the il_dol sample itself.

Like `core/verified.py`: no model, no new field labels beyond one anchor-only string
(TOTAL DEDUCTIONS names the identity, never a field), certainty capped at "low", and the
whole path lives under `REALDOOR_ARITHMETIC` -- with the flag at `0` this module is never
imported and `extract_document` is bit-identical to what it was.
"""
from __future__ import annotations

from typing import Any, Sequence

from core import arithmetic as ar
from core.extract import (
    VALUE_X_TOLERANCE,
    LineBoxConvention,
    Word,
    _join_run,
    _run_box,
    _split_runs,
    group_lines,
    normalize_label,
    parse_value,
)

#: Note prefix carried by every field this module produces, so a reader counting fields
#: can separate this path from the geometry and arithmetic paths without reading code.
SHREDDED_NOTE = "digit-grouped value accepted by anchored arithmetic (see core/shredded.py)"

#: The printed row labels the identities hang on. GROSS PAY and NET PAY are the pack's own
#: canonical labels; TOTAL DEDUCTIONS exists here only to close A3 and never becomes a
#: field. Closed and hand-written, like every vocabulary in this repository.
_ROW_LABELS = {
    "GROSS PAY": "gross_pay",
    "NET PAY": "net_pay",
    "TOTAL DEDUCTIONS": "_deductions",
}

#: The fields this module may emit. `_deductions` is deliberately absent.
EMITTABLE = ("gross_pay", "net_pay")

#: How far above a row a header row may sit and still name its columns -- the same
#: standing definition `core/columns.py` uses (`HEADER_SEARCH_BAND`), restated because
#: importing `core.columns` here would break the promise that `REALDOOR_COLUMNS=0` keeps
#: that module unimported.
_HEADER_BAND = 60.0


def _is_shredded(run: Sequence[Word]) -> bool:
    """Two or more words, every one of them nothing but digits."""
    return len(run) >= 2 and all(w.text.isdigit() for w in run)


def _joined(run: Sequence[Word]) -> int:
    return int("".join(w.text for w in run))


def _span(run: Sequence[Word]) -> tuple[float, float]:
    return min(w.x0 for w in run), max(w.x1 for w in run)


def _same_column(a: Sequence[Word], b: Sequence[Word]) -> bool:
    (a0, a1), (b0, b1) = _span(a), _span(b)
    return abs(a0 - b0) <= VALUE_X_TOLERANCE and abs(a1 - b1) <= VALUE_X_TOLERANCE


def _x_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return min(a[1], b[1]) - max(a[0], b[0]) > 0.0


def _is_header_cell(run: Sequence[Word]) -> bool:
    text = _join_run(run)
    return any(c.isalpha() for c in text) and not any(c.isdigit() for c in text)


def _is_cumulative(text: str) -> bool:
    lowered = text.lower()
    return "to date" in lowered or "ytd" in lowered


def _intact_value(run: Sequence[Word]) -> float | None:
    """One ordinary printed number (`3,322.00`), or None. Never reads a shredded run."""
    if len(run) != 1:
        return None
    parsed = ar.parse_number(run[0].text)
    return parsed[0] if parsed is not None else None


def _row_label(line: Sequence[Word]) -> str | None:
    for run in _split_runs(line):
        name = _ROW_LABELS.get(normalize_label(_join_run(run)))
        if name is not None:
            return name
    return None


def _sole_shredded(line: Sequence[Word]) -> list[Word] | None:
    """The line's one shredded run, or None if it has none or several."""
    shredded = [run for run in _split_runs(line) if _is_shredded(run)]
    return shredded[0] if len(shredded) == 1 else None


# --------------------------------------------------------------------------------------
# A1 -- the scale anchor: rate x hours pairs under the page's own header cells
# --------------------------------------------------------------------------------------


def _header_cells(
    lines: Sequence[Sequence[Word]], baseline: float, page: int
) -> list[list[Word]] | None:
    """The nearest header row above `baseline`, as its cells in x order, or None."""
    above = sorted(
        (
            line
            for line in lines
            if line
            and line[0].page == page
            and 0 < (line[0].baseline - baseline) <= _HEADER_BAND
        ),
        key=lambda line: line[0].baseline - baseline,
    )
    for line in above:
        cells = [run for run in _split_runs(line) if _is_header_cell(run)]
        if len(cells) >= 2:
            return sorted(cells, key=lambda c: c[0].x0)
    return None


def _anchored(lines: Sequence[Sequence[Word]], line: Sequence[Word], joined: int) -> bool:
    """Does this row's own printed arithmetic pin `joined` at full magnitude?

    The row's intact numeric tokens are attributed to the header cells above them; a
    token under a `Rate` cell pairs with the token under the immediately following
    `Hours` cell. Every rate token and every hours token must pair -- an odd one out
    means the attribution is not plain, and we refuse. The sum of the products must
    equal `joined` exactly.
    """
    cells = _header_cells(lines, line[0].baseline, line[0].page)
    if cells is None:
        return False
    shredded_words = {
        id(w) for run in _split_runs(line) if _is_shredded(run) for w in run
    }

    def _axis(index: int) -> str:
        text = normalize_label(_join_run(cells[index]))
        if _is_cumulative(_join_run(cells[index])):
            return "cumulative"
        if "RATE" in text.split():
            return "rate"
        if "HOURS" in text.split():
            return "hours"
        return "other"

    placed: list[tuple[int, float]] = []  # (cell index, value) for intact tokens
    for word in line:
        if id(word) in shredded_words:
            continue
        parsed = ar.parse_number(word.text)
        if parsed is None:
            continue
        hits = [i for i, cell in enumerate(cells) if _x_overlap((word.x0, word.x1), _span(cell))]
        if len(hits) != 1:
            return False  # a number no single header cell owns: not plain enough
        placed.append((hits[0], parsed[0]))

    placed.sort(key=lambda item: item[0])
    total = 0.0
    pairs = 0
    used: set[int] = set()
    for position, (index, value) in enumerate(placed):
        axis = _axis(index)
        if axis in ("cumulative", "other"):
            continue
        if position in used:
            continue
        if axis == "hours":
            return False  # an hours token with no rate token before it
        partner = position + 1
        if (
            partner >= len(placed)
            or _axis(placed[partner][0]) != "hours"
            or placed[partner][0] != index + 1
        ):
            return False  # a rate token whose neighbouring Hours cell holds nothing
        total += value * placed[partner][1]
        used.add(partner)
        pairs += 1
    return pairs > 0 and round(total, 2) == float(joined)


# --------------------------------------------------------------------------------------
# A4 -- the cumulative bound
# --------------------------------------------------------------------------------------


def _cumulative_spans(
    lines: Sequence[Sequence[Word]], page: int
) -> list[tuple[float, float]]:
    return [
        _span(run)
        for line in lines
        if line and line[0].page == page
        for run in _split_runs(line)
        if _is_cumulative(_join_run(run)) and not any(c.isdigit() for c in _join_run(run))
    ]


def _within_cumulative_bound(
    line: Sequence[Word],
    joined_run: Sequence[Word],
    joined: int,
    cumulative: Sequence[tuple[float, float]],
) -> bool:
    """False only when an intact amount under a printed cumulative column contradicts us."""
    right_edge = max(w.x1 for w in joined_run)
    for run in _split_runs(line):
        if run[0].x0 <= right_edge:
            continue
        value = _intact_value(run)
        if value is None:
            continue
        if any(_x_overlap(_span(run), span) for span in cumulative):
            if float(joined) > value:
                return False
    return True


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def recover(
    words: Sequence[Word],
    convention: LineBoxConvention,
    wanted: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """gross_pay / net_pay for one page, or {} -- meaning abstain, exactly as before.

    Everything must hold at once: three labelled rows (GROSS PAY, TOTAL DEDUCTIONS,
    NET PAY) each carrying exactly one shredded run, all in one x-aligned column; the
    band A3; the column sum A2 over the earnings rows above the gross row; the scale
    anchor A1 on every one of those earnings rows; and the cumulative bound A4 on every
    row it can be asked of. Any refusal returns {} and every field stays abstained.
    """
    lines = group_lines(words)

    labelled: dict[str, tuple[Sequence[Word], list[Word]]] = {}
    for line in lines:
        name = _row_label(line)
        if name is None:
            continue
        run = _sole_shredded(line)
        if run is None:
            continue
        if name in labelled:
            return {}  # the same label twice: the page has not said which row is which
        labelled[name] = (line, run)

    if set(labelled) != {"gross_pay", "_deductions", "net_pay"}:
        return {}
    gross_line, gross_run = labelled["gross_pay"]
    ded_line, ded_run = labelled["_deductions"]
    net_line, net_run = labelled["net_pay"]
    page = gross_run[0].page

    if not (_same_column(gross_run, ded_run) and _same_column(gross_run, net_run)):
        return {}

    gross, ded, net = _joined(gross_run), _joined(ded_run), _joined(net_run)
    if gross != ded + net:
        return {}  # A3

    # A2: every shredded run in the same column above the gross row is an earnings
    # amount, and together they must sum to the gross.
    earnings: list[tuple[Sequence[Word], list[Word]]] = []
    for line in lines:
        if not line or line[0].page != page:
            continue
        if line[0].baseline <= gross_line[0].baseline:
            continue
        for run in _split_runs(line):
            if _is_shredded(run) and _same_column(run, gross_run):
                earnings.append((line, run))
    if len(earnings) < 2:
        return {}  # one row proves nothing about a sum
    if sum(_joined(run) for _, run in earnings) != gross:
        return {}

    # A1 on every earnings row.
    if not all(_anchored(lines, line, _joined(run)) for line, run in earnings):
        return {}

    # A4 wherever a cumulative column is printed beside a row.
    cumulative = _cumulative_spans(lines, page)
    for line, run in [labelled["gross_pay"], labelled["_deductions"], labelled["net_pay"], *earnings]:
        if not _within_cumulative_bound(line, run, _joined(run), cumulative):
            return {}

    chain = (
        f"anchored at {' + '.join(str(_joined(r)) for _, r in earnings)} = {gross} from "
        f"rate x hours products of intact tokens under the page's own Rate/Hours header "
        f"cells; band {gross} = {ded} + {net} over the printed GROSS PAY / TOTAL "
        f"DEDUCTIONS / NET PAY rows; every joined amount within its printed "
        f"year-to-date bound"
    )
    out: dict[str, dict[str, Any]] = {}
    for name, (line, run) in (("gross_pay", labelled["gross_pay"]), ("net_pay", labelled["net_pay"])):
        if name not in wanted:
            continue
        value, _clean = parse_value(name, str(_joined(run)))
        out[name] = {
            "field": name,
            "value": value,
            "page": run[0].page,
            "bbox": _run_box(run, convention),
            "bbox_units": "pdf_points_bottom_left_origin",
            "certainty": "low",
            "evidence_kind": "extracted",
            "source_text": _join_run(run),
            "notes": f"{SHREDDED_NOTE} | {chain}",
        }
    return out
