"""Agreement with the organizer: their arithmetic, their gold, their expectations.

Where we and the organizer overlap, they win. These tests are the record of whether we
actually agree, swept rather than spot-checked, so the claim can be re-run rather than
believed.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from logic import income as our_income
from logic import threshold as our_threshold
from logic.constants import FREQUENCY
from logic.household import load_pack_checklists, repo_root
from logic.income import annualize_household
from logic.readiness import assess_readiness


def _load_organizer_module():
    """Import pack/starter/src/calculate.py directly, without touching the pack."""
    path = repo_root() / "pack" / "starter" / "src" / "calculate.py"
    spec = importlib.util.spec_from_file_location("_organizer_calculate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


organizer = _load_organizer_module()


# =====================================================================================
# their arithmetic
# =====================================================================================


def test_frequency_table_is_identical():
    assert dict(FREQUENCY) == organizer.FREQUENCY


AMOUNTS = [0.0, 0.01, 1.0, 99.99, 100.0, 850.0, 960.0, 1155.0, 1200.0, 1395.0, 1408.0,
           1768.0, 2166.0, 3600.0, 10000.0, 123456.78]


@pytest.mark.parametrize("amount", AMOUNTS)
@pytest.mark.parametrize("frequency", sorted(FREQUENCY))
def test_annualize_agrees_with_the_organizer(amount, frequency):
    assert our_income.annualize(amount, frequency) == organizer.annualize(amount, frequency)


@pytest.mark.parametrize("frequency", ["fortnightly", "", "WEEKLY", "daily", None])
def test_annualize_rejects_the_same_frequencies_the_organizer_rejects(frequency):
    with pytest.raises(ValueError):
        organizer.annualize(100.0, frequency)
    with pytest.raises(ValueError):
        our_income.annualize(100.0, frequency)


def test_annualize_rejects_negative_amounts_like_the_organizer():
    with pytest.raises(ValueError):
        organizer.annualize(-0.01, "weekly")
    with pytest.raises(ValueError):
        our_income.annualize(-0.01, "weekly")


PAIRS = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (71999.99, 72000.0), (72000.0, 72000.0),
         (72000.01, 72000.0), (49920.0, 82320.0), (105000.0, 119340.0),
         (135780.0, 135780.0), (999999.0, 72000.0)]


@pytest.mark.parametrize("income,threshold", PAIRS)
def test_compare_to_threshold_agrees_with_the_organizer(income, threshold):
    assert our_threshold.compare_to_threshold(income, threshold) == \
        organizer.compare_to_threshold(income, threshold)


@pytest.mark.parametrize("income,threshold", [(-1.0, 100.0), (100.0, -1.0), (-1.0, -1.0)])
def test_compare_rejects_the_same_negatives(income, threshold):
    with pytest.raises(ValueError):
        organizer.compare_to_threshold(income, threshold)
    with pytest.raises(ValueError):
        our_threshold.compare_to_threshold(income, threshold)


def test_agreement_is_total_over_the_swept_grid():
    """One assertion carrying the whole claim, so the count is visible in one place."""
    checked = disagreed = 0
    for amount in AMOUNTS:
        for frequency in FREQUENCY:
            checked += 1
            if our_income.annualize(amount, frequency) != organizer.annualize(amount, frequency):
                disagreed += 1
    for pair in PAIRS:
        checked += 1
        if our_threshold.compare_to_threshold(*pair) != organizer.compare_to_threshold(*pair):
            disagreed += 1
    assert disagreed == 0, f"{disagreed} of {checked} disagreements with the organizer"
    assert checked == len(AMOUNTS) * len(FREQUENCY) + len(PAIRS)


# =====================================================================================
# their gold
# =====================================================================================

PACK = load_pack_checklists()
HOUSEHOLD_IDS = sorted(PACK)


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_annualized_income_matches_the_pack(household_id, gold_households):
    expected = PACK[household_id]["expected_annualized_income"]
    actual = annualize_household(gold_households[household_id]).total
    assert actual == expected, f"{household_id}: got {actual}, pack expects {expected}"


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_threshold_matches_the_pack(household_id, gold_households):
    expected = PACK[household_id]["frozen_60_percent_threshold"]
    house = gold_households[household_id]
    assert our_threshold.lookup_60_percent(house.size).amount == float(expected)


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_comparison_matches_the_pack(household_id, gold_households):
    house = gold_households[household_id]
    result = assess_readiness(house, PACK[household_id]["required_document_types"])
    assert result.comparison.comparison == PACK[household_id]["comparison"]


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_readiness_status_matches_the_pack(household_id, gold_households):
    house = gold_households[household_id]
    result = assess_readiness(house, PACK[household_id]["required_document_types"])
    assert result.readiness_status == PACK[household_id]["expected_readiness_status"]


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_every_pack_review_reason_is_raised(household_id, gold_households):
    """We must raise every reason the pack expects. We may raise more; see below."""
    house = gold_households[household_id]
    result = assess_readiness(house, PACK[household_id]["required_document_types"])
    expected = set(PACK[household_id]["expected_review_reasons"])
    assert expected.issubset(set(result.codes)), (
        f"{household_id}: pack expects {sorted(expected)}, we raised {sorted(result.codes)}"
    )


#: Reasons we raise that the pack's expected list does not contain. Recorded rather than
#: suppressed. HH-004's gig statement is dated "2026-06" with no day, so it genuinely
#: cannot be shown current under a 60-day convention; the pack simply did not list that
#: alongside GIG_INCOME_UNCORROBORATED. The readiness STATUS is unaffected -- HH-004 is
#: NEEDS_REVIEW either way.
KNOWN_EXTRA_REASONS = {"HH-004": {"DOCUMENT_UNDATABLE"}}


@pytest.mark.parametrize("household_id", HOUSEHOLD_IDS)
def test_extra_reasons_are_only_the_ones_we_have_declared(household_id, gold_households):
    house = gold_households[household_id]
    result = assess_readiness(house, PACK[household_id]["required_document_types"])
    extra = set(result.codes) - set(PACK[household_id]["expected_review_reasons"])
    assert extra == KNOWN_EXTRA_REASONS.get(household_id, set()), (
        f"{household_id}: undeclared extra reason(s) {sorted(extra)}"
    )


def test_a_ready_household_has_no_reasons_at_all(gold_households):
    for household_id in HOUSEHOLD_IDS:
        if PACK[household_id]["expected_readiness_status"] != "READY_TO_REVIEW":
            continue
        result = assess_readiness(gold_households[household_id],
                                  PACK[household_id]["required_document_types"])
        assert result.reasons == (), f"{household_id} is READY but carries reasons"


def test_the_pack_checklist_would_contradict_itself_if_presence_were_literal(gold_households):
    """Documents the contradiction our convention resolves, so it cannot be forgotten.

    HH-003 and HH-006 are missing a required employment_letter and are still expected
    READY_TO_REVIEW with an empty reason list. Any implementation that treats
    'required and missing' as automatically blocking gets these two households wrong.
    """
    contradictory = [
        household_id for household_id, row in PACK.items()
        if row["missing_document_types"] and row["expected_readiness_status"] == "READY_TO_REVIEW"
    ]
    assert sorted(contradictory) == ["HH-003", "HH-006"], (
        "the pack's self-contradiction changed; revisit "
        "constants.CONVENTIONS['REDUNDANT_REQUIRED_DOCUMENT_DOES_NOT_BLOCK_READINESS']"
    )


def test_all_six_households_agree_on_every_scored_field(gold_households):
    """The headline number, computed rather than asserted."""
    fields = 0
    mismatches = []
    for household_id in HOUSEHOLD_IDS:
        row = PACK[household_id]
        house = gold_households[household_id]
        result = assess_readiness(house, row["required_document_types"])
        checks = [
            ("annualized_income", result.income.total, row["expected_annualized_income"]),
            ("threshold", result.comparison.threshold.amount,
             float(row["frozen_60_percent_threshold"])),
            ("comparison", result.comparison.comparison, row["comparison"]),
            ("readiness_status", result.readiness_status, row["expected_readiness_status"]),
        ]
        for name, got, want in checks:
            fields += 1
            if got != want:
                mismatches.append(f"{household_id}.{name}: got {got!r}, want {want!r}")
    assert fields == 24
    assert not mismatches, "\n".join(mismatches)
