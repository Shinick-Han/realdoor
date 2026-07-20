"""Rule answering, and the qa_gold measurement itself.

The important tests here are not the ones that check 36/36. They are the falsification
tests at the bottom, which perturb the documents and require the answers to move. A
lookup table would pass the first kind and fail the second.
"""

from __future__ import annotations

import pytest

from logic.answer_rules import (
    answer,
    equivalent,
    load_qa_gold,
    route,
    score_against_gold,
    summary_line,
)
from logic.conftest import make_document, make_household
from logic.constants import RULE_IDS
from logic.household import households_from_views, load_gold_households


@pytest.fixture(scope="module")
def graded():
    return score_against_gold()


# =====================================================================================
# the measurement
# =====================================================================================


def test_all_36_records_are_graded(graded):
    assert graded["total"] == 36 == len(load_qa_gold())
    assert graded["correct"] + graded["abstained"] + graded["wrong"] == 36


def test_no_wrong_answers(graded):
    """Wrong is much worse than abstained. If this ever fails, read the details."""
    assert graded["wrong"] == 0, summary_line(graded) + "\n" + str(graded["wrong_details"])


def test_every_answer_cites_the_rules_gold_cites(graded):
    shortfall = [row["qa_id"] for row in graded["graded"] if not row["citation_ok"]]
    assert not shortfall, f"answers not citing gold's rule ids: {shortfall}"


def test_buckets_are_reported_separately(graded):
    """An abstention must never be counted as a correct answer."""
    for key in ("correct", "abstained", "wrong", "exact_matches", "semantic_matches"):
        assert key in graded
    assert graded["exact_matches"] + graded["semantic_matches"] == graded["correct"]


def test_derived_and_templated_are_reported_separately(graded):
    """A perfect result on templated sentences must not flatter the pipeline's result."""
    assert graded["derived_total"] == 24, "6 households x 4 computed answers"
    assert graded["templated_total"] == 12
    assert graded["derived_total"] + graded["templated_total"] == graded["total"]


def test_the_derived_half_is_the_one_that_carries_the_claim(graded):
    assert graded["derived_wrong"] == 0
    assert graded["derived_correct"] == graded["derived_total"], (
        f"{graded['derived_correct']}/{graded['derived_total']} derived answers correct"
    )


# =====================================================================================
# routing
# =====================================================================================


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What is the frozen 60% threshold for HH-001?", "frozen_threshold"),
        ("What annualized income should the scorer use for HH-001?", "annualized_income"),
        ("How does HH-001's amount compare with the frozen threshold?", "threshold_comparison"),
        ("What readiness status is expected for HH-001?", "readiness_status"),
        ("May the system call HH-001 eligible or ineligible?", "decision_boundary"),
        ("When do the frozen FY 2026 MTSP limits take effect?", "limits_effective_date"),
        ("Does a HUD LIHTC property record prove a unit is vacant?", "vacancy_claim"),
        ("Which geocode codes are suitable for address display?", "geocode_precision"),
        ("What should happen to instructions embedded inside a pay stub?",
         "embedded_instructions"),
        ("Is the 60-day currency rule an official universal LIHTC rule?", "currency_rule_status"),
        ("What is the federal statutory anchor for LIHTC?", "statutory_anchor"),
    ],
)
def test_routing(question, expected):
    assert route(question) == expected


def test_an_unroutable_question_abstains_rather_than_guessing():
    result = answer("What is the airspeed velocity of an unladen swallow?")
    assert result.abstained
    assert result.text is None
    assert result.what_would_resolve_it


def test_a_question_about_an_unknown_household_abstains():
    result = answer("What is the frozen 60% threshold for HH-999?")
    assert result.abstained


def test_every_non_abstained_answer_carries_a_citation():
    for record in load_qa_gold():
        result = answer(record["question"], record.get("household_id"))
        if not result.abstained:
            assert result.rule_ids, f"{record['qa_id']} answered with no rule id"
            for rid in result.rule_ids:
                assert rid in RULE_IDS


def test_an_answer_object_cannot_be_built_uncited():
    from logic.answer_rules import Answer

    with pytest.raises(ValueError, match="must cite at least one rule"):
        Answer("something true", (), "kind")


def test_the_decision_boundary_answer_refuses_the_label():
    result = answer("May the system call HH-001 eligible or ineligible?")
    assert result.text.startswith("No.")
    assert "comparison" in result.text and "human" in result.text
    assert result.rule_ids == ("CH-DECISION-001",)


# =====================================================================================
# equivalence -- the grader must not be a rubber stamp
# =====================================================================================


def test_exact_match():
    assert equivalent("$72,000 for household size 1.", "$72,000 for household size 1.") == \
        (True, "exact")


def test_normalization_ignores_case_and_trailing_period():
    ok, tier = equivalent("BELOW_OR_EQUAL", "below_or_equal")
    assert ok and tier == "exact"


def test_a_different_number_is_wrong():
    ok, _ = equivalent("$72,001 for household size 1.", "$72,000 for household size 1.")
    assert not ok


def test_flipped_polarity_is_wrong():
    ok, _ = equivalent("Yes. It is a frozen convention for this hackathon simulation.",
                       "No. It is a frozen convention for this hackathon simulation.")
    assert not ok


def test_dropping_content_is_wrong():
    ok, _ = equivalent("No.", "No. The dataset is a project inventory, not a vacancy feed.")
    assert not ok


def test_a_vaguer_answer_cannot_pass_as_a_match():
    ok, _ = equivalent("It depends on the household.", "below_or_equal")
    assert not ok


def test_the_grader_fires_on_a_planted_wrong_answer():
    """Negative control: if the grader cannot fail, its 36/36 means nothing."""
    ok, _ = equivalent("above", "below_or_equal")
    assert not ok


# =====================================================================================
# falsification -- the answers must be computed, not remembered
# =====================================================================================


def _perturbed(views, mutate):
    return households_from_views([mutate(dict(v)) for v in views])


def test_changing_household_size_changes_the_threshold_answer():
    """If this passed unchanged, the threshold answer would be a memorized string."""
    house = make_household(
        "HH-980",
        make_document("HH-980-D01", "application_summary", household_size=3,
                      application_date="2026-07-10"),
    )
    result = answer("What is the frozen 60% threshold for HH-980?",
                    households={"HH-980": house})
    assert result.text == "$92,580 for household size 3."


def test_changing_gross_pay_changes_the_income_answer():
    house = make_household(
        "HH-981",
        make_document("HH-981-D01", "application_summary", household_size=1,
                      application_date="2026-07-10"),
        make_document("HH-981-D02", "pay_stub", pay_date="2026-06-27", pay_frequency="biweekly",
                      regular_hours=76, hourly_rate=30.0, gross_pay=2280.0),
    )
    result = answer("What annualized income should the scorer use for HH-981?",
                    households={"HH-981": house})
    assert result.text == "$59,280.00 under the frozen annualization convention."


def test_a_large_income_flips_the_comparison_to_above():
    house = make_household(
        "HH-982",
        make_document("HH-982-D01", "application_summary", household_size=1,
                      application_date="2026-07-10"),
        make_document("HH-982-D02", "pay_stub", pay_date="2026-06-27", pay_frequency="biweekly",
                      regular_hours=80, hourly_rate=60.0, gross_pay=4800.0),
    )
    result = answer("How does HH-982's amount compare with the frozen threshold?",
                    households={"HH-982": house}, checklists={})
    assert result.text == "above", "124,800 is above the 72,000 limit for size 1"


def test_expiring_a_document_flips_the_readiness_answer(gold_households, pack_checklists):
    """HH-001 is READY. Push its letter out of the window and it must stop being READY."""
    from logic.household import load_gold_households
    import json
    from logic.household import default_gold_path

    views = [json.loads(line) for line in
             default_gold_path().read_text(encoding="utf-8").splitlines() if line.strip()]
    hh001 = [v for v in views if v["household_id"] == "HH-001"]
    before = answer("What readiness status is expected for HH-001?",
                    households=households_from_views(hh001))
    assert before.text == "READY_TO_REVIEW"

    aged = []
    for view in hh001:
        copy = json.loads(json.dumps(view))
        for item in copy["fields"]:
            if item["field"] == "document_date":
                item["value"] = "2026-01-05"
        aged.append(copy)
    after = answer("What readiness status is expected for HH-001?",
                   households=households_from_views(aged))
    assert after.text == "NEEDS_REVIEW", "an expired letter must change the answer"


def test_a_household_of_nine_abstains_on_both_threshold_and_comparison():
    house = make_household(
        "HH-983",
        make_document("HH-983-D01", "application_summary", household_size=9,
                      application_date="2026-07-10"),
        make_document("HH-983-D02", "pay_stub", pay_date="2026-06-27", pay_frequency="biweekly",
                      regular_hours=76, hourly_rate=28.5, gross_pay=2166.0),
    )
    threshold = answer("What is the frozen 60% threshold for HH-983?",
                       households={"HH-983": house}, checklists={})
    comparison = answer("How does HH-983's amount compare with the frozen threshold?",
                        households={"HH-983": house}, checklists={})
    assert threshold.abstained and comparison.abstained
    assert threshold.what_would_resolve_it


# =====================================================================================
# household size stated in the question
# =====================================================================================
#
# qa_gold has 36 records and not one of them names a household size in the question --
# every threshold record says "for HH-001" and lets the session supply the size. So
# 36/36 stayed green while the system answered "$72,000 for household size 1" to a
# question about a household of 3, and returned nothing at all when no household was in
# scope. The gold set could not see it. These tests can.


def test_the_size_pattern_matches_no_qa_gold_question():
    """The guard on width. If this ever fails, the pattern is too broad and the 36
    records are at risk -- their questions carry HH-001, 60%, 60-day and FY 2026, and a
    pattern that reads a household size out of any of those is reading noise."""
    from logic.answer_rules import question_household_size

    offenders = [r["qa_id"] for r in load_qa_gold()
                 if question_household_size(r["question"]) is not None]
    assert offenders == []


@pytest.mark.parametrize("question, expected", [
    ("What is the frozen 60% threshold for a household of 3?", 3),
    ("What is the frozen 60% threshold for household size 3?", 3),
    ("What is the 60% limit for a 3-person household?", 3),
    ("What is the frozen 60% threshold for 3 people?", 3),
    ("What is the frozen 60% threshold for a household of three?", 3),
    ("What is the frozen 60% threshold for a family of 4?", 4),
    ("What is the frozen 60% threshold for HH-001?", None),
    ("When do the frozen FY 2026 MTSP limits take effect?", None),
    ("Is the 60-day currency rule an official universal LIHTC rule?", None),
    ("What annualized income should the scorer use for HH-002?", None),
])
def test_question_household_size_reads_only_real_size_phrases(question, expected):
    from logic.answer_rules import question_household_size

    assert question_household_size(question) == expected


def test_size_in_question_wins_over_the_session_household(gold_households):
    """The reported defect. HH-001 is a household of 1; the question says 3."""
    result = answer("What is the frozen 60% threshold for a household of 3?",
                    "HH-001", households=gold_households)
    assert not result.abstained
    assert "92,580" in result.text
    assert "72,000" not in result.text


def test_a_differing_session_household_is_named_in_the_answer(gold_households):
    """Answering the right question silently, while the reader believes it is about
    their own file, is the same defect wearing better clothes."""
    result = answer("What is the frozen 60% threshold for a household of 3?",
                    "HH-001", households=gold_households)
    assert "household of 1" in result.text
    assert "3" in result.text


def test_a_matching_session_household_gets_no_mismatch_note(gold_households):
    result = answer("What is the frozen 60% threshold for a household of 3?",
                    "HH-003", households=gold_households)
    assert "92,580" in result.text
    assert "not for this session" not in result.text


def test_size_in_question_answers_with_no_household_in_scope(gold_households):
    """The second half of the defect: the row is in the table, so silence was wrong."""
    result = answer("What is the frozen 60% threshold for a household of 3?",
                    None, households=gold_households)
    assert not result.abstained
    assert result.text == "$92,580 for household size 3."
    assert result.rule_ids == ("HUD-MTSP-002",)


@pytest.mark.parametrize("size, amount", [
    (1, "72,000"), (2, "82,320"), (3, "92,580"), (4, "102,840"),
    (5, "111,120"), (6, "119,340"), (7, "127,560"), (8, "135,780"),
])
def test_every_frozen_row_is_reachable_from_the_question_alone(size, amount, gold_households):
    result = answer(f"What is the frozen 60% threshold for a household of {size}?",
                    None, households=gold_households)
    assert not result.abstained
    assert amount in result.text


@pytest.mark.parametrize("size", [9, 10, 12])
def test_a_size_outside_the_table_gives_the_range_and_no_number(size, gold_households):
    """Not silence, and not an extrapolation either. HUD publishes a rule for sizes above
    8; our frozen table does not contain those rows, so we do not have those numbers."""
    from logic.constants import LIMITS_60_PCT

    result = answer(f"What is the frozen 60% threshold for a household of {size}?",
                    None, households=gold_households)
    assert result.abstained, "no number is claimed"
    assert result.text, "but it does not answer with nothing"
    assert "1 to 8" in result.text
    assert "extrapolate" in result.text
    # no invented amount, and no frozen row smuggled in as if it were the answer
    import re as _re
    assert _re.search(r"\$\s?[\d,]+", result.text) is None
    for amount in LIMITS_60_PCT.values():
        assert f"{amount:,}" not in result.text


@pytest.mark.parametrize("size", [3, 9])
def test_the_size_path_never_speaks_about_a_person(size, gold_households):
    """Rule CH-DECISION-001. A threshold is a number to compare against; this path must
    not slide into saying what it means for anyone."""
    banned = ("eligible", "ineligible", "qualify", "qualifies", "qualified", "approved",
              "denied", "rejected", "accepted", "entitled")
    result = answer(f"What is the frozen 60% threshold for a household of {size}?",
                    "HH-001", households=gold_households)
    lowered = (result.text or "").lower()
    for word in banned:
        assert word not in lowered


def test_the_qa_gold_threshold_records_are_untouched_by_the_size_path(gold_households):
    """Direct regression on the six records the new branch runs closest to."""
    expected = {
        "HH-001": "$72,000 for household size 1.",
        "HH-002": "$82,320 for household size 2.",
        "HH-003": "$92,580 for household size 3.",
        "HH-004": "$102,840 for household size 4.",
        "HH-005": "$111,120 for household size 5.",
        "HH-006": "$119,340 for household size 6.",
    }
    for hid, gold in expected.items():
        result = answer(f"What is the frozen 60% threshold for {hid}?", hid,
                        households=gold_households)
        assert result.text == gold


# =====================================================================================
# the question-form / answer-kind agreement gate
# =====================================================================================
#
# The defect these tests pin down: "when does the new 2026 income limit start counting"
# was answered "$92,580 for household size 3." -- a time question answered with a money
# figure, cited, and indistinguishable in tone from a right answer. The repair had to be
# structural, because the obvious repair (teach the effective-date alias one more phrasing)
# is what produced the defect in the first place.


def test_the_gate_uses_no_domain_vocabulary():
    """The claim that separates this from a wider alias table, asserted rather than argued.

    An alias table is a list of TOPIC words: "income", "limit", "paperwork". This gate is
    written in GRAMMAR -- interrogatives and auxiliaries -- so it generalises to phrasings
    nobody has authored. If a housing word ever appears in a question-side pattern, the
    gate has quietly become a second alias table and this test is the alarm.
    """
    import re as _re

    from logic import answer_rules as ar

    # Compare whole tokens, not substrings: "current" is a recency word and legitimately
    # contains "rent", and a substring test would call that a housing term.
    tokens = set()
    for pattern in (ar._TEMPORAL_QUESTION, ar._AMOUNT_QUESTION,
                    ar._YES_NO_QUESTION, ar._WH_WORD, ar._SELF_SUBJECT):
        tokens |= set(_re.findall(r"[a-z]+", pattern.pattern.lower()))

    domain_words = {
        "income", "incomes", "limit", "limits", "cap", "caps", "ceiling", "threshold",
        "household", "households", "family", "document", "documents", "paper", "papers",
        "paperwork", "form", "forms", "rent", "housing", "tenant", "renter", "eligible",
        "eligibility", "qualify", "approved", "denied", "vacancy", "vacant", "geocode",
        "statute", "statutory", "readiness", "ami", "hud", "salary", "wage", "wages",
        "earn", "pay", "size", "money", "dollar", "file", "application",
    }
    leaked = tokens & domain_words
    assert not leaked, f"domain vocabulary leaked into the gate: {sorted(leaked)}"

    # The same rule holds for the Korean half of the gate. 얼마/언제/뭐 are grammar the
    # way "how much"/"when"/"what" are; the moment a housing noun (소득, 한도, 가구,
    # 서류, 승인 ...) appears in a question-side pattern, the gate has become a Korean
    # alias table. The Hangul tokens are extracted the same way the Latin ones are.
    hangul_tokens = set()
    for pattern in (ar._TEMPORAL_QUESTION, ar._AMOUNT_QUESTION,
                    ar._YES_NO_QUESTION, ar._WH_WORD, ar._SELF_SUBJECT):
        hangul_tokens |= set(_re.findall(r"[가-힣]+", pattern.pattern))
    korean_domain_words = {
        "소득", "연소득", "수입", "연봉", "월급", "한도", "상한", "제한", "기준",
        "가구", "세대", "가족", "서류", "문서", "승인", "거절", "거부", "자격",
        "입주", "신청", "임대", "주택",
    }
    korean_leaked = hangul_tokens & korean_domain_words
    assert not korean_leaked, f"Korean domain vocabulary leaked: {sorted(korean_leaked)}"
    # The converse again: the Korean interrogatives are actually there.
    assert {"언제", "얼마", "무엇", "뭐"} <= hangul_tokens

    # And the converse, so the test cannot pass by the patterns being empty: the gate is
    # in fact built out of interrogatives and auxiliaries.
    assert {"when", "what", "which", "how", "much", "is", "are", "am", "do"} <= tokens


@pytest.mark.parametrize("question", [
    "when does the new 2026 income limit start counting",
    "as of what day is the new income cap",
    "since when has the income ceiling been in force",
    "when will the numbers be updated",
    "what year do these figures come from",
    "how recent do the limits have to be",
])
def test_a_time_question_is_never_answered_with_a_money_figure(question):
    """The whole point, stated once. None of these six phrasings is in any alias table,
    and the gate has never been shown any of them."""
    from logic.answer_rules import canonical_admits

    assert canonical_admits(question, "frozen_threshold") is False
    assert canonical_admits(question, "annualized_income") is False
    assert canonical_admits(question, "limits_effective_date") is True


@pytest.mark.parametrize("question", [
    "how much can i earn and still get in",
    "what amount do i have to stay under",
])
def test_an_amount_question_is_never_answered_with_a_date(question):
    from logic.answer_rules import canonical_admits

    assert canonical_admits(question, "limits_effective_date") is False
    assert canonical_admits(question, "frozen_threshold") is True


def test_a_question_about_the_asker_is_not_answered_with_a_program_fact():
    """The second axis. "so am i approved" is about the asker's standing; the geocoding
    convention is true whoever asks and answers nothing about anyone."""
    from logic.answer_rules import canonical_admits, question_scope, SCOPE_SELF

    assert question_scope("so am i approved") == SCOPE_SELF
    assert canonical_admits("so am i approved", "geocode_precision") is False
    assert canonical_admits("so am i approved", "statutory_anchor") is False
    # ...but the intents that CAN speak to the asker's own file stay reachable.
    assert canonical_admits("so am i approved", "decision_boundary") is True
    assert canonical_admits("am i under or over", "threshold_comparison") is True


def test_a_possessive_is_not_a_self_subject():
    """"which of these codes is ok to show on my address" is a question about the codes.
    Treating any first-person token as a self-question would veto correct routes."""
    from logic.answer_rules import canonical_admits, question_scope, SCOPE_GENERAL

    q = "which of these location codes is ok to actually show on my address"
    assert question_scope(q) == SCOPE_GENERAL
    assert canonical_admits(q, "geocode_precision") is True


def test_the_gate_only_ever_vetoes():
    """It can turn a wrong answer into an abstention. It can never invent a route.

    An unknown intent and an indeterminate question both pass, so no phrasing can be
    ADMITTED by this code that was not already reachable without it.
    """
    from logic.answer_rules import canonical_admits, question_admits

    assert canonical_admits("my income went up last month", "frozen_threshold") is True
    assert canonical_admits("anything at all", None) is True
    assert question_admits("so am i approved", None) is True


def test_every_canonical_route_declares_a_profile():
    """A route without a profile is a silent hole in the gate -- it would pass everything.
    New routes have to declare what kind of thing they answer."""
    from logic.answer_rules import ROUTES, CANONICAL_PROFILES

    for item in ROUTES:
        assert item.kind in CANONICAL_PROFILES, f"{item.kind} declares no answer profile"


def test_the_pack_questions_are_never_shown_the_gate(gold_households):
    """The structural reason the 36 cannot move: `route()` catches every pack question, and
    a question `route()` catches never reaches the alias path or the classifier."""
    from logic.answer_rules import route

    for record in load_qa_gold():
        assert route(record["question"]) is not None, record["qa_id"]


# =====================================================================================
# the gate reads Korean interrogative grammar
# =====================================================================================
#
# The defect these tests pin down: the gate's grammar was English-only, so a Korean
# question could never be shape-classified. That cut both ways -- "1인 가구의 소득
# 한도가 얼마예요?" could not be confirmed as an amount question, and "제가 승인받을 수
# 있나요?" could not be VETOED as a polar question about the asker, so a classifier
# nomination of a money intent for it would have sailed through. Teaching the gate the
# small enumerated set of Korean interrogative shapes closes both, without any Korean
# domain vocabulary (asserted above in test_the_gate_uses_no_domain_vocabulary).


def test_a_korean_amount_question_admits_money_and_vetoes_a_date():
    """얼마 is "how much": the question's grammar requests an amount."""
    from logic.answer_rules import ANSWER_MONEY, ANSWER_RELATION, asked_shapes, canonical_admits

    q = "1인 가구의 소득 한도가 얼마예요?"
    assert asked_shapes(q) == frozenset({ANSWER_MONEY, ANSWER_RELATION})
    assert canonical_admits(q, "frozen_threshold") is True
    assert canonical_admits(q, "limits_effective_date") is False


def test_the_owner_phrasing_is_an_amount_question():
    """The acceptance phrasing: an eligibility frame around an amount interrogative.
    The matrix interrogative is 얼마, so the grammar requests a figure -- the routing of
    the eligibility frame itself is decided (and tested) in api/ask.py."""
    from logic.answer_rules import ANSWER_MONEY, ANSWER_RELATION, asked_shapes

    q = "이거 승인받으려면 1인가구 기준 연소득이 얼마정도여야 하나요?"
    assert asked_shapes(q) == frozenset({ANSWER_MONEY, ANSWER_RELATION})


def test_a_korean_temporal_question_is_never_answered_with_a_money_figure():
    """언제 is "when": the Korean twin of the defect the gate was built for."""
    from logic.answer_rules import ANSWER_DATE, asked_shapes, canonical_admits

    q = "새 소득 한도는 언제부터 적용되나요?"
    assert asked_shapes(q) == frozenset({ANSWER_DATE})
    assert canonical_admits(q, "frozen_threshold") is False
    assert canonical_admits(q, "annualized_income") is False
    assert canonical_admits(q, "limits_effective_date") is True


def test_a_korean_polar_question_is_never_answered_with_a_bare_figure():
    """~나요 with no wh-word is a yes/no question, exactly as a leading auxiliary is in
    English. Handing "$72,000" to someone who asked "제가 승인받을 수 있나요?" answers
    nothing -- and reads as a determination, which is worse than answering nothing."""
    from logic.answer_rules import ANSWER_DATE, ANSWER_MONEY, asked_shapes, canonical_admits

    q = "제가 승인받을 수 있나요?"
    shapes = asked_shapes(q)
    assert shapes is not None and not ({ANSWER_MONEY, ANSWER_DATE} & shapes)
    assert canonical_admits(q, "frozen_threshold") is False
    assert canonical_admits(q, "annualized_income") is False
    # ...while the intents whose answer is a policy sentence about the asker stay open.
    assert canonical_admits(q, "decision_boundary") is True


def test_a_korean_wh_question_with_a_polar_ending_is_not_polar():
    """뭐/무엇 must block the yes/no reading the way "what" does -- Korean wh-questions
    end in the same suffixes polar questions do."""
    from logic.answer_rules import asked_shapes

    assert asked_shapes("제 서류가 뭐가 필요한가요?") is None


def test_korean_self_subject_agreement():
    """제가/저희 as subject work the way "am i" / "do we" do; possessives do not."""
    from logic.answer_rules import SCOPE_GENERAL, SCOPE_SELF, canonical_admits, question_scope

    assert question_scope("제가 승인받을 수 있나요?") == SCOPE_SELF
    assert question_scope("저희가 지금 내야 하나요?") == SCOPE_SELF
    # An asker-predicated question is never answered with a program fact.
    assert canonical_admits("제가 승인받을 수 있나요?", "geocode_precision") is False
    assert canonical_admits("제가 승인받을 수 있나요?", "statutory_anchor") is False
    # Possessive 제 ("my") is about the papers, not the asker -- same as English "my".
    assert question_scope("제 서류가 뭐가 필요한가요?") == SCOPE_GENERAL
    # 문제가 contains the syllables 제가 and says nothing about the speaker.
    assert question_scope("문제가 있나요?") == SCOPE_GENERAL


def test_korean_lookalikes_do_not_trigger_the_shapes():
    """The enumerated exclusions, asserted: 언제나 ("always") is not 언제 ("when"), and
    얼마나 ("how (often/long/...)") is not 얼마 ("how much"). Both fall back to "no
    opinion", which can never veto."""
    from logic.answer_rules import asked_shapes

    assert asked_shapes("이 규칙은 언제나 적용되나요?") is None
    assert asked_shapes("서류가 얼마나 최근이어야 하나요?") is None


def test_only_the_matrix_interrogative_decides_the_asked_shape():
    """An embedded temporal clause must not hijack the question it is embedded in.

    "who made up the rule about how recent my papers have to be" asks for an authority.
    The recency phrase describes the rule, not the request. Reading it as a date question
    vetoes the correct route -- this is a real regression that a measurement caught, and
    the fix was to compare interrogative POSITION rather than mere presence.
    """
    from logic.answer_rules import asked_shapes, canonical_admits, ANSWER_DATE

    embedded = "who made up the rule about how recent my papers have to be"
    assert asked_shapes(embedded) is None
    assert canonical_admits(embedded, "currency_rule_status") is True

    # The same phrase in matrix position still governs.
    assert asked_shapes("how recent do my papers have to be") == frozenset({ANSWER_DATE})
