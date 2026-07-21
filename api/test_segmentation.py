# -*- coding: utf-8 -*-
"""
test_segmentation.py — 결합 문서(한 PDF 안 여러 종류)의 페이지별 분절.

여기서 고정하는 성질:
  * 제목이 바뀌는 자리에서 하위 문서가 갈린다 (급여명세서 → 재직증명서 → 수급 통지서
    = 세 하위 문서).
  * 제목 없는 페이지는 앞 문서를 잇는다 (제목 있는 1페이지 + 제목 없는 2페이지 =
    한 문서, 두 페이지).
  * 각 필드의 페이지 번호는 원본 파일 기준이다 (2페이지에서 읽은 값은 page==2).
  * 제로-오답: 첫 페이지가 스스로를 밝히지 못하면 보이는 기본값(pay_stub)으로 읽되,
    맞는 라벨이 없으면 값을 지어내지 않고 기권한다.
  * 사람이 종류를 고르면 파일 전체가 그 한 종류의 하나의 문서로 읽힌다.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import upload as upload_mod  # noqa: E402
from api.app import app  # noqa: E402

UPLOADS = ROOT / "testdata" / "uploads"


def _combine(*names: str) -> bytes:
    """여러 단일 페이지 PDF 를 한 파일로 잇는다 — 결합 문서의 합성 표본."""
    dst = pdfium.PdfDocument.new()
    for name in names:
        src = pdfium.PdfDocument((UPLOADS / name).read_bytes())
        dst.import_pages(src, list(range(len(src))))
    buf = io.BytesIO()
    dst.save(buf)
    return buf.getvalue()


# ── 분절 규칙: 순수 함수 수준에서 ────────────────────────────────────────────
def test_titled_pages_split_into_one_sub_document_each():
    """급여명세서 + 재직증명서 + 수급 통지서 = 세 하위 문서, 각자의 페이지·종류·근거."""
    combo = _combine(
        "up_003_pay_stub_john_doe.pdf",
        "up_007_employment_letter_john_doe.pdf",
        "up_009_benefit_letter_jane_roe.pdf",
    )
    views = upload_mod.read_document_file(combo, "combo.pdf")
    assert [v["document_type"] for v in views] == [
        "pay_stub", "employment_letter", "benefit_letter"]
    assert [(v["page_start"], v["page_end"]) for v in views] == [(1, 1), (2, 2), (3, 3)]
    # 각 하위 문서의 지명 근거는 자기 페이지를 가리킨다.
    assert [v["nomination"]["page"] for v in views] == [1, 2, 3]
    # 필드의 페이지 번호는 원본 파일 기준으로 되돌려져 있다.
    assert {f["page"] for f in views[1]["fields"] if f.get("page")} == {2}
    assert {f["page"] for f in views[2]["fields"] if f.get("page")} == {3}


def test_a_titleless_page_continues_the_current_sub_document():
    """제목 있는 1페이지 + 제목 없는 2페이지 = 한 문서, 두 페이지 (2쪽짜리 명세서 규칙).

    2페이지에는 지명하는 제목이 없으므로 새 문서를 열지 않고 앞의 급여명세서를 잇는다.
    """
    combo = _combine("up_003_pay_stub_john_doe.pdf", "up_013_utility_bill_john_doe.pdf")
    views = upload_mod.read_document_file(combo, "cont.pdf")
    assert len(views) == 1
    assert views[0]["document_type"] == "pay_stub"
    assert views[0]["page_start"] == 1 and views[0]["page_end"] == 2
    assert [p["page"] for p in views[0]["pages"]] == [1, 2]


def test_an_unrecognised_first_page_reads_under_the_visible_default_without_wrong_values():
    """제로-오답: 제목 없는 첫 페이지는 보이는 기본값 pay_stub 으로 읽되, pay_stub 라벨이
    없으므로 값을 지어내지 않는다 — 조용한 오답이 아니라 보이는 가정 + 전부 기권."""
    data = (UPLOADS / "up_013_utility_bill_john_doe.pdf").read_bytes()
    views = upload_mod.read_document_file(data, "u.pdf")
    assert len(views) == 1
    v = views[0]
    assert v["document_type"] == upload_mod.DEFAULT_DOCUMENT_TYPE == "pay_stub"
    assert v["assumed_type"] is True
    assert "nomination" not in v
    assert v["located_count"] == 0            # 지어낸 값이 없다


def test_an_explicit_type_reads_the_whole_file_as_one_document():
    """사람이 종류를 고르면 페이지별 분절보다 우선 — 파일 전체가 하나의 그 종류 문서다."""
    combo = _combine(
        "up_003_pay_stub_john_doe.pdf",
        "up_007_employment_letter_john_doe.pdf",
    )
    views = upload_mod.read_document_file(combo, "combo.pdf", explicit_type="pay_stub")
    assert len(views) == 1
    assert views[0]["document_type"] == "pay_stub"
    assert views[0]["page_start"] == 1 and views[0]["page_end"] == 2
    assert [p["page"] for p in views[0]["pages"]] == [1, 2]


# ── 엔드포인트 + 세대: 결합 문서가 올바르게 목록·체크리스트로 이어진다 ────────
@pytest.fixture(scope="module")
def client():
    from api.store import STORE

    STORE.warm()
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def test_endpoint_returns_all_sub_documents_and_they_join_the_uploads_file(client, session):
    combo = _combine(
        "up_003_pay_stub_john_doe.pdf",
        "up_007_employment_letter_john_doe.pdf",
        "up_009_benefit_letter_jane_roe.pdf",
    )
    H = {"X-Session-Id": session}
    body = client.post("/api/upload",
                       files={"file": ("combo.pdf", combo, "application/pdf")},
                       data={}, headers=H).json()
    assert body["file"]["sub_count"] == 3
    assert [s["document_type"] for s in body["sub_documents"]] == [
        "pay_stub", "employment_letter", "benefit_letter"]
    # 세 하위 문서가 업로드 파일의 세 문서로 목록에 선다.
    rows = client.get("/api/households", headers=H).json()["households"]
    up_row = [r for r in rows if r["file_kind"] == "uploads"][0]
    assert up_row["document_count"] == 3
    # 체크리스트는 실제 종류 집합을 본다: benefit_letter 하위 문서가 그 항목을 present 로.
    rep = client.get("/api/report/YOUR-UPLOADS", headers=H).json()
    states = {i["item_id"]: i["state"] for i in rep["checklist"]}
    assert states.get("CHK-BENEFIT-LETTER") == "present"
    assert states.get("CHK-EMPLOYMENT-LETTER") == "present"


def test_retype_re_reads_only_that_sub_document(client, session):
    """결합 파일에서 한 장의 종류를 바꿔도 나머지 지명은 살아 있다 (item 3)."""
    combo = _combine(
        "up_003_pay_stub_john_doe.pdf",
        "up_009_benefit_letter_jane_roe.pdf",
    )
    H = {"X-Session-Id": session}
    body = client.post("/api/upload",
                       files={"file": ("combo.pdf", combo, "application/pdf")},
                       data={}, headers=H).json()
    subs = body["sub_documents"]
    assert [s["document_type"] for s in subs] == ["pay_stub", "benefit_letter"]
    # 1페이지(pay_stub)를 employment_letter 로 다시 읽는다.
    first = subs[0]["upload_id"]
    rt = client.post(f"/api/upload/{first}/retype",
                     json={"document_type": "employment_letter"}, headers=H).json()
    types = [s["document_type"] for s in rt["sub_documents"]]
    assert types == ["employment_letter", "benefit_letter"]   # 2페이지는 그대로
    # 다시 읽은 하위 문서는 사람이 골랐으므로 지명/가정 표시가 없다.
    changed = [s for s in rt["sub_documents"] if s["upload_id"] == first][0]
    assert "nomination" not in changed and not changed.get("assumed_type")


def test_a_combined_file_that_would_exceed_the_upload_ceiling_is_refused_atomically(client):
    """상한을 넘기는 결합 파일은 하나도 저장하지 않고 통째로 거절된다."""
    from api.store import MAX_SESSION_UPLOADS

    session = client.post("/api/session").json()["session_id"]
    H = {"X-Session-Id": session}
    names = ["up_003_pay_stub_john_doe.pdf", "up_007_employment_letter_john_doe.pdf",
             "up_009_benefit_letter_jane_roe.pdf"]
    combo = _combine(*(names * 3))   # 9 sub-documents > ceiling (6)
    assert 9 > MAX_SESSION_UPLOADS
    r = client.post("/api/upload",
                    files={"file": ("big.pdf", combo, "application/pdf")},
                    data={}, headers=H)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "session_upload_limit"
    # 아무것도 저장되지 않았다.
    rows = client.get("/api/households", headers=H).json()["households"]
    assert not [r for r in rows if r["file_kind"] == "uploads"]
