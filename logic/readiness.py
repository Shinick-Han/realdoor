"""READY_TO_REVIEW vs NEEDS_REVIEW under CH-READINESS-001. Pure functions.

    "Return READY_TO_REVIEW only when required evidence is present, current under the
     challenge's 60-day convention, internally consistent, and traceable to page-level
     source boxes. Otherwise return NEEDS_REVIEW with reasons."

That is four conditions, so this module runs four checks, each in its own function, each
producing its own reason string when it fails. They are not collapsed into one boolean,
because "NEEDS_REVIEW" with no reason is the same as no answer at all -- the renter
cannot act on it and the reviewer cannot check it.

    present   -> _check_presence
    current   -> _check_currency
    consistent-> _check_consistency
    traceable -> _check_traceability

What this module never does: emit an eligibility judgement. ``NEEDS_REVIEW`` means our
packet is incomplete, not that anything is wrong with the renter. ``READY_TO_REVIEW``
means a human can now start, not that they will say yes. The distinction is the entire
product.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from logic import abstain, checklist as checklist_mod
from logic.abstain import Abstention
from logic.checklist import ChecklistItem
from logic.constants import (
    HUMAN_DECISION_NOTICE,
    READINESS_STATUSES,
    REFERENCE_DATE,
    RULE_IDS,
)
from logic.household import Household, load_rule_corpus, read_document_date
from logic.income import AnnualizedIncome, annualize_household
from logic.threshold import ComparisonResult, compare

READY = "READY_TO_REVIEW"
NEEDS_REVIEW = "NEEDS_REVIEW"
RULE_ID = "CH-READINESS-001"

#: The four CH-READINESS-001 conditions, in the rule's own order.
CHECKS = ("present", "current", "consistent", "traceable")

#: Our reason codes, mapped onto the pack's own vocabulary where the pack has one
#: (pack/evaluation/application_checklists.json `expected_review_reasons`). Codes are
#: carried as VALUES only, never as JSON keys.
PACK_CODE_BY_TRIGGER = {
    "pay_stub_totals_conflict": "PAY_STUB_TOTAL_CONFLICT",
    "pay_stub_totals_irreconcilable": "PAY_STUB_TOTAL_CONFLICT",
    "self_reported_income_uncorroborated": "GIG_INCOME_UNCORROBORATED",
}

GENERIC_CODE_BY_TRIGGER = {
    "required_document_missing": "REQUIRED_DOCUMENT_MISSING",
    "document_not_current": "DOCUMENT_NOT_CURRENT",
    "document_date_month_precision": "DOCUMENT_UNDATABLE",
    "document_unreadable": "DOCUMENT_UNREADABLE",
    "value_not_traceable": "VALUE_NOT_TRACEABLE",
}


@dataclass(frozen=True)
class ReadinessReason:
    """One named gap. Always about the packet, never about the person."""

    check: str
    code: str
    message: str
    rule_id: str = RULE_ID

    def __post_init__(self) -> None:
        if self.check not in CHECKS:
            raise ValueError(f"{self.check!r} is not one of the four CH-READINESS-001 checks")
        if self.rule_id not in RULE_IDS:
            raise ValueError(f"{self.rule_id!r} is not a pack rule id")

    def to_dict(self) -> dict[str, str]:
        return {"check": self.check, "code": self.code, "message": self.message,
                "rule_id": self.rule_id}


@dataclass(frozen=True)
class ReadinessAssessment:
    readiness_status: str
    reasons: tuple[ReadinessReason, ...]
    checklist: tuple[ChecklistItem, ...]
    income: AnnualizedIncome
    comparison: ComparisonResult
    abstentions: tuple[Abstention, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(r.code for r in self.reasons))

    def reasons_for(self, check: str) -> tuple[ReadinessReason, ...]:
        return tuple(r for r in self.reasons if r.check == check)


def _code_for(item: Abstention, subject: str = "") -> str:
    if item.trigger in PACK_CODE_BY_TRIGGER:
        return PACK_CODE_BY_TRIGGER[item.trigger]
    # The pack names one specific expired document; use its vocabulary when it applies.
    if item.trigger == "document_not_current" and "EMPLOYMENT-LETTER" in item.about:
        return "EMPLOYMENT_LETTER_EXPIRED"
    if item.trigger == "required_document_missing" and "GIG-INCOME-CORROBORATION" in item.about:
        return "GIG_INCOME_UNCORROBORATED"
    return GENERIC_CODE_BY_TRIGGER.get(item.trigger, item.trigger.upper())


# =====================================================================================
# the four checks
# =====================================================================================


def _check_presence(items: Sequence[ChecklistItem]) -> list[ReadinessReason]:
    """Condition 1: required evidence is PRESENT.

    A required document that is missing but whose evidentiary job is already done by
    other present documents is reported on the checklist and does not raise a reason
    here -- see constants.CONVENTIONS['REDUNDANT_REQUIRED_DOCUMENT_DOES_NOT_BLOCK_READINESS'],
    which exists because the pack's own checklist demands it.
    """
    reasons: list[ReadinessReason] = []
    for item in items:
        if item.state != "missing" or not item.required or item.substituted:
            continue
        for problem in item.abstentions:
            if problem.trigger == "required_document_missing":
                reasons.append(ReadinessReason(
                    "present", _code_for(problem, item.item_id),
                    f"{item.label}: {item.detail}",
                ))
    return reasons


def _check_currency(items: Sequence[ChecklistItem]) -> list[ReadinessReason]:
    """Condition 2: evidence is CURRENT under the 60-day convention.

    'undatable' fails this check too: a document whose date lacks day precision cannot
    be shown to be current, and we will not invent the day that would settle it.
    """
    reasons: list[ReadinessReason] = []
    for item in items:
        if item.state not in ("expired", "undatable"):
            continue
        for problem in item.abstentions:
            if problem.trigger in ("document_not_current", "document_date_month_precision",
                                  "document_unreadable"):
                reasons.append(ReadinessReason(
                    "current", _code_for(problem, item.item_id),
                    f"{item.label}: {item.detail}",
                ))
    return reasons


def _check_consistency(house: Household, income: AnnualizedIncome) -> list[ReadinessReason]:
    """Condition 3: evidence is INTERNALLY CONSISTENT.

    Two families of inconsistency are checked: numbers that disagree across documents
    (pay stub totals, and an employment letter that contradicts the stubs), and the
    documents not agreeing on whose file this is.
    """
    reasons: list[ReadinessReason] = []

    for problem in income.abstentions:
        if problem.trigger in ("pay_stub_totals_conflict", "pay_stub_totals_irreconcilable"):
            reasons.append(ReadinessReason("consistent", _code_for(problem), problem.reason))

    names = {str(doc.value("person_name")).strip()
             for doc in house.documents if doc.get("person_name")}
    if len(names) > 1:
        reasons.append(ReadinessReason(
            "consistent", "PERSON_NAME_MISMATCH",
            f"documents in this file name different people: {sorted(names)}",
        ))

    # Uncorroborated self-reported income is an evidence-quality gap, and the pack files
    # it under review reasons rather than under presence.
    for problem in income.abstentions:
        if problem.trigger == "self_reported_income_uncorroborated":
            reasons.append(ReadinessReason("consistent", _code_for(problem), problem.reason))

    return reasons


def _check_traceability(house: Household, items: Sequence[ChecklistItem]) -> list[ReadinessReason]:
    """Condition 4: every value is TRACEABLE to a page-level source box."""
    reasons: list[ReadinessReason] = []
    for item in items:
        for problem in item.abstentions:
            if problem.trigger == "value_not_traceable":
                reasons.append(ReadinessReason(
                    "traceable", _code_for(problem, item.item_id),
                    f"{item.label}: {problem.reason}",
                ))
    return reasons


# =====================================================================================
# assessment
# =====================================================================================


def assess_readiness(
    house: Household,
    required_types: Sequence[str],
    income: AnnualizedIncome | None = None,
) -> ReadinessAssessment:
    """Run all four CH-READINESS-001 checks and return a status with its reasons."""
    income = income if income is not None else annualize_household(house)
    items = checklist_mod.evaluate_checklist(house, required_types)
    result = compare(income.total, house.size)

    reasons: list[ReadinessReason] = []
    reasons += _check_presence(items)
    reasons += _check_currency(items)
    reasons += _check_consistency(house, income)
    reasons += _check_traceability(house, items)

    # An income we could not compute is a review reason in its own right: the packet is
    # not ready for a human if the central number is absent.
    if income.total is None:
        reasons.append(ReadinessReason(
            "present", "INCOME_NOT_COMPUTABLE",
            "no recurring income could be annualized from the documents in this file",
            rule_id="CH-INCOME-001",
        ))
    if result.comparison == "no_frozen_threshold" and income.total is not None:
        reasons.append(ReadinessReason(
            "present", "NO_FROZEN_THRESHOLD",
            result.threshold.abstention.reason if result.threshold.abstention
            else "no frozen threshold applies to this household size",
            rule_id="HUD-MTSP-002",
        ))

    deduped: list[ReadinessReason] = []
    seen: set[tuple[str, str, str]] = set()
    for reason in reasons:
        key = (reason.check, reason.code, reason.message)
        if key not in seen:
            seen.add(key)
            deduped.append(reason)

    problems: list[Abstention] = list(income.abstentions)
    problems += checklist_mod.checklist_abstentions(items)
    problems += list(result.abstentions)

    status = READY if not deduped else NEEDS_REVIEW
    assert status in READINESS_STATUSES
    return ReadinessAssessment(
        readiness_status=status,
        reasons=tuple(deduped),
        checklist=tuple(items),
        income=income,
        comparison=result,
        abstentions=tuple(problems),
    )


# =====================================================================================
# report assembly (CONTRACTS section 7)
# =====================================================================================


def build_report(
    house: Household,
    required_types: Sequence[str],
    generated_at: str | None = None,
    engine_version: str = "sha:unversioned",
    ruleset_version: str = "pack-v1/2026-05-01",
) -> dict[str, Any]:
    """A ``ReadinessReport``. Contains no eligibility judgement, by construction."""
    assessment = assess_readiness(house, required_types)
    rules = load_rule_corpus()

    cited: list[str] = ["CH-READINESS-001", "CH-INCOME-001", "CH-DECISION-001"]
    if assessment.comparison.threshold.rule_id:
        cited.append(assessment.comparison.threshold.rule_id)
    cited.append("HUD-MTSP-001")
    if any(doc.get("untrusted_instruction_text") for doc in house.documents):
        cited.append("CH-SAFETY-001")

    calculations = [s.to_calculation(house.household_id) for s in assessment.income.sources]
    total = assessment.income.to_calculation()
    calculations.append(assessment.comparison.to_calculation(
        house.household_id, total["inputs"], total["formula"]))

    return {
        "household_id": house.household_id,
        "generated_at": generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ruleset_version": ruleset_version,
        "reference_date": REFERENCE_DATE.isoformat(),
        "readiness_status": assessment.readiness_status,
        "review_reasons": [r.to_dict() for r in assessment.reasons],
        "documents": [
            {
                "document_id": doc.document_id,
                "document_type": doc.document_type,
                "file_name": doc.file_name,
                "document_date": read_document_date(doc).raw,
                "days_until_stale": read_document_date(doc).days_until_stale,
                "stale_rule_id": RULE_ID,
            }
            for doc in house.documents
        ],
        "calculations": calculations,
        "checklist": [item.to_dict() for item in assessment.checklist],
        "citations": [
            {
                "rule_id": rid,
                "authority": rules[rid]["authority"],
                "effective_date": rules[rid]["effective_date"],
                "text": rules[rid]["text"],
                "source_url": rules[rid]["source_url"],
                "source_locator": rules[rid]["source_locator"],
                "verified_against_source": None,
            }
            for rid in dict.fromkeys(cited)
            if rid in rules
        ],
        "abstentions": abstain.to_entries(assessment.abstentions),
        "human_decision_notice": HUMAN_DECISION_NOTICE,
        "engine_version": engine_version,
    }


__all__ = [
    "CHECKS",
    "NEEDS_REVIEW",
    "READY",
    "ReadinessAssessment",
    "ReadinessReason",
    "assess_readiness",
    "build_report",
]
