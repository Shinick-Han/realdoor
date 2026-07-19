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
    # up_023 (side-by-side) used to belong here. It is now read by `_side_by_side_value`.
    # up_024 (earnings table) stays, and is *meant* to stay: its overtime row means the
    # GROSS PAY column holds two numbers, so no rule may pick one. See test below.
    ("up_024_pay_stub_table.pdf", "pay_stub"),
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


# ── 배치 인지: 읽되, 애매하면 절대 읽지 않는다 ───────────────────────────
def test_a_side_by_side_stub_is_read_from_the_same_line(client, session):
    """값이 라벨 오른쪽 같은 줄에 있는, 세상에서 제일 흔한 급여명세서 배치."""
    body = post(client, session, "up_023_pay_stub_side_by_side.pdf", "pay_stub").json()
    got = {f["field"]: f["value"] for f in body["fields"]}
    assert got["gross_pay"] == 1386.00
    assert got["net_pay"] == 1121.66
    assert got["person_name"] == "John Doe"
    assert body["located_count"] == 9


def test_a_caption_layout_is_read_from_the_line_above(client, session):
    """라벨이 값 '아래' 캡션으로 붙은 배치."""
    body = post(client, session, "up_025_benefit_letter_caption_layout.pdf", "benefit_letter").json()
    got = {f["field"]: f["value"] for f in body["fields"]}
    assert got["monthly_benefit"] == 868.00
    assert got["person_name"] == "Sam Poe"


def test_a_table_row_never_pairs_a_header_with_a_neighbouring_number(client, session):
    """이게 이 작업의 핵심 안전 장치다.

    up_024 의 GROSS PAY 열에는 숫자가 둘(정규 1120.00, 초과근무 210.00) 있다. 어느 쪽도
    '그 문서의 총지급액'이 아니다 -- 실제 총액은 1330.00 이다. 규칙이 하나를 고르면 그건
    맞춘 게 아니라 우연이고, 다음 문서에서 틀린다. 그래서 표 배치는 풀지 않고 기권한다.

    이 테스트는 '아직 못 읽는다'는 기록이 아니라 **읽어서는 안 된다**는 요구사항이다.
    """
    body = post(client, session, "up_024_pay_stub_table.pdf", "pay_stub").json()
    for field in body["fields"]:
        assert field["certainty"] == "abstain", (
            f"표 배치에서 {field['field']} 에 값을 만들어냈다: {field['value']!r} — "
            "열 안에 후보가 둘인데 하나를 골랐다는 뜻이다"
        )


def test_prose_that_opens_with_a_label_is_not_read_as_a_value(client, session):
    """'PAY DATE has not been assigned yet' 같은 산문은 라벨-값 쌍이 아니다.

    person_name/address 는 어떤 문자열이든 통과시키므로 파싱이 이걸 걸러주지 못한다.
    오직 기하 -- 단어 간격이 열 간격인가 낱말 간격인가 -- 만이 구분할 수 있다.
    """
    from core.extract import SIDE_BY_SIDE_MIN_GAP, _side_by_side_value, LineBoxConvention
    from core.extract import Word

    def word(text, x0, x1, bold=False, size=7.5):
        return Word(text=text, x0=x0, x1=x1, baseline=100.0, glyph_bottom=98.0,
                    glyph_top=108.0, size=size, bold=bold, page=1)

    label = [word("EMPLOYEE", 40.0, 81.7, bold=True)]
    # 낱말 간격(2pt)으로 이어지는 산문 -> 읽지 않는다
    prose = [word("has", 83.7, 95.0, size=10.0), word("not", 97.0, 108.0, size=10.0)]
    assert _side_by_side_value(
        label + prose, [label], 0, float("inf"), "person_name", LineBoxConvention(), True
    ) is None
    # 열 간격(68pt)으로 떨어진 값 -> 읽는다
    value = [word("John", 150.0, 171.7, size=10.0), word("Doe", 174.5, 192.8, size=10.0)]
    read = _side_by_side_value(
        label + value, [label], 0, float("inf"), "person_name", LineBoxConvention(), True
    )
    assert read is not None and read["value"] == "John Doe"
    assert value[0].x0 - label[0].x1 >= SIDE_BY_SIDE_MIN_GAP


def test_the_caption_rule_never_steals_the_row_above_in_a_top_down_form(client, session):
    """위를 보는 규칙이 일반 양식에서 한 칸씩 밀려 읽으면 페이지 전체가 오답이 된다.

    막아주는 건 소유권 검사다: 위에 있는 그 값에는 *자기 라벨*이 이미 붙어 있다.
    팩 문서 전체(157/159)가 그대로라는 게 이 검사가 작동한다는 증거다.
    """
    from core.extract import _claimed_from_above, Word

    def run(x0, baseline):
        return [Word(text="2026-07-03", x0=x0, x1=x0 + 51, baseline=baseline,
                     glyph_bottom=baseline, glyph_top=baseline + 10, size=10.0,
                     bold=False, page=1)]

    # 위쪽 15pt 에 자기 라벨이 있는 값 -> 이미 임자가 있다
    assert _claimed_from_above([(115.0, 40.0)], run(40.0, 100.0)) is True
    # 캡션 배치: 값 위에는 아무 라벨도 없다 -> 임자가 없다
    assert _claimed_from_above([(89.0, 40.0)], run(40.0, 100.0)) is False


# ── 낯선 문구는 기권이 아니라 "low" 로 돌아온다 ──────────────────────────
def test_a_synonym_label_is_read_but_never_claims_to_be_certain(client, session):
    """up_016 은 아홉 라벨이 전부 동의어다. 예전에는 아홉 개 전부 기권이었다.

    되찾는 것 자체보다 **어떻게** 되찾는지가 중요하다. 값의 위치를 찾는 방법은 하나도
    바뀌지 않았고 라벨 어휘만 넓혔으므로, 이렇게 얻은 값은 팩 자신의 단어로 읽은 값과
    구별돼야 한다. certainty='low' 와 명시적 note 가 그 구별이다.
    """
    body = post(client, session, "up_016_pay_stub_wording_total_earnings.pdf", "pay_stub").json()
    assert body["read_nothing"] is False
    assert body["located_count"] == 9
    recovered = [f for f in body["fields"] if f["certainty"] != "abstain"]
    assert len(recovered) == 9
    # 동의어로 찾은 필드는 high 를 주장하지 않는다
    assert all(f["certainty"] == "low" for f in recovered)
    assert all("non-exact mapper" in (f["notes"] or "") for f in recovered)
    # 그래도 상자는 진짜다 -- 기하는 손대지 않았다
    assert all(f["bbox"] and len(f["bbox"]) == 4 for f in recovered)


def test_a_canonical_label_still_beats_a_synonym_for_the_same_field(client, session):
    """팩 자신의 단어로 붙은 라벨은 동의어보다 항상 먼저다.

    이 순서가 "기권을 정답으로만 바꾼다"는 성질의 근거다. 순서가 뒤집히면 이미 맞게
    읽던 필드가 다른 값으로 다시 풀릴 수 있다.
    """
    body = post(client, session, "up_003_pay_stub_john_doe.pdf", "pay_stub").json()
    got = {f["field"]: f for f in body["fields"]}
    # up_003 의 라벨은 전부 LABEL_MAP 에 있다 -> 전부 1차 통과로 high 여야 한다
    assert all(got[name]["certainty"] == "high" for name in EXPECTED_FIELDS["pay_stub"])


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
