# -*- coding: utf-8 -*-
"""성적표의 숫자가 **자기가 말하는 것을 재고 있는지** 확인한다.

이 파일이 생긴 이유는 구체적이다. `calculation_section` 의 threshold 10쌍 루프가
주최자 함수만 부르고 예외가 안 나면 일치로 세고 있었다. 우리 구현은 import 되지도
않았다. 화면에는 90/90 이 떴지만 그중 10 은 아무것도 비교하지 않은 숫자였다.

그런 결함은 값을 확인하는 시험으로는 잡히지 않는다 — 90 은 그때도 90 이었다.
잡으려면 **우리 쪽을 고의로 망가뜨렸을 때 숫자가 떨어지는지**를 봐야 한다.
계측기가 자기 대상에 실제로 연결돼 있는지를 재는 시험이고, 그래서 여기 있다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "eval")):
    if path not in sys.path:
        sys.path.insert(0, path)

from api import gate, selftest  # noqa: E402


# =====================================================================================
# 양방향 비교 자체
# =====================================================================================
def _boom():
    raise ValueError("refused")


def _other_boom():
    raise TypeError("refused differently")


def test_equal_values_agree():
    assert selftest._both_ways(lambda: 1.0, lambda: 1.0) is True


def test_different_values_disagree():
    assert selftest._both_ways(lambda: 1.0, lambda: 2.0) is False


def test_both_refusing_the_same_way_is_agreement():
    """같은 입력을 같은 이유로 막는 것도 합의다."""
    assert selftest._both_ways(_boom, _boom) is True


def test_refusing_differently_is_a_disagreement():
    assert selftest._both_ways(_boom, _other_boom) is False


def test_one_side_raising_is_a_disagreement_not_a_skip():
    """예전 코드가 조용히 건너뛰던 바로 그 경우. 비대칭 실패는 불일치다."""
    assert selftest._both_ways(_boom, lambda: 1.0) is False
    assert selftest._both_ways(lambda: 1.0, _boom) is False


# =====================================================================================
# 계측기가 대상에 연결돼 있는가 — 우리 쪽을 망가뜨리면 숫자가 떨어져야 한다
# =====================================================================================
def test_the_grid_is_the_size_the_screen_claims():
    section = selftest.calculation_section()
    assert section["checks"] == 90  # 16 amounts x 5 frequencies + 10 threshold pairs
    assert section["agree_with_organizer_reference"] + section["disagree"] == 90


def test_breaking_our_annualize_is_visible_on_the_scorecard(monkeypatch):
    from logic import income

    monkeypatch.setattr(income, "annualize", lambda amount, frequency: -1.0)
    section = selftest.calculation_section()
    assert section["disagree"] == 80, "the 80 annualize checks did not reach our code"
    assert section["agree_with_organizer_reference"] == 10


def test_breaking_our_threshold_comparison_is_visible_on_the_scorecard(monkeypatch):
    """이 시험이 결함을 잡는다. 고치기 전에는 우리 구현이 불리지 않았으므로
    아무리 망가뜨려도 90/90 이 그대로였다."""
    from logic import threshold

    monkeypatch.setattr(threshold, "compare_to_threshold",
                        lambda income, limit: "something else entirely")
    section = selftest.calculation_section()
    assert section["disagree"] == 10, "the 10 threshold checks did not reach our code"
    assert section["agree_with_organizer_reference"] == 80


def test_a_threshold_comparison_that_dies_on_our_side_is_counted(monkeypatch):
    from logic import threshold

    def explode(income, limit):
        raise RuntimeError("our side fell over")

    monkeypatch.setattr(threshold, "compare_to_threshold", explode)
    section = selftest.calculation_section()
    assert section["disagree"] == 10
    assert len(section["disagreeing_inputs"]) == 10


def test_disagreements_are_named_not_just_counted(monkeypatch):
    from logic import threshold

    monkeypatch.setattr(threshold, "compare_to_threshold", lambda income, limit: "wrong")
    section = selftest.calculation_section()
    assert all("compare_to_threshold" in entry for entry in section["disagreeing_inputs"])


def test_the_section_carries_no_decision_shaped_key():
    assert gate.scan(selftest.calculation_section()) == []


# =====================================================================================
# 하드코딩되어 있던 숫자
# =====================================================================================
def test_distinct_hostile_inputs_are_counted_from_the_pack():
    """24 는 24개의 독립 시행이 아니라는 것이 이 절의 요지다. 그렇다면 12 도
    손으로 적을 것이 아니라 세어야 한다."""
    import run_adversarial  # eval/

    tests = run_adversarial.load_tests()
    expected = len({test["input"] for test in tests})

    section = selftest.adversarial_section(
        lambda text: {"answer": "I cannot help with that."})
    assert section["distinct_inputs"] == expected
    assert section["total_tests"] == len(tests)
    assert section["distinct_inputs"] < section["total_tests"]


@pytest.mark.parametrize("section_name", ["calculation", "adversarial"])
def test_no_section_reports_a_measured_status_without_numbers(section_name):
    section = (selftest.calculation_section() if section_name == "calculation"
               else selftest.adversarial_section(lambda text: {"answer": "no"}))
    assert section["status"] == "measured"
    assert any(isinstance(value, int) for value in section.values())
