# -*- coding: utf-8 -*-
"""The it-004 completions (`REALDOOR_OCR_BAND_ROLE`): what they emit, and -- mostly --
what they refuse.

Two conduct changes in `core.verified.verify_page`, active only on pages carrying
it-003-injected OCR words (loop/proposals/it-004.md, falsified over all 77 corpus
documents first -- loop/falsification/it-004.json, fired on 2 of 77, zero conflicts):

  (1) a `x * 1 = x` coincidence -- the multiplicative identity -- no longer testifies
      that a line is an earnings row, so a deductions+net band sharing that line is
      visible to the EXISTING net rule (the last term of a run summing to the gross);
  (2) `regular_hours` candidates are the hours factors of anchored rows that print
      the word REGULAR, under a printed column header that is exactly HOURS -- no
      longer every member of the hours column.

The OCR-backed tests skip when the untracked confirm PDFs are absent, like the
existing confirm-set tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex
from core import verified
from core.extract import LineBoxConvention

ROOT = Path(__file__).resolve().parent.parent
CONFIRM = ROOT / "testdata" / "confirm_raw"

OU = CONFIRM / "ou_sample_check_stub.pdf"
OSU = CONFIRM / "osu_sample_earnings_statement.pdf"

WANTED = ["gross_pay", "net_pay", "hourly_rate", "regular_hours"]


def _word(text: str, x0: float, x1: float, y0: float, y1: float, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x1, baseline=y0, glyph_bottom=y0,
                   glyph_top=y1, size=max(y1 - y0 - 4.0, 1.0), bold=False, page=page)


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_OCR_BAND_ROLE", raising=False)
    assert ex._ocr_band_role_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_OCR_BAND_ROLE", value)
    assert ex._ocr_band_role_enabled() is (value.strip() != "0")


# ─────────────────────────────── the named-row hours rule, on a synthetic anchored page
#
# Layout under test: two earnings rows whose amounts column sums to a printed total
# and whose hours column sums to a printed total (which is what tells the factor
# columns apart), one row named by the printed word Regular.
#
#     Rate      Hours       Amount
#     Regular   10.00 31.00 310.00
#     Overtime  20.00  6.00 120.00
#     Total           37.00 430.00


def _anchored_page(header_words, second_row_name: str = "Overtime") -> list[ex.Word]:
    return [
        *header_words,
        _word("Regular", 20.0, 55.0, 680.0, 692.0),
        _word("10.00", 100.0, 122.0, 680.0, 692.0),
        _word("31.00", 150.0, 172.0, 680.0, 692.0),
        _word("310.00", 220.0, 250.0, 680.0, 692.0),
        _word(second_row_name, 20.0, 60.0, 660.0, 672.0),
        _word("20.00", 100.0, 122.0, 660.0, 672.0),
        _word("6.00", 154.0, 172.0, 660.0, 672.0),
        _word("120.00", 220.0, 250.0, 660.0, 672.0),
        _word("Total", 20.0, 45.0, 640.0, 652.0),
        _word("37.00", 150.0, 172.0, 640.0, 652.0),
        _word("430.00", 220.0, 250.0, 640.0, 652.0),
    ]


_PLAIN_HEADER = [
    _word("Rate", 100.0, 120.0, 700.0, 712.0),
    _word("Hours", 150.0, 175.0, 700.0, 712.0),
    _word("Amount", 220.0, 250.0, 700.0, 712.0),
]

_QUALIFIED_HEADER = [
    _word("Rate", 100.0, 120.0, 700.0, 712.0),
    _word("Hours", 150.0, 175.0, 700.0, 712.0),
    _word("or", 178.0, 186.0, 700.0, 712.0),
    _word("Units", 189.0, 210.0, 700.0, 712.0),
    _word("Amount", 220.0, 250.0, 700.0, 712.0),
]


def test_the_regular_named_row_emits_its_hours() -> None:
    answers, _ = verified.verify_page(
        _anchored_page(_PLAIN_HEADER), "pay_stub", {}, LineBoxConvention(), WANTED,
        band_role=True,
    )
    assert answers["regular_hours"]["value"] == pytest.approx(31.0)
    assert answers["regular_hours"]["certainty"] == "low"
    notes = answers["regular_hours"]["notes"]
    assert "REGULAR" in notes and "HOURS" in notes


def test_without_band_role_the_same_page_still_abstains_on_hours() -> None:
    """The committed conduct is untouched: three-survivor S3 refusal stands whenever
    `band_role` is not passed -- which is every text-path call."""
    answers, _ = verified.verify_page(
        _anchored_page(_PLAIN_HEADER), "pay_stub", {}, LineBoxConvention(), WANTED,
    )
    assert "regular_hours" not in answers
    assert answers["gross_pay"]["value"] == pytest.approx(430.0)  # unchanged either way


def test_an_hours_or_units_header_refuses_by_its_own_wording() -> None:
    """lcc's trap, pinned synthetically: `Hours or Units` is not HOURS, and lcc's
    truth lists regular_hours in expect_absent -- emitting there is a scored WRONG."""
    answers, _ = verified.verify_page(
        _anchored_page(_QUALIFIED_HEADER), "pay_stub", {}, LineBoxConvention(), WANTED,
        band_role=True,
    )
    assert "regular_hours" not in answers


def test_two_regular_named_rows_refuse_on_two_survivors() -> None:
    """S3 is not relaxed: a second row also named Regular contributes its own hours
    figure and the two distinct survivors abstain."""
    answers, _ = verified.verify_page(
        _anchored_page(_PLAIN_HEADER, second_row_name="Regular"),
        "pay_stub", {}, LineBoxConvention(), WANTED,
        band_role=True,
    )
    assert "regular_hours" not in answers


# ─────────────────────────────── the band exclusion, weakened only for degenerates


def test_a_real_earnings_run_still_excludes_its_own_band() -> None:
    """The 111.75 trap (ADP shape), pinned: the earnings column 596.00 + 111.75 =
    707.75 must not nominate 111.75 as net once the exclusion admits degenerate-only
    lines -- these rows carry real rate x hours products, so they stay excluded."""
    words = [
        _word("14.90", 100.0, 122.0, 680.0, 692.0),
        _word("40.00", 150.0, 172.0, 680.0, 692.0),
        _word("596.00", 220.0, 250.0, 680.0, 692.0),
        _word("22.35", 100.0, 122.0, 660.0, 672.0),
        _word("5.00", 154.0, 172.0, 660.0, 672.0),
        _word("111.75", 221.0, 250.0, 660.0, 672.0),
        _word("707.75", 220.0, 250.0, 640.0, 652.0),
    ]
    answers, _ = verified.verify_page(
        words, "pay_stub", {}, LineBoxConvention(), WANTED, band_role=True,
    )
    assert answers["gross_pay"]["value"] == pytest.approx(707.75)
    assert "net_pay" not in answers


def test_a_degenerate_product_no_longer_excludes_the_band() -> None:
    """osu's shape in miniature: a stray printed 1 beside the deductions figure forms
    `1666.94 x 1 = 1666.94`, which used to mark the band's own line as an earnings
    row. With band_role the multiplicative identity testifies to nothing and the
    existing net rule reads the band's last term."""
    words = [
        _word("Summary", 320.0, 360.0, 640.0, 652.0),
        _word("5994.00", 400.0, 432.0, 622.0, 634.0),
        _word("1", 193.0, 199.0, 616.0, 628.0),
        _word("1666.94", 400.0, 432.0, 616.0, 628.0),
        _word("1666.94", 441.0, 473.0, 616.0, 628.0),  # the YTD twin (osu prints both)
        _word("4327.06", 400.0, 432.0, 610.0, 622.0),
    ]
    with_role, _ = verified.verify_page(
        words, "pay_stub", {}, LineBoxConvention(), ["net_pay"], band_role=True,
    )
    without_role, _ = verified.verify_page(
        words, "pay_stub", {}, LineBoxConvention(), ["net_pay"],
    )
    assert with_role["net_pay"]["value"] == pytest.approx(4327.06)
    assert "net_pay" not in without_role


# ─────────────────────────────── the two target documents, measured end to end


@pytest.fixture(scope="module")
def ou_fields() -> dict:
    if not OU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    view = ex.extract_document(OU, document_type="pay_stub")
    return {f["field"]: f for f in view["fields"]}


@pytest.fixture(scope="module")
def osu_fields() -> dict:
    if not OSU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    view = ex.extract_document(OSU, document_type="pay_stub")
    return {f["field"]: f for f in view["fields"]}


def test_ou_regular_hours_lands_on_the_regular_row(ou_fields: dict) -> None:
    field = ou_fields["regular_hours"]
    assert field["value"] == pytest.approx(68.43)
    assert field["certainty"] == "low"
    assert "REGULAR" in (field["notes"] or "")
    assert "read by OCR from an embedded image region" in (field["notes"] or "")


def test_ou_it003_values_are_untouched(ou_fields: dict) -> None:
    assert ou_fields["gross_pay"]["value"] == pytest.approx(1251.09)
    assert ou_fields["net_pay"]["value"] == pytest.approx(750.14)
    assert ou_fields["hourly_rate"]["value"] == pytest.approx(12.4808)


def test_osu_net_pay_is_the_band_tail(osu_fields: dict) -> None:
    field = osu_fields["net_pay"]
    assert field["value"] == pytest.approx(4327.06)
    assert field["certainty"] == "low"
    assert "total_band" in (field["notes"] or "")
    assert "read by OCR from an embedded image region" in (field["notes"] or "")
    assert osu_fields["gross_pay"]["value"] == pytest.approx(5994.0)


def test_the_flag_at_zero_restores_the_it003_abstentions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not OU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.setenv("REALDOOR_OCR_BAND_ROLE", "0")
    view = ex.extract_document(OU, document_type="pay_stub")
    fields = {f["field"]: f for f in view["fields"]}
    assert fields["regular_hours"]["certainty"] == "abstain"
    assert fields["regular_hours"]["value"] is None
    # the it-003 emissions do not depend on this iteration's flag
    assert fields["gross_pay"]["value"] == pytest.approx(1251.09)
