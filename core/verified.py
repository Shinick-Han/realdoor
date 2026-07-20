# -*- coding: utf-8 -*-
"""
verified.py -- acceptance built out of refusals.

THE ASYMMETRY THIS EXPLOITS
---------------------------
Measured on six real published PDFs whose ground truth a human transcribed from page images
*before* the extractor ran once: 28 fields that should carry a value produced 7 correct, and
16 fields that should be absent produced 0 false positives. **This system is accurate about
saying "I cannot read that" and poor at reading.**

So do not ask it to read. Ask it to refuse. "What is the gross pay?" is generation and we are
bad at it. "Is 707.75 the gross pay?" is verification and we are good at it. This module turns
the second question into the answer to the first: a deterministic proposer enumerates every
number printed on the page, and a stack of refusals removes all but one.

THE ELEMENTS
------------
Vetoes -- any one failing kills the candidate outright:

  V1 grounding   the text at the named word index really is the proposed value. The proposer
                 must name a `(page, index)`, so a value nobody printed has no index to name.
  V2 type        `core.extract.parse_value` accepts it for this field. Note what this does NOT
                 catch: UNC prints "$45,000.00 Annual" under an hourly-rate caption, and money
                 parses as money. That one is V3's job.
  V3 bound       a typed physical bound derived from *other values read on the same document*.
                 The load-bearing one is hours: `regular_hours <= (period_end - period_start)
                 x 24`. 74.50 fits a fortnight; the year-to-date 28,707.21 does not.

Supports -- nothing is accepted without one:

  S1 arithmetic  the chain of `core.arithmetic` identities, anchored at hours.
  S2 adjacency   an existing frozen-vocabulary label sits next to the number. **One support
                 bit, never a position decision**, and never enough on its own to answer.
  S3 uniqueness  how many distinct values survive. Two survivors is an abstention.

WHY NOT MAJORITY VOTING
-----------------------
Because the votes are not independent. S2 correlates with the geometry `core/extract.py`
already uses -- when S2 fires, the ordinary path has usually already answered. And S1's
identities share a value family: on the UNC advice the *year-to-date* numbers satisfy the row
product, the column sum and the total band amongst themselves, so a vote over identities elects
28,707.21 as gross unanimously. Counting correlated elements three times is counting once.

What breaks that tie is not another vote, it is a different KIND of evidence. `regular_hours`
is the only field with a physical bound the document itself supplies, so the chain starts
there: hours bounds the family, `rate x hours` names a row amount, that amount's column sums
to gross, and the band `deductions + net = gross` yields net. Current and year-to-date separate
by measurement, with no vocabulary involved.

WHAT IS NOT HERE, ON PURPOSE
----------------------------
* **No model proposer.** A model naming candidate *values* would send document content out of
  the process, which is the line `core/label_llm.py` holds deliberately (it sends captions and
  never values). That is a separate decision and not this one.
* **No new labels.** S2 reads `LABEL_MAP` and `LABEL_SYNONYMS` exactly as they are.
* **Certainty is capped at "low".** Nothing this module produces is ever "high", regardless of
  how many identities agree. The ordinary geometry path is the only thing that earns "high",
  because it is the path the 159/159 gold and the bbox IoU were measured against.

FLAG
----
On by default; `REALDOOR_ARITHMETIC=0` switches it off. With the flag off `extract_document`
never calls into this module, so its output is bit-identical to the output before this module
existed. Promoted from opt-in after the measurement recorded in
`core.extract._arithmetic_enabled`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from typing import Any, Sequence

from core import arithmetic as ar
from core.extract import (
    LABEL_MAP,
    LABEL_SYNONYMS,
    ParseError,
    VALUE_X_TOLERANCE,
    Word,
    _join_run,
    _run_box,
    _split_runs,
    group_lines,
    normalize_label,
    parse_value,
)

#: Note prefix carried by anything this module produces, so a reader counting fields can
#: separate the arithmetic path from the geometry path without reading the code.
ARITHMETIC_NOTE = "value accepted by arithmetic verification (see core/verified.py)"

#: Prefix of the machine-readable proposal attached to an abstention. **An abstention, not an
#: answer.** `scripts/measure_external_holdout.py` scores everything that is not abstained, so
#: a proposal resting on label adjacency alone would quietly enter the wrong-answer denominator
#: if it were emitted as a value. It is emitted as an abstention carrying a suggestion that a
#: renter may accept -- `confirmed_by_renter` already exists in the contract's evidence_kind
#: enum, so nothing about the schema changes.
PROPOSAL_PREFIX = "PROPOSAL "


# The flag itself lives in `core.extract._arithmetic_enabled`, deliberately and not here.
# Reading it from this module would mean importing this module in order to ask whether this
# module should run, and the promise the flag makes is that with it off nothing here is
# imported at all. One definition, in the place that has to check it first.


# --------------------------------------------------------------------------------------
# V3 -- typed physical bounds, derived from the document
# --------------------------------------------------------------------------------------

#: Hours ceiling when the pay period cannot be read off the page.
#:
#: **Documented fallback, and it is a real bound rather than a guess.** `regular_hours` feeds
#: the annualisation in rule CH-INCOME-001, and the longest pay period any frequency in
#: `core.extract.KNOWN_FREQUENCIES` can span below "annual" is one calendar month. The longest
#: calendar month is 31 days, and a day holds 24 hours, so 744 is the largest number of hours a
#: single period can physically contain. It is deliberately loose: its job is to separate a
#: period figure from a year-to-date figure, and every year-to-date hours total we have
#: measured -- UNC 1,390.00, UTEP 1,596 -- is comfortably above it while every period figure --
#: 74.50, 74.25, 80.00, 40.00 -- is comfortably below.
FALLBACK_HOURS_BOUND = 744.0


def hours_bound(found: dict[str, dict[str, Any]]) -> tuple[float, str]:
    """(ceiling, how we got it) for any hours figure on this document.

    Prefers the document's own pay period. `(end - start)` is inclusive of both days, because
    a period printed 03/30 - 04/05 is seven days of work and not six.
    """
    start = found.get("pay_period_start")
    end = found.get("pay_period_end")
    if start and end and start.get("certainty") != "abstain" and end.get("certainty") != "abstain":
        try:
            first = datetime.strptime(str(start["value"]), "%Y-%m-%d").date()
            last = datetime.strptime(str(end["value"]), "%Y-%m-%d").date()
        except ValueError:
            first = last = None  # type: ignore[assignment]
        if first and last and last >= first:
            days = (last - first).days + 1
            return days * 24.0, f"pay period read from the page ({days} days x 24h)"
    return FALLBACK_HOURS_BOUND, "pay period unreadable; fallback of one calendar month (31d x 24h)"


# --------------------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------------------


@dataclass
class Candidate:
    """One proposed answer, and every refusal it survived."""

    field: str
    token: ar.NumberToken
    supports: list[str] = dc_field(default_factory=list)
    identities: set[str] = dc_field(default_factory=set)
    detail: str = ""

    @property
    def chain_complete(self) -> bool:
        """All three arithmetic identities speak: row product, column sum, total band."""
        return {"row_product", "column_sum", "total_band"} <= self.identities


def _veto_grounding(words: Sequence[Word], token: ar.NumberToken) -> bool:
    """V1. The word at the named index really is this text.

    The proposer hands over an index rather than a string, which is what makes this checkable:
    a value the document does not print has no index to hand over, and an index that has been
    mis-copied points at a different word and fails here.
    """
    if not (0 <= token.index < len(words)):
        return False
    word = words[token.index]
    if word.text != token.text or word.page != token.page:
        return False
    parsed = ar.parse_number(word.text)
    return parsed is not None and parsed[0] == token.value


def _veto_type(field: str, token: ar.NumberToken) -> bool:
    """V2. The printed text parses as the type this field requires."""
    try:
        parse_value(field, token.text)
    except ParseError:
        return False
    return True


def _veto_bound(field: str, value: float, bound: float, gross: float | None) -> bool:
    """V3. A typed physical bound, derived from other values read on this same document."""
    if field == "regular_hours":
        return 0 < value <= bound
    if field == "hourly_rate":
        # An hourly rate is positive, and it cannot exceed the whole period's gross pay --
        # which is where UNC's "$45,000.00 Annual" under an hourly caption dies. V2 cannot
        # catch it, because money parses as money.
        return 0 < value and (gross is None or value <= gross)
    if field == "gross_pay":
        return value > 0
    if field == "net_pay":
        return 0 < value and (gross is None or value <= gross)
    return False


# --------------------------------------------------------------------------------------
# S1 -- the arithmetic chain, anchored at hours
# --------------------------------------------------------------------------------------


def _nonzero(run: Sequence[ar.NumberToken]) -> int:
    return sum(1 for t in run if t.value != 0)


def _same_baseline(a: ar.NumberToken, b: ar.NumberToken) -> bool:
    return abs(a.baseline - b.baseline) <= ar.BASELINE_TOLERANCE


def _overlaps(a: ar.NumberToken, b: ar.NumberToken) -> bool:
    return not (a.x1 < b.x0 - VALUE_X_TOLERANCE or b.x1 < a.x0 - VALUE_X_TOLERANCE)


@dataclass
class Anchored:
    """One earnings column run that an hours figure vouches for."""

    run: tuple[ar.NumberToken, ...]
    total: ar.NumberToken
    products: tuple[ar.RowProduct, ...]


def _anchored_runs(
    tokens: Sequence[ar.NumberToken], bound: float
) -> list[Anchored]:
    """Column runs that an hours-bounded row product anchors. This is the whole chain.

    The anchor is a **row product on one printed line** -- `rate_i x hours_i = amount_i` --
    whose hours factor passes the physical bound and whose amount is a member of the run. That
    is what separates the current-period family from the year-to-date family without using a
    single word:

      * UNC current: `20.346846 x 74.50 = 1,515.84`, and 74.50 fits a fortnight. Anchored.
      * UNC year-to-date: `20.346846 x 855.00 = 17,396.55`, but the page prints 17,446.65.
        The product does not hold, *and* 855.00 exceeds the bound. Twice refused.

    Note what is deliberately absent: an anchor by "hours somewhere on the same line". It is
    weaker and it re-opens the trap, because the UNC year-to-date amounts sit on the very lines
    that carry the current-period hours. The product is what ties a specific hours figure to a
    specific amount.
    """
    products = ar.find_row_products(tokens)
    sums = ar.find_run_sums(tokens)
    out: list[Anchored] = []
    for run_sum in sums:
        if run_sum.kind != "column" or _nonzero(run_sum.run) < 2:
            continue
        members = {id(t) for t in run_sum.run}
        anchoring = tuple(
            p
            for p in products
            if id(p.amount) in members
            and 0 < p.hours.value <= bound
            and not _overlaps(p.hours, p.amount)
            and not _overlaps(p.rate, p.amount)
            and not _overlaps(p.rate, p.hours)
        )
        if anchoring:
            out.append(Anchored(run=run_sum.run, total=run_sum.total, products=anchoring))
    return out


def _bands(
    tokens: Sequence[ar.NumberToken], gross: ar.NumberToken, anchored_lines: set[float]
) -> list[ar.RunSum]:
    """Runs that sum to the gross and are NOT part of the earnings table: `deductions + net`.

    A run whose lines carry the earnings anchors is the earnings side of the identity and is
    excluded here, because otherwise `596.00 + 111.75 = 707.75` would nominate 111.75 as the
    net pay. What is left is the other side of the same equation.
    """
    out: list[ar.RunSum] = []
    for run_sum in ar.find_run_sums(tokens):
        if _nonzero(run_sum.run) < 2:
            continue
        if abs(run_sum.total.value - gross.value) > 1e-9:
            continue
        if any(
            any(abs(t.baseline - line) <= ar.BASELINE_TOLERANCE for line in anchored_lines)
            for t in run_sum.run
        ):
            continue
        out.append(run_sum)
    return out


def _factor_columns(
    tokens: Sequence[ar.NumberToken], anchored: Anchored
) -> tuple[set[float], set[float]]:
    """(hours values, rate values) for one anchored run, or two empty sets if undecidable.

    Multiplication commutes, so the arithmetic alone cannot say which factor of
    `21.38 x 80.00 = 1710.00` is the rate. The document can, and it says so without a word:
    **the hours column adds up to a printed total and the rate column does not.** Hours are a
    quantity the employer totals; a rate is not a thing anyone sums.

      * UNC: the hours on the anchored lines are 74.50 + 3.50 + 2.00 = 80.00, printed. The
        rates on those same lines are 20.346846 three times, summing to 61.04, printed nowhere.
        Decided.
      * ADP: hours 40.00 + 5.00 = 45.00 and rates 14.9000 + 22.3500 = 37.25 are both unprinted.
        Undecided, so both fields abstain -- which is the right answer anyway, since each column
        holds two different values.

    The comparison is made over exactly the baselines of the anchored run. A looser reading
    would accept UNC's coincidence `20.346846 + 20.346846 = 40.69`, which is a real accidental
    hit on that page (40.69 is an earnings amount) and would decide the question backwards.
    """
    # `find_row_products` emits both orientations of every product, so the factors have to be
    # regrouped by the COLUMN they were printed in before either group means anything. A group
    # mixing 20.346846 with 74.50 sums to nothing and would decide nothing.
    factors: dict[float, list[ar.NumberToken]] = {}
    for product in anchored.products:
        for token in (product.rate, product.hours):
            factors.setdefault(product.amount.baseline, [])
            if all(id(token) != id(t) for t in factors[product.amount.baseline]):
                factors[product.amount.baseline].append(token)
    if len(factors) < 2 or any(len(v) != 2 for v in factors.values()):
        return set(), set()

    flat = [t for pair in factors.values() for t in pair]
    columns = ar._cluster(flat, lambda t: t.x1, VALUE_X_TOLERANCE)
    if len(columns) != 2 or any(len(c) != len(factors) for c in columns):
        return set(), set()

    printed = {round(t.value, 2) for t in tokens}

    def sums_to_printed(group: Sequence[ar.NumberToken]) -> bool:
        total = round(sum(t.value for t in group), 2)
        return total != 0 and any(
            abs(total - value) <= ar.sum_tolerance(len(group)) for value in printed
        )

    first, second = columns
    if sums_to_printed(first) and not sums_to_printed(second):
        return {t.value for t in first}, {t.value for t in second}
    if sums_to_printed(second) and not sums_to_printed(first):
        return {t.value for t in second}, {t.value for t in first}
    return set(), set()


# --------------------------------------------------------------------------------------
# S2 -- label adjacency, using the frozen vocabulary and nothing else
# --------------------------------------------------------------------------------------

#: How far from a label a number may sit and still count as adjacent to it. Deliberately much
#: looser than `core.extract.VALUE_Y_WINDOW`, because loose geometry is exactly what this
#: module is allowed to have: S2 is one support bit that can never answer on its own, so a
#: sloppy window here costs a proposal at worst. It is never a position decision.
ADJACENCY_RADIUS = 40.0

_FIELD_LABELS: dict[str, dict[str, set[str]]] = {}


def _labels_for(document_type: str) -> dict[str, set[str]]:
    """field name -> the frozen label strings that name it. No new labels are added here."""
    cached = _FIELD_LABELS.get(document_type)
    if cached is not None:
        return cached
    out: dict[str, set[str]] = {}
    for table in (LABEL_MAP, LABEL_SYNONYMS):
        for label, field in table.get(document_type, {}).items():
            out.setdefault(field, set()).add(normalize_label(label))
    _FIELD_LABELS[document_type] = out
    return out


def _adjacent_values(
    words: Sequence[Word], document_type: str, field: str
) -> list[ar.NumberToken]:
    """Numbers sitting next to a frozen label for this field, in any direction."""
    wanted = _labels_for(document_type).get(field)
    if not wanted:
        return []
    tokens = ar.number_tokens(words)
    anchors: list[tuple[float, float, float]] = []
    for line in group_lines(words):
        for run in _split_runs(line):
            if normalize_label(_join_run(run)) in wanted:
                anchors.append((run[0].baseline, run[0].x0, max(w.x1 for w in run)))
    out: list[ar.NumberToken] = []
    for token in tokens:
        for baseline, x0, x1 in anchors:
            near_y = abs(token.baseline - baseline) <= ADJACENCY_RADIUS
            near_x = token.x0 >= x0 - ADJACENCY_RADIUS and token.x0 <= x1 + 8 * ADJACENCY_RADIUS
            if near_y and near_x:
                out.append(token)
                break
    return out


# --------------------------------------------------------------------------------------
# Combination
# --------------------------------------------------------------------------------------

#: Fields this module will speak about at all. Every one is a number whose value participates
#: in an identity the document prints about itself. Nothing textual is here: a name and a date
#: satisfy no arithmetic, so there is no refusal to build acceptance out of.
VERIFIABLE_FIELDS = ("gross_pay", "net_pay", "hourly_rate", "regular_hours")


def verify_page(
    words: Sequence[Word],
    document_type: str,
    found: dict[str, dict[str, Any]],
    convention: Any,
    wanted: Sequence[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """(answers, proposals) for one page. Never overwrites anything already in `found`.

    The two are returned separately so the caller can take every page's *answers* before any
    page's *proposal*. They are not interchangeable and the ordering matters on real documents:
    the federal LES opens with two pages of glossary whose left column is our label vocabulary,
    so a proposal raised on page 1 would otherwise shadow a verified answer on page 3.

    The combination rule, stated once:

        accept (certainty "low")   V1 & V2 & V3 & S1 & S3-unique
        propose (certainty stays   V1 & V2 & V3 & S2 alone
          "abstain", note carries
          the proposal)
        abstain                    any veto fails, or no support, or two or more survivors

    There is no "high" here. The chain being complete rather than partial is recorded in the
    note, so a reader can count the two apart, but it does not buy a stronger word: "high" is
    reserved for the ordinary geometry path that the 159/159 gold and the bbox IoU measured.
    """
    tokens = ar.number_tokens(words)
    if len(tokens) < 3:
        return {}, {}
    bound, bound_reason = hours_bound(found)
    anchored = _anchored_runs(tokens, bound)

    candidates: dict[str, list[Candidate]] = {name: [] for name in wanted}

    # ---- gross: the total of an anchored earnings run.
    #
    # Computed whether or not `gross_pay` is one of the fields being asked for, because every
    # other bound in V3 is derived from it -- an hourly rate cannot exceed the period's gross,
    # and neither can the net. A document whose gross the label path already read still has to
    # supply that number here, or the bounds below would be vacuous on exactly the documents we
    # know most about.
    anchored_lines = {p.amount.baseline for a in anchored for p in a.products}
    gross_token: ar.NumberToken | None = None
    gross_candidates: list[Candidate] = []
    for item in anchored:
        identities = {"row_product", "column_sum"}
        bands = _bands(tokens, item.total, anchored_lines)
        if bands:
            identities.add("total_band")
        gross_candidates.append(
            Candidate(
                field="gross_pay",
                token=item.total,
                supports=["S1"],
                identities=identities,
                detail=(
                    f"{' + '.join(t.text for t in item.run)} = {item.total.text} in one "
                    f"aligned column, anchored by {item.products[0].rate.text} x "
                    f"{item.products[0].hours.text} = {item.products[0].amount.text} on one "
                    f"printed line (hours ceiling {bound:g}: {bound_reason})"
                ),
            )
        )
    if "gross_pay" in candidates:
        candidates["gross_pay"].extend(gross_candidates)

    gross_values = {c.token.value for c in gross_candidates}
    gross_value = next(iter(gross_values)) if len(gross_values) == 1 else None
    if len(gross_values) == 1:
        gross_token = gross_candidates[0].token

    # ---- net: the last element of a band that sums to that gross
    if gross_token is not None and "net_pay" in candidates:
        for band in _bands(tokens, gross_token, anchored_lines):
            tail = band.run[-1]
            candidates["net_pay"].append(
                Candidate(
                    field="net_pay",
                    token=tail,
                    supports=["S1"],
                    identities={"total_band", "column_sum" if band.kind == "column" else "line_sum"},
                    detail=(
                        f"{' + '.join(t.text for t in band.run)} = {band.total.text}, a "
                        f"consecutive run of one {band.kind} that does not touch the earnings "
                        f"rows; the last term is what is left after the deductions"
                    ),
                )
            )

    # ---- hours and rate: the two factors of the anchoring product, told apart by measurement
    for item in anchored:
        hours_values, rate_values = _factor_columns(tokens, item)
        if not hours_values:
            continue
        # A rate printed identically on every earnings row gives several tokens carrying the
        # same verified value. Point at the first one in reading order: the value is the same
        # either way, but a box on the top row is the one a human checking it expects to see,
        # and a box on the third row reads as if we had picked that row for a reason.
        by_value: dict[float, ar.NumberToken] = {}
        for token in sorted(
            [p.hours for p in item.products] + [p.rate for p in item.products],
            key=lambda t: (-t.baseline, t.x0),
        ):
            by_value.setdefault(token.value, token)
        detail = (
            "the two factors were told apart by measurement: the hours on these lines add up "
            "to a printed total and the rates do not"
        )
        for name, values in (("regular_hours", hours_values), ("hourly_rate", rate_values)):
            if name not in candidates:
                continue
            for value in values:
                token = by_value.get(value)
                if token is None:
                    continue
                candidates[name].append(
                    Candidate(
                        field=name,
                        token=token,
                        supports=["S1"],
                        identities={"row_product"} | ({"column_sum"} if name == "regular_hours" else set()),
                        detail=detail,
                    )
                )

    answers: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    for name in wanted:
        survivors = [
            c
            for c in candidates.get(name, [])
            if _veto_grounding(words, c.token)
            and _veto_type(name, c.token)
            and _veto_bound(name, c.token.value, bound, gross_value)
        ]
        distinct = {c.token.value for c in survivors}
        if len(distinct) == 1:
            best = max(survivors, key=lambda c: len(c.identities))
            answers[name] = _accept(best, words, convention, bound_reason)
            continue
        # S2 alone -- a proposal attached to an abstention, never an answer.
        proposal = _propose(words, document_type, name, bound, gross_value, convention)
        if proposal is not None:
            proposals[name] = proposal
    return answers, proposals


def _accept(
    candidate: Candidate, words: Sequence[Word], convention: Any, bound_reason: str
) -> dict[str, Any]:
    token = candidate.token
    value, _clean = parse_value(candidate.field, token.text)
    strength = "complete" if candidate.chain_complete else "partial"
    return {
        "field": candidate.field,
        "value": value,
        "page": token.page,
        "bbox": _run_box([words[token.index]], convention),
        "bbox_units": "pdf_points_bottom_left_origin",
        "certainty": "low",
        "evidence_kind": "extracted",
        "source_text": token.text,
        "notes": (
            f"{ARITHMETIC_NOTE} | chain {strength} "
            f"({', '.join(sorted(candidate.identities))}) | {candidate.detail}"
        ),
    }


def _propose(
    words: Sequence[Word],
    document_type: str,
    field: str,
    bound: float,
    gross: float | None,
    convention: Any,
) -> dict[str, Any] | None:
    """An abstention carrying a suggestion a human may accept. Never a value answer."""
    nearby = [
        t
        for t in _adjacent_values(words, document_type, field)
        if _veto_grounding(words, t) and _veto_type(field, t) and _veto_bound(field, t.value, bound, gross)
    ]
    values = {t.value for t in nearby}
    if len(values) != 1:
        return None
    token = nearby[0]
    payload = json.dumps(
        {
            "field": field,
            "value": token.text,
            "page": token.page,
            "bbox": _run_box([words[token.index]], convention),
            "support": "label adjacency only",
        },
        ensure_ascii=False,
    )
    return {
        "field": field,
        "value": None,
        "page": None,
        "bbox": None,
        "bbox_units": "pdf_points_bottom_left_origin",
        "certainty": "abstain",
        "evidence_kind": "extracted",
        "source_text": None,
        "notes": (
            "a frozen label for this field sits next to a number, but nothing the document "
            "computes confirms it, so this is NOT an answer. A renter may confirm it. "
            f"{PROPOSAL_PREFIX}{payload}"
        ),
    }
