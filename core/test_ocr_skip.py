# -*- coding: utf-8 -*-
"""The it-007 skip (`REALDOOR_OCR_SKIP_SATISFIED`): when the OCR-words pass is dead
work, and the proof that skipping it changes nothing.

One conduct change in `core.extract.extract_document` (loop/proposals/it-007.md,
falsified over all 77 corpus documents first -- loop/falsification/it-007.json):
the only fields any OCR consumer can ask for are the blank expected fields in
`verified.VERIFIABLE_FIELDS` ∪ {gross_pay, net_pay} -- that is the it-003
injection gate's own design, read off the three consumer gates -- so when the
text pass leaves none of those blank, the OCR-words path (discovery, rendering,
recognition) is skipped entirely. When any is blank, collection runs exactly as
before, merely deferred to after the text pass. The tests pin both halves and
the refusals: bonita, whose expect-absent `hourly_rate`/`regular_hours` keep the
OCR consumers reachable, must NOT skip. The confirm-PDF tests skip when the
untracked PDFs are absent, like the existing confirm tests.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import extract as ex

ROOT = Path(__file__).resolve().parent.parent
CA_DLSE = ROOT / "testdata" / "confirm_raw" / "ca_dlse_paystub_hourly.pdf"
BONITA = ROOT / "testdata" / "confirm_raw" / "bonita_certificated_check_sample.pdf"
UP_010 = ROOT / "testdata" / "uploads" / "up_010_benefit_letter_sam_poe_scan.pdf"


def _dump(path: Path, doc_type: str) -> str:
    view = ex.extract_document(path, document_type=doc_type,
                               fallback_mapper=ex.synonym_mapper)
    return json.dumps(view, sort_keys=True, ensure_ascii=False, default=str)


def _count_region_ocr_calls(monkeypatch: pytest.MonkeyPatch) -> list:
    """Route `region_ocr_words` through a counter that still does the real work."""
    from core import ocr_words as ow

    calls: list = []
    real = ow.region_ocr_words

    def counting(pdf_source, plumber_page, page_number, text_words):
        calls.append(page_number)
        return real(pdf_source, plumber_page, page_number, text_words)

    monkeypatch.setattr(ow, "region_ocr_words", counting)
    return calls


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    assert ex._ocr_skip_satisfied_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_OCR_SKIP_SATISFIED", value)
    assert ex._ocr_skip_satisfied_enabled() is (value.strip() != "0")


# ─────────────── the numeric four all read from text: the skip fires, nothing changes


def test_ca_dlse_skips_the_ocr_pass_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    """ca_dlse_paystub_hourly reads gross, net, hours and rate from its text
    layer, so no OCR consumer can run -- with the flag on, `region_ocr_words`
    must never be called, and its one embedded image is never rendered."""
    if not CA_DLSE.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    calls = _count_region_ocr_calls(monkeypatch)
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    view = ex.extract_document(CA_DLSE, document_type="pay_stub",
                               fallback_mapper=ex.synonym_mapper)
    assert calls == []
    settled = {f["field"]: f for f in view["fields"]}
    from core import verified

    for name in ex.EXPECTED_FIELDS["pay_stub"]:
        if name in verified.VERIFIABLE_FIELDS:
            assert settled[name]["certainty"] != "abstain"


def test_ca_dlse_output_is_byte_identical_either_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not CA_DLSE.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    with_skip = _dump(CA_DLSE, "pay_stub")
    monkeypatch.setenv("REALDOOR_OCR_SKIP_SATISFIED", "0")
    without_skip = _dump(CA_DLSE, "pay_stub")
    assert with_skip == without_skip


# ──────── bonita, the must-NOT-skip pin: blank verifiable fields keep OCR live


def test_bonita_still_collects_and_output_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """bonita's text pass reads its five present fields, but `hourly_rate` and
    `regular_hours` (absent on the page) stay abstaining -- both VERIFIABLE, so
    the OCR-injected verify path stays reachable and collection must still run.
    Deferred means later, not different: same pages, same order, same bytes."""
    if not BONITA.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    calls = _count_region_ocr_calls(monkeypatch)
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    with_skip = _dump(BONITA, "pay_stub")
    assert calls != []  # the OCR pass ran
    deferred_calls = list(calls)
    calls.clear()
    monkeypatch.setenv("REALDOOR_OCR_SKIP_SATISFIED", "0")
    without_skip = _dump(BONITA, "pay_stub")
    assert calls == deferred_calls  # same pages, same order, merely later
    assert with_skip == without_skip


# ──────────────────────────────── interactions with the neighbouring flags


def test_with_ocr_words_off_the_skip_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`REALDOOR_OCR_WORDS=0` already collects nothing; the skip must not alter
    that, in either flag state."""
    if not BONITA.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    calls = _count_region_ocr_calls(monkeypatch)
    monkeypatch.setenv("REALDOOR_OCR_WORDS", "0")
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    a = _dump(BONITA, "pay_stub")
    monkeypatch.setenv("REALDOOR_OCR_SKIP_SATISFIED", "0")
    b = _dump(BONITA, "pay_stub")
    assert calls == []
    assert a == b


# ─────── a type that expects no numeric-four field: vacuously satisfied, exactly


def test_a_benefit_letter_scan_skips_by_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """up_010 is a full-page scan, but `benefit_letter` expects no field in
    `VERIFIABLE_FIELDS` ∪ {gross_pay, net_pay}, so no OCR consumer can ever run
    on it -- the whole-page render was dead work by document type alone."""
    calls = _count_region_ocr_calls(monkeypatch)
    monkeypatch.delenv("REALDOOR_OCR_SKIP_SATISFIED", raising=False)
    with_skip = _dump(UP_010, "benefit_letter")
    assert calls == []
    monkeypatch.setenv("REALDOOR_OCR_SKIP_SATISFIED", "0")
    without_skip = _dump(UP_010, "benefit_letter")
    assert calls != []  # today's conduct pays the render for nothing
    assert with_skip == without_skip
