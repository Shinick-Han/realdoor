# -*- coding: utf-8 -*-
"""
test_upload_limits.py — 업로드 상한이 제품 자신의 흐름과 싸우지 않는가.

이 파일이 지키는 것은 숫자 하나가 아니라 **관계** 두 개다.

  (1) 세션 문서 상한(`api/store.py::MAX_SESSION_UPLOADS`)까지 문서를 모으는 동안
      분당 상한에 닿지 않는다. 문서 한 장이 요청 한 번이 아니기 때문에 — 스스로
      종류를 밝히지 않는 페이지는 거절 + 다시 읽기로 2회를 쓰고, 거절도 미들웨어를
      지나므로 토큰을 쓴다 — 이 관계는 "6 ≥ 6" 이 아니라 "상한 ≥ 조립 비용" 이다.
  (2) 그러면서도 두드리는 클라이언트는 여전히 거절한다.

두 성질은 반대 방향이라 한쪽만 보면 반드시 다른 쪽이 깨진다. 그래서 같은 파일에 둔다.

그리고 429 는 **업로드 거절이 아니다**. 화면이 그 둘을 갈라 보이려면 응답이 먼저
갈라져 있어야 하므로, 429 본문이 `UploadRejected` 의 코드(특히 `type_not_announced`)를
절대 싣지 않는다는 것도 여기서 못 박는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import limits  # noqa: E402
from api.app import app  # noqa: E402
from api.store import MAX_SESSION_UPLOADS  # noqa: E402

UPLOADS = ROOT / "testdata" / "uploads"

#: 여섯 장 조립의 정직한 비용. 문서 6장 × 왕복 2회(지명 실패 → 종류 골라 다시 읽기,
#: 또는 지명을 사람이 고치는 "종류 바꾸기") = 12, 거기에 잘못 올린 것을 지우고 다시
#: 올리는 몇 번을 더한 값. `api/limits.py` 의 근거 주석과 같은 수를 여기서도 센다.
ASSEMBLY_ROUND_TRIPS = MAX_SESSION_UPLOADS * 2 + 4


@pytest.fixture(scope="module")
def client():
    from api.store import STORE

    STORE.warm()
    return TestClient(app)


@pytest.fixture
def limits_on(monkeypatch):
    """스위트는 기본적으로 상한이 꺼져 있다(`limits.enabled`). 여기서는 켠다."""
    monkeypatch.setenv("REALDOOR_LIMITS", "1")
    return True


_address = iter(range(1, 10_000))


def fresh_address() -> str:
    """테스트마다 새 버킷. 미들웨어 인스턴스는 앱과 함께 살아 있으므로 상태를
    되감는 대신 **다른 클라이언트인 척** 한다 — `_key()` 가 보는 것이 이 헤더다."""
    return "203.0.113.%d" % (next(_address) % 250 + 1)


def post_upload(client, addr, *, session=None, payload=b"not a pdf",
                file_name="x.pdf", document_type=None):
    form = {} if document_type is None else {"document_type": document_type}
    headers = {"X-Forwarded-For": addr}
    if session:
        headers["X-Session-Id"] = session
    return client.post(
        "/api/upload",
        files={"file": (file_name, payload, "application/pdf")},
        data=form,
        headers=headers,
    )


def open_session(client, addr):
    return client.post("/api/session", headers={"X-Forwarded-For": addr}).json()["session_id"]


# ── (1) 조립은 상한에 닿지 않는다 ──────────────────────────────────────────
def test_the_limit_leaves_room_for_a_whole_six_document_assembly(limits_on):
    """숫자 자체의 관계. 이게 깨지면 아래 두 테스트가 왜 초록인지도 의미가 없다."""
    assert limits.RATE_UPLOAD_PER_MIN >= ASSEMBLY_ROUND_TRIPS, (
        "분당 업로드 상한이 여섯 장 조립의 왕복 수보다 작으면, 상한은 남용이 아니라 "
        "제품의 정상 경로를 막는다"
    )


def test_an_assembly_worth_of_uploads_never_meets_the_limiter(client, limits_on):
    """조립 비용만큼 두드려도 429 가 하나도 나오지 않는다.

    바이트는 일부러 PDF 가 아니다. 여기서 재는 것은 추출이 아니라 **미들웨어를 몇 번
    지날 수 있는가**이고, 거절되는 요청도 토큰을 쓴다는 것이 이 결함의 핵심이었다.
    실제 PDF 로 재면 같은 성질을 훨씬 느리게 재게 된다.
    """
    addr = fresh_address()
    statuses = [post_upload(client, addr).status_code
                for _ in range(ASSEMBLY_ROUND_TRIPS)]
    assert 429 not in statuses, (
        "여섯 장 조립 도중에 상한에 걸렸다: %r" % statuses
    )


def test_six_real_documents_go_in_without_a_pause(client, limits_on):
    """실제 경로로 한 번 더. 세션 문서 상한까지 채우는 동안 429 는 없다.

    먼저 PDF 가 아닌 바이트로 한 번 두드린다 — 그 요청은 400 으로 거절되지만
    **그러면서 토큰을 쓴다**(거절도 미들웨어를 지난다). 옛 상한 6 을 그 자리에서
    무너뜨리던 바로 그 성질이다. (예전엔 스캔본이 type_not_announced 로 이 역할을
    했지만, item 3 이후 스캔본은 보이는 기본값으로 읽혀 200 을 내고 자리를 차지한다 —
    그래서 여기서는 자리를 차지하지 않는 값싼 거절로 같은 성질을 잰다.)
    """
    addr = fresh_address()
    session = open_session(client, addr)
    good = (UPLOADS / "up_003_pay_stub_john_doe.pdf").read_bytes()

    seen = []
    r = post_upload(client, addr, session=session, payload=b"not a pdf at all",
                    file_name="not_a_pdf.pdf")
    seen.append(r.status_code)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "not_a_pdf"

    for _ in range(MAX_SESSION_UPLOADS):
        r = post_upload(client, addr, session=session, payload=good,
                        file_name="up_003_pay_stub_john_doe.pdf")
        seen.append(r.status_code)

    assert 429 not in seen, "여섯 장을 모으는 동안 상한에 걸렸다: %r" % seen
    assert seen.count(200) == MAX_SESSION_UPLOADS


# ── (2) 그래도 두드리면 막는다 ─────────────────────────────────────────────
def test_a_client_that_hammers_the_endpoint_is_still_refused(client, limits_on):
    """상한을 올린 것이 상한을 없앤 것이 되어서는 안 된다."""
    addr = fresh_address()
    statuses = [post_upload(client, addr).status_code
                for _ in range(limits.RATE_UPLOAD_PER_MIN + 5)]
    assert 429 in statuses, "상한을 넘겨 두드렸는데 아무것도 거절되지 않았다"


def test_the_limit_is_still_overridable_from_the_environment(monkeypatch):
    """배포 중에 코드를 고치지 않고 조일 수 있어야 한다 — 이 파일의 원래 약속."""
    monkeypatch.setenv("REALDOOR_RATE_UPLOAD", "3")
    assert limits._int_env("REALDOOR_RATE_UPLOAD", 30) == 3


# ── (3) 429 는 업로드 거절이 아니다 ────────────────────────────────────────
def test_a_rate_limited_upload_does_not_carry_an_upload_rejection_code(client, limits_on,
                                                                       monkeypatch):
    """화면이 원인별로 갈라 말하려면 응답이 먼저 갈라져 있어야 한다.

    특히 `type_not_announced` 가 실려서는 안 된다. 그 코드는 "종류 선택을 펼쳐라"를
    뜻하는데, 상한은 renter 의 문서 종류와 아무 상관이 없다.
    """
    monkeypatch.setattr(limits, "RATE_UPLOAD_PER_MIN", 1)
    addr = fresh_address()
    post_upload(client, addr)
    r = post_upload(client, addr)

    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "too_many_requests"
    assert "code" not in body, "429 에 업로드 거절의 코드 자리가 생기면 화면이 헷갈린다"
    assert "detail" in body and isinstance(body["detail"], str)
    assert "type_not_announced" not in r.text
    assert isinstance(body["retry_after_seconds"], int) and body["retry_after_seconds"] > 0
    assert r.headers["Retry-After"] == str(body["retry_after_seconds"])


def test_the_rate_limit_sentence_never_blames_the_document(client, limits_on, monkeypatch):
    """말투 규칙. 이 문장은 파일에 대해 아무 말도 하지 않아야 한다."""
    monkeypatch.setattr(limits, "RATE_UPLOAD_PER_MIN", 1)
    addr = fresh_address()
    post_upload(client, addr)
    detail = post_upload(client, addr).json()["detail"]

    assert "your session was changed or lost" in detail
    for blame in ("could not read", "did not read", "not a PDF", "damaged", "choose the kind"):
        assert blame.lower() not in detail.lower(), (
            "상한 문장이 파일 탓을 하고 있다: %r" % blame
        )
