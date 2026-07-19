# -*- coding: utf-8 -*-
"""
arithmetic.py -- the identities a pay stub prints about itself, and nothing else.

WHY THIS FILE EXISTS
--------------------
`core/extract.py` finds a value by asking "what is printed *there*?" -- under the label,
inside `VALUE_Y_WINDOW`, aligned to `VALUE_X_TOLERANCE`. Measured on six real published
PDFs that guard is excellent at refusing (0 wrong out of 44) and poor at reading (7 of 28
values found). The misses are geometry: the label is visible and the value is outside the
window. The federal LES centres its values in boxes; ADP prints the value for `Gross Pay`
on a baseline 1.69pt *above* the label's.

Widening the window is the obvious move and it is the one this project has already
established as dangerous -- a geometry miss reads the *neighbouring* cell and produces a
confident wrong figure where an honest blank stood.

So this module inverts the question. Instead of "what is the gross pay?" (generation, which
we are bad at) it answers "is 707.75 the gross pay?" (verification, which we are good at).
The evidence it uses is the arithmetic the document prints about itself:

    row product   rate_i x hours_i = amount_i, on one printed line
    column sum    a consecutive run of one aligned column equals a printed total
    total band    deductions + net = gross

None of these mention a word. They are properties of the numbers, so a document whose label
vocabulary we do not know can still be read, and a document that prints numbers that do not
agree gets nothing.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
* **`hours x rate = gross` is not an identity.** Measured on all four real stubs it FAILS
  every time -- ADP 596.00 != 707.75, UNC 1515.84 != 1627.74, LES 1710.40 != 1813.00 --
  because gross is a sum of several earning rows. A mismatch here is therefore SILENCE, never
  refutation. Using it to reject would kill correct values.
* **Tolerance is frozen.** `product_tolerance` is `0.005 * hours + 0.005`, which is exactly
  the display-rounding budget: the LES prints rate 21.38 where the true rate is 21.375, so at
  80 hours the printed product is 0.40 off. Widening this is the arithmetic version of
  widening the geometry window. Any change requires a measurement first.
* **No model.** This module imports nothing that can reach a network. It is a search over the
  page's own number tokens.

THE LOAD-BEARING MEASUREMENT, AND A CORRECTION TO IT
----------------------------------------------------
Arithmetic alone is not evidence, because a page of 113 numbers contains coincidences. The
design this module implements rested on a measurement stating that free subset-sum finds 116
coincidental matches on the UNC advice and 182 on the LES, and that constraining the search to
*a consecutive run within one aligned column* drops both to **zero**.

**The zero does not reproduce here, and the difference matters enough to state plainly.**
Counting distinct printed totals reachable by a search of size <= 3 (`--targets` in
`scripts/measure_arithmetic_identities.py`):

    document      constrained    free
    ext_adp                1        1
    ext_unc                6       36
    ext_utep               6        8
    ext_les                8       24

The column constraint shrinks the candidate space by roughly three to six times on a dense
page. It does not empty it. Real accidental hits survive it -- on the UNC advice
`8.00 + 72.00 = 80.00` joins two unrelated year-to-date leave figures into the current-period
hours total, and `20.346846 + 20.346846 = 40.69` lands on a printed earnings amount.

So geometry alone is NOT what makes this safe, and anything built as though it were would be
built on sand. What makes it safe is the rest of the stack in `core/verified.py`: the column
sum has to be anchored by a row product, the row product's hours factor has to pass a physical
bound derived from the document, and after all of that exactly one distinct value has to
survive. Every one of the coincidences above dies at the anchor or at the uniqueness test,
which is measurable end to end and is what `core/test_arithmetic.py` asserts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from core.extract import VALUE_X_TOLERANCE, Word

# --------------------------------------------------------------------------------------
# Number tokens
# --------------------------------------------------------------------------------------

#: What counts as a number on the page. Deliberately narrow: an optional currency sign, an
#: optional sign, digits with optional thousands separators, an optional fraction. A token
#: like "07/23/2017" or "XXXXX000000" is not a number and never enters the search.
_NUMBER_RE = re.compile(r"^\$?-?\d[\d,]*(?:\.\d+)?-?$")

#: Trailing glyphs that decorate an amount without changing it. The ADP statement prints its
#: deduction amounts with a trailing "-" as a *separate* word, but other generators attach it.
_TRAILING = "-*"


@dataclass(frozen=True)
class NumberToken:
    """One printed number, with the page coordinates it was printed at.

    `index` is the position of this word in `read_words(page)` for its page. It exists so a
    proposal can *name* a location, and the grounding veto can go back and check that the
    text really is there. A value nobody printed has no index to name.
    """

    page: int
    index: int
    text: str
    value: float
    x0: float
    x1: float
    baseline: float
    decimals: int

    @property
    def is_money_shaped(self) -> bool:
        """Two decimal places, which is how money is printed and hours usually are not."""
        return self.decimals == 2


def parse_number(text: str) -> tuple[float, int] | None:
    """(value, decimal places) for a printed number, or None if it is not one."""
    raw = text.strip().rstrip(_TRAILING).strip()
    if not _NUMBER_RE.match(text.strip()):
        return None
    cleaned = raw.replace("$", "").replace(",", "")
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    decimals = len(cleaned.partition(".")[2])
    return value, decimals


def number_tokens(words: Sequence[Word]) -> list[NumberToken]:
    """Every printed number on one page, carrying its word index."""
    out: list[NumberToken] = []
    for index, word in enumerate(words):
        parsed = parse_number(word.text)
        if parsed is None:
            continue
        value, decimals = parsed
        out.append(
            NumberToken(
                page=word.page,
                index=index,
                text=word.text,
                value=value,
                x0=word.x0,
                x1=word.x1,
                baseline=word.baseline,
                decimals=decimals,
            )
        )
    return out


# --------------------------------------------------------------------------------------
# Columns and lines -- the geometry that binds coincidence
# --------------------------------------------------------------------------------------

#: Two numbers share a baseline when their baselines agree to this many points. Matches
#: `core.extract.group_lines`, which is the same question asked of the same pages.
BASELINE_TOLERANCE = 1.5


@dataclass(frozen=True)
class Column:
    """Numbers printed one above another on a shared edge, top to bottom."""

    alignment: str  # "left" or "right"
    tokens: tuple[NumberToken, ...]


def _cluster(tokens: Sequence[NumberToken], edge, tolerance: float) -> list[list[NumberToken]]:
    """Group tokens whose chosen edge agrees to within `tolerance`, greedily and stably."""
    groups: list[list[NumberToken]] = []
    for token in sorted(tokens, key=edge):
        if groups and abs(edge(token) - edge(groups[-1][-1])) <= tolerance:
            groups[-1].append(token)
        else:
            groups.append([token])
    return groups


def build_columns(tokens: Sequence[NumberToken], min_height: int = 2) -> list[Column]:
    """Every left-aligned and every right-aligned column of numbers on one page.

    Both alignments are built rather than one being chosen, because real documents use both
    and the choice is not ours to make: ADP right-aligns its amounts on x1=257.04, and the
    UTEP handout left-aligns the same kind of column on x0=310.0 because every amount carries
    a `$`. A run has to be consecutive within *one* of these columns; that is the constraint
    the coincidence measurement was made under.
    """
    out: list[Column] = []
    for alignment, edge in (("left", lambda t: t.x0), ("right", lambda t: t.x1)):
        for group in _cluster(tokens, edge, VALUE_X_TOLERANCE):
            if len(group) < min_height:
                continue
            ordered = tuple(sorted(group, key=lambda t: -t.baseline))
            out.append(Column(alignment=alignment, tokens=ordered))
    return out


def build_lines(tokens: Sequence[NumberToken]) -> list[tuple[NumberToken, ...]]:
    """Numbers printed side by side on one baseline, left to right."""
    lines: list[list[NumberToken]] = []
    for token in sorted(tokens, key=lambda t: (-t.baseline, t.x0)):
        if lines and abs(lines[-1][0].baseline - token.baseline) <= BASELINE_TOLERANCE:
            lines[-1].append(token)
        else:
            lines.append([token])
    return [tuple(sorted(line, key=lambda t: t.x0)) for line in lines]


# --------------------------------------------------------------------------------------
# The three identities
# --------------------------------------------------------------------------------------

#: Display-rounding budget for `rate x hours`. A rate printed to 2dp can be up to 0.005 away
#: from the true rate, and that error is multiplied by the hours; the product's own printed
#: value carries another 0.005. FROZEN -- see the module docstring.
def product_tolerance(hours: float) -> float:
    return 0.005 * abs(hours) + 0.005


#: Display-rounding budget for a sum of n printed values compared against a printed total.
#: Each addend and the total may each be up to 0.005 from their true value. Linear in n
#: because rounding errors add; it is not a free parameter.
def sum_tolerance(n: int) -> float:
    return 0.005 * (n + 1)


@dataclass(frozen=True)
class RowProduct:
    """`rate x hours = amount`, all three printed on one line."""

    rate: NumberToken
    hours: NumberToken
    amount: NumberToken

    @property
    def exact(self) -> bool:
        return abs(self.rate.value * self.hours.value - self.amount.value) < 1e-9


def find_row_products(tokens: Sequence[NumberToken]) -> list[RowProduct]:
    """Every (rate, hours, amount) triple printed on one baseline that multiplies out.

    Both assignments of the two factors are emitted -- `21.38 x 80.00` and `80.00 x 21.38`
    are the same product, and nothing in the arithmetic says which factor is the rate. The
    caller resolves that by other measurement or abstains; see `core/verified.py`.
    """
    out: list[RowProduct] = []
    for line in build_lines(tokens):
        if len(line) < 3:
            continue
        for i, a in enumerate(line):
            for j, b in enumerate(line):
                if i == j or a.value == 0 or b.value == 0:
                    continue
                for k, product in enumerate(line):
                    if k in (i, j):
                        continue
                    if abs(a.value * b.value - product.value) <= product_tolerance(b.value):
                        out.append(RowProduct(rate=a, hours=b, amount=product))
    return out


@dataclass(frozen=True)
class RunSum:
    """A consecutive run of an aligned column (or of one line) equalling a printed total."""

    kind: str  # "column" or "line"
    alignment: str
    run: tuple[NumberToken, ...]
    total: NumberToken

    @property
    def exact(self) -> bool:
        return abs(sum(t.value for t in self.run) - self.total.value) < 1e-9


def _runs(sequence: Sequence[NumberToken], min_len: int) -> Iterable[tuple[NumberToken, ...]]:
    for start in range(len(sequence)):
        for end in range(start + min_len, len(sequence) + 1):
            yield tuple(sequence[start:end])


def find_run_sums(
    tokens: Sequence[NumberToken], min_len: int = 2, max_len: int = 16
) -> list[RunSum]:
    """Every consecutive run of an aligned column, or of one line, that hits a printed total.

    This narrows the search a great deal but it does **not** eliminate coincidence -- see the
    correction in the module docstring. Treat the output as a shortlist to be refuted, never as
    a set of facts. `core.verified` is where the refuting happens.
    """
    by_value: dict[float, list[NumberToken]] = {}
    for token in tokens:
        by_value.setdefault(round(token.value, 6), []).append(token)

    out: list[RunSum] = []
    sequences: list[tuple[str, str, tuple[NumberToken, ...]]] = [
        ("column", column.alignment, column.tokens) for column in build_columns(tokens)
    ]
    sequences += [("line", "line", line) for line in build_lines(tokens) if len(line) >= min_len]

    for kind, alignment, sequence in sequences:
        members = {id(t) for t in sequence}
        for run in _runs(sequence, min_len):
            if len(run) > max_len:
                continue
            total_value = sum(t.value for t in run)
            if total_value == 0:
                continue
            budget = sum_tolerance(len(run))
            for candidate_value, candidates in by_value.items():
                if abs(candidate_value - total_value) > budget:
                    continue
                for total in candidates:
                    if id(total) in {id(t) for t in run}:
                        continue
                    # A total printed *inside* the same run's span would be a member of the
                    # run, so it is excluded above. A total elsewhere in the same column, or
                    # anywhere else on the page, is allowed -- what binds the coincidence is
                    # the run being consecutive, not where the total is printed.
                    if kind == "line" and id(total) not in members:
                        continue
                    out.append(
                        RunSum(kind=kind, alignment=alignment, run=run, total=total)
                    )
    return out


def reachable_totals(tokens: Sequence[NumberToken], max_size: int = 3) -> set[float]:
    """Distinct printed totals a *constrained* search can hit. The honest candidate space.

    This, not the raw number of matching runs, is what the uniqueness test in `core.verified`
    has to survive: the same identity is found several times over (a column clusters on both
    edges, and trailing zeros extend a run without changing its sum), so counting runs
    overstates the search and counting the values it can reach does not.
    """
    return {
        round(s.total.value, 2)
        for s in find_run_sums(tokens, min_len=2, max_len=max_size)
    }


def free_reachable_totals(tokens: Sequence[NumberToken], max_size: int = 3) -> set[float]:
    """The same question with the geometry removed: the negative control for `reachable_totals`."""
    from itertools import combinations

    printed = {round(t.value, 2) for t in tokens if t.value != 0}
    pool = [t for t in tokens if t.value != 0]
    out: set[float] = set()
    for size in range(2, max_size + 1):
        for subset in combinations(pool, size):
            total = round(sum(t.value for t in subset), 2)
            if total in printed and total not in {round(t.value, 2) for t in subset}:
                out.add(total)
    return out


def free_subset_sums(tokens: Sequence[NumberToken], max_size: int = 4) -> int:
    """The negative control: how many *unconstrained* subsets hit a printed total.

    This is the number the geometry constraint has to beat. It is measured, not assumed, and
    `scripts/measure_arithmetic_identities.py` prints both sides.
    """
    from itertools import combinations

    values = {round(t.value, 2) for t in tokens if t.value != 0}
    hits = 0
    pool = [t for t in tokens if t.value != 0]
    for size in range(2, max_size + 1):
        for subset in combinations(pool, size):
            total = round(sum(t.value for t in subset), 2)
            if total in values and total not in {round(t.value, 2) for t in subset}:
                hits += 1
    return hits
