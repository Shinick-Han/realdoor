# -*- coding: utf-8 -*-
"""
test_absence.py — 확인된 부재(confirmed absence)를 순서대로 눌러본다.

브리프의 경계 선언은 이 제품의 산출물을 "document readiness and human-review handoff"
라고 이름 붙이고, 참가자 가이드의 준비도 관행은 빠진 필수 증거를 NEEDS_REVIEW 로
보낸다. 그 인수인계에서 지금까지 빠져 있던 절반이 이것이다: 확인된 값
(`confirmed_by_renter`)은 있는데 **확인된 부재**가 없어서, 검토자는 "추출기가 못
읽었다" 와 "신청자가 페이지를 봤는데 정말 없다" 를 구분할 수 없었다.

여기서 재는 계약 넷:
  1. 부재 확인은 **enum 을 움직이지 않는다.** 필드는 certainty="abstain", value=null,
     evidence_kind="extracted" 그대로이고, 응답 전체의 evidence_kind 값은 여전히 동결된
     셋뿐이다 (contracts/CONTRACTS.md §1).
  2. 기록은 값 없이 남는다 — 동작·문서·필드명만. field_confirmed 와 같은 규율.
  3. 철회가 있다. 걷어내면 필드는 주석이 붙기 전과 완전히 같다.
  4. 패킷이 그 구분을 실어 나른다: 표지의 standing 이 "applicant confirmed: not shown
     on this document" 로, 기계만 못 읽은 부재("not read — the machine took no value
     here")와 **다른 문장**이 된다. README 는 0이 아닐 때만 그 수를 말한다.

팩은 159/159 로 기권이 없으므로(test_confirmation.py 의 같은 자리 참고) 부재는 여기서
만들어 넣거나, 실제로 부재가 생기는 유일한 입구인 업로드로 만든다. 재는 대상은 그날그날의
추출 성적이 아니라 `/api/absence` 의 계약이다.
"""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "eval") not in sys.path:
    sys.path.insert(0, str(ROOT / "eval"))

from api.store import STORE

HH = "HH-001"
DOC_APP = "HH-001-D01"
DOC_PAY = "HH-001-D02"

#: 표 레이아웃 코호트. 매니페스트(testdata/uploads_manifest.json)의 intended_fields 가
#: 다섯 필드뿐이다 — pay_frequency·net_pay·급여 기간은 **의도적으로 페이지에 없다**.
#: 즉 이 픽스처의 기권 일부는 진짜 부재이고, 그것이 이 기능이 다루는 사건이다.
#: (유의어·타이포그래피 코호트는 it-001~003 개선 뒤로 전부 읽힌다 — 2026-07-20 실측.)
UPLOAD_FIXTURE = ROOT / "testdata" / "uploads" / "up_024_pay_stub_table.pdf"

FROZEN_EVIDENCE_KINDS = {"extracted", "confirmed_by_renter", "corrected_by_renter"}
FROZEN_CERTAINTY = {"high", "low", "abstain"}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.app import app

    STORE.warm()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def session(client):
    sid = client.post("/api/session").json()["session_id"]
    yield sid
    STORE.delete(sid)


def _h(sid: str) -> dict:
    return {"X-Session-Id": sid}


def _report(client, sid: str) -> dict:
    r = client.get(f"/api/report/{HH}", headers=_h(sid))
    assert r.status_code == 200, r.text
    return r.json()


def _field(payload: dict, document_id: str, field_name: str) -> dict:
    for doc in payload.get("documents", []):
        if doc.get("document_id") != document_id:
            continue
        for f in doc.get("fields", []):
            if f.get("field") == field_name:
                return f
    raise AssertionError(f"{document_id}.{field_name} not in payload")


def _actions(report: dict) -> list[str]:
    return [e["action"] for e in report["activity_log"]["events"]]


def _make_absent(sid: str, document_id: str, field_name: str) -> None:
    """세션 사본에 기권을 만들어 넣는다 — test_confirmation.py 와 같은 수법, 같은 이유.

    core 의 기권 노트 문구는 측정 대상 문자열이므로 원문 그대로 옮겨 적는다.
    """
    for f in STORE.get(sid).views[document_id]["fields"]:
        if f["field"] == field_name:
            f["value"] = None
            f["certainty"] = "abstain"
            f["source_text"] = None
            f["notes"] = "no label for this field was found on the page"
            return
    raise AssertionError(f"{document_id}.{field_name} 가 뷰에 없다")


def _confirm_absence(client, sid, document_id, field_name):
    return client.post("/api/absence", headers=_h(sid),
                       json={"document_id": document_id, "field": field_name})


def _withdraw_absence(client, sid, document_id, field_name):
    return client.post("/api/absence/undo", headers=_h(sid),
                       json={"document_id": document_id, "field": field_name})


# ── 1. 확인해도 동결 enum 은 움직이지 않는다 ────────────────────────────────
def test_confirming_an_absence_moves_no_frozen_enum(client, session):
    _make_absent(session, DOC_APP, "address")

    r = _confirm_absence(client, session, DOC_APP, "address")
    assert r.status_code == 200, r.text
    report = r.json()

    f = _field(report, DOC_APP, "address")
    # 사람이 부재를 확인해도 기계의 읽기는 더 확실해지지 않는다.
    assert f["value"] is None
    assert f["certainty"] == "abstain"
    assert f["evidence_kind"] == "extracted"
    # 남는 것은 표시용 주석뿐이다.
    assert f["absence_confirmed_by_renter"] is True
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", f["absence_confirmed_on"])

    # 응답 전체를 훑어도 evidence_kind / certainty 는 동결된 값뿐이다 — 부재 확인은
    # enum 확장이 아니라 활동 기록 + 표시 상태라는 계약을 응답에서 직접 잰다.
    kinds = {f2.get("evidence_kind") for d in report["documents"] for f2 in d["fields"]}
    sureness = {f2.get("certainty") for d in report["documents"] for f2 in d["fields"]}
    assert kinds <= FROZEN_EVIDENCE_KINDS, kinds
    assert sureness <= FROZEN_CERTAINTY, sureness

    # 출력 게이트도 그대로 통과한다.
    from api import gate
    assert gate.scan(report) == []


def test_a_field_that_holds_a_value_has_no_absence_to_confirm(client, session):
    r = _confirm_absence(client, session, DOC_PAY, "gross_pay")
    assert r.status_code == 400
    assert "no absence to confirm" in r.text


def test_bad_requests_are_refused(client, session):
    assert client.post("/api/absence", headers=_h(session),
                       json={"field": "address"}).status_code == 400
    assert _confirm_absence(client, session, "HH-001-D99", "address").status_code == 404
    assert _confirm_absence(client, session, DOC_APP, "no_such_field").status_code == 404


# ── 2. 기록은 값 없이 남는다 ────────────────────────────────────────────────
def test_the_event_logs_the_field_and_document_and_nothing_else(client, session):
    _make_absent(session, DOC_APP, "address")
    report = _confirm_absence(client, session, DOC_APP, "address").json()

    assert _actions(report) == ["session_created", "field_absence_confirmed"]
    event = report["activity_log"]["events"][-1]
    assert event["document_id"] == DOC_APP
    assert event["field"] == "address"
    # 값도, 파일 이름도 없다 — 애초에 값이 없다는 사실이 확인의 내용이다.
    blob = json.dumps(report["activity_log"], ensure_ascii=False)
    assert ".pdf" not in blob
    assert "value" not in event


# ── 3. 철회 ────────────────────────────────────────────────────────────────
def test_withdrawing_leaves_the_field_exactly_as_before(client, session):
    _make_absent(session, DOC_APP, "address")
    before = _field(_report(client, session), DOC_APP, "address")

    _confirm_absence(client, session, DOC_APP, "address")
    r = _withdraw_absence(client, session, DOC_APP, "address")
    assert r.status_code == 200, r.text
    after = _field(r.json(), DOC_APP, "address")

    assert after == before, "철회 뒤의 필드는 주석이 붙기 전과 완전히 같아야 한다"
    assert "absence_confirmation_withdrawn" in _actions(r.json())


def test_withdrawing_nothing_is_a_404(client, session):
    assert _withdraw_absence(client, session, DOC_APP, "address").status_code == 404


def test_a_correction_clears_the_absence_mark(client, session):
    """부재를 확인해 둔 필드에 값을 채워 넣으면 두 주장이 충돌한다 — 새로 선 쪽이 이긴다."""
    _make_absent(session, DOC_APP, "address")
    _confirm_absence(client, session, DOC_APP, "address")

    filled = client.post("/api/confirm", headers=_h(session),
                         json={"document_id": DOC_APP, "field": "address",
                               "value": "12 Elm St"}).json()
    f = _field(filled, DOC_APP, "address")
    assert f["evidence_kind"] == "corrected_by_renter"
    assert "absence_confirmed_by_renter" not in f
    # 값이 선 뒤에는 철회할 부재 확인도 없다.
    assert _withdraw_absence(client, session, DOC_APP, "address").status_code == 404


# ── 4. 집계 ────────────────────────────────────────────────────────────────
def test_the_tally_counts_a_checked_absence_only_when_one_exists(client, session):
    # 부재 확인이 한 건도 없는 리포트에는 키 자체가 없다 — 패킷 JSON 은 바이트 단위로
    # 동결된 캡처와 대조되고(api/test_packet_summary.py), 0을 실으면 그 캡처가 깨진다.
    assert "confirmed_absent" not in _report(client, session)["confirmation"]

    _make_absent(session, DOC_APP, "address")
    before = _report(client, session)["confirmation"]
    report = _confirm_absence(client, session, DOC_APP, "address").json()
    tally = report["confirmation"]

    assert tally["confirmed_absent"] == 1
    # 확인된 부재는 not_read 의 부분집합이다: 기계가 읽지 못했다는 사실은 그대로다.
    assert tally["not_read"] == before["not_read"]
    assert tally["fields"] == (tally["confirmed"] + tally["corrected"]
                               + tally["not_confirmed"] + tally["not_read"])
    # 값의 확인 집계(seen_by_a_person)는 값을 본 사람 수 그대로다 — 의미를 섞지 않는다.
    assert tally["seen_by_a_person"] == before["seen_by_a_person"]


# ── 5. 패킷 ────────────────────────────────────────────────────────────────
def test_the_packet_tells_a_checked_absence_apart_from_a_machine_one(client, session):
    """표지의 standing 한 칸이 이 기능의 수신처다: 검토자가 "추출기가 못 읽었다" 와
    "사람이 봤는데 정말 없다" 를 같은 표에서 구분해 읽을 수 있어야 한다."""
    _make_absent(session, DOC_APP, "address")           # 확인할 부재
    _make_absent(session, DOC_APP, "application_date")  # 확인하지 않은 채 남길 부재
    _confirm_absence(client, session, DOC_APP, "address")

    r = client.post(f"/api/packet/{HH}", headers=_h(session))
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        html = z.read("packet_summary.html").decode("utf-8")
        readme = z.read("README.txt").decode("utf-8")
        log = json.loads(z.read("activity_log.json").decode("utf-8"))

    # 확인된 부재와 기계만 못 읽은 부재는 다른 문장을 받는다.
    assert "applicant confirmed: not shown on this document" in html
    assert "not read &mdash; the machine took no value here" in html
    # 기계의 원문 기록은 옮겨질 뿐 지워지지 않는다.
    assert "no label for this field was found on the page" in html
    # 집계 문단이 그 구분을 문장으로 말한다.
    assert "confirmed the document does not show it" in html
    # README 는 0이 아닐 때만 그 수를 말한다.
    assert "The applicant also checked 1 value(s) the machine could" in readme
    # 활동 기록에도 이벤트가 실린다 — 값 없이.
    assert "field_absence_confirmed" in [e["action"] for e in log["activity_log"]["events"]]

    # 판정 어휘는 한 글자도 늘어나지 않았다 (금지 목록은 가드에서 가져온다).
    import test_no_decision as guard
    tokens = {t.lower() for t in guard._KEY_SPLIT.split(html) if t}
    assert not (tokens & guard.BANNED_TOKENS)


def test_a_packet_with_no_absence_events_says_nothing_about_them(client, session):
    r = client.post(f"/api/packet/{HH}", headers=_h(session))
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        html = z.read("packet_summary.html").decode("utf-8")
        readme = z.read("README.txt").decode("utf-8")
    assert "applicant confirmed: not shown" not in html
    assert "The applicant also checked" not in readme


# ── 6. 업로드 경로 — 부재가 실제로 생기는 입구 ─────────────────────────────
def test_an_absent_field_on_an_upload_can_be_checked_and_unchecked(client, session):
    """팩은 159/159 라 부재가 없다. 부재는 업로드에서 생기고, 업로드는 세대에 합류하지
    않으므로 응답은 리포트가 아니라 갱신된 업로드 뷰다."""
    with UPLOAD_FIXTURE.open("rb") as fh:
        up = client.post("/api/upload", headers=_h(session),
                         data={"document_type": "pay_stub"},
                         files={"file": (UPLOAD_FIXTURE.name, fh, "application/pdf")})
    assert up.status_code == 200, up.text
    view = up.json()
    assert view["abstained_count"] > 0, "이 픽스처는 기권을 내도록 만들어졌다 (manifest)"

    absent = next(f["field"] for f in view["fields"]
                  if f["value"] is None and f["certainty"] == "abstain")
    uid = view["upload_id"]

    checked = _confirm_absence(client, session, uid, absent)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["upload_id"] == uid, "업로드에 대한 응답은 업로드 뷰다"
    f = next(x for x in body["fields"] if x["field"] == absent)
    assert f["absence_confirmed_by_renter"] is True
    assert f["value"] is None and f["certainty"] == "abstain"

    # 세션 활동 기록에 값 없이 남는다 — 패킷의 activity_log.json 이 이것을 실어 나른다.
    report = _report(client, session)
    assert "field_absence_confirmed" in _actions(report)

    undone = _withdraw_absence(client, session, uid, absent)
    assert undone.status_code == 200, undone.text
    f = next(x for x in undone.json()["fields"] if x["field"] == absent)
    assert "absence_confirmed_by_renter" not in f
