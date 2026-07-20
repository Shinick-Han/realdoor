# -*- coding: utf-8 -*-
"""
test_uploads_file.py — 업로드들이 이루는 세션 자신의 파일, 그리고 사각형 읽기.

지키려는 성질 셋:

1. **팩은 한 글자도 움직이지 않는다.** 업로드 파일은 팩 세대 옆의 **추가 행**이고,
   팩 세대의 목록·리포트·계산은 업로드가 있든 없든 같아야 한다. 원래의 설계 거절이
   지키던 것이 팩의 무결성이었고, 이 파일은 그 무결성을 그대로 둔 채 벽만 걷는다.
2. **같은 기계.** 업로드 파일의 리포트·정정·되돌리기·패킷은 팩 세대와 같은 경로를
   탄다. 별도 기계를 만들면 반드시 한쪽만 고쳐지는 날이 온다.
3. **제안은 제안일 뿐.** 사각형 읽기는 아무것도 기록하지 않는다. 기록은 세입자가
   저장을 눌러 정정 경로를 거칠 때만 생기고, 그때도 기계의 page/bbox 는 얼어 있다.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
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


def post_upload(client, session, file_name, document_type):
    return client.post(
        "/api/upload",
        files={"file": (file_name, (UPLOADS / file_name).read_bytes(), "application/pdf")},
        data={"document_type": document_type},
        headers={"X-Session-Id": session},
    )


def open_file(client, session, *names_and_types):
    """올리고, 업로드 파일의 리포트를 돌려준다."""
    views = [post_upload(client, session, n, t).json() for n, t in names_and_types]
    rep = client.get(f"/api/report/{UPLOADS_HOUSEHOLD_ID}",
                     headers={"X-Session-Id": session}).json()
    return views, rep


def field_of(rep, document_id, name):
    for doc in rep["documents"]:
        if doc["document_id"] != document_id:
            continue
        for f in doc["fields"]:
            if f["field"] == name:
                return f
    return None


# ── 파일의 존재: 업로드가 있을 때만, 팩 옆의 추가 행으로 ─────────────────────
def test_the_uploads_file_appears_only_when_uploads_exist(client, session):
    h = {"X-Session-Id": session}
    before = client.get("/api/households", headers=h).json()["households"]
    assert all(r["household_id"] != UPLOADS_HOUSEHOLD_ID for r in before)
    # 업로드가 없으면 리포트도 없다 — 빈 파일을 지어내지 않는다.
    assert client.get(f"/api/report/{UPLOADS_HOUSEHOLD_ID}", headers=h).status_code == 404

    post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    after = client.get("/api/households", headers=h).json()["households"]
    mine = [r for r in after if r["household_id"] == UPLOADS_HOUSEHOLD_ID]
    assert len(mine) == 1
    assert mine[0]["document_count"] == 1
    assert mine[0]["file_kind"] == "uploads"
    # 팩 세대 행은 업로드 전과 완전히 같다.
    assert before == [r for r in after if r["household_id"] != UPLOADS_HOUSEHOLD_ID]


def test_a_pack_household_report_is_untouched_by_uploads(client, session):
    h = {"X-Session-Id": session}
    before = client.get("/api/report/HH-001", headers=h).json()
    post_upload(client, session, "up_001_application_summary_john_doe.pdf",
                "application_summary")
    after = client.get("/api/report/HH-001", headers=h).json()
    before.pop("generated_at"), after.pop("generated_at")
    # activity_log 는 업로드 이벤트를 정직하게 담으므로 여기서 뺀다 — 비교 대상은
    # 팩 세대의 **내용**이다.
    before.pop("activity_log"), after.pop("activity_log")
    assert before == after


def test_the_file_walks_the_same_machinery_as_a_pack_household(client, session):
    views, rep = open_file(
        client, session,
        ("up_001_application_summary_john_doe.pdf", "application_summary"),
        ("up_003_pay_stub_john_doe.pdf", "pay_stub"),
    )
    # 리포트의 뼈대가 팩 리포트와 같은 키를 갖는다: 계산·체크리스트·기권·평문 계층.
    for key in ("readiness_status", "calculations", "checklist", "abstentions",
                "plain", "confirmation", "activity_log", "citations"):
        assert key in rep, key
    assert rep["household_id"] == UPLOADS_HOUSEHOLD_ID
    # 체크리스트는 주최측 패턴의 기본 셋을 요구한다: 신청 요약서·급여명세서·고용확인서.
    listed = {i["item_id"] for i in rep["checklist"]}
    assert listed == {"CHK-APPLICATION-SUMMARY", "CHK-PAY-STUB", "CHK-EMPLOYMENT-LETTER"}


def test_the_required_set_is_the_organizers_own_conditional_pattern():
    """pack/evaluation/application_checklists.json 이 부호화한 패턴 그대로: 기본 셋은
    항상, benefit_letter 는 수당 서류가 있을 때, gig_income_corroboration 은 긱
    명세서가 있을 때. 팩 체크리스트에 이 파일의 행을 심는 것은 지어낸 목록이다."""
    from api.store import uploads_required_types
    from logic.household import load_pack_checklists

    assert UPLOADS_HOUSEHOLD_ID not in load_pack_checklists()
    base = ("application_summary", "pay_stub", "employment_letter")
    assert uploads_required_types([{"document_type": "pay_stub"}]) == base
    assert uploads_required_types([{"document_type": "benefit_letter"}]) == \
        base + ("benefit_letter",)
    assert uploads_required_types([{"document_type": "gig_statement"}]) == \
        base + ("gig_income_corroboration",)


def test_a_gig_statement_demands_corroboration_the_statement_cannot_supply(client, session):
    """HH-004 와 같은 요구가 심사위원 자신의 업로드에도 걸린다: 긱 명세서는 자기 작성
    문서라서 자기 소득의 교차 확인이 될 수 없다 — 팩 골드가 gig_statement 를 present 로
    두면서 gig_income_corroboration 을 missing 으로 남기는 그 규칙이다."""
    views, rep = open_file(client, session,
                           ("up_011_gig_statement_sam_poe.pdf", "gig_statement"))
    items = {i["item_id"]: i for i in rep["checklist"]}
    corroboration = items["CHK-GIG-INCOME-CORROBORATION"]
    assert corroboration["state"] == "missing"
    # 긱 명세서 자신은 present 로 실리되, 교차 확인 항목을 만족시키지 못한다.
    assert items["CHK-GIG-STATEMENT"]["state"] in ("present", "undatable")
    # 다음 걸음은 HH-004 레일과 같은 어휘다.
    assert "1099" in corroboration["action_for_renter"]
    # 팩 카드와 같은 방식의 규칙 인용.
    assert corroboration["required_because_rule_id"] == "CH-READINESS-001"
    assert any(r["code"] == "GIG_INCOME_UNCORROBORATED"
               for r in rep["review_reasons"])
    assert rep["readiness_status"] == "NEEDS_REVIEW"


def test_a_file_with_no_application_summary_has_no_name_and_still_reports(client, session):
    views, rep = open_file(client, session,
                           ("up_003_pay_stub_john_doe.pdf", "pay_stub"))
    h = {"X-Session-Id": session}
    row = [r for r in client.get("/api/households", headers=h).json()["households"]
           if r["household_id"] == UPLOADS_HOUSEHOLD_ID][0]
    # 이름은 신청 요약서에서만 온다. 없으면 없다 — 짓지 않는다. (급여명세서에도 이름
    # 필드가 있지만 그것은 고용주가 적은 이름이다.)
    assert row["applicant_name"] is None
    assert rep["readiness_status"] in ("READY_TO_REVIEW", "NEEDS_REVIEW")


# ── 정정 왕복: 같은 경로, 하위 계산 재계산, 되돌리기 ─────────────────────────
def test_an_inline_correction_on_an_upload_recomputes_and_undoes(client, session):
    views, rep = open_file(
        client, session,
        ("up_001_application_summary_john_doe.pdf", "application_summary"),
        ("up_003_pay_stub_john_doe.pdf", "pay_stub"),
    )
    stub = [v for v in views if v["document_type"] == "pay_stub"][0]
    doc_id = stub["upload_id"]
    h = {"X-Session-Id": session}
    read_value = field_of(rep, doc_id, "gross_pay")["value"]
    income_before = rep["annualized_income"]

    corrected = client.post("/api/confirm", json={
        "document_id": doc_id, "field": "gross_pay", "value": read_value + 1000,
    }, headers=h).json()
    f = field_of(corrected, doc_id, "gross_pay")
    assert f["evidence_kind"] == "corrected_by_renter"
    assert f["value"] == read_value + 1000
    # 하위 계산이 즉시 따라 움직인다 — 팩 세대의 정정과 같은 약속.
    assert corrected["annualized_income"] != income_before

    undone = client.post("/api/undo", json={
        "document_id": doc_id, "field": "gross_pay",
    }, headers=h).json()
    f = field_of(undone, doc_id, "gross_pay")
    assert f["evidence_kind"] == "extracted"
    assert f["value"] == read_value
    assert undone["annualized_income"] == income_before


def test_confirming_an_upload_value_marks_it_without_changing_it(client, session):
    views, rep = open_file(client, session,
                           ("up_003_pay_stub_john_doe.pdf", "pay_stub"))
    doc_id = views[0]["upload_id"]
    h = {"X-Session-Id": session}
    read_value = field_of(rep, doc_id, "gross_pay")["value"]
    confirmed = client.post("/api/confirm", json={
        "document_id": doc_id, "field": "gross_pay", "value": read_value,
    }, headers=h).json()
    f = field_of(confirmed, doc_id, "gross_pay")
    assert f["evidence_kind"] == "confirmed_by_renter"
    assert f["value"] == read_value
    assert confirmed["annualized_income"] == rep["annualized_income"]


# ── 사각형 읽기: 검증, 격리, 그리고 "제안은 커밋이 아니다" ───────────────────
def region_url(doc_id):
    return f"/api/document/{doc_id}/read-region"


@pytest.fixture
def stub_upload(client, session):
    view = post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    return {"session": session, "view": view}


def test_region_bounds_are_validated_against_the_page(client, stub_upload):
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    cases = [
        ({"page": 1, "box": [-5, 0, 100, 40]}, "box_outside_page"),
        ({"page": 1, "box": [0, 0, 700, 40]}, "box_outside_page"),
        ({"page": 1, "box": [10, 10, 12, 12]}, "box_too_small"),
        ({"page": 1, "box": [0, 0, 600, 700]}, "box_too_large"),
        ({"page": 9, "box": [10, 10, 100, 40]}, "bad_page"),
        ({"page": 1, "box": [10, 10, 100]}, "bad_box"),
        ({"page": 1, "box": ["a", "b", "c", "d"]}, "bad_box"),
    ]
    for payload, code in cases:
        r = client.post(region_url(doc_id), json=payload, headers=h)
        assert r.status_code == 400, (payload, r.status_code)
        assert r.json()["detail"]["code"] == code, payload


def test_a_region_in_another_session_is_invisible(client, stub_upload):
    other = client.post("/api/session").json()["session_id"]
    doc_id = stub_upload["view"]["upload_id"]
    r = client.post(region_url(doc_id), json={"page": 1, "box": [10, 10, 100, 40]},
                    headers={"X-Session-Id": other})
    assert r.status_code == 404


def test_an_unknown_document_is_a_404(client, session):
    r = client.post(region_url("UP-DEADBEEF"), json={"page": 1, "box": [10, 10, 100, 40]},
                    headers={"X-Session-Id": session})
    assert r.status_code == 404


def test_reading_a_region_commits_nothing(client, stub_upload):
    """제안은 입력칸을 채울 뿐이다. 읽기만으로는 리포트가 한 바이트도 달라지지 않는다."""
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    bbox = [f for f in stub_upload["view"]["fields"] if f["field"] == "gross_pay"][0]["bbox"]

    before = client.get(f"/api/report/{UPLOADS_HOUSEHOLD_ID}", headers=h).json()
    r = client.post(region_url(doc_id), json={"page": 1, "box": bbox, "field": "gross_pay"},
                    headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["could_read"] is True
    assert body["reading"] == 1386.0
    after = client.get(f"/api/report/{UPLOADS_HOUSEHOLD_ID}", headers=h).json()
    before.pop("generated_at"), after.pop("generated_at")
    assert before == after
    # 활동 기록에도 값은 없다: 읽기는 이벤트조차 남기지 않는다 (기록은 커밋의 일이다).
    assert all(e["action"] != "field_region_marked"
               for e in after["activity_log"]["events"])


def test_a_region_read_names_its_own_boundary(client, stub_upload):
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    bbox = [f for f in stub_upload["view"]["fields"] if f["field"] == "gross_pay"][0]["bbox"]
    body = client.post(region_url(doc_id), json={"page": 1, "box": bbox},
                       headers=h).json()
    assert "Nothing is saved until you choose to save it." in body["note"]


def test_a_box_that_caught_the_label_still_reads_the_value(client, stub_upload):
    """사람이 그리는 사각형에는 라벨이 걸쳐 들어오는 것이 보통이다. 합쳐 읽으면
    "GROSS PAY 1386.00" 이라 필드 문법에 안 맞지만, 조각 재시도가 값을 건진다."""
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    bbox = [f for f in stub_upload["view"]["fields"] if f["field"] == "gross_pay"][0]["bbox"]
    wide = [bbox[0] - 8, bbox[1] - 4, bbox[2] + 8, bbox[3] + 26]   # label row included
    body = client.post(region_url(doc_id),
                       json={"page": 1, "box": wide, "field": "gross_pay"},
                       headers=h).json()
    assert body["could_read"] is True
    assert body["reading"] == 1386.0


def test_an_unparseable_region_offers_no_suggestion(client, stub_upload):
    """필드의 문법에 맞지 않는 읽기는 제안이 아니다 — 입력칸만 남는다."""
    h = {"X-Session-Id": stub_upload["session"]}
    view = stub_upload["view"]
    doc_id = view["upload_id"]
    # person_name 라벨의 상자(텍스트)를 household_size(정수 문법)로 읽어 본다.
    name_box = [f for f in view["fields"] if f["field"] == "person_name"][0]["bbox"]
    body = client.post(region_url(doc_id),
                       json={"page": 1, "box": name_box, "field": "household_size"},
                       headers=h).json()
    assert body["could_read"] is False
    assert body["reading"] is None
    assert body["note"] == "We could not read that area — type what it says."


# ── 커밋된 사각형: 추가 주석, 얼어붙은 증거, 패킷의 문장 ─────────────────────
def test_a_committed_region_is_additive_and_never_moves_the_machine_box(client, stub_upload):
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    machine = [f for f in stub_upload["view"]["fields"] if f["field"] == "gross_pay"][0]
    marked = {"page": 1, "box": [354.0, 523.0, 430.0, 545.0],
              "machine_suggestion_shown": True}

    rep = client.post("/api/confirm", json={
        "document_id": doc_id, "field": "gross_pay", "value": 2500, "region": marked,
    }, headers=h).json()
    f = field_of(rep, doc_id, "gross_pay")
    assert f["region_marked_by_renter"]["page"] == 1
    assert f["region_marked_by_renter"]["box"] == [354.0, 523.0, 430.0, 545.0]
    assert f["region_marked_by_renter"]["machine_suggestion_shown"] is True
    # 계약 §1: 기계의 증거는 정정으로 움직이지 않는다.
    assert f["page"] == machine["page"]
    assert f["bbox"] == machine["bbox"]
    assert f["evidence_kind"] == "corrected_by_renter"
    assert f["certainty"] in ("high", "low", "abstain")

    # 활동 기록: 가리킴은 값 없이 남는다.
    events = [e for e in rep["activity_log"]["events"]
              if e["action"] == "field_region_marked"]
    assert len(events) == 1
    assert events[0]["field"] == "gross_pay"
    blob = json.dumps(events)
    assert "2500" not in blob and "354" not in blob

    # 되돌리면 주석도 함께 걷힌다 — 필드는 스냅샷과 완전히 같다.
    undone = client.post("/api/undo", json={
        "document_id": doc_id, "field": "gross_pay",
    }, headers=h).json()
    f = field_of(undone, doc_id, "gross_pay")
    assert "region_marked_by_renter" not in f
    assert f["evidence_kind"] == "extracted"


def test_a_committed_region_is_validated_like_the_read_path(client, stub_upload):
    h = {"X-Session-Id": stub_upload["session"]}
    doc_id = stub_upload["view"]["upload_id"]
    r = client.post("/api/confirm", json={
        "document_id": doc_id, "field": "gross_pay", "value": 2500,
        "region": {"page": 1, "box": [-10, 0, 5000, 40]},
    }, headers=h)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "box_outside_page"
    # 거절된 커밋은 아무것도 남기지 않는다.
    rep = client.get(f"/api/report/{UPLOADS_HOUSEHOLD_ID}", headers=h).json()
    f = field_of(rep, doc_id, "gross_pay")
    assert f["evidence_kind"] == "extracted"


def test_the_packet_cover_sheet_carries_the_pointed_region(client, session):
    views, rep = open_file(
        client, session,
        ("up_001_application_summary_john_doe.pdf", "application_summary"),
        ("up_003_pay_stub_john_doe.pdf", "pay_stub"),
    )
    stub = [v for v in views if v["document_type"] == "pay_stub"][0]
    h = {"X-Session-Id": session}
    client.post("/api/confirm", json={
        "document_id": stub["upload_id"], "field": "gross_pay", "value": 2500,
        "region": {"page": 1, "box": [354.0, 523.0, 430.0, 545.0],
                   "machine_suggestion_shown": True},
    }, headers=h)
    pk = client.post(f"/api/packet/{UPLOADS_HOUSEHOLD_ID}", headers=h)
    assert pk.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(pk.content))
    html = z.read("packet_summary.html").decode("utf-8")
    assert "machine read 1386; applicant corrected to 2500" in html
    assert "applicant pointed at page 1, region [354.0, 523.0, 430.0, 545.0]" in html
    assert "shown to the applicant as a suggestion" in html
    # 문서 원본은 메모리에서 패킷으로 직행한다.
    assert f"documents/{stub['file_name']}" in z.namelist()
    # 표지의 나머지 두 파일도 동결 enum 만 싣는다.
    from api import gate
    assert gate.scan(json.loads(z.read("readiness_report.json"))) == []


def test_two_uploads_with_the_same_name_both_survive_the_packet(client, session):
    """같은 파일을 두 번 올리면 파일 이름이 같은 문서 둘이 생긴다. ZIP 은 같은 경로
    둘을 조용히 받아 주므로, 갈라놓지 않으면 풀 때 한쪽이 다른 쪽을 덮어쓴다."""
    post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    pk = client.post(f"/api/packet/{UPLOADS_HOUSEHOLD_ID}",
                     headers={"X-Session-Id": session})
    names = zipfile.ZipFile(io.BytesIO(pk.content)).namelist()
    doc_entries = [n for n in names if n.startswith("documents/")]
    assert len(doc_entries) == 2
    assert len(set(doc_entries)) == 2


# ── 상한과 격리 ──────────────────────────────────────────────────────────────
def test_uploads_stop_at_the_ceiling_with_a_reason(client, session):
    for i in range(MAX_SESSION_UPLOADS):
        r = post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
        assert r.status_code == 200, i
    over = post_upload(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub")
    assert over.status_code == 400
    assert over.json()["detail"]["code"] == "session_upload_limit"
    h = {"X-Session-Id": session}
    row = [r for r in client.get("/api/households", headers=h).json()["households"]
           if r["household_id"] == UPLOADS_HOUSEHOLD_ID][0]
    assert row["document_count"] == MAX_SESSION_UPLOADS


def test_the_measured_path_never_sees_the_uploads_file():
    """측정 하네스는 core/logic 을 직접 부른다. 골드에서 세운 세대에 업로드 파일이
    섞일 수 있는 유일한 길은 골드나 체크리스트에 그 id 가 생기는 것이므로, 그 문이
    닫혀 있음을 여기서 잰다."""
    from logic.household import load_gold_households

    houses = load_gold_households()
    assert sorted(houses) == [f"HH-{n:03d}" for n in range(1, 7)]
    assert UPLOADS_HOUSEHOLD_ID not in houses


def test_the_uploads_report_passes_the_output_gate(client, session):
    from api import gate

    views, rep = open_file(
        client, session,
        ("up_002_application_summary_jane_roe_month_only.pdf", "application_summary"),
        ("up_005_pay_stub_jane_roe_expired.pdf", "pay_stub"),
    )
    assert gate.scan(rep) == []
    # 기한 지난 명세서·월 단위 날짜 — 기권과 검토 사유가 있어도 판정 어휘는 없다.
    assert rep["readiness_status"] in ("READY_TO_REVIEW", "NEEDS_REVIEW")
