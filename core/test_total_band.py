# -*- coding: utf-8 -*-
"""What `core/total_band.py` reads, and -- mostly -- what it refuses to read.

The module emits gross_pay/net_pay only from a printed four-cell band whose
arithmetic closes (loop/proposals/it-005.md; falsified over all 77 corpus documents
first -- loop/falsification/it-005.json). Everything here pins either the identity,
the two halves of the instance-conflict guard, or the refusals the design named
(FED TAXABLE adjacency, straddling tokens, a band that does not sum). The OCR-backed
tests skip when the untracked confirm PDFs are absent, like the existing confirm
tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core import extract as ex
from core import total_band as tb
from core.extract import LineBoxConvention

ROOT = Path(__file__).resolve().parent.parent
HI_AGS = ROOT / "testdata" / "confirm_raw" / "hi_ags_pay_statement_example_2021.pdf"

WANTED = ["gross_pay", "net_pay"]


def _word(text: str, x0: float, x1: float, y0: float, y1: float, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x1, baseline=y0, glyph_bottom=y0,
                   glyph_top=y1, size=max(y1 - y0 - 4.0, 1.0), bold=False, page=page)


def _band_page(values=("2,328.01", "444.00", "372.63", "1,511.38"),
               extra=()) -> list[ex.Word]:
    """The hi_ags band in miniature: OCR-fused label cells, one value line below."""
    gross, taxes, deductions, net = values
    return [
        _word("TOTALGROSS", 100.0, 160.0, 700.0, 712.0),
        _word("FEDTAXABLEGROSS", 170.0, 240.0, 700.0, 712.0),
        _word("TOTALTAXES", 250.0, 300.0, 700.0, 712.0),
        _word("TOTALDEDUCTIONS", 310.0, 390.0, 700.0, 712.0),
        _word("NETPAY", 400.0, 440.0, 700.0, 712.0),
        _word(gross, 100.0, 150.0, 680.0, 692.0),
        _word(taxes, 255.0, 295.0, 680.0, 692.0),
        _word(deductions, 315.0, 365.0, 680.0, 692.0),
        _word(net, 400.0, 445.0, 680.0, 692.0),
        *extra,
    ]


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_OCR_TOTAL_BAND", raising=False)
    assert ex._ocr_total_band_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_OCR_TOTAL_BAND", value)
    assert ex._ocr_total_band_enabled() is (value.strip() != "0")


# ─────────────────────────────────────────────── the identity, and its refusals


def test_a_closed_band_emits_gross_and_net() -> None:
    got = tb.recover(_band_page(), LineBoxConvention(), WANTED)
    assert got["gross_pay"]["value"] == pytest.approx(2328.01)
    assert got["net_pay"]["value"] == pytest.approx(1511.38)
    for name in WANTED:
        assert got[name]["certainty"] == "low"
        assert tb.TOTAL_BAND_NOTE in got[name]["notes"]


def test_a_band_that_does_not_sum_refuses() -> None:
    got = tb.recover(_band_page(values=("2,328.01", "445.00", "372.63", "1,511.38")),
                     LineBoxConvention(), WANTED)
    assert got == {}


def test_a_duplicated_label_refuses_the_whole_page() -> None:
    """The within-page instance guard: two stub instances in one merged stream print
    the labels twice, and the page has not said which band is which. Measured live
    on hi_ags page 2; pinned here synthetically."""
    twice = _band_page(extra=(_word("NETPAY", 500.0, 540.0, 700.0, 712.0),))
    assert tb.recover(twice, LineBoxConvention(), WANTED) == {}


def test_a_token_two_cells_could_claim_refuses() -> None:
    straddler = _band_page(extra=(_word("99.00", 295.0, 320.0, 680.0, 692.0),))
    assert tb.recover(straddler, LineBoxConvention(), WANTED) == {}


def test_fed_taxable_gross_is_not_a_band_cell() -> None:
    """The design's named adjacency risk: a value under FED TAXABLE GROSS belongs to
    no band cell and is ignored -- it neither joins the sum nor blocks the band."""
    with_fed = _band_page(extra=(_word("2,328.01", 175.0, 225.0, 680.0, 692.0),))
    got = tb.recover(with_fed, LineBoxConvention(), WANTED)
    assert got["gross_pay"]["value"] == pytest.approx(2328.01)
    assert got["gross_pay"]["bbox"][0] < 170.0  # the TOTAL GROSS cell's token, not FED's


def test_a_separator_misread_is_not_money() -> None:
    """`'2.328.01'` (comma read as period, measured on hi_ags p1's earnings total)
    must never enter the band: cents-form or nothing."""
    got = tb.recover(_band_page(values=("2.328.01", "444.00", "372.63", "1,511.38")),
                     LineBoxConvention(), WANTED)
    assert got == {}


def test_a_known_gross_contradiction_refuses_whole() -> None:
    got = tb.recover(_band_page(), LineBoxConvention(), WANTED, known_gross=1000.0)
    assert got == {}


def test_two_pages_that_disagree_withdraw_everything() -> None:
    """The cross-page instance guard: page order must never choose between two stub
    instances that each closed their own band."""
    p1 = tb.recover(_band_page(), LineBoxConvention(), WANTED)
    p2 = tb.recover(_band_page(values=("2,583.00", "500.00", "571.62", "1,511.38")),
                    LineBoxConvention(), WANTED)
    assert p1 and p2 and p1["gross_pay"]["value"] != p2["gross_pay"]["value"]
    assert tb.reconcile([p1, p2]) == {}
    assert tb.reconcile([p1, p1]) == p1
    assert tb.reconcile([p1]) == p1


# ─────────────────────────────────── the target document, measured end to end


@pytest.fixture(scope="module")
def hi_ags_fields() -> dict:
    if not HI_AGS.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    view = ex.extract_document(HI_AGS, document_type="pay_stub")
    return {f["field"]: f for f in view["fields"]}


def test_hi_ags_band_values_are_emitted(hi_ags_fields: dict) -> None:
    assert hi_ags_fields["gross_pay"]["value"] == pytest.approx(2328.01)
    assert hi_ags_fields["net_pay"]["value"] == pytest.approx(1511.38)
    for name in WANTED:
        field = hi_ags_fields[name]
        assert field["certainty"] == "low"
        assert tb.TOTAL_BAND_NOTE in (field["notes"] or "")
        assert "read by OCR from an embedded image region" in (field["notes"] or "")


def test_hi_ags_everything_else_stays_abstained(hi_ags_fields: dict) -> None:
    """Dates and the name have no identity (T13); regular_hours / hourly_rate are
    expect_absent. The band module can name none of them, structurally."""
    for name in ("pay_date", "pay_period_start", "pay_period_end",
                 "person_name", "regular_hours", "hourly_rate"):
        assert hi_ags_fields[name]["certainty"] == "abstain"
        assert hi_ags_fields[name]["value"] is None


def test_the_flag_at_zero_restores_the_abstentions_and_never_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not HI_AGS.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.setenv("REALDOOR_OCR_TOTAL_BAND", "0")
    sys.modules.pop("core.total_band", None)
    view = ex.extract_document(HI_AGS, document_type="pay_stub")
    assert "core.total_band" not in sys.modules
    sys.modules["core.total_band"] = tb  # restore for the other tests
    fields = {f["field"]: f for f in view["fields"]}
    for name in WANTED:
        assert fields[name]["certainty"] == "abstain"
        assert fields[name]["value"] is None
