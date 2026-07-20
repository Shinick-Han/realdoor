# -*- coding: utf-8 -*-
"""The period license on period-dependent rate synonyms (`REALDOOR_RATE_PERIOD_LICENSE`).

`RATE OF PAY` names an hourly rate on one form and a monthly salary on the next, and the
filled-forms corpus measured the difference as this project's first wrong value:
`orangeusd_sample_paystub_filled.pdf` prints `Rate of Pay` over a monthly certificated
4,812.00 and the synonym read it as `hourly_rate`. The license in `core.extract` lets the
binding stand only when the page itself settles the period -- a printed
`value x hours = amount` identity closing cent-exact on the value's own page.

As everywhere in this codebase, the interesting assertions are the refusals: the salaried
stub, the degenerate `x 1` product, the beyond-a-month hours factor and the circle-one
menu must all keep producing abstentions, while the one page that proves its rate
(`up_016`: 19.25 x 72 = 1386.00, all three printed) must keep its reading byte-for-byte.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex

ROOT = Path(__file__).resolve().parent.parent
FILLED = ROOT / "testdata" / "filled"
UPLOADS = ROOT / "testdata" / "uploads"

ORANGEUSD = FILLED / "orangeusd_sample_paystub_filled.pdf"
SEATTLE = FILLED / "seattle_housing_employment_verification_filled.pdf"
UP_016 = UPLOADS / "up_016_pay_stub_wording_total_earnings.pdf"
UP_018 = UPLOADS / "up_018_employment_letter_wording_company.pdf"


def _fields(pdf: Path, document_type: str) -> dict:
    view = ex.extract_document(pdf, document_type=document_type)
    return {f["field"]: f for f in view["fields"]}


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_RATE_PERIOD_LICENSE", raising=False)
    assert ex._rate_period_license_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_RATE_PERIOD_LICENSE", value)
    assert ex._rate_period_license_enabled() is (value.strip() != "0")


def test_flag_off_restores_the_pre_license_conduct(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the flag at `0` the intercept never runs and the old wrong value returns --
    that is the G5 contract, pinned on the exact document that motivated the license."""
    monkeypatch.setenv("REALDOOR_RATE_PERIOD_LICENSE", "0")
    got = _fields(ORANGEUSD, "pay_stub")["hourly_rate"]
    assert got["certainty"] != "abstain"
    assert got["value"] == pytest.approx(4812.0)


# ─────────────────────────────────────────── the mechanism, on hand-built geometry
#
# A minimal stacked form: the label `RATE OF PAY` (recognised through the synonym
# table, pass 2) with its value 14pt beneath, inside `VALUE_Y_WINDOW` and x-aligned.
# Extra tokens are placed far away on the same page so they join the closure search
# without becoming value candidates.


def _w(text: str, x0: float, baseline: float, size: float = 8.0,
       bold: bool = False, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x0 + 4.0 * max(len(text), 1), baseline=baseline,
                   glyph_bottom=baseline, glyph_top=baseline + size, size=size,
                   bold=bold, page=page)


def _page(value_text: str, far_tokens: list[str]) -> list[ex.Word]:
    words = [
        # gaps of 2pt, well under the 0.6 x size run-split threshold, so the three
        # words read as one label run
        _w("RATE", 50.0, 700.0), _w("OF", 68.0, 700.0), _w("PAY", 78.0, 700.0),
        _w(value_text, 50.0, 686.0),
    ]
    words += [_w(t, 300.0 + 90.0 * i, 500.0) for i, t in enumerate(far_tokens)]
    return words


def _hourly_rate(words: list[ex.Word]) -> dict:
    found, _ = ex.extract_fields_from_page(
        words, "pay_stub", ex.LineBoxConvention(),
        field_mapper=ex.deterministic_mapper, fallback_mapper=ex.synonym_mapper,
    )
    return found["hourly_rate"]


@pytest.fixture()
def isolated(monkeypatch: pytest.MonkeyPatch):
    """The license under test, with the arithmetic chain held fixed (same convention as
    `core/test_columns.py`): these tests measure what the *license* does."""
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    monkeypatch.delenv("REALDOOR_RATE_PERIOD_LICENSE", raising=False)
    yield


def test_a_rate_no_identity_closes_is_refused(isolated) -> None:
    """The salaried-stub shape: a big figure under RATE OF PAY, other numbers on the
    page, nothing multiplying to anything. The binding becomes an abstention that says
    why."""
    got = _hourly_rate(_page("4,812.00", ["21.00", "4,812.00", "553.38"]))
    assert got["certainty"] == "abstain"
    assert got["value"] is None
    assert "unstated period" in got["notes"]


def test_a_rate_that_closes_the_product_is_licensed(isolated) -> None:
    """The up_016 shape: rate x printed hours = printed amount, cent-exact. The emission
    is the unchanged synonym-path field -- low certainty, no license note added."""
    got = _hourly_rate(_page("19.25", ["72", "1386.00"]))
    assert got["certainty"] == "low"
    assert got["value"] == pytest.approx(19.25)
    assert "unstated period" not in (got["notes"] or "")


def test_the_multiplicative_identity_licenses_nothing(isolated) -> None:
    """A salaried stub printing `rate = amount, hours 1` would close v x 1 = v. The
    it-004 precedent holds: x 1 testifies to nothing, and the binding stays refused."""
    got = _hourly_rate(_page("4,812.00", ["1", "4,812.00"]))
    assert got["certainty"] == "abstain"


def test_an_hours_factor_beyond_a_month_licenses_nothing(isolated) -> None:
    """2.00 x 800 = 1600.00 closes arithmetically, but 800 hours exceed the physical
    ceiling of one calendar month, so the pair is no hours-and-amount at all."""
    got = _hourly_rate(_page("2.00", ["800", "1600.00"]))
    assert got["certainty"] == "abstain"


def test_a_printed_menu_of_periods_licenses_nothing(isolated) -> None:
    """The seattle finding, pinned: the text layer of a circle-one menu prints every
    period word equally (the circling is ink), so period words near the wage are not
    evidence. No marker license exists -- with the menu printed and no closing identity
    the binding is refused exactly as without it."""
    words = _page("4,812.00", ["21.00"])
    words += [_w(t, 150.0 + 60.0 * i, 686.0) for i, t in enumerate(
        ["(circle", "one)", "hourly", "weekly", "monthly", "yearly"])]
    got = _hourly_rate(words)
    assert got["certainty"] == "abstain"


def test_the_value_run_cannot_corroborate_itself(isolated) -> None:
    """With no other tokens on the page, the value's own words must not be recruited as
    the hours or the amount of a closing pair."""
    got = _hourly_rate(_page("4,812.00", []))
    assert got["certainty"] == "abstain"


# ──────────────────────────────────────────────── the real documents, end to end


def test_orangeusd_filled_the_monthly_rate_stays_unread() -> None:
    """The corpus's first measured wrong value, gone the right way: hourly_rate is in
    the document's `expect_absent`, so the correct terminal state is an abstention --
    with the refusal said out loud -- while every neighbouring reading stays put."""
    fields = _fields(ORANGEUSD, "pay_stub")
    rate = fields["hourly_rate"]
    assert rate["certainty"] == "abstain"
    assert "unstated period" in rate["notes"]
    assert fields["gross_pay"]["value"] == pytest.approx(4812.0)
    assert fields["net_pay"]["value"] == pytest.approx(4166.12)
    assert fields["person_name"]["value"] == "DELGADO, RUTH A"


def test_orangeusd_filled_the_hours_units_twin_stays_out() -> None:
    """`Hours/Units` 21.00 is working DAYS on this stub -- the same context-dependence
    one label over. regular_hours must stay abstained, and 21.00 must be the value of
    no field at all."""
    fields = _fields(ORANGEUSD, "pay_stub")
    assert fields["regular_hours"]["certainty"] == "abstain"
    assert all(
        f["value"] != pytest.approx(21.0)
        for f in fields.values() if isinstance(f["value"], (int, float))
    )


def test_hours_units_is_in_no_vocabulary() -> None:
    """The must-stay-out pin, structural: admitting the twin is how this wrong value
    would come back wearing a different label."""
    for table in (ex.LABEL_MAP, ex.LABEL_SYNONYMS):
        for mapping in table.values():
            assert "HOURS/UNITS" not in {ex.normalize_label(k) for k in mapping}


def test_up_016_keeps_every_reading_through_the_closure() -> None:
    """The one corpus document whose correct field rides RATE OF PAY on a pay stub:
    19.25 x 72 = 1386.00 is printed whole, the binding is licensed, and all nine
    intended fields keep their values."""
    fields = _fields(UP_016, "pay_stub")
    rate = fields["hourly_rate"]
    assert rate["value"] == pytest.approx(19.25)
    assert rate["certainty"] == "low"
    assert "unstated period" not in (rate["notes"] or "")
    for name, expected in {
        "person_name": "John Doe", "pay_date": "2026-07-03",
        "pay_period_start": "2026-06-15", "pay_period_end": "2026-06-28",
        "pay_frequency": "biweekly", "regular_hours": 72,
        "gross_pay": 1386.00, "net_pay": 1121.66,
    }.items():
        got = fields[name]["value"]
        assert got == (pytest.approx(expected) if isinstance(expected, (int, float))
                       else expected), name


def test_the_employment_letter_table_is_out_of_scope() -> None:
    """`up_018` reads hourly_rate through the employment_letter RATE OF PAY entry, with
    no closable identity on the page (letters print no gross). The license is scoped to
    pay_stub, so this measured-correct reading must not move; the residual hazard is
    recorded in loop/reports/it-008.md, not patched here."""
    got = _fields(UP_018, "employment_letter")["hourly_rate"]
    assert got["value"] == pytest.approx(17.50)
    assert got["certainty"] != "abstain"


def test_seattle_filled_stays_all_abstain() -> None:
    """The menu document itself: nothing on the seattle fill binds through RATE OF PAY,
    and nothing may start to -- every reachable field stays an abstention."""
    fields = _fields(SEATTLE, "pay_stub")
    assert all(f["certainty"] == "abstain" for f in fields.values())


# ─────────────────────────────────────────────────────────── the restated constant


def test_the_hours_ceiling_is_the_same_number_everywhere() -> None:
    """`RATE_PERIOD_MAX_HOURS` restates `verified.FALLBACK_HOURS_BOUND` (as
    `columns.MAX_PERIOD_HOURS` already does) so `core.verified` can stay unimported
    under its flag. If one of the three ever moves alone, this is the alarm."""
    from core import columns, verified

    assert ex.RATE_PERIOD_MAX_HOURS == verified.FALLBACK_HOURS_BOUND
    assert ex.RATE_PERIOD_MAX_HOURS == columns.MAX_PERIOD_HOURS
