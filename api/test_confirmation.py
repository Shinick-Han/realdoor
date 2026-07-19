# -*- coding: utf-8 -*-
"""
test_confirmation.py — 확인·정정·취소를 **순서대로 눌러본다**.

이 제품에서 지금까지 나온 결함 셋은 전부 같은 모양이었다: 컨트롤 하나를 따로 눌러보면
멀쩡하고, 순서를 밟아야 보인다. 세 번째가 이번 것이다 —

  결함 3: 브리프 표제("human-confirmed profile")와 Required Build 01("Require confirmation
          or correction before reuse")이 요구하는 **확인**이 구현되지 않았다.
          `confirmed_by_renter` 는 enum·주석·화면 라벨에 이름만 있고, 그 값을 만드는 코드가
          리포지토리에 한 줄도 없었다. 세입자가 아무것도 확인하지 않아도 추출값이 그대로
          연소득 계산과 한도 비교에 재사용됐다.

여기서 검사하는 것은 API 계약이다. 한 엔드포인트(`/api/confirm`)가 값이 같은지 다른지에
따라 **두 결과**를 내는지, 그리고 그 셋을 이어 밟았을 때 상태가 어디에도 새지 않는지.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.store import STORE, same_value

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
    sid = client.post("/api/session").json()["session_id"]
    yield sid
    STORE.delete(sid)


def _h(sid: str) -> dict:
    return {"X-Session-Id": sid}


def _report(client, sid: str) -> dict:
    r = client.get(f"/api/report/{HH}", headers=_h(sid))
    assert r.status_code == 200, r.text
    return r.json()


def _field(report: dict, document_id: str, field_name: str) -> dict:
    for doc in report.get("documents", []):
        if doc.get("document_id") != document_id:
            continue
        for f in doc.get("fields", []):
            if f.get("field") == field_name:
                return f
    raise AssertionError(f"{document_id}.{field_name} not in report")


def _send(client, sid, document_id, field_name, value, together=False):
    body = {"document_id": document_id, "field": field_name, "value": value}
    if together:
        body["together"] = True
    return client.post("/api/confirm", headers=_h(sid), json=body)


def _undo(client, sid, document_id, field_name):
    return client.post("/api/undo", headers=_h(sid),
                       json={"document_id": document_id, "field": field_name})


def _actions(report: dict) -> list[str]:
    return [e["action"] for e in report["activity_log"]["events"]]


# ── 한 엔드포인트, 두 결과 ──────────────────────────────────────────────────
def test_sending_back_the_same_value_is_a_confirmation(client, session):
    """고치지 않고 그대로 보내면 확인이다. **이것이 없던 기능이다.**"""
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    assert read["evidence_kind"] == "extracted"

    after = _send(client, session, DOC_PAY, "gross_pay", read["value"])
    assert after.status_code == 200, after.text
    f = _field(after.json(), DOC_PAY, "gross_pay")
    assert f["evidence_kind"] == "confirmed_by_renter"


def test_a_confirmation_changes_nothing_but_the_mark(client, session):
    """확인은 사실을 바꾸지 않는다. 값도, 확신도, 그 아래 계산도 그대로다.

    이 테스트가 지키는 것은 문구가 아니라 의미다. 확인이 `certainty` 를 올리거나 숫자를
    움직이면, 화면의 "확인해도 값은 바뀌지 않습니다" 가 거짓이 된다.
    """
    before = _report(client, session)
    read = _field(before, DOC_PAY, "gross_pay")

    after = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()
    f = _field(after, DOC_PAY, "gross_pay")

    assert f["value"] == read["value"]
    assert f["certainty"] == read["certainty"]
    assert after["calculations"] == before["calculations"]
    assert after["readiness_status"] == before["readiness_status"]
    assert [r["code"] for r in after.get("review_reasons", [])] == \
           [r["code"] for r in before.get("review_reasons", [])]


def test_sending_back_a_different_value_is_still_a_correction(client, session):
    after = _send(client, session, DOC_PAY, "gross_pay", 2280).json()
    f = _field(after, DOC_PAY, "gross_pay")
    assert f["evidence_kind"] == "corrected_by_renter"
    assert f["value"] == 2280


def test_the_form_sends_text_and_that_is_still_a_confirmation(client, session):
    """입력칸은 언제나 문자열을 돌려준다.

    미리 채운 값을 손대지 않은 사람이 `"1,408"` 을 보내는데 그것이 정정으로 기록되면,
    확인이라는 상태는 화면에서 영원히 도달할 수 없다. 표기가 아니라 값으로 비교해야 한다.
    """
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    typed = f"{read['value']:,}"           # 화면이 보여주는 그대로: 쉼표가 들어간다
    after = _send(client, session, DOC_PAY, "gross_pay", typed).json()
    assert _field(after, DOC_PAY, "gross_pay")["evidence_kind"] == "confirmed_by_renter"
    assert _field(after, DOC_PAY, "gross_pay")["value"] == read["value"]


@pytest.mark.parametrize("submitted,extracted,expected", [
    (1408, 1408.0, True),
    ("1,408", 1408.0, True),
    (" 1408 ", 1408.0, True),
    ("1408.00", 1408.0, True),
    (1409, 1408.0, False),
    ("Jordan Ellis", "Jordan Ellis", True),
    ("jordan ellis", "Jordan Ellis", False),   # 애매하면 정정이 안전한 쪽이다
    (None, None, False),                        # 읽히지 않은 것은 확인 대상이 아니다
])
def test_same_value_absorbs_notation_and_nothing_else(submitted, extracted, expected):
    if submitted is None:
        assert same_value(submitted, extracted) is True   # 값으로는 같지만
        return
    assert same_value(submitted, extracted) is expected


def test_a_value_that_was_not_read_cannot_be_confirmed(client, session):
    """기권한 필드에 "사람이 확인했다"는 표시가 붙으면, 하필 사람 손이 가장 필요한
    자리에서 그 표시가 거짓이 된다. 값을 채워 넣으라고 거절한다."""
    # 이 테스트는 원래 HH-002-D01 의 address 를 짚었다 — 팩에서 실제로 기권이 나던 자리다.
    # 그리고 예고한 대로 동작했다: OCR 이 떨어뜨린 단어 공백을 복원하게 되면서 그 자리가
    # 읽히기 시작했고, 테스트는 조용히 통과하는 대신 없어진 전제를 알려주며 실패했다.
    # 지금 팩에는 기권이 한 건도 없다(159/159).
    #
    # 그래서 기권을 여기서 만든다. 재는 대상은 추출 성적이 아니라 `/api/confirm` 의 계약이고,
    # 계약을 재는 데 그날그날의 추출 성적이 끼어들 이유가 없다. 팩에 다시 기권이 생기든
    # 안 생기든 이 검사는 같은 것을 잰다.
    blank = (DOC_APP, "address")
    for field in STORE.get(session).views[blank[0]]["fields"]:
        if field["field"] == blank[1]:
            field["value"] = None
            field["certainty"] = "abstain"
            field["source_text"] = None
            break
    else:
        raise AssertionError(f"{blank[0]}.{blank[1]} 가 뷰에 없다")

    assert _field(_report(client, session), *blank)["value"] is None

    assert _send(client, session, blank[0], blank[1], None).status_code == 400
    assert _field(_report(client, session), *blank)["evidence_kind"] == "extracted"

    # 대신 값을 채워 넣는 것은 언제나 가능하다 — 그것은 정정이다.
    filled = _send(client, session, blank[0], blank[1], "12 Elm St").json()
    assert _field(filled, *blank)["evidence_kind"] == "corrected_by_renter"


def test_an_empty_box_is_neither_a_confirmation_nor_a_correction(client, session):
    r = _send(client, session, DOC_PAY, "gross_pay", "   ")
    assert r.status_code == 400
    assert _field(_report(client, session), DOC_PAY, "gross_pay")["evidence_kind"] == "extracted"


# ── 순서: 확인 → 정정 → 취소 ───────────────────────────────────────────────
def test_confirm_then_correct_then_undo_lands_on_the_extracted_value(client, session):
    """세 컨트롤을 이어 밟는다. 하나씩 누르면 전부 통과하는 순서다.

    확인이 먼저 걸리므로 정정 시점의 '추출된 원값' 은 확인 표시가 붙은 값이다. 취소가
    거기서 멈추면 필드는 확인된 상태로 남고, 화면은 "추출된 값으로 돌아갔다" 고 말한다.
    """
    read = _field(_report(client, session), DOC_PAY, "gross_pay")

    step1 = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()
    assert _field(step1, DOC_PAY, "gross_pay")["evidence_kind"] == "confirmed_by_renter"

    step2 = _send(client, session, DOC_PAY, "gross_pay", 2280).json()
    assert _field(step2, DOC_PAY, "gross_pay")["evidence_kind"] == "corrected_by_renter"

    step3 = _undo(client, session, DOC_PAY, "gross_pay")
    assert step3.status_code == 200, step3.text
    final = _field(step3.json(), DOC_PAY, "gross_pay")

    assert final["value"] == read["value"]
    assert final["certainty"] == read["certainty"]
    assert final["evidence_kind"] == "extracted", (
        "한 번의 취소가 확인 표시까지 걷어내야 한다 — 확인은 추출 상태가 아니다")


def test_undo_after_a_confirmation_alone_withdraws_the_confirmation(client, session):
    """확인만 하고 취소하면? 이 조합은 확인 기능이 생기기 전까지 정의돼 있지 않았다.

    정의: **확인도 걷힌다.** 잘못 누른 확인을 되돌릴 길이 없으면, 확인은 세입자가 철회할
    수 없는 주장이 된다. 값은 애초에 바뀐 적이 없으므로 그대로다.
    """
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    _send(client, session, DOC_PAY, "gross_pay", read["value"])

    r = _undo(client, session, DOC_PAY, "gross_pay")
    assert r.status_code == 200, r.text
    f = _field(r.json(), DOC_PAY, "gross_pay")
    assert f["evidence_kind"] == "extracted"
    assert f["value"] == read["value"]
    assert "confirmation_withdrawn" in _actions(r.json())


def test_correcting_back_to_the_read_value_is_recorded_as_a_confirmation(client, session):
    """고쳤다가 원래 값을 도로 적어 보내면 정정이 아니라 확인이다.

    남는 상태가 `corrected_by_renter` 인데 값이 기계가 읽은 값과 같으면, 리포트는 사람이
    고치지 않은 것을 고쳤다고 말하게 된다.
    """
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    _send(client, session, DOC_PAY, "gross_pay", 2280)
    back = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()

    f = _field(back, DOC_PAY, "gross_pay")
    assert f["evidence_kind"] == "confirmed_by_renter"
    assert f["value"] == read["value"]
    assert f["certainty"] == read["certainty"], "확인은 확신을 올리지 않는다"
    # 그리고 그 상태에서 한 번 더 취소하면 추출 상태로 완전히 돌아간다.
    assert _field(_undo(client, session, DOC_PAY, "gross_pay").json(),
                  DOC_PAY, "gross_pay")["evidence_kind"] == "extracted"


def test_a_confirmation_does_not_revive_an_undone_correction(client, session):
    """결함 1 의 회귀 테스트를 확인 쪽으로 한 번 더 밟는다.

    정정 → 취소 → **다른 필드 확인**. 취소한 값이 세 번째 단계에서 되살아나면 안 된다.
    """
    _send(client, session, DOC_PAY, "gross_pay", 2280)
    _undo(client, session, DOC_PAY, "gross_pay")

    size = _field(_report(client, session), DOC_APP, "household_size")
    final = _send(client, session, DOC_APP, "household_size", size["value"]).json()

    revived = _field(final, DOC_PAY, "gross_pay")
    assert revived["value"] != 2280
    assert revived["evidence_kind"] == "extracted"
    assert _field(final, DOC_APP, "household_size")["evidence_kind"] == "confirmed_by_renter"
    assert "RENTER_CORRECTION_NOT_USED" not in [r["code"] for r in final.get("review_reasons", [])]


def test_confirming_one_field_leaves_the_others_alone(client, session):
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    after = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()

    marked = [(d["document_id"], f["field"]) for d in after["documents"] for f in d["fields"]
              if f["evidence_kind"] != "extracted"]
    assert marked == [(DOC_PAY, "gross_pay")]


def test_a_confirmation_does_not_leak_into_another_session(client):
    a = client.post("/api/session").json()["session_id"]
    b = client.post("/api/session").json()["session_id"]
    try:
        read = _field(_report(client, a), DOC_PAY, "gross_pay")
        _send(client, a, DOC_PAY, "gross_pay", read["value"])
        assert _field(_report(client, b), DOC_PAY, "gross_pay")["evidence_kind"] == "extracted"
    finally:
        STORE.delete(a)
        STORE.delete(b)


# ── 세는 일 ─────────────────────────────────────────────────────────────────
def test_the_report_counts_what_a_person_has_seen(client, session):
    report = _report(client, session)
    start = report["confirmation"]
    assert start["confirmed"] == 0 and start["corrected"] == 0
    assert start["fields"] == start["not_confirmed"] + start["not_read"]

    read = _field(report, DOC_PAY, "gross_pay")
    one = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()["confirmation"]
    assert one["confirmed"] == 1
    assert one["not_confirmed"] == start["not_confirmed"] - 1
    assert one["seen_by_a_person"] == 1

    two = _send(client, session, DOC_APP, "household_size", 9).json()["confirmation"]
    assert (two["confirmed"], two["corrected"], two["seen_by_a_person"]) == (1, 1, 2)

    back = _undo(client, session, DOC_PAY, "gross_pay").json()["confirmation"]
    assert back["confirmed"] == 0 and back["seen_by_a_person"] == 1


def test_the_count_never_asks_for_a_value_that_was_not_read(client, session):
    """읽히지 않은 필드는 '아직 확인 안 함' 과 다른 칸에 센다. 합치면 화면이 도달할 수
    없는 목표를 제시하게 된다."""
    tally = _report(client, session)["confirmation"]
    assert tally["fields"] == (tally["confirmed"] + tally["corrected"]
                               + tally["not_confirmed"] + tally["not_read"])


# ── 기록: Session.log() 를 아무도 읽지 않던 상태의 회귀 테스트 ────────────
def test_the_activity_log_reaches_the_report(client, session):
    """`Session.log()` 는 처음부터 있었지만 아무도 읽지 않았다.

    브리프 CONSENT AND CORRECTION: "log consent, actions, and rule versions". 기록만 하고
    어디로도 내보내지 않는 로그는 그 요구의 절반이다.
    """
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    _send(client, session, DOC_PAY, "gross_pay", read["value"])
    _send(client, session, DOC_APP, "household_size", 9)
    report = _undo(client, session, DOC_APP, "household_size").json()

    log = report["activity_log"]
    assert _actions(report) == ["session_created", "field_confirmed", "field_corrected",
                                "correction_undone"]
    assert log["counts"]["field_confirmed"] == 1
    assert log["ruleset_version"] == report["ruleset_version"]
    assert log["engine_version"] == report["engine_version"]


def test_confirming_together_is_recorded_as_a_different_action(client, session):
    """한 문서의 남은 값을 한 번에 확인한 것과 하나씩 본 것은 **표시가 같고 기록이 다르다.**

    `evidence_kind` 는 둘 다 `confirmed_by_renter` 다 — 사람이 확인한 것은 맞기 때문이다.
    그러나 어떻게 확인했는지를 기록이 지우면, 패킷을 읽는 사람은 실제보다 강한 확인을
    보게 된다.
    """
    report = _report(client, session)
    read = _field(report, DOC_APP, "person_name")
    _send(client, session, DOC_APP, "person_name", read["value"], together=True)
    after = _report(client, session)

    assert _field(after, DOC_APP, "person_name")["evidence_kind"] == "confirmed_by_renter"
    assert "fields_confirmed_together" in _actions(after)
    assert "field_confirmed" not in _actions(after)


def test_the_log_never_carries_a_value_or_a_document_name(client, session):
    """브리프: "log consent, actions, and rule versions - **not raw document contents**"."""
    _send(client, session, DOC_PAY, "gross_pay", 987654)
    _undo(client, session, DOC_PAY, "gross_pay")
    client.post("/api/ask", headers=_h(session),
                json={"question": "What is the frozen threshold?", "household_id": HH})
    report = _report(client, session)

    blob = json.dumps(report["activity_log"], ensure_ascii=False)
    assert "987654" not in blob, "세입자가 적어 넣은 값이 기록에 실렸다"
    assert ".pdf" not in blob, "파일 이름이 기록에 실렸다"
    assert "What is the frozen threshold?" not in blob, "질문 원문이 기록에 실렸다"


# ── 패킷 ────────────────────────────────────────────────────────────────────
def test_the_packet_carries_the_log_and_not_the_document_text(client, session):
    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    _send(client, session, DOC_PAY, "gross_pay", read["value"])

    r = client.post(f"/api/packet/{HH}", headers=_h(session))
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
        assert "activity_log.json" in names
        log = json.loads(z.read("activity_log.json").decode("utf-8"))
        readme = z.read("README.txt").decode("utf-8")

    assert log["confirmation"]["confirmed"] == 1
    assert [e["action"] for e in log["activity_log"]["events"]] == \
           ["session_created", "field_confirmed"]
    # 문서 원문은 기록에 없다. (PDF 원본은 세입자 자신의 패킷이므로 documents/ 에 따로 있다.)
    blob = json.dumps(log, ensure_ascii=False)
    assert str(read["value"]) not in blob
    assert "1 value(s) confirmed as read correctly" in readme


def test_the_packet_says_how_much_is_still_unchecked(client, session):
    """패킷은 이 프로필이 화면을 떠나 남이 읽는 파일이 되는 지점이다. 무엇이 아직 사람의
    눈을 거치지 않았는지는 그 사람에게도 전달돼야 한다."""
    r = client.post(f"/api/packet/{HH}", headers=_h(session))
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        readme = z.read("README.txt").decode("utf-8")
    tally = _report(client, session)["confirmation"]
    assert f"{tally['not_confirmed']} value(s) still carry only the machine reading" in readme


# ── 판정 어휘는 한 글자도 늘어나지 않았다 ──────────────────────────────────
def test_the_new_surface_still_passes_the_output_gate(client, session):
    """확인 기능이 붙은 응답도 게이트를 그대로 통과해야 한다. 게이트는 미들웨어이므로
    200 이 돌아온 것 자체가 통과의 증거지만, 여기서는 그것을 명시적으로 다시 훑는다."""
    from api import gate

    read = _field(_report(client, session), DOC_PAY, "gross_pay")
    report = _send(client, session, DOC_PAY, "gross_pay", read["value"]).json()
    assert gate.scan(report) == []
