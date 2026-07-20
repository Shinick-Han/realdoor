# -*- coding: utf-8 -*-
"""
limits.py — 공개 URL 에서 살아남기 위한 최소한의 방어.

이 앱은 인증이 없다. 그건 버그가 아니라 설계다 — 심사위원이 계정을 만들지 않고 6단계를
전부 걸어볼 수 있어야 한다. 대신 인증이 없다는 것은 **누구나 무한히** 세션을 만들고,
업로드하고, 질문할 수 있다는 뜻이기도 하다. 링크는 심사위원에게만 가지 않는다.

여기 있는 것은 전부 **정직하게 낮은 수준의 방어**다. 키는 `X-Forwarded-For` 의 첫
항목이고, 그 헤더는 위조할 수 있다. 그러므로 이것은 "작정한 공격자"를 막지 못한다.
막는 것은 "스크립트 한 대가 아무 생각 없이 두드리는 것" 과 "사고로 무한루프에 빠진
클라이언트" 다. 그 둘이 이 데모를 죽일 수 있는 현실적인 경로의 대부분이다.

의존성을 새로 넣지 않는다. `slowapi` 는 requirements 를 늘리고 배포일에 새 실패 지점을
만든다. 표준 라이브러리 토큰버킷이면 충분하고, 무엇이 왜 걸렸는지 여기서 다 읽힌다.

**말투 규칙**: 상한에 걸렸을 때의 응답도 화면과 같은 말투여야 한다. 못 하는 것을 먼저
말하고, 왜인지 말하고, 다음에 무엇을 하면 되는지 말한다. 판정 어휘는 쓰지 않는다 —
출력 게이트(`api/gate.py`)가 금지 키를 보면 500 을 던지므로, 여기서 실수하면 429 가
아니라 500 이 나간다.
"""
from __future__ import annotations

import os
import sys
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# ── 상한값 ──────────────────────────────────────────────────────────────
# 전부 환경변수로 덮을 수 있다. 배포 중에 코드를 고치지 않고 조일 수 있어야 한다.


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


#: 한 IP 가 1분에 낼 수 있는 /api 요청 총량. 정적 자산은 세지 않는다 — 화면 한 번
#: 여는 데 파일 몇 개가 따라 나오고, 그걸 세면 정상 사용자가 먼저 걸린다.
RATE_API_PER_MIN = _int_env("REALDOOR_RATE_API", 180)
#: 질문. 여기가 모델 호출로 이어지는 유일한 경로다.
RATE_ASK_PER_MIN = _int_env("REALDOOR_RATE_ASK", 12)
#: 업로드. 10MB PDF 의 OCR 은 이 앱에서 가장 비싼 CPU 작업이다.
#:
#: 6이었다. 그 6은 업로드 **파일**(세션이 올린 문서들로 만들어지는 자기 파일)이 생기기
#: 전의 숫자다. 그때 업로드는 "한 장 올려 보고 근거를 확인한다"가 전부였다. 지금은
#: 심사위원이 문서 여러 장으로 자기 파일을 만들어 두 페이지를 그 파일로 걷는 것이
#: **정상 경로**이고, 그래서 6은 제품 자신의 흐름과 싸운다. 실제로 연달아 올리다가
#: 거절당했다.
#:
#: 왜 6이 모자라는가. 세션 문서 상한은 6이다(`api/store.py::MAX_SESSION_UPLOADS`).
#: 그런데 **문서 한 장이 요청 한 번으로 끝나지 않는다**: 스스로 종류를 밝히지 않는
#: 페이지는 거절(400 `type_not_announced`) 한 번 + 종류를 골라 다시 읽기 한 번으로
#: 2회를 쓰고, 지명을 사람이 고치는 "종류 바꾸기"도 같은 값이다. 거절도 이 미들웨어를
#: 지나므로 토큰을 쓴다. 여섯 장 조립의 정직한 비용은 6이 아니라 12~16회다. 6은 모든
#: 페이지가 순조로운 최선의 경우에조차 여유가 0이고, 스캔본 한 장이 섞이면 그 자리에서
#: 걸린다(실측: 스캔 1장 + 정상 5장에서 여섯 번째 업로드가 429).
#:
#: 왜 30 이어도 두드리는 클라이언트를 막는가. 비싼 일의 진짜 상한은 이 버킷이 아니다.
#: `store.add_upload` 는 6문서 상한을 **추출을 시작하기 전에** 검사하므로, 세션 하나가
#: 살 수 있는 추출은 아무리 두드려도 6회다. 그 이상을 사려면 세션을 새로 만들어야 하고,
#: 세션 생성은 바로 아래 RATE_SESSION_PER_MIN=6 이 막는다. 그래서 한 주소가 1분에 살
#: 수 있는 추출은 이 값과 무관하게 6세션 × 6문서 = 36회가 구조적 천장이다. 30 은 그
#: 천장 **아래**에 있으므로 두드리는 쪽에는 여전히 이 버킷이 먼저 걸리고, 조립하는
#: 쪽에는 12~16 위로 두 배 가까운 여유가 남는다. 그리고 이 앱은 한 프로세스라 요청은
#: 어차피 직렬화된다 — 이 상한이 하는 일은 CPU 를 재는 것이 아니라 한 주소가 큐를
#: 독차지하지 못하게 하는 것이고, 30 은 그 일을 그대로 한다.
#:
#: 남용의 진짜 방어는 여전히 세션 문서 상한 6과 바이트 상한 10MB 다. 그 둘이 자리를
#: 지키는 한 이 숫자는 페이싱 장치이지 방어의 마지막 줄이 아니다.
RATE_UPLOAD_PER_MIN = _int_env("REALDOOR_RATE_UPLOAD", 30)
#: 세션 생성. 한 번에 팩 24문서를 deep copy 한다.
#:
#: 이 숫자는 이제 **분당 페이지 로드 6회**를 뜻한다. 전에는 그렇지 않았다 — 화면이 부팅
#: 할 때마다 세션을 3개씩 만들었으므로(`ui/dist/app.js` 의 ensureSession 경쟁) 같은 6이
#: "분당 2회 새로고침"이었고, 두 번째 새로고침에서 예산이 바닥났다. 값을 올려서 증상을
#: 덮는 대신 화면이 로드당 1개만 만들도록 고쳤고, 그래서 6은 처음으로 읽는 그대로다.
#:
#: 6이 맞는 근거: 정직한 독자 한 명이 1분에 하는 일은 페이지를 한 번 열고 6단계를 걷는
#: 것이다. 세션은 그 walkthrough 전체에서 하나면 된다. 헷갈려서 두세 번 다시 여는
#: 사람까지 계산해도 여유가 두 배 남는다. 그 이상을 1분에 하는 것은 읽는 행위가 아니다.
#:
#: 그런데도 걸리는 경우가 있다 — 같은 출구 IP 를 쓰는 심사위원 둘, 하드 리로드 연타.
#: 거기에 대한 답은 더 큰 숫자가 아니라 **화면이 429 에서 스스로 돌아오는 것**이다.
#: 응답의 `Retry-After` 를 화면이 읽고 그만큼 기다렸다가 다시 보낸다. 그래서 상한에
#: 닿은 독자가 보는 것은 죽은 페이지가 아니라 십 초 느린 페이지다.
#:
#: 남은 위험은 이 상한의 크기가 아니라 **키**다. `_key()` 는 `X-Forwarded-For` 의 첫
#: 항목을 쓴다. 앞단 프록시가 그 헤더를 채우지 않으면 모든 방문자가 프록시 IP 하나를
#: 공유하고, 그때는 6 이든 60 이든 같은 방식으로 틀린다. 고칠 곳은 이 값이 아니라 키다.
#:
#: 업로드 상한을 올리면서 이 값도 같은 눈으로 다시 봤고, **그대로 둔다**. 업로드를 막던
#: 논리(여섯 장 조립이 요청 하나로 안 끝난다)가 여기에는 해당되지 않기 때문이다: 문서를
#: 몇 장 올리든 세션은 하나이고(`ensureSession` 이 로드당 하나로 묶는다), 업로드 파일은
#: 그 한 세션 안에서 자란다. 오히려 이 6 은 이제 **더** 실어 나른다 — 위에서 적었듯이
#: 한 주소가 살 수 있는 추출의 구조적 천장(6세션 × 6문서)이 이 값에서 나온다. 올리면
#: 업로드 상한을 30 으로 둔 근거가 같이 무너진다.
RATE_SESSION_PER_MIN = _int_env("REALDOOR_RATE_SESSION", 6)
#: 자기 성적표. 모델 호출은 0 이지만 24항목 적대 스위트를 매번 다시 돌린다.
RATE_SELFTEST_PER_MIN = _int_env("REALDOOR_RATE_SELFTEST", 6)

#: 동시에 살아 있을 수 있는 세션 수. 세션 하나 = 팩 24문서 사본이다.
MAX_SESSIONS = _int_env("REALDOOR_MAX_SESSIONS", 300)
#: 이 나이를 넘긴 세션은 새 세션이 들어올 때 청소한다. 심사위원 한 명의 6단계
#: walkthrough 는 몇 분이면 끝난다. 한 시간이면 넉넉하다.
MAX_SESSION_AGE_SECONDS = _int_env("REALDOOR_MAX_SESSION_AGE", 3600)

#: 프로세스 전체의 모델 호출 상한. 넘으면 결정론 경로만 남는다 — 화면은 죽지 않는다.
MAX_LLM_CALLS_TOTAL = _int_env("REALDOOR_LLM_MAX_CALLS", 2000)
#: 세션 하나가 쓸 수 있는 모델 호출.
MAX_LLM_CALLS_PER_SESSION = _int_env("REALDOOR_LLM_MAX_CALLS_SESSION", 30)

#: 레이트리밋이 기억하는 클라이언트 수 상한. 방어 장치가 스스로 메모리 누수가 되면
#: 방어가 아니다. 넘으면 가장 오래 안 쓴 것부터 버린다.
MAX_TRACKED_CLIENTS = 4096


def enabled() -> bool:
    """테스트에서는 기본 OFF.

    스위트 880개가 같은 클라이언트로 같은 엔드포인트를 두드린다. 레이트리밋이 켜져
    있으면 스위트가 초록인지 429 인지가 실행 속도에 따라 달라진다 — 그건 측정이 아니다.
    `REALDOOR_LIMITS=1` 로 명시하면 테스트에서도 켤 수 있고, 실제로 켜서 검증했다.
    """
    flag = os.environ.get("REALDOOR_LIMITS", "").strip()
    if flag == "0":
        return False
    if flag == "1":
        return True
    return "pytest" not in sys.modules


# ── 토큰버킷 ────────────────────────────────────────────────────────────
class _Buckets:
    """클라이언트 하나의 버킷 묶음. 이름 -> (남은 토큰, 마지막 갱신 시각)."""

    __slots__ = ("state",)

    def __init__(self) -> None:
        self.state: dict[str, tuple[float, float]] = {}

    def take(self, name: str, per_minute: int, now: float) -> float:
        """토큰 하나를 쓴다. 성공이면 0.0, 실패면 다음 토큰까지 남은 초."""
        if per_minute <= 0:
            return 0.0
        rate = per_minute / 60.0
        tokens, last = self.state.get(name, (float(per_minute), now))
        tokens = min(float(per_minute), tokens + (now - last) * rate)
        if tokens < 1.0:
            self.state[name] = (tokens, now)
            return max(1.0, (1.0 - tokens) / rate)
        self.state[name] = (tokens - 1.0, now)
        return 0.0


class RateLimit(BaseHTTPMiddleware):
    """IP·분 단위 요청 제한. `/api` 경로에만 건다.

    `app.add_middleware(DecisionGate)` **다음에** 등록해야 한다. Starlette 은 나중에
    add 한 것이 바깥이므로, 그래야 차단된 요청이 앱에 아예 닿지 않는다.
    """

    def __init__(self, app) -> None:
        super().__init__(app)
        self._clients: OrderedDict[str, _Buckets] = OrderedDict()

    @staticmethod
    def _key(request) -> str:
        # 프록시 뒤에서는 request.client.host 가 프록시 IP 다. 헤더는 위조 가능하다 —
        # 그러므로 이건 완벽한 방어가 아니고, 그렇게 취급하지도 않는다.
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                return first
        client = getattr(request, "client", None)
        return getattr(client, "host", None) or "unknown"

    def _buckets(self, key: str) -> _Buckets:
        b = self._clients.get(key)
        if b is None:
            if len(self._clients) >= MAX_TRACKED_CLIENTS:
                self._clients.popitem(last=False)
            b = _Buckets()
        else:
            self._clients.move_to_end(key)
        self._clients[key] = b
        return b

    @staticmethod
    def _rules(method: str, path: str) -> list[tuple[str, int]]:
        rules: list[tuple[str, int]] = [("api", RATE_API_PER_MIN)]
        if method == "POST" and path == "/api/ask":
            rules.append(("ask", RATE_ASK_PER_MIN))
        elif method == "POST" and path == "/api/upload":
            rules.append(("upload", RATE_UPLOAD_PER_MIN))
        elif method == "POST" and path == "/api/session":
            rules.append(("session", RATE_SESSION_PER_MIN))
        elif method == "GET" and path == "/api/selftest":
            rules.append(("selftest", RATE_SELFTEST_PER_MIN))
        return rules

    async def dispatch(self, request, call_next):
        path = request.url.path
        if not enabled() or not path.startswith("/api"):
            return await call_next(request)

        now = time.monotonic()
        buckets = self._buckets(self._key(request))
        for name, per_minute in self._rules(request.method, path):
            wait = buckets.take(name, per_minute, now)
            if wait > 0.0:
                return _slow_down(name, wait)
        return await call_next(request)


def _slow_down(bucket: str, wait: float) -> JSONResponse:
    """상한에 걸린 응답.

    못 하는 것을 먼저 말하고, 왜인지 말하고, 언제 다시 되는지 말한다. 이 서비스는
    누구도 판정하지 않으므로 거절도 판정처럼 읽혀선 안 된다 — 이건 **이 링크가 공개라서
    한 대가 전부를 쓰지 못하게 하는 것**이고, 문장이 그렇게 말해야 한다.
    """
    seconds = int(wait + 0.999)
    what = {
        "ask": "questions",
        "upload": "uploads",
        "session": "new sessions",
        "selftest": "self-test runs",
        "api": "requests",
    }.get(bucket, "requests")
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(seconds)},
        content={
            "error": "too_many_requests",
            "detail": (
                f"This copy is not handling more {what} from your connection right now. "
                f"It is a free public demo running as one process, and the cap is there so "
                f"one client cannot take the whole thing away from everyone else. Nothing "
                f"about your session was changed or lost. Wait {seconds} second"
                f"{'' if seconds == 1 else 's'} and repeat what you were doing."
            ),
            "retry_after_seconds": seconds,
        },
    )


# ── 세션 총량 ───────────────────────────────────────────────────────────
# 세션의 생성 시각은 `Session` 이 들고 있지 않다. 그 dataclass 를 고치는 대신 여기서
# 따로 장부를 쓴다 — 이 파일 하나만 되돌리면 방어 전체가 사라지게 두려는 것이다.
_created: "OrderedDict[str, float]" = OrderedDict()


class SessionCapacity(Exception):
    """세션을 더 만들 수 없다."""


def note_session(session_id: str) -> None:
    _created[session_id] = time.monotonic()


def forget_session(session_id: str) -> None:
    _created.pop(session_id, None)


def reap(store) -> int:
    """나이 지난 세션을 실제로 폐기한다. 폐기한 수를 돌려준다."""
    if MAX_SESSION_AGE_SECONDS <= 0:
        return 0
    now = time.monotonic()
    stale = [sid for sid, born in _created.items()
             if now - born > MAX_SESSION_AGE_SECONDS]
    for sid in stale:
        store.delete(sid)
        _created.pop(sid, None)
    # 장부에 없는 세션(이 모듈이 붙기 전에 생긴 것)은 건드리지 않는다.
    return len(stale)


def admit_session(store) -> None:
    """새 세션을 받아도 되는지 본다. 안 되면 `SessionCapacity`.

    순서가 중요하다: **먼저 청소하고**, 그래도 자리가 없으면 가장 오래된 것을 축출하고,
    축출할 것조차 없으면 그때 거절한다. 거절이 첫 수단이면 하루 지난 유령 세션 때문에
    새 심사위원이 문 앞에서 돌아가게 된다.
    """
    if not enabled() or MAX_SESSIONS <= 0:
        return
    reap(store)
    while store.session_count >= MAX_SESSIONS and _created:
        oldest, _ = _created.popitem(last=False)
        store.delete(oldest)
    if store.session_count >= MAX_SESSIONS:
        raise SessionCapacity("session_capacity")


# ── 모델 호출 예산 ──────────────────────────────────────────────────────
# 상한을 넘겨도 **사용자에게는 아무 것도 깨지지 않는다.** 분류기를 건너뛰면 답은 결정론
# 경로로 나가고, 결정론 경로가 침묵하면 화면은 원래 하던 대로 "모르겠다"고 말한다.
# 이게 이 앱 설계의 이점이고, 그래서 이 상한은 안전하게 낮게 걸 수 있다.
_llm_total = 0
_llm_by_session: "OrderedDict[str, int]" = OrderedDict()


def llm_budget_left(session_id: str | None) -> bool:
    if not enabled():
        return True
    if MAX_LLM_CALLS_TOTAL and _llm_total >= MAX_LLM_CALLS_TOTAL:
        return False
    if session_id and MAX_LLM_CALLS_PER_SESSION:
        if _llm_by_session.get(session_id, 0) >= MAX_LLM_CALLS_PER_SESSION:
            return False
    return True


def note_llm_attempt(session_id: str | None, spent: int = 1) -> None:
    global _llm_total
    if spent <= 0:
        return
    _llm_total += spent
    if session_id:
        _llm_by_session[session_id] = _llm_by_session.get(session_id, 0) + spent
        _llm_by_session.move_to_end(session_id)
        while len(_llm_by_session) > MAX_TRACKED_CLIENTS:
            _llm_by_session.popitem(last=False)


def enforce_llm_budget(session_id: str | None) -> bool:
    """예산이 남았으면 True. 다 썼으면 분류기를 **끄고** False.

    끄는 방법은 이미 있는 스위치를 쓰는 것이다 — `REALDOOR_LLM_ROUTER=0` 과
    `REALDOOR_LABEL_LLM=0` 은 두 모듈이 원래부터 읽는 값이다(`api/route_llm.py:284`,
    `core/label_llm.py:276`). 새 우회로를 뚫는 대신 있는 문을 닫는다.

    전체 예산은 한 번 소진되면 되살아나지 않으므로 되돌릴 필요가 없다 — 그래서 요청
    사이에 환경변수를 껐다 켰다 하는 경쟁 조건이 생기지 않는다. 세션 예산만 남은
    경우에는 환경을 건드리지 않고 False 만 돌려준다. 이 값을 어떻게 쓸지는 호출자가
    정한다(`api/app.py` 의 `ask()`).
    """
    if not enabled():
        return True
    if MAX_LLM_CALLS_TOTAL and _llm_total >= MAX_LLM_CALLS_TOTAL:
        # 프로세스 전체 상한. 여기서부터는 결정론 경로만 남는다.
        os.environ["REALDOOR_LLM_ROUTER"] = "0"
        os.environ["REALDOOR_LABEL_LLM"] = "0"
        return False
    return llm_budget_left(session_id)


def budget_snapshot() -> dict:
    return {
        "llm_calls_used": _llm_total,
        "llm_calls_cap": MAX_LLM_CALLS_TOTAL,
        "llm_calls_cap_per_session": MAX_LLM_CALLS_PER_SESSION,
        "sessions_cap": MAX_SESSIONS,
        "limits_active": enabled(),
    }


def reset() -> None:
    """테스트용. 프로세스 전역 상태를 쓰는 모듈은 되감을 방법이 있어야 한다."""
    global _llm_total
    _llm_total = 0
    _llm_by_session.clear()
    _created.clear()
