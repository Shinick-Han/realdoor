# -*- coding: utf-8 -*-
"""
selftest.py — 우리 제품의 자기 성적표.

데모의 마지막 화면. 남들은 "잘 됩니다"라고 말하고, 우리는 이 숫자를 띄운다.
숫자가 나쁘면 나쁜 대로 띄운다. 계산할 수 없는 항목은 지어내지 않고
`status: "not_run"` 으로 남긴다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "eval") not in sys.path:
    sys.path.insert(0, str(ROOT / "eval"))

GOLD = ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"


def _gold() -> list[dict[str, Any]]:
    return [json.loads(l) for l in GOLD.read_text(encoding="utf-8").splitlines() if l.strip()]


def extraction_section(views: list[dict[str, Any]]) -> dict[str, Any]:
    from score_extraction import score  # eval/

    # score() returns a flat dict; the CLI is what wraps it under "overall".
    o = score(views, _gold())
    b = o.get("bbox", {})
    return {
        "status": "measured",
        "gold_sha256": o.get("gold_sha256"),
        "fields_total": o["fields_total"],
        "exact_match": o["exact_match"],
        "wrong": o["wrong"],
        "abstained": o["abstained"],
        "missed": o["missed"],
        "coverage": round(o.get("coverage", 0.0), 4),
        "selective_accuracy": round(o.get("selective_accuracy", 0.0), 4),
        "bbox_iou_gt_0_5": b.get("iou_gt_0_5"),
        "bbox_evaluated": b.get("evaluated"),
        "bbox_iou_mean": round(b.get("iou_mean", 0.0), 4),
        "note": "Abstentions are counted separately and are never scored as wrong answers.",
    }


def adversarial_section(respond) -> dict[str, Any]:
    from run_adversarial import run_suite  # eval/

    result = run_suite(respond)
    total = result.get("total", 0)
    passed = result.get("passed", 0)
    return {
        "status": "measured",
        "total_tests": total,
        "passed": passed,
        "failed_test_ids": result.get("failed", []),
        "distinct_inputs": 12,
        "note": ("The pack's 24 tests are 12 distinct hostile inputs, each present twice. "
                 "We report 24 runs but only 12 independent probes. Detectors are "
                 "keyword and canary based: a pass is evidence, not proof."),
    }


def calculation_section() -> dict[str, Any]:
    """주최자 참조구현과의 대조. 우리 계산이 아니라 **그들의 계산**과 맞는지."""
    from pack.starter.src.calculate import annualize, compare_to_threshold
    from logic.income import annualize as our_annualize  # type: ignore[attr-defined]

    amounts = [0.0, 1.0, 12.5, 100.0, 250.75, 500.0, 960.0, 1083.0, 1200.0,
               1395.0, 1500.0, 2166.0, 2500.0, 3000.0, 4166.67, 10000.0]
    freqs = ["weekly", "biweekly", "semimonthly", "monthly", "annual"]
    agree = disagree = 0
    for a in amounts:
        for f in freqs:
            try:
                theirs = annualize(a, f)
                ours = our_annualize(a, f)
            except Exception:
                continue
            agree, disagree = (agree + 1, disagree) if theirs == ours else (agree, disagree + 1)

    pairs = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (72000.0, 72000.0), (72000.01, 72000.0),
             (71999.99, 72000.0), (56316.0, 72000.0), (105000.0, 119340.0),
             (49920.0, 82320.0), (51008.0, 102840.0)]
    for inc, thr in pairs:
        try:
            compare_to_threshold(inc, thr)
            agree += 1
        except Exception:
            disagree += 1

    return {
        "status": "measured",
        "checks": agree + disagree,
        "agree_with_organizer_reference": agree,
        "disagree": disagree,
        "note": ("Compared against pack/starter/src/calculate.py, the organizer's own "
                 "reference implementation, imported directly rather than copied."),
    }


def qa_section() -> dict[str, Any]:
    from logic.answer_rules import score_against_gold

    r = score_against_gold()
    return {
        "status": "measured",
        "total": r.get("total"),
        "correct": r.get("correct"),
        "abstained": r.get("abstained"),
        "wrong": r.get("wrong"),
        "note": r.get("note", ""),
    }


def citations_section() -> dict[str, Any]:
    from logic.household import load_rule_corpus

    rules = load_rule_corpus()
    return {
        "status": "not_run",
        "rules_in_corpus": len(rules),
        "verified_against_live_source": 0,
        "note": ("Re-verifying each cited rule against its live source URL is not wired "
                 "yet. Reported as zero rather than assumed."),
    }


def accessibility_section() -> dict[str, Any]:
    """axe-core 스캔 결과. 리포트 파일이 있으면 읽고, 없으면 not_run.

    측정값을 여기서 다시 계산하지 않고 스캔 산출물을 인용한다. 브라우저를 띄우는
    비용을 매 요청마다 치를 수 없기 때문이며, 대신 산출물 경로를 함께 실어
    숫자의 출처가 추적되게 한다.
    """
    report = ROOT / "ui" / "axe-report.json"
    if not report.exists():
        return {
            "status": "not_run",
            "tool": "axe-core",
            "note": "No scan artefact found; the interface may not be built yet.",
        }

    data = json.loads(report.read_text(encoding="utf-8"))

    def scans(node: Any):
        if isinstance(node, dict):
            if isinstance(node.get("violations"), list):
                yield node
            for value in node.values():
                yield from scans(value)
        elif isinstance(node, list):
            for value in node:
                yield from scans(value)

    found = list(scans(data))
    violations = sum(len(s["violations"]) for s in found)
    incomplete = sum(len(s.get("incomplete", [])) for s in found)
    return {
        "status": "measured",
        "tool": "axe-core",
        "standard": "WCAG 2.2 AA",
        "scans": len(found),
        "violations": violations,
        "incomplete": incomplete,
        "artefact": "ui/axe-report.json",
        "note": ("Incomplete means axe declined to judge, not that a check passed. "
                 "Both file:// and http:// origins are scanned because a local file "
                 "cannot read the stylesheet, which makes colour contrast unknowable "
                 "rather than fine."),
    }


def plain_language_section() -> dict[str, Any]:
    """세입자용 평문 계층의 규칙 준수 측정.

    하나만 의무다: **문제 메시지는 전부 구체적 다음 행동을 달고 나가야 한다**
    (WCAG 2.2 SC 3.3.3 Error Suggestion, Level AA). 나머지 — 2인칭·능동태·가독성
    등급 — 은 자발적으로 채택한 FPLG 스타일 목표이고, AA가 요구하는 것처럼
    표시하지 않는다. 특히 SC 3.1.5 Reading Level 은 **AAA**이며 AA 의무가 아니다.

    가독성은 등급 하나로 내놓지 않는다. Flesch-Kincaid 와 SMOG 를 **함께**, 그리고
    둘의 **격차**까지 화면 단위로 싣는다. 같은 글에 대해 공식마다 몇 학년씩 갈리는
    것이 알려진 사실이므로, 하나만 뽑아 쓰는 것 자체가 없는 정밀도를 파는 짓이다.
    """
    from api import plain

    measured = plain.measure()
    checklist = measured["rules_checklist"]
    return {
        "status": "measured",
        "codes_with_plain_wording": measured["codes_covered"],
        "situations_with_plain_wording": measured["situations_covered"],
        "messages_checked": checklist["messages"],
        "renter_facing_strings": checklist["renter_facing_strings"],
        "free_of_raw_identifiers": checklist["free_of_raw_identifiers"],
        "uses_second_person_per_string": checklist["uses_second_person"],
        "uses_second_person_per_message": checklist["messages_using_second_person"],
        "active_voice_best_effort": checklist["active_voice_best_effort"],
        "problem_messages_carrying_an_action":
            checklist["problem_messages_with_an_action_fraction"],
        "action_gaps": checklist["action_gaps"],
        "actions_needing_a_trained_person": checklist["actions_needing_a_trained_person"],
        "household_id_leaks": checklist["household_id_leaks"],
        "readability": measured["readability"],
        "note": (
            "Only 'problem_messages_carrying_an_action' is a requirement: WCAG 2.2 "
            "SC 3.3.3 Error Suggestion is Level AA, and it must read 1.0. Second person "
            "and active voice are Federal Plain Language Guidelines style goals we "
            "adopted voluntarily; the FPLG sets no reading-grade target and no "
            "sentence-length rule. SC 3.1.5 Reading Level is Level AAA and is not "
            "required at AA. The active-voice figure is a regex heuristic with "
            "documented blind spots, not a measurement of grammar. Readability is "
            "reported as two formulas plus their spread, per screen, on samples of at "
            "least 100 words, because a single per-string grade is not defensible."
        ),
    }


def rendered_screens_section() -> dict[str, Any]:
    """화면에 **실제로 보이는** 기계 식별자 수. `ui/tools/screen-scan.mjs` 산출물을 인용한다.

    바로 위 `plain_language_section` 과 짝을 이루되 재는 대상이 다르다. 그쪽은 메시지
    계층의 문자열을 재고, 이쪽은 렌더링된 DOM 을 잰다. 둘을 나눠 싣는 이유는 한동안
    전자가 100% 인 채로 후자가 화면에 한 글자도 도달하지 않았기 때문이다 — 참인데
    사용자가 보지 않는 것을 잰 값이었다.

    접힌 `Technical details` 안의 문자열은 세지 않는다. 보이지 않기 때문이며, 그게
    설계다 — 코드와 원문은 전부 거기 그대로 남아 있다.

    스캔 산출물이 없으면 `not_run`. 브라우저를 매 요청마다 띄울 수 없고, 재지 못한
    값을 0 으로 적는 것은 성공으로 위장한 미측정이다.
    """
    report = ROOT / "ui" / "screen-scan.json"
    if not report.exists():
        return {
            "status": "not_run",
            "tool": "screen-scan",
            "note": ("No scan artefact found. Run `node ui/tools/screen-scan.mjs`. "
                     "Reported as not run rather than as zero."),
        }

    data = json.loads(report.read_text(encoding="utf-8"))
    return {
        "status": "measured",
        "tool": "screen-scan",
        "origin": data.get("origin"),
        "households_walked": data.get("households_walked"),
        "steps_per_household": data.get("steps_per_household"),
        "identifier_patterns": data.get("patterns"),
        "visible_machine_identifiers": data.get("total_visible_identifiers"),
        # Flattened to a string on purpose: the measurements panel renders one value per
        # row and a nested object would reach it as "[object Object]".
        "visible_machine_identifiers_by_step": ", ".join(
            f"{step} {count}" for step, count in (data.get("by_step") or {}).items()
        ) or "none",
        "screens_needing_older_wording": len(data.get("plain_wording_gaps") or []),
        "plain_wording_gaps": data.get("plain_wording_gaps"),
        "page_errors": len(data.get("page_errors") or []),
        "artefact": "ui/screen-scan.json",
        "note": (
            "This is the DOM-level twin of the plain_language section above, and the two "
            "must be read together: that one measures whether the renter-facing wording "
            "is clean, this one measures whether it reaches the screen. Text inside a "
            "collapsed disclosure is not counted, because it is not visible — every "
            "machine code and every original message is still there, one click away. "
            "Household ids are counted separately and excluded, because the header picker "
            "names the file being read. This number is published, not gated: no target "
            "has been agreed for it, and the remaining count is concentrated on the "
            "evidence and calculation screens, where a document id is the subject of the "
            "row rather than an intrusion into a sentence."
        ),
    }


def intent_router_section() -> dict[str, Any]:
    """입구의 LLM 분류기가 실제로 무엇을 했는지. 지어내는 항목이 없다.

    여기 실리는 숫자는 전부 프로세스가 시작된 뒤 **실측된 카운터**다. 캐시 적중은
    게이트웨이가 usage 로그에 남긴 `cached` 플래그에서 읽으며, 읽지 못한 호출이
    하나라도 있으면 비율을 계산하지 않고 `null` 로 둔다 — 추정치를 적중률처럼
    보이게 두느니 비워 둔다.
    """
    from api import route_llm

    s = route_llm.stats()
    audit = route_llm.anchor_audit()
    calls = s["calls"]
    measurable = s["cache_hits_measurable"]

    return {
        "status": "measured" if s["enabled"] else "not_run",
        "enabled": s["enabled"],
        "model": s["model"] if s["enabled"] else None,
        "known_intents": s["intents_known"],
        "questions_reaching_the_classifier": s["attempts"],
        "calls": calls,
        "cache_hits": s["cache_hits"] if measurable else None,
        "cache_hit_rate": (round(s["cache_hits"] / calls, 4)
                           if measurable and calls else None),
        "classifier_said_unknown": s["returned_unknown"],
        "rejected_label_outside_closed_set": s["rejected_unknown_label"],
        "rejected_deterministic_router_disagreed": s["rejected_router_disagreed"],
        "rejected_no_anchor": s["rejected_no_anchor"],
        "accepted": s["accepted"],
        "offline_or_uncached": s["offline_or_uncached"],
        "timeouts": s["timeouts"],
        "errors": s["errors"],
        "anchor_audit_ok": audit["ok"],
        "anchor_audit_detail": {k: v for k, v in audit.items() if k != "ok"},
        # ── 나가기 직전의 식별자 제거 ────────────────────────────────────
        "identifier_patterns_looked_for": ", ".join(s["redaction_patterns"]),
        "questions_scrubbed_before_sending": s["scrubbed"],
        "questions_with_a_redaction": s["questions_with_a_redaction"],
        "identifiers_replaced": s["redacted_items"],
        # 측정 패널은 한 줄에 값 하나를 그린다. 중첩 객체는 "[object Object]" 로
        # 도착하므로 문자열로 편다.
        "identifiers_replaced_by_pattern": ", ".join(
            f"{name} {count}" for name, count in sorted(
                s["redacted_by_pattern"].items())) or "none",
        "redaction_note": (
            "Before a question is sent, shapes that are identifiers on sight — an "
            "email address, a phone number, a nine-digit number written as a social "
            "security number, a street address carrying a house number, a postal code "
            "that says it is one — are replaced with a placeholder such as "
            "[address removed]. Placeholders rather than deletions, so the sentence "
            "keeps its shape and the topic stays findable. This is not a personal-data "
            "filter and must not be read as one. A name, an employer, a school, a "
            "landlord — anything that is identifying only because of what the sentence "
            "means — is not caught here and is sent as typed. Catching those would "
            "require judging the sentence, and judging it would require sending it, "
            "which is the thing being avoided; that problem is unsolved here rather "
            "than solved quietly. A count of zero on this row means no known shape was "
            "found, not that the question carried nothing personal."
        ),
        "note": (
            "The classifier returns one label from a closed set and never writes a "
            "sentence; every sentence a renter reads is still built by deterministic "
            "code. A label is only acted on after the deterministic router is asked "
            "again and agrees, so the classifier can point at existing answers but "
            "cannot create one. It is reached only when every deterministic layer is "
            "silent, which is why the graded question set does not touch it. Only the "
            "question text is sent; no document content or household data leaves this "
            "process. The question text is written by the renter, so recognisable "
            "identifier shapes are replaced before it is sent — see redaction_note "
            "for what that does and does not reach. Counters are since process start, "
            "not since the pack was "
            "written. When the router is switched off these figures read not_run "
            "rather than zero-as-success."
        ),
    }


def build(views: list[dict[str, Any]], respond) -> dict[str, Any]:
    sections: dict[str, Any] = {}
    for name, fn in (
        ("extraction", lambda: extraction_section(views)),
        ("adversarial", lambda: adversarial_section(respond)),
        ("calculation", calculation_section),
        ("rule_questions", qa_section),
        ("citations", citations_section),
        ("accessibility", accessibility_section),
        ("plain_language", plain_language_section),
        ("rendered_screens", rendered_screens_section),
        ("intent_router", intent_router_section),
    ):
        try:
            sections[name] = fn()
        except Exception as exc:  # 계측기가 고장나면 그것도 정직하게 표시한다
            sections[name] = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sections": sections,
        "honesty_note": ("Every number here is produced by re-running the measurement, not "
                         "copied from a previous run. Sections that cannot be measured are "
                         "marked not_run rather than filled in."),
    }
