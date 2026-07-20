# -*- coding: utf-8 -*-
"""
test_nominate.py — 문서 종류 지명(인쇄된 제목 → 닫힌 표, 완전 일치).

여기서 고정하는 성질은 정확도 숫자가 아니라 **실패의 방향**이다: 표가 놓치면
지명 없이 묻고(놓침은 질문), 지명은 반드시 근거(인쇄 문구 + 페이지/좌표)를
동봉하며, 종류 단어를 인쇄하지만 그 종류가 아닌 문서 — 저장소의 살아 있는 반례
둘 — 는 지명되지 않는다. 마지막으로 세 말뭉치 전체(64장)에 대한 오지명 0 을
스윕으로 고정한다: 이 표를 넓히다 오지명이 생기면 이 파일이 먼저 안다.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import nominate as nominate_mod  # noqa: E402
from api.app import app  # noqa: E402
from core.extract import EXPECTED_FIELDS  # noqa: E402

PACK = ROOT / "pack" / "synthetic_documents" / "documents"
UPLOADS = ROOT / "testdata" / "uploads"
CONFIRM = ROOT / "testdata" / "confirm_raw"


# ── 표 자체의 성질 ────────────────────────────────────────────────────────
def test_every_nominated_type_is_one_the_extractor_can_read():
    """지명은 읽을 줄 아는 종류로만 간다. 표가 추출기가 모르는 종류를 내면
    지명된 업로드가 그 자리에서 unsupported 로 거절된다 — 자기모순이다."""
    assert set(nominate_mod.NOMINATION_TABLE.values()) <= set(EXPECTED_FIELDS)


def test_the_table_holds_no_genre_qualified_phrases():
    """"SAMPLE ...", "UNDERSTANDING ..." 류가 표에 들어오는 순간, 어떤 종류에
    **대한** 문서(견본·해설·안내)가 그 종류로 지명된다. 방어선은 표의 규율이다."""
    for phrase in nominate_mod.NOMINATION_TABLE:
        for banned in ("SAMPLE", "UNDERSTANDING", "INSTRUCTIONS", "EXAMPLE",
                       "TEMPLATE", "GUIDE", "READING"):
            assert banned not in phrase, (phrase, banned)


# ── 지명의 모양 ───────────────────────────────────────────────────────────
def test_a_nomination_always_carries_its_printed_evidence():
    nom, reason = nominate_mod.nominate(
        (UPLOADS / "up_003_pay_stub_john_doe.pdf").read_bytes())
    assert reason == "matched"
    assert nom["document_type"] == "pay_stub"
    # 근거는 분리 불가: 일치한 인쇄 문구와 그 위치가 함께 온다.
    assert nom["matched_text"] == "Earnings Statement"
    assert nom["page"] == 1
    x0, y0, x1, y1 = nom["bbox"]
    assert x0 < x1 and y0 < y1


def test_a_scan_is_not_nominated_because_there_is_no_printed_text_to_read():
    nom, reason = nominate_mod.nominate(
        (UPLOADS / "up_006_pay_stub_sam_poe_scan.pdf").read_bytes())
    assert nom is None and reason == "no_text_layer"


def test_an_unknown_title_asks_instead_of_guessing():
    """유틸리티 고지서: 지원하지 않는 종류다. 표에 없으니 지명도 없다."""
    nom, reason = nominate_mod.nominate(
        (UPLOADS / "up_013_utility_bill_john_doe.pdf").read_bytes())
    assert nom is None and reason == "no_title_match"


# ── 이름 붙인 위험: 종류 단어를 인쇄하지만 그 종류가 아닌 문서 ────────────
def test_the_pay_statement_instructions_are_not_nominated_as_a_pay_stub():
    """급여명세서에 **대한** 안내문. "Pay Statement" 를 여러 번 인쇄하지만 명세서가
    아니다. 완전 일치에서는 수식어("... Template Instructions")가 곧 불일치다."""
    nom, reason = nominate_mod.nominate(
        (CONFIRM / "md_labor_paystatement_template_instructions.pdf").read_bytes())
    assert nom is None, nom


def test_the_paycheck_explainer_is_not_nominated_as_a_pay_stub():
    """"Understanding Your Pay Check/Stub" — 해설서다. 같은 방어선."""
    nom, reason = nominate_mod.nominate(
        (CONFIRM / "lcc_understanding_your_paycheck.pdf").read_bytes())
    assert nom is None, nom


# ── 세 말뭉치 스윕: 오지명 0 ─────────────────────────────────────────────
def _truth_pack(name: str) -> str | None:
    m = re.search(r"d\d\d_(.+)\.pdf$", name)
    return m.group(1) if m else None


def _truth_upload(name: str) -> str | None:
    m = re.match(r"up_\d+_([a-z_]+?)_(?:john|jane|sam|wording|labels|side|table|caption)",
                 name)
    return m.group(1) if m else None


#: confirm_raw 의 종류 진실. testdata/confirm_truth.json 의 `kind` 에서 옮겨 적었다:
#: filled_pay_stub → pay_stub, blank_form(고용 확인 서식) → employment_letter.
#: None 은 "다섯 종류의 어느 것도 아니다" — 해설서·안내문·빈 명세서 틀·패킷.
#: 이들이 지명되면 그것이 바로 이름 붙인 위험의 실현이므로, None 문서에 대한
#: 지명은 방향과 무관하게 오지명으로 센다.
_CONFIRM_TRUTH = {
    "ca_dlse_paystub_hourly.pdf": "pay_stub",
    "ca_dlse_paystub_piecerate.pdf": "pay_stub",
    "hi_ags_pay_statement_example_2021.pdf": "pay_stub",
    "ou_sample_check_stub.pdf": "pay_stub",
    "osu_sample_earnings_statement.pdf": "pay_stub",
    "bonita_certificated_check_sample.pdf": "pay_stub",
    "il_dol_day_labor_wage_notice_sample.pdf": "pay_stub",
    "lcc_understanding_your_paycheck.pdf": None,
    "md_labor_paystatement_template_instructions.pdf": None,
    "orangeusd_sample_paystub.pdf": None,
    "kcha_section8_doc21.pdf": None,
    "seattle_housing_employment_verification_blank.pdf": "employment_letter",
    "mnhousing_employment_verification_blank.pdf": "employment_letter",
    "wa_dshs_14252_employment_verification.pdf": "employment_letter",
}


def test_zero_misnominations_across_all_three_corpora():
    """오지명 0. 놓침(지명 없이 묻기)은 얼마든지 있어도 된다 — 그건 오늘까지의
    동작이다. 2026-07 측정: 64장 중 42장 지명(전부 정답), 22장 질문, 오지명 0."""
    mis = []
    nominated = asked = 0
    corpora = (
        [(PACK, _truth_pack)] + [(UPLOADS, _truth_upload)]
        + [(CONFIRM, lambda n: _CONFIRM_TRUTH.get(n))]
    )
    for corpus, truth_of in corpora:
        for pdf in sorted(corpus.glob("*.pdf")):
            nom, _reason = nominate_mod.nominate(pdf.read_bytes())
            if nom is None:
                asked += 1
                continue
            nominated += 1
            if nom["document_type"] != truth_of(pdf.name):
                mis.append((pdf.name, nom["document_type"], truth_of(pdf.name)))
    assert mis == [], mis
    # 스윕이 실제로 지명을 보고 있는지의 하한 — 표가 통째로 죽어 전부 질문이 되면
    # "오지명 0" 은 공허하게 참이 된다. 42 는 측정값이지 목표가 아니므로 하한만 건다.
    assert nominated >= 40, (nominated, asked)


# ── 엔드포인트: 종류 없이 올리면 지명이 응답에 실린다 ─────────────────────
@pytest.fixture(scope="module")
def client():
    from api.store import STORE

    STORE.warm()
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def _post(client, session, file_name, document_type=None):
    data = (UPLOADS / file_name).read_bytes()
    form = {} if document_type is None else {"document_type": document_type}
    return client.post("/api/upload",
                       files={"file": (file_name, data, "application/pdf")},
                       data=form, headers={"X-Session-Id": session})


def test_upload_without_a_type_reads_the_type_off_the_page(client, session):
    body = _post(client, session, "up_003_pay_stub_john_doe.pdf").json()
    assert body["document_type"] == "pay_stub"
    nom = body["nomination"]
    assert nom["matched_text"] == "Earnings Statement"
    assert nom["page"] == 1 and len(nom["bbox"]) == 4
    # 근거 문장은 화면 어디서든 접히지 않는 limits 로도 나간다.
    assert any("Earnings Statement" in line for line in body["limits"])
    # 지명돼도 읽기는 같은 기계를 탄다.
    assert body["located_count"] == 9


def test_upload_with_an_explicit_type_carries_no_nomination(client, session):
    """사람이 고른 종류는 지명이 아니다 — 지명 근거가 붙으면 그게 거짓말이다."""
    body = _post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    assert "nomination" not in body


def test_a_scan_without_a_type_falls_back_to_asking(client, session):
    r = _post(client, session, "up_006_pay_stub_sam_poe_scan.pdf")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "type_not_announced"
    assert "does not announce" in detail["detail"]


def test_an_unannounced_page_without_a_type_falls_back_to_asking(client, session):
    r = _post(client, session, "up_013_utility_bill_john_doe.pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "type_not_announced"


def test_size_and_pdf_checks_still_run_before_nomination(client, session):
    """지명은 PDF 를 여는 일이므로 바이트 검사가 먼저여야 한다."""
    r = client.post("/api/upload",
                    files={"file": ("x.pdf", b"GIF89a not a pdf", "application/pdf")},
                    data={}, headers={"X-Session-Id": session})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "not_a_pdf"
