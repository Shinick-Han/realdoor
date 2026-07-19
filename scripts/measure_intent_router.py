# -*- coding: utf-8 -*-
"""
measure_intent_router.py -- what does the LLM intent classifier actually buy?

WHY THIS FILE EXISTS
--------------------
Every other claim in this submission has a number under it. The one AI component did not.
`api/route_llm.py` ships an `anchor_audit()` that returns `ok: True`, but that audit only
proves the wiring is self-consistent -- that each anchor phrase round-trips to its own
intent through the deterministic router. It says nothing about whether the classifier
routes a question the deterministic layer could not route, and nothing about what it does
when it routes one WRONG.

There is also a second, quieter problem. `logic/answer_rules.py ROUTES` was written against
the 36 phrasings in `pack/evaluation/qa_gold.jsonl`, and `api/ask.py _ALIASES` was written
by hand on top of it. The pack scores 36/36. That number was never in doubt: the exam and
the answer key were written in the same week by the same people. The pack rubric warns that
"Hidden tests may perturb names and values while retaining the schemas" -- and nobody had
measured how far the deterministic router bends when the WORDS move.

WHAT IS BEING MEASURED
----------------------
Two suites x two configurations:

                          deterministic only     deterministic + classifier
  pack qa_gold (36)               ?                          ?
  phrasing hold-out (44)          ?                          ?

Three buckets per cell, never merged: correct / abstained / wrong.

The wrong bucket is the one that matters. An abstention is the system saying "a housing
professional answers this" -- disappointing, safe, already the documented behaviour. A
wrong answer is the system handing a renter the output of a DIFFERENT rule while sounding
exactly as confident as it does when it is right. If the classifier converts abstentions
into answers, it is worth something. If it converts abstentions into wrong answers, it is
worth less than nothing, because the deterministic silence it replaced was honest.

HOW A VERDICT IS DECIDED
------------------------
Grading is by INTENT, not by string equality, and the reason is that string equality would
score the safe failure and the dangerous failure identically. A renter who asks "am i under
or over" and is handed the readiness status has been given a confident, cited, wrong-topic
answer; a renter who is handed nothing has been given an abstention. Those are different
events and this script counts them differently.

  correct    the response carries the intent the question was asking, and (where the intent
             yields a value) that value equals what the deterministic system produces for
             the same session household on the pack's own phrasing of the same question.
  abstained  the response is an abstention, an unrouted silence, or a safety refusal. No
             claim was made.
  wrong      a non-abstained answer belonging to a different intent, or the right intent
             carrying a value that does not match. This is the bucket to read first.

Gold is not hand-written here. For each hold-out line, gold is whatever the deterministic
system answers for the PACK's phrasing of that same question with the same session
household -- and that path is the one already verified 36/36. So the hold-out asks exactly
one question: does the wording change the answer?

RUN
    python scripts/measure_intent_router.py
    python scripts/measure_intent_router.py --json scripts/intent_router_measurement.json

Needs OPENAI_API_KEY for the classifier column. Without it the script measures the
deterministic column, reports the other as unmeasured, and does not pretend otherwise.
Nothing here writes to any file outside `scripts/`, and nothing here imports a module it
also modifies -- this is a measurement, not a fix.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RAW = Path(__file__).resolve().parent / "holdout_phrasing_raw.txt"

# ─────────────────────────────────────────────────────── intent bookkeeping

#: hold-out intent letter -> the pack question index within a household block (0-4), or the
#: qa_id of the standalone pack question it paraphrases.
INTENT_TO_PACK: dict[str, Any] = {
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4,
    "F": "QA-031", "G": "QA-032", "H": "QA-033",
    "I": "QA-034", "J": "QA-035", "K": "QA-036",
}

#: hold-out intent letter -> the response `kind`s that count as having understood it.
#:
#: Several letters accept more than one kind, and each case is a real equivalence rather
#: than a loosened grader. "E" is answered correctly by `decision_boundary` (the rule
#: sentence) or by `eligibility_refused` (the situation router's version of the same
#: refusal) -- `api/ask.py` deliberately routes first-person eligibility questions to the
#: latter so the two paths say the same words. "I" is answered by `embedded_instructions`
#: (the rule about document text) or by `embedded_instruction_ignored` (the live refusal
#: emitted when the question itself trips the injection guard); both tell the renter that
#: document text is not obeyed.
ACCEPTED_KINDS: dict[str, set[str]] = {
    "A": {"frozen_threshold"},
    "B": {"annualized_income"},
    "C": {"threshold_comparison"},
    "D": {"readiness_status"},
    "E": {"decision_boundary", "eligibility_refused"},
    "F": {"limits_effective_date"},
    "G": {"vacancy_claim"},
    "H": {"geocode_precision"},
    "I": {"embedded_instructions", "embedded_instruction_ignored"},
    "J": {"currency_rule_status"},
    "K": {"statutory_anchor"},
}

#: Kinds that are a refusal or an abstention rather than an answer. None of these hands the
#: renter a claim, so none of them can be a wrong answer.
ABSTAINING_KINDS = {"unrouted", "cross_applicant_refused"}

#: Session household for hold-out lines that name none. A renter mid-session has a file
#: open; the API takes `household_id` from that session, not from the sentence. Assigned
#: here so the assignment is auditable rather than buried in a loop: sizes are 1-6 for
#: HH-001..HH-006, so the line that says "theres 4 of us now" gets the size-4 file and the
#: narrative and the gold answer agree. The rest are spread so no single household carries
#: the result.
UNNAMED_SESSION: dict[tuple[str, int], str] = {
    ("A", 1): "HH-001", ("A", 3): "HH-004",   # "4 of us now" -> the size-4 file
    ("B", 1): "HH-002", ("B", 3): "HH-005",
    ("C", 1): "HH-003", ("C", 3): "HH-006",
    ("D", 1): "HH-001", ("D", 3): "HH-004",
    ("E", 1): "HH-002", ("E", 3): "HH-005",
}

#: Standalone intents F-K are not about a household; they run with no session file.
STANDALONE = set("FGHIJK")


@dataclass(frozen=True)
class HoldoutLine:
    intent: str
    session: str | None
    text: str
    ordinal: int          # index of this line within its intent (0-3)

    @property
    def label(self) -> str:
        return f"{self.intent}{self.ordinal + 1}"


def load_holdout() -> list[HoldoutLine]:
    lines: list[HoldoutLine] = []
    seen: dict[str, int] = {}
    for raw in RAW.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("/"):
            continue
        intent, household, text = raw.split("|", 2)
        ordinal = seen.get(intent, 0)
        seen[intent] = ordinal + 1
        if household == "-":
            session = None if intent in STANDALONE else UNNAMED_SESSION[(intent, ordinal)]
        else:
            session = household
        lines.append(HoldoutLine(intent, session, text, ordinal))
    return lines


# ───────────────────────────────────────────────────────────────── grading

@dataclass
class Cell:
    correct: int = 0
    abstained: int = 0
    wrong: int = 0
    rows: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.correct + self.abstained + self.wrong

    def line(self) -> str:
        return (f"{self.correct:>3} correct / {self.abstained:>3} abstained / "
                f"{self.wrong:>3} wrong   (n={self.total})")

    def to_dict(self) -> dict[str, Any]:
        return {"correct": self.correct, "abstained": self.abstained,
                "wrong": self.wrong, "total": self.total, "rows": self.rows}


def grade(intent: str, response: dict[str, Any], gold_text: str | None) -> tuple[str, str]:
    """(verdict, why). See the module docstring for what each verdict means."""
    from logic.answer_rules import equivalent

    kind = str(response.get("kind") or "")
    text = response.get("answer")

    if response.get("abstained") or kind in ABSTAINING_KINDS or not text:
        return "abstained", f"abstained (kind={kind or 'none'})"

    if kind not in ACCEPTED_KINDS[intent]:
        return "wrong", f"answered a different intent: {kind}"

    # Right intent. For the refusal intents the sentence IS the answer and there is no
    # value to check; for the rest, the value has to match what the pack phrasing yields.
    if gold_text is None or kind in ("eligibility_refused", "embedded_instruction_ignored"):
        return "correct", f"kind={kind}"

    ok, tier = equivalent(str(text), gold_text)
    if ok:
        return "correct", f"kind={kind}, match={tier}"
    return "wrong", f"kind={kind} but value differs ({tier}): {text!r} vs {gold_text!r}"


# ─────────────────────────────────────────────────────────────── the runs

def pack_records() -> list[dict[str, Any]]:
    from logic.answer_rules import load_qa_gold
    return load_qa_gold()


def gold_for(line: HoldoutLine, records: list[dict[str, Any]],
             households: dict[str, Any], checklists: dict[str, Any]) -> str | None:
    """What the deterministic system answers for the PACK phrasing of this same question.

    Not a hand-written key. The pack phrasing routes through the verified path, so if the
    hold-out line disagrees with this, the disagreement is caused by the wording and by
    nothing else.
    """
    from logic.answer_rules import answer as answer_rule

    target = INTENT_TO_PACK[line.intent]
    if isinstance(target, str):
        record = next(r for r in records if r["qa_id"] == target)
        return record["answer"]

    assert line.session is not None
    index = int(line.session.split("-")[1]) - 1
    record = records[index * 5 + target]
    result = answer_rule(record["question"], record.get("household_id"),
                         households=households, checklists=checklists)
    return result.text


def run_suite(lines: list[HoldoutLine], households: dict[str, Any]) -> Cell:
    from api import ask

    records = pack_records()
    from logic.household import load_pack_checklists
    checklists = load_pack_checklists()

    cell = Cell()
    for line in lines:
        response = ask.handle(line.text, line.session, households)
        gold = gold_for(line, records, households, checklists)
        verdict, why = grade(line.intent, response, gold)
        setattr(cell, verdict, getattr(cell, verdict) + 1)
        cell.rows.append({
            "id": line.label, "intent": line.intent, "session": line.session,
            "question": line.text, "kind": response.get("kind"),
            "answer": response.get("answer"), "gold": gold,
            "verdict": verdict, "why": why,
        })
    return cell


def run_pack(households: dict[str, Any]) -> Cell:
    """The pack's own 36, through the same serving path (`api.ask.handle`).

    Deliberately not `score_against_gold()`. That function calls `answer_rules.answer()`
    directly and so never touches the aliases, the situation router or the classifier --
    it cannot show what the classifier does to the pack, which is half of the question.
    Routing the pack through `handle` puts both columns on the same path.
    """
    from api import ask

    letters = "ABCDE"
    cell = Cell()
    for record in pack_records():
        qa_id = record["qa_id"]
        number = int(qa_id.split("-")[1])
        if number <= 30:
            intent = letters[(number - 1) % 5]
        else:
            intent = {31: "F", 32: "G", 33: "H", 34: "I", 35: "J", 36: "K"}[number]
        response = ask.handle(record["question"], record.get("household_id"), households)
        verdict, why = grade(intent, response, record["answer"])
        setattr(cell, verdict, getattr(cell, verdict) + 1)
        cell.rows.append({
            "id": qa_id, "intent": intent, "session": record.get("household_id"),
            "question": record["question"], "kind": response.get("kind"),
            "answer": response.get("answer"), "gold": record["answer"],
            "verdict": verdict, "why": why,
        })
    return cell


def diagnose(lines: list[HoldoutLine], households: dict[str, Any]) -> list[dict[str, Any]]:
    """For every hold-out line, ask the classifier directly and record its raw label.

    This is the part that cannot be read off the 2x2. The table shows the outcome; this
    shows WHY -- specifically, whether the model named the wrong intent and the anchor
    round-trip caught it, or named the wrong intent and the round-trip agreed. The second
    case is the failure the audit was never able to see, because `anchor_audit()` only ever
    asks whether an anchor reaches its own intent from a placeholder question. It never
    asks whether an anchor can drag a REAL question somewhere the renter did not point.
    """
    from api import route_llm
    from logic.answer_rules import route as canonical_route

    out: list[dict[str, Any]] = []
    for line in lines:
        deterministic = canonical_route(line.text)
        label = None
        confirmed = None
        error = None
        try:
            label = route_llm.classify(line.text)
            if label is not None:
                resolution = route_llm.confirm(line.text, label, count=False)
                confirmed = resolution.intent if resolution else None
        except Exception as exc:  # pragma: no cover - network shape varies
            error = f"{type(exc).__name__}: {exc}"
        expected = ACCEPTED_KINDS[line.intent]
        out.append({
            "id": line.label, "question": line.text,
            "deterministic_route": deterministic,
            "model_label": label,
            "confirmed_intent": confirmed,
            "expected_kinds": sorted(expected),
            "model_named_wrong_intent": bool(label) and label not in expected,
            "anchor_let_it_through": bool(confirmed) and confirmed not in expected,
            "error": error,
        })
    return out


# ───────────────────────────────────────────────────────────── two probes
#
# The 2x2 says WHAT happened. These two say why, and both were prompted by a row in it.

def probe_anchor_filter() -> dict[str, Any]:
    """How much does the anchor round-trip actually reject?

    `confirm()` is the safety argument of the whole component: the model may only nominate,
    and a nomination counts only if the deterministic router independently agrees. The way
    it asks for agreement is to append the intent's anchor phrase to the question and
    re-route the result. But the anchor phrase is, by construction, the exact string that
    triggers that route -- `anchor_audit()` asserts precisely that, and a test enforces it.
    So the re-route is being asked a question whose answer was appended to it.

    This probe measures the consequence directly: every hold-out question crossed with every
    intent, including pairings that are obvious nonsense. A filter doing real work rejects
    most of those. Whatever number comes back is the strength of the check that the rest of
    the component's safety story rests on.
    """
    from api import route_llm
    from logic.answer_rules import ROUTES as CANONICAL

    questions = [line.text for line in load_holdout()]
    canonical = {r.kind for r in CANONICAL}

    # Intent names are carried as VALUES, never as object keys. `eval/test_no_decision.py`
    # scans every data file in the repo for response keys containing determination words,
    # and `eligibility_refused` as a key trips it. The intent it names is a refusal, so the
    # hit is a false positive -- but the scanner is right to be blunt, and the way to keep
    # it blunt is to not hand it a shape it has to make exceptions for.
    per_intent = [
        {
            "intent": intent,
            "rejected": sum(1 for q in questions
                            if route_llm.confirm(q, intent, count=False) is None),
            "of": len(questions),
            "canonical": intent in canonical,
        }
        for intent in route_llm.known_intents()
    ]
    canon_rows = [r for r in per_intent if r["canonical"]]
    return {
        "note": "every hold-out question x every intent, including nonsense pairings",
        "pairs_tested": len(questions) * len(per_intent),
        "canonical_pairs": sum(r["of"] for r in canon_rows),
        "canonical_rejected": sum(r["rejected"] for r in canon_rows),
        "per_intent": per_intent,
    }


def probe_latent_wrong() -> dict[str, Any]:
    """Standalone questions re-run with a household file open.

    The F-K hold-out lines are not about a household, so the suite runs them with no
    session -- which is how a renter browsing the rules would ask them. But a renter with a
    file open asks the same questions, and a wrong route that abstains for want of a
    household stops abstaining the moment one is present. An abstention that is only an
    abstention because a field happened to be empty is not a refusal; it is a wrong answer
    waiting for a session. This probe opens one and looks.
    """
    from api import ask
    from logic.household import load_gold_households

    households = load_gold_households()
    found = []
    for line in load_holdout():
        if line.intent not in STANDALONE:
            continue
        for session in ("HH-001", "HH-003"):
            response = ask.handle(line.text, session, households)
            kind = str(response.get("kind") or "")
            if response.get("abstained") or not response.get("answer"):
                continue
            if kind in ACCEPTED_KINDS[line.intent]:
                continue
            found.append({"id": line.label, "session": session,
                          "question": line.text, "kind": kind,
                          "answer": response.get("answer")})
    return {"note": "abstentions that stop abstaining once a session household exists",
            "count": len(found), "rows": found}


# ───────────────────────────────────────────────────────────────── driver

def measure(with_classifier: bool) -> dict[str, Any]:
    """One column of the table. Re-imports so the env flag is read fresh."""
    os.environ["REALDOOR_LLM_ROUTER"] = "1" if with_classifier else "0"
    for name in [m for m in list(sys.modules) if m.startswith(("api", "logic"))]:
        del sys.modules[name]

    from api import route_llm
    from logic.household import load_gold_households

    route_llm.reset_stats()
    households = load_gold_households()
    lines = load_holdout()

    result = {
        "classifier_enabled": route_llm.is_enabled(),
        "pack": run_pack(households).to_dict(),
        "holdout": run_suite(lines, households).to_dict(),
        "router_stats": route_llm.stats(),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the full per-question record here")
    args = parser.parse_args()

    have_key = bool(os.environ.get("OPENAI_API_KEY"))

    print("=" * 78)
    print("what the intent classifier actually buys")
    print("=" * 78)

    off = measure(with_classifier=False)
    report: dict[str, Any] = {"deterministic_only": off, "api_key_present": have_key}

    if have_key:
        on = measure(with_classifier=True)
        report["with_classifier"] = on
        if not on["classifier_enabled"]:
            print("\n!! REALDOOR_LLM_ROUTER=1 set but route_llm.is_enabled() is False.")
    else:
        on = None
        print("\n!! OPENAI_API_KEY is not set. The classifier column is UNMEASURED.")
        print("   Not estimated, not inferred -- absent. Re-run with a key.")

    def cell(column: dict[str, Any] | None, suite: str) -> str:
        if column is None:
            return "unmeasured (no API key)"
        return Cell(**{k: v for k, v in column[suite].items()
                       if k in ("correct", "abstained", "wrong", "rows")}).line()

    print(f"\n{'':<24}{'deterministic only':<40}{'+ classifier'}")
    for suite, name in (("pack", "pack qa_gold (36)"), ("holdout", "phrasing hold-out (44)")):
        print(f"{name:<24}{cell(off, suite):<40}{cell(on, suite)}")

    # The bucket that decides whether this component is worth shipping.
    for column, name in ((off, "deterministic only"), (on, "+ classifier")):
        if column is None:
            continue
        for suite in ("pack", "holdout"):
            bad = [r for r in column[suite]["rows"] if r["verdict"] == "wrong"]
            if not bad:
                continue
            print(f"\n--- WRONG ANSWERS: {name}, {suite} ({len(bad)}) ---")
            for row in bad:
                print(f"  [{row['id']}] {row['question']}")
                print(f"      -> {row['why']}")

    if on is not None:
        print("\n--- classifier call stats (hold-out + pack, classifier column) ---")
        stats = on["router_stats"]
        for key in ("attempts", "calls", "cache_hits", "returned_unknown",
                    "rejected_unknown_label", "rejected_no_anchor",
                    "rejected_router_disagreed", "accepted", "timeouts", "errors",
                    "offline_or_uncached"):
            print(f"  {key:<28}{stats.get(key)}")

        os.environ["REALDOOR_LLM_ROUTER"] = "1"
        for module in [m for m in list(sys.modules) if m.startswith(("api", "logic"))]:
            del sys.modules[module]
        from logic.household import load_gold_households
        rows = diagnose(load_holdout(), load_gold_households())
        report["diagnosis"] = rows

        slipped = [r for r in rows if r["anchor_let_it_through"]]
        misnamed = [r for r in rows if r["model_named_wrong_intent"]]
        print(f"\n--- classifier named a wrong intent: {len(misnamed)} ---")
        for row in misnamed:
            caught = "CAUGHT by anchor round-trip" if not row["anchor_let_it_through"] \
                else "!! NOT CAUGHT -- flowed through as " + str(row["confirmed_intent"])
            print(f"  [{row['id']}] {row['question']}")
            print(f"      model said {row['model_label']!r}, expected one of "
                  f"{row['expected_kinds']} -- {caught}")
        print(f"\n--- wrong intents the anchor round-trip did NOT catch: {len(slipped)} ---")
        if not slipped:
            print("  none")
        for row in slipped:
            print(f"  [{row['id']}] {row['question']}")
            print(f"      model said {row['model_label']!r} -> confirmed as "
                  f"{row['confirmed_intent']!r}, expected {row['expected_kinds']}")

        report["anchor_filter_strength"] = probe_anchor_filter()
        report["latent_wrong_with_session"] = probe_latent_wrong()

        print("\n--- anchor_audit() for reference ---")
        from api import route_llm
        print(" ", json.dumps(route_llm.anchor_audit(), ensure_ascii=False))

        strength = report["anchor_filter_strength"]
        print("\n--- how much does the anchor round-trip reject? ---")
        print(f"  canonical intents: rejected {strength['canonical_rejected']} of "
              f"{strength['canonical_pairs']} question x intent pairs")
        print("  (a pairing like 'so am i approved' x geocode_precision is nonsense; "
              "a filter doing work rejects it)")

        latent = report["latent_wrong_with_session"]
        print(f"\n--- abstentions that become answers once a session is open: "
              f"{latent['count']} ---")
        for row in latent["rows"]:
            print(f"  [{row['id']}] {row['question']}  (session {row['session']})")
            print(f"      -> {row['kind']}: {row['answer'][:90]!r}")

    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                             encoding="utf-8")
        print(f"\nfull per-question record: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
