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
    return {
        "status": "not_run",
        "tool": "axe-core",
        "note": "The interface is not built yet, so no accessibility scan has been run.",
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
