"""60% AMI lookup for the frozen HMFA, and the comparison. Pure functions.

The whole module is 1-8 and nothing else. HUD publishes an extrapolation rule for
households larger than 8, and this module deliberately does not implement it: the pack
froze sizes 1-8 (rule HUD-MTSP-002), that is the scored universe, and a number sourced
from outside the pack would be an uncited rule wearing a citation's clothes. Size 9
returns ``no_frozen_threshold`` with an abstention that says who can supply the number.

The comparison is a comparison. It is not a determination, and nothing here returns a
word about the renter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from logic import abstain
from logic.abstain import Abstention
from logic.constants import (
    HMFA,
    LIMITS_50_PCT,
    LIMITS_60_PCT,
    LIMITS_EFFECTIVE_DATE,
    MEDIAN_FAMILY_INCOME,
)

#: The band the pack scores. RULES_README.md: "Compare it with the 60% AMI frozen threshold".
SCORED_BAND = "60%"
SCORED_BAND_RULE_ID = "HUD-MTSP-002"
FIFTY_PCT_RULE_ID = "HUD-MTSP-003"

MIN_FROZEN_SIZE = 1
MAX_FROZEN_SIZE = 8


@dataclass(frozen=True)
class Threshold:
    """A frozen limit, or an explicit absence of one."""

    household_size: int | None
    amount: float | None
    band: str = SCORED_BAND
    rule_id: str | None = SCORED_BAND_RULE_ID
    hmfa: str = HMFA
    effective_date: str = LIMITS_EFFECTIVE_DATE
    abstention: Abstention | None = None

    @property
    def available(self) -> bool:
        return self.amount is not None


def lookup_60_percent(household_size: Any) -> Threshold:
    """The frozen 60% limit for a household size, or an abstention.

    Sizes outside 1-8 are NOT extrapolated. That is the point of this function.
    """
    about = "frozen_60_percent_threshold"

    if household_size is None:
        return Threshold(
            None, None,
            abstention=abstain.raise_abstention("household_size_unknown", about),
            rule_id=None,
        )

    try:
        size = int(household_size)
    except (TypeError, ValueError):
        return Threshold(
            None, None,
            abstention=abstain.raise_abstention(
                "household_size_unknown", about, f"{household_size!r} is not a whole number"),
            rule_id=None,
        )

    if size < MIN_FROZEN_SIZE or size > MAX_FROZEN_SIZE:
        return Threshold(
            size, None,
            abstention=abstain.raise_abstention(
                "household_size_outside_frozen_table", about,
                f"household size {size}; the frozen table covers "
                f"{MIN_FROZEN_SIZE}-{MAX_FROZEN_SIZE}",
            ),
            rule_id=None,
        )

    return Threshold(size, float(LIMITS_60_PCT[size]))


def lookup_50_percent(household_size: Any) -> Threshold:
    """The 50% band (HUD-MTSP-003). Not the scored band; held for citation completeness."""
    result = lookup_60_percent(household_size)
    if not result.available:
        return Threshold(result.household_size, None, band="50%", rule_id=None,
                         abstention=result.abstention)
    return Threshold(result.household_size, float(LIMITS_50_PCT[result.household_size]),
                     band="50%", rule_id=FIFTY_PCT_RULE_ID)


@dataclass(frozen=True)
class ComparisonResult:
    """A number placed next to a threshold. Nothing more is claimed."""

    comparison: str
    annual_income: float | None
    threshold: Threshold
    abstentions: tuple[Abstention, ...] = ()

    def to_calculation(self, household_id: str, inputs: list[dict[str, Any]] | None = None,
                       formula: str = "") -> dict[str, Any]:
        return {
            "name": "annualized_income",
            "household_id": household_id,
            "inputs": list(inputs or []),
            "formula": formula,
            "result": self.annual_income,
            "threshold": self.threshold.amount,
            "threshold_rule_id": self.threshold.rule_id,
            "comparison": self.comparison,
            "effective_date": self.threshold.effective_date,
            "rule_id": "CH-INCOME-001",
        }


def compare_to_threshold(annual_income: float, threshold: float) -> str:
    """The bare comparison, matching ``pack/starter/src/calculate.py`` exactly.

    Agreement is asserted over a swept grid in ``logic/test_pack_agreement.py``, including
    the boundary (equal amounts are ``below_or_equal``) and the ValueError cases.
    """
    if annual_income < 0 or threshold < 0:
        raise ValueError("Values must be non-negative")
    return "below_or_equal" if annual_income <= threshold else "above"


def compare(annual_income: float | None, household_size: Any) -> ComparisonResult:
    """Full path: look the threshold up, then compare -- abstaining at either step."""
    threshold = lookup_60_percent(household_size)
    problems: list[Abstention] = []
    if threshold.abstention is not None:
        problems.append(threshold.abstention)

    if annual_income is None:
        problems.append(
            abstain.raise_abstention("income_unavailable_for_comparison", "threshold_comparison")
        )
        return ComparisonResult("no_frozen_threshold", None, threshold, tuple(problems))

    if not threshold.available:
        return ComparisonResult("no_frozen_threshold", annual_income, threshold, tuple(problems))

    return ComparisonResult(
        compare_to_threshold(annual_income, threshold.amount),
        annual_income,
        threshold,
        tuple(problems),
    )


def threshold_statement(threshold: Threshold) -> str:
    """A citable sentence about the threshold. Says nothing about any person."""
    if not threshold.available:
        return (
            f"No frozen {threshold.band} limit is available for household size "
            f"{threshold.household_size}; the frozen table covers "
            f"{MIN_FROZEN_SIZE}-{MAX_FROZEN_SIZE}."
        )
    return (
        f"${threshold.amount:,.0f} for household size {threshold.household_size}."
    )


def out_of_table_statement(household_size: Any) -> str:
    """What we say when a question names a size the frozen table has no row for.

    It says what we hold and where its edges are, so the asker can ask something we can
    answer, instead of stopping at "unknown". It does NOT compute the missing row: HUD's
    extrapolation rule for households above 8 is real and is deliberately not applied
    here, because a number sourced from outside the pack would break the one promise this
    service makes about its figures.
    """
    return (
        f"The frozen table we hold covers households of {MIN_FROZEN_SIZE} to "
        f"{MAX_FROZEN_SIZE}. For a household of {household_size} it has no row, and we "
        f"will not extrapolate one. Ask about a size from {MIN_FROZEN_SIZE} to "
        f"{MAX_FROZEN_SIZE} and the figure is available; for size {household_size} a "
        f"housing professional can supply the published limit with its source."
    )


def median_family_income() -> tuple[int, str]:
    return MEDIAN_FAMILY_INCOME, SCORED_BAND_RULE_ID


__all__ = [
    "ComparisonResult",
    "MAX_FROZEN_SIZE",
    "MIN_FROZEN_SIZE",
    "SCORED_BAND",
    "Threshold",
    "compare",
    "compare_to_threshold",
    "lookup_50_percent",
    "lookup_60_percent",
    "out_of_table_statement",
    "threshold_statement",
]
