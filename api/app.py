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
from api.store import PDFIUM_LOCK, STORE, DOCS, UPLOADS_HOUSEHOLD_ID, engine_version

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
    import traceback

    def _warm() -> None:
        # A daemon thread that raises dies quietly: the interpreter prints the traceback and
        # every other thread carries on, so the process keeps answering 200 with nothing
        # loaded. That is exactly how a container full of git-lfs pointer files served an
        # empty pack for hours. `STORE.warm()` records the failure before it re-raises, so
        # /api/health can report it; this handler exists to make sure the traceback is
        # printed by us, deliberately, rather than lost in whatever the runtime does with a
        # dead thread. It is never swallowed — the store keeps the type and message, and the
        # full stack goes to stderr.
        try:
            info = STORE.warm()
        except BaseException:
            traceback.print_exc()
            print("[realdoor] the warm FAILED; /api/health will answer 503 until it is fixed",
                  flush=True)
            return
        print(f"[realdoor] warmed {info['documents']} documents · {info['engine']}",
              flush=True)
        if not info["documents"]:
            print("[realdoor] the warm finished with ZERO documents; /api/health will "
                  "answer 503 because a session created now would be empty", flush=True)

    threading.Thread(target=_warm, name="realdoor-warm", daemon=True).start()
    print("[realdoor] serving; warming in the background", flush=True)


def _session(x_session_id: str | None):
    if not x_session_id:
        raise HTTPException(400, "missing X-Session-Id header; POST /api/session first")
    s = STORE.get(x_session_id)
    if s is None:
        raise HTTPException(404, "session not found or already deleted")
    return s


def _household_of(s, document_id: str) -> str:
    """이 문서가 속한 파일의 id. 업로드는 세션 자신의 파일(YOUR-UPLOADS)에 산다.

    팩 문서 id 는 `HH-001-D02` 꼴이라 rsplit 으로 세대가 나오지만, 업로드 id
    (`UP-xxxxxxxx`)에는 그런 구조가 없다 — 구조를 흉내 내는 대신 소속을 직접 본다.
    """
    if document_id in s.uploads:
        return UPLOADS_HOUSEHOLD_ID
    return document_id.rsplit("-", 1)[0]


# ── 기본 ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health() -> Response:
    """Whether this process can actually serve the thing it exists to serve.

    It used to return {"ok": true} unconditionally, which made it a check on whether the
    port was open — a question the TCP connect already answered. Meanwhile the deployed
    server held zero documents and handed every caller {"households": []} with a 200. A
    health check that cannot fail is not a health check, it is a decoration.

    So it reports the readiness of the pack itself:

      warm "running"    → 200. Booting is not a fault. `Store.new_session()` waits for the
                          warm, so a session created right now still gets its documents;
                          the only cost is that the first request is slow.
      warm "completed"  → 200 if documents_loaded > 0. This is the normal steady state.
                        → 503 if documents_loaded == 0. Nothing raised, and nothing loaded:
                          every session from here on is born empty and no later call
                          repairs it. This is the shape of the outage we shipped.
      warm "failed"     → 503, with the exception type and message in `warm_error`, so the
                          reason is in the body of the check rather than in a container log
                          nobody is tailing.

    `ok`, `engine_version`, `active_sessions` and `notice` keep their meaning and their
    names: ui/dist/app.js reads `ok` to decide whether to adopt the same-origin API, and
    ui/tools/*.mjs read `active_sessions`. The readiness fields are additions.
    """
    warm = STORE.warm_report()
    serving = warm["phase"] == "running" or (
        warm["phase"] == "completed" and warm["documents_loaded"] > 0)
    if warm["phase"] == "failed":
        detail = ("The document warm raised. No session created by this process will hold "
                  "the pack, and this instance should not take traffic.")
    elif warm["phase"] == "running":
        detail = ("The document warm is still going. A session created now waits for it "
                  "rather than being born empty, so this instance can take traffic.")
    elif warm["documents_loaded"]:
        detail = "The pack is loaded."
    else:
        detail = ("The document warm finished without raising and loaded nothing. Every "
                  "session this process hands out would be empty.")

    body = {
        "ok": serving,
        "engine_version": engine_version(),
        "active_sessions": STORE.session_count,
        # The documents are the reason this service exists. Without the count in the
        # check, a process holding zero of them and one holding all 24 give the same
        # answer, which is how tonight's outage stayed invisible.
        "documents_loaded": warm["documents_loaded"],
        "warm": warm["phase"],
        "warm_error": warm["error"],
        "detail": detail,
        # 화면과 같은 순서로 말한다: 무엇을 하는지 먼저, 경계는 이유와 함께 뒤에.
        # 서버가 화면과 다른 말을 하면 그것도 어긋남이다.
        "notice": ("This service gets a file to the person who decides, complete the first "
                   "time it is handed over. It never decides eligibility itself."),
    }
    return JSONResponse(status_code=200 if serving else 503, content=body)


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
    # `region` 은 **추가 전용** 키다: 인라인 편집기에서 세입자가 페이지 위에 그린
    # 사각형이 정정과 함께 온다. 검증은 읽기 엔드포인트와 같은 함수가 한다 — 커밋
    # 경로만 검증이 느슨하면 화면을 거치지 않은 호출이 페이지 밖 좌표를 기록으로 남긴다.
    region = payload.get("region")
    if region is not None:
        from api import region as region_mod

        if not isinstance(region, dict):
            raise HTTPException(400, {"code": "bad_region",
                                      "detail": "`region` must be an object"})
        _, view = region_mod.resolve_document(s, payload["document_id"])
        page_number, box = region_mod.validate_region(
            view, region.get("page"), region.get("box"))
        region = {"page": page_number, "box": box,
                  "machine_suggestion_shown": bool(region.get("machine_suggestion_shown"))}
    outcome = STORE.apply_correction(s, payload["document_id"], payload["field"],
                                     payload["value"],
                                     together=bool(payload.get("together")),
                                     region=region)
    if outcome == "no_such_field":
        raise HTTPException(404, "no such field on that document")
    if outcome == "nothing_was_read":
        raise HTTPException(
            400, "this field was not read from the document, so there is nothing to "
                 "confirm; send the value it should hold instead")
    hid = _household_of(s, payload["document_id"])
    rep = STORE.report(s, hid)
    if rep is None:
        raise HTTPException(404, f"unknown household {hid}")
    return rep


def _absence_response(s, document_id: str) -> dict:
    """부재 확인·철회 뒤에 화면이 다시 그릴 대상을 돌려준다.

    업로드는 세대에 합류하지 않으므로(`api/upload.py` 모듈 문서) 리포트가 없다 —
    업로드 문서면 갱신된 업로드 뷰를, 팩 문서면 `/api/confirm` 과 같은 관례로 갱신된
    세대 리포트를 돌려준다. 부재는 계산을 움직이지 않지만, 화면이 서버 상태를 다시
    받아 그리는 왕복은 확인·정정과 같아야 한다 — 화면이 스스로 표시를 지어내기
    시작하면, 화면 버그 하나가 아무도 확인한 적 없는 부재를 확인된 것으로 만든다.
    """
    if document_id in s.uploads:
        return s.uploads[document_id]
    hid = document_id.rsplit("-", 1)[0]
    rep = STORE.report(s, hid)
    if rep is None:
        raise HTTPException(404, f"unknown household {hid}")
    return rep


@app.post("/api/absence")
def confirm_absence(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """세입자가 **값이 없는** 필드에 대해 "이 문서에는 이 값이 없다" 를 확인한다.

    브리프의 경계 선언이 이 제품의 산출물이라 부르는 것은 "document readiness and
    human-review handoff" 이고, 참가자 가이드의 준비도 관행은 빠진 필수 증거를
    NEEDS_REVIEW 로 보낸다. 그 인수인계에서 검토자가 알아야 하는 것은 두 가지가
    구분되는가다: 추출기가 못 읽은 것인가, 신청자가 페이지를 보고 "정말 없다" 고
    확인한 것인가. 확인된 값(`confirmed_by_renter`)은 있었지만 확인된 부재는 지금까지
    없었다. 이 라우트가 그 절반을 채운다.

    **추가 전용이다.** `/api/confirm` 은 값(`value`)을 요구하고 그 계약은 테스트가
    고정하고 있으므로, 값이 없는 확인은 자기 엔드포인트를 갖는다. 계약 §1 의 동결
    enum(`evidence_kind`, `certainty`)은 늘리지 않는다 — 부재 확인은 활동 기록의
    이벤트 + 표시용 주석이지 새 enum 값이 아니다. 근거는 `api/store.py::confirm_absence`.
    """
    s = _session(x_session_id)
    for key in ("document_id", "field"):
        if key not in payload:
            raise HTTPException(400, f"missing `{key}`")
    outcome = STORE.confirm_absence(s, payload["document_id"], payload["field"])
    if outcome == "no_such_field":
        raise HTTPException(404, "no such field on that document")
    if outcome == "value_was_read":
        raise HTTPException(
            400, "this field holds a value, so there is no absence to confirm; "
                 "confirm or correct the value instead")
    return _absence_response(s, payload["document_id"])


@app.post("/api/absence/undo")
def withdraw_absence(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """한 부재 확인을 철회한다 — `/api/undo` 가 확인 철회에 대해 하는 일의 거울.

    부재 확인도 사람의 주장이므로 철회 가능해야 한다. 걷어낸 뒤 필드는 주석이 붙기
    전과 완전히 같다: 값도 certainty 도 evidence_kind 도 처음부터 움직인 적이 없다.
    """
    s = _session(x_session_id)
    for key in ("document_id", "field"):
        if key not in payload:
            raise HTTPException(400, f"missing `{key}`")
    if not STORE.withdraw_absence(s, payload["document_id"], payload["field"]):
        raise HTTPException(404, "no absence check on that field to withdraw")
    return _absence_response(s, payload["document_id"])


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
    hid = _household_of(s, payload["document_id"])
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
        "accepted": "application/pdf, image/png, image/jpeg",
        "notice": ("Upload synthetic documents only. Everything you upload stays in this "
                   "session's memory, is never written to disk, and is never used to train "
                   "anything."),
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 document_type: str = Form(""),
                 content_length: int | None = Header(default=None),
                 x_session_id: str | None = Header(default=None)) -> dict:
    """올린 PDF 파일을 읽고 **근거와 함께** 돌려준다. 결합 문서면 페이지별로 쪼갠다.

    `document_type` 은 선택이다. 비워서 보내면 서버가 페이지를 하나씩 훑어 각 페이지의
    **인쇄된 제목**에서 종류를 지명하고(`api/nominate.py` — 닫힌 표, 완전 일치), 제목이
    바뀌는 자리에서 하위 문서를 가른다(`api/upload.py::segment_pages`). 제목 없는 페이지는
    앞 문서를 잇는다 — 제목 없는 2쪽짜리 급여명세서는 한 문서다. 지명은 근거(일치한 인쇄
    문구 + 페이지/좌표)와 함께 하위 문서마다 `nomination` 으로 실린다.

    첫 페이지가 스스로를 밝히지 못하면(스캔·표에 없는 제목·상충하는 제목) 질문으로 막지
    않고 **보이는 기본값**(`pay_stub`)으로 읽어 결과를 곧바로 보여 주며, 종류 선택은
    결과 옆에 "그 종류가 아니면 여기서 바꾸세요"로 함께 둔다(item 3). 사람이 "읽기"를
    누르면 질문이 아니라 읽기가 돌아 나간다. 파일 이름에서는 여전히 추측하지 않는다.

    응답은 첫 하위 문서를 top-level 로 펴고, `sub_documents` 에 전부를, `file` 에 파일
    단위 집계를 싣는다. 결과는 세션 메모리에만 담긴다 — 그 이유는 `api/upload.py` 모듈
    문서에 적혀 있다.
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
    file_name = file.filename or "upload.pdf"
    try:
        chosen_type = (document_type or "").strip()
        if chosen_type:
            # 사람이 종류를 골랐다(또는 "종류 바꾸기"). 파일 전체를 그 한 종류로 읽는다 —
            # 명시적 선택이 페이지별 분절보다 우선한다. validate 가 지원 종류 + 바이트를
            # 함께 검사한다.
            doc_type = upload_mod.validate(data, file_name, file.content_type, chosen_type)
        else:
            # 종류가 오지 않았다. 분절은 PDF 를 실제로 열므로 바이트 검사가 먼저다 —
            # 순서를 바꾸면 10MB 상한이나 매직바이트 검사가 분절 뒤로 밀린다. 페이지별
            # 지명 + item 3 의 보이는 기본값은 add_upload 안(read_document_file)에서 돈다.
            upload_mod.validate_bytes(data, file.content_type)
        # 바이트 검사를 통과했으면, 이미지(PNG/JPEG)는 여기서 한 장짜리 PDF 로 감싼다.
        # 이 지점 이후로 저장·분절·OCR·렌더에 흐르는 바이트는 언제나 PDF 라, 이미지용
        # 분기가 아래 어디에도 생기지 않는다 — 이미지는 스캔본과 똑같은 경로를 탄다.
        # PDF 는 손대지 않으므로 기존 PDF 업로드는 바이트 단위로 같다.
        data = upload_mod.normalize_to_pdf(data)
        response = STORE.add_upload(s, data, file_name,
                                    explicit_type=doc_type if chosen_type else None)
    except upload_mod.UploadRejected as exc:
        raise HTTPException(400, {"code": exc.code, "detail": exc.message}) from exc
    return response


@app.post("/api/upload/{upload_id}/retype")
def retype_upload(upload_id: str, payload: dict,
                  x_session_id: str | None = Header(default=None)) -> dict:
    """올린 하위 문서 **한 장**을 사람이 고른 종류로 다시 읽는다 (item 3 의 한 클릭 정정).

    페이지가 스스로를 밝히지 못해 보이는 기본값(pay_stub)으로 읽혔거나, 지명이 틀렸을 때
    세입자가 결과 옆에서 종류를 골라 그 하위 문서만 다시 읽게 한다. 같은 파일의 다른 하위
    문서는 건드리지 않는다. 갱신된 파일 응답을 돌려줘 화면이 그대로 다시 그린다.
    """
    from api import upload as upload_mod

    s = _session(x_session_id)
    document_type = payload.get("document_type")
    if not document_type:
        raise HTTPException(400, {"code": "document_type_required",
                                  "detail": "Choose the kind of document to read it as."})
    try:
        response = STORE.retype_upload(s, upload_id, str(document_type))
    except upload_mod.UploadRejected as exc:
        raise HTTPException(400, {"code": exc.code, "detail": exc.message}) from exc
    if response is None:
        raise HTTPException(404, f"unknown upload {upload_id}")
    return response


@app.delete("/api/upload/{upload_id}")
def remove_upload(upload_id: str,
                  x_session_id: str | None = Header(default=None)) -> dict:
    """올린 문서 **한 장**을 세션에서 걷어낸다.

    세션 전체 삭제(6단계)만 있던 자리의 반쪽: 문서 하나를 잘못 올렸을 때 전부를
    버릴 필요가 없어야 한다. 걷어낸 뒤에는 그 문서의 바이트·뷰·정정·부재 확인이
    프로세스 어디에도 남지 않고, 업로드 상한 여섯 자리 중 하나가 돌아오며,
    업로드 파일(YOUR-UPLOADS)의 리포트·체크리스트·패킷은 다음 조회에서 남은
    문서만으로 다시 계산된다 — 리포트는 항상 재계산이므로(§store 설계 원칙 3)
    여기서 따로 할 일이 없다. 마지막 한 장을 걷어내면 파일 자체가 목록에서
    사라진다. 활동 기록에는 값 없는 이벤트(`document_removed`, 문서 id 만)가
    남는다. 다른 문서의 정정·확인은 한 글자도 움직이지 않는다.
    """
    s = _session(x_session_id)
    if not STORE.remove_upload(s, upload_id):
        raise HTTPException(404, f"unknown upload {upload_id}")
    return {"removed": True, "document_id": upload_id,
            "uploads_remaining": len(s.uploads)}


#: pdfium 직렬화 락. FastAPI 는 동기 엔드포인트를 스레드풀에서 돌리므로, 화면이 페이지
#: 이미지 두 장을 동시에 요청하면(업로드 패널 + 문서 패널이 함께 살아 있을 때 실제로
#: 일어난다) pdfium 네이티브 렌더가 겹친다. pdfium 은 스레드 안전하지 않고, 그 겹침은
#: 예외가 아니라 **access violation 으로 프로세스 전체를 죽였다** (2026-07 실측:
#: FPDF_RenderPageBitmap / FPDF_CloseDocument). core/render.py 는 이 프로세스 모델을
#: 모르는 순수 함수이므로, 동시성이 생기는 이 층에서 렌더 호출을 직렬화한다.
#: 비용은 이미지 응답의 순차화 하나 — 죽은 서버보다 느린 이미지가 낫다.
#: 업로드가 결합 PDF 를 페이지 범위별 하위 PDF 로 쪼갤 때(api/upload.py) 도 pdfium 을
#: 부르므로 그 겹침도 같은 락으로 막아야 한다. 그래서 락은 두 모듈이 함께 import 하는
#: api/store.py 에 두고, 여기서는 그 하나를 가리킨다.
_RENDER_LOCK = PDFIUM_LOCK


@app.get("/api/upload/{upload_id}/page/{page}.png")
def upload_page_png(upload_id: str, page: int,
                    x_session_id: str | None = Header(default=None)) -> Response:
    """올린 문서의 페이지 이미지. 원본 바이트는 세션 메모리에서만 나온다."""
    from core.render import render_page_png

    s = _session(x_session_id)
    data = s.upload_bytes.get(upload_id)
    if data is None:
        raise HTTPException(404, f"unknown upload {upload_id}")
    with _RENDER_LOCK:
        img = render_page_png(data, page_number=page)
    return Response(content=img.png_bytes, media_type="image/png",
                    headers={"X-Image-Scale": str(img.scale),
                             "X-Image-Width": str(img.width_px),
                             "X-Image-Height": str(img.height_px)})


# ── 페이지 이미지 (UI가 근거 상자를 그리는 바탕) ────────────────────────
@app.get("/api/document/{document_id}/page/{page}.png")
def page_png(document_id: str, page: int,
             x_session_id: str | None = Header(default=None)) -> Response:
    """팩 문서든 업로드든 **한 URL**로 페이지 이미지가 나온다.

    업로드 파일이 팩 세대와 같은 화면 기계를 타려면 화면이 문서마다 이미지 주소를
    갈라 짚을 필요가 없어야 한다. 업로드의 원본 바이트는 세션 메모리에서만 나온다 —
    `/api/upload/{id}/page/{n}.png` 는 업로드 패널이 계속 쓰므로 그대로 남는다.
    """
    from core.render import render_page_png

    s = _session(x_session_id)
    if document_id in s.uploads:
        data = s.upload_bytes.get(document_id)
        if data is None:
            raise HTTPException(404, f"unknown document {document_id}")
        with _RENDER_LOCK:
            img = render_page_png(data, page_number=page)
    else:
        view = s.views.get(document_id)
        if view is None:
            raise HTTPException(404, f"unknown document {document_id}")
        with _RENDER_LOCK:
            img = render_page_png(str(DOCS / view["file_name"]), page_number=page)
    return Response(content=img.png_bytes, media_type="image/png",
                    headers={"X-Image-Scale": str(img.scale),
                             "X-Image-Width": str(img.width_px),
                             "X-Image-Height": str(img.height_px)})


# ── 사각형 읽기 (인라인 편집기의 "Point at it on the page") ─────────────
@app.post("/api/document/{document_id}/read-region")
def read_region(document_id: str, payload: dict,
                x_session_id: str | None = Header(default=None)) -> dict:
    """세입자가 그린 사각형 하나를 읽어 **제안**을 돌려준다.

    제안은 자동으로 어디에도 기록되지 않는다 — 입력칸을 채울 뿐이고, 기록은 세입자가
    저장을 눌러 `/api/confirm` 을 거칠 때만 생긴다. 경계·크기 검증과 세션 격리는
    `api/region.py` 가 강제한다.
    """
    from api import region as region_mod

    s = _session(x_session_id)
    return region_mod.read_region(s, document_id, payload)


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
def _fmt_value(value) -> str:
    """리포트가 든 값을 사람이 읽을 표기로. 2166.0 → 2166, 나머지는 그대로."""
    if value is None:
        return ""
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _packet_summary_html(rep: dict, originals: dict) -> str:
    """패킷의 표지 — 사람이 읽는 한 장.

    패킷의 나머지(두 JSON)는 사무소의 검토 도구를 위한 것이고, 지금까지 그 사실을
    아무 데도 적지 않았다. 이 파일이 그 공백을 메운다: 패킷이 **누구에게** 가는
    문서인지 첫 줄에 말하고, 사람이 읽을 수 있는 형태로 프로필·공백·확인 내역을
    담는다.

    렌더링 규칙 셋:
      * `rep` 에 실린 값만 싣는다 — 정정된 값 포함, 서버가 지금 알고 있는 그대로.
        정정 이전의 기계 판독값만은 `rep` 에 없으므로 세션의 originals 스냅샷에서
        온다. 정정은 증거 **옆의 주석**이지 증거의 변경이 아니다 — 원본 문서는
        재렌더링되지 않고, 그 경계를 본문이 한 줄로 말한다.
      * 5단계 체크리스트가 이미 렌더하는 문장(`rep["plain"]["checklist"]`)을 그대로
        재사용한다. 같은 공백을 두 벌의 문장으로 설명하면 언젠가 갈라진다.
      * 자기완결: 인라인 CSS만, 외부 리소스 없음, JS 없음. 패킷은 영원히 오프라인로
        열려야 한다.
      * 판정 어휘 금지 목록(eval/test_no_decision.py)의 토큰은 본문 어디에도 쓰지
        않는다. 결정을 이름으로 부르지 않고 "the person who decides" 라고만 부른다.
    """
    from html import escape

    from api.plain import DOC_NAMES

    hid = escape(str(rep.get("household_id", "")))
    tally = rep.get("confirmation") or {}
    plain_checklist = (rep.get("plain") or {}).get("checklist") or {}

    # ── the profile, one table per document ─────────────────────────────
    doc_sections: list[str] = []
    for doc in rep.get("documents", []):
        doc_id = str(doc.get("document_id", ""))
        name = DOC_NAMES.get(str(doc.get("document_type", "")),
                             str(doc.get("document_type", "document")).replace("_", " "))
        title = name[:1].upper() + name[1:]
        dated = f" (dated {escape(str(doc.get('document_date')))})" if doc.get("document_date") else ""
        rows: list[str] = []
        for f in doc.get("fields", []):
            field_name = escape(str(f.get("field", "")).replace("_", " "))
            value = f.get("value")
            kind = f.get("evidence_kind")
            if value is None:
                where = "&mdash;"
                note = escape(str(f.get("notes") or "")) or "nothing usable was found on the page"
                if f.get("absence_confirmed_by_renter"):
                    # 확인된 부재는 기계가 읽지 못한 부재와 **다른 문장**을 받는다.
                    # 검토자가 이 칸에서 알아야 하는 것이 바로 그 구분이다: 아래 줄은
                    # "사람이 페이지를 봤고, 값이 정말 거기 없다" 이고, else 가지는
                    # "기계가 값을 얻지 못했고 아무도 아직 안 봤다" 다. 기계의 원문
                    # 기록(note)은 옮겨질 뿐 지워지지 않는다.
                    checked = escape(str(f.get("absence_confirmed_on") or ""))
                    when = f" on {checked}" if checked else ""
                    standing = (f"applicant confirmed: not shown on this document"
                                f" (checked{when}; machine note kept on file: {note})")
                else:
                    # R26: 표지의 독자는 검토자이고, "기계가 값을 얻지 못했다"에서 멈추면
                    # 검토자의 다음 행동이 없다. 부재 확인 가지(위)는 "신청자가 이미
                    # 확인했다"를 싣고, 이 가지는 "신청자에게 무엇을 요청할지"를 싣는다.
                    standing = (f"not read &mdash; the machine took no value here ({note}). "
                                "If the review needs this value, ask the applicant for a "
                                "copy of the document that shows it")
                shown = "&mdash;"
            else:
                page = f.get("page")
                box = "source box recorded" if f.get("bbox") else "no source box on file"
                where = f"page {escape(str(page))} &middot; {box}" if page else box
                shown = escape(_fmt_value(value))
                if kind == "corrected_by_renter":
                    snapshot = originals.get((doc_id, str(f.get("field"))))
                    machine = _fmt_value(snapshot.get("value")) if snapshot else ""
                    if machine:
                        standing = (f"machine read {escape(machine)}; "
                                    f"applicant corrected to {escape(_fmt_value(value))}")
                    else:
                        standing = "corrected by the applicant"
                    # 세입자가 페이지 위를 직접 가리킨 정정은 그 사각형이 검토자에게
                    # 전달된다. 기계의 page/bbox 는 위의 "where" 칸에 그대로 있다 —
                    # 이 줄은 추가 주석이지 그 좌표의 수정이 아니다.
                    marked = f.get("region_marked_by_renter")
                    if marked:
                        box_words = ", ".join(str(v) for v in (marked.get("box") or []))
                        standing += (f"; applicant pointed at page "
                                     f"{escape(str(marked.get('page')))}, region "
                                     f"[{escape(box_words)}]")
                        standing += (
                            " (the machine's reading of that region was shown to the "
                            "applicant as a suggestion beside the marked area)"
                            if marked.get("machine_suggestion_shown") else
                            " (the machine could not read that region; the applicant "
                            "typed the value)")
                elif kind == "confirmed_by_renter":
                    standing = "machine-read; confirmed by the applicant"
                else:
                    standing = "machine-read; not yet checked by a person"
            rows.append(
                f"<tr><th scope=\"row\">{field_name}</th><td>{shown}</td>"
                f"<td>{where}</td><td>{standing}</td></tr>"
            )
        doc_sections.append(
            f"<h3>{escape(title)} &mdash; {escape(str(doc.get('file_name', '')))}{dated}</h3>\n"
            "<table><thead><tr><th scope=\"col\">Value</th><th scope=\"col\">As it stands</th>"
            "<th scope=\"col\">Where it came from</th><th scope=\"col\">Standing</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    # ── what is still open: the step-5 checklist wording, verbatim ──────
    open_items: list[str] = []
    for item in rep.get("checklist", []):
        if item.get("state") == "present":
            continue
        wording = plain_checklist.get(str(item.get("item_id", ""))) or {}
        headline = escape(str(wording.get("headline") or item.get("label") or ""))
        body = escape(str(wording.get("body") or item.get("detail") or ""))
        action = escape(str(wording.get("action") or ""))
        detail = escape(str(item.get("detail") or ""))
        block = [f"<h3>{headline}</h3>", f"<p>{body}</p>"]
        if action:
            block.append(f"<p><strong>Next step:</strong> {action}</p>")
        if detail:
            block.append(f"<p class=\"machine\">On the record: {detail}</p>")
        open_items.append("\n".join(block))
    if open_items:
        gaps = "\n".join(open_items)
    else:
        # The same sentence step 5 shows when the list is clear.
        gaps = "<p>Nothing. Every required item is present and current.</p>"

    # ── the tally, in a sentence rather than an exam mark ───────────────
    seen = int(tally.get("confirmed", 0)) + int(tally.get("corrected", 0))
    readable = int(tally.get("fields", 0)) - int(tally.get("not_read", 0))
    tally_text = (
        f"The applicant checked {seen} of the {readable} values the machine read: "
        f"{tally.get('confirmed', 0)} value(s) confirmed as read correctly and "
        f"{tally.get('corrected', 0)} value(s) corrected. "
        f"The other {tally.get('not_confirmed', 0)} value(s) still carry only the machine "
        "reading. Checking is optional and an unchecked value is not an error &mdash; it "
        "travels marked as read by the machine and not yet confirmed by a person, and the "
        "reviewer can weigh it either way."
    )
    if tally.get("not_read"):
        tally_text += (f" {tally.get('not_read', 0)} value(s) could not be read at all; "
                       "those need a person to supply them.")
    if tally.get("confirmed_absent"):
        # 기계가 읽지 못한 것(위)과 사람이 부재를 확인한 것(아래)은 다른 사건이고,
        # 검토자에게는 그 차이가 정보다. 키 자체가 0일 때는 존재하지 않으므로
        # (api/store.py::confirmation_tally), 이 문장은 실제로 일어난 세션에만 실린다.
        tally_text += (
            f" For {tally.get('confirmed_absent', 0)} of the values the machine could not "
            "read, the applicant looked at the page and confirmed the document does not "
            "show it &mdash; a person checked the absence, which is not the same as the "
            "machine simply reading nothing."
        )

    # ── abstentions: what was not said, and why ─────────────────────────
    abstention_rows: list[str] = []
    for entry in rep.get("abstentions", []):
        about = escape(str(entry.get("about", "")))
        reason = escape(str(entry.get("reason", "")))
        fix = escape(str(entry.get("what_would_resolve_it", "")))
        abstention_rows.append(
            f"<li><strong>{about}</strong>: {reason}"
            + (f" <em>What would clear it: {fix}</em>" if fix else "") + "</li>"
        )
    abstentions = ("<ul>" + "".join(abstention_rows) + "</ul>") if abstention_rows else \
        "<p>None for this file. Every figure this sheet carries could be read and traced.</p>"

    status = str(rep.get("readiness_status", ""))
    if status == "READY_TO_REVIEW":
        status_line = ("READY_TO_REVIEW &mdash; a person can start reading this file. "
                       "That says nothing about what they will say.")
    else:
        status_line = ("NEEDS_REVIEW &mdash; something in this file is still open: "
                       "missing, out of date, or not settled. The open points are "
                       "listed below. This is about the paperwork, not the person.")

    ruleset = escape(str(rep.get("ruleset_version", "")))
    reference = escape(str(rep.get("reference_date", "")))
    engine = escape(str(rep.get("engine_version", "")))
    generated = escape(str(rep.get("generated_at", "")))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Readiness packet cover sheet &mdash; {hid}</title>
<style>
  body {{ font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; margin: 2rem auto;
         max-width: 46rem; padding: 0 1rem; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; border-bottom: 3px solid #1a1a1a; padding-bottom: .4rem; }}
  h2 {{ font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #999; padding-bottom: .2rem; }}
  h3 {{ font-size: 1rem; margin-top: 1.2rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .85rem;
           font-family: Helvetica, Arial, sans-serif; }}
  th, td {{ border: 1px solid #bbb; padding: .3rem .5rem; text-align: left;
            vertical-align: top; }}
  thead th {{ background: #eee; }}
  .who {{ font-size: 1.02rem; }}
  .machine {{ font-family: monospace; font-size: .78rem; color: #444; }}
  .boundary {{ border-left: 4px solid #1a1a1a; padding: .5rem .8rem; background: #f4f4f4; }}
  footer {{ margin-top: 2.5rem; border-top: 1px solid #999; padding-top: .8rem;
            font-size: .85rem; color: #333; }}
  @media print {{ body {{ margin: 0; max-width: none; }} a {{ color: inherit; }} }}
</style>
</head>
<body>
<h1>Readiness packet &mdash; cover sheet</h1>
<p class="who"><strong>Who this packet is for.</strong> It goes to the reviewing housing
professional at the housing office &mdash; the person who decides on the application. The
applicant prepared it with RealDoor and carries it to that person. The two JSON files
beside this sheet are for the office&rsquo;s review tooling. The applicant was never meant
to read them. This sheet says, in plain words, what a person needs from them.</p>
<p><strong>What this sheet is not.</strong> It is not a determination of any kind. It does
not say what should happen with the application. The person who decides makes that call,
with checks that are not in these papers.</p>
<p class="machine">File {hid} &middot; generated {generated} &middot; {status_line}</p>

<h2>The profile as it stands</h2>
<p>Every value below was read from a page of the documents in this packet. Each row says
which document and page it came from; the exact source box on that page is recorded in
readiness_report.json. Where the applicant corrected a reading, the row shows both the
machine&rsquo;s reading and the applicant&rsquo;s correction.</p>
<p class="boundary">A correction is a note beside the evidence, never a change to it. The
original documents in this packet are not re-rendered or modified in any way &mdash; what
the applicant corrected is this tool&rsquo;s reading of the page, not the page itself.</p>
{''.join(doc_sections)}

<h2>What is still missing, expired, or undatable</h2>
{gaps}

<h2>What a person has checked</h2>
<p>{tally_text}</p>

<h2>Things this tool did not say</h2>
<p>When this tool could not read, date, or trace a figure, it said so instead of
guessing. Each entry below is one of those refusals, with its reason.</p>
{abstentions}

<footer>
<p>Ruleset {ruleset} &middot; reference date {reference} &middot; engine {engine}. The
same versions appear in the machine-readable files, so the office can check that this
sheet and the records agree.</p>
<p>Nothing in this packet was sent anywhere by RealDoor. Sharing it is the
applicant&rsquo;s choice, made outside the tool.</p>
</footer>
</body>
</html>
"""


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
        # 표지가 맨 앞에 온다. 사람이 이 ZIP 을 열면 처음 보는 파일이 사람을 위한
        # 파일이어야 한다. 두 JSON 은 아래에 **바이트 하나 바뀌지 않고** 그대로 있다 —
        # 이 표지는 추가이지 재구성이 아니다 (api/test_packet_summary.py 가 잰다).
        z.writestr("packet_summary.html", _packet_summary_html(rep, s.originals))
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
        # README 는 주소록이다. 첫 줄이 패킷 전체의 수신인을 말하고, 그 다음은 파일마다
        # 한 줄씩 "누구를 위한 파일인지"다. 확인 집계는 표지(packet_summary.html)로
        # 옮겨 갔다 — 집계는 사람이 읽는 문서의 일이고, 이제 그 문서가 생겼다.
        #
        # 부재 확인 한 줄은 예외로 여기에도 실린다: 있을 때만. 부재 확인이 0인 세션의
        # README 는 한 글자도 달라지지 않는다 — 거의 모든 파일에 없는 상태를 모든
        # README 에 0으로 적으면 그것이 목표처럼 읽히고, 표지의 집계 문단과도 어긋난다.
        absent_checked = int((rep.get("confirmation") or {}).get("confirmed_absent") or 0)
        absence_line = "" if not absent_checked else (
            f"The applicant also checked {absent_checked} value(s) the machine could\n"
            "not read, and confirmed each one is not shown on its document. The\n"
            "cover sheet marks those rows, and the machine's own note stays with\n"
            "each of them.\n\n"
        )
        z.writestr("README.txt",
                   "This packet is for the person at the housing office who decides\n"
                   "on the application. You, the applicant, carry it to them.\n\n"
                   "RealDoor readiness packet - what each file is for\n"
                   "=================================================\n\n"
                   "packet_summary.html    For you and the reviewer - open this one.\n"
                   "                       It is the cover sheet: what the documents\n"
                   "                       show, what a person checked, and what is\n"
                   "                       still open, on one printable page.\n\n"
                   "readiness_report.json  For the office's review tooling. You do\n"
                   "                       not need to open it.\n\n"
                   "activity_log.json      For the office's review tooling. You do\n"
                   "                       not need to open it. It lists the actions\n"
                   "                       taken in this session, in order, with the\n"
                   "                       rule versions that applied. It holds no\n"
                   "                       document contents and no typed values.\n\n"
                   "documents/             The documents themselves, exactly as they\n"
                   "                       were read. A correction you made is a note\n"
                   "                       in the files above, never a change to a\n"
                   "                       document - no document here was altered.\n\n"
                   + absence_line +
                   "This packet is NOT an eligibility decision. A qualified\n"
                   "housing professional makes that determination.\n\n"
                   "Nothing here has been sent to any property or provider. Sharing it\n"
                   "is your choice.\n")
        # 두 업로드가 같은 파일 이름을 가질 수 있다(같은 문서를 두 번 올리면 실제로
        # 그렇게 된다). ZIP 은 같은 경로 두 개를 조용히 받아 주므로, 여기서 막지 않으면
        # 압축을 푼 쪽에서 한 파일이 다른 파일을 덮어쓴다. 겹치는 이름은 문서 id 로
        # 앞을 붙여 갈라놓는다 — 첫 파일의 경로는 그대로라 팩 세대의 패킷은 한 바이트도
        # 달라지지 않는다.
        used_names: set[str] = set()

        def _entry_name(doc: dict) -> str:
            name = str(doc.get("file_name", ""))
            if name in used_names:
                name = f"{doc.get('document_id', '')}_{name}"
            used_names.add(name)
            return f"documents/{name}"

        for doc in rep.get("documents", []):
            # 업로드 파일의 문서는 디스크에 없다 — 원본 바이트는 세션 메모리에만 있고,
            # 패킷에는 거기서 바로 실린다. 디스크에는 이번에도 아무것도 쓰지 않는다.
            doc_id = str(doc.get("document_id", ""))
            if doc_id in s.upload_bytes:
                z.writestr(_entry_name(doc), s.upload_bytes[doc_id])
                continue
            src = DOCS / doc["file_name"]
            if src.exists():
                z.write(src, _entry_name(doc))
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
    view = s.views.get(document_id) or s.uploads.get(document_id)
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
