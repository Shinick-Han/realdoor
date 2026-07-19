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


#: 추출 결과를 만들어 내는 코드 파일들. 이 파일들이 바뀌면 캐시된 추출은 **낡은 코드의 산물**이다.
ENGINE_SOURCES = (
    ROOT / "core/extract.py",
    ROOT / "core/render.py",
    ROOT / "ocr/ocr_extract.py",
)

_ENGINE_SHA: str | None = None


def engine_sha() -> str:
    """추출 엔진 **소스 내용**의 해시.

    `engine_version()`(커밋 해시)을 쓰지 않는 이유: 커밋 해시는 커밋해야 움직인다.
    작업 중인 트리에서 extract.py를 고쳐도 HEAD는 그대로이므로, 캐시는 낡은 추출을 계속
    내주고 우리는 고친 적 없는 코드를 측정하게 된다. 실제로 이번 작업 중 그렇게 깨진
    빌드가 한 번 통과했다. 내용 해시는 저장하는 순간 움직인다.

    프로세스 수명 동안 한 번만 계산한다 — 문서 24장마다 소스를 다시 읽을 이유가 없다.
    """
    global _ENGINE_SHA
    if _ENGINE_SHA is None:
        digest = hashlib.sha256()
        for source in ENGINE_SOURCES:
            digest.update(source.name.encode())
            try:
                digest.update(source.read_bytes())
            except OSError:
                # 파일이 사라졌다면 그 사실 자체가 키의 일부다. 조용히 무시하면 서로 다른
                # 두 트리가 같은 키를 쓰게 된다.
                digest.update(b"<missing>")
        _ENGINE_SHA = digest.hexdigest()[:12]
    return _ENGINE_SHA


def _cache_key(pdf: Path) -> str:
    st = pdf.stat()
    raw = f"{pdf.name}|{st.st_size}|{int(st.st_mtime)}|{engine_sha()}|v2"
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
    # 정정 **직전**의 필드 스냅샷. 정정을 되돌리려면 추출된 원값이 필요한데,
    # apply_correction 은 필드를 제자리에서 덮어쓰므로 여기 남겨두지 않으면 원값이 사라진다.
    # 키가 (document_id, field) 단위이므로 한 정정의 취소가 다른 정정을 건드리지 않는다.
    originals: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    # 사용자가 올린 문서. **팩 문서(`views`)와 같은 자루에 넣지 않는다** — 섞는 순간
    # 세대 계산·체크리스트·연소득이 골드 없는 문서를 먹기 시작하고, 그건 인수 데모가
    # 요구하지 않은 데다 근거 없는 추측을 요구한다. 여기 있는 것은 자기 자신에 대해서만 말한다.
    uploads: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 올린 PDF 원본 바이트. 페이지 이미지를 그리려면 필요한데, 디스크에 쓰지 않기로 했으므로
    # 세션 안에 들고 있는다. 세션이 폐기되면 이 사전도 같이 사라진다 — 그게 전부다.
    upload_bytes: dict[str, bytes] = field(default_factory=dict)

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
                key = (document_id, field_name)
                # 추출된 원값은 **첫 정정 때 한 번만** 보관한다. 같은 필드를 두 번 고쳐도
                # 취소는 기계가 읽은 값까지 돌아가야지, 직전 정정값에서 멈추면 안 된다.
                if key not in s.originals:
                    s.originals[key] = {
                        "value": f.get("value"),
                        "certainty": f.get("certainty"),
                        "evidence_kind": f.get("evidence_kind"),
                    }
                f["value"] = value
                f["certainty"] = "high"
                f["evidence_kind"] = "corrected_by_renter"
                s.corrections[key] = value
                s.log("field_corrected", document_id=document_id, field=field_name)
                return True
        return False

    # ── 업로드 (인수 데모 1단계: 문서를 올리고 추출 근거를 보인다) ─────────
    def add_upload(self, s: Session, data: bytes, file_name: str,
                   document_type: str) -> dict[str, Any]:
        """올린 문서를 읽어 **세션 메모리에만** 담는다. 디스크에 닿지 않는다."""
        from api import upload as upload_mod

        view = upload_mod.read_upload(data, file_name, document_type)
        # **직전 업로드는 여기서 사라진다.** 화면은 언제나 마지막에 올린 문서 하나만 보여주므로
        # 그 이상 들고 있을 이유가 없고, 들고 있으면 세션 메모리가 올린 만큼 계속 늘어난다.
        # 개수 상한을 두는 것보다 이쪽이 정직하다 — 상한은 "10장까지는 남아 있다"고 약속하는데
        # 그 약속을 쓰는 화면이 없다. 이렇게 하면 세션이 쥐는 문서 바이트는 항상 한 장분이다.
        s.uploads.clear()
        s.upload_bytes.clear()
        uid = view["upload_id"]
        s.uploads[uid] = view
        s.upload_bytes[uid] = data
        # 파일 이름도 원문도 남기지 않는다 — 브리프: "log consent, actions, and rule
        # versions - not raw document contents".
        s.log("document_uploaded", document_type=document_type,
              extraction_path=view["extraction_path"])
        return view

    def undo_correction(self, s: Session, document_id: str, field_name: str) -> bool:
        """한 정정만 되돌린다 — 그 필드를 추출된 값으로, 다른 정정은 건드리지 않고.

        화면은 취소 버튼 옆에서 "the report is back to the extracted values" 라고 말한다.
        그 문장이 사실이 되려면 되돌리기가 **서버 세션에서** 일어나야 한다. 정정은 세션의
        DocumentView 를 제자리에서 덮어쓰므로, 클라이언트가 자기 화면의 리포트만 되돌리면
        서버는 여전히 정정된 값을 들고 있고 다음 정정 때 그 값이 되살아난다.
        """
        key = (document_id, field_name)
        snapshot = s.originals.get(key)
        if snapshot is None:
            return False
        view = s.views.get(document_id)
        if view is None:
            return False
        for f in view.get("fields", []):
            if f.get("field") == field_name:
                f["value"] = snapshot["value"]
                f["certainty"] = snapshot["certainty"]
                f["evidence_kind"] = snapshot["evidence_kind"]
                s.originals.pop(key, None)
                s.corrections.pop(key, None)
                s.log("correction_undone", document_id=document_id, field=field_name)
                return True
        return False


STORE = Store()
