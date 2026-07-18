"""The abstention policy, in one auditable place.

The brief: *"Abstain when the rule or input is uncertain; never label the renter
eligible."* This module is that sentence made executable. It exists as a module rather
than as scattered ``if`` statements so that a reviewer can read the whole policy at once
and check it against the pack, which is the only way anyone can trust the rest.

Two grades, and the distinction is the point:

``BLOCKING``
    We refuse to produce the value. Something downstream will be ``None`` or
    ``no_frozen_threshold``. Used when computing anyway would mean inventing an input or
    extrapolating past what the pack froze.

``ADVISORY``
    We produce the value, and we say what is weak about it. Used when the pack's own
    ground truth expects a number but also expects the gap to be reported -- HH-004's
    uncorroborated gig income is exactly this: the pack wants 51,008.00 computed AND
    wants GIG_INCOME_UNCORROBORATED raised.

Both grades serialize to the same three-key ``abstentions[]`` entry from CONTRACTS
section 7 (``about``, ``reason``, ``what_would_resolve_it``). The grade is internal: it
controls our arithmetic, it is not a label we put on the renter.

Nothing here decides eligibility. An abstention says what WE cannot do, never what the
renter is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from logic.constants import RULE_IDS

BLOCKING = "blocking"
ADVISORY = "advisory"


@dataclass(frozen=True)
class Abstention:
    """One thing the system declined to assert, and how a human can clear it."""

    about: str
    reason: str
    what_would_resolve_it: str
    grade: str
    rule_id: str
    trigger: str

    def __post_init__(self) -> None:
        if self.grade not in (BLOCKING, ADVISORY):
            raise ValueError(f"unknown grade: {self.grade!r}")
        if self.rule_id not in RULE_IDS:
            raise ValueError(f"{self.rule_id!r} is not one of the 11 pack rules")

    @property
    def blocking(self) -> bool:
        return self.grade == BLOCKING

    def to_entry(self) -> dict[str, str]:
        """The exact CONTRACTS section 7 shape -- three keys, nothing smuggled in."""
        return {
            "about": self.about,
            "reason": self.reason,
            "what_would_resolve_it": self.what_would_resolve_it,
        }


# =====================================================================================
# The policy table. Read this and you have read the policy.
# =====================================================================================


@dataclass(frozen=True)
class Trigger:
    """A named condition under which the system declines to assert something."""

    name: str
    grade: str
    rule_id: str
    reason: str
    what_would_resolve_it: str
    rationale: str


POLICY: tuple[Trigger, ...] = (
    # ---- inputs we would have to invent -------------------------------------------
    Trigger(
        name="pay_frequency_not_stated",
        grade=BLOCKING,
        rule_id="CH-INCOME-001",
        reason="the document does not state a pay frequency, and it cannot be inferred",
        what_would_resolve_it="the renter confirms the pay frequency, or uploads a stub that states it",
        rationale=(
            "CH-INCOME-001 says annualize using the EXPLICIT frequency. Guessing biweekly "
            "from two dates two weeks apart is an inference about undocumented facts."
        ),
    ),
    Trigger(
        name="pay_frequency_not_recognized",
        grade=BLOCKING,
        rule_id="CH-INCOME-001",
        reason="the stated pay frequency is not one of the five frozen frequencies",
        what_would_resolve_it="a housing professional maps this frequency to an annual multiplier",
        rationale=(
            "The pack froze exactly five multipliers. A sixth would be our number, not the "
            "pack's, and the organizer's calculate.py raises on it too."
        ),
    ),
    Trigger(
        name="amount_missing",
        grade=BLOCKING,
        rule_id="CH-INCOME-001",
        reason="no gross amount could be read for this income source",
        what_would_resolve_it="the renter confirms the amount, or re-uploads a legible document",
        rationale="An income source with no readable amount contributes nothing we can defend.",
    ),
    Trigger(
        name="income_amount_not_traceable",
        grade=BLOCKING,
        rule_id="CH-READINESS-001",
        reason="the amount has no page-level source box, so it cannot be shown to a reviewer",
        what_would_resolve_it="the renter confirms the value against the page",
        rationale=(
            "CH-READINESS-001 requires traceability to page-level source boxes. A number we "
            "cannot point at is a number a reviewer cannot check."
        ),
    ),
    Trigger(
        name="pay_stub_totals_irreconcilable",
        grade=BLOCKING,
        rule_id="CH-INCOME-001",
        reason=(
            "the pay stubs disagree and none of them reconciles with its own "
            "regular_hours * hourly_rate, so no recurring base amount is documented"
        ),
        what_would_resolve_it="the renter or employer confirms which stub reflects recurring pay",
        rationale=(
            "Picking one of two conflicting totals with nothing to break the tie would be a "
            "coin flip presented as arithmetic."
        ),
    ),
    # ---- thresholds the pack did not freeze ----------------------------------------
    Trigger(
        name="household_size_outside_frozen_table",
        grade=BLOCKING,
        rule_id="HUD-MTSP-002",
        reason="the frozen 60% limit table covers household sizes 1-8 only",
        what_would_resolve_it=(
            "a housing professional supplies the limit for this household size from the "
            "current HUD MTSP tables"
        ),
        rationale=(
            "A real HUD extrapolation formula for sizes above 8 exists, and we deliberately "
            "do not use it. The pack froze 1-8; a number from outside the pack would be an "
            "uncited rule, which is the failure mode this project exists to avoid."
        ),
    ),
    Trigger(
        name="household_size_unknown",
        grade=BLOCKING,
        rule_id="HUD-MTSP-002",
        reason="household size could not be read from any application summary",
        what_would_resolve_it="the renter confirms the household size",
        rationale="The threshold is a function of household size; without it there is no lookup.",
    ),
    Trigger(
        name="income_unavailable_for_comparison",
        grade=BLOCKING,
        rule_id="CH-INCOME-001",
        reason="no annualized amount could be computed, so no comparison is possible",
        what_would_resolve_it="resolve the income abstentions listed above",
        rationale="Comparing an unknown with a threshold produces a shape, not a fact.",
    ),
    # ---- documents we could not date or read ---------------------------------------
    Trigger(
        name="document_date_month_precision",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason=(
            "the document states a month but no day, so the 60-day currency convention "
            "cannot be applied without inventing a date"
        ),
        what_would_resolve_it="the renter supplies a day-precise statement or confirms the date",
        rationale=(
            "contracts/CONTRACTS.md section 1 added 'undatable' for exactly this. Calling it "
            "unreadable would be a false claim about our own capability; assuming the 1st or "
            "the last of the month would be a fabricated date."
        ),
    ),
    Trigger(
        name="document_unreadable",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason="no field on this document could be read, so it cannot support any claim",
        what_would_resolve_it="the renter re-uploads a text-layer copy, or OCR is applied",
        rationale="A scan with no text layer yields abstentions, never guesses.",
    ),
    Trigger(
        name="document_not_current",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason="the document is dated outside the challenge's 60-day currency window",
        what_would_resolve_it="the renter uploads a document dated on or after 2026-05-19",
        rationale=(
            "60 days before the frozen event date 2026-07-18. This is the pack's convention, "
            "not a universal LIHTC rule, and it is stated as such."
        ),
    ),
    # ---- evidence that exists but does not stand on its own -------------------------
    Trigger(
        name="self_reported_income_uncorroborated",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason=(
            "this income is documented only by a self-reported statement, with no "
            "independent corroborating document"
        ),
        what_would_resolve_it=(
            "the renter uploads platform earnings records, bank deposits, or a 1099 covering "
            "the same period"
        ),
        rationale=(
            "The amount is still computed, because the pack's ground truth includes it. What "
            "is withheld is the claim that it is verified."
        ),
    ),
    Trigger(
        name="pay_stub_totals_conflict",
        grade=ADVISORY,
        rule_id="CH-INCOME-001",
        reason=(
            "the pay stubs report different gross totals; the recurring base is taken from "
            "the stub that reconciles with its own hours and rate, and the excess is not "
            "annualized"
        ),
        what_would_resolve_it="the renter or employer confirms whether the extra pay recurs",
        rationale=(
            "Annualizing a one-off overtime week overstates a renter's income by thousands of "
            "dollars, which in this domain is the expensive direction to be wrong in."
        ),
    ),
    # ---- corrections the renter made, and what we did with them ---------------------
    Trigger(
        name="corrected_value_not_used",
        grade=ADVISORY,
        rule_id="CH-INCOME-001",
        reason=(
            "a value the renter corrected was NOT used as the recurring base, because "
            "after the correction that document no longer settles what the recurring pay "
            "is; the annualized amount does not reflect the correction"
        ),
        what_would_resolve_it=(
            "the renter also corrects regular_hours or hourly_rate on that document so the "
            "three figures agree, or the renter or employer confirms which document "
            "reflects recurring pay"
        ),
        rationale=(
            "This is the failure the pack cannot show us and the demo can. A renter types a "
            "number, the screen accepts it, and the total does not move -- because the "
            "reconciliation rule quietly dropped that stub. The arithmetic is defensible; "
            "the silence is not. The brief forbids silently suppressing information, and a "
            "correction accepted at the UI and ignored at the reasoning layer is exactly "
            "that. Softer machine-extracted disagreement stays under "
            "pay_stub_totals_conflict; a human-entered value gets its own entry because a "
            "person is waiting on an answer to it."
        ),
    ),
    Trigger(
        name="corrected_value_is_the_recurring_base",
        grade=ADVISORY,
        rule_id="CH-INCOME-001",
        reason=(
            "the recurring base amount is a value the renter corrected, not the value that "
            "was read off the page"
        ),
        what_would_resolve_it=(
            "a reviewer confirms the corrected amount against the page image before relying "
            "on it"
        ),
        rationale=(
            "The symmetric case of corrected_value_not_used, and the reason this pair is "
            "advisory-only rather than a review reason: a correction that makes a document "
            "reconcile SHOULD change the number, and blocking readiness for it would punish "
            "the renter for doing the thing we asked. But a reviewer must still be able to "
            "see that the driving figure was typed by a person rather than read from a "
            "document, so it is named in abstentions[] and left out of review_reasons[]."
        ),
    ),
    Trigger(
        name="required_document_missing",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason="a required document type is not present in the file",
        what_would_resolve_it="the renter uploads the missing document",
        rationale="Presence is the first of the four CH-READINESS-001 conditions.",
    ),
    Trigger(
        name="value_not_traceable",
        grade=ADVISORY,
        rule_id="CH-READINESS-001",
        reason="a value was read but carries no page-level source box",
        what_would_resolve_it="the renter confirms the value against the page image",
        rationale="Traceability is the fourth CH-READINESS-001 condition.",
    ),
)

_BY_NAME = {t.name: t for t in POLICY}


def trigger(name: str) -> Trigger:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"{name!r} is not in the abstention policy. Add it to POLICY rather than "
            f"writing a one-off branch elsewhere."
        ) from None


def raise_abstention(name: str, about: str, detail: str | None = None) -> Abstention:
    """Instantiate a policy trigger for a specific subject.

    ``detail`` appends case-specific facts (which document, which value) to the policy's
    generic reason. The policy text itself never changes per case.
    """
    spec = trigger(name)
    reason = spec.reason if not detail else f"{spec.reason} ({detail})"
    return Abstention(
        about=about,
        reason=reason,
        what_would_resolve_it=spec.what_would_resolve_it,
        grade=spec.grade,
        rule_id=spec.rule_id,
        trigger=spec.name,
    )


def blocking(items: Iterable[Abstention]) -> list[Abstention]:
    return [a for a in items if a.blocking]


def to_entries(items: Iterable[Abstention]) -> list[dict[str, str]]:
    """Deduplicated, order-stable ``abstentions[]`` for a ReadinessReport."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, str]] = []
    for item in items:
        entry = item.to_entry()
        key = (entry["about"], entry["reason"], entry["what_would_resolve_it"])
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def policy_report() -> str:
    """The whole policy as text, for the demo and for review."""
    lines = [f"Abstention policy: {len(POLICY)} triggers.", ""]
    for grade in (BLOCKING, ADVISORY):
        members = [t for t in POLICY if t.grade == grade]
        lines.append(f"{grade.upper()} ({len(members)}) -- " + (
            "the value is withheld" if grade == BLOCKING else "the value is produced with the gap named"
        ))
        for spec in members:
            lines += [
                f"  {spec.name}  [{spec.rule_id}]",
                f"      says:  {spec.reason}",
                f"      fix:   {spec.what_would_resolve_it}",
                f"      why:   {spec.rationale}",
            ]
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "ADVISORY",
    "BLOCKING",
    "Abstention",
    "POLICY",
    "Trigger",
    "blocking",
    "policy_report",
    "raise_abstention",
    "to_entries",
    "trigger",
]


if __name__ == "__main__":  # pragma: no cover
    print(policy_report())
