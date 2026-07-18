# -*- coding: utf-8 -*-
"""
store.py — 추출 캐시 · 세대 조립 · 세션 관리.

설계 원칙
  1. **추출은 한 번만.** OCR은 문서당 수 초가 걸린다. 디스크 캐시(파일 크기+수정시각 키)로
     재시작해도 즉시 뜬다. 데모 중 로딩 대기 = 무대에서 죽는 지점이므로 제거한다.
  2. **세션은 메모리에만.** DB 없음. 프로세스가 죽으면 전부 사라진다.
     브리프의 "isolated or ephemeral processing" / "Never train on uploads"가
     약속이 아니라 **구조적 사실**이 된다. DELETE 후 GET이 404를 반환하는 것으로 시연한다.
  3. **리포트는 항상 재계산.** 사용자가 필드를 고치면(§confirm) 하위 값이 즉시 따라 움직여야
     한다(데모 2단계). 캐시하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import plain
from core.extract import extract_document
from logic.household import (households_from_views, load_pack_checklists,
                             required_document_types)
from logic.readiness import build_report
from ocr.ocr_extract import extract_document_ocr

GOLD = ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"
DOCS = ROOT / "pack/synthetic_documents/documents"
CACHE = ROOT / ".cache/extractions"


def engine_version() -> str:
    """커밋 해시. 리포트에 박혀서 '어느 코드가 이 숫자를 냈는지'가 추적된다."""
    head = ROOT / ".git" / "HEAD"
    try:
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            sha = (ROOT / ".git" / ref[5:]).read_text(encoding="utf-8").strip()
        else:
            sha = ref
        return f"sha:{sha[:12]}"
    except OSError:
        return "sha:unversioned"


def _cache_key(pdf: Path) -> str:
    st = pdf.stat()
    raw = f"{pdf.name}|{st.st_size}|{int(st.st_mtime)}|v1"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def extract_one(pdf: Path, rasterized: bool) -> dict[str, Any]:
    """캐시를 거친 단일 문서 추출. 텍스트 레이어가 있으면 core, 없으면 ocr."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{_cache_key(pdf)}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    view = extract_document_ocr(str(pdf)) if rasterized else extract_document(str(pdf))
    cached.write_text(json.dumps(view, ensure_ascii=False, default=str), encoding="utf-8")
    return view


def extract_all() -> list[dict[str, Any]]:
    """팩의 24개 문서 전부. 골드는 파일명과 rasterized 플래그를 얻는 데만 쓴다."""
    views = []
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        views.append(extract_one(DOCS / g["file_name"], bool(g.get("rasterized"))))
    return views


@dataclass
class Session:
    """한 사용자의 작업 공간. 메모리에만 존재한다."""

    session_id: str
    views: dict[str, dict[str, Any]]                       # document_id -> DocumentView
    corrections: dict[tuple[str, str], Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def log(self, action: str, **detail: Any) -> None:
        """동의·조작·규칙버전을 남긴다. **문서 원문은 절대 남기지 않는다.**
        브리프: "log consent, actions, and rule versions - not raw document contents"."""
        self.events.append({"action": action, **detail})


class Store:
    """프로세스 수명 동안의 상태 전부. 여기 밖에는 아무것도 저장되지 않는다."""

    def __init__(self) -> None:
        self._base: list[dict[str, Any]] = []
        self._sessions: dict[str, Session] = {}
        self._checklists = load_pack_checklists()

    # ── 부팅 ────────────────────────────────────────────────────────────
    def warm(self) -> dict[str, Any]:
        """서버 기동 시 1회. 캐시가 있으면 즉시, 없으면 여기서 OCR 비용을 치른다."""
        self._base = extract_all()
        return {"documents": len(self._base), "engine": engine_version()}

    # ── 세션 ────────────────────────────────────────────────────────────
    def new_session(self) -> Session:
        sid = uuid.uuid4().hex[:12]
        views = {v["document_id"]: json.loads(json.dumps(v, default=str))
                 for v in self._base}
        s = Session(session_id=sid, views=views)
        s.log("session_created")
        self._sessions[sid] = s
        return s

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def delete(self, sid: str) -> bool:
        """세션 폐기. 이 호출 이후 해당 데이터는 프로세스 어디에도 남지 않는다."""
        return self._sessions.pop(sid, None) is not None

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    # ── 조회 ────────────────────────────────────────────────────────────
    def households(self, s: Session) -> list[dict[str, Any]]:
        houses = households_from_views(list(s.views.values()))
        out = []
        for hid in sorted(houses):
            docs = houses[hid].documents
            out.append({
                "household_id": hid,
                "document_count": len(docs),
                "document_ids": [d.get("document_id") for d in docs],
            })
        return out

    def report(self, s: Session, household_id: str) -> dict[str, Any] | None:
        """`ReadinessReport` + 각 문서에 추출 필드(bbox 포함)를 병합.

        로직층의 리포트는 문서를 메타데이터로만 담는다. UI가 문서 위에 근거 상자를
        그리려면 필드와 좌표가 필요하므로, 그 병합은 이 층의 책임이다.
        """
        views = list(s.views.values())
        houses = households_from_views(views)
        house = houses.get(household_id)
        if house is None:
            return None

        rep = build_report(
            house,
            required_document_types(household_id, self._checklists),
            engine_version=engine_version(),
        )

        by_id = {v["document_id"]: v for v in views}
        for doc in rep.get("documents", []):
            v = by_id.get(doc.get("document_id"), {})
            doc["fields"] = v.get("fields", [])
            doc["page_count"] = v.get("page_count")
            doc["page_size_points"] = v.get("page_size_points")
            doc["state"] = v.get("state")
            doc["source"] = "ocr" if v.get("rasterized") else "text_layer"
        rep["session_id"] = s.session_id

        # 세입자용 평문 계층. **덧붙이기만 한다** — 로직층이 만든 정밀한 문자열은
        # 하나도 바꾸지 않고, 그 옆에 사람이 읽을 문장과 "그래서 뭘 하면 되는지"를
        # 얹는다. 기계 코드와 원문은 각 항목의 code/detail 로 계속 꺼낼 수 있다.
        rep["plain"] = plain.for_report(rep)
        return rep

    def apply_correction(self, s: Session, document_id: str, field_name: str,
                         value: Any) -> bool:
        """사람이 확인/정정한 값을 반영한다.

        정정된 값은 `evidence_kind`를 바꿔 기록한다 — 기계가 읽은 값과 사람이 고친 값을
        리포트에서 구분할 수 있어야 하기 때문이다.
        """
        view = s.views.get(document_id)
        if view is None:
            return False
        for f in view.get("fields", []):
            if f.get("field") == field_name:
                f["value"] = value
                f["certainty"] = "high"
                f["evidence_kind"] = "corrected_by_renter"
                s.corrections[(document_id, field_name)] = value
                s.log("field_corrected", document_id=document_id, field=field_name)
                return True
        return False


STORE = Store()
