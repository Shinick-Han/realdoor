# -*- coding: utf-8 -*-
"""
test_remove_upload.py — 올린 문서 한 장 걷어내기.

고정하는 성질 네 가지: (1) 걷어낸 문서의 것은 전부 사라진다 — 뷰·바이트·정정·
부재 확인, 이어지는 이미지 요청은 404. (2) 다른 문서의 것은 한 글자도 움직이지
않는다. (3) 업로드 상한 한 자리가 실제로 돌아온다. (4) 업로드 파일은 남은 문서로
재계산되고, 마지막 한 장이 걷히면 파일 자체가 목록과 리포트에서 사라진다.
활동 기록에는 값 없는 `document_removed` (문서 id 만)가 남는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.app import app  # noqa: E402
from api.store import MAX_SESSION_UPLOADS, STORE, UPLOADS_HOUSEHOLD_ID  # noqa: E402

UPLOADS = ROOT / "testdata" / "uploads"


@pytest.fixture(scope="module")
def client():
    STORE.warm()
    return TestClient(app)


@pytest.fixture
def session(client):
    return client.post("/api/session").json()["session_id"]


def upload(client, session, file_name, document_type):
    r = client.post("/api/upload",
                    files={"file": (file_name, (UPLOADS / file_name).read_bytes(),
                                    "application/pdf")},
                    data={"document_type": document_type},
                    headers={"X-Session-Id": session})
    assert r.status_code == 200, r.text
    return r.json()


def test_removal_takes_only_that_document_and_all_of_it(client, session):
    kept = upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    gone = upload(client, session, "up_007_employment_letter_john_doe.pdf",
                  "employment_letter")
    headers = {"X-Session-Id": session}

    # 남는 문서에 사람의 흔적을 남겨 둔다 — 걷어내기가 이것을 건드리면 안 된다.
    r = client.post("/api/confirm", headers=headers,
                    json={"document_id": kept["upload_id"], "field": "person_name",
                          "value": "John Doe"})
    assert r.status_code == 200

    r = client.delete("/api/upload/" + gone["upload_id"], headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["removed"] is True and body["uploads_remaining"] == 1

    # (1) 걷어낸 문서: 이미지도 리포트의 자리도 없다.
    assert client.get("/api/upload/" + gone["upload_id"] + "/page/1.png",
                      headers=headers).status_code == 404
    rep = client.get("/api/report/" + UPLOADS_HOUSEHOLD_ID, headers=headers).json()
    ids = [d["document_id"] for d in rep["documents"]]
    assert gone["upload_id"] not in ids and kept["upload_id"] in ids

    # (2) 다른 문서의 확인은 그대로 서 있다.
    kept_doc = [d for d in rep["documents"] if d["document_id"] == kept["upload_id"]][0]
    name = [f for f in kept_doc["fields"] if f["field"] == "person_name"][0]
    assert name["evidence_kind"] == "confirmed_by_renter"

    # 활동 기록: 값 없는 이벤트, 문서 id 만.
    events = rep["activity_log"]["events"]
    removed = [e for e in events if e["action"] == "document_removed"]
    assert len(removed) == 1
    assert removed[0]["document_id"] == gone["upload_id"]
    assert set(removed[0]) <= {"n", "action", "what_happened", "document_id"}


def test_removing_the_last_document_makes_the_file_disappear(client, session):
    only = upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    headers = {"X-Session-Id": session}
    rows = client.get("/api/households", headers=headers).json()["households"]
    assert any(r["household_id"] == UPLOADS_HOUSEHOLD_ID for r in rows)

    assert client.delete("/api/upload/" + only["upload_id"],
                         headers=headers).json()["uploads_remaining"] == 0

    rows = client.get("/api/households", headers=headers).json()["households"]
    assert not any(r["household_id"] == UPLOADS_HOUSEHOLD_ID for r in rows)
    assert client.get("/api/report/" + UPLOADS_HOUSEHOLD_ID,
                      headers=headers).status_code == 404


def test_removal_frees_a_seat_under_the_upload_ceiling(client, session):
    headers = {"X-Session-Id": session}
    first = upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    for _ in range(MAX_SESSION_UPLOADS - 1):
        upload(client, session, "up_004_pay_stub_john_doe_mismatch.pdf", "pay_stub")
    # 상한: 일곱 번째는 거절.
    r = client.post("/api/upload",
                    files={"file": ("x.pdf",
                                    (UPLOADS / "up_003_pay_stub_john_doe.pdf").read_bytes(),
                                    "application/pdf")},
                    data={"document_type": "pay_stub"}, headers=headers)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "session_upload_limit"
    # 한 장을 걷어내면 자리가 실제로 돌아온다.
    client.delete("/api/upload/" + first["upload_id"], headers=headers)
    again = upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    assert again["upload_id"]


def test_an_unknown_or_pack_document_cannot_be_removed(client, session):
    headers = {"X-Session-Id": session}
    assert client.delete("/api/upload/UP-DOESNOTEXIST",
                         headers=headers).status_code == 404
    # 팩 문서는 세입자가 올린 것이 아니므로 걷어낼 수 없다.
    assert client.delete("/api/upload/HH-001-D01", headers=headers).status_code == 404
