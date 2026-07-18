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

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api import gate
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


@app.on_event("startup")
def _startup() -> None:
    info = STORE.warm()
    print(f"[realdoor] warmed {info['documents']} documents · {info['engine']}",
          flush=True)


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
        "notice": "This service reports readiness only. It never decides eligibility.",
    }


# ── 세션 (데모 6단계: 세션 삭제) ────────────────────────────────────────
@app.post("/api/session")
def create_session() -> dict:
    s = STORE.new_session()
    return {"session_id": s.session_id, "documents": len(s.views)}


@app.delete("/api/session/{session_id}")
def delete_session(session_id: str) -> dict:
    """폐기 후에는 프로세스 어디에도 남지 않는다. 이어지는 GET은 404가 된다."""
    existed = STORE.delete(session_id)
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


# ── 정정 (데모 2단계) ───────────────────────────────────────────────────
@app.post("/api/confirm")
def confirm(payload: dict, x_session_id: str | None = Header(default=None)) -> dict:
    """사람이 값을 확인·정정하면 하위 계산이 즉시 따라 움직인다."""
    s = _session(x_session_id)
    for key in ("document_id", "field", "value"):
        if key not in payload:
            raise HTTPException(400, f"missing `{key}`")
    ok = STORE.apply_correction(s, payload["document_id"], payload["field"],
                                payload["value"])
    if not ok:
        raise HTTPException(404, "no such field on that document")
    hid = payload["document_id"].rsplit("-", 1)[0]
    rep = STORE.report(s, hid)
    if rep is None:
        raise HTTPException(404, f"unknown household {hid}")
    return rep


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
        "eligible": True,          # ← 금지 키
        "score": 0.92,             # ← 금지 키
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
