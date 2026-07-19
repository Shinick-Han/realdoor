"""Constants for the reasoning layer, split by provenance.

Two tables live here and they are deliberately kept apart:

``FROZEN``
    Values that appear in ``contracts/FROZEN_CONSTANTS.md`` and trace to a file under
    ``pack/``. Each carries its source. These are not ours to change.

``CONVENTIONS``
    Values the pack did **not** freeze but that the reasoning layer needs in order to
    reproduce the pack's own expected answers. Each one records what it is, why it was
    needed, what evidence in the pack forced it, and what would falsify it. Nothing in
    this table is presented to a user as a cited rule; every user-visible claim cites a
    ``rule_id`` from the 11-rule corpus.

The split exists because the alternative -- quietly inventing a number and letting it
look frozen -- is the exact failure mode this project argues against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType

# =====================================================================================
# FROZEN -- traceable to pack/
# =====================================================================================

#: The event date for the whole simulation. Not today(). Source: pack/rules/RULES_README.md
#: ("no more than 60 days before 2026-07-18").
REFERENCE_DATE = date(2026, 7, 18)

#: Source: pack/rules/RULES_README.md line 11; rule CH-READINESS-001.
CURRENCY_WINDOW_DAYS = 60

#: Arithmetic consequence of the two above: a document is current when dated on or after
#: this day. 2026-05-19.
CURRENCY_FLOOR = REFERENCE_DATE - timedelta(days=CURRENCY_WINDOW_DAYS)

#: Source: pack/starter/src/calculate.py (identical table, verified by
#: logic/test_pack_agreement.py).
FREQUENCY = MappingProxyType(
    {"weekly": 52, "biweekly": 26, "semimonthly": 24, "monthly": 12, "annual": 1}
)

#: Source: rule HUD-MTSP-002 in pack/rules/rule_corpus.jsonl.
HMFA = "Boston-Cambridge-Quincy, MA-NH HMFA"
MEDIAN_FAMILY_INCOME = 164_600
LIMITS_60_PCT = MappingProxyType(
    {1: 72_000, 2: 82_320, 3: 92_580, 4: 102_840, 5: 111_120, 6: 119_340, 7: 127_560, 8: 135_780}
)

#: Source: rule HUD-MTSP-003. Held for citation completeness; the scored band is 60%.
LIMITS_50_PCT = MappingProxyType(
    {1: 60_000, 2: 68_600, 3: 77_150, 4: 85_700, 5: 92_600, 6: 99_450, 7: 106_300, 8: 113_150}
)

#: Source: rule HUD-MTSP-001.
LIMITS_EFFECTIVE_DATE = "2026-05-01"

#: The 11 rule ids in pack/rules/rule_corpus.jsonl. Every claim we emit cites one of these.
RULE_IDS = (
    "HUD-MTSP-001",
    "HUD-MTSP-002",
    "HUD-MTSP-003",
    "HUD-DATA-001",
    "HUD-GEO-001",
    "FED-LIHTC-001",
    "FED-MONITOR-001",
    "CH-INCOME-001",
    "CH-READINESS-001",
    "CH-SAFETY-001",
    "CH-DECISION-001",
)

#: contracts/CONTRACTS.md section 1, frozen enums.
COMPARISONS = ("below_or_equal", "above", "no_frozen_threshold")
READINESS_STATUSES = ("READY_TO_REVIEW", "NEEDS_REVIEW")
ITEM_STATES = ("present", "missing", "expired", "undatable", "unreadable")

#: contracts/CONTRACTS.md section 7.
HUMAN_DECISION_NOTICE = (
    "This is not an eligibility determination. A qualified housing professional must decide."
)

#: The pack's own review-reason vocabulary, from pack/evaluation/application_checklists.json
#: (`expected_review_reasons`). Carried as VALUES only, never as JSON keys -- see
#: eval/CONTRACT_CONFLICTS.md section 5.
PACK_REVIEW_REASONS = (
    "PAY_STUB_TOTAL_CONFLICT",
    "GIG_INCOME_UNCORROBORATED",
    "EMPLOYMENT_LETTER_EXPIRED",
)

#: The five document types that actually exist in pack/synthetic_documents/gold.
GOLD_DOCUMENT_TYPES = (
    "application_summary",
    "pay_stub",
    "employment_letter",
    "benefit_letter",
    "gig_statement",
)


# =====================================================================================
# CONVENTIONS -- needed by this layer, NOT frozen by the pack
# =====================================================================================


@dataclass(frozen=True)
class Convention:
    """A judgement call this layer had to make because the pack left a gap."""

    key: str
    value: object
    what_it_decides: str
    why_needed: str
    pack_evidence: str
    would_be_falsified_by: str


CONVENTIONS: tuple[Convention, ...] = (
    Convention(
        key="WAGE_SOURCE_IS_ONE_SOURCE",
        value=True,
        what_it_decides=(
            "Pay stubs and an employment letter describing the same job are ONE recurring "
            "income source, so their amounts corroborate rather than sum."
        ),
        why_needed=(
            "CH-INCOME-001 says to 'sum independently documented recurring sources' but does "
            "not define when two documents are independent sources versus two views of one."
        ),
        pack_evidence=(
            "In HH-001, HH-002 and HH-005 the employment letter's weekly_hours * hourly_rate "
            "* 52 equals the pay-stub annualization to the cent (56,316 / 49,920 / 45,968), "
            "and each equals the pack's expected_annualized_income. Summing them would double "
            "every wage household."
        ),
        would_be_falsified_by=(
            "A household whose expected_annualized_income equals stub + letter rather than "
            "stub alone."
        ),
    ),
    Convention(
        key="RECURRING_BASE_IS_THE_RECONCILING_STUB",
        value="gross_pay == regular_hours * hourly_rate",
        what_it_decides=(
            "When pay stubs disagree, the recurring amount is the one whose gross_pay "
            "reconciles with regular_hours * hourly_rate; the excess is treated as "
            "non-recurring variance and is NOT annualized."
        ),
        why_needed=(
            "CH-INCOME-001 says 'recurring' but the pack's overtime household ships two stubs "
            "with different gross_pay and no rule for choosing between them."
        ),
        pack_evidence=(
            "HH-002 (scenario 'overtime_variance') has stubs of 1,395.00 and 960.00 weekly. "
            "40h * $24.00 = 960.00 reconciles; 1,395.00 does not. The pack expects 49,920.00 "
            "= 960 * 52, and flags PAY_STUB_TOTAL_CONFLICT. Annualizing 1,395 would give "
            "72,540.00."
        ),
        would_be_falsified_by=(
            "A pack household whose expected income annualizes the non-reconciling stub, or "
            "averages the two."
        ),
    ),
    Convention(
        key="MONTHLY_STATEMENT_PERIOD_IS_A_STATED_FREQUENCY",
        value="statement_month (YYYY-MM) implies frequency 'monthly'",
        what_it_decides=(
            "A gig statement covering one named calendar month is read as a stated monthly "
            "period, so gross_receipts annualize at x12."
        ),
        why_needed=(
            "CH-INCOME-001 requires an EXPLICIT pay frequency. A gig statement carries a "
            "coverage month, not a frequency field. Read strictly, gig income could not be "
            "annualized at all."
        ),
        pack_evidence=(
            "HH-004: wages 1,408.00 biweekly = 36,608.00; the pack expects 51,008.00; the "
            "difference is exactly 14,400.00 = 1,200.00 * 12, the gig statement's "
            "gross_receipts over its single stated month."
        ),
        would_be_falsified_by=(
            "A gig household whose expected income excludes the gig amount, or annualizes it "
            "net of platform fees (1,080 * 12 = 12,960 would give 49,568.00, not 51,008.00)."
        ),
    ),
    Convention(
        key="GIG_INCOME_IS_GROSS_OF_PLATFORM_FEES",
        value=True,
        what_it_decides="gross_receipts is annualized; platform_fees are not deducted.",
        why_needed="CH-INCOME-001 says 'gross income' but the statement itemizes fees.",
        pack_evidence=(
            "HH-004 expected 51,008.00 requires 1,200 * 12, not (1,200 - 120) * 12."
        ),
        would_be_falsified_by="An expected income consistent with net receipts.",
    ),
    Convention(
        key="REDUNDANT_REQUIRED_DOCUMENT_DOES_NOT_BLOCK_READINESS",
        value="employment_letter is substitutable by >=2 mutually agreeing pay stubs",
        what_it_decides=(
            "A required document type whose evidentiary job is already done by other present "
            "documents is reported 'missing' on the checklist but does not, by itself, force "
            "NEEDS_REVIEW."
        ),
        why_needed=(
            "The pack's checklist file contradicts itself if presence is read literally: it "
            "lists employment_letter as required and missing for HH-003 and HH-006, yet "
            "expects READY_TO_REVIEW with an EMPTY expected_review_reasons list."
        ),
        pack_evidence=(
            "HH-003 and HH-006: missing_document_types == ['employment_letter'], "
            "expected_readiness_status == 'READY_TO_REVIEW', expected_review_reasons == []. "
            "Meanwhile HH-005 has every required type present and is NEEDS_REVIEW. Readiness "
            "in this pack is driven by review reasons, not document completeness. Both "
            "READY households have two pay stubs that agree with each other, so the wage "
            "source is already internally consistent without the letter."
        ),
        would_be_falsified_by=(
            "A household missing an employment_letter that the pack still expects to be "
            "NEEDS_REVIEW for that reason, or a READY household with disagreeing stubs."
        ),
    ),
    Convention(
        key="SELF_REPORTED_INCOME_HAS_NO_SUBSTITUTE",
        value="gig_income_corroboration cannot be satisfied by the gig_statement itself",
        what_it_decides=(
            "A self-reported income document cannot corroborate itself, so a missing "
            "corroboration document is a genuine readiness gap."
        ),
        why_needed="Distinguishes HH-004 (blocked) from HH-003/HH-006 (not blocked).",
        pack_evidence=(
            "HH-004 required_document_types includes 'gig_income_corroboration', which is not "
            "one of the five real document types in the gold; the pack expects NEEDS_REVIEW "
            "with reason GIG_INCOME_UNCORROBORATED."
        ),
        would_be_falsified_by="A gig household expected READY_TO_REVIEW with no corroboration.",
    ),
    Convention(
        key="UNDATABLE_IS_NOT_UNREADABLE",
        value="YYYY-MM precision yields state 'undatable'",
        what_it_decides=(
            "A document we read successfully but whose date lacks day precision is 'undatable', "
            "not 'unreadable', and the 60-day window is not applied to it."
        ),
        why_needed=(
            "contracts/CONTRACTS.md section 1 defines 'undatable' for exactly this case. "
            "core/extract.assess_staleness() currently returns 'unreadable' here -- a "
            "divergence reported to the conductor rather than silently matched."
        ),
        pack_evidence="HH-004-D04 gig_statement carries statement_month='2026-06', no day.",
        would_be_falsified_by="A pack rule defining a day to assume for month-precision dates.",
    ),
)

CONVENTION_KEYS = tuple(c.key for c in CONVENTIONS)


def convention(key: str) -> Convention:
    for item in CONVENTIONS:
        if item.key == key:
            return item
    raise KeyError(f"no such convention: {key!r}")


def unfrozen_constants_report() -> str:
    """Human-readable list of every value this layer needed that the pack did not freeze."""
    lines = [
        f"{len(CONVENTIONS)} value(s) needed by logic/ are NOT in contracts/FROZEN_CONSTANTS.md:",
        "",
    ]
    for item in CONVENTIONS:
        lines += [
            f"* {item.key} = {item.value!r}",
            f"    decides:   {item.what_it_decides}",
            f"    needed:    {item.why_needed}",
            f"    evidence:  {item.pack_evidence}",
            f"    falsified: {item.would_be_falsified_by}",
            "",
        ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    print(unfrozen_constants_report())
