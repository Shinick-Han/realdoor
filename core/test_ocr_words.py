# -*- coding: utf-8 -*-
"""What `core/ocr_words.py` reads, and -- mostly -- what it refuses to read.

The module adds no acceptance rule: OCR-read words are handed only to the identity
paths, so everything here pins either the guards (region merge, overlap drop, the
flag) or the refusals the loop's falsification measured (loop/falsification/it-003.json
-- fired on 2 of 77 documents, zero conflicts). The OCR-backed tests skip when the
untracked confirm PDFs are absent, like the existing confirm-set tests.
"""
from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path

import pytest

from core import extract as ex
from core import ocr_words as ow

ROOT = Path(__file__).resolve().parent.parent
CONFIRM = ROOT / "testdata" / "confirm_raw"
UPLOADS = ROOT / "testdata" / "uploads"

OU = CONFIRM / "ou_sample_check_stub.pdf"
HI_AGS = CONFIRM / "hi_ags_pay_statement_example_2021.pdf"
UP_014 = UPLOADS / "up_014_pay_stub_jane_roe_unreadable.pdf"


def _word(text: str, x0: float, x1: float, y0: float, y1: float, page: int = 1) -> ex.Word:
    return ex.Word(text=text, x0=x0, x1=x1, baseline=y0, glyph_bottom=y0,
                   glyph_top=y1, size=max(y1 - y0 - 4.0, 1.0), bold=False, page=page)


# ───────────────────────────────────────────────────────────────── the flag itself


def test_the_default_is_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REALDOOR_OCR_WORDS", raising=False)
    assert ex._ocr_words_enabled() is True


@pytest.mark.parametrize("value", ["0", "0 ", " 0", "1", "", "true", "yes", "2"])
def test_only_the_literal_zero_switches_it_off(
    value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REALDOOR_OCR_WORDS", value)
    assert ex._ocr_words_enabled() is (value.strip() != "0")


# ─────────────────────────────────────────────── region discovery and the merge guard


class _StubPage:
    """Just enough of a pdfplumber page for `regions`: `images` and `height`."""

    def __init__(self, images: list[dict], height: float = 792.0):
        self.images = images
        self.height = height


def _image(x0: float, top: float, x1: float, bottom: float, sw: int, sh: int) -> dict:
    return {"x0": x0, "top": top, "x1": x1, "bottom": bottom, "srcsize": (sw, sh)}


def test_native_scale_is_the_placement_statement() -> None:
    """966 source px over 348 placed pt is the page's own resolution claim (osu's stub);
    a non-uniform placement (ou: 197x165 dpi) takes the max so neither axis is
    undersampled."""
    scale = ow._native_scale(_image(138.1, 114.2, 486.1, 589.7, 966, 1320))
    assert scale == pytest.approx(966 / 348.0, rel=1e-3)
    stretched = ow._native_scale(_image(72.0, 94.9, 561.7, 488.6, 1339, 900))
    assert stretched == pytest.approx(1339 / 489.7, rel=1e-3)


def test_a_placement_without_a_source_size_is_skipped() -> None:
    page = _StubPage([{"x0": 0, "top": 0, "x1": 100, "bottom": 100, "srcsize": (None, None)}])
    assert ow.regions(page) == []


def test_intersecting_placements_merge_into_one_region() -> None:
    """hi_ags page 2 in miniature: two stub instances whose placements overlap by a
    sliver, each with a backing frame. One merged region -- the same pixels can never
    be OCR'd twice into one word stream, and the two instances land in one stream
    where their disagreement refuses emission."""
    page = _StubPage([
        _image(28.7, 196.2, 402.4, 490.5, 779, 614),   # left frame (150 dpi)
        _image(36.0, 202.6, 395.4, 484.2, 998, 782),   # left stub  (200 dpi)
        _image(391.2, 195.1, 764.4, 526.7, 778, 692),  # right frame; x-overlaps left
    ])
    merged = ow.regions(page)
    assert len(merged) == 1
    rect, scale = merged[0]
    assert rect == [28.7, 195.1, 764.4, 526.7]
    assert scale == pytest.approx(998 / 359.4, rel=1e-3)  # the max member scale


def test_disjoint_placements_stay_separate_and_ordered() -> None:
    page = _StubPage([
        _image(300.0, 500.0, 400.0, 600.0, 100, 100),
        _image(10.0, 10.0, 110.0, 60.0, 200, 100),
    ])
    got = ow.regions(page)
    assert len(got) == 2
    assert got[0][0][1] < got[1][0][1]  # sorted by position, top first


# ───────────────────────────────────────────────────────────── the overlap guard


def test_an_ocr_word_overlapping_a_printed_word_is_dropped() -> None:
    """The page's own printed words take precedence: a scanned duplicate of printed
    text can never enter the arithmetic beside its original."""
    printed = [_word("1,251.09", 100.0, 140.0, 500.0, 512.0)]
    duplicate = _word("1,251.09", 102.0, 141.0, 501.0, 511.0)
    elsewhere = _word("750.14", 100.0, 140.0, 400.0, 412.0)
    kept = ow.drop_overlapping([duplicate, elsewhere], printed)
    assert kept == [elsewhere]


def test_the_guard_is_inert_without_printed_words() -> None:
    scanned = [_word("750.14", 100.0, 140.0, 400.0, 412.0)]
    assert ow.drop_overlapping(scanned, []) == scanned


# ─────────────────────────────────────────── the ou target, measured end to end
# One extraction, shared: the OCR pass is seconds, not milliseconds.


@pytest.fixture(scope="module")
def ou_view() -> dict:
    """The it-003 conduct, pinned: `REALDOOR_OCR_BAND_ROLE=0` isolates the injection
    layer from the it-004 completions, whose own on/off pins live in
    `core/test_ocr_band_role.py` -- this fixture keeps asserting what it-003 shipped."""
    if not OU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    seen: list[int] = []
    original = ex.extract_fields_from_page

    def recording(words, *args, **kwargs):
        seen.append(len(words))
        return original(words, *args, **kwargs)

    ex.extract_fields_from_page = recording
    flags = pytest.MonkeyPatch()
    flags.setenv("REALDOOR_OCR_BAND_ROLE", "0")
    try:
        view = ex.extract_document(OU, document_type="pay_stub")
    finally:
        ex.extract_fields_from_page = original
        flags.undo()
    return {"fields": {f["field"]: f for f in view["fields"]},
            "label_path_word_counts": seen}


def test_ou_emits_exactly_its_identity_closed_values(ou_view: dict) -> None:
    """The design's target, exceeded and pinned: at the region's native scale the
    earnings column, the deduction band and the row products all close, so gross, net
    and rate are emitted; regular_hours refuses on S3 (three distinct hours survivors)
    with the it-004 completion pinned off -- its recovery is asserted, flag on, in
    `core/test_ocr_band_role.py`."""
    fields = ou_view["fields"]
    assert fields["gross_pay"]["value"] == pytest.approx(1251.09)
    assert fields["net_pay"]["value"] == pytest.approx(750.14)
    assert fields["hourly_rate"]["value"] == pytest.approx(12.4808)
    assert fields["regular_hours"]["certainty"] == "abstain"


def test_ou_ocr_values_are_low_and_name_their_license(ou_view: dict) -> None:
    """Constraint: an OCR-derived value is at most `low`, and its note must name both
    the identity that licensed it and the OCR provenance."""
    for name in ("gross_pay", "net_pay", "hourly_rate"):
        field = ou_view["fields"][name]
        assert field["certainty"] == "low"
        notes = field["notes"] or ""
        assert "chain" in notes  # the identity, named by verified.py
        assert "read by OCR from an embedded image region" in notes


def test_the_label_paths_never_see_an_injected_word(ou_view: dict) -> None:
    """The licensing rule is structural: `extract_fields_from_page` received exactly
    the printed words (ou page 1 prints 131, page 2 prose), so no adjacency rule can
    ever emit an OCR reading."""
    import pdfplumber

    with pdfplumber.open(OU) as pdf:
        printed = [len(ex.read_words(p, i)) for i, p in enumerate(pdf.pages, start=1)]
    assert ou_view["label_path_word_counts"] == printed


def test_flag_off_restores_the_abstentions_and_never_imports_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not OU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.setenv("REALDOOR_OCR_WORDS", "0")
    sys.modules.pop("core.ocr_words", None)
    view = ex.extract_document(OU, document_type="pay_stub")
    assert "core.ocr_words" not in sys.modules
    sys.modules["core.ocr_words"] = ow  # restore for the other tests
    fields = {f["field"]: f for f in view["fields"]}
    for name in ("gross_pay", "net_pay", "hourly_rate", "regular_hours"):
        assert fields[name]["certainty"] == "abstain"
        assert fields[name]["value"] is None


# ──────────────────────────────────────────────── the refusals, pinned permanently


_MONEY = re.compile(r"^\$?-?\d[\d,]*\.\d+$")


def test_a_decimal_stripped_page_emits_nothing() -> None:
    """Uniform decimal loss is the one correlated misread family a sum cannot refuse
    (every ratio still closes at x100). What refuses it: the chain's anchor is a row
    PRODUCT, which scales x10^4 while the amount scales x10^2, so no anchored run can
    form. Pinned on the one page that closes today."""
    if not OU.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    import pdfplumber

    from core import verified
    from core.extract import LineBoxConvention

    with pdfplumber.open(OU) as pdf:
        page = pdf.pages[0]
        words = ex.read_words(page, 1)
        ocr = ow.region_ocr_words(OU, page, 1, words)
    assert ocr, "the ou stub must yield OCR words for this test to test anything"
    stripped = [
        dataclasses.replace(w, text=w.text.replace(".", "")) if _MONEY.match(w.text) else w
        for w in ocr
    ]
    assert any(a.text != b.text for a, b in zip(ocr, stripped))
    answers, _ = verified.verify_page(
        list(words) + stripped, "pay_stub", {}, LineBoxConvention(),
        ["gross_pay", "net_pay", "hourly_rate", "regular_hours"],
    )
    assert answers == {}


def test_hi_ags_dual_instance_pages_emit_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three stub instances printing three different pay periods: page 1's total
    misreads at 200 dpi ('2.328.01', parse-refused) and page 2's two instances merge
    into one region and one stream, where their disagreement forms no identity. This
    pins the INJECTION layer's own refusals, so the it-005 labeled-band reader --
    which recovers gross/net from page 1's printed band and carries its own
    instance-conflict guard -- is pinned off; its flag-on conduct is asserted in
    `core/test_total_band.py`."""
    if not HI_AGS.exists():
        pytest.skip("confirm corpus not present (untracked PDFs)")
    monkeypatch.setenv("REALDOOR_OCR_TOTAL_BAND", "0")
    view = ex.extract_document(HI_AGS, document_type="pay_stub")
    fields = {f["field"]: f for f in view["fields"]}
    for name in ("gross_pay", "net_pay", "regular_hours", "hourly_rate"):
        assert fields[name]["certainty"] == "abstain"
        assert fields[name]["value"] is None


def test_up_014_gross_trap_stays_refused() -> None:
    """The wrong-value trap in the flesh: gross 700.00 is unreadable on the rotated,
    blurred scan and 567.00 -- the NET -- is the amount below the GROSSPAY label.
    Adjacency cannot emit (structural gating) and no identity closes over 567 as
    gross, so both fields abstain."""
    view = ex.extract_document(UP_014, document_type="pay_stub")
    fields = {f["field"]: f for f in view["fields"]}
    for name in ("gross_pay", "net_pay"):
        assert fields[name]["certainty"] == "abstain"
        assert fields[name]["value"] is None


def test_flag_on_and_off_agree_everywhere_there_are_no_images() -> None:
    """A page without embedded images injects nothing, so the flag must move nothing.
    Measured over the whole corpus in loop/falsification/it-003.json; pinned here on
    one readable pack document."""
    target = ROOT / "pack" / "synthetic_documents" / "documents" / "hh-002_d02_pay_stub.pdf"
    if not target.exists():
        pytest.skip("pack documents not present")
    # hh-002_d02 is a text-layer document (gold: rasterized false) with no image
    # XObjects -- the it-003 census found images only on the 8 rasterized pack docs.
    document_type = ex.infer_document_type(target)
    on = json.dumps(ex.extract_document(target, document_type=document_type),
                    sort_keys=True, default=str)
    off_env = pytest.MonkeyPatch()
    off_env.setenv("REALDOOR_OCR_WORDS", "0")
    try:
        off = json.dumps(ex.extract_document(target, document_type=document_type),
                         sort_keys=True, default=str)
    finally:
        off_env.undo()
    assert on == off
