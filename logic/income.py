"""Annualization of recurring gross income (CH-INCOME-001). Pure functions.

    "For scoring only, annualize recurring gross income using the explicit pay
     frequency. Sum independently documented recurring sources. Do not infer protected
     traits or undocumented income."

Four commitments follow from that sentence and are enforced here:

1. **Explicit frequency only.** ``annualize()`` refuses any frequency outside the five
   frozen multipliers, and the source derivations refuse to guess one from pay dates.
2. **Independently documented sources sum; duplicate views of one source do not.**
   Pay stubs and an employment letter for the same job describe ONE source. See
   ``constants.CONVENTIONS['WAGE_SOURCE_IS_ONE_SOURCE']`` for the pack evidence.
3. **Recurring, not merely observed.** A stub whose gross exceeds its own
   ``regular_hours * hourly_rate`` contains non-recurring pay; the excess is not
   annualized, and the discrepancy is reported rather than absorbed.
4. **Every input names its document.** ``Calculation.inputs[].from_document`` is not
   decoration; a number with no document behind it does not enter the sum.

No protected trait, and no proxy for one, is read anywhere in this module. The only
fields consulted are: pay_frequency, gross_pay, regular_hours, hourly_rate,
weekly_hours, monthly_benefit, benefit_frequency, gross_receipts, statement_month.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from logic import abstain
from logic.abstain import Abstention
from logic.constants import FREQUENCY, LIMITS_EFFECTIVE_DATE
from logic.household import Document, FieldRef, Household

WEEKS_PER_YEAR = FREQUENCY["weekly"]


# =====================================================================================
# the primitive
# =====================================================================================


def annualize(amount: float, frequency: str) -> float:
    """Annualize one amount at one stated frequency.

    Deliberately identical in behaviour to ``pack/starter/src/calculate.py::annualize``,
    including the ValueError cases and the 2-decimal rounding. Agreement is asserted by
    ``logic/test_pack_agreement.py`` over a swept grid, not assumed.
    """
    if frequency not in FREQUENCY:
        raise ValueError(f"Unsupported frequency: {frequency}")
    if amount < 0:
        raise ValueError("Amount must be non-negative")
    return round(float(amount) * FREQUENCY[frequency], 2)


# =====================================================================================
# results
# =====================================================================================


@dataclass(frozen=True)
class IncomeSource:
    """One independently documented recurring income source."""

    name: str
    annual_amount: float | None
    formula: str
    inputs: list[dict[str, Any]]
    documents: tuple[str, ...]
    abstentions: tuple[Abstention, ...] = ()

    @property
    def counted(self) -> bool:
        return self.annual_amount is not None

    def to_calculation(self, household_id: str) -> dict[str, Any]:
        """A ``Calculation`` (CONTRACTS section 5) for this one source.

        A per-source calculation has no threshold of its own -- only the household total
        is compared -- so it carries ``comparison="no_frozen_threshold"``, the contract's
        abstention slot, rather than a fabricated threshold.
        """
        return {
            "name": f"annualized_{self.name}_income",
            "household_id": household_id,
            "inputs": list(self.inputs),
            "formula": self.formula,
            "result": self.annual_amount,
            "threshold": None,
            "threshold_rule_id": None,
            "comparison": "no_frozen_threshold",
            "effective_date": LIMITS_EFFECTIVE_DATE,
            "rule_id": "CH-INCOME-001",
        }


@dataclass(frozen=True)
class AnnualizedIncome:
    """The household total, or an honest absence of one."""

    household_id: str
    total: float | None
    sources: tuple[IncomeSource, ...]
    abstentions: tuple[Abstention, ...]

    @property
    def counted_sources(self) -> tuple[IncomeSource, ...]:
        return tuple(s for s in self.sources if s.counted)

    def to_calculation(self) -> dict[str, Any]:
        inputs: list[dict[str, Any]] = []
        for source in self.counted_sources:
            inputs.extend(source.inputs)
        formula = " + ".join(s.formula for s in self.counted_sources) or "no documented source"
        return {
            "name": "annualized_income",
            "household_id": self.household_id,
            "inputs": inputs,
            "formula": formula,
            "result": self.total,
            "threshold": None,
            "threshold_rule_id": None,
            "comparison": "no_frozen_threshold",
            "effective_date": LIMITS_EFFECTIVE_DATE,
            "rule_id": "CH-INCOME-001",
        }


# =====================================================================================
# helpers
# =====================================================================================


def _require_traceable(ref: FieldRef | None, about: str, label: str) -> tuple[FieldRef | None, list[Abstention]]:
    if ref is None:
        return None, [abstain.raise_abstention("amount_missing", about, f"{label} not found")]
    if not ref.traceable:
        return None, [
            abstain.raise_abstention(
                "income_amount_not_traceable", about, f"{label} on {ref.document_id}"
            )
        ]
    return ref, []


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reconciles(gross: float | None, hours: Any, rate: Any) -> bool | None:
    """Does the stated gross equal hours * rate? None when the check cannot be run."""
    h, r = _as_number(hours), _as_number(rate)
    if gross is None or h is None or r is None:
        return None
    return round(h * r, 2) == round(gross, 2)


@dataclass(frozen=True)
class _StubReading:
    """One pay stub's gross, whether it reconciles, and where the gross came from.

    ``ref`` is kept (rather than just the number) so the reasoning can tell a value a
    renter typed from a value a machine read. That distinction is what lets the report
    say "the amount you corrected was not used" instead of nothing at all.
    """

    doc: Document
    gross: float
    reconciles: bool | None
    ref: FieldRef

    @property
    def corrected(self) -> bool:
        return self.ref.corrected_by_renter

    @property
    def implied(self) -> float | None:
        """This stub's own regular_hours * hourly_rate, when both are readable."""
        h = _as_number(self.doc.value("regular_hours"))
        r = _as_number(self.doc.value("hourly_rate"))
        return None if h is None or r is None else round(h * r, 2)

    def own_arithmetic(self) -> str:
        """`76 * 28.5 = 2,166.00`, or a plain statement when the factors are unreadable."""
        h = self.doc.value("regular_hours")
        r = self.doc.value("hourly_rate")
        implied = self.implied
        if implied is None:
            return "its own regular_hours * hourly_rate could not be read"
        return f"its own regular_hours * hourly_rate is {h} * {r} = {implied:,.2f}"


# =====================================================================================
# source derivations
# =====================================================================================


def derive_wage_source(house: Household) -> IncomeSource | None:
    """Wages from pay stubs, corroborated (not summed) by any employment letter.

    The recurring base is the stub gross that reconciles with its own
    ``regular_hours * hourly_rate``. When stubs disagree, the reconciling one wins and
    ``pay_stub_totals_conflict`` is raised; when none reconciles, we abstain outright
    rather than pick.
    """
    stubs = house.of_type("pay_stub")
    letters = house.of_type("employment_letter")
    if not stubs and not letters:
        return None

    about = "annualized_wage_income"
    problems: list[Abstention] = []

    if not stubs:
        # An employment letter alone states hours and rate; that is a documented
        # recurring wage even without a stub.
        return _wage_from_letter_only(letters, about)

    # -- frequency must be stated, and stated identically, across stubs ---------------
    frequencies = {str(d.value("pay_frequency")) for d in stubs if d.get("pay_frequency")}
    if not frequencies:
        return IncomeSource(
            "wage", None, "abstained", [], tuple(d.document_id for d in stubs),
            (abstain.raise_abstention("pay_frequency_not_stated", about,
                                      f"no pay stub states one ({len(stubs)} stub(s) read)"),),
        )
    if len(frequencies) > 1:
        return IncomeSource(
            "wage", None, "abstained", [], tuple(d.document_id for d in stubs),
            (abstain.raise_abstention("pay_frequency_not_stated", about,
                                      f"stubs state different frequencies: {sorted(frequencies)}"),),
        )
    frequency = frequencies.pop()
    if frequency not in FREQUENCY:
        return IncomeSource(
            "wage", None, "abstained", [], tuple(d.document_id for d in stubs),
            (abstain.raise_abstention("pay_frequency_not_recognized", about, repr(frequency)),),
        )

    # -- read each stub's gross and check it against its own hours * rate -------------
    candidates: list[_StubReading] = []
    for stub in stubs:
        ref, missing = _require_traceable(stub.get("gross_pay"), about, "gross_pay")
        if ref is None:
            problems.extend(missing)
            continue
        gross = _as_number(ref.value)
        if gross is None:
            problems.append(
                abstain.raise_abstention("amount_missing", about,
                                         f"gross_pay on {stub.document_id} is not numeric")
            )
            continue
        candidates.append(_StubReading(
            doc=stub,
            gross=gross,
            reconciles=_reconciles(gross, stub.value("regular_hours"),
                                   stub.value("hourly_rate")),
            ref=ref,
        ))

    if not candidates:
        return IncomeSource("wage", None, "abstained", [],
                            tuple(d.document_id for d in stubs), tuple(problems))

    distinct = sorted({c.gross for c in candidates})
    reconciling = [c for c in candidates if c.reconciles]

    if len(distinct) == 1:
        chosen = candidates[0]
        chosen_doc, base = chosen.doc, distinct[0]
        # All stubs agree. If none of them reconciles with hours * rate we still use the
        # agreed figure -- it is what every document says -- but we say so.
        if chosen.reconciles is False:
            problems.append(
                abstain.raise_abstention(
                    "pay_stub_totals_conflict", about,
                    f"gross_pay {base:,.2f} does not equal regular_hours * hourly_rate on "
                    f"{chosen_doc.document_id}",
                )
            )
    elif reconciling:
        reconciled_values = sorted({c.gross for c in reconciling})
        if len(reconciled_values) > 1:
            return IncomeSource(
                "wage", None, "abstained", [], tuple(d.document_id for d in stubs),
                tuple(problems + [abstain.raise_abstention(
                    "pay_stub_totals_irreconcilable", about,
                    f"multiple reconciling stubs disagree: {reconciled_values}")]),
            )
        chosen = reconciling[0]
        chosen_doc, base = chosen.doc, chosen.gross
        excluded = [c for c in candidates if c.doc.document_id != chosen_doc.document_id]
        problems.append(
            abstain.raise_abstention(
                "pay_stub_totals_conflict", about,
                f"stub totals {[f'{v:,.2f}' for v in distinct]}; using {base:,.2f} from "
                f"{chosen_doc.document_id}, which reconciles with its own hours and rate; "
                + _excluded_phrase(excluded),
            )
        )
        problems.extend(_correction_abstentions(excluded, chosen_doc.document_id, about))
    else:
        problems.extend(_correction_abstentions(candidates, None, about))
        return IncomeSource(
            "wage", None, "abstained", [], tuple(d.document_id for d in stubs),
            tuple(problems + [abstain.raise_abstention(
                "pay_stub_totals_irreconcilable", about,
                f"stub totals {[f'{v:,.2f}' for v in distinct]}, none reconciling")]),
        )

    # The symmetric case: the figure we DID use is one a person typed. That is not a gap
    # -- a correction that makes a stub reconcile is supposed to move the number -- but a
    # reviewer must be able to see that a human, not a page, is behind the base amount.
    for reading in candidates:
        if reading.corrected and round(reading.gross, 2) == round(base, 2):
            problems.append(
                abstain.raise_abstention(
                    "corrected_value_is_the_recurring_base", about,
                    f"gross_pay {base:,.2f} on {reading.doc.document_id} was entered by "
                    f"the renter, and {reading.own_arithmetic()}, so it IS used as the "
                    f"recurring base and the annualized figure reflects it",
                )
            )

    annual = annualize(base, frequency)

    inputs = [
        {"label": "gross_pay", "value": base, "from_document": chosen_doc.document_id},
        {"label": "pay_frequency", "value": frequency, "from_document": chosen_doc.document_id},
    ]

    # -- an employment letter corroborates; it never adds -----------------------------
    for letter in letters:
        implied = _letter_implied_annual(letter)
        if implied is None:
            continue
        inputs.append({
            "label": "corroborating_weekly_hours_x_rate",
            "value": round(implied / WEEKS_PER_YEAR, 2),
            "from_document": letter.document_id,
        })
        if round(implied, 2) != round(annual, 2):
            problems.append(
                abstain.raise_abstention(
                    "pay_stub_totals_conflict", about,
                    f"employment letter {letter.document_id} implies {implied:,.2f}/yr but "
                    f"the pay stubs give {annual:,.2f}/yr",
                )
            )

    return IncomeSource(
        name="wage",
        annual_amount=annual,
        formula=f"{base} * {FREQUENCY[frequency]}",
        inputs=inputs,
        documents=tuple(d.document_id for d in stubs + letters),
        abstentions=tuple(problems),
    )


def _excluded_phrase(excluded: list[_StubReading]) -> str:
    """Name the stub(s) dropped from the recurring base, and the sum that dropped them.

    Previously the conflict entry listed the totals and named only the WINNER. A reader
    could see that two numbers disagreed and which one survived, but not which document
    had been set aside or on what arithmetic -- so a renter looking at their own
    corrected stub had no way to find it in the report.
    """
    if not excluded:
        return "no other stub was set aside"
    parts = [
        f"{c.doc.document_id} ({c.gross:,.2f}) was not used as the recurring base because "
        f"{c.own_arithmetic()}"
        for c in excluded
    ]
    return "; ".join(parts)


def _correction_abstentions(
    excluded: list[_StubReading], used_instead: str | None, about: str
) -> list[Abstention]:
    """Say out loud when a value the RENTER typed was the one we set aside.

    Machine-extracted disagreement is already covered, more softly, by
    ``pay_stub_totals_conflict``: two documents differ and we explain which won. A
    correction is a different event. Someone read our number, decided it was wrong, typed
    a replacement, and is now looking at a total that did not move. Only an entry that
    names their document and their number tells them what happened.
    """
    out: list[Abstention] = []
    for reading in excluded:
        if not reading.corrected:
            continue
        where = (
            f"the recurring base was taken from {used_instead} instead, so the corrected "
            f"{reading.gross:,.2f} does not change the annualized amount"
            if used_instead
            else "no stub could be used as a recurring base at all, so the corrected "
                 f"{reading.gross:,.2f} does not produce an annualized amount"
        )
        out.append(
            abstain.raise_abstention(
                "corrected_value_not_used", about,
                f"gross_pay on {reading.doc.document_id} was corrected to "
                f"{reading.gross:,.2f}, but {reading.own_arithmetic()} on that same "
                f"document; {where}",
            )
        )
    return out


def _letter_implied_annual(letter: Document) -> float | None:
    hours = _as_number(letter.value("weekly_hours"))
    rate = _as_number(letter.value("hourly_rate"))
    if hours is None or rate is None:
        return None
    return round(hours * rate * WEEKS_PER_YEAR, 2)


def _wage_from_letter_only(letters: list[Document], about: str) -> IncomeSource:
    for letter in letters:
        hours_ref = letter.get("weekly_hours")
        rate_ref = letter.get("hourly_rate")
        if hours_ref is None or rate_ref is None:
            continue
        if not (hours_ref.traceable and rate_ref.traceable):
            return IncomeSource(
                "wage", None, "abstained", [], (letter.document_id,),
                (abstain.raise_abstention("income_amount_not_traceable", about,
                                          f"employment letter {letter.document_id}"),),
            )
        implied = _letter_implied_annual(letter)
        return IncomeSource(
            name="wage",
            annual_amount=implied,
            formula=f"{hours_ref.value} * {rate_ref.value} * {WEEKS_PER_YEAR}",
            inputs=[hours_ref.as_input("weekly_hours"), rate_ref.as_input("hourly_rate")],
            documents=(letter.document_id,),
        )
    return IncomeSource(
        "wage", None, "abstained", [], tuple(l.document_id for l in letters),
        (abstain.raise_abstention("amount_missing", about,
                                  "employment letter states neither hours nor rate"),),
    )


def derive_benefit_source(house: Household) -> IncomeSource | None:
    """Recurring benefit income. Frequency must be stated on the letter."""
    letters = house.of_type("benefit_letter")
    if not letters:
        return None
    about = "annualized_benefit_income"
    letter = letters[0]

    amount_ref, problems = _require_traceable(letter.get("monthly_benefit"), about, "monthly_benefit")
    if amount_ref is None:
        return IncomeSource("benefit", None, "abstained", [], (letter.document_id,), tuple(problems))

    frequency = letter.value("benefit_frequency")
    if frequency is None:
        return IncomeSource(
            "benefit", None, "abstained", [], (letter.document_id,),
            (abstain.raise_abstention("pay_frequency_not_stated", about,
                                      f"benefit letter {letter.document_id} states no frequency"),),
        )
    frequency = str(frequency)
    if frequency not in FREQUENCY:
        return IncomeSource(
            "benefit", None, "abstained", [], (letter.document_id,),
            (abstain.raise_abstention("pay_frequency_not_recognized", about, repr(frequency)),),
        )

    amount = _as_number(amount_ref.value)
    if amount is None:
        return IncomeSource(
            "benefit", None, "abstained", [], (letter.document_id,),
            (abstain.raise_abstention("amount_missing", about, "monthly_benefit is not numeric"),),
        )

    return IncomeSource(
        name="benefit",
        annual_amount=annualize(amount, frequency),
        formula=f"{amount} * {FREQUENCY[frequency]}",
        inputs=[amount_ref.as_input("monthly_benefit"),
                {"label": "benefit_frequency", "value": frequency,
                 "from_document": letter.document_id}],
        documents=(letter.document_id,),
    )


#: Document types that could corroborate a self-reported gig statement. None of them
#: exists in this pack, which is why HH-004 is uncorroborated.
GIG_CORROBORATION_TYPES = ("gig_income_corroboration", "bank_statement", "form_1099")


def derive_gig_source(house: Household) -> IncomeSource | None:
    """Gig income from a statement covering one stated calendar month.

    The x12 rests on ``MONTHLY_STATEMENT_PERIOD_IS_A_STATED_FREQUENCY`` -- a convention,
    not a frozen rule, and recorded as such in ``logic/constants.py``. Gross receipts are
    annualized; platform fees are not deducted (CH-INCOME-001 says gross).
    """
    statements = house.of_type("gig_statement")
    if not statements:
        return None
    about = "annualized_gig_income"
    statement = statements[0]

    receipts_ref, problems = _require_traceable(statement.get("gross_receipts"), about, "gross_receipts")
    if receipts_ref is None:
        return IncomeSource("gig", None, "abstained", [], (statement.document_id,), tuple(problems))

    amount = _as_number(receipts_ref.value)
    if amount is None:
        return IncomeSource(
            "gig", None, "abstained", [], (statement.document_id,),
            (abstain.raise_abstention("amount_missing", about, "gross_receipts is not numeric"),),
        )

    month = statement.value("statement_month")
    if month is None:
        return IncomeSource(
            "gig", None, "abstained", [], (statement.document_id,),
            (abstain.raise_abstention(
                "pay_frequency_not_stated", about,
                f"gig statement {statement.document_id} names no coverage period"),),
        )

    problems = []
    if not any(house.of_type(t) for t in GIG_CORROBORATION_TYPES):
        problems.append(
            abstain.raise_abstention(
                "self_reported_income_uncorroborated", about,
                f"{statement.document_id} covers {month}; no corroborating document is present",
            )
        )

    return IncomeSource(
        name="gig",
        annual_amount=annualize(amount, "monthly"),
        formula=f"{amount} * 12",
        inputs=[receipts_ref.as_input("gross_receipts"),
                {"label": "statement_month", "value": month,
                 "from_document": statement.document_id}],
        documents=(statement.document_id,),
        abstentions=tuple(problems),
    )


DERIVATIONS = (derive_wage_source, derive_benefit_source, derive_gig_source)


# =====================================================================================
# the household total
# =====================================================================================


def annualize_household(house: Household) -> AnnualizedIncome:
    """Sum independently documented recurring sources (CH-INCOME-001).

    A source with a blocking abstention contributes nothing and is not silently dropped:
    its abstention travels with the result. If NO source could be computed, the total is
    ``None`` -- not 0.0, which would read as "this renter has no income".
    """
    sources: list[IncomeSource] = []
    for derive in DERIVATIONS:
        source = derive(house)
        if source is not None:
            sources.append(source)

    problems: list[Abstention] = []
    for source in sources:
        problems.extend(source.abstentions)

    counted = [s for s in sources if s.counted]
    if not counted:
        if not problems:
            problems.append(
                abstain.raise_abstention(
                    "amount_missing", "annualized_income",
                    "no document in this household states a recurring income amount",
                )
            )
        total = None
    else:
        total = round(sum(s.annual_amount for s in counted), 2)

    return AnnualizedIncome(
        household_id=house.household_id,
        total=total,
        sources=tuple(sources),
        abstentions=tuple(problems),
    )


__all__ = [
    "AnnualizedIncome",
    "IncomeSource",
    "annualize",
    "annualize_household",
    "derive_benefit_source",
    "derive_gig_source",
    "derive_wage_source",
]
