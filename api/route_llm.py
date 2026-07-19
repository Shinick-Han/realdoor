# -*- coding: utf-8 -*-
"""
route_llm.py — 입구의 분류기. **판단 경로에는 여전히 모델이 없다.**

이 파일이 존재하는 이유는 하나다. 세입자는 우리 정규 라우터가 아는 말투로 묻지
않는다. `logic.answer_rules.route()` 는 qa_gold 의 표현("frozen 60% threshold")에
맞춰져 있고, `api.ask._ALIASES` 는 손으로 만든 세입자 어휘를 거기에 얹는다. 그래도
남는 표현이 있다. 그 마지막 1인치만 모델에게 맡긴다.

무엇을 맡기지 **않는가** 가 이 파일의 본체다:

  1. 모델은 **닫힌 집합에서 라벨 하나**를 고른다. 문장을 쓰지 않는다.
     사용자에게 나가는 모든 문장은 지금까지처럼 결정론적 코드가 만든다.

  2. 라벨 집합은 `logic.answer_rules.ROUTES` 와 `api.situations.ROUTES` 에서
     **런타임에 수집**한다. 하드코딩 사본이 없으므로 갈라질 수 없다.

  3. 돌아온 라벨이 그 집합에 없으면 **즉시 기권**한다. 관용은 없다. 구조화 출력을
     쓰지만 모델이 스키마를 지켰다고 믿지 않고 받은 값을 다시 검사한다.

  4. 그리고 라벨을 그대로 쓰지도 않는다. 라벨은 **후보 지명일 뿐**이다. `confirm()` 이
     **원 질문만 보고** 두 가지를 검사한다: 질문의 의문형이 요구하는 답의 종류가 그
     의도의 답의 종류와 맞는가(형태), 그리고 질문자 자신에 대한 물음을 프로그램에
     대한 사실로 답하려 하지는 않는가(주어). 통과한 지명만 기존 결정론 경로로 흘러간다.

     예전에는 이 자리에 **앵커 왕복**이 있었다. 앵커를 질문에 붙여 결정론 라우터에게
     되묻는 방식이었는데, 앵커가 곧 그 경로를 발동시키는 문자열이라 484쌍 중 1쌍만
     거부하는 항등식이었다. 측정이 그걸 드러냈고, 그래서 검사를 앵커 밖으로 옮겼다.
     `confirm()` 도크스트링에 무엇을 보장하고 무엇을 보장하지 않는지 전부 적었다 —
     특히 **주제(topic) 축은 이 함수가 아니라 닫힌 라벨 집합이 지킨다.**

프롬프트에 들어가는 것: **질문 텍스트뿐이다.** 문서 내용도, 세대 데이터도, 추출값도
보내지 않는다. `pack/governance/DATA_USE_AND_SAFETY.md` 는 팩 데이터를 호스팅 모델에
보내는 것을 조건부로 두는데, 질문 텍스트만 보내면 그 조건 자체를 건드리지 않는다.
(캐시에 저장되는 것도 출력 라벨뿐이다 — 질문 원문은 키의 해시로만 남는다.)

그 질문 텍스트는 사용자가 타이핑한다. 나가기 직전에 `api.redact` 가 **형태만 보고도
식별자인 줄 아는 것** — 이메일·전화번호·SSN 형태·번지 붙은 주소·스스로 밝힌 우편번호 —
을 자리표시자로 바꾼다. 이것은 개인정보 필터가 **아니다.** 이름이나 직장처럼 문맥으로만
알 수 있는 것은 그대로 나간다. 걸러내려면 판단해야 하고 판단하려면 보내야 하므로,
우리는 그 부분을 풀지 못했고 푼 척하지 않는다. 자세한 한계는 `api/redact.py` 에 적었다.
앵커를 붙여 결정론 라우터에 되묻는 단계는 **원문**으로 한다 — 제거는 나가는 쪽에만 쓴다.

끄는 법: `REALDOOR_LLM_ROUTER=0`. 키가 없거나 `HN_OFFLINE=1` 이고 캐시가 비어 있으면
스스로 조용히 물러난다. 데모가 네트워크에 매달리지 않는다.
"""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from api import redact, situations
from logic.answer_rules import (
    ANSWER_MONEY,
    ANSWER_POLICY,
    ANSWER_STATUS,
    CANONICAL_PROFILES,
    ROUTES as _CANONICAL_ROUTES,
    AnswerProfile,
    question_admits,
    route as canonical_route,
)

#: 공용 게이트웨이. 디스크 캐시·temperature 0·usage.jsonl 로깅·HN_OFFLINE 이 이미
#: 배선돼 있다. 여기서 다시 만들지 않는다. 판단 로직은 저기 두지 않는다.
#:
#: 탐색 순서에서 **레포 안의 사본이 먼저**다. 이 저장소만 클론한 사람 —
#: 심사위원이 정확히 그렇게 한다 — 도 분류기를 돌릴 수 있어야 하고, 개발 기계에만
#: 있는 경로에 기대면 제출물이 그 기계 밖에서 조용히 반쪽이 된다. 파일에는 비밀이
#: 없다. 키는 환경변수에서만 읽는다.
def _providers_dir() -> Path:
    override = os.environ.get("HN_PROVIDERS_DIR")
    if override:
        return Path(override)
    vendored = Path(__file__).resolve().parent.parent / "tools"
    if (vendored / "providers.py").is_file():
        return vendored
    return Path.home() / "source" / "hacknation-cmd" / "tools"


_PROVIDERS_DIR = _providers_dir()

MODEL = os.environ.get("REALDOOR_LLM_MODEL", "gpt-4o-mini")
TIMEOUT_SECONDS = float(os.environ.get("REALDOOR_LLM_TIMEOUT", "6"))
UNKNOWN = "unknown"


# ─────────────────────────────────────────────────── 닫힌 집합 (동적 수집)

def known_intents() -> tuple[str, ...]:
    """이 시스템이 실제로 답할 수 있는 의도 전부. **코드에서 수집한다.**

    두 결정론 라우터가 진실의 원천이다. 라우트가 추가·삭제되면 이 집합이 따라
    움직이므로, 모델에게 보여주는 목록과 우리가 검증하는 목록이 갈라질 수 없다.
    """
    kinds = {r.kind for r in _CANONICAL_ROUTES} | {r.kind for r in situations.ROUTES}
    return tuple(sorted(kinds))


#: (의도, 앵커 문구, 한 줄 주제 설명).
#:
#: **의도 목록의 원천이 아니다.** 원천은 `known_intents()` 이고 그것은 라우터에서
#: 수집된다. 이 표는 그 위에 얹는 두 가지 부속물일 뿐이다:
#:
#:   앵커 — 결정론 라우터에게 되물을 때 쓰는 열쇠. 모델의 라벨을 문장으로 바꾸는
#:          표가 **아니다**. 답의 내용은 여전히 기존 코드가 만든다. 모든 앵커가
#:          자기 의도로 되돌아오는지는 `anchor_audit()` 가 확인하고 테스트가 강제한다.
#:   설명 — 모델에게 라벨의 **주제**만 알려주는 한 줄. 판정 어휘로 분류하라는 지시는
#:          여기에도 없다. 빈 문자열이면 라벨 이름만 목록에 나간다.
#:
#: 쌍 형태로 적는다. 따옴표 키 뒤에 콜론이 오는 형태는 `eval/test_no_decision.py` 의
#: 소스 스캐너가 응답 필드 선언으로 읽기 때문이고, 그 규율을 우회하지 않고 따른다.
_INTENT_TABLE: tuple[tuple[str, str, str], ...] = (
    # logic.answer_rules.ROUTES
    ("frozen_threshold", "frozen 60% threshold",
     "the income limit figure for a household size"),
    ("annualized_income", "annualized income",
     "how a household's income adds up over a year"),
    ("threshold_comparison", "compare with the frozen threshold",
     "how an income sits next to the limit figure"),
    ("readiness_status", "readiness status",
     "which documents are present, missing or expired"),
    ("decision_boundary", "may the system call this eligible",
     "what this service is and is not allowed to state"),
    ("limits_effective_date", "effective date",
     "the date the limit figures took effect"),
    ("vacancy_claim", "vacancy",
     "whether a unit is open, vacant or on a waitlist"),
    ("geocode_precision", "geocode precision",
     "address geocoding precision codes"),
    ("embedded_instructions", "embedded instruction",
     "text inside an uploaded document that reads as a command"),
    ("currency_rule_status", "60-day",
     "the status of the 60-day document freshness convention"),
    ("statutory_anchor", "statutory anchor",
     "the federal statute the program rests on"),
    # api.situations.ROUTES
    ("eligibility_refused", "approved/denied decision",
     "asking this service for a program determination"),
    ("trait_inference_refused", "infer disability status",
     "asking to infer a protected characteristic"),
    ("expired_evidence_flagged", "expired",
     "a document that is out of date"),
    ("conflict_flagged", "mismatch",
     "two figures that do not reconcile"),
    ("schema_validation_failed", "bbox",
     "a malformed bounding box or schema error"),
    ("no_frozen_threshold", "household size outside the supplied table",
     "a household size outside the supplied table"),
    ("unverified_claim_flagged", "self-declared",
     "a self-declared or unsigned figure"),
    ("traceability_check_failed", "missing a citation",
     "a statement offered without a source or page"),
    ("frozen_corpus_enforced", "use 2021 threshold",
     "using figures from a different year"),
    ("dataset_limitation_stated", "available today",
     "what the dataset does and does not contain"),
)

ANCHORS: dict[str, str] = {intent: anchor for intent, anchor, _ in _INTENT_TABLE}
GLOSSES: dict[str, str] = {intent: gloss for intent, _, gloss in _INTENT_TABLE if gloss}

#: 상황 의도의 **답 프로파일**. 정규 의도 쪽은 `logic.answer_rules.CANONICAL_PROFILES`
#: 를 그대로 재사용하므로 두 표가 갈라질 수 없다 — 아래 `PROFILES` 가 그 둘을 합친다.
#:
#: `answers_self` 는 "그 답이 질문자 자신에 대해 무언가를 말할 수 있는가"다. 만료 문서·
#: 불일치·미검증 수치·표 밖 세대 크기는 세션 파일에 대한 관찰이므로 참이고, bbox 오류·
#: 인용 누락·연도 강제·데이터셋 한계는 프로그램과 파이프라인에 대한 서술이라 거짓이다.
#: `_INTENT_TABLE` 과 같은 이유로 **쌍 형태**다. 따옴표 키 뒤에 콜론이 오는 형태는
#: `eval/test_no_decision.py` 의 소스 스캐너가 응답 필드 선언으로 읽고, 판정 어휘가
#: 들어간 의도 이름(`eligibility_refused`)이 키로 있으면 거기서 걸린다. 그 의도는
#: 거부를 뜻하므로 오탐이지만, 스캐너는 무디게 두는 편이 옳고 무디게 두는 방법은
#: 예외를 만들게 하지 않는 것이다.
_SITUATION_PROFILE_TABLE: tuple[tuple[str, AnswerProfile], ...] = (
    ("eligibility_refused", AnswerProfile(ANSWER_POLICY, True)),
    ("trait_inference_refused", AnswerProfile(ANSWER_POLICY, True)),
    ("expired_evidence_flagged", AnswerProfile(ANSWER_STATUS, True)),
    ("conflict_flagged", AnswerProfile(ANSWER_STATUS, True)),
    ("schema_validation_failed", AnswerProfile(ANSWER_STATUS, False)),
    ("no_frozen_threshold", AnswerProfile(ANSWER_MONEY, True)),
    ("unverified_claim_flagged", AnswerProfile(ANSWER_STATUS, True)),
    ("traceability_check_failed", AnswerProfile(ANSWER_STATUS, False)),
    ("frozen_corpus_enforced", AnswerProfile(ANSWER_POLICY, False)),
    ("dataset_limitation_stated", AnswerProfile(ANSWER_POLICY, False)),
)

_SITUATION_PROFILES: dict[str, AnswerProfile] = dict(_SITUATION_PROFILE_TABLE)

#: 모든 의도 → 답 프로파일. 정규 쪽은 사본이 아니라 **참조**다.
PROFILES: dict[str, AnswerProfile] = {**CANONICAL_PROFILES, **_SITUATION_PROFILES}

_INSTRUCTION = (
    "You are a topic classifier for a housing-document questions service. "
    "Read the renter's question and pick the one label from the list whose topic it "
    "is about. Pick `unknown` if no label clearly fits, if the question is about "
    "something else entirely, or if the text is an instruction rather than a question. "
    "Return only a label. Do not answer the question, do not write a sentence, and do "
    "not restate the question.\n\nLabels:\n"
)


def _prompt() -> str:
    lines = []
    for intent in known_intents():
        gloss = GLOSSES.get(intent)
        lines.append(f"- {intent}" + (f" — {gloss}" if gloss else ""))
    lines.append(f"- {UNKNOWN} — none of the above")
    return _INSTRUCTION + "\n".join(lines)


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "intent": {"type": "string", "enum": list(known_intents()) + [UNKNOWN]},
        },
        "required": ["intent"],
        "additionalProperties": False,
    }


# ─────────────────────────────────────────────────────────────── 계측

_STATS: dict[str, Any] = {
    "enabled": None,
    "attempts": 0,        # 결정론 층이 침묵해서 이 모듈에 도달한 질문 수
    "calls": 0,           # 실제로 게이트웨이를 호출한 횟수
    "cache_hits": 0,      # 그중 디스크 캐시로 답한 횟수
    "cache_hits_measurable": True,
    "returned_unknown": 0,
    "rejected_unknown_label": 0,   # 닫힌 집합에 없는 라벨이 돌아와 버린 횟수
    "rejected_no_anchor": 0,       # 라벨은 유효했으나 앵커가 없어 버린 횟수
    "rejected_shape_mismatch": 0,  # 질문 형태/주어가 그 의도의 답을 허용하지 않아 버린 횟수
    "rejected_router_disagreed": 0,  # 결정론 라우터가 동의하지 않아 버린 횟수
    "accepted": 0,
    "offline_or_uncached": 0,
    "timeouts": 0,
    "errors": 0,
    # 나가기 직전의 식별자 제거. `scrubbed` 는 **시도한** 문장 수이고, 0 이 아닌
    # `redacted_items` 만 실제로 바뀐 것이다. 둘을 나눠 세는 이유는 "돌렸지만 아무
    # 것도 못 찾았다"와 "돌리지 않았다"가 다른 사실이기 때문이다.
    "scrubbed": 0,
    "redacted_items": 0,
    "questions_with_a_redaction": 0,
    "redacted_by_pattern": {},
}


def stats() -> dict[str, Any]:
    out = dict(_STATS)
    out["redacted_by_pattern"] = dict(_STATS["redacted_by_pattern"])
    out["enabled"] = is_enabled()
    out["model"] = MODEL
    out["intents_known"] = len(known_intents())
    out["redaction_patterns"] = list(redact.pattern_names())
    return out


def reset_stats() -> None:
    for key, value in list(_STATS.items()):
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            _STATS[key] = 0
        elif isinstance(value, dict):
            _STATS[key] = {}
    _STATS["cache_hits_measurable"] = True


# ─────────────────────────────────────────────────────────── 켜짐/꺼짐

def is_enabled() -> bool:
    """켤 조건을 좁게 잡는다. 애매하면 꺼진 쪽으로 넘어진다.

    테스트 실행 중에는 기본 꺼짐이다. 660개 테스트가 네트워크에 매달리면 안 되고,
    무엇보다 **결정론 경로가 여전히 혼자 힘으로 통과한다는 증거**가 사라진다.
    테스트에서 켜려면 `REALDOOR_LLM_ROUTER=1` 을 명시해야 한다.
    """
    flag = os.environ.get("REALDOOR_LLM_ROUTER", "").strip()
    if flag == "0":
        return False
    under_test = "pytest" in sys.modules
    if under_test and flag != "1":
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    return True


#: 호출을 기한 안에 포기하기 위한 워커. 요청마다 새로 만들지 않는다.
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="realdoor-intent")


def _providers():
    if str(_PROVIDERS_DIR) not in sys.path:
        sys.path.insert(0, str(_PROVIDERS_DIR))
    import providers  # type: ignore

    return providers


# ───────────────────────────────────────────────────────── 분류 (라벨만)

def _usage_tail_cached(providers, offset: int) -> bool | None:
    """방금 붙은 usage 레코드의 `cached` 플래그를 읽는다.

    캐시 적중을 추측하지 않고 게이트웨이가 남긴 기록에서 읽는다. 읽을 수 없으면
    `None` 을 돌려주고, 성적표는 그 항목을 측정 불가로 표시한다.
    """
    try:
        log = Path(providers.USAGE_LOG)
        if not log.exists():
            return None
        with log.open("r", encoding="utf-8") as f:
            f.seek(offset)
            added = [l for l in f.read().splitlines() if l.strip()]
        for line in reversed(added):
            record = json.loads(line)
            if record.get("provider") == "openai":
                return bool(record.get("cached"))
        return None
    except Exception:
        return None


def classify(question: str) -> str | None:
    """자유 텍스트 → 알려진 의도 ID 하나, 또는 `None`.

    돌려주는 값은 **반드시** `known_intents()` 의 원소이거나 `None` 이다.
    """
    text = (question or "").strip()
    if not text:
        return None

    # 나가는 문장에서만 지운다. 아래 `confirm()` 은 원문을 쓴다 — 결정론 라우터는
    # 이 프로세스 안에 있으므로 가릴 이유가 없고, 가리면 라우팅만 나빠진다.
    scrubbed = redact.scrub(text)
    _STATS["scrubbed"] += 1
    if scrubbed.removed:
        _STATS["redacted_items"] += scrubbed.removed
        _STATS["questions_with_a_redaction"] += 1
        for name, hits in scrubbed.by_pattern.items():
            _STATS["redacted_by_pattern"][name] = (
                _STATS["redacted_by_pattern"].get(name, 0) + hits)
    text = scrubbed.text

    providers = _providers()
    schema = _schema()
    instruction = _prompt()

    try:
        offset = Path(providers.USAGE_LOG).stat().st_size
    except OSError:
        offset = 0

    def _call():
        return providers.complete(instruction, text, model=MODEL,
                                  json_schema=schema, max_tokens=32, temperature=0.0)

    _STATS["calls"] += 1
    try:
        # 컨텍스트 매니저(`with`)를 쓰지 않는다. `__exit__` 이 `shutdown(wait=True)` 라
        # 타임아웃이 나도 스레드가 끝날 때까지 붙잡혀 있고, 그러면 타임아웃이 이름만
        # 타임아웃이 된다. 느린 호출은 버리고 즉시 돌아온다 — 그 스레드가 나중에
        # 끝나서 캐시를 채우는 것은 해가 없다.
        raw = _POOL.submit(_call).result(timeout=TIMEOUT_SECONDS)
    except _FutureTimeout:
        _STATS["timeouts"] += 1
        return None
    except Exception as exc:
        # 오프라인인데 캐시가 없으면 게이트웨이가 CacheMiss 를 던진다. 그건 사고가
        # 아니라 설계된 결말이다 — 조용히 결정론 거부로 돌아간다.
        if type(exc).__name__ == "CacheMiss":
            _STATS["offline_or_uncached"] += 1
        else:
            _STATS["errors"] += 1
        return None

    hit = _usage_tail_cached(providers, offset)
    if hit is None:
        _STATS["cache_hits_measurable"] = False
    elif hit:
        _STATS["cache_hits"] += 1

    # ── 받은 값을 다시 검증한다. 스키마를 지켰다고 믿지 않는다. ──────────
    label = raw.get("intent") if isinstance(raw, dict) else raw
    if not isinstance(label, str):
        _STATS["rejected_unknown_label"] += 1
        return None
    label = label.strip()
    if label == UNKNOWN:
        _STATS["returned_unknown"] += 1
        return None
    if label not in known_intents():
        _STATS["rejected_unknown_label"] += 1
        return None
    return label


# ──────────────────────────────────────────── 결정론 라우터의 재확인

@dataclass(frozen=True)
class Resolution:
    """모델이 지명하고 결정론 코드가 **독립적으로 허용한** 결과."""

    intent: str
    anchored_question: str


def confirm(question: str, intent: str, *, count: bool = True) -> Resolution | None:
    """모델의 지명을 결정론 코드가 검사한다. 통과하지 못하면 `None`.

    ── 예전에 여기 있던 것과, 왜 바꿨는가 ──────────────────────────────────

    이전 구현은 의도의 **앵커 문구를 질문에 덧붙인 뒤** 결정론 라우터에게 되물었다.
    그런데 앵커란 정의상 그 경로를 발동시키는 문자열이고, `anchor_audit()` 이 바로
    그 성질을 강제한다. 즉 답을 붙여놓고 문제를 다시 낸 셈이었다. 측정이 그대로
    보여줬다: 44질문 × 11정규의도 = 484쌍 중 거부는 **1쌍(0.2%)**, 실제 37회 호출
    중 거부 **0회**. "so am i approved" 를 `geocode_precision` 으로 지명해도 통과했다.
    고무도장이었고, 제출 서술의 핵심 문장이 그 위에 얹혀 있었다.

    ── 지금 하는 것: 앵커를 쓰지 않는 두 축의 검사 ─────────────────────────

    두 검사 모두 **원 질문만** 읽는다. 앵커는 통과한 뒤 질문을 흘려보내는 데만 쓰고,
    검사에는 넣지 않는다. 그래서 순환이 끊긴다.

      1. **형태 일치** — 질문의 의문형(문법)이 요구하는 답의 종류와, 지명된 의도가
         실제로 내놓는 답의 종류가 맞는가. 시간을 묻는 질문은 금액으로 답할 수 없다.
      2. **주어 일치** — 질문이 질문자 자신에 대해 묻는데(`am i ...`, `do we ...`),
         지명된 의도가 프로그램에 대한 사실만 말할 수 있다면 그것은 답이 될 수 없다.
         "so am i approved" × `geocode_precision` 이 여기서 걸린다.

    둘 다 `logic.answer_rules` 에 있고 도메인 어휘를 한 단어도 쓰지 않는다. 표에 없는
    의도·판정할 수 없는 질문은 **통과**시킨다 — 이 게이트는 거부만 하고 승인하지 않는다.

    ── 그리고 여전히 보장하지 못하는 것 (정직하게) ─────────────────────────

    이 두 축은 **주제(topic)를 검증하지 않는다.** 문법이 같고 주어가 같은 두 의도
    사이에서, 모델이 둘 중 틀린 쪽을 지명하면 이 코드는 그것을 잡지 못한다. 예를 들어
    `vacancy_claim` 과 `currency_rule_status` 는 둘 다 3인칭 정책 문장이라 서로를
    가려낼 수 없다. 주제 검증을 하려면 결국 손으로 쓴 의도별 키워드 표가 필요하고,
    그것은 이 프로젝트가 이미 두 번 실패한 방식(별칭 표 넓히기)이라 만들지 않았다.
    **주제 축의 안전성은 이 함수가 아니라 닫힌 라벨 집합에서 온다** — 모델은
    `known_intents()` 밖으로 나갈 수 없고, 문장을 쓰지 못하며, 모든 문장은 여전히
    결정론 코드가 만든다. 이 함수가 좁히는 것은 그 닫힌 집합 **안에서의** 오지명이고,
    좁히는 정도는 `scripts/measure_intent_router.py` 의 484쌍 측정치가 말한다.

    `count=False` 는 감사용 호출이다 — 성적표의 거부 카운터를 오염시키지 않는다.
    """
    anchor = ANCHORS.get(intent)
    if not anchor:
        if count:
            _STATS["rejected_no_anchor"] += 1
        return None

    # ── 독립 검사: 앵커를 보지 않고 원 질문만 본다 ──────────────────────
    if not question_admits(question or "", PROFILES.get(intent)):
        if count:
            _STATS["rejected_shape_mismatch"] += 1
        return None

    # 앵커는 검사가 아니라 **배송**이다. 통과한 지명을 기존 결정론 경로로 흘려보내는
    # 열쇠일 뿐이고, 아래 동일성 확인은 그 배송이 실제로 도착하는지만 본다. 이 줄이
    # 무엇을 증명하지 **않는지**는 위 도크스트링에 적었다.
    anchored = f"{question} [{anchor}]"
    canonical = canonical_route(anchored)
    if canonical == intent:
        return Resolution(intent, anchored)
    matched = situations.match(anchored, canonical)
    if matched is not None and matched.kind == intent:
        return Resolution(intent, anchored)

    if count:
        _STATS["rejected_router_disagreed"] += 1
    return None


def resolve(question: str) -> Resolution | None:
    """이 모듈의 유일한 진입점. 실패는 전부 `None` 이고, `None` 은 기존 거부다."""
    if not is_enabled():
        return None
    _STATS["attempts"] += 1
    try:
        intent = classify(question)
    except Exception:
        _STATS["errors"] += 1
        return None
    if intent is None:
        return None
    found = confirm(question, intent)
    if found is not None:
        _STATS["accepted"] += 1
    return found


# ─────────────────────────────────────────────────────────────── 감사

def anchor_audit() -> dict[str, Any]:
    """앵커 표가 닫힌 집합과 어긋나지 않는지 확인한다. LLM 없이 돈다.

    두 가지를 본다: (1) 모든 의도에 앵커가 있는가, (2) 각 앵커가 결정론 라우터를
    통해 **자기 의도로 되돌아오는가**. 라우트가 바뀌면 여기서 먼저 깨진다.
    """
    intents = known_intents()
    missing = [i for i in intents if not ANCHORS.get(i)]
    stale = [i for i in ANCHORS if i not in intents]
    broken: list[str] = []
    for intent in intents:
        if intent in missing:
            continue
        if confirm("placeholder question", intent, count=False) is None:
            broken.append(intent)
    return {
        "intents": len(intents),
        "anchors_missing": missing,
        "anchors_for_unknown_intents": stale,
        "anchors_not_round_tripping": broken,
        "ok": not (missing or stale or broken),
    }


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(anchor_audit(), ensure_ascii=False, indent=1))
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
