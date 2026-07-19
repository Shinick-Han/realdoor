# -*- coding: utf-8 -*-
"""
test_session_lifecycle.py — 정정 취소와 세션 삭제를 **눌러본다**.

두 결함 모두 코드를 읽어서는 보이지 않았고, 순서대로 눌러봐야 보였다.
그래서 이 파일의 테스트는 단위 호출이 아니라 **사람이 밟는 순서**를 밟는다.

  결함 1: 정정 → 취소 → 다른 정정. 취소한 값이 세 번째 단계에서 되살아났다.
          취소가 클라이언트에서만 일어나고 서버 세션은 정정된 채로 남았기 때문.
  결함 2: 세션 삭제 → 이후 요청. UI가 조용히 새 세션을 만들어 픽스처를 다시 적재했고,
          화면은 "이후 요청은 404" 라고 말하고 있었다.

여기서 검사하는 것은 API 계약이다. UI 쪽 순서는 ui/tools/live-check.mjs 가 브라우저로 밟는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.store import STORE

HH = "HH-004"
DOC_PAY = "HH-004-D02"
DOC_APP = "HH-004-D01"


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.app import app

    STORE.warm()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def session(client):
    """정정이 세션 사이로 새지 않도록 테스트마다 새 세션."""
    sid = client.post("/api/session").json()["session_id"]
    yield sid
    STORE.delete(sid)


def _headers(sid: str) -> dict:
    return {"X-Session-Id": sid}


def _field(report: dict, document_id: str, field_name: str):
    for doc in report.get("documents", []):
        if doc.get("document_id") != document_id:
            continue
        for f in doc.get("fields", []):
            if f.get("field") == field_name:
                return f
    raise AssertionError(f"{document_id}.{field_name} not in report")


def _codes(report: dict) -> list[str]:
    return [r.get("code") for r in report.get("review_reasons", [])]


def _confirm(client, sid, document_id, field_name, value) -> dict:
    r = client.post("/api/confirm", headers=_headers(sid),
                    json={"document_id": document_id, "field": field_name, "value": value})
    assert r.status_code == 200, r.text
    return r.json()


def _undo(client, sid, document_id, field_name):
    return client.post("/api/undo", headers=_headers(sid),
                       json={"document_id": document_id, "field": field_name})


# ── 결함 1: 취소가 세션을 오염시켰다 ────────────────────────────────────────
def test_undo_restores_the_extracted_value(client, session):
    """취소 후 필드는 기계가 읽은 값과 그 evidence_kind 로 돌아간다."""
    before = _field(client.get(f"/api/report/{HH}", headers=_headers(session)).json(),
                    DOC_PAY, "gross_pay")
    assert before["evidence_kind"] == "extracted"

    _confirm(client, session, DOC_PAY, "gross_pay", 2280)
    after = _undo(client, session, DOC_PAY, "gross_pay")
    assert after.status_code == 200, after.text

    restored = _field(after.json(), DOC_PAY, "gross_pay")
    assert restored["value"] == before["value"]
    assert restored["certainty"] == before["certainty"]
    assert restored["evidence_kind"] == "extracted"


def test_undo_leaves_the_session_as_if_the_correction_never_happened(client, session):
    """취소한 세션의 리포트 == 아무 정정도 없던 세션의 리포트.

    화면은 "back to the extracted values" 라고 말한다. 그 문장이 사실이려면
    필드 하나가 아니라 **거기서 파생된 것 전부**가 돌아와 있어야 한다.
    """
    clean_sid = client.post("/api/session").json()["session_id"]
    try:
        clean = client.get(f"/api/report/{HH}", headers=_headers(clean_sid)).json()
    finally:
        STORE.delete(clean_sid)

    _confirm(client, session, DOC_PAY, "gross_pay", 2280)
    undone = _undo(client, session, DOC_PAY, "gross_pay").json()

    assert _codes(undone) == _codes(clean)
    assert undone["readiness_status"] == clean["readiness_status"]
    assert undone["calculations"] == clean["calculations"]


def test_the_demo_sequence_correct_undo_correct_something_else(client, session):
    """감사에서 재현된 순서 그대로. 이것이 결함 1 의 회귀 테스트다.

    1) D02 의 gross_pay 를 2280 으로 정정
    2) 취소
    3) D01 의 household_size 를 2 로 정정
    → 취소한 2280 은 3단계 리포트 어디에도 남아 있으면 안 된다.
    """
    _confirm(client, session, DOC_PAY, "gross_pay", 2280)
    _undo(client, session, DOC_PAY, "gross_pay")
    final = _confirm(client, session, DOC_APP, "household_size", 2)

    revived = _field(final, DOC_PAY, "gross_pay")
    assert revived["value"] != 2280, "the undone correction came back on the next correction"
    assert revived["evidence_kind"] == "extracted"

    # 취소된 정정이 만들어냈던 "당신의 정정은 사용되지 않았습니다" 도 함께 사라져야 한다.
    assert "RENTER_CORRECTION_NOT_USED" not in _codes(final)

    # 3단계에서 실제로 한 정정은 살아 있어야 한다.
    kept = _field(final, DOC_APP, "household_size")
    assert kept["value"] == 2
    assert kept["evidence_kind"] == "corrected_by_renter"


def test_undo_touches_only_the_field_it_names(client, session):
    """취소는 그 정정 하나만 되돌린다. 다른 정정을 함께 날리면 안 된다."""
    _confirm(client, session, DOC_APP, "household_size", 2)
    _confirm(client, session, DOC_PAY, "gross_pay", 2280)
    report = _undo(client, session, DOC_PAY, "gross_pay").json()

    assert _field(report, DOC_APP, "household_size")["value"] == 2
    assert _field(report, DOC_APP, "household_size")["evidence_kind"] == "corrected_by_renter"
    assert _field(report, DOC_PAY, "gross_pay")["evidence_kind"] == "extracted"


def test_undo_goes_back_to_the_extracted_value_not_the_previous_correction(client, session):
    """같은 필드를 두 번 고쳐도 취소는 기계가 읽은 값까지 돌아간다."""
    original = _field(client.get(f"/api/report/{HH}", headers=_headers(session)).json(),
                      DOC_PAY, "gross_pay")["value"]
    _confirm(client, session, DOC_PAY, "gross_pay", 2280)
    _confirm(client, session, DOC_PAY, "gross_pay", 2500)
    report = _undo(client, session, DOC_PAY, "gross_pay").json()

    assert _field(report, DOC_PAY, "gross_pay")["value"] == original


def test_undo_without_a_correction_is_a_404_not_a_silent_success(client, session):
    r = _undo(client, session, DOC_PAY, "gross_pay")
    assert r.status_code == 404


def test_undo_needs_a_session(client):
    r = client.post("/api/undo", json={"document_id": DOC_PAY, "field": "gross_pay"})
    assert r.status_code == 400
    r = client.post("/api/undo", headers=_headers("deadbeefdead"),
                    json={"document_id": DOC_PAY, "field": "gross_pay"})
    assert r.status_code == 404


def test_undo_rejects_an_incomplete_payload(client, session):
    assert client.post("/api/undo", headers=_headers(session),
                       json={"document_id": DOC_PAY}).status_code == 400
    assert client.post("/api/undo", headers=_headers(session),
                       json={"field": "gross_pay"}).status_code == 400


# ── 결함 2: 삭제 후에도 답이 나왔다 ─────────────────────────────────────────
def test_every_route_that_reads_the_session_404s_after_deletion(client):
    """화면 문구: "requests that follow return 404 because there is nothing left to
    answer with." 문구가 route 하나에만 맞으면 그건 맞는 게 아니다."""
    sid = client.post("/api/session").json()["session_id"]
    assert client.get(f"/api/report/{HH}", headers=_headers(sid)).status_code == 200

    deleted = client.delete(f"/api/session/{sid}")
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True

    h = _headers(sid)
    assert client.get("/api/households", headers=h).status_code == 404
    assert client.get(f"/api/report/{HH}", headers=h).status_code == 404
    assert client.post(f"/api/packet/{HH}", headers=h).status_code == 404
    assert client.post("/api/confirm", headers=h,
                       json={"document_id": DOC_PAY, "field": "gross_pay",
                             "value": 1}).status_code == 404
    assert client.post("/api/undo", headers=h,
                       json={"document_id": DOC_PAY, "field": "gross_pay"}).status_code == 404
    assert client.get(f"/api/document/{DOC_PAY}/page/1.png", headers=h).status_code == 404
    assert client.get(f"/api/document/{DOC_PAY}/overlay/1", headers=h).status_code == 404
    assert client.post("/api/ask", headers=h, json={"question": "hi"}).status_code == 404


def test_deletion_does_not_hand_out_a_replacement_session(client):
    """삭제된 id 로 온 요청은 404 여야 한다 — 새 세션을 만들어 답해서는 안 된다.

    이것이 결함 2 의 서버쪽 계약이다. UI 쪽 짝은 live-check.mjs 가 브라우저에서 밟는다.
    """
    sid = client.post("/api/session").json()["session_id"]
    client.delete(f"/api/session/{sid}")
    before = STORE.session_count
    r = client.get(f"/api/report/{HH}", headers=_headers(sid))
    assert r.status_code == 404
    assert STORE.session_count == before, "a request with a deleted id created a session"


def test_deleting_one_session_leaves_the_others_alone(client):
    keep = client.post("/api/session").json()["session_id"]
    drop = client.post("/api/session").json()["session_id"]
    try:
        client.delete(f"/api/session/{drop}")
        assert client.get(f"/api/report/{HH}", headers=_headers(keep)).status_code == 200
    finally:
        STORE.delete(keep)


def test_deleting_a_session_leaves_the_pack_on_disk_untouched(client):
    """세션을 지우는 것이지 원본 팩을 지우는 것이 아니다."""
    from api.store import DOCS

    before = sorted(p.name for p in DOCS.glob("*.pdf"))
    assert before, "no pack documents found — the check would pass vacuously"

    sid = client.post("/api/session").json()["session_id"]
    client.post("/api/confirm", headers=_headers(sid),
                json={"document_id": DOC_PAY, "field": "gross_pay", "value": 2280})
    client.delete(f"/api/session/{sid}")

    assert sorted(p.name for p in DOCS.glob("*.pdf")) == before


def test_deleting_twice_reports_the_second_one_as_nothing_deleted(client):
    sid = client.post("/api/session").json()["session_id"]
    assert client.delete(f"/api/session/{sid}").json()["deleted"] is True
    assert client.delete(f"/api/session/{sid}").json()["deleted"] is False


def test_a_correction_does_not_leak_into_another_session(client):
    """세션 격리. 한 사람의 정정이 다른 세션의 리포트에 보이면 안 된다."""
    a = client.post("/api/session").json()["session_id"]
    b = client.post("/api/session").json()["session_id"]
    try:
        _confirm(client, a, DOC_PAY, "gross_pay", 2280)
        other = client.get(f"/api/report/{HH}", headers=_headers(b)).json()
        assert _field(other, DOC_PAY, "gross_pay")["evidence_kind"] == "extracted"
    finally:
        STORE.delete(a)
        STORE.delete(b)
