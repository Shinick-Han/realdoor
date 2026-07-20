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

import datetime
import hashlib
import json
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import plain
from core.extract import extract_document, tracking_layered_mapper
from logic.household import (households_from_views, load_pack_checklists,
                             required_document_types)
from logic.readiness import build_report
from ocr.ocr_extract import extract_document_ocr

GOLD = ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"
DOCS = ROOT / "pack/synthetic_documents/documents"
CACHE = ROOT / ".cache/extractions"

#: 세입자가 올린 문서들이 이루는 **세션 자신의 파일** 의 id. 팩 세대와 같은 기계
#: (리포트·정정·계산·체크리스트·패킷)를 그대로 타지만, 팩 세대의 자루에는 절대 섞이지
#: 않는다 — 업로드를 팩 세대에 편입하는 것은 근거 없는 추측(누구의 문서인지, 중복인지)을
#: 요구하고, 그 거절의 근거는 처음부터 팩의 무결성이었지 업로드끼리의 파일을 막는 것이
#: 아니었다. 업로드가 하나도 없으면 이 파일은 어디에도 나타나지 않는다.
UPLOADS_HOUSEHOLD_ID = "YOUR-UPLOADS"

#: 한 세션이 쥘 수 있는 업로드 문서 수. 바이트가 전부 세션 메모리에 살기 때문에 상한이
#: 있어야 한다(문서당 10MB까지 — api/upload.py). 여섯이면 팩의 가장 큰 세대(5문서)보다
#: 크고, 인수 데모 한 바퀴를 자기 문서로 걷기에 넉넉하다.
MAX_SESSION_UPLOADS = 6


def uploads_required_types(views: list[dict[str, Any]]) -> tuple[str, ...]:
    """업로드 파일의 필수 문서 목록 — **주최측 자신의 규칙을 그들의 데이터에서 읽은 것**
    이지 우리가 지어낸 정책이 아니다.

    `pack/evaluation/application_checklists.json` 의 여섯 시나리오가 조건부 패턴 하나를
    일관되게 부호화한다:

      * 기본 셋(application_summary, pay_stub, employment_letter)은 **모든** 시나리오가
        요구한다.
      * `benefit_letter` 는 수당 소득이 있는 시나리오(HH-003, HH-006)에서만 요구된다.
      * `gig_income_corroboration` 은 긱 명세서가 있는 시나리오(HH-004)에서만 요구되고,
        긱 명세서 **자신은 그것을 만족하지 못한다** — 자기 작성 문서이기 때문이다.
        팩 문서의 각주가 스스로 교차 확인을 요구하고, HH-004 골드도 gig_statement 를
        present 로 두면서 gig_income_corroboration 을 missing 으로 남긴다. 규칙 근거는
        CH-INCOME-001 의 "Sum independently documented recurring sources" 이며, 항목의
        인용은 팩 카드와 같은 길(evaluate_item 의 CH-READINESS-001 + 기권의
        GIG_INCOME_UNCORROBORATED 코드)을 그대로 탄다.

    같은 패턴을 세션이 실제로 쥔 문서에 적용한다. 수당 소득의 존재는 수당 서류로만
    알 수 있으므로(monthly_benefit 은 benefit_letter 의 필드다) 그 조건은 문서의 존재로
    판정된다.
    """
    present = {str(v.get("document_type") or "") for v in views}
    required = ["application_summary", "pay_stub", "employment_letter"]
    if "benefit_letter" in present:
        required.append("benefit_letter")
    if "gig_statement" in present:
        required.append("gig_income_corroboration")
    return tuple(required)


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
#:
#: `core/label_llm.py` 가 여기 있는 이유: 팩 추출도 이제 3단 매퍼를 쓰고, 모델이 무엇을
#: 이름 댈 수 있는지는 그 파일의 프롬프트·글로스·닫힌 집합이 정한다. 그 파일이 바뀌면
#: 캐시된 추출은 다른 어휘가 만든 산물이다.
ENGINE_SOURCES = (
    ROOT / "core/extract.py",
    ROOT / "core/render.py",
    ROOT / "ocr/ocr_extract.py",
    ROOT / "core/label_llm.py",
    # 임베디드 이미지 영역 OCR(REALDOOR_OCR_WORDS)의 소스. 캐시 키는 플래그 상태를 담지
    # 않으므로(루프 README 함정 1), 이 파일이 바뀌면 캐시된 추출은 낡은 코드의 산물이다.
    ROOT / "core/ocr_words.py",
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
                # 줄바꿈을 정규화하고 해시한다. 이게 없으면 이 해시는 코드가 아니라
                # **체크아웃한 플랫폼**을 식별한다: Windows 워킹트리는 CRLF, 컨테이너는
                # LF 이므로 같은 커밋의 같은 파일이 다른 해시를 낸다. 그러면 이 기계에서
                # 채운 캐시는 리눅스 컨테이너에서 단 한 건도 맞지 않는다. 한 줄도 다르지
                # 않은 코드가 다른 코드로 취급되는 것은 이 키가 답해야 할 질문이 아니다.
                digest.update(source.read_bytes().replace(b"\r\n", b"\n"))
            except OSError:
                # 파일이 사라졌다면 그 사실 자체가 키의 일부다. 조용히 무시하면 서로 다른
                # 두 트리가 같은 키를 쓰게 된다.
                digest.update(b"<missing>")
        _ENGINE_SHA = digest.hexdigest()[:12]
    return _ENGINE_SHA


def _label_model_key() -> str:
    """라벨 모델의 **켜짐 상태**를 캐시 키에 넣기 위한 조각.

    이게 없으면 캐시가 조용히 거짓말을 한다. 키가 있는 기계에서 한 번 돌리면 모델이
    참여한 추출이 `.cache/extractions` 에 눌러앉고, 나중에 키 없이 돌린 사람은 자기가
    표만으로 얻은 결과라고 믿으면서 **모델이 만든 캐시**를 읽는다. 두 상태가 같은 키를
    쓰는 한 "표만 썼을 때의 성능"이라는 문장은 검증할 수 없는 문장이 된다.

    모델 이름까지 넣는 이유는 같다 -- 다른 모델은 다른 어휘고, 다른 산물이다.
    """
    from core import label_llm

    return f"{int(label_llm.is_enabled())}:{label_llm.MODEL}"


def _cache_key(pdf: Path) -> str:
    """캐시 키. 문서는 **내용**으로 식별한다 -- 수정 시각이 아니라.

    처음에는 `st_mtime` 을 썼는데, 그러면 캐시는 이 기계에서만 맞는다. git 체크아웃은
    파일의 수정 시각을 체크아웃한 시각으로 새로 찍기 때문에, 컨테이너에 캐시를 실어
    보내도 키가 전부 어긋나 단 한 건도 적중하지 않는다. 실제로 배포 브랜치는 미리 채운
    캐시 466개를 싣고 다니면서 매 기동마다 8장을 다시 OCR 했고, 그게 87초짜리 부팅과
    512MB 호스트에서의 OOM 이었다. 내용 해시는 체크아웃을 견딘다.

    비용은 기동당 24개 PDF를 한 번 읽는 것이고, 그 파일들은 어차피 곧 열린다.
    """
    from ocr.ocr_extract import ocr_max_side

    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()[:16]
    raw = (f"{pdf.name}|{digest}|{engine_sha()}"
           f"|{_label_model_key()}|ocr{ocr_max_side()}|v4")
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def extract_one(pdf: Path, rasterized: bool) -> dict[str, Any]:
    """캐시를 거친 단일 문서 추출. 텍스트 레이어가 있으면 core, 없으면 ocr.

    팩 문서도 업로드와 같은 3단 매퍼(정본 표 → 유의어 표 → 모델)를 쓴다. 팩 루브릭이
    "Hidden tests may perturb names and values while retaining the schemas" 라고 예고한
    이상, 채점되는 문서가 팩의 어휘를 쓴다는 보장이 없기 때문이다. 표가 못 읽는 라벨에서만
    모델이 발동하므로, 어휘가 그대로인 문서에서는 1패스가 전부 잡고 모델은 호출조차
    되지 않는다 -- 그래서 이 변경은 팩 숫자를 움직이지 않으면서 낯선 어휘에서만 일한다.

    모델이 이름 댄 필드는 `MODEL_MAPPER_NOTE` 로 태깅되고 certainty="low" 로 남는다.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{_cache_key(pdf)}.json"
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    view = (
        extract_document_ocr(str(pdf))
        if rasterized
        else extract_document(str(pdf), fallback_mapper=tracking_layered_mapper())
    )
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


def same_value(submitted: Any, extracted: Any) -> bool:
    """세입자가 보낸 값이 기계가 읽은 값과 **같은 값인가**.

    입력칸을 미리 채워 두면 사용자는 `2280` 을 그대로 돌려보내는데, HTML 입력칸은 그것을
    문자열 `"2280"` 으로 돌려준다. 이걸 그대로 비교하면 아무것도 고치지 않은 사람이 전부
    "정정" 으로 기록되고, 확인이라는 상태는 영원히 도달할 수 없게 된다. 그래서 표기가
    아니라 값으로 비교한다: 양쪽이 수로 읽히면 수로, 아니면 공백을 다듬은 문자열로.

    ⚠️ 관대함의 상한: 숫자 표기(쉼표·앞뒤 공백·`2280` 대 `2280.0`)만 흡수한다. 내용이
    다르면 무조건 정정이다 — 애매하면 정정이 안전한 쪽이다. 확인은 "사람이 이 값을 보고
    맞다고 했다" 는 주장이므로, 잘못 붙으면 없느니만 못하다.
    """
    if submitted is None or extracted is None:
        return submitted is None and extracted is None
    if isinstance(submitted, bool) or isinstance(extracted, bool):
        return submitted is extracted
    try:
        return (float(str(submitted).replace(",", "").strip())
                == float(str(extracted).replace(",", "").strip()))
    except (TypeError, ValueError):
        pass
    return str(submitted).strip() == str(extracted).strip()


def confirmation_tally(rep: dict[str, Any]) -> dict[str, Any]:
    """이 세대의 필드가 각각 어느 상태인지 **세어서** 리포트에 싣는다.

    브리프 표제가 요구하는 것은 "human-confirmed profile" 이다. 화면이 "무엇이 아직
    확인되지 않았는가" 를 말하려면 그 수를 스스로 셀 수 있어야 하고, 세는 규칙이 화면과
    서버에 각각 있으면 언젠가 갈라진다. 그래서 여기서 한 번 센다.

    `not_read` 는 따로 센다 — 기계가 읽지 못한 필드는 '아직 확인 안 함' 이 아니라 애초에
    확인할 대상이 아니다. 둘을 한 칸에 합치면 화면이 도달할 수 없는 목표를 제시하게 된다.

    `confirmed_absent` 는 `not_read` 의 **부분집합**이다: 기계가 읽지 못한 필드 중,
    세입자가 페이지를 보고 "이 문서에는 이 값이 정말 없다" 고 확인한 것의 수. 팩의
    참가자 가이드가 말하는 준비도 관행에서 빠진 필수 증거는 NEEDS_REVIEW 를 낳는데,
    검토자는 "추출기가 놓쳤다" 와 "사람이 봤는데 정말 페이지에 없다" 를 구분할 수
    있어야 한다 — 이 수가 그 구분의 집계다. 0이면 키 자체를 싣지 않는다: (a) 패킷의
    JSON 은 바이트 단위로 동결된 캡처(api/packet_baseline/)와 대조되고, 부재 확인이
    한 건도 없는 세션의 리포트는 그 캡처와 한 바이트도 달라져선 안 된다. (b) 거의 모든
    파일에 없는 상태를 모든 리포트에 0으로 싣는 것은 목표처럼 읽힌다 — 부재 확인은
    할 일이 아니라 일어난 일의 기록이다.
    """
    confirmed = corrected = not_confirmed = not_read = confirmed_absent = 0
    for doc in rep.get("documents", []):
        for f in doc.get("fields", []):
            kind = f.get("evidence_kind")
            if kind == "confirmed_by_renter":
                confirmed += 1
            elif kind == "corrected_by_renter":
                corrected += 1
            elif f.get("value") is None:
                not_read += 1
                if f.get("absence_confirmed_by_renter"):
                    confirmed_absent += 1
            else:
                not_confirmed += 1
    tally = {
        "confirmed": confirmed,
        "corrected": corrected,
        "not_confirmed": not_confirmed,
        "not_read": not_read,
        "fields": confirmed + corrected + not_confirmed + not_read,
        "seen_by_a_person": confirmed + corrected,
    }
    if confirmed_absent:
        tally["confirmed_absent"] = confirmed_absent
    return tally


#: 이벤트를 세입자가 읽을 수 있는 한 줄로. 값은 절대 넣지 않는다 — 무엇을 했는지는 남기고,
#: 무엇이라고 적었는지는 남기지 않는다.
EVENT_WORDS = {
    "session_created": "This session was created",
    "document_uploaded": "A document was uploaded and read in memory",
    "field_confirmed": "A value was confirmed as read",
    "fields_confirmed_together": "A value was confirmed as part of one document's remaining values",
    "field_corrected": "A value was corrected",
    "correction_undone": "A correction was undone",
    "confirmation_withdrawn": "A confirmation was withdrawn",
    # 값이 없는 필드에 대한 사람의 확인. 여기에도 값은 실리지 않는다 — 애초에 값이
    # 없다는 사실이 확인의 내용이다. field_confirmed 와 같은 규율: 동작·문서·필드명만.
    "field_absence_confirmed": "A value the machine could not read was checked by the renter: not shown on that document",
    "absence_confirmation_withdrawn": "An absence check was withdrawn",
    # 세입자가 페이지 위의 위치를 손으로 가리킨 기록. 값도 좌표도 여기엔 싣지 않는다 —
    # 좌표는 리포트의 필드 주석(region_marked_by_renter)에 있고, 이 로그는 동작·문서·
    # 필드명만 남기는 규율을 지킨다.
    "field_region_marked": "The renter pointed at the place on the page this value comes from",
    "question_asked": "A rule question was asked",
    "packet_exported": "A packet was exported by the renter",
}


def activity_log(s: Session, ruleset_version: str = "") -> dict[str, Any]:
    """세션에 쌓인 이벤트 요약. **문서 원문은 들어가지 않는다.**

    브리프 CONSENT AND CORRECTION: "log consent, actions, and rule versions - not raw
    document contents". `Session.log()` 는 처음부터 있었지만 **아무도 읽지 않았다** —
    기록만 하고 어디에도 내보내지 않는 로그는 요구의 절반만 만족한 상태다. 여기서
    리포트와 패킷으로 나간다.

    실리는 것은 동작·대상 필드 이름·규칙 버전뿐이다. 값도, 파일 이름도, 질문 원문도
    `Session.log()` 호출부에서 이미 빠져 있고 여기서도 만들지 않는다.
    """
    counts: dict[str, int] = {}
    entries = []
    for index, event in enumerate(s.events, 1):
        action = str(event.get("action", ""))
        counts[action] = counts.get(action, 0) + 1
        entry = {
            "n": index,
            "action": action,
            "what_happened": EVENT_WORDS.get(action, action.replace("_", " ")),
        }
        for key in ("document_id", "field", "household_id", "document_type",
                    "extraction_path", "evidence_kind"):
            if event.get(key) is not None:
                entry[key] = event[key]
        entries.append(entry)
    return {
        "notice": ("Actions only. This log never holds the contents of a document, a file "
                   "name, or a value you typed."),
        "ruleset_version": ruleset_version,
        "engine_version": engine_version(),
        "counts": counts,
        "events": entries,
    }


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
    # 부재 확인: (document_id, field) -> 확인한 날짜(ISO). 값이 없는 필드에 대해 세입자가
    # "이 문서에는 이 값이 없다" 고 확인한 기록이다. 값의 확인(`confirmed_by_renter`)과
    # 달리 `evidence_kind` 를 움직이지 않는다 — 그 enum 은 계약 §1 에서 동결됐고, 사람이
    # 부재를 확인해도 기계가 읽지 못했다는 사실은 그대로이기 때문이다. 팩 문서와 업로드
    # 어느 쪽의 필드든 여기 실릴 수 있다.
    absences: dict[tuple[str, str], str] = field(default_factory=dict)
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
        self._warm_lock = threading.Lock()
        # warm 이 **끝까지 갔는지**. 한 번이라도 예외 없이 통과하면 True 가 되고, 그 뒤로는
        # 내려가지 않는다. 문서 0장으로 끝난 것과 아직 도는 중인 것은 둘 다 `_base` 가
        # 비어 있어서 구분되지 않는데, 그 둘은 완전히 다른 사건이다 -- 전자는 장애고
        # 후자는 정상적인 부팅 중간이다. 그래서 개수 말고 이 플래그로 구분한다.
        self._warm_completed = False
        # 마지막 warm 이 던진 예외의 종류와 문장. 성공하면 다시 None 이 된다.
        # 배포된 컨테이너에서 팩 PDF 가 git-lfs 포인터 파일로 도착해 pdfplumber 가
        # "No /Root object!" 를 던졌을 때, 그 예외는 데몬 스레드의 stderr 로만 갔고
        # 서버는 몇 시간 동안 200 을 답했다. 던진 쪽이 스스로 남기지 않으면 아무도 모른다.
        self._warm_failure: dict[str, str] | None = None

    # ── 부팅 ────────────────────────────────────────────────────────────
    def warm(self) -> dict[str, Any]:
        """문서를 읽어 `_base` 를 채운다. 여러 번 불러도 한 번만 일한다.

        기동 시 백그라운드 스레드가 부르고, 세션을 만들 때 요청 경로가 다시 부른다.
        락이 있는 이유는 **먼저 도착한 요청이 같은 일을 기다리게** 하기 위해서다.
        락이 없으면 두 요청이 24장을 각각 추출한다.

        결과(성공/실패)를 스토어에 남긴다. 예외는 **삼키지 않고 그대로 올려보낸다** —
        부른 쪽이 요청 경로면 500 으로 알아야 하고, 백그라운드 스레드면 traceback 을
        찍어야 한다. 여기서 하는 일은 기록뿐이고, 그 기록을 `/api/health` 가 읽는다.
        """
        with self._warm_lock:
            if not self._base:
                try:
                    self._base = extract_all()
                except BaseException as exc:
                    self._warm_failure = {
                        "type": type(exc).__name__,
                        "message": str(exc) or repr(exc),
                    }
                    raise
            # 실패한 뒤 다시 불러 성공했다면 그 실패는 더 이상 현재 상태가 아니다.
            self._warm_failure = None
            self._warm_completed = True
        return {"documents": len(self._base), "engine": engine_version()}

    def warm_report(self) -> dict[str, Any]:
        """`/api/health` 가 읽는 준비 상태 한 조각.

        락을 잡지 않는다. 헬스체크가 24장을 추출하는 warm 뒤에서 **블록되면** 그
        헬스체크는 부팅 중인 서버를 죽은 서버로 오해하게 만든다. 여기서 읽는 값들은
        각각 한 번의 원자적 읽기이므로, 최악의 경우라도 한 순간 낡은 값을 볼 뿐이다.

        `phase` 값 셋:
          "running"    아직 한 번도 끝까지 가지 못했고, 예외도 없었다. 부팅 중이다.
          "completed"  예외 없이 끝났다. 몇 장을 읽었는지는 `documents_loaded` 가 말한다.
          "failed"     예외로 끝났다. 그 종류와 문장이 `error` 에 있다.
        """
        if self._warm_failure is not None:
            phase = "failed"
        elif self._warm_completed:
            phase = "completed"
        else:
            phase = "running"
        return {
            "phase": phase,
            "documents_loaded": len(self._base),
            "error": dict(self._warm_failure) if self._warm_failure else None,
        }

    # ── 세션 ────────────────────────────────────────────────────────────
    def new_session(self) -> Session:
        # 기동 직후 warm 이 아직 도는 중에 도착한 요청은, 여기서 그 일이 끝나기를
        # 기다린다. 기다리지 않으면 `_base` 가 빈 채로 복사되어 이 세션은 **영구히**
        # 빈 세션이 된다 -- 에러도 없고, 나중에 채워지지도 않는다. 실제로 배포된
        # 서버가 그 상태로 `{"households":[]}` 를 200 으로 돌려주고 있었고, 헬스체크는
        # 내내 통과했다. 빈 화면을 조용히 내주느니 첫 요청이 기다리는 편이 낫다.
        self.warm()
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
    def _applicant(self, house: Any) -> dict[str, Any]:
        """신청인 이름과 **그 이름의 확실성**. 없으면 `None` 이다 — 짓지 않는다.

        `person_name` 은 신청 요약서에서 이미 뽑아 놓은 필드다. 여기서 다시 읽지도,
        다른 문서에서 유추하지도 않는다. 급여명세서에도 같은 이름 필드가 있지만 그걸
        섞으면 "고용주가 적은 이름"과 "본인이 적은 이름"이 한 칸에서 뭉개진다.
        세대를 대표하는 이름은 신청서의 것 하나뿐이고, 그 문서가 없으면 이름도 없다.

        `Document.get()` 은 `certainty == "abstain"` 이나 값 없음을 `None` 으로 접는데,
        여기서는 그 접힘을 쓰지 않는다. **얼마나 확실한 이름인지가 화면에 실려야**
        하기 때문이다. 낮게 읽힌 이름을 확실한 이름과 같은 모양으로 내보내면, 이
        프로젝트가 문서 필드마다 지켜 온 구분이 이름 한 칸에서만 사라진다.
        """
        for doc in house.documents:
            if doc.document_type != "application_summary":
                continue
            ref = doc.fields.get("person_name")
            if ref is None or ref.value is None or ref.certainty == "abstain":
                return {"applicant_name": None, "applicant_name_certainty": None,
                        "applicant_name_evidence": None}
            return {
                "applicant_name": str(ref.value),
                "applicant_name_certainty": ref.certainty,
                "applicant_name_evidence": ref.evidence_kind,
            }
        return {"applicant_name": None, "applicant_name_certainty": None,
                "applicant_name_evidence": None}

    def households(self, s: Session) -> list[dict[str, Any]]:
        houses = households_from_views(list(s.views.values()))
        out = []
        for hid in sorted(houses):
            docs = houses[hid].documents
            row = {
                "household_id": hid,
                "document_count": len(docs),
                # `Document` 는 데이터클래스이고 `.get(name)` 은 **추출 필드**를 찾는
                # 메서드다. 그래서 `d.get("document_id")` 는 언제나 None 이었고, 이
                # 배열은 지금까지 [null, null, null, null] 로 나갔다. 속성으로 읽는다.
                "document_ids": [d.document_id for d in docs],
                "file_kind": "pack",
            }
            row.update(self._applicant(houses[hid]))
            out.append(row)
        # 업로드가 하나라도 있으면 그것들로 이룬 파일이 목록의 마지막 행이 된다.
        # 팩 세대 행은 위에서 이미 만들어졌고 여기서는 한 글자도 달라지지 않는다.
        if s.uploads:
            up_houses = households_from_views(list(s.uploads.values()))
            up_house = up_houses.get(UPLOADS_HOUSEHOLD_ID)
            row = {
                "household_id": UPLOADS_HOUSEHOLD_ID,
                "document_count": len(s.uploads),
                "document_ids": list(s.uploads),
                "file_kind": "uploads",
            }
            # 업로드에 신청 요약서가 없으면 이름도 없다 — 팩과 같은 규칙, 같은 함수.
            row.update(self._applicant(up_house) if up_house else {
                "applicant_name": None, "applicant_name_certainty": None,
                "applicant_name_evidence": None})
            out.append(row)
        return out

    def report(self, s: Session, household_id: str) -> dict[str, Any] | None:
        """`ReadinessReport` + 각 문서에 추출 필드(bbox 포함)를 병합.

        로직층의 리포트는 문서를 메타데이터로만 담는다. UI가 문서 위에 근거 상자를
        그리려면 필드와 좌표가 필요하므로, 그 병합은 이 층의 책임이다.

        업로드 파일(`UPLOADS_HOUSEHOLD_ID`)도 **같은 기계**를 탄다: 같은 build_report,
        같은 병합, 같은 평문 계층, 같은 집계. 다른 것은 뷰의 출처(세션의 업로드 사전)와
        필수 문서 목록의 출처뿐이다 — 팩 체크리스트에 이 파일의 행이 없으므로 목록은
        주최측 체크리스트가 부호화한 조건부 패턴을 세션의 실제 문서에 적용해 얻는다
        (`uploads_required_types` 의 문서 주석이 그 패턴의 출처를 인용한다).
        """
        if household_id == UPLOADS_HOUSEHOLD_ID:
            if not s.uploads:
                return None
            views = list(s.uploads.values())
            required = uploads_required_types(views)
        else:
            views = list(s.views.values())
            required = required_document_types(household_id, self._checklists)
        houses = households_from_views(views)
        house = houses.get(household_id)
        if house is None:
            return None

        rep = build_report(
            house,
            required,
            engine_version=engine_version(),
        )

        by_id = {v["document_id"]: v for v in views}
        for doc in rep.get("documents", []):
            v = by_id.get(doc.get("document_id"), {})
            doc["fields"] = v.get("fields", [])
            doc["page_count"] = v.get("page_count")
            doc["page_size_points"] = v.get("page_size_points")
            doc["state"] = v.get("state")
            # 업로드 뷰는 어느 경로로 읽었는지를 스스로 안다(api/upload.py 가 "source" 를
            # 싣는다). 팩 뷰에는 그 키가 없으므로 기존 문장이 그대로 남는다 — 팩 리포트는
            # 이 변경 전과 바이트 단위로 같아야 한다(api/packet_baseline).
            doc["source"] = v.get("source") or ("ocr" if v.get("rasterized") else "text_layer")
        rep["session_id"] = s.session_id

        # 세입자용 평문 계층. **덧붙이기만 한다** — 로직층이 만든 정밀한 문자열은
        # 하나도 바꾸지 않고, 그 옆에 사람이 읽을 문장과 "그래서 뭘 하면 되는지"를
        # 얹는다. 기계 코드와 원문은 각 항목의 code/detail 로 계속 꺼낼 수 있다.
        rep["plain"] = plain.for_report(rep)
        # 사람이 무엇을 보았는지. 아래 두 블록은 브리프의 서로 다른 두 요구다.
        rep["confirmation"] = confirmation_tally(rep)
        rep["activity_log"] = activity_log(s, rep.get("ruleset_version", ""))
        return rep

    def apply_correction(self, s: Session, document_id: str, field_name: str,
                         value: Any, together: bool = False,
                         region: dict[str, Any] | None = None) -> str:
        """사람이 **확인하거나 정정한** 값을 반영한다. 한 경로, 두 결과.

        브리프 표제: "turns synthetic household documents into a human-confirmed profile",
        Required Build 01: "Require confirmation or correction before reuse". 확인과 정정은
        **같은 동작의 두 결과**다 — 세입자는 미리 채워진 값을 보고, 맞으면 그대로 보내고
        틀리면 고쳐서 보낸다. 그래서 엔드포인트도 하나다.

        ⚠️ **확인은 사실을 바꾸지 않는다.** 받은 값이 기계가 읽은 값과 같으면 값도
        `certainty` 도 건드리지 않는다. 바뀌는 것은 `evidence_kind` — 그 값이 사람의 눈을
        거쳤다는 표시 — 하나뿐이다. 정정은 다르다: 값이 바뀌었으므로 사람이 댄 값이
        기계가 읽은 값을 대신하고, 그 사실이 `corrected_by_renter` 로 남는다.

        반환값:
          "confirmed_by_renter" | "corrected_by_renter"  적용된 결과
          "no_such_field"                                 그 문서에 그 필드가 없다
          "nothing_was_read"                              읽히지 않은 필드를 확인하려 했다

        `region` 은 세입자가 페이지 위에 직접 그린 사각형이다(인라인 편집기의
        "Point at it on the page"). **정정에만** 붙는 추가 주석이고, 기계의 page/bbox 는
        계약대로 얼어붙은 채 한 글자도 움직이지 않는다 — 정정은 증거 옆의 주석이지
        증거의 변경이 아니다. 확인(값이 같음)으로 끝나면 사각형은 버려진다: 값이 기계의
        읽기 그대로라면 그 값의 출처는 기계 자신의 상자가 이미 말하고 있다.
        """
        view = self._document_view(s, document_id)
        if view is None:
            return "no_such_field"
        for f in view.get("fields", []):
            if f.get("field") != field_name:
                continue
            key = (document_id, field_name)
            # 추출된 원값은 **첫 조작 때 한 번만** 보관한다. 같은 필드를 두 번 고쳐도
            # 취소는 기계가 읽은 값까지 돌아가야지, 직전 정정값에서 멈추면 안 된다.
            snapshot = s.originals.get(key)
            extracted = snapshot["value"] if snapshot else f.get("value")

            if same_value(value, extracted):
                # 기권한 필드(값이 없음)는 확인할 수 있는 대상이 아니다. 읽히지 않은 것을
                # "사람이 확인했다"고 표시하면 그 표시는 거짓이고, 하필 사람 손이 가장
                # 필요한 자리에서 거짓이 된다. 확인 대신 값을 채워 넣어야 한다.
                if extracted is None:
                    return "nothing_was_read"
                if snapshot is None:
                    s.originals[key] = {
                        "value": f.get("value"),
                        "certainty": f.get("certainty"),
                        "evidence_kind": f.get("evidence_kind"),
                    }
                # 값도 certainty 도 그대로 둔다 — 확인은 사실이 아니라 그 사실을 누가
                # 보았는지를 바꾼다. 값을 되돌려 놓는 것은, 같은 필드를 고쳤다가 원래
                # 값으로 되돌려 확인한 경우를 위해서다.
                f["value"] = s.originals[key]["value"]
                f["certainty"] = s.originals[key]["certainty"]
                f["evidence_kind"] = "confirmed_by_renter"
                # 확인은 "기계가 맞게 읽었다"는 주장이다. 앞선 정정에 붙어 있던
                # 가리킴 주석은 그 정정과 함께 걷힌다 — 기계 값의 출처는 기계의 상자다.
                f.pop("region_marked_by_renter", None)
                s.corrections.pop(key, None)
                s.log("field_confirmed" if not together else "fields_confirmed_together",
                      document_id=document_id, field=field_name,
                      evidence_kind="confirmed_by_renter")
                return "confirmed_by_renter"

            if snapshot is None:
                s.originals[key] = {
                    "value": f.get("value"),
                    "certainty": f.get("certainty"),
                    "evidence_kind": f.get("evidence_kind"),
                }
            f["value"] = value
            f["certainty"] = "high"
            f["evidence_kind"] = "corrected_by_renter"
            # 부재를 확인해 둔 필드에 값을 채워 넣으면 두 주장이 충돌한다 — "이 문서에는
            # 이 값이 없다" 와 "값은 이것이다" 는 같은 필드에 함께 설 수 없다. 새로 선
            # 쪽(사람이 댄 값)이 이기고, 부재 표시는 여기서 걷힌다. 별도 이벤트는 남기지
            # 않는다: field_corrected 가 이미 무슨 일이 일어났는지 말한다.
            if s.absences.pop(key, None) is not None:
                f.pop("absence_confirmed_by_renter", None)
                f.pop("absence_confirmed_on", None)
            # 가리킨 사각형은 이 정정의 주석이다. 새 정정이 사각형 없이 오면 이전
            # 정정의 사각형은 더 이상 서 있는 주장이 아니므로 함께 걷힌다.
            if region is not None:
                f["region_marked_by_renter"] = dict(region)
                s.log("field_region_marked", document_id=document_id, field=field_name)
            else:
                f.pop("region_marked_by_renter", None)
            s.corrections[key] = value
            s.log("field_corrected", document_id=document_id, field=field_name,
                  evidence_kind="corrected_by_renter")
            return "corrected_by_renter"
        return "no_such_field"

    # ── 업로드 (인수 데모 1단계: 문서를 올리고 추출 근거를 보인다) ─────────
    def add_upload(self, s: Session, data: bytes, file_name: str,
                   document_type: str) -> dict[str, Any]:
        """올린 문서를 읽어 **세션 메모리에만** 담는다. 디스크에 닿지 않는다."""
        from api import upload as upload_mod

        # 예전에는 마지막 한 장만 남기고 직전 업로드를 지웠다. 이제 업로드들은 함께
        # **세션 자신의 파일**(UPLOADS_HOUSEHOLD_ID)을 이루므로 전부 남는다 — 심사위원이
        # 자기 문서 여러 장으로 2~6단계를 걸을 수 있는 것이 이 파일의 존재 이유다.
        # 바이트가 세션 메모리에 살기 때문에 개수 상한(MAX_SESSION_UPLOADS)이 자리를
        # 대신한다. 상한 초과는 조용한 교체가 아니라 이유를 말하는 거절이다: 먼저 올린
        # 문서가 파일의 일부인 채로 소리 없이 사라지는 쪽이 더 나쁘다.
        if len(s.uploads) >= MAX_SESSION_UPLOADS:
            raise upload_mod.UploadRejected(
                "session_upload_limit",
                f"This session already holds {MAX_SESSION_UPLOADS} uploaded documents, "
                f"and they all stay in this session's memory. That is the ceiling. "
                f"You can open the file made of the ones you have, or delete the "
                f"session at the end of page 2 and start again.",
            )
        view = upload_mod.read_upload(data, file_name, document_type)
        # 업로드들이 한 파일로 모이려면 같은 household_id 를 말해야 한다. 이 키는 팩
        # 세대의 id 공간(HH-xxx)과 겹치지 않으므로 팩 세대는 이 문서를 절대 줍지 않는다.
        view["household_id"] = UPLOADS_HOUSEHOLD_ID
        uid = view["upload_id"]
        s.uploads[uid] = view
        s.upload_bytes[uid] = data
        # 파일 이름도 원문도 남기지 않는다 — 브리프: "log consent, actions, and rule
        # versions - not raw document contents".
        s.log("document_uploaded", document_type=document_type,
              extraction_path=view["extraction_path"])
        return view

    def undo_correction(self, s: Session, document_id: str, field_name: str) -> bool:
        """한 필드의 **사람 표시를 걷어낸다** — 그 필드를 추출 상태로, 다른 필드는 그대로.

        화면은 취소 버튼 옆에서 "the report is back to the extracted values" 라고 말한다.
        그 문장이 사실이 되려면 되돌리기가 **서버 세션에서** 일어나야 한다. 정정은 세션의
        DocumentView 를 제자리에서 덮어쓰므로, 클라이언트가 자기 화면의 리포트만 되돌리면
        서버는 여전히 정정된 값을 들고 있고 다음 정정 때 그 값이 되살아난다.

        ── 확인한 값을 취소하면?  (이 조합은 확인 기능이 생기기 전까지 정의되지 않았다)
        **확인도 걷힌다.** 필드는 `extracted` 로 돌아가고, 값은 어차피 처음부터 바뀐 적이
        없으므로 그대로다. 근거 셋:
          1. 취소의 뜻은 "내가 이 필드에 한 일을 무르기" 다. 확인은 사람이 한 일이다.
             정정만 무르고 확인은 남긴다면, 취소 버튼이 어떤 때는 듣고 어떤 때는 안 듣는다.
          2. 잘못 누른 확인을 되돌릴 길이 있어야 한다. 확인은 "내가 이 값을 봤고 맞다"는
             주장이므로, 철회할 수 없는 주장으로 만들면 오히려 신뢰가 떨어진다.
          3. `confirmed_by_renter` 는 추출 상태가 **아니다**. 확인을 남긴 채 "추출된 값으로
             돌아갔다"고 말하면 화면이 거짓말을 한다.
        정정 후 확인(값을 되돌려 확인)한 필드도 마찬가지로 한 번의 취소로 `extracted` 가
        된다 — 사람이 남긴 흔적은 그 필드에 하나뿐이고, 취소는 그 하나를 지운다.
        """
        key = (document_id, field_name)
        snapshot = s.originals.get(key)
        if snapshot is None:
            return False
        view = self._document_view(s, document_id)
        if view is None:
            return False
        for f in view.get("fields", []):
            if f.get("field") == field_name:
                was = f.get("evidence_kind")
                f["value"] = snapshot["value"]
                f["certainty"] = snapshot["certainty"]
                f["evidence_kind"] = snapshot["evidence_kind"]
                # 되돌린 필드는 스냅샷과 완전히 같아야 한다. 가리킴 주석은 정정과 함께
                # 생겼으니 정정과 함께 사라진다.
                f.pop("region_marked_by_renter", None)
                s.originals.pop(key, None)
                s.corrections.pop(key, None)
                s.log("confirmation_withdrawn" if was == "confirmed_by_renter"
                      else "correction_undone",
                      document_id=document_id, field=field_name,
                      evidence_kind=f.get("evidence_kind"))
                return True
        return False

    # ── 부재 확인 (값이 없는 필드를 사람이 보았다는 기록) ────────────────────
    def _document_view(self, s: Session, document_id: str) -> dict[str, Any] | None:
        """팩 문서와 업로드를 한 이름으로 찾는다. 부재는 두 곳 모두에서 생긴다 —
        실제로는 팩이 159/159 로 기권이 없으므로, 사실상 업로드에서 생긴다."""
        return s.views.get(document_id) or s.uploads.get(document_id)

    def confirm_absence(self, s: Session, document_id: str, field_name: str) -> str:
        """세입자가 "이 문서에는 이 값이 없다" 를 확인한다.

        브리프의 경계 선언은 이 제품의 산출물을 "document readiness and human-review
        handoff" 라고 이름 붙이고, 참가자 가이드의 준비도 관행은 빠진 필수 증거를
        NEEDS_REVIEW 로 보낸다. 그런데 지금까지 기대 필드의 부재는 기계의 자백
        ("no label for this field was found on the page")으로만 나갔다 — 검토자는
        "추출기가 못 읽었다" 와 "신청자가 페이지를 봤는데 정말 없다" 를 구분할 수
        없었다. 확인된 값(`confirmed_by_renter`)은 있는데 **확인된 부재**는 없었다.
        이 메서드가 그 공백을 메운다.

        ⚠️ **부재 확인은 enum 을 움직이지 않는다.** 계약 §1 은 `evidence_kind`
        (extracted / confirmed_by_renter / corrected_by_renter)와 `certainty`
        (high / low / abstain)를 동결했고, 여기서 그 어느 쪽도 늘리지 않는다. 필드는
        `certainty="abstain"`, `value=null` 그대로다 — 사람이 부재를 확인해도 기계의
        읽기가 더 확실해지는 것은 아니기 때문이다. 남는 것은 활동 기록의 이벤트 하나와
        표시용 주석 두 개(`absence_confirmed_by_renter`, `absence_confirmed_on`)뿐이며,
        둘 다 **확인이 있을 때만** 붙는다 — 없을 때 리포트는 한 바이트도 달라지지 않는다
        (api/packet_baseline/ 이 그것을 잰다).

        기록에는 값이 실리지 않는다 — 애초에 값이 없다는 사실이 확인의 내용이다.
        field_confirmed 와 같은 규율: 동작·문서·필드명만 남는다.

        반환값:
          "absence_confirmed"   적용됨
          "no_such_field"       그 문서에 그 필드가 없다
          "value_was_read"      값이 읽힌 필드다 — 부재가 아니라 값을 확인·정정해야 한다
        """
        view = self._document_view(s, document_id)
        if view is None:
            return "no_such_field"
        for f in view.get("fields", []):
            if f.get("field") != field_name:
                continue
            if f.get("value") is not None:
                return "value_was_read"
            checked_on = datetime.date.today().isoformat()
            s.absences[(document_id, field_name)] = checked_on
            f["absence_confirmed_by_renter"] = True
            f["absence_confirmed_on"] = checked_on
            s.log("field_absence_confirmed", document_id=document_id, field=field_name)
            return "absence_confirmed"
        return "no_such_field"

    def withdraw_absence(self, s: Session, document_id: str, field_name: str) -> bool:
        """한 부재 확인을 걷어낸다 — 확인 철회(`confirmation_withdrawn`)의 거울.

        부재 확인도 "내가 페이지를 봤고 거기 없다" 는 사람의 주장이므로, 철회할 수
        없는 주장으로 만들면 오히려 신뢰가 떨어진다. 걷어내면 필드는 주석이 붙기 전과
        완전히 같아진다 — 값도 certainty 도 evidence_kind 도 처음부터 움직인 적이 없다.
        """
        if s.absences.pop((document_id, field_name), None) is None:
            return False
        view = self._document_view(s, document_id)
        if view is not None:
            for f in view.get("fields", []):
                if f.get("field") == field_name:
                    f.pop("absence_confirmed_by_renter", None)
                    f.pop("absence_confirmed_on", None)
                    break
        s.log("absence_confirmation_withdrawn", document_id=document_id, field=field_name)
        return True


STORE = Store()
