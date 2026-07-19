"""Threshold lookup and comparison, including the deliberate refusal to extrapolate."""

from __future__ import annotations

import pytest

from logic.constants import LIMITS_60_PCT
from logic.threshold import (
    MAX_FROZEN_SIZE,
    compare,
    compare_to_threshold,
    lookup_50_percent,
    lookup_60_percent,
    threshold_statement,
)


@pytest.mark.parametrize(
    "size,expected",
    [(1, 72000.0), (2, 82320.0), (3, 92580.0), (4, 102840.0),
     (5, 111120.0), (6, 119340.0), (7, 127560.0), (8, 135780.0)],
)
def test_frozen_60_percent_table(size, expected):
    result = lookup_60_percent(size)
    assert result.amount == expected
    assert result.rule_id == "HUD-MTSP-002"
    assert result.available


def test_the_table_is_exactly_the_rule_corpus_values():
    """Guards against a typo in the constants drifting away from HUD-MTSP-002."""
    from logic.household import load_rule_corpus

    text = load_rule_corpus()["HUD-MTSP-002"]["text"]
    for size, amount in LIMITS_60_PCT.items():
        assert f"{amount:,}" in text, f"size {size} limit {amount:,} is not in the rule text"


@pytest.mark.parametrize("size", [9, 10, 0, -1, 100])
def test_sizes_outside_the_frozen_table_do_not_extrapolate(size):
    result = lookup_60_percent(size)
    assert result.amount is None
    assert result.rule_id is None
    assert result.abstention.trigger == "household_size_outside_frozen_table"
    assert result.abstention.blocking


def test_size_nine_returns_no_frozen_threshold_not_a_computed_one():
    """HUD publishes an extrapolation rule for 9+. The pack did not. The pack wins."""
    result = compare(150000.0, 9)
    assert result.comparison == "no_frozen_threshold"
    assert result.threshold.amount is None
    # 8-person limit plus the real-world 8% step would be ~146,642; we must not emit it.
    assert result.threshold.amount != 146642.4


def test_unknown_household_size_abstains():
    result = lookup_60_percent(None)
    assert result.abstention.trigger == "household_size_unknown"


def test_non_integer_household_size_abstains():
    assert lookup_60_percent("two").abstention.trigger == "household_size_unknown"


@pytest.mark.parametrize(
    "income,threshold,expected",
    [
        (39000.0, 72000.0, "below_or_equal"),
        (72000.0, 72000.0, "below_or_equal"),  # the boundary is inclusive
        (72000.01, 72000.0, "above"),
        (0.0, 0.0, "below_or_equal"),
    ],
)
def test_compare_to_threshold(income, threshold, expected):
    assert compare_to_threshold(income, threshold) == expected


def test_compare_to_threshold_rejects_negatives():
    with pytest.raises(ValueError):
        compare_to_threshold(-1.0, 100.0)
    with pytest.raises(ValueError):
        compare_to_threshold(100.0, -1.0)


def test_compare_at_the_boundary_is_below_or_equal():
    assert compare(72000.0, 1).comparison == "below_or_equal"
    assert compare(72000.01, 1).comparison == "above"


def test_compare_without_income_abstains():
    result = compare(None, 1)
    assert result.comparison == "no_frozen_threshold"
    assert any(a.trigger == "income_unavailable_for_comparison" for a in result.abstentions)


def test_above_is_a_comparison_not_a_judgement():
    """'above' must stay a statement about two numbers."""
    result = compare(200000.0, 1)
    assert result.comparison == "above"
    assert result.comparison in ("below_or_equal", "above", "no_frozen_threshold")


def test_50_percent_band_is_available_for_citation():
    assert lookup_50_percent(1).amount == 60000.0
    assert lookup_50_percent(1).rule_id == "HUD-MTSP-003"
    assert lookup_50_percent(9).amount is None


def test_threshold_statement_formats_like_the_pack():
    assert threshold_statement(lookup_60_percent(1)) == "$72,000 for household size 1."
    assert threshold_statement(lookup_60_percent(2)) == "$82,320 for household size 2."


def test_threshold_statement_for_unfrozen_size_says_so():
    text = threshold_statement(lookup_60_percent(MAX_FROZEN_SIZE + 1))
    assert "No frozen" in text and "1-8" in text


def test_calculation_shape_matches_the_contract():
    result = compare(39000.0, 1)
    calculation = result.to_calculation("HH-001")
    for key in ("name", "inputs", "formula", "result", "threshold", "threshold_rule_id",
                "comparison", "effective_date"):
        assert key in calculation
    assert calculation["threshold"] == 72000.0
    assert calculation["threshold_rule_id"] == "HUD-MTSP-002"


def test_no_frozen_threshold_carries_a_null_threshold():
    """CONTRACTS section 5: no threshold means comparison is the abstention value."""
    calculation = compare(39000.0, 9).to_calculation("HH-999")
    assert calculation["threshold"] is None
    assert calculation["comparison"] == "no_frozen_threshold"
