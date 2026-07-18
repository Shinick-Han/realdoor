"""Checklist evaluation into ``ChecklistItem`` objects (CONTRACTS section 6).

``ItemState`` is exactly ``present | missing | expired | undatable | unreadable``.

Two things about that enum are load-bearing:

* ``expiring_soon`` is gone. The pack defines no threshold for "soon", so emitting it
  would mean shipping a number we invented under the appearance of a cited rule. The UI
  shows ``days_until_stale`` instead and lets the reader decide what soon means.
* ``undatable`` is not ``unreadable``. We read HH-004's gig statement perfectly well; it
  simply says ``2026-06`` with no day. Saying "unreadable" would be a false statement
  about our own capability, and assuming a day would be a fabricated fact.

Every item cites ``CH-READINESS-001``, which is the rule that makes required evidence a
readiness condition. ``required_because_rule_id`` is constrained to the 11 pack rule ids;
``CH-DOC-STUBS`` and ``CH-DOC-120DAY``, which appear in CONTRACTS, do not exist in the
pack corpus and are never emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from logic import abstain
from logic.abstain import Abstention
from logic.constants import CURRENCY_FLOOR, ITEM_STATES, REFERENCE_DATE, RULE_IDS
from logic.household import Document, Household, read_document_date

READINESS_RULE_ID = "CH-READINESS-001"

#: Human labels for the document types the pack uses. A type with no entry falls back to
#: a de-underscored version of its own name -- unknown types are never dropped silently.
LABELS = {
    "application_summary": "Application summary",
    "pay_stub": "Recent pay stubs",
    "employment_letter": "Employment verification letter",
    "benefit_letter": "Benefit award letter",
    "gig_statement": "Gig platform earnings statement",
    "gig_income_corroboration": "Independent corroboration of gig income",
}

ACTIONS = {
    "application_summary": "Upload your completed application summary",
    "pay_stub": "Upload your two most recent pay stubs",
    "employment_letter": "Ask your employer for a signed employment verification letter",
    "benefit_letter": "Upload your current benefit award letter",
    "gig_statement": "Upload your most recent gig platform earnings statement",
    "gig_income_corroboration": (
        "Upload bank deposits, platform earnings records, or a 1099 covering the same period"
    ),
}

#: A required type whose evidentiary job can be done by other documents already in the
#: file. Value is a predicate over the household. See constants.CONVENTIONS
#: ('REDUNDANT_REQUIRED_DOCUMENT_DOES_NOT_BLOCK_READINESS') for the pack evidence.
#: A self-reported document can never substitute for its own corroboration.
def _two_agreeing_pay_stubs(house: Household) -> bool:
    stubs = house.of_type("pay_stub")
    if len(stubs) < 2:
        return False
    totals = {d.value("gross_pay") for d in stubs if d.get("gross_pay")}
    return len(totals) == 1 and None not in totals


SUBSTITUTES = {
    "employment_letter": (
        _two_agreeing_pay_stubs,
        "two pay stubs reporting the same gross pay already document this wage source",
    ),
}


def label_for(document_type: str) -> str:
    return LABELS.get(document_type, document_type.replace("_", " ").capitalize())


def item_id_for(document_type: str) -> str:
    return "CHK-" + document_type.upper().replace("_", "-")


@dataclass(frozen=True)
class ChecklistItem:
    """CONTRACTS section 6, plus internals that never reach the JSON."""

    item_id: str
    label: str
    required_because_rule_id: str
    state: str
    satisfied_by: tuple[str, ...]
    detail: str
    action_for_renter: str | None
    required: bool = True
    substituted: bool = False
    abstentions: tuple[Abstention, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in ITEM_STATES:
            raise ValueError(f"{self.state!r} is not an ItemState; frozen set is {ITEM_STATES}")
        if self.required_because_rule_id not in RULE_IDS:
            raise ValueError(f"{self.required_because_rule_id!r} is not a pack rule id")

    @property
    def blocking(self) -> bool:
        """Does this item, on its own, prevent READY_TO_REVIEW?"""
        if self.state == "present":
            return False
        if not self.required:
            return False
        if self.state == "missing" and self.substituted:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "required_because_rule_id": self.required_because_rule_id,
            "state": self.state,
            "satisfied_by": list(self.satisfied_by),
            "detail": self.detail,
            "action_for_renter": self.action_for_renter,
        }


def _state_for_document(doc: Document) -> tuple[str, str]:
    """(state, detail) for one document under the 60-day convention."""
    if not doc.readable:
        return "unreadable", f"{doc.document_id} could not be read"

    dated = read_document_date(doc)
    if dated.precision == "month":
        return "undatable", (
            f"{doc.document_id} is dated {dated.raw} (month precision); the 60-day "
            f"convention cannot be applied without inventing a day"
        )
    if dated.precision == "none":
        return "undatable", f"{doc.document_id} carries no readable document date"
    if dated.current is False:
        return "expired", (
            f"{doc.document_id} is dated {dated.raw}, outside the 60-day window "
            f"(on or after {CURRENCY_FLOOR.isoformat()} for the frozen event date "
            f"{REFERENCE_DATE.isoformat()})"
        )
    return "present", (
        f"{doc.document_id} is dated {dated.raw}, current with "
        f"{dated.days_until_stale} day(s) of the window remaining"
    )


#: Worst-first, so a set of documents is described by its weakest member.
_SEVERITY = {"unreadable": 4, "expired": 3, "undatable": 2, "missing": 1, "present": 0}


def evaluate_item(house: Household, document_type: str, required: bool = True) -> ChecklistItem:
    docs = house.of_type(document_type)
    item_id = item_id_for(document_type)
    label = label_for(document_type)
    action = ACTIONS.get(document_type, f"Upload your {label.lower()}")

    if not docs:
        substituted = False
        detail = f"no {label.lower()} found in this file"
        problems: list[Abstention] = []
        substitute = SUBSTITUTES.get(document_type)
        if substitute is not None and substitute[0](house):
            substituted = True
            detail = f"{detail}; {substitute[1]}"
        if required and not substituted:
            problems.append(
                abstain.raise_abstention("required_document_missing", item_id, detail)
            )
        return ChecklistItem(
            item_id=item_id,
            label=label,
            required_because_rule_id=READINESS_RULE_ID,
            state="missing",
            satisfied_by=(),
            detail=detail,
            action_for_renter=action,
            required=required,
            substituted=substituted,
            abstentions=tuple(problems),
        )

    assessed = [(doc, *_state_for_document(doc)) for doc in docs]
    worst = max(assessed, key=lambda row: _SEVERITY[row[1]])
    state = worst[1]
    details = "; ".join(row[2] for row in assessed)

    problems = []
    if state == "expired":
        problems.append(abstain.raise_abstention("document_not_current", item_id, worst[2]))
    elif state == "undatable":
        problems.append(
            abstain.raise_abstention("document_date_month_precision", item_id, worst[2])
        )
    elif state == "unreadable":
        problems.append(abstain.raise_abstention("document_unreadable", item_id, worst[2]))

    untraceable = sorted({f"{doc.document_id}:{name}"
                          for doc in docs for name in doc.untraceable_fields})
    if untraceable:
        problems.append(
            abstain.raise_abstention("value_not_traceable", item_id, ", ".join(untraceable))
        )

    return ChecklistItem(
        item_id=item_id,
        label=label,
        required_because_rule_id=READINESS_RULE_ID,
        state=state,
        satisfied_by=tuple(doc.document_id for doc in docs),
        detail=details,
        action_for_renter=None if state == "present" else action,
        required=required,
        abstentions=tuple(problems),
    )


def evaluate_checklist(house: Household, required_types: Sequence[str]) -> list[ChecklistItem]:
    """Items for every required type, plus any present type the checklist did not require.

    Extra present documents are included as non-required items so that, for example,
    HH-004's gig statement can carry its ``undatable`` state visibly rather than being
    invisible because the pack's required list happens to name a corroboration document
    instead of the statement itself.
    """
    ordered = list(dict.fromkeys(required_types))
    items = [evaluate_item(house, t, required=True) for t in ordered]
    extras = [t for t in sorted(house.present_types) if t not in ordered]
    items += [evaluate_item(house, t, required=False) for t in extras]
    return items


def blocking_items(items: Sequence[ChecklistItem]) -> list[ChecklistItem]:
    return [i for i in items if i.blocking]


def checklist_abstentions(items: Sequence[ChecklistItem]) -> list[Abstention]:
    out: list[Abstention] = []
    for item in items:
        out.extend(item.abstentions)
    return out


__all__ = [
    "ChecklistItem",
    "SUBSTITUTES",
    "blocking_items",
    "checklist_abstentions",
    "evaluate_checklist",
    "evaluate_item",
    "item_id_for",
    "label_for",
]
