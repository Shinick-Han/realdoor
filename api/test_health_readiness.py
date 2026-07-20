# -*- coding: utf-8 -*-
"""
test_health_readiness.py — 배포된 서버가 **조용히** 빈 답을 내주던 밤의 회귀 테스트.

그날 벌어진 일: 컨테이너에 팩 PDF 가 git-lfs 포인터 파일로 도착해 pdfplumber 가
"No /Root object! - Is this really a PDF?" 를 던졌다. 그 예외는 백그라운드 warm
스레드에서 났고, 데몬 스레드 하나가 죽었을 뿐 아무도 알아채지 못했다. `/api/health` 는
몇 시간 동안 200 을 답했고 `/api/households` 는 `{"households":[]}` 를 답했다.

여기서 검사하는 것은 **그 상태가 헬스체크에서 보이는가** 다. 세 가지 사건이 각각 다른
답을 내야 한다: warm 이 던졌다 / warm 이 0장으로 끝났다 / warm 이 아직 돈다.

  결함 1: 죽은 warm 스레드가 헬스체크에 보이지 않았다.
  결함 2: `new_session()` 이 warm 을 기다리지 않고 빈 `_base` 를 복사했다 — 그 세션은
          평생 빈 세션이었다(713dc2a 에서 고침). 아래 두 동시성 테스트가 그 회귀 감시다.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import store as store_mod
from api.store import STORE, Store


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from api.app import app

    STORE.warm()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _view(document_id: str = "HH-000-D01") -> dict:
    """`new_session()` 이 복사해 갈 수 있는 최소한의 DocumentView.

    추출을 실제로 돌리면 이 파일의 테스트는 24장의 OCR 을 기다리게 되고, 재는 대상도
    추출 정확도가 아니라 **빈 상태가 보고되는가** 로 바뀐다. 그래서 모양만 맞춘다.
    """
    return {"document_id": document_id, "fields": [], "page_count": 1}


def _store_that_has_warmed(monkeypatch, extract) -> Store:
    """`extract_all` 을 대신할 함수를 심은 새 스토어. 전역 STORE 는 건드리지 않는다."""
    monkeypatch.setattr(store_mod, "extract_all", extract)
    return Store()


# ── 사건 1: warm 이 예외로 죽었다 ────────────────────────────────────────────
def test_health_is_not_200_when_the_warm_raised(client, monkeypatch):
    """그날 밤의 예외 그대로. 헬스체크는 200 이면 안 되고, 이유가 본문에 있어야 한다."""
    def boom() -> list[dict]:
        raise ValueError("No /Root object! - Is this really a PDF?")

    store = _store_that_has_warmed(monkeypatch, boom)
    with pytest.raises(ValueError):
        store.warm()
    monkeypatch.setattr("api.app.STORE", store)

    r = client.get("/api/health")
    assert r.status_code == 503, "a dead warm answered a healthy status code"
    body = r.json()
    assert body["ok"] is False
    assert body["warm"] == "failed"
    assert body["documents_loaded"] == 0
    # 종류와 문장 둘 다. 종류만 있으면 어느 PDF 인지 모르고, 문장만 있으면 잡을 예외를
    # 코드로 특정할 수 없다.
    assert body["warm_error"]["type"] == "ValueError"
    assert "No /Root object!" in body["warm_error"]["message"]


def test_the_warm_records_its_own_death_without_swallowing_the_exception(monkeypatch):
    """스토어는 실패를 기록하되, 예외는 그대로 올려보내야 한다.

    기록하면서 삼키면 `new_session()` 이 조용히 빈 세션을 내주게 된다 — 고쳐 놓은 결함이
    다른 자리에서 되살아나는 길이다.
    """
    def boom() -> list[dict]:
        raise RuntimeError("pdfminer said no")

    store = _store_that_has_warmed(monkeypatch, boom)
    with pytest.raises(RuntimeError):
        store.warm()
    assert store.warm_report()["phase"] == "failed"
    # 실패한 스토어로 세션을 만들면 빈 세션이 아니라 예외가 나와야 한다.
    with pytest.raises(RuntimeError):
        store.new_session()


def test_a_warm_that_recovers_stops_reporting_the_old_failure(monkeypatch):
    """실패는 **현재 상태**여야 한다. 한 번 실패한 스토어가 성공한 뒤에도 503 을 답하면,
    그 헬스체크는 다음 사건 때 아무도 믿지 않는 경보가 된다."""
    attempts = {"n": 0}

    def flaky() -> list[dict]:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("lfs pointer, not a pdf")
        return [_view()]

    store = _store_that_has_warmed(monkeypatch, flaky)
    with pytest.raises(OSError):
        store.warm()
    store.warm()
    assert store.warm_report() == {"phase": "completed", "documents_loaded": 1, "error": None}


# ── 사건 2: warm 이 끝났는데 0장이다 (그날 밤 화면이 보인 상태) ───────────────
def test_health_is_not_200_when_the_warm_loaded_nothing(client, monkeypatch):
    """예외는 없었고 문서도 없다. 이 상태의 서버는 빈 화면 공장이다."""
    store = _store_that_has_warmed(monkeypatch, lambda: [])
    store.warm()
    monkeypatch.setattr("api.app.STORE", store)

    r = client.get("/api/health")
    assert r.status_code == 503, "zero documents answered a healthy status code"
    body = r.json()
    assert body["ok"] is False
    assert body["documents_loaded"] == 0
    assert body["warm"] == "completed"
    # 예외가 없었으므로 오류 칸은 비어 있어야 한다 — 없는 예외를 지어내면 안 된다.
    assert body["warm_error"] is None
    assert "empty" in body["detail"]


# ── 사건 3: warm 이 아직 도는 중 (이건 장애가 아니다) ────────────────────────
def test_health_is_200_while_the_warm_is_still_running(client, monkeypatch):
    """부팅 중은 고장이 아니다. `new_session()` 이 기다리므로 이 인스턴스는 답할 수 있다.

    여기서 503 을 내면 호스트가 부팅 중인 컨테이너를 죽은 것으로 보고 재시작하고,
    재시작은 warm 을 다시 시작시킨다 — 컨테이너가 자기 부팅의 끝에 영원히 닿지 못한다.
    """
    store = _store_that_has_warmed(monkeypatch, lambda: [_view()])   # 아직 부르지 않는다
    monkeypatch.setattr("api.app.STORE", store)

    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["warm"] == "running"
    assert body["documents_loaded"] == 0
    assert body["warm_error"] is None


def test_health_keeps_the_keys_the_ui_and_the_tools_read(client):
    """`ui/dist/app.js` 는 `ok` 로 같은 오리진 API 를 채택할지 정하고,
    `ui/tools/*.mjs` 는 `active_sessions` 를 읽는다. 새 필드는 **덧붙이기만** 한다."""
    body = client.get("/api/health").json()
    for key in ("ok", "engine_version", "active_sessions", "notice"):
        assert key in body, f"/api/health lost the key `{key}` that other code reads"
    assert body["ok"] is True
    assert isinstance(body["active_sessions"], int)
    assert body["documents_loaded"] > 0, "the module fixture warmed; the pack should be here"


# ── 결함 2 의 회귀 감시: warm 중에 태어난 세션 ───────────────────────────────
def test_a_session_created_during_the_warm_still_gets_the_documents(monkeypatch):
    """warm 이 도는 **한가운데** 에서 만든 세션도 문서를 받아야 한다.

    이것이 713dc2a 의 회귀 테스트다. `new_session()` 에서 `self.warm()` 을 지우면 이
    테스트는 실패한다 — 그 호출이 없으면 세션은 기다리지 않고 빈 `_base` 를 복사하고,
    아래 단언이 0 을 본다. 그게 배포된 서버가 `{"households":[]}` 를 200 으로 답한 이유다.
    """
    entered = threading.Event()
    finish = threading.Event()

    def slow_extract() -> list[dict]:
        entered.set()
        assert finish.wait(10), "the test's own release never fired"
        return [_view("HH-000-D01"), _view("HH-000-D02")]

    store = _store_that_has_warmed(monkeypatch, slow_extract)
    warmer = threading.Thread(target=store.warm, name="test-warm")
    warmer.start()
    assert entered.wait(5), "the warm never started"

    # 이 시점의 `_base` 는 비어 있다. 세션을 만들면 기다려야 한다.
    assert store.warm_report()["documents_loaded"] == 0
    threading.Timer(0.2, finish.set).start()
    session = store.new_session()
    warmer.join(10)

    assert len(session.views) == 2, (
        "a session created while the warm was in flight was born empty — "
        "new_session() is not waiting for warm()")
    assert store.warm_report()["phase"] == "completed"


def test_the_warm_runs_once_even_when_sessions_are_created_concurrently(monkeypatch):
    """락은 **먼저 도착한 요청이 같은 일을 기다리게** 하기 위한 것이다.

    락이 없으면 동시에 도착한 여덟 개의 요청이 24장을 각각 추출한다 — 512MB 호스트에서
    그것은 OOM 이고, 재시작이고, 다시 여덟 번의 추출이다.
    """
    calls = {"n": 0}
    started = threading.Event()

    def counted_extract() -> list[dict]:
        calls["n"] += 1
        started.set()
        time.sleep(0.1)          # 두 번째 스레드가 락에 도달할 시간을 준다
        return [_view()]

    store = _store_that_has_warmed(monkeypatch, counted_extract)
    sessions: list[object] = []
    errors: list[BaseException] = []

    def make() -> None:
        try:
            sessions.append(store.new_session())
        except BaseException as exc:      # 스레드에서 난 예외는 조용히 사라진다
            errors.append(exc)

    threads = [threading.Thread(target=make, name=f"test-session-{i}") for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert not errors, f"a concurrent session creation raised: {errors[0]!r}"
    assert calls["n"] == 1, f"the pack was extracted {calls['n']} times, not once"
    assert len(sessions) == 8
    assert all(len(s.views) == 1 for s in sessions), "a concurrent session came out empty"
