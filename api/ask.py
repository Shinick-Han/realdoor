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
"""
from __future__ import annotations

import re
from typing import Any

from logic.answer_rules import answer as answer_rule
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

    # ── 1) 자격 판정 요구 ───────────────────────────────────────────────
    if _DECIDE.search(q):
        return _refusal(
            "eligibility_refused",
            "This service does not decide eligibility, and will not say whether anyone "
            "qualifies. It reports what the documents show, what is missing or expired, "
            "and how the annualized amount compares with the frozen threshold. The "
            "determination is made by a qualified housing professional.",
            "ask what the threshold is, what the annualized amount is, or what is still "
            "missing",
            ["CH-DECISION-001", "CH-READINESS-001"],
        )

    # ── 정상 질문: 결정론 규칙 응답기로 ─────────────────────────────────
    ans = answer_rule(q, household_id, households=households,
                      checklists=load_pack_checklists())
    d = ans.to_dict()
    d["refused"] = False
    d["citations"] = _citations(list(d.get("rule_ids", [])))
    d["notice"] = NOTICE
    return d
