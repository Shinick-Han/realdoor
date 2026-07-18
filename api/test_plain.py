# -*- coding: utf-8 -*-
"""
test_plain.py — a mechanical compliance checker over every renter-facing string.

This file reports as much as it asserts. Most of the numbers here are measurements we
publish rather than gates we hide behind, because a checklist that only ever says "pass"
tells a reader nothing. Run it directly to see the whole report:

    python api/test_plain.py

WHAT IS A HARD GATE AND WHAT IS A REPORTED NUMBER
=================================================
Exactly one thing is a hard gate, and it is the one the standard actually requires:

  **Every renter-facing problem message must carry a non-empty action.**
  WCAG 2.2 SC 3.3.3 Error Suggestion is Level AA. If we detect an input error and we know
  how to fix it, we must say how. `test_every_problem_message_carries_an_action` fails the
  build at anything below 100%, and `test_no_action_gaps` fails if we ever shipped a
  message where we could not name a safe next step. Those gaps are recorded in the data
  rather than papered over with an empty string, so they are visible when they happen.

Everything else -- second person, active voice, reading grade -- is measured and printed.
Those are FPLG style goals we adopted voluntarily and WCAG AAA territory, not AA duties,
and dressing them up as pass/fail gates would misrepresent what the standards require.
They carry loose floors only, to catch a wholesale regression.

ON READABILITY, SPECIFICALLY
============================
There is no assertion anywhere in this file about a reading grade, and that is deliberate.

  * CMS publishes "Toolkit Part 7: Using readability formulas: a cautionary note".
  * Wang et al. (2013) found spreads up to roughly five grade levels across formulas on
    the same text.
  * Redish's critique notes the formulas assume running paragraphs, which screens of
    headlines and one-line actions are not.
  * SMOG is defined over a 30-sentence sample; below that it is extrapolation.

So a per-string grade is not defensible and we do not compute one. We report
Flesch-Kincaid and SMOG together, per screen, with the spread between them, on samples of
at least 100 words. If the two formulas disagree, that disagreement is the finding, and it
is printed rather than averaged away.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import plain, situations
from api.gate import scan
from logic.abstain import POLICY
from logic.readiness import GENERIC_CODE_BY_TRIGGER, PACK_CODE_BY_TRIGGER

MEASURED = plain.measure()
CHECKLIST = MEASURED["rules_checklist"]
READABILITY = MEASURED["readability"]

#: Loose floors. These exist to catch a wholesale regression, not to certify a standard.
#: They sit well below what we currently measure precisely so that a real drop trips them
#: while ordinary wording changes do not.
SECOND_PERSON_FLOOR = 0.80
ACTIVE_VOICE_FLOOR = 0.75


# =====================================================================================
# the one hard gate: WCAG 2.2 SC 3.3.3
# =====================================================================================


def test_every_problem_message_carries_an_action():
    """SC 3.3.3 Error Suggestion, Level AA. This one is required, so this one fails."""
    fraction = CHECKLIST["problem_messages_with_an_action_fraction"]
    missing = [m.code for m in plain.audit_messages()
               if m.kind == "problem" and not m.action.strip()]
    assert fraction == 1.0, (
        f"WCAG 2.2 SC 3.3.3 (AA) requires a correction suggestion for every detected "
        f"error. Only {fraction:.1%} of problem messages carry one. "
        f"Missing an action: {missing}"
    )


def test_no_action_gaps():
    """A message where we could not name a safe next step is a gap we must see."""
    gaps = CHECKLIST["action_gaps"]
    assert not gaps, (
        f"These messages have no safe next action and fell back to a placeholder: {gaps}. "
        f"Either write a real action or, if none exists, decide deliberately to ship the "
        f"gap and record why here."
    )


def test_unregistered_codes_are_flagged_not_hidden():
    """An unknown code must produce a visible gap, never silent or empty text."""
    message = plain.message_for("SOME_FUTURE_CODE", "a machine message", plain.Context())
    assert message.action.strip(), "even the fallback must give the reader somewhere to go"
    assert message.action_gap is True, "an unknown code must be recorded as a gap"
    assert message.detail == "a machine message", "the machine message must survive verbatim"


def test_a_problem_message_cannot_be_constructed_without_an_action():
    """The obligation is enforced at construction, not only in this test file."""
    with pytest.raises(ValueError):
        plain.PlainMessage(headline="x", body="y", action="", code="C", detail="d",
                           kind="problem")


# =====================================================================================
# coverage: every code the system can emit has plain wording
# =====================================================================================


def test_every_abstention_trigger_resolves_to_a_registered_code():
    """Nothing in the abstention policy may reach a renter without plain wording."""
    unmapped = []
    for trigger in POLICY:
        code = plain.code_for_trigger(trigger.name)
        if code not in plain.REGISTRY:
            unmapped.append((trigger.name, code))
    assert not unmapped, (
        f"These abstention triggers have no plain wording: {unmapped}. "
        f"Add them to api/plain.py REGISTRY."
    )


def test_every_readiness_reason_code_has_plain_wording():
    """Codes from logic/readiness.py, plus the ones it builds inline."""
    codes = set(PACK_CODE_BY_TRIGGER.values()) | set(GENERIC_CODE_BY_TRIGGER.values())
    codes |= {"EMPLOYMENT_LETTER_EXPIRED", "PERSON_NAME_MISMATCH",
              "INCOME_NOT_COMPUTABLE", "NO_FROZEN_THRESHOLD"}
    missing = sorted(codes - set(plain.REGISTRY))
    assert not missing, f"no plain wording for reason codes: {missing}"


def test_every_situation_route_has_plain_wording():
    """Every situation api/situations.py can return, plus the two ask.py refusals."""
    kinds = {route.kind for route in situations.ROUTES}
    kinds |= {"cross_applicant_refused", "embedded_instruction_ignored"}
    missing = sorted(kinds - set(plain.SITUATION_MESSAGES))
    assert not missing, f"no plain wording for situation kinds: {missing}"


# =====================================================================================
# the rules checklist (FPLG), measured
# =====================================================================================


def test_no_raw_identifiers_in_renter_facing_text():
    """FPLG III.a.3. `gross_pay` and `PAY_STUB_TOTAL_CONFLICT` are for the record, not the reader."""
    hits = CHECKLIST["raw_identifier_hits"]
    assert not hits, (
        f"raw identifiers leaked into text a renter reads "
        f"({CHECKLIST['free_of_raw_identifiers']:.1%} clean): {hits}"
    )


def test_no_household_ids_in_renter_facing_text():
    """A household id in renter-facing text is a cross-household leak in the harness."""
    leaks = CHECKLIST["household_id_leaks"]
    assert not leaks, f"household ids leaked into renter-facing text: {leaks}"


def test_second_person_is_measured_and_has_not_collapsed():
    """FPLG p.30. Reported, with a loose floor -- not a certification."""
    per_string = CHECKLIST["uses_second_person"]
    per_message = CHECKLIST["messages_using_second_person"]
    assert per_string >= SECOND_PERSON_FLOOR, (
        f"second person fell to {per_string:.1%} of renter-facing strings "
        f"(floor {SECOND_PERSON_FLOOR:.0%}). "
        f"Strings with no 'you': {CHECKLIST['strings_without_second_person']}"
    )
    assert per_message == 1.0, (
        f"every message should address the reader somewhere in its own text; "
        f"these do not: {CHECKLIST['messages_without_second_person']}"
    )


def test_active_voice_is_measured_and_has_not_collapsed():
    """FPLG p.20. A heuristic with documented blind spots -- see PASSIVE in api/plain.py."""
    active = CHECKLIST["active_voice_best_effort"]
    assert active >= ACTIVE_VOICE_FLOOR, (
        f"active-voice heuristic fell to {active:.1%} of sentences "
        f"(floor {ACTIVE_VOICE_FLOOR:.0%}). Candidates flagged as passive: "
        f"{CHECKLIST['passive_candidates']}"
    )


# =====================================================================================
# meaning survives the rewrite
# =====================================================================================


def test_the_machine_message_survives_verbatim():
    """The plain text is added alongside the precise text. It never replaces it."""
    original = ("the pay stubs report different gross totals; the recurring base is taken "
                "from the stub that reconciles with its own hours and rate")
    message = plain.message_for("PAY_STUB_TOTAL_CONFLICT", original, plain.Context())
    assert message.detail == original, "the audit trail must not be paraphrased"
    assert message.code == "PAY_STUB_TOTAL_CONFLICT", "the machine code must stay retrievable"
    assert message.code not in message.headline + message.body + message.action, \
        "the machine code must never be the text a renter reads"


def test_readiness_status_never_implies_a_determination():
    """READY_TO_REVIEW means a person can start. It must not read as anything else."""
    ready = plain.STATUS_MESSAGES["READY_TO_REVIEW"]
    text = " ".join(ready.renter_text).lower()
    for forbidden in ("you are eligible", "you qualify", "approved", "you will get",
                      "you have been accepted"):
        assert forbidden not in text, f"the ready status implies a determination: {forbidden!r}"
    assert ready.precision_note, "this is exactly the message that needs its note kept"
    assert "READY_TO_REVIEW" in ready.detail, "the exact status term must stay retrievable"


def test_messages_that_risked_a_meaning_change_carry_a_note():
    """Where plain phrasing could have changed what is true, we recorded the decision."""
    for code in ("PAY_STUB_TOTAL_CONFLICT", "RENTER_CORRECTION_NOT_USED",
                 "GIG_INCOME_UNCORROBORATED", "NO_FROZEN_THRESHOLD"):
        assert plain.REGISTRY[code].precision_note, (
            f"{code} was rewritten in a way that risked softening the meaning; "
            f"record what was kept and why in its precision_note"
        )


# =====================================================================================
# the live pipeline
# =====================================================================================


def _live_reports():
    from api.store import STORE
    from logic.household import households_from_views

    STORE.warm()
    session = STORE.new_session()
    houses = households_from_views(list(session.views.values()))
    return [STORE.report(session, hid) for hid in sorted(houses)]


@pytest.mark.parametrize("report", _live_reports(),
                         ids=lambda r: r.get("household_id", "?"))
def test_live_report_renders_plain_text_with_actions(report):
    """Every message a real household produces is renter-ready."""
    section = plain.for_report(report)
    assert "status" in section, "every report needs a plain status headline"
    for message in section["messages"]:
        assert message["headline"].strip(), f"{message['code']}: no headline"
        assert message["action"].strip(), (
            f"{message['code']}: no action. WCAG 2.2 SC 3.3.3 requires one."
        )
        assert not plain.RAW_IDENTIFIER.search(
            message["headline"] + message["body"] + message["action"]), \
            f"{message['code']}: raw identifier in renter-facing text"
        assert not plain.HOUSEHOLD_ID.search(
            message["headline"] + message["body"] + message["action"]), \
            f"{message['code']}: household id in renter-facing text"


@pytest.mark.parametrize("report", _live_reports(),
                         ids=lambda r: r.get("household_id", "?"))
def test_live_plain_output_carries_no_banned_key(report):
    """api/gate.py withholds a whole response over one banned key. Ours must be clean."""
    problems = scan(plain.for_report(report))
    assert not problems, "; ".join(problems)


def test_every_review_reason_reaches_the_renter():
    """No reason may be silently dropped on the way to the screen."""
    for report in _live_reports():
        codes = {r["code"] for r in report["review_reasons"]}
        shown = {m["code"] for m in plain.for_report(report)["messages"]}
        assert codes == shown, (
            f"{report['household_id']}: reasons {sorted(codes - shown)} never reached the "
            f"renter, and {sorted(shown - codes)} appeared from nowhere"
        )


def test_rendering_is_deterministic():
    """No model call, no clock, no randomness. The same report renders identically."""
    for report in _live_reports():
        first = json.dumps(plain.for_report(report), sort_keys=True)
        second = json.dumps(plain.for_report(report), sort_keys=True)
        assert first == second


# =====================================================================================
# readability: reported, never asserted
# =====================================================================================


def test_readability_is_reported_for_every_screen_long_enough_to_measure():
    """No grade threshold is asserted. We check only that we measured and disclosed."""
    if READABILITY.get("status") == "not_run":
        pytest.skip(f"readability not measured: {READABILITY.get('reason')}")
    for screen in READABILITY["screens"]:
        assert screen["words"] >= plain.MIN_SAMPLE_WORDS
        assert "flesch_kincaid_grade" in screen and "smog_grade" in screen, \
            "both formulas must be reported; a single grade is not defensible"
        assert "spread_between_the_two" in screen, "the disagreement is the finding"
        if screen["sentences"] < 30:
            assert screen["smog_is_extrapolated"] is True, \
                "SMOG below 30 sentences must be marked as extrapolated"


# =====================================================================================
# the report
# =====================================================================================


def report_text() -> str:
    lines = ["", "=" * 78, "PLAIN LANGUAGE COMPLIANCE - measured, not asserted", "=" * 78]
    c = CHECKLIST

    def pct(value):
        return "n/a" if value is None else f"{value:.1%}"

    lines += [
        "",
        f"messages checked ............................. {c['messages']}",
        f"renter-facing strings ........................ {c['renter_facing_strings']}",
        f"sentences .................................... {c['sentences']}",
        "",
        "RULES CHECKLIST (the primary artifact)",
        f"  free of raw identifiers .................... {pct(c['free_of_raw_identifiers'])}",
        f"  uses second person (per string) ............ {pct(c['uses_second_person'])}",
        f"  uses second person (per message) ........... {pct(c['messages_using_second_person'])}",
        f"  active voice (heuristic, see limits) ....... {pct(c['active_voice_best_effort'])}",
        f"  problem messages carrying an action ........ "
        f"{pct(c['problem_messages_with_an_action_fraction'])}  <-- REQUIRED (WCAG 3.3.3 AA)",
        "",
        f"  action gaps ................................ {c['action_gaps'] or 'none'}",
        f"  actions needing a trained person ........... "
        f"{c['actions_needing_a_trained_person'] or 'none'}",
        f"  household id leaks ......................... {c['household_id_leaks'] or 'none'}",
    ]

    if c["strings_without_second_person"]:
        lines += ["", "  strings with no second person:"]
        lines += [f"    {h['code']}.{h['field']}" for h in c["strings_without_second_person"]]
    if c["passive_candidates"]:
        lines += ["", "  sentences the passive heuristic flagged (may be false positives):"]
        lines += [f"    {s}" for s in c["passive_candidates"]]

    lines += ["", "READABILITY (reported, never asserted)"]
    if READABILITY.get("status") == "not_run":
        lines += [f"  not_run: {READABILITY.get('reason')}"]
    else:
        lines += ["  screen                     words  sents   F-K   SMOG  spread",
                  "  " + "-" * 60]
        for s in READABILITY["screens"]:
            flag = " (SMOG extrapolated)" if s["smog_is_extrapolated"] else ""
            lines.append(
                f"  {s['screen']:<26}{s['words']:>5}{s['sentences']:>7}"
                f"{s['flesch_kincaid_grade']:>7}{s['smog_grade']:>7}"
                f"{s['spread_between_the_two']:>8}{flag}"
            )
        lines += [f"  widest spread between the two formulas: {READABILITY['widest_spread']}"]
        for skipped in READABILITY["screens_too_short_to_measure"]:
            lines.append(f"  skipped {skipped['screen']}: {skipped['words']} words "
                         f"(under {plain.MIN_SAMPLE_WORDS})")

    lines += [
        "",
        "Only the action fraction is a pass/fail gate. WCAG 2.2 SC 3.1.5 Reading Level is",
        "Level AAA and is not required at AA; the Federal Plain Language Guidelines are a",
        "voluntarily adopted benchmark with no reading-grade target and no sentence-length",
        "rule. Nothing here should be read as a claim that AA obliges either.",
        "=" * 78,
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    # Windows consoles default to a codepage that cannot encode the dashes and quotes our
    # own message text contains. Fall back rather than crash on the report.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(report_text())
