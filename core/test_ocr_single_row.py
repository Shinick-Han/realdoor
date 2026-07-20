# -*- coding: utf-8 -*-
"""The it-006 single-row anchor (`REALDOOR_OCR_SINGLE_ROW`): what it emits, and --
mostly -- what it refuses.

One conduct change in `core.verified.verify_page`, active only on pages carrying
it-003-injected OCR words (loop/proposals/it-006.md, falsified over all 77 corpus
documents first -- loop/falsification/it-006.json): a single-current-period-row
column may anchor when a non-degenerate exact row product closes on an amount the
page REPRINTS, cents-form, x-aligned, on another line -- the column's own printed
total. Everything downstream (S3, V1-V3, the band search, certainty "low") is the
committed chain. The lcc-backed tests skip when the untracked confirm PDFs are
absent, like the existing confirm tests.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex
from core import verified
from core.extract import LineBoxConvention

ROOT = Path(__file__).resolve().parent.parent
LCC = ROOT / "testdata" / "confirm_raw" / "lcc_understanding_your_paycheck.pdf"

WANTED = ["gross_pay", "net_pay", "hourly_rate", "regular_hours"]


def _word(text: str, x0: float, x1: float, y0: float, y1: float, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x1, baseline=y0, glyph_bottom=y0,
                   glyph_top=y1, size=max(y1 - y0 - 4.0, 1.0), bold=False, page=page)


def _single_row_page(total_text: str = "325.81", extra=()) -> list[ex.Word]:
    """lcc's earnings table in miniature: one current-period row and its Total row."""
    return [
        _word("31.00", 150.0, 172.0, 680.0, 692.0),
        _word("10.510000", 200.0, 245.0, 680.0, 692.0),
        _word("325.81", 300.0, 340.0, 680.0, 692.0),
        _word("Total:", 260.0, 290.0, 660.0, 672.0),
        _word(total_text, 300.0, 340.0, 660.0, 672.0),
        *extra,
    ]


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_OCR_SINGLE_ROW", raising=False)
    assert ex._ocr_single_row_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_OCR_SINGLE_ROW", value)
    assert ex._ocr_single_row_enabled() is (value.strip() != "0")


# ───────────────────────────── the mechanism, on lcc's earnings table in miniature


def test_a_single_row_with_its_printed_total_anchors_gross() -> None:
    answers, _ = verified.verify_page(
        _single_row_page(), "pay_stub", {}, LineBoxConvention(), WANTED,
        single_row=True,
    )
    assert answers["gross_pay"]["value"] == pytest.approx(325.81)
    assert answers["gross_pay"]["certainty"] == "low"
    # a single row can never resolve its factor columns, so rate/hours stay silent
    assert "hourly_rate" not in answers
    assert "regular_hours" not in answers


def test_the_committed_conduct_is_untouched_without_the_keyword() -> None:
    answers, _ = verified.verify_page(
        _single_row_page(), "pay_stub", {}, LineBoxConvention(), WANTED,
    )
    assert answers == {}


def test_a_colocated_band_yields_net_through_the_committed_rule() -> None:
    """The mechanism documented whole: with deductions+net printed under the same
    column, the band search reads net off the anchored gross exactly as it does for
    a multi-row table. (lcc's own pages never co-locate the two at native scale --
    the document-level test below pins that net stays abstained there.)"""
    band = (
        _word("61.36", 300.0, 340.0, 640.0, 652.0),
        _word("264.45", 300.0, 340.0, 620.0, 632.0),
    )
    answers, _ = verified.verify_page(
        _single_row_page(extra=band), "pay_stub", {}, LineBoxConvention(), WANTED,
        single_row=True,
    )
    assert answers["gross_pay"]["value"] == pytest.approx(325.81)
    assert answers["net_pay"]["value"] == pytest.approx(264.45)


def test_a_reprint_off_by_one_cent_refuses() -> None:
    """The document's own digit flips are the hazard ('$4,209.35' on p3 where p1
    prints '$4,209.38'): the two printings must agree to the cent, or nothing."""
    answers, _ = verified.verify_page(
        _single_row_page(total_text="325.82"), "pay_stub", {}, LineBoxConvention(),
        WANTED, single_row=True,
    )
    assert answers == {}


def test_a_same_line_twin_is_not_a_reprint() -> None:
    """osu prints Current = YTD side by side; a twin on the row's own baseline is
    the second column, not the column's total."""
    words = [
        _word("31.00", 150.0, 172.0, 680.0, 692.0),
        _word("10.510000", 200.0, 245.0, 680.0, 692.0),
        _word("325.81", 300.0, 340.0, 680.0, 692.0),
        _word("325.81", 299.0, 341.0, 680.0, 692.0),  # x-aligned, same baseline
    ]
    answers, _ = verified.verify_page(
        words, "pay_stub", {}, LineBoxConvention(), WANTED, single_row=True,
    )
    assert answers == {}


# ─────────────────────────────────── the target document, measured end to end


@pytest.fixture(scope="module")
def lcc_fields() -> dict:
    if not LCC.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    view = ex.extract_document(LCC, document_type="pay_stub")
    return {f["field"]: f for f in view["fields"]}


def test_lcc_gross_closes_on_page_3(lcc_fields: dict) -> None:
    field = lcc_fields["gross_pay"]
    assert field["value"] == pytest.approx(325.81)
    assert field["certainty"] == "low"
    assert "read by OCR from an embedded image region" in (field["notes"] or "")


def test_lcc_everything_else_stays_abstained(lcc_fields: dict) -> None:
    """The must-stay-abstained pins for the 96-116 dpi misread family, measured on
    this document: '5113.20' (a $ read as a digit, parses as money), '$4,209.35' on
    p3 vs '$4,209.38' on p1, 'Sap 15, 2017', Banner ID 'X00123458'. net_pay's band
    never shares a page with an anchor at native scale; hourly_rate and
    regular_hours are expect_absent (a single row cannot resolve factor columns);
    dates and the name have no identity at all."""
    for name in ("net_pay", "hourly_rate", "regular_hours",
                 "pay_date", "pay_period_start", "pay_period_end", "person_name"):
        assert lcc_fields[name]["certainty"] == "abstain"
        assert lcc_fields[name]["value"] is None


def test_the_flag_at_zero_restores_the_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not LCC.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.setenv("REALDOOR_OCR_SINGLE_ROW", "0")
    view = ex.extract_document(LCC, document_type="pay_stub")
    fields = {f["field"]: f for f in view["fields"]}
    assert fields["gross_pay"]["certainty"] == "abstain"
    assert fields["gross_pay"]["value"] is None
