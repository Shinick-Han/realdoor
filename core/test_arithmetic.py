# -*- coding: utf-8 -*-
"""
test_arithmetic.py -- what the arithmetic path must refuse, and what it must not move.

The tests are grouped the way the risk is: the ones that matter most are the ones asserting
that something does NOT happen. A new reading path in this codebase is only worth having if
turning it off restores the previous behaviour exactly, and if turning it on cannot invent a
figure that was previously an honest blank.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core import arithmetic as ar
from core import extract as ex
from core import verified as vf

ROOT = Path(__file__).resolve().parent.parent
EXTERNAL = ROOT / "testdata" / "external_raw"
PACK = ROOT / "pack" / "synthetic_documents"


@pytest.fixture()
def flag_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "1")
    yield


@pytest.fixture()
def flag_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    yield


# ─────────────────────────────────────────────────────────────── number tokens


@pytest.mark.parametrize(
    "text,expected",
    [
        ("707.75", 707.75),
        ("$1,142.71", 1142.71),
        ("1,627.74", 1627.74),
        ("20.346846", 20.346846),
        ("0", 0.0),
        ("90.66-", 90.66),
    ],
)
def test_numbers_we_read(text: str, expected: float) -> None:
    parsed = ar.parse_number(text)
    assert parsed is not None and parsed[0] == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "07/23/2017",     # a date is not a number
        "2026-07-03",
        "XXXXX000000",
        "N/A",
        "",
        "Regular",
        "$",              # the bare currency glyphs sitting in the VA form's empty boxes
    ],
)
def test_things_that_are_not_numbers(text: str) -> None:
    assert ar.parse_number(text) is None


# ─────────────────────────────────────────────────────── the frozen tolerances


def test_product_tolerance_is_the_display_rounding_budget_and_is_frozen() -> None:
    """The federal LES prints rate 21.38 for a true rate of 21.375. At 80 hours the printed
    product is 0.40 away from the computed one, and the budget has to cover exactly that and
    not appreciably more. Widening this is the arithmetic version of widening the geometry
    window, which is the failure this whole project is organised around avoiding."""
    assert ar.product_tolerance(80.0) == pytest.approx(0.405)
    assert abs(21.38 * 80.0 - 1710.00) <= ar.product_tolerance(80.0)
    # ...and it is tight enough that a genuinely different rate does not slip through.
    assert abs(21.50 * 80.0 - 1710.00) > ar.product_tolerance(80.0)


def test_sum_tolerance_is_linear_in_the_number_of_addends() -> None:
    assert ar.sum_tolerance(2) == pytest.approx(0.015)
    assert ar.sum_tolerance(5) == pytest.approx(0.030)


# ────────────────────────────────────── the measurement the whole design rests on


def _tokens(pdf: Path, page_number: int = 1) -> list[ar.NumberToken]:
    import pdfplumber

    with pdfplumber.open(pdf) as doc:
        page = doc.pages[page_number - 1]
        return ar.number_tokens(ex.read_words(page, page_number))


@pytest.mark.parametrize(
    "file_name,page",
    [("ext_unc.pdf", 1), ("ext_les.pdf", 3)],
)
def test_geometry_narrows_the_candidate_space_but_does_not_empty_it(
    file_name: str, page: int
) -> None:
    """The column constraint shrinks the search. It does not make it safe on its own.

    The design this module implements claimed the constrained search finds ZERO coincidences.
    That does not reproduce: on these two dense pages it reaches roughly a third to a sixth of
    the values the free search reaches, and what is left still contains real accidents --
    `8.00 + 72.00 = 80.00` on the UNC advice joins two year-to-date leave figures into the
    current-period hours total.

    So this test asserts the true thing in both directions. The constraint must help, and it
    must NOT be mistaken for a guarantee -- if someone later makes the second assertion fail by
    tightening the search until nothing survives, the acceptance rule silently stops being
    tested by the documents that produced it."""
    tokens = _tokens(EXTERNAL / file_name, page)
    constrained = ar.reachable_totals(tokens, max_size=3)
    free = ar.free_reachable_totals(tokens, max_size=3)
    assert len(constrained) * 2 < len(free), (
        f"{file_name} page {page}: constrained={len(constrained)} free={len(free)} -- the "
        f"geometry constraint has stopped narrowing the candidate space"
    )
    assert constrained, "the constrained search found nothing at all on a page full of totals"


def test_a_known_coincidence_survives_the_geometry_and_dies_at_the_anchor() -> None:
    """The specific accident, named, so nobody has to take the paragraph above on trust.

    `8.00 + 72.00 = 80.00` is a consecutive run of one aligned column on the UNC advice whose
    total is a printed number -- it passes every geometric test this module applies. It is
    still nonsense: those are year-to-date Civil Leave and Holiday hours, and 80.00 is the
    current-period hours total. Nothing multiplies out to it, so the anchor refuses it, and
    that is the layer actually holding the line."""
    tokens = _tokens(EXTERNAL / "ext_unc.pdf", 1)
    hits = [
        s
        for s in ar.find_run_sums(tokens, min_len=2, max_len=2)
        if [t.text for t in s.run] == ["8.00", "72.00"]
    ]
    assert hits, "the coincidence this test is about has disappeared; re-check the search"
    anchored_totals = {a.total.value for a in vf._anchored_runs(tokens, 744.0)}
    assert 80.00 not in anchored_totals


def test_the_row_product_that_anchors_adp() -> None:
    products = ar.find_row_products(_tokens(EXTERNAL / "ext_adp.pdf"))
    pairs = {(p.rate.text, p.hours.text, p.amount.text) for p in products}
    assert ("14.9000", "40.00", "596.00") in pairs
    assert ("22.3500", "5.00", "111.75") in pairs


def test_hours_times_rate_does_not_equal_gross_and_that_is_silence() -> None:
    """Measured on every real stub: gross is a sum of several earning rows, so this identity
    fails everywhere. It must therefore never be used to reject a candidate -- doing so would
    kill correct values on all four documents. The assertion is that the mismatch is real."""
    for file_name, hours, rate, gross in [
        ("ext_adp.pdf", 40.00, 14.90, 707.75),
        ("ext_unc.pdf", 74.50, 20.346846, 1627.74),
    ]:
        assert abs(hours * rate - gross) > ar.product_tolerance(hours)


# ───────────────────────────────────────────────────────────── V3, the bounds


def test_hours_bound_prefers_the_documents_own_pay_period() -> None:
    found = {
        "pay_period_start": {"value": "2015-03-30", "certainty": "low"},
        "pay_period_end": {"value": "2015-04-05", "certainty": "low"},
    }
    bound, why = vf.hours_bound(found)
    assert bound == 7 * 24.0  # inclusive of both days: 03/30..04/05 is seven days of work
    assert "pay period read from the page" in why


def test_hours_bound_falls_back_when_the_period_is_unreadable() -> None:
    bound, why = vf.hours_bound({"pay_period_start": {"value": None, "certainty": "abstain"}})
    assert bound == vf.FALLBACK_HOURS_BOUND == 744.0
    assert "fallback" in why


@pytest.mark.parametrize("ytd_hours", [1390.00, 1596.0, 855.00])
def test_the_fallback_bound_separates_year_to_date_hours_from_a_period(ytd_hours: float) -> None:
    """The YTD trap, stated as a test. Every year-to-date hours total on the real documents
    must fail the bound and every period figure must pass it -- that separation is the only
    thing standing between us and electing 28,707.21 as the gross pay."""
    assert not vf._veto_bound("regular_hours", ytd_hours, vf.FALLBACK_HOURS_BOUND, None)


@pytest.mark.parametrize("period_hours", [74.50, 74.25, 80.00, 40.00])
def test_period_hours_pass_the_fallback_bound(period_hours: float) -> None:
    assert vf._veto_bound("regular_hours", period_hours, vf.FALLBACK_HOURS_BOUND, None)


def test_v3_refuses_the_annual_salary_printed_under_an_hourly_caption() -> None:
    """UNC prints `Pay Rate: $45,000.00 Annual`, and `PAY RATE` is in the frozen vocabulary as
    `hourly_rate`. V2 cannot catch this -- money parses as money. The bound is what catches it,
    and it is derived from the document itself: an hourly rate cannot exceed the period gross."""
    assert not vf._veto_bound("hourly_rate", 45000.0, 744.0, 1627.74)
    assert vf._veto_bound("hourly_rate", 20.346846, 744.0, 1627.74)


# ───────────────────────────────────────────────────────── V1, grounding


def test_grounding_refuses_an_index_that_names_a_different_word() -> None:
    import pdfplumber

    with pdfplumber.open(EXTERNAL / "ext_adp.pdf") as doc:
        words = ex.read_words(doc.pages[0], 1)
    tokens = ar.number_tokens(words)
    good = tokens[0]
    assert vf._veto_grounding(words, good)

    # Same value, an index that points somewhere else: refused.
    moved = ar.NumberToken(
        page=good.page, index=(good.index + 1) % len(words), text=good.text,
        value=good.value, x0=good.x0, x1=good.x1, baseline=good.baseline,
        decimals=good.decimals,
    )
    assert not vf._veto_grounding(words, moved)

    # A value nobody printed has no honest index to name.
    invented = ar.NumberToken(
        page=good.page, index=good.index, text="999999.99", value=999999.99,
        x0=good.x0, x1=good.x1, baseline=good.baseline, decimals=2,
    )
    assert not vf._veto_grounding(words, invented)


# ─────────────────────────────────────────────── the flag, and what it must not move


def test_flag_is_off_by_default(flag_off) -> None:
    assert ex._arithmetic_enabled() is False


@pytest.mark.parametrize("value", ["0", "", "true", "yes", "2"])
def test_only_the_literal_one_switches_it_on(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REALDOOR_ARITHMETIC", value)
    assert ex._arithmetic_enabled() is False


def _view_signature(pdf: Path, document_type: str) -> str:
    view = ex.extract_document(pdf, document_type=document_type)
    return json.dumps(view, sort_keys=True, default=str)


PACK_SAMPLES = sorted(PACK.rglob("*.pdf"))[:6]


@pytest.mark.parametrize("pdf", PACK_SAMPLES, ids=lambda p: p.name)
def test_the_flag_moves_nothing_on_the_pack(pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pack is what the 159/159 gold and the bbox IoU were measured against. The arithmetic
    path may not touch it in either direction -- every field there is already answered by the
    label geometry, so there is no blank for it to fill and it must stay silent."""
    document_type = ex.infer_document_type(pdf)
    monkeypatch.delenv("REALDOOR_ARITHMETIC", raising=False)
    off = _view_signature(pdf, document_type)
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "1")
    on = _view_signature(pdf, document_type)
    assert off == on


# ──────────────────────────────────────── what the chain accepts, end to end


ACCEPTED = [
    ("ext_adp.pdf", "gross_pay", 707.75),
    ("ext_adp.pdf", "net_pay", 532.76),
    ("ext_unc.pdf", "hourly_rate", 20.346846),
]


@pytest.mark.parametrize("file_name,field,expected", ACCEPTED, ids=lambda v: str(v))
def test_the_chain_reads_what_the_geometry_could_not(
    file_name: str, field: str, expected: float, flag_on
) -> None:
    view = ex.extract_document(EXTERNAL / file_name, document_type="pay_stub")
    got = {f["field"]: f for f in view["fields"]}[field]
    assert got["value"] == pytest.approx(expected)
    assert got["certainty"] == "low", "the arithmetic path never earns `high`"
    assert vf.ARITHMETIC_NOTE in (got["notes"] or "")
    assert got["bbox"] is not None and got["page"] is not None


def test_the_chain_never_claims_high(flag_on) -> None:
    """`high` belongs to the geometry path the gold measured. However many identities agree,
    a value that arrived by arithmetic is offered as `low` and a human is expected to look."""
    for file_name in ("ext_adp.pdf", "ext_unc.pdf", "ext_utep.pdf", "ext_les.pdf"):
        view = ex.extract_document(EXTERNAL / file_name, document_type="pay_stub")
        for item in view["fields"]:
            if vf.ARITHMETIC_NOTE in (item.get("notes") or ""):
                assert item["certainty"] == "low"


# ───────────────────────────────────────────── what it must keep refusing


REFUSALS = [
    # The two blank government forms: the whole point is that nothing is invented.
    ("ext_nydol.pdf", "benefit_letter"),
    ("ext_va.pdf", "employment_letter"),
]


@pytest.mark.parametrize("file_name,document_type", REFUSALS, ids=lambda v: str(v))
def test_blank_forms_stay_blank(file_name: str, document_type: str, flag_on) -> None:
    view = ex.extract_document(EXTERNAL / file_name, document_type=document_type)
    answered = [f["field"] for f in view["fields"] if f["certainty"] != "abstain"]
    assert answered == [], f"{file_name} invented {answered} out of a blank form"


def test_les_gross_and_net_stay_refused(flag_on) -> None:
    """The LES is the hard one and it must stay hard rather than be made to pass. Its earnings
    table prints a single row of 1710.00 against a gross of 1813.00, and its own totals do not
    close: 1813.00 - 852.57 = 960.43 where the page prints 960.50. Nothing the document
    computes supports either figure, so we do not report either figure."""
    view = ex.extract_document(EXTERNAL / "ext_les.pdf", document_type="pay_stub")
    got = {f["field"]: f for f in view["fields"]}
    assert got["gross_pay"]["certainty"] == "abstain"
    assert got["net_pay"]["certainty"] == "abstain"


def test_ambiguous_factors_abstain_rather_than_guess(flag_on) -> None:
    """ADP's earnings table holds two rows, so `hours` is 40.00 or 5.00 and `rate` is 14.9000
    or 22.3500. Multiplication commutes and neither column adds up to anything printed, so
    there is no measurement that tells them apart -- and two survivors is an abstention."""
    view = ex.extract_document(EXTERNAL / "ext_adp.pdf", document_type="pay_stub")
    got = {f["field"]: f for f in view["fields"]}
    assert got["regular_hours"]["certainty"] == "abstain"
    assert got["hourly_rate"]["certainty"] == "abstain"


# ───────────────────────────────────── a proposal is not an answer


def test_a_proposal_is_always_an_abstention_carrying_a_suggestion(flag_on) -> None:
    """`scripts/measure_external_holdout.py` scores everything that is not abstained. A
    proposal resting on label adjacency alone would therefore enter the wrong-answer
    denominator if it were emitted as a value, so it never is: `certainty` stays `abstain`
    and `value` stays null. A renter may confirm it, which is what `confirmed_by_renter` in
    the contract's evidence_kind enum is already for."""
    seen = 0
    sources = [(EXTERNAL / n, "pay_stub") for n in
               ("ext_adp.pdf", "ext_unc.pdf", "ext_utep.pdf", "ext_les.pdf")]
    sources.append((ROOT / "testdata" / "uploads" / "up_024_pay_stub_table.pdf", "pay_stub"))
    for pdf, document_type in sources:
        if not pdf.exists():
            continue
        for item in ex.extract_document(pdf, document_type=document_type)["fields"]:
            if vf.PROPOSAL_PREFIX not in (item.get("notes") or ""):
                continue
            seen += 1
            assert item["certainty"] == "abstain"
            assert item["value"] is None
            assert item["bbox"] is None and item["page"] is None
            payload = json.loads((item["notes"]).split(vf.PROPOSAL_PREFIX, 1)[1])
            assert payload["support"] == "label adjacency only"
    assert seen > 0, "no proposal was produced anywhere; this test has stopped testing anything"


def test_the_table_fixture_proposes_but_does_not_answer(flag_on) -> None:
    """up_024 is the earnings-TABLE layout the geometry path deliberately leaves unsolved. It
    prints no column total, so the chain has nothing to verify and correctly stays silent --
    but a `GROSS PAY` label does sit beside a number, so S2 raises it as a suggestion."""
    pdf = ROOT / "testdata" / "uploads" / "up_024_pay_stub_table.pdf"
    got = {f["field"]: f for f in ex.extract_document(pdf, document_type="pay_stub")["fields"]}
    gross = got["gross_pay"]
    assert gross["certainty"] == "abstain" and gross["value"] is None
    assert vf.PROPOSAL_PREFIX in gross["notes"]


# ──────────────────────────────────────────────── the contract still holds


def test_nothing_this_path_emits_breaches_the_output_gate(flag_on) -> None:
    from api.gate import assert_clean

    for name in ("ext_adp.pdf", "ext_unc.pdf", "ext_utep.pdf", "ext_les.pdf",
                 "ext_nydol.pdf", "ext_va.pdf"):
        document_type = "pay_stub"
        if name == "ext_nydol.pdf":
            document_type = "benefit_letter"
        if name == "ext_va.pdf":
            document_type = "employment_letter"
        assert_clean(ex.extract_document(EXTERNAL / name, document_type=document_type))


def test_no_new_labels_were_added_to_the_vocabulary() -> None:
    """S2 reads the frozen tables and nothing else. If a label were quietly added to make a
    document read, this is where it would show up."""
    for document_type in ex.LABEL_MAP:
        for field, labels in vf._labels_for(document_type).items():
            frozen = {
                ex.normalize_label(k)
                for table in (ex.LABEL_MAP, ex.LABEL_SYNONYMS)
                for k, v in table.get(document_type, {}).items()
                if v == field
            }
            assert labels == frozen
