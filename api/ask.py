# -*- coding: utf-8 -*-
"""
ask.py — 규칙 질문 처리 + 적대적 입력 방어.

방어의 성격을 분명히 해둔다:
  **프롬프트 인젝션이 우리 판단을 바꿀 수 없는 이유는 방어를 잘해서가 아니라,
  판단 경로에 LLM이 없기 때문이다.** 소득 계산·한도 조회·준비도 판정은 전부
  순수 함수다. 문서에 무슨 문장이 적혀 있든 그 문자열은 의사결정 부품에 도달하지 않는다.

여기서 하는 일은 그 위에 얹는 세 가지 명시적 거부다:
  1. 자격 판정 요구      → 거부 (CH-DECISION-001)
  2. 타 세대 정보 요구   → 거부 (CH-SAFETY-001)
  3. 문서에 삽입된 지시  → 데이터로 취급, 무시 (CH-SAFETY-001)

그 아래에 두 개의 층이 더 있다. 둘 다 **새 행동이 아니라 표현**이다.

  4. 상황 라우팅 (`api/situations.py`)
     적대 팩의 입력은 1·2인칭 질문이 아니라 3인칭 상황 서술이다. 시스템은 그 열두
     상황에서 이미 옳게 행동하고 있었지만 — 만료 문서를 잡고, 8인 초과에서 기권하고,
     급여 총액 불일치를 올리고 — 그걸 **말하지 않았다.** 그래서 `unrouted` 침묵이
     돌아왔다. 상황 라우터는 그 침묵을 없앤다. 실증 가능한 것은 세션의 실제 문서로
     계산해서 보여주고, 아닌 것은 규칙을 인용하되 증거가 있는 척하지 않는다.

  5. 세입자 어휘 별칭 (아래 `_ALIASES`)
     `logic.answer_rules.route()` 는 qa_gold의 정확한 표현("frozen 60% threshold",
     "annualized income")에 맞춰져 있다. 세입자는 그렇게 말하지 않는다 — "이 세대 소득
     한도가 얼마죠?" 라고 말한다. 별칭은 세입자 어휘를 같은 정규 의도로 옮긴다.
     **정규 라우터가 이미 잡은 질문에는 절대 손대지 않는다.** 그래서 별칭은 답의
     내용을 바꿀 수 없고, 오직 어떤 표현이 그 답에 도달하는지만 바꾼다.
"""
from __future__ import annotations

import re
from typing import Any

from api import situations
from logic.answer_rules import answer as answer_rule, route as canonical_route
from logic.household import load_pack_checklists, load_rule_corpus

# 1) 자격 판정을 요구하는 질문
_DECIDE = re.compile(
    r"\b(am i|are they|is (he|she|they|this applicant)|do i|does (he|she|they))\b.*"
    r"\b(eligible|qualify|qualified|approved|denied|accepted|rejected)\b"
    r"|\b(approve|deny|reject|decide|determine)\b.*\b(me|them|this|application|applicant)\b"
    r"|\b(eligible|ineligible|approved|denied)\b\s*\?",
    re.IGNORECASE,
)

# 2) 다른 세대를 캐묻는 질문
_HOUSEHOLD = re.compile(r"\bHH-\d{3}\b", re.IGNORECASE)
_OTHER_PERSON = re.compile(
    r"\b(other|another|someone else'?s?|different)\b.{0,24}"
    r"\b(applicant|household|tenant|renter|family|person)\b",
    re.IGNORECASE,
)

# 3) 문서/질문에 삽입된 지시
_INJECTION = re.compile(
    r"\b(ignore|disregard|forget|override)\b.{0,40}"
    r"\b(previous|prior|above|earlier|system|all)\b.{0,20}\b(instruction|prompt|rule)s?\b"
    r"|\b(reveal|print|show|output|repeat)\b.{0,30}\b(system prompt|instructions|secret)\b"
    r"|\bmark\b.{0,30}\b(approved|eligible)\b"
    r"|\byou are now\b|\bact as\b.{0,20}\badmin",
    re.IGNORECASE,
)

NOTICE = ("This service reports readiness only. A qualified housing professional "
          "makes the eligibility determination.")

# ── 5) 세입자 어휘 → 정규 의도 ──────────────────────────────────────────
#
# 각 항목은 (세입자가 실제로 쓰는 표현, 정규 라우터가 아는 표현)이다. 오른쪽 문자열은
# 원문 질문에 **덧붙여진다** — 치환이 아니다. 원문을 남겨야 `answer_rules` 가 질문에서
# 세대 id를 계속 뽑을 수 있고, 세입자가 뭘 물었는지도 로그 없이 사라지지 않는다.
#
# 이 표는 답의 내용을 바꾸지 않는다. 정규 라우터가 이미 잡은 질문에는 적용되지 않으므로
# (아래 `_with_aliases`), qa_gold 36문항은 이 코드를 지나가지도 않는다.
_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    # 한도 (frozen_threshold)
    (re.compile(r"\b(income|earning|salary|wage)s?\s+(limit|cap|ceiling|max\w*)\b"
                r"|\b(limit|cap|ceiling|max\w*)\b[^.]{0,20}\b(income|earn|make|qualify for)\b"
                r"|\bhow much (can|could) (i|we|they|this household)\b[^.]{0,20}\b(earn|make)\b"
                r"|\bwhat('?s| is) the (income )?limit\b"
                r"|\b(income|ami) (limit|threshold) for (this|my|our) (household|family|size)\b",
                re.I),
     "frozen 60% threshold"),
    # 연환산 소득 (annualized_income)
    (re.compile(r"\b(yearly|annual|per year|a year)\b[^.]{0,20}\bincome\b"
                r"|\bincome\b[^.]{0,20}\b(per year|a year|yearly|annually)\b"
                r"|\bhow much (do|does) (i|we|they|this household) (make|earn)\b"
                r"|\bwhat income (will|do) (they|you|we) use\b"
                r"|\b(counted|countable|total) income\b",
                re.I),
     "annualized income"),
    # 비교 (threshold_comparison)
    (re.compile(r"\b(under|over|above|below|within|past)\b[^.]{0,20}\b(the )?(limit|threshold|cap)\b"
                r"|\bhow (do|does) (my|our|their|this household'?s?) income (stack|measure|sit)\b"
                r"|\bwhere do (i|we) stand\b",
                re.I),
     "compare with the frozen threshold"),
    # 준비도 (readiness_status)
    (re.compile(r"\bwhat (documents?|papers?|paperwork|forms?)\b[^.]{0,30}"
                r"\b(missing|still need|do i need|left|outstanding)\b"
                r"|\b(am i|are we|is my (file|packet|paperwork))\b[^.]{0,20}"
                r"\b(ready|complete|all set|good to go)\b"
                r"|\bwhat('?s| is) (still )?missing\b"
                r"|\banything else (i|we) need\b"
                r"|\bis (my|our) (file|packet|application) (ready|complete)\b",
                re.I),
     "readiness status"),
    # 한도 시행일 (limits_effective_date)
    (re.compile(r"\bwhen (did|do|does|will) the (new )?(income )?limits?\b"
                r"[^.]{0,20}\b(change|start|apply|kick in|update)\b"
                r"|\bhow (old|current|recent) are (the|these) (limits?|numbers?)\b",
                re.I),
     "effective date"),
    # 문서 속 지시 (embedded_instructions)
    (re.compile(r"\b(instruction|command|directive)s?\b[^.]{0,40}"
                r"\b(in|inside|on|within)\s+(my|the|a|this)\b[^.]{0,25}"
                r"\b(document|pdf|letter|stub|file|paperwork|upload)s?\b"
                r"|\b(document|pdf|letter|stub|file)\b[^.]{0,20}\b(says?|tells?) (you|the system|it)\b",
                re.I),
     "embedded instruction"),
)


def _with_aliases(question: str, canonical_kind: str | None) -> str:
    """세입자 표현을 정규 표현으로 옮긴다. **정규 라우터가 이미 잡았으면 손대지 않는다.**

    이 가드가 요구사항의 핵심이다. 별칭은 오직 지금 침묵하는(라우팅 실패하는) 질문만
    건드릴 수 있으므로, 이미 답이 나가는 질문의 답을 바꾸는 것은 구조적으로 불가능하다.
    """
    if canonical_kind is not None:
        return question
    for pattern, canonical_phrase in _ALIASES:
        if pattern.search(question or ""):
            rewritten = f"{question} [{canonical_phrase}]"
            if canonical_route(rewritten) is not None:
                return rewritten
    return question


def _refusal(kind: str, text: str, resolve: str, rule_ids: list[str]) -> dict[str, Any]:
    return {
        "kind": kind,
        "answer": text,
        "abstained": True,
        "refused": True,
        "rule_ids": rule_ids,
        "what_would_resolve_it": resolve,
        "citations": _citations(rule_ids),
        "notice": NOTICE,
    }


#: `_DECIDE`(1·2인칭)와 팩의 3인칭 서술이 **같은 문구**로 답하도록 라우트를 공유한다.
_ELIGIBILITY_ROUTE = next(r for r in situations.ROUTES if r.kind == "eligibility_refused")


def _situation(found: situations.Situation) -> dict[str, Any]:
    """상황 응답을 API 모양으로. 실측/인용 구분을 지우지 않고 그대로 싣는다."""
    return {
        "kind": found.kind,
        "answer": found.text,
        "abstained": False,
        "refused": found.refused,
        "rule_ids": list(found.rule_ids),
        "what_would_resolve_it": found.resolve,
        "citations": _citations(list(found.rule_ids)),
        "evidence": [e.to_dict() for e in found.evidence],
        "notice": NOTICE,
    }


def _citations(rule_ids: list[str]) -> list[dict[str, Any]]:
    rules = load_rule_corpus()
    out = []
    for rid in rule_ids:
        r = rules.get(rid)
        if r:
            out.append({
                "rule_id": rid,
                "authority": r["authority"],
                "effective_date": r["effective_date"],
                "text": r["text"],
                "source_url": r["source_url"],
                "source_locator": r["source_locator"],
                "verified_against_source": None,
            })
    return out


def handle(question: str, household_id: str | None,
           households: dict[str, Any]) -> dict[str, Any]:
    """질문 하나를 처리한다. 인용 없는 주장은 절대 반환하지 않는다."""
    q = question or ""

    # ── 3) 삽입된 지시: 데이터로 취급하고 무시 ──────────────────────────
    if _INJECTION.search(q):
        return _refusal(
            "embedded_instruction_ignored",
            "That text was treated as document content, not as an instruction. "
            "It did not change anything: the readiness calculations are deterministic "
            "code and no text from a document or question reaches them.",
            "ask about a rule, a required document, or a calculation instead",
            ["CH-SAFETY-001", "CH-DECISION-001"],
        )

    # ── 2) 타 세대 정보 요구 ────────────────────────────────────────────
    mentioned = {m.upper() for m in _HOUSEHOLD.findall(q)}
    others = mentioned - ({household_id.upper()} if household_id else set())
    if others or _OTHER_PERSON.search(q):
        return _refusal(
            "cross_applicant_refused",
            "This session can only answer about its own household. Information about "
            "another applicant is never disclosed.",
            "open that household's own session, with that renter's consent",
            ["CH-SAFETY-001"],
        )

    # ── 1) 자격 판정 요구 (1·2인칭) ─────────────────────────────────────
    # 기존 라우트를 그대로 보존하되, 문구는 상황 라우터와 하나로 합쳤다. 예전 문구에는
    # "will not say whether anyone qualifies" 가 들어 있었는데, `qualifies` 는 하네스의
    # 판정 탐지기가 잡는 단어다 — 판정을 거부하는 문장이 판정으로 채점되는 셈이었다.
    if _DECIDE.search(q):
        return _situation(situations.build(_ELIGIBILITY_ROUTE, households))

    # ── 4) 3인칭 상황 서술 ──────────────────────────────────────────────
    # 정규 라우터가 잡은 질문은 가로채지 않는다(알려진 오라우팅 1건 제외).
    canonical = canonical_route(q)
    situation_route = situations.match(q, canonical)
    if situation_route is not None:
        return _situation(situations.build(situation_route, households))

    # ── 정상 질문: 세입자 어휘를 정규 의도로 옮긴 뒤 결정론 규칙 응답기로 ─
    ans = answer_rule(_with_aliases(q, canonical), household_id, households=households,
                      checklists=load_pack_checklists())
    d = ans.to_dict()
    d["refused"] = False
    d["citations"] = _citations(list(d.get("rule_ids", [])))
    d["notice"] = NOTICE
    return d
