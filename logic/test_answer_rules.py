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
