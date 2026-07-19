"""Checklist items and the ItemState enum, including the two states that carry meaning."""

from __future__ import annotations

import pytest

from logic.conftest import make_document, make_household
from logic.constants import ITEM_STATES
from logic.checklist import ChecklistItem, evaluate_checklist, evaluate_item, item_id_for


def _by_id(items):
    return {item.item_id: item for item in items}


def test_the_enum_is_exactly_the_contract_enum():
    assert ITEM_STATES == ("present", "missing", "expired", "undatable", "unreadable")


def test_expiring_soon_is_not_constructible():
    """It was removed from the contract because the pack defines no 'soon'."""
    assert "expiring_soon" not in ITEM_STATES
    with pytest.raises(ValueError, match="not an ItemState"):
        ChecklistItem("CHK-X", "X", "CH-READINESS-001", "expiring_soon", (), "", None)


def test_required_because_rule_id_must_be_a_real_pack_rule():
    with pytest.raises(ValueError, match="not a pack rule id"):
        ChecklistItem("CHK-X", "X", "CH-DOC-STUBS", "present", (), "", None)


def test_present_current_document():
    house = make_household(
        "HH-960",
        make_document("HH-960-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
    )
    item = evaluate_item(house, "pay_stub")
    assert item.state == "present"
    assert item.satisfied_by == ("HH-960-D01",)
    assert item.action_for_renter is None


def test_missing_document():
    house = make_household("HH-961", make_document("HH-961-D01", "application_summary",
                                                   household_size=1,
                                                   application_date="2026-07-10"))
    item = evaluate_item(house, "pay_stub")
    assert item.state == "missing"
    assert item.satisfied_by == ()
    assert item.action_for_renter
    assert item.blocking


def test_expired_document():
    house = make_household(
        "HH-962",
        make_document("HH-962-D01", "employment_letter", document_date="2026-04-14",
                      weekly_hours=34, hourly_rate=26.0),
    )
    item = evaluate_item(house, "employment_letter")
    assert item.state == "expired"
    assert "2026-05-19" in item.detail
    assert item.blocking


def test_undatable_is_used_for_month_precision_not_unreadable():
    """We read HH-004's gig statement fine. It just has no day. Say that, precisely."""
    house = make_household(
        "HH-963",
        make_document("HH-963-D01", "gig_statement", statement_month="2026-06",
                      gross_receipts=1200, platform_fees=120.0),
    )
    item = evaluate_item(house, "gig_statement")
    assert item.state == "undatable"
    assert item.state != "unreadable"
    assert "without inventing a day" in item.detail


def test_unreadable_document():
    house = make_household(
        "HH-964",
        make_document("HH-964-D01", "pay_stub", gross_pay=None, pay_date=None,
                      pay_frequency=None),
    )
    item = evaluate_item(house, "pay_stub")
    assert item.state == "unreadable"


def test_worst_state_wins_across_several_documents_of_one_type():
    house = make_household(
        "HH-965",
        make_document("HH-965-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
        make_document("HH-965-D02", "pay_stub", pay_date="2026-01-05", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
    )
    assert evaluate_item(house, "pay_stub").state == "expired"


def test_redundant_employment_letter_is_missing_but_not_blocking():
    """The pack's HH-003 / HH-006 shape: missing letter, still READY_TO_REVIEW."""
    house = make_household(
        "HH-966",
        make_document("HH-966-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="biweekly",
                      regular_hours=60, hourly_rate=19.25, gross_pay=1155.0),
        make_document("HH-966-D02", "pay_stub", pay_date="2026-06-20", pay_frequency="biweekly",
                      regular_hours=60, hourly_rate=19.25, gross_pay=1155.0),
    )
    item = evaluate_item(house, "employment_letter")
    assert item.state == "missing", "it IS missing and we say so"
    assert item.substituted
    assert not item.blocking, "but two agreeing stubs already document the wage source"
    assert item.action_for_renter, "the renter is still told how to supply it"


def test_letter_is_not_substitutable_when_the_stubs_disagree():
    house = make_household(
        "HH-967",
        make_document("HH-967-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=1395.0),
        make_document("HH-967-D02", "pay_stub", pay_date="2026-06-20", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
    )
    item = evaluate_item(house, "employment_letter")
    assert not item.substituted
    assert item.blocking


def test_a_single_stub_does_not_substitute_for_the_letter():
    house = make_household(
        "HH-968",
        make_document("HH-968-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
    )
    assert not evaluate_item(house, "employment_letter").substituted


def test_self_reported_income_has_no_substitute():
    house = make_household(
        "HH-969",
        make_document("HH-969-D01", "gig_statement", statement_month="2026-06",
                      gross_receipts=1200, platform_fees=120.0),
    )
    item = evaluate_item(house, "gig_income_corroboration")
    assert item.state == "missing"
    assert not item.substituted, "a gig statement cannot corroborate itself"
    assert item.blocking


def test_extra_present_documents_appear_as_non_required_items():
    house = make_household(
        "HH-970",
        make_document("HH-970-D01", "application_summary", household_size=4,
                      application_date="2026-07-10"),
        make_document("HH-970-D02", "gig_statement", statement_month="2026-06",
                      gross_receipts=1200, platform_fees=120.0),
    )
    items = _by_id(evaluate_checklist(house, ("application_summary", "gig_income_corroboration")))
    assert item_id_for("gig_statement") in items
    assert items[item_id_for("gig_statement")].required is False
    assert items[item_id_for("gig_statement")].state == "undatable"


def test_checklist_item_dict_matches_the_contract_keys():
    house = make_household("HH-971", make_document("HH-971-D01", "application_summary",
                                                   household_size=1,
                                                   application_date="2026-07-10"))
    payload = evaluate_item(house, "application_summary").to_dict()
    assert set(payload) == {"item_id", "label", "required_because_rule_id", "state",
                            "satisfied_by", "detail", "action_for_renter"}


def test_every_item_state_is_reachable():
    """A state nothing can produce is a state that lies about the system's vocabulary."""
    reached = set()
    house_present = make_household("HH-972", make_document(
        "HH-972-D01", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
        regular_hours=40, hourly_rate=24.0, gross_pay=960.0))
    reached.add(evaluate_item(house_present, "pay_stub").state)
    reached.add(evaluate_item(house_present, "benefit_letter").state)
    house_expired = make_household("HH-973", make_document(
        "HH-973-D01", "employment_letter", document_date="2026-01-01", weekly_hours=40,
        hourly_rate=24.0))
    reached.add(evaluate_item(house_expired, "employment_letter").state)
    house_undatable = make_household("HH-974", make_document(
        "HH-974-D01", "gig_statement", statement_month="2026-06", gross_receipts=1200))
    reached.add(evaluate_item(house_undatable, "gig_statement").state)
    house_unreadable = make_household("HH-975", make_document(
        "HH-975-D01", "pay_stub", gross_pay=None, pay_date=None))
    reached.add(evaluate_item(house_unreadable, "pay_stub").state)
    assert reached == set(ITEM_STATES)
