"""Income annualization, including every abstention branch."""

from __future__ import annotations

import pytest

from logic.abstain import BLOCKING
from logic.conftest import make_document, make_household
from logic.income import (
    annualize,
    annualize_household,
    derive_benefit_source,
    derive_gig_source,
    derive_wage_source,
)


# =====================================================================================
# the primitive
# =====================================================================================


@pytest.mark.parametrize(
    "amount,frequency,expected",
    [
        (1500.0, "biweekly", 39000.0),
        (2166.0, "biweekly", 56316.0),
        (960.0, "weekly", 49920.0),
        (850.0, "monthly", 10200.0),
        (1200.0, "monthly", 14400.0),
        (1000.0, "semimonthly", 24000.0),
        (50000.0, "annual", 50000.0),
        (0.0, "weekly", 0.0),
    ],
)
def test_annualize_known_values(amount, frequency, expected):
    assert annualize(amount, frequency) == expected


def test_annualize_rejects_unknown_frequency():
    with pytest.raises(ValueError, match="Unsupported frequency"):
        annualize(100.0, "fortnightly")


def test_annualize_rejects_negative_amount():
    with pytest.raises(ValueError, match="non-negative"):
        annualize(-1.0, "weekly")


def test_annualize_rounds_to_cents():
    """Rounding is round-half-even on a binary float, exactly as the organizer's is.

    1000.005 is not exactly representable and rounds DOWN to 1000.0 here. That is
    surprising, and it is copied deliberately: the organizer's annualize() does the same
    thing, and agreeing with them matters more than being independently tidy.
    """
    assert annualize(100.125, "monthly") == 1201.5
    assert annualize(1000.005, "annual") == 1000.0
    assert annualize(1.005, "weekly") == 52.26


# =====================================================================================
# wages
# =====================================================================================


def _stub(doc_id, gross, hours=40, rate=24.0, frequency="weekly", **extra):
    return make_document(doc_id, "pay_stub", gross_pay=gross, regular_hours=hours,
                         hourly_rate=rate, pay_frequency=frequency, **extra)


def test_two_agreeing_stubs_annualize_once_not_twice():
    house = make_household("HH-900", _stub("HH-900-D01", 960.0), _stub("HH-900-D02", 960.0))
    source = derive_wage_source(house)
    assert source.annual_amount == 49920.0
    assert not source.abstentions


def test_employment_letter_corroborates_and_does_not_add():
    """The single most expensive possible bug in this layer: double-counting a job."""
    house = make_household(
        "HH-901",
        _stub("HH-901-D01", 960.0),
        _stub("HH-901-D02", 960.0),
        make_document("HH-901-D03", "employment_letter", document_date="2026-07-06",
                      weekly_hours=40, hourly_rate=24.0),
    )
    source = derive_wage_source(house)
    assert source.annual_amount == 49920.0, "letter must corroborate, never sum"


def test_letter_contradicting_stubs_is_flagged_not_averaged():
    house = make_household(
        "HH-902",
        _stub("HH-902-D01", 960.0),
        make_document("HH-902-D02", "employment_letter", document_date="2026-07-06",
                      weekly_hours=30, hourly_rate=24.0),
    )
    source = derive_wage_source(house)
    assert source.annual_amount == 49920.0
    assert any(a.trigger == "pay_stub_totals_conflict" for a in source.abstentions)


def test_conflicting_stubs_use_the_reconciling_one():
    """HH-002's shape: 1,395 does not reconcile with 40h * $24; 960 does."""
    house = make_household(
        "HH-903",
        _stub("HH-903-D01", 1395.0),
        _stub("HH-903-D02", 960.0),
    )
    source = derive_wage_source(house)
    assert source.annual_amount == 49920.0
    assert source.annual_amount != 72540.0, "must not annualize the overtime week"
    assert any(a.trigger == "pay_stub_totals_conflict" for a in source.abstentions)


def test_conflicting_stubs_with_no_reconciling_one_abstains():
    house = make_household(
        "HH-904",
        _stub("HH-904-D01", 1395.0, hours=None, rate=None),
        _stub("HH-904-D02", 1500.0, hours=None, rate=None),
    )
    source = derive_wage_source(house)
    assert source.annual_amount is None
    assert any(a.trigger == "pay_stub_totals_irreconcilable" for a in source.abstentions)
    assert all(a.grade == BLOCKING for a in source.abstentions)


def test_missing_pay_frequency_abstains_rather_than_inferring_from_dates():
    house = make_household(
        "HH-905",
        make_document("HH-905-D01", "pay_stub", gross_pay=960.0, regular_hours=40,
                      hourly_rate=24.0, pay_date="2026-06-27"),
    )
    source = derive_wage_source(house)
    assert source.annual_amount is None
    assert source.abstentions[0].trigger == "pay_frequency_not_stated"


def test_unrecognized_frequency_abstains():
    house = make_household("HH-906", _stub("HH-906-D01", 960.0, frequency="fortnightly"))
    source = derive_wage_source(house)
    assert source.annual_amount is None
    assert source.abstentions[0].trigger == "pay_frequency_not_recognized"


def test_disagreeing_frequencies_across_stubs_abstain():
    house = make_household(
        "HH-907",
        _stub("HH-907-D01", 960.0, frequency="weekly"),
        _stub("HH-907-D02", 960.0, frequency="biweekly"),
    )
    assert derive_wage_source(house).annual_amount is None


def test_untraceable_amount_abstains():
    house = make_household(
        "HH-908",
        make_document("HH-908-D01", "pay_stub", traceable=False, gross_pay=960.0,
                      regular_hours=40, hourly_rate=24.0, pay_frequency="weekly"),
    )
    source = derive_wage_source(house)
    assert source.annual_amount is None
    assert source.abstentions[0].trigger == "income_amount_not_traceable"


def test_employment_letter_alone_is_a_documented_wage():
    house = make_household(
        "HH-909",
        make_document("HH-909-D01", "employment_letter", document_date="2026-07-06",
                      weekly_hours=40, hourly_rate=24.0),
    )
    assert derive_wage_source(house).annual_amount == 49920.0


def test_no_wage_documents_yields_no_wage_source():
    house = make_household("HH-910", make_document("HH-910-D01", "application_summary",
                                                   household_size=2))
    assert derive_wage_source(house) is None


# =====================================================================================
# benefits
# =====================================================================================


def test_benefit_letter_annualizes_at_stated_frequency():
    house = make_household(
        "HH-911",
        make_document("HH-911-D01", "benefit_letter", document_date="2026-06-13",
                      monthly_benefit=850, benefit_frequency="monthly"),
    )
    assert derive_benefit_source(house).annual_amount == 10200.0


def test_benefit_letter_without_stated_frequency_abstains():
    house = make_household(
        "HH-912",
        make_document("HH-912-D01", "benefit_letter", document_date="2026-06-13",
                      monthly_benefit=850),
    )
    source = derive_benefit_source(house)
    assert source.annual_amount is None
    assert source.abstentions[0].trigger == "pay_frequency_not_stated"


# =====================================================================================
# gig
# =====================================================================================


def _gig(doc_id="HH-913-D01", receipts=1200, fees=120.0, month="2026-06"):
    return make_document(doc_id, "gig_statement", statement_month=month,
                         gross_receipts=receipts, platform_fees=fees)


def test_gig_annualizes_gross_not_net():
    house = make_household("HH-913", _gig())
    source = derive_gig_source(house)
    assert source.annual_amount == 14400.0
    assert source.annual_amount != 12960.0, "platform fees must not be deducted from gross"


def test_gig_without_corroboration_is_advisory_not_blocking():
    """The pack expects the number AND the gap. Both, not one or the other."""
    house = make_household("HH-914", _gig("HH-914-D01"))
    source = derive_gig_source(house)
    assert source.annual_amount == 14400.0
    assert source.abstentions[0].trigger == "self_reported_income_uncorroborated"
    assert not source.abstentions[0].blocking


def test_gig_with_corroboration_raises_nothing():
    house = make_household(
        "HH-915",
        _gig("HH-915-D01"),
        make_document("HH-915-D02", "form_1099", document_date="2026-06-30", gross_receipts=1200),
    )
    assert not derive_gig_source(house).abstentions


def test_gig_without_a_stated_period_abstains():
    house = make_household(
        "HH-916",
        make_document("HH-916-D01", "gig_statement", gross_receipts=1200),
    )
    assert derive_gig_source(house).annual_amount is None


# =====================================================================================
# household totals
# =====================================================================================


def test_independent_sources_sum():
    house = make_household(
        "HH-917",
        _stub("HH-917-D01", 1155.0, hours=60, rate=19.25, frequency="biweekly"),
        _stub("HH-917-D02", 1155.0, hours=60, rate=19.25, frequency="biweekly"),
        make_document("HH-917-D03", "benefit_letter", document_date="2026-06-13",
                      monthly_benefit=850, benefit_frequency="monthly"),
    )
    result = annualize_household(house)
    assert result.total == 40230.0
    assert {s.name for s in result.counted_sources} == {"wage", "benefit"}


def test_no_documented_income_gives_none_not_zero():
    """0.0 would read as 'this renter has no income'. It means 'we do not know'."""
    house = make_household("HH-918", make_document("HH-918-D01", "application_summary",
                                                   household_size=3))
    result = annualize_household(house)
    assert result.total is None
    assert result.total != 0.0
    assert result.abstentions


def test_blocked_source_does_not_silently_vanish():
    house = make_household(
        "HH-919",
        make_document("HH-919-D01", "pay_stub", gross_pay=960.0, regular_hours=40,
                      hourly_rate=24.0),  # no frequency
        make_document("HH-919-D02", "benefit_letter", document_date="2026-06-13",
                      monthly_benefit=850, benefit_frequency="monthly"),
    )
    result = annualize_household(house)
    assert result.total == 10200.0
    assert any(a.trigger == "pay_frequency_not_stated" for a in result.abstentions)


def test_every_input_names_its_document():
    house = make_household("HH-920", _stub("HH-920-D01", 960.0))
    calculation = annualize_household(house).to_calculation()
    assert calculation["inputs"]
    for item in calculation["inputs"]:
        assert item["from_document"], "an input with no document is an uncited number"
