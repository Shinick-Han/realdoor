# -*- coding: utf-8 -*-
"""
test_redact.py — 나가기 직전 식별자 제거의 **두 방향**을 함께 강제한다.

한 방향만 재면 이 기능은 쉽게 거짓말이 된다. 제거를 세게 하면 "많이 지웠다"는 숫자는
좋아지는데 질문이 알아볼 수 없게 되어 분류기가 죽고, 약하게 하면 분류는 멀쩡한데
지운 게 없다. 그래서 여기서는 (1) 아는 형태를 지우는가, (2) **지우면 안 되는 것을
남기는가**, (3) 지운 뒤에도 질문의 주제어가 살아 있는가를 같이 본다.

정확도 자체는 모델의 성질이라 여기서 증명하지 않는다. 증명하는 것은 제거가 주제어를
건드리지 않는다는 구조적 성질이고, 라이브 비교는 사람이 따로 돌린다.
"""
from __future__ import annotations

import pytest

from api import redact, route_llm


# ── 아는 형태는 지우는가 ───────────────────────────────────────────────

@pytest.mark.parametrize("text,pattern", [
    ("email me at renter.name@example.com about it", "email"),
    ("my ssn is 123-45-6789", "ssn_shaped"),
    ("call me at 617-555-0134", "phone"),
    ("call me at (617) 555-0134", "phone"),
    ("call me at +1 617 555 0134", "phone"),
    ("전화는 010-1234-5678 입니다", "phone"),
    ("I live at 302 Glass Street and my pay stub is too old", "street_address"),
    ("we moved to 45 North Harbor Avenue last year", "street_address"),
    ("my address is 12 Elm Rd Apt 4B", "street_address"),
    ("the office is at Boston, MA 02139 today", "postal_code"),
    ("zip code 02139 is where I rent", "postal_code"),
    ("ZIP+4 is 02139-1234 on the form", "postal_code"),
])
def test_known_identifier_shapes_are_replaced(text, pattern):
    out = redact.scrub(text)
    assert out.removed >= 1, f"nothing removed from {text!r}"
    assert pattern in out.by_pattern, f"{pattern} did not fire: {out.by_pattern}"
    assert "removed]" in out.text


def test_ssn_wins_over_the_phone_pattern():
    """둘 다 숫자와 하이픈이다. 순서가 뒤집히면 SSN 이 전화번호로 기록된다."""
    out = redact.scrub("my ssn is 123-45-6789")
    assert out.by_pattern == {"ssn_shaped": 1}


# ── 지우면 안 되는 것을 남기는가 ───────────────────────────────────────

@pytest.mark.parametrize("text", [
    # 금액. 지우면 의도 분류가 나빠지고, 그 자체로 사람을 지목하지 않는다.
    "my income is 45000 a year",
    "I earn $52,480 annually and want to know the limit",
    "the threshold is 60% of area median income",
    # 규칙 용어에 붙은 숫자.
    "is the 60-day currency rule official",
    "when do the frozen FY 2026 MTSP limits take effect",
    "what is the limit for a household of 4",
    # 접미어 없는 숫자+단어. 주소가 아니다.
    "I uploaded 302 pages of documents",
    "section 8 applies to me",
])
def test_figures_and_rule_language_survive(text):
    out = redact.scrub(text)
    assert out.removed == 0, f"over-removed from {text!r}: {out.by_pattern}"
    assert out.text == text


def test_the_topic_words_survive_a_redaction():
    """지운 뒤에도 분류기가 볼 주제어가 문장에 남아 있어야 한다."""
    out = redact.scrub("I live at 302 Glass Street and my pay stub is too old")
    assert out.removed == 1
    assert "pay stub" in out.text
    assert "too old" in out.text
    assert "Glass Street" not in out.text


def test_a_placeholder_is_left_behind_not_a_hole():
    out = redact.scrub("write to me at a@b.com please")
    assert out.text == "write to me at [email removed] please"


def test_empty_input_is_handled():
    assert redact.scrub("").text == ""
    assert redact.scrub("").removed == 0


# ── 계측이 정직한가 ────────────────────────────────────────────────────

def test_pattern_names_are_unique_and_named():
    names = redact.pattern_names()
    assert len(names) == len(set(names))
    assert set(names) == {"email", "ssn_shaped", "phone", "street_address",
                          "postal_code"}


def test_classify_scrubs_before_the_call_and_counts_it(monkeypatch):
    """모델이 실제로 받은 문자열을 붙잡아 확인한다. 계측만 보고 믿지 않는다."""
    route_llm.reset_stats()
    seen: list[str] = []

    class _Capture:
        USAGE_LOG = "does-not-exist.jsonl"

        def complete(self, instruction, text, **kwargs):
            seen.append(text)
            return {"intent": "readiness_status"}

    monkeypatch.setenv("REALDOOR_LLM_ROUTER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(route_llm, "_providers", lambda: _Capture())

    route_llm.classify("I live at 302 Glass Street, call 617-555-0134")

    assert len(seen) == 1
    assert "Glass Street" not in seen[0]
    assert "617-555-0134" not in seen[0]

    s = route_llm.stats()
    assert s["scrubbed"] == 1
    assert s["questions_with_a_redaction"] == 1
    assert s["redacted_items"] == 2
    assert s["redacted_by_pattern"] == {"street_address": 1, "phone": 1}
    route_llm.reset_stats()


def test_the_deterministic_confirmation_still_sees_the_original():
    """앵커 확인은 원문으로 한다. 제거는 나가는 쪽에만 쓴다."""
    found = route_llm.confirm("I live at 302 Glass Street, when does this kick in",
                              "limits_effective_date")
    assert found is not None
    assert "302 Glass Street" in found.anchored_question


def test_reset_clears_the_per_pattern_table():
    route_llm._STATS["redacted_by_pattern"]["email"] = 3
    route_llm.reset_stats()
    assert route_llm.stats()["redacted_by_pattern"] == {}
    assert route_llm.stats()["cache_hits_measurable"] is True


def test_selftest_publishes_the_limits_of_this_measure(monkeypatch):
    """성적표가 스스로 불완전하다고 말하는지. 말하지 않으면 이 항목은 거짓이 된다."""
    from api import selftest as selftest_mod

    monkeypatch.setenv("REALDOOR_LLM_ROUTER", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-real-key")
    section = selftest_mod.intent_router_section()

    assert "identifiers_replaced" in section
    assert "identifiers_replaced_by_pattern" in section
    assert "questions_scrubbed_before_sending" in section
    note = section["redaction_note"].lower()
    assert "not a personal-data filter" in note
    assert "not caught here" in note
    # 완전성을 주장하는 어휘가 없어야 한다.
    for banned in ("all personal", "fully anonymis", "fully anonymiz",
                   "guarantee", "complete removal"):
        assert banned not in note, f"redaction note overclaims: {banned!r}"
