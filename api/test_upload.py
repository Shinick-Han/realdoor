# -*- coding: utf-8 -*-
"""
test_upload.py — 업로드 경로.

여기서 지키려는 성질은 정확도가 아니라 **실패의 모양**이다. 측정해 보면 손실은 전부
기권이고 오답은 0건인데, 그 성질은 조용히 깨질 수 있다. 그래서 이 파일은
"못 읽었다"가 오류도 추측도 아닌 명시적 기권으로 나오는지를 본다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import upload as upload_mod  # noqa: E402
from api.app import app  # noqa: E402
from core.extract import EXPECTED_FIELDS, infer_document_type  # noqa: E402

UPLOADS = ROOT / "testdata" / "uploads"
MANIFEST = ROOT / "testdata" / "uploads_manifest.json"


@pytest.fixture(scope="module")
def client():
    # `TestClient(app)` 를 그냥 만들면 startup 이벤트가 돌지 않아 STORE 가 비어 있고,
    # /api/report 가 404 를 낸다. 업로드만 보는 테스트에는 티가 안 나지만
    # "업로드가 세대를 건드리지 않는다"를 보려면 세대가 있어야 한다.
    from api.store import STORE

    STORE.warm()
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def post(client, session, file_name, document_type=None, data=None, content_type="application/pdf"):
    payload = data if data is not None else (UPLOADS / file_name).read_bytes()
    form = {} if document_type is None else {"document_type": document_type}
    return client.post(
        "/api/upload",
        files={"file": (file_name, payload, content_type)},
        data=form,
        headers={"X-Session-Id": session},
    )


# ── 문서 종류는 반드시 받아야 한다 ────────────────────────────────────────
def test_the_type_list_comes_from_the_extractor_not_a_copy():
    """선택지가 하드코딩 사본이면 추출기와 갈라지는 날이 온다."""
    assert upload_mod.supported_document_types() == sorted(EXPECTED_FIELDS.keys())


def test_a_file_named_anything_else_has_no_inferable_type():
    """이 함정이 이 엔드포인트 설계의 이유다. 사라지면 알아야 한다."""
    assert infer_document_type("my_pay_stub_march.pdf") == "unknown"
    assert infer_document_type(UPLOADS / "up_003_pay_stub_john_doe.pdf") == "unknown"


def test_upload_without_a_document_type_is_refused(client, session):
    r = post(client, session, "up_003_pay_stub_john_doe.pdf", document_type=None)
    assert r.status_code == 422  # FastAPI: 필수 폼 필드 누락


def test_an_unsupported_type_says_so_instead_of_reading_nothing(client, session):
    r = post(client, session, "up_013_utility_bill_john_doe.pdf", "utility_bill")
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "document_type_unsupported"
    # 우리가 읽을 줄 아는 것을 실제로 말해 준다
    assert "pay_stub" in detail["detail"]


# ── PDF 만, 그리고 크기 상한 ──────────────────────────────────────────────
def test_a_non_pdf_is_refused_on_its_bytes_not_its_name(client, session):
    """MIME 은 클라이언트가 붙이는 값이다. 매직바이트가 진짜 검사다."""
    r = post(client, session, "not_really.pdf", "pay_stub",
             data=b"GIF89a this is not a pdf", content_type="application/pdf")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "not_a_pdf"


def test_an_empty_file_is_refused(client, session):
    r = post(client, session, "empty.pdf", "pay_stub", data=b"")
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "empty_file"


def test_a_file_over_the_limit_is_refused(client, session):
    oversized = b"%PDF-" + b"0" * (upload_mod.MAX_UPLOAD_BYTES + 1)
    r = post(client, session, "big.pdf", "pay_stub", data=oversized)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "file_too_large"


# ── 추출 경로 ─────────────────────────────────────────────────────────────
def test_a_text_layer_document_is_read_from_its_text(client, session):
    body = post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    assert body["extraction_path"] == "text_layer"
    assert body["text_layer_present"] is True
    assert body["located_count"] == 9
    assert body["read_nothing"] is False
    assert body["file_name"] == "up_003_pay_stub_john_doe.pdf"


def test_a_scan_falls_through_to_ocr_instead_of_abstaining_on_everything(client, session):
    """이 전환은 자동이 아니다. 엔드포인트가 판단하지 않으면 스캔본은 전부 기권한다."""
    body = post(client, session, "up_006_pay_stub_sam_poe_scan.pdf", "pay_stub").json()
    assert body["extraction_path"] == "ocr"
    assert body["text_layer_present"] is False
    assert body["located_count"] > 0


def test_every_field_has_a_real_box_or_no_value_at_all(client, session):
    """값이 있으면 근거 상자가 있고, 상자가 없으면 값도 없다."""
    body = post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    for field in body["fields"]:
        if field["certainty"] == "abstain":
            assert field["value"] is None
            assert field["bbox"] is None
        else:
            assert field["bbox"] is not None
            assert len(field["bbox"]) == 4


# ── 못 읽었을 때의 모양 ───────────────────────────────────────────────────
@pytest.mark.parametrize("file_name,document_type", [
    ("up_023_pay_stub_side_by_side.pdf", "pay_stub"),
    ("up_024_pay_stub_table.pdf", "pay_stub"),
    ("up_016_pay_stub_wording_total_earnings.pdf", "pay_stub"),
])
def test_a_document_we_cannot_read_abstains_explicitly(client, session, file_name, document_type):
    """빈 목록이 아니라 **기권한 필드 목록**이 와야 한다.

    화면이 "아무것도 확신할 수 없었다"고 말하려면 말할 대상이 있어야 한다. 필드가
    통째로 없으면 화면은 빈 카드를 그리고, 그건 버그처럼 보인다.
    """
    body = post(client, session, file_name, document_type).json()
    assert body["read_nothing"] is True
    assert body["located_count"] == 0
    assert len(body["fields"]) == len(EXPECTED_FIELDS[document_type])
    assert all(f["certainty"] == "abstain" for f in body["fields"])
    assert all(f["notes"] for f in body["fields"])


def test_the_response_names_the_limit_the_screen_has_to_repeat(client, session):
    """추출은 필드 간 산술을 하지 않는다. up_004 는 시급×시간 ≠ 총액인데 total 은 high 다.
    그 한계를 화면이 말할 수 있도록 서버가 실어 보내는지 본다."""
    body = post(client, session, "up_004_pay_stub_john_doe_mismatch.pdf", "pay_stub").json()
    gross = [f for f in body["fields"] if f["field"] == "gross_pay"][0]
    assert gross["certainty"] == "high"          # 산술 검증은 여기서 일어나지 않는다
    assert any("against each other" in text for text in body["limits"])


# ── 오답 0건 ──────────────────────────────────────────────────────────────
def test_no_uploaded_document_produces_a_wrong_value(client, session):
    """26장 전체. 손실은 전부 기권이어야 하고 틀린 값은 하나도 없어야 한다."""
    docs = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
    wrong: list[str] = []
    for doc in docs:
        if doc["document_type"] not in EXPECTED_FIELDS:
            continue  # 읽을 줄 모르는 종류는 400 으로 거절된다 (위에서 따로 본다)
        sid = client.post("/api/session").json()["session_id"]
        body = post(client, sid, doc["file_name"], doc["document_type"]).json()
        got = {f["field"]: f for f in body["fields"]}
        for name, want in doc["intended_fields"].items():
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                continue
            value = field["value"]
            same = (abs(float(want) - float(value)) < 1e-6
                    if isinstance(want, (int, float)) and isinstance(value, (int, float))
                    else str(want).strip() == str(value).strip())
            if not same:
                wrong.append(f"{doc['file_name']}:{name} want {want!r} got {value!r}")
    assert wrong == [], "업로드 경로에서 오답이 생겼다: " + "; ".join(wrong)


# ── 세션 안에만 있다 ──────────────────────────────────────────────────────
def test_an_upload_never_touches_the_extraction_cache(client, session, tmp_path):
    from api.store import CACHE

    before = set(CACHE.glob("*.json")) if CACHE.exists() else set()
    post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    after = set(CACHE.glob("*.json")) if CACHE.exists() else set()
    assert before == after


def test_an_upload_does_not_join_the_household(client, session):
    """세대 편입은 요구되지 않았고, 하려면 근거 없는 추측이 필요하다."""
    before = client.get("/api/report/HH-001", headers={"X-Session-Id": session}).json()
    post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    after = client.get("/api/report/HH-001", headers={"X-Session-Id": session}).json()
    assert [d["document_id"] for d in before["documents"]] == \
           [d["document_id"] for d in after["documents"]]
    assert before["calculations"] == after["calculations"]


def test_only_the_most_recent_upload_is_kept(client, session):
    from api.store import STORE

    first = post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    second = post(client, session, "up_001_application_summary_john_doe.pdf",
                  "application_summary").json()
    s = STORE.get(session)
    assert list(s.uploads) == [second["upload_id"]]
    assert list(s.upload_bytes) == [second["upload_id"]]
    assert first["upload_id"] not in s.uploads


def test_the_page_image_comes_from_memory_and_dies_with_the_session(client):
    sid = client.post("/api/session").json()["session_id"]
    body = post(client, sid, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    url = f"/api/upload/{body['upload_id']}/page/1.png"

    ok = client.get(url, headers={"X-Session-Id": sid})
    assert ok.status_code == 200
    assert ok.content.startswith(b"\x89PNG")

    client.delete(f"/api/session/{sid}")
    gone = client.get(url, headers={"X-Session-Id": sid})
    assert gone.status_code == 404


def test_an_upload_logs_the_action_but_never_the_contents(client, session):
    from api.store import STORE

    post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    events = [e for e in STORE.get(session).events if e["action"] == "document_uploaded"]
    assert len(events) == 1
    blob = json.dumps(events, ensure_ascii=False)
    assert "John Doe" not in blob
    assert "up_003" not in blob          # 파일 이름도 남기지 않는다


def test_uploading_needs_a_session(client):
    r = client.post(
        "/api/upload",
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        data={"document_type": "pay_stub"},
    )
    assert r.status_code == 400
