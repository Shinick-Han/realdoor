"""What the engine does with a value a *person* typed, and whether it says so.

The defect these tests lock down was found live, during API integration, not by the
pack -- the pack has no corrected document, so nothing here could have been caught by
running the six households.

    HH-001 ships two pay stubs, D02 and D03, both 2,166.00 = 76h * $28.50. A renter
    corrects D02's gross_pay to 2,500.00. 2,500.00 no longer equals 76 * 28.50, so the
    reconciliation rule (constants.CONVENTIONS['RECURRING_BASE_IS_THE_RECONCILING_STUB'])
    drops D02 and falls back to D03. Annualized income stays 56,316.00.

The arithmetic is right and stays right -- these tests assert that it does not move. What
was wrong was that the report named neither the document that had been set aside nor the
fact that a human had typed the number in it. The renter saw a total that refused to
budge and no sentence anywhere explaining why.

Three cases, because the silence has three shapes:

    dropped   a correction that is NOT used         -> abstention AND review reason
    adopted   a correction that IS used             -> abstention only
    blocked   a correction that leaves nothing usable -> abstention, income None
"""

from __future__ import annotations

import copy
import json

import pytest

from logic.household import (
    default_gold_path,
    households_from_views,
    required_document_types,
)
from logic.income import derive_wage_source
from logic.readiness import NEEDS_REVIEW, READY, assess_readiness, build_report
from logic.conftest import make_document, make_household


# =====================================================================================
# the live scenario, against the real pack household
# =====================================================================================


def _gold_views() -> list[dict]:
    return [
        json.loads(line)
        for line in default_gold_path().read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _corrected(views: list[dict], document_id: str, field: str, value) -> list[dict]:
    """Apply a correction the way ``api/store.py::apply_correction`` does."""
    views = copy.deepcopy(views)
    for view in views:
        if view["document_id"] != document_id:
            continue
        for item in view["fields"]:
            if item["field"] == field:
                item["value"] = value
                item["certainty"] = "high"
                item["evidence_kind"] = "corrected_by_renter"
                return views
    raise AssertionError(f"{document_id} has no field {field!r} to correct")


@pytest.fixture
def hh001_d02_corrected_to_2500():
    views = _corrected(_gold_views(), "HH-001-D02", "gross_pay", 2500.0)
    house = households_from_views(views)["HH-001"]
    return build_report(house, required_document_types("HH-001"), generated_at="fixed")


def test_the_untouched_household_is_ready_and_silent():
    """The control. Without a correction, none of the new entries may appear."""
    house = households_from_views(_gold_views())["HH-001"]
    report = build_report(house, required_document_types("HH-001"), generated_at="fixed")
    assert report["readiness_status"] == READY
    assert report["review_reasons"] == []
    text = json.dumps(report)
    assert "corrected" not in text.lower()


def test_the_arithmetic_does_not_move(hh001_d02_corrected_to_2500):
    """We are fixing the silence, not the selection. 2,500 still must not annualize."""
    results = [c["result"] for c in hh001_d02_corrected_to_2500["calculations"]]
    assert results[-1] == 56316.0
    assert 65000.0 not in results, "2,500 * 26 must never be annualized"


def test_the_discarded_correction_is_named_in_a_review_reason(hh001_d02_corrected_to_2500):
    codes = [r["code"] for r in hh001_d02_corrected_to_2500["review_reasons"]]
    assert "RENTER_CORRECTION_NOT_USED" in codes
    assert hh001_d02_corrected_to_2500["readiness_status"] == NEEDS_REVIEW


def test_the_message_names_both_documents_and_both_quantities(hh001_d02_corrected_to_2500):
    """The four facts a renter needs: my document, my number, its number, and what won."""
    message = next(
        r["message"] for r in hh001_d02_corrected_to_2500["review_reasons"]
        if r["code"] == "RENTER_CORRECTION_NOT_USED"
    )
    assert "HH-001-D02" in message, "the document the renter corrected"
    assert "2,500.00" in message, "the value the renter typed"
    assert "2,166.00" in message, "the value that document's own hours * rate implies"
    assert "HH-001-D03" in message, "the document used instead"


def test_the_discarded_correction_also_reaches_abstentions(hh001_d02_corrected_to_2500):
    reasons = [a["reason"] for a in hh001_d02_corrected_to_2500["abstentions"]]
    assert any("HH-001-D02" in r and "HH-001-D03" in r for r in reasons)
    assert all(
        set(a) == {"about", "reason", "what_would_resolve_it"}
        for a in hh001_d02_corrected_to_2500["abstentions"]
    ), "CONTRACTS section 7 shape must survive the new entries"


def test_the_softer_machine_level_entry_now_names_the_dropped_stub_too(
    hh001_d02_corrected_to_2500,
):
    """Even without the correction signal, the conflict entry must say what it dropped."""
    message = next(
        r["message"] for r in hh001_d02_corrected_to_2500["review_reasons"]
        if r["code"] == "PAY_STUB_TOTAL_CONFLICT"
    )
    assert "HH-001-D02" in message and "HH-001-D03" in message


def test_every_new_message_cites_a_real_pack_rule(hh001_d02_corrected_to_2500):
    from logic.constants import RULE_IDS

    for reason in hh001_d02_corrected_to_2500["review_reasons"]:
        assert reason["rule_id"] in RULE_IDS


def test_no_banned_key_appears_after_a_correction(hh001_d02_corrected_to_2500):
    banned = ("eligible", "approved", "denied", "score", "rank", "priority",
              "recommendation", "decision", "verdict")
    # The one contract key that contains a banned token on purpose: it exists to say a
    # HUMAN makes the decision, which is the opposite of the thing being banned.
    allowed = {"human_decision_notice"}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key in allowed or not any(b in key.lower() for b in banned), (
                    f"banned key {key!r}")
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(hh001_d02_corrected_to_2500)


# =====================================================================================
# machine-extracted disagreement stays softer than a human correction
# =====================================================================================


def _stub(document_id: str, gross: float, *, hours=76, rate=28.5, corrected=()):
    return make_document(
        document_id, "pay_stub", corrected=corrected, person_name="Mara North",
        pay_date="2026-06-27", pay_frequency="biweekly",
        regular_hours=hours, hourly_rate=rate, gross_pay=gross,
    )


def test_machine_disagreement_does_not_raise_the_correction_entry():
    """The grading that makes the correction entry mean something."""
    house = make_household("HH-960", _stub("HH-960-D01", 2500.0), _stub("HH-960-D02", 2166.0))
    source = derive_wage_source(house)
    triggers = {a.trigger for a in source.abstentions}
    assert "pay_stub_totals_conflict" in triggers
    assert "corrected_value_not_used" not in triggers


def test_the_same_disagreement_from_a_correction_does_raise_it():
    house = make_household(
        "HH-961",
        _stub("HH-961-D01", 2500.0, corrected=("gross_pay",)),
        _stub("HH-961-D02", 2166.0),
    )
    source = derive_wage_source(house)
    assert source.annual_amount == 56316.0
    assert "corrected_value_not_used" in {a.trigger for a in source.abstentions}


# =====================================================================================
# the symmetric case: a correction that IS used
# =====================================================================================


def test_a_correction_that_makes_a_stub_reconcile_is_surfaced_but_does_not_block():
    """HH-002's shape, resolved by the renter: 1,395 corrected down to 960.

    Without this entry the household would flip NEEDS_REVIEW -> READY_TO_REVIEW with the
    PAY_STUB_TOTAL_CONFLICT reason simply gone -- the same silence, in the direction that
    happens to favour the renter. It is still a silence.
    """
    house = make_household(
        "HH-962",
        _stub("HH-962-D01", 960.0, hours=40, rate=24.0, corrected=("gross_pay",)),
        _stub("HH-962-D02", 960.0, hours=40, rate=24.0),
        make_document("HH-962-D03", "application_summary", person_name="Mara North",
                      household_size=1, application_date="2026-07-10"),
    )
    result = assess_readiness(house, ("application_summary", "pay_stub"))
    assert result.income.total == 24960.0
    assert "corrected_value_is_the_recurring_base" in {
        a.trigger for a in result.abstentions
    }
    assert "RENTER_CORRECTION_IN_USE" not in result.codes, (
        "an adopted correction is information for a reviewer, not a gap to hold the "
        "packet open for -- blocking here would penalise the renter for correcting"
    )
    assert result.readiness_status == READY


def test_a_correction_to_hours_or_rate_counts_too():
    """The reconciliation reads three fields; a correction to any of them decides it."""
    house = make_household(
        "HH-963",
        _stub("HH-963-D01", 2166.0, hours=76, rate=28.5, corrected=("regular_hours",)),
        _stub("HH-963-D02", 2166.0),
    )
    source = derive_wage_source(house)
    assert "corrected_value_is_the_recurring_base" in {a.trigger for a in source.abstentions}


# =====================================================================================
# a correction that leaves nothing usable
# =====================================================================================


def test_a_correction_that_blocks_the_calculation_is_still_named():
    """Two stubs that each reconcile but disagree: we refuse to pick, and we say why."""
    house = make_household(
        "HH-964",
        _stub("HH-964-D01", 2500.0, hours=100, rate=25.0, corrected=("regular_hours",
                                                                     "hourly_rate")),
        _stub("HH-964-D02", 2166.0),
    )
    source = derive_wage_source(house)
    assert source.annual_amount is None
    reasons = {a.trigger: a.reason for a in source.abstentions}
    assert "corrected_value_not_used" in reasons
    assert "HH-964-D01" in reasons["corrected_value_not_used"]


# =====================================================================================
# the guarantee the pack data has to keep
# =====================================================================================


def test_no_gold_household_gains_a_correction_entry(gold_households, pack_checklists):
    """Nothing in the pack is corrected, so none of this may fire on untouched data."""
    for household_id, house in gold_households.items():
        result = assess_readiness(house, required_document_types(household_id, pack_checklists))
        triggers = {a.trigger for a in result.abstentions}
        assert "corrected_value_not_used" not in triggers, household_id
        assert "corrected_value_is_the_recurring_base" not in triggers, household_id
