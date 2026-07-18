"""Readiness: the four CH-READINESS-001 checks, each proven to fire on its own."""

from __future__ import annotations

import pytest

from logic.conftest import make_document, make_household
from logic.constants import CURRENCY_FLOOR, REFERENCE_DATE
from logic.readiness import CHECKS, NEEDS_REVIEW, READY, assess_readiness, build_report

REQUIRED = ("application_summary", "pay_stub", "employment_letter")


def _complete_household(household_id="HH-950", **overrides):
    letter_date = overrides.get("letter_date", "2026-07-06")
    stub_gross = overrides.get("stub_gross", 960.0)
    second_gross = overrides.get("second_gross", stub_gross)
    return make_household(
        household_id,
        make_document(f"{household_id}-D01", "application_summary", person_name="Ada Lane",
                      household_size=2, application_date="2026-07-10"),
        make_document(f"{household_id}-D02", "pay_stub", person_name="Ada Lane",
                      pay_date="2026-06-27", pay_frequency="weekly", regular_hours=40,
                      hourly_rate=24.0, gross_pay=stub_gross),
        make_document(f"{household_id}-D03", "pay_stub", person_name="Ada Lane",
                      pay_date="2026-06-20", pay_frequency="weekly", regular_hours=40,
                      hourly_rate=24.0, gross_pay=second_gross),
        make_document(f"{household_id}-D04", "employment_letter", person_name="Ada Lane",
                      document_date=letter_date, weekly_hours=40, hourly_rate=24.0),
    )


def test_a_complete_current_consistent_traceable_file_is_ready():
    result = assess_readiness(_complete_household(), REQUIRED)
    assert result.readiness_status == READY
    assert result.reasons == ()


def test_readiness_is_only_ever_one_of_the_two_frozen_values():
    result = assess_readiness(_complete_household(), REQUIRED)
    assert result.readiness_status in (READY, NEEDS_REVIEW)


# =====================================================================================
# check 1 of 4 -- present
# =====================================================================================


def test_missing_required_document_fires_the_presence_check():
    house = make_household(
        "HH-951",
        make_document("HH-951-D01", "application_summary", household_size=2,
                      application_date="2026-07-10"),
    )
    result = assess_readiness(house, REQUIRED)
    assert result.readiness_status == NEEDS_REVIEW
    assert result.reasons_for("present")
    assert any("pay stub" in r.message.lower() for r in result.reasons_for("present"))


def test_missing_document_reason_names_the_document():
    house = make_household(
        "HH-952",
        make_document("HH-952-D01", "application_summary", household_size=2,
                      application_date="2026-07-10"),
        make_document("HH-952-D02", "pay_stub", pay_date="2026-06-27", pay_frequency="weekly",
                      regular_hours=40, hourly_rate=24.0, gross_pay=960.0),
    )
    result = assess_readiness(house, REQUIRED)
    messages = " ".join(r.message for r in result.reasons)
    assert "Employment verification letter" in messages


def test_an_unreadable_document_fires_the_presence_check():
    """Regression: 'unreadable' blocked the checklist item but emitted no reason, so a
    scan with no text layer fell through to READY_TO_REVIEW. Silence is the worst
    possible behaviour here -- the file LOOKS complete and nobody is told otherwise.
    """
    house = make_household(
        "HH-958",
        make_document("HH-958-D01", "application_summary", person_name="Ada Lane",
                      household_size=2, application_date="2026-07-10"),
        make_document("HH-958-D02", "pay_stub", person_name=None, pay_date=None,
                      pay_frequency=None, regular_hours=None, hourly_rate=None,
                      gross_pay=None),
    )
    result = assess_readiness(house, ("application_summary", "pay_stub"))
    assert result.readiness_status == NEEDS_REVIEW
    assert result.reasons_for("present"), "an unreadable document must produce a reason"
    assert "DOCUMENT_UNREADABLE" in result.codes


def test_an_unreadable_copy_alongside_a_readable_one_still_raises():
    """Two stubs, one a scan. The readable one gives us the number; the scan is still a
    page nobody has checked, so the packet is not silently declared ready."""
    house = make_household(
        "HH-959",
        make_document("HH-959-D01", "application_summary", person_name="Ada Lane",
                      household_size=2, application_date="2026-07-10"),
        make_document("HH-959-D02", "pay_stub", person_name=None, pay_date=None,
                      pay_frequency=None, gross_pay=None),
        make_document("HH-959-D03", "pay_stub", person_name="Ada Lane",
                      pay_date="2026-06-20", pay_frequency="weekly", regular_hours=40,
                      hourly_rate=24.0, gross_pay=960.0),
    )
    result = assess_readiness(house, ("application_summary", "pay_stub"))
    assert result.income.total == 49920.0, "the readable stub still yields the number"
    assert result.readiness_status == NEEDS_REVIEW
    assert "DOCUMENT_UNREADABLE" in result.codes


# =====================================================================================
# check 2 of 4 -- current
# =====================================================================================


def test_expired_document_fires_the_currency_check():
    result = assess_readiness(_complete_household(letter_date="2026-04-14"), REQUIRED)
    assert result.readiness_status == NEEDS_REVIEW
    assert result.reasons_for("current")
    assert "EMPLOYMENT_LETTER_EXPIRED" in result.codes


def test_the_currency_boundary_is_the_frozen_one_not_120_days():
    """60 days before 2026-07-18 is 2026-05-19. A 120-day window would pass this file."""
    assert CURRENCY_FLOOR.isoformat() == "2026-05-19"
    assert REFERENCE_DATE.isoformat() == "2026-07-18"
    on_the_line = assess_readiness(_complete_household(letter_date="2026-05-19"), REQUIRED)
    assert on_the_line.readiness_status == READY
    one_day_early = assess_readiness(_complete_household(letter_date="2026-05-18"), REQUIRED)
    assert one_day_early.readiness_status == NEEDS_REVIEW
    # A 120-day window would have accepted 2026-03-20; the frozen one must not.
    assert assess_readiness(_complete_household(letter_date="2026-03-20"),
                            REQUIRED).readiness_status == NEEDS_REVIEW


def test_month_precision_date_fires_the_currency_check_as_undatable():
    house = make_household(
        "HH-953",
        make_document("HH-953-D01", "application_summary", household_size=4,
                      application_date="2026-07-10"),
        make_document("HH-953-D02", "gig_statement", statement_month="2026-06",
                      gross_receipts=1200, platform_fees=120.0),
    )
    result = assess_readiness(house, ("application_summary", "gig_statement"))
    assert "DOCUMENT_UNDATABLE" in result.codes
    assert result.reasons_for("current")


# =====================================================================================
# check 3 of 4 -- internally consistent
# =====================================================================================


def test_conflicting_pay_stub_totals_fire_the_consistency_check():
    result = assess_readiness(_complete_household(stub_gross=1395.0, second_gross=960.0), REQUIRED)
    assert result.readiness_status == NEEDS_REVIEW
    assert result.reasons_for("consistent")
    assert "PAY_STUB_TOTAL_CONFLICT" in result.codes


def test_documents_naming_different_people_fire_the_consistency_check():
    house = make_household(
        "HH-954",
        make_document("HH-954-D01", "application_summary", person_name="Ada Lane",
                      household_size=2, application_date="2026-07-10"),
        make_document("HH-954-D02", "pay_stub", person_name="Someone Else",
                      pay_date="2026-06-27", pay_frequency="weekly", regular_hours=40,
                      hourly_rate=24.0, gross_pay=960.0),
    )
    result = assess_readiness(house, ("application_summary", "pay_stub"))
    assert "PERSON_NAME_MISMATCH" in result.codes


def test_uncorroborated_self_reported_income_fires_a_reason_but_still_computes():
    house = make_household(
        "HH-955",
        make_document("HH-955-D01", "application_summary", household_size=4,
                      application_date="2026-07-10"),
        make_document("HH-955-D02", "gig_statement", statement_month="2026-06",
                      gross_receipts=1200, platform_fees=120.0),
    )
    result = assess_readiness(house, ("application_summary", "gig_income_corroboration"))
    assert result.income.total == 14400.0, "the number is still produced"
    assert "GIG_INCOME_UNCORROBORATED" in result.codes, "and the gap is still named"


# =====================================================================================
# check 4 of 4 -- traceable
# =====================================================================================


def test_untraceable_value_fires_the_traceability_check():
    house = make_household(
        "HH-956",
        make_document("HH-956-D01", "application_summary", household_size=2,
                      application_date="2026-07-10"),
        make_document("HH-956-D02", "pay_stub", traceable=False, pay_date="2026-06-27",
                      pay_frequency="weekly", regular_hours=40, hourly_rate=24.0,
                      gross_pay=960.0),
    )
    result = assess_readiness(house, ("application_summary", "pay_stub"))
    assert result.readiness_status == NEEDS_REVIEW
    assert result.reasons_for("traceable")


def test_all_four_checks_can_fire_at_once_and_each_keeps_its_own_reason():
    house = make_household(
        "HH-957",
        make_document("HH-957-D01", "application_summary", person_name="Ada Lane",
                      household_size=2, application_date="2026-07-10"),
        make_document("HH-957-D02", "pay_stub", person_name="Ada Lane", pay_date="2026-06-27",
                      pay_frequency="weekly", regular_hours=40, hourly_rate=24.0,
                      gross_pay=1395.0),
        make_document("HH-957-D03", "pay_stub", person_name="Ada Lane", pay_date="2026-06-20",
                      pay_frequency="weekly", regular_hours=40, hourly_rate=24.0,
                      gross_pay=960.0),
        make_document("HH-957-D04", "benefit_letter", traceable=False,
                      document_date="2026-01-01", monthly_benefit=850,
                      benefit_frequency="monthly"),
    )
    result = assess_readiness(house, REQUIRED + ("benefit_letter",))
    fired = {r.check for r in result.reasons}
    assert fired == set(CHECKS), f"expected all four checks to fire, got {sorted(fired)}"
    for check in CHECKS:
        assert all(r.message for r in result.reasons_for(check)), "every reason needs a string"


def test_every_reason_cites_a_pack_rule():
    from logic.constants import RULE_IDS

    result = assess_readiness(_complete_household(letter_date="2026-01-01"), REQUIRED)
    assert result.reasons
    for reason in result.reasons:
        assert reason.rule_id in RULE_IDS


# =====================================================================================
# the report
# =====================================================================================


def test_report_has_the_contract_shape():
    report = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")
    for key in ("household_id", "generated_at", "ruleset_version", "readiness_status",
                "documents", "calculations", "checklist", "citations", "abstentions",
                "human_decision_notice", "engine_version"):
        assert key in report


def test_report_never_contains_a_judgement_key():
    banned = {"eligible", "ineligible", "approved", "denied", "qualified", "score", "rank",
              "priority", "recommendation"}
    report = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert not (set(str(key).lower().split("_")) & banned), f"banned key {key!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(report)


def test_report_always_carries_the_human_decision_notice():
    report = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")
    assert "not an eligibility determination" in report["human_decision_notice"]
    assert "human" in report["human_decision_notice"].lower() or \
           "professional" in report["human_decision_notice"].lower()


def test_report_citations_are_all_real_pack_rules():
    from logic.constants import RULE_IDS

    report = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")
    assert report["citations"]
    for citation in report["citations"]:
        assert citation["rule_id"] in RULE_IDS
        assert citation["verified_against_source"] is None, "we have not checked live sources"


def test_report_is_deterministic():
    first = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")
    second = build_report(_complete_household(), REQUIRED, generated_at="1970-01-01T00:00:00Z")
    assert first == second


def test_abstention_entries_have_exactly_the_three_contract_keys():
    house = _complete_household(letter_date="2026-01-01")
    report = build_report(house, REQUIRED, generated_at="1970-01-01T00:00:00Z")
    assert report["abstentions"]
    for entry in report["abstentions"]:
        assert set(entry) == {"about", "reason", "what_would_resolve_it"}
        assert all(entry.values()), "an abstention with an empty field explains nothing"
