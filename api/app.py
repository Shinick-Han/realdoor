# -*- coding: utf-8 -*-
"""
app.py — RealDoor API.

한 프로세스가 API와 UI를 함께 서빙한다. 오리진이 하나이므로 CORS가 없고,
인터넷이 끊겨도 시연이 돌아간다. 데모 중에 죽을 지점을 줄이는 것이 목적이다.

엔드포인트는 브리프가 지정한 6단계 인수 데모에 1:1로 대응한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api import gate, limits
from api.store import STORE, DOCS, engine_version

app = FastAPI(
    title="RealDoor — application-readiness copilot",
    description="Ready, not eligible. This service never decides eligibility.",
    version="0.1.0",
)

UI_DIR = ROOT / "ui" / "dist"


# ── 출력 게이트 ─────────────────────────────────────────────────────────
class DecisionGate(BaseHTTPMiddleware):
    """나가는 모든 JSON을 검사한다. 판정이 섞이면 **응답을 보내지 않고 실패**한다."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if not ctype.startswith("application/json"):
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return Response(content=body, status_code=response.status_code,
                            headers=dict(response.headers),
                            media_type=response.media_type)

        problems = gate.scan(payload)
        if problems:
            return JSONResponse(
                status_code=500,
                content={
                    "error": "decision_gate_blocked_response",
                    "detail": ("This service must never approve, deny, score, rank or "
                               "prioritise. The response was withheld."),
                    "violations": problems,
                },
            )

        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(content=body, status_code=response.status_code,
                        headers=headers, media_type="application/json")


app.add_middleware(DecisionGate)

# 레이트리밋은 **게이트 다음에** 등록한다. Starlette 은 나중에 add 한 것이 바깥이므로
# 이 순서라야 차단된 요청이 앱에 아예 닿지 않는다. 반대로 두면 429 응답까지 게이트가
# 훑는다 — 무해하지만 낭비고, 무엇보다 막으려던 일이 이미 벌어진 뒤가 된다.
# 상한값과 그 근거는 `api/limits.py` 에 있다. 테스트 중에는 기본 OFF.
app.add_middleware(limits.RateLimit)


# Warming reads all 24 pack documents. With a cold cache that takes over a minute, and a
# host that health-checks the port will conclude the process is dead and restart it —
# which starts the warm again, so the container never reaches the end of its own boot. The
# app is useful before the warm finishes (health answers, the UI serves), so the warm runs
# behind the port rather than in front of it. `STORE.warm()` is idempotent and the request
# paths call it themselves, so a request that arrives first simply waits for the same work
# instead of racing it.
@app.on_event("startup")
def _startup() -> None:
    import threading

    def _warm() -> None:
        info = STORE.warm()
        print(f"[realdoor] warmed {info['documents']} documents · {info['engine']}",
              flush=True)

    threading.Thread(target=_warm, name="realdoor-warm", daemon=True).start()
    print("[realdoor] serving; warming in the background", flush=True)


def _session(x_session_id: str | None):
    if not x_session_id:
        raise HTTPException(400, "missing X-Session-Id header; POST /api/session first")
    s = STORE.get(x_session_id)
    if s is None:
        raise HTTPException(404, "session not found or already deleted")
    return s


# ── 기본 ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "engine_version": engine_version(),
        "active_sessions": STORE.session_count,
        # 화면과 같은 순서로 말한다: 무엇을 하는지 먼저, 경계는 이유와 함께 뒤에.
        # 서버가 화면과 다른 말을 하면 그것도 어긋남이다.
        "notice": ("This service gets a file to the person who decides, complete the first "
                   "time it is handed over. It never decides eligibility itself."),
    }


# ── 세션 (데모 6단계: 세션 삭제) ────────────────────────────────────────
@app.post("/api/session")
def create_session() -> dict:
    """세션 하나 = 팩 24문서의 **사본** 하나다 (`api/store.py:298-305`).

    인증이 없으므로 이 라우트는 누구나 무한히 부를 수 있고, 부를 때마다 프로세스
    메모리가 그만큼 늘어난다. 그래서 여기에만 총량 상한이 있다. 상한에 닿으면 먼저
    나이 지난 세션을 청소하고, 그래도 자리가 없으면 가장 오래된 것을 축출한다
    (근거는 `api/limits.py`). 거절은 마지막 수단이다.
    """
    try:
        limits.admit_session(STORE)
    except limits.SessionCapacity:
        raise HTTPException(
            503,
            "This copy is not opening new sessions right now. It is a free public demo "
            "holding every session in one process's memory, so there is a ceiling on how "
            "many can be open at once, and it has been reached. Nothing is wrong with "
            "your browser. Wait about a minute and load the page again.",
        ) from None
    s = STORE.new_session()
    limits.note_session(s.session_id)
    return {"session_id": s.session_id, "documents": len(s.views)}


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str) -> dict:
    """폐기 후에는 프로세스 어디에도 남지 않는다. 이어지는 GET은 404가 된다."""
    existed = STORE.delete(session_id)
    limits.forget_session(session_id)
    return {"deleted": existed, "session_id": session_id,
            "remaining_sessions": STORE.session_count}


# ── 조회 (데모 1단계) ───────────────────────────────────────────────────
@app.get("/api/households")
def households(x_session_id: str | None = Header(default=None)) -> dict:
    s = _session(x_session_id)
    return {"households": STORE.households(s)}


@app.get("/api/report/{household_id}")
def report(household_id: str, x_session_id: str | None = Header(default=None)) -> dict:
    s = _session(x_session_id)
    rep = STORE.report(s, household_id)
    if rep is None:
        raise HTTPException(404, f"unknown household {household_id}")
    return rep


# ── 확인과 정정 (데모 1·2단계) ─────────────────────────────────────────
@app.post("/api/confirm")
def confirm(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """세입자가 값을 되돌려 보낸다. **한 엔드포인트, 두 결과.**

    화면은 읽은 값을 입력칸에 미리 채워 둔다. 세입자가 그대로 보내면 그 값이 사람의 눈을
    거쳤다는 표시(`confirmed_by_renter`)가 붙고, 고쳐서 보내면 정정(`corrected_by_renter`)이
    된다. 어느 쪽인지는 **서버가 값을 비교해서 정한다** — 화면이 "이건 확인입니다" 라고
    선언할 수 있게 두면, 화면 버그 하나가 확인해 준 적 없는 값을 확인된 것으로 만든다.

    브리프 Required Build 01: "Require confirmation or correction before reuse".
    확인·정정 어느 쪽이든 하위 계산은 즉시 다시 돌아 나간다.

    `together` 는 세입자가 한 문서의 남은 값들을 한 번에 확인했음을 기록에 남기기 위한
    것이다. 표시(`evidence_kind`)는 같지만, **어떻게 확인했는지**는 감사 기록에서 구분되어야
    한다. 한 번에 확인한 것을 하나씩 본 것처럼 적으면 그 기록이 실제보다 강해 보인다.
    """
    s = _session(x_session_id)
    for key in ("document_id", "field", "value"):
        if key not in payload:
            raise HTTPException(400, f"missing `{key}`")
    # 빈 칸은 확인도 정정도 아니다. 입력칸을 미리 채워 두면 사용자는 그것을 지울 수도
    # 있는데, 빈 문자열을 값으로 받아들이면 읽은 값을 사람이 "정정해서 지웠다"는 기록이
    # 남는다. 그건 사용자가 한 일이 아니다.
    if isinstance(payload["value"], str) and not payload["value"].strip():
        raise HTTPException(400, "`value` is empty; send the value this field should hold")
    outcome = STORE.apply_correction(s, payload["document_id"], payload["field"],
                                     payload["value"],
                                     together=bool(payload.get("together")))
    if outcome == "no_such_field":
        raise HTTPException(404, "no such field on that document")
    if outcome == "nothing_was_read":
        raise HTTPException(
            400, "this field was not read from the document, so there is nothing to "
                 "confirm; send the value it should hold instead")
    hid = payload["document_id"].rsplit("-", 1)[0]
    rep = STORE.report(s, hid)
    if rep is None:
        raise HTTPException(404, f"unknown household {hid}")
    return rep


@app.post("/api/undo")
def undo(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """한 정정을 취소한다. 취소는 **세션 상태에서** 일어나야 한다.

    화면이 "back to the extracted values" 라고 말하는데 클라이언트만 되돌리면,
    서버 세션에는 정정값이 남아 다음 정정 때 되살아난다. 그래서 취소도 왕복한다.
    지정한 (문서, 필드) 하나만 되돌리고 다른 정정은 그대로 둔다.
    """
    s = _session(x_session_id)
    for key in ("document_id", "field"):
        if key not in payload:
            raise HTTPException(400, f"missing `{key}`")
    ok = STORE.undo_correction(s, payload["document_id"], payload["field"])
    if not ok:
        raise HTTPException(404, "no correction on that field to undo")
    hid = payload["document_id"].rsplit("-", 1)[0]
    rep = STORE.report(s, hid)
    if rep is None:
        raise HTTPException(404, f"unknown household {hid}")
    return rep


# ── 업로드 (인수 데모 1단계) ────────────────────────────────────────────
@app.get("/api/upload/types")
def upload_types() -> dict:
    """읽을 줄 아는 문서 종류. 화면의 선택지는 여기서 온다 — 하드코딩 사본은 없다."""
    from api import upload as upload_mod

    return {
        "document_types": upload_mod.supported_document_types(),
        "max_bytes": upload_mod.MAX_UPLOAD_BYTES,
        "accepted": "application/pdf",
        "notice": ("Upload synthetic documents only. Everything you upload stays in this "
                   "session's memory, is never written to disk, and is never used to train "
                   "anything."),
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 document_type: str = Form(...),
                 content_length: int | None = Header(default=None),
                 x_session_id: str | None = Header(default=None)) -> dict:
    """올린 PDF 한 장을 읽고 **근거와 함께** 돌려준다.

    `document_type` 은 선택이 아니라 필수다. 파일 이름으로는 종류를 알 수 없고
    (`core.extract.infer_document_type` 은 팩 명명 규칙 밖에서 항상 `unknown` 을 낸다),
    `unknown` 은 오류가 아니라 **빈 필드 목록**을 내므로 조용히 실패한다. 그 실패를
    사용자에게 떠넘기지 않으려면 여기서 막아야 한다.

    결과는 세션 메모리에만 담긴다. 세대 계산에는 합류시키지 않는다 — 그 이유는
    `api/upload.py` 모듈 문서에 적혀 있다.
    """
    from api import upload as upload_mod

    s = _session(x_session_id)
    # `upload_mod.validate` 의 10MB 검사는 **바이트가 이미 전부 메모리에 올라온 뒤**에
    # 돈다. 그러면 500MB POST 도 일단 다 버퍼된 다음에야 거절당한다 — 공개 URL 에서는
    # 그 자체가 공격이다. 그래서 여기서 두 번 막는다.
    #
    # (1) Content-Length 를 먼저 본다. 싸고, 정상 클라이언트는 항상 보낸다.
    #     헤더는 위조할 수 있으므로 이것만으로는 부족하다.
    # (2) 그래서 읽기도 청크 루프로 바꾼다. 누적이 한도를 넘는 순간 읽기를 멈춘다.
    #     멀티파트 경계 때문에 본문은 파일보다 조금 크므로 여유를 조금 둔다.
    #
    # 응답의 모양과 상태 코드는 `upload_mod.validate` 가 내던 것과 **똑같이** 맞춘다
    # (400 + `{"code": "file_too_large", ...}`). 413 이 HTTP 로는 더 정확하지만, 그
    # 정확함을 얻자고 화면과 테스트가 알고 있는 계약을 바꾸는 것은 남는 장사가 아니다.
    # 여기서 달라지는 것은 **언제 거절하느냐** 하나여야 한다.
    ceiling = upload_mod.MAX_UPLOAD_BYTES

    def _too_big(size: int | None) -> HTTPException:
        how_big = f"That upload is {size / 1048576:.1f} MB. " if size else "That upload is too large. "
        return HTTPException(400, {
            "code": "file_too_large",
            "detail": (
                f"{how_big}The limit is {ceiling // 1048576} MB, because an uploaded "
                f"document is held in memory for this session only and never written to "
                f"disk. We stopped reading it rather than taking it in first and refusing "
                f"afterwards."
            ),
        })

    if content_length is not None and content_length > ceiling + 65536:
        raise _too_big(content_length)

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(262144)
        if not chunk:
            break
        total += len(chunk)
        if total > ceiling:
            # 남은 본문을 읽지 않고 여기서 끊는다. 읽어 버리면 막은 의미가 없다.
            chunks.clear()
            raise _too_big(total)
        chunks.append(chunk)
    data = b"".join(chunks)
    chunks.clear()
    try:
        doc_type = upload_mod.validate(data, file.filename or "upload.pdf",
                                       file.content_type, document_type)
        view = STORE.add_upload(s, data, file.filename or "upload.pdf", doc_type)
    except upload_mod.UploadRejected as exc:
        raise HTTPException(400, {"code": exc.code, "detail": exc.message}) from exc
    return view


@app.get("/api/upload/{upload_id}/page/{page}.png")
def upload_page_png(upload_id: str, page: int,
                    x_session_id: str | None = Header(default=None)) -> Response:
    """올린 문서의 페이지 이미지. 원본 바이트는 세션 메모리에서만 나온다."""
    from core.render import render_page_png

    s = _session(x_session_id)
    data = s.upload_bytes.get(upload_id)
    if data is None:
        raise HTTPException(404, f"unknown upload {upload_id}")
    img = render_page_png(data, page_number=page)
    return Response(content=img.png_bytes, media_type="image/png",
                    headers={"X-Image-Scale": str(img.scale),
                             "X-Image-Width": str(img.width_px),
                             "X-Image-Height": str(img.height_px)})


# ── 페이지 이미지 (UI가 근거 상자를 그리는 바탕) ────────────────────────
@app.get("/api/document/{document_id}/page/{page}.png")
def page_png(document_id: str, page: int,
             x_session_id: str | None = Header(default=None)) -> Response:
    from core.render import render_page_png

    s = _session(x_session_id)
    view = s.views.get(document_id)
    if view is None:
        raise HTTPException(404, f"unknown document {document_id}")
    img = render_page_png(str(DOCS / view["file_name"]), page_number=page)
    return Response(content=img.png_bytes, media_type="image/png",
                    headers={"X-Image-Scale": str(img.scale),
                             "X-Image-Width": str(img.width_px),
                             "X-Image-Height": str(img.height_px)})


# ── 규칙 질문 + 적대적 입력 (데모 3·6단계) ─────────────────────────────
@app.post("/api/ask")
def ask(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """규칙 질문에 인용과 함께 답하거나, 명시적으로 거부한다.

    판단 경로에 LLM이 없으므로, 문서나 질문에 삽입된 지시는 원리적으로
    계산을 바꿀 수 없다. 여기서는 그 위에 명시적 거부 세 가지를 얹는다.
    """
    import os

    from api import ask as ask_mod
    from api import route_llm
    from logic.household import households_from_views

    s = _session(x_session_id)
    question = payload.get("question", "")
    hid = payload.get("household_id")
    houses = households_from_views(list(s.views.values()))
    s.log("question_asked", household_id=hid)   # 질문 원문은 남기지 않는다

    # ── 모델 호출 예산 ──────────────────────────────────────────────────
    # 이 라우트가 이 앱에서 모델 호출로 이어지는 유일한 경로다. 캐시를 비껴가는 무작위
    # 문장을 반복하면 분류기가 계속 불린다 — 공개 URL 에서 돈이 새는 유일한 구멍이다.
    #
    # 예산을 다 쓰면 분류기만 건너뛴다. 답은 여전히 결정론 경로로 나가고, 결정론 층이
    # 침묵하면 화면은 원래 하던 대로 기권한다. **사용자에게는 아무 것도 깨지지 않으므로**
    # 상한을 낮게 걸어도 안전하다. 이게 판단 경로에 LLM 을 두지 않은 설계의 이점이다.
    before = route_llm.stats().get("calls", 0)
    if limits.enforce_llm_budget(s.session_id):
        answer = ask_mod.handle(question, hid, houses)
    else:
        saved = os.environ.get("REALDOOR_LLM_ROUTER")
        os.environ["REALDOOR_LLM_ROUTER"] = "0"
        try:
            answer = ask_mod.handle(question, hid, houses)
        finally:
            # 이 요청이 도는 사이에 **전체** 예산이 소진됐다면 그쪽 결정이 이긴다.
            # 그때는 되돌리지 않는다 — 되돌리면 방금 닫은 문을 다시 여는 셈이다.
            if not limits.llm_budget_left(None):
                pass
            elif saved is None:
                os.environ.pop("REALDOOR_LLM_ROUTER", None)
            else:
                os.environ["REALDOOR_LLM_ROUTER"] = saved
    # 시도가 아니라 **분류기가 실제로 게이트웨이를 부른 횟수**를 센다
    # (`route_llm._STATS["calls"]`). 결정론 층이 잡아낸 질문은 예산을 쓰지 않는다.
    limits.note_llm_attempt(s.session_id, route_llm.stats().get("calls", 0) - before)
    return answer


# ── 패킷 내보내기 (데모 5단계) ─────────────────────────────────────────
@app.post("/api/packet/{household_id}")
def packet(household_id: str, x_session_id: str | None = Header(default=None)) -> Response:
    """신청자가 통제하는 준비 패킷. **어디에도 자동 전송되지 않는다.**"""
    import io
    import zipfile

    s = _session(x_session_id)
    rep = STORE.report(s, household_id)
    if rep is None:
        raise HTTPException(404, f"unknown household {household_id}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readiness_report.json",
                   json.dumps(rep, ensure_ascii=False, indent=1, default=str))
        # 활동 기록을 **따로** 싣는다. 리포트 안에도 있지만, 이 파일을 열어 본 사람이
        # 리포트 전체를 뒤지지 않고도 "이 프로필의 어느 값이 사람의 눈을 거쳤는지" 를
        # 볼 수 있어야 한다. 브리프: "log consent, actions, and rule versions - not raw
        # document contents" — 그래서 값도, 파일 이름도, 질문 원문도 여기 없다.
        z.writestr("activity_log.json",
                   json.dumps({"household_id": household_id,
                               "confirmation": rep.get("confirmation"),
                               "activity_log": rep.get("activity_log")},
                              ensure_ascii=False, indent=1, default=str))
        tally = rep.get("confirmation") or {}
        z.writestr("README.txt",
                   "RealDoor readiness packet\n"
                   "=========================\n\n"
                   "This packet describes what your documents show and what is still\n"
                   "missing or expired. It is NOT an eligibility decision. A qualified\n"
                   "housing professional makes that determination.\n\n"
                   "What a person checked\n"
                   "---------------------\n"
                   f"  {tally.get('confirmed', 0)} value(s) confirmed as read correctly\n"
                   f"  {tally.get('corrected', 0)} value(s) corrected by the renter\n"
                   f"  {tally.get('not_confirmed', 0)} value(s) still carry only the machine reading\n"
                   f"  {tally.get('not_read', 0)} value(s) could not be read at all\n\n"
                   "activity_log.json lists the actions taken in this session, in order.\n"
                   "It records what was done and which rule versions applied. It does not\n"
                   "record the contents of any document or any value that was typed.\n\n"
                   "Nothing here has been sent to any property or provider. Sharing it\n"
                   "is your choice.\n")
        for doc in rep.get("documents", []):
            src = DOCS / doc["file_name"]
            if src.exists():
                z.write(src, f"documents/{doc['file_name']}")
    s.log("packet_exported", household_id=household_id)
    return Response(
        content=buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition":
                 f'attachment; filename="realdoor_{household_id}_packet.zip"'})


# ── 자기 성적표 (데모 마지막 화면) ─────────────────────────────────────
@app.get("/api/selftest")
def selftest(x_session_id: str | None = Header(default=None)) -> dict:
    """측정을 지금 다시 돌려서 낸 숫자. 이전 실행 결과를 옮겨 적지 않는다."""
    from api import ask as ask_mod
    from api import selftest as selftest_mod
    from logic.household import households_from_views

    s = _session(x_session_id)
    views = list(s.views.values())
    houses = households_from_views(views)

    def respond(text: str) -> dict:
        return ask_mod.handle(text, None, houses)

    return selftest_mod.build(views, respond)


# ── 게이트 자기시험 (데모: 통제가 동작함을 눈앞에서 증명) ───────────────
@app.get("/api/_gate_selftest")
def gate_selftest() -> dict:
    """**의도적으로** 판정이 든 응답을 만들어 본다.

    브리프: "Teams must demonstrate these controls live. A disclaimer without
    working controls does not satisfy the challenge."

    이 라우트는 규정을 위반한 페이로드를 반환하려 시도한다. 정상 동작이라면
    사용자는 이 내용을 절대 보지 못하고, 게이트가 가로챈 500을 받는다.
    즉 이 엔드포인트가 '성공'하면 그게 우리 시스템의 실패다.
    """
    return {
        "household_id": "HH-001",
        "eligible": True,   # no-decision-fixture  ← 금지 키 (의도적)
        "score": 0.92,      # no-decision-fixture  ← 금지 키 (의도적)
        "note": "이 응답은 사용자에게 도달해서는 안 된다.",
    }


@app.get("/api/document/{document_id}/overlay/{page}")
def overlay(document_id: str, page: int,
            x_session_id: str | None = Header(default=None)) -> dict:
    """해당 페이지의 필드별 픽셀 사각형. UI는 이걸 이미지 위에 그대로 얹으면 된다."""
    from core.render import overlay_rects

    s = _session(x_session_id)
    view = s.views.get(document_id)
    if view is None:
        raise HTTPException(404, f"unknown document {document_id}")
    return {"document_id": document_id, "page": page,
            "rects": overlay_rects(view, page_number=page)}


# ── UI 정적 서빙 ────────────────────────────────────────────────────────
# **반드시 모든 /api 라우트 뒤에 온다.** "/" 마운트는 먼저 등록된 라우트만
# 비켜가므로, 위쪽에 두면 API 전체를 삼킨다.
#
# 한 프로세스가 UI와 API를 같은 오리진에서 서빙한다 → CORS 없음, 인터넷 없이 동작,
# 심사위원은 서버 하나만 띄우면 된다.
if UI_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:  # pragma: no cover
    @app.get("/")
    def _no_ui() -> dict:
        return {"error": "ui_not_built",
                "detail": f"expected the interface at {UI_DIR}"}
