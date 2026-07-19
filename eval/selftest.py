#!/usr/bin/env python3
"""Builds the ``/api/selftest`` payload (CONTRACTS section 9) — our own scorecard.

    python eval/selftest.py                      # everything computable from the pack alone
    python eval/selftest.py --pred preds.jsonl --adversarial-responses r.jsonl \
                            --calculations calcs.json --report report.json \
                            --axe axe.json --now 2026-07-19T04:25:00Z

THE ONE RULE OF THIS FILE: it never invents a metric.
A section that cannot be computed from the inputs actually supplied is emitted as

    {"status": "not_run", "reason": "<why>", "needs": "<what input would compute it>"}

and carries NO numbers at all — not zeros, not nulls dressed up as measurements. A section
computed for real is emitted with ``"status": "ok"`` plus a ``"source"`` naming the file (and
sha256 where it is a pack file) every number came from.

SECTIONS
  extraction     — computed only with --pred (DocumentView predictions). Delegates to
                   eval/score_extraction.py, so the numbers here are the same numbers that
                   command prints. With --self-check-extraction it instead reports the
                   gold-against-gold calibration run and labels it as such.
  adversarial    — computed only with --adversarial-responses. Delegates to
                   eval/run_adversarial.py.
  calculations   — computed only with --calculations. Each Calculation (CONTRACTS section 5)
                   named "annualized_income" is matched to a household (via its own
                   household_id, else via the HH-xxx prefix of an input's from_document) and
                   compared, to the cent, with expected_annualized_income in
                   pack/evaluation/application_checklists.json. Calculations that cannot be
                   matched to a household are counted in "unmatched", never in "verified".
  accessibility  — never computed here. This is the ui/ stream's axe-core run; supply its
                   JSON with --axe and we transcribe violation and page counts, nothing more.
  citations      — computed only with --report (a ReadinessReport). Counts citations and how
                   many carry verified_against_source == true. Per CONTRACTS section 4, null
                   means UNVERIFIED and is never counted as verified.

DETERMINISM
  Same inputs -> same output, with exactly one exception: ``generated_at`` defaults to the
  wall clock. Pass --now (or set REALDOOR_NOW) to pin it; the test suite always does.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_adversarial  # noqa: E402
import score_extraction  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKLISTS_PATH = REPO_ROOT / "pack" / "evaluation" / "application_checklists.json"


def not_run(reason: str, needs: str) -> dict:
    return {"status": "not_run", "reason": reason, "needs": needs}


def _rel(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


# =====================================================================================
# sections
# =====================================================================================
def extraction_section(pred_path: Path | None, self_check: bool) -> dict:
    if self_check:
        report, problems = score_extraction.self_check()
        mode = "self_check_gold_vs_gold"
        source = report["gold_file"]
    elif pred_path:
        gold = score_extraction.load_jsonl(score_extraction.GOLD_PATH)
        report = score_extraction.score(
            score_extraction.load_predictions(pred_path), gold
        )
        problems = []
        mode = "predictions"
        source = _rel(pred_path)
    else:
        return not_run(
            "no DocumentView predictions were supplied, so nothing has been extracted yet",
            "--pred <predictions.jsonl>  (or --self-check-extraction for calibration only)",
        )

    return {
        "status": "ok",
        "mode": mode,
        "source": source,
        "gold_file": report["gold_file"],
        "gold_sha256": report["gold_sha256"],
        "fields_total": report["fields_total"],
        "exact_match": report["exact_match"],
        "wrong": report["wrong"],
        "abstained": report["abstained"],
        "missed": report["missed"],
        "accuracy": report["accuracy_incl_abstentions"],
        "selective_accuracy": report["selective_accuracy"],
        "coverage": report["coverage"],
        "bbox_iou_gt_0_5": report["bbox"]["iou_gt_0_5"],
        "bbox_evaluated": report["bbox"]["evaluated"],
        "bbox_iou_mean": report["bbox"]["iou_mean"],
        "documents_in_gold": report["documents_in_gold"],
        "documents_predicted": report["documents_predicted"],
        "self_check_problems": problems,
        "note": (
            "accuracy = exact_match / fields_total (abstentions counted as not-right but "
            "NOT as wrong); selective_accuracy = exact_match / attempted."
        ),
    }


def adversarial_section(responses_path: Path | None) -> dict:
    if not responses_path:
        return not_run(
            "no recorded responses were supplied, so the 24 pack tests have not been run "
            "against a real responder",
            '--adversarial-responses <jsonl of {"test_id": ..., "response": {...}}>',
        )
    result = run_adversarial.run_suite(run_adversarial._load_recorded(responses_path))
    return {
        "status": "ok",
        "source": _rel(responses_path),
        "tests_file": result["tests_file"],
        "total": result["total"],
        "passed": result["passed"],
        "failed": result["failed"],
        "must_not_violations": result["must_not_violations"],
        "behavior_signal_absent": result["behavior_signal_absent"],
        "detector_limits": "see the module docstring of eval/run_adversarial.py",
    }


def calculations_section(calc_path: Path | None) -> dict:
    if not calc_path:
        return not_run(
            "no Calculation objects were supplied, so none have been checked against the "
            "pack starter expectations",
            "--calculations <calculations.json>",
        )
    data = json.loads(calc_path.read_text(encoding="utf-8"))
    calcs = data if isinstance(data, list) else data.get("calculations", [])
    expected = {
        row["household_id"]: Decimal(str(row["expected_annualized_income"]))
        for row in json.loads(CHECKLISTS_PATH.read_text(encoding="utf-8"))
    }

    verified, mismatched, unmatched = [], [], []
    for calc in calcs:
        household = calc.get("household_id")
        if not household:
            for item in calc.get("inputs", []):
                doc = str(item.get("from_document") or "")
                if doc.startswith("HH-"):
                    household = doc.split("-D")[0]
                    break
        name = calc.get("name")
        if name != "annualized_income" or household not in expected:
            unmatched.append({"name": name, "household_id": household,
                              "reason": "no matching pack expectation for this calculation"})
            continue
        got = Decimal(str(calc.get("result")))
        if got == expected[household]:
            verified.append(household)
        else:
            mismatched.append({"household_id": household,
                               "pack_expected": str(expected[household]),
                               "produced": str(got)})
    return {
        "status": "ok",
        "source": _rel(calc_path),
        "compared_against": _rel(CHECKLISTS_PATH),
        "compared_against_sha256": score_extraction.sha256_of(CHECKLISTS_PATH),
        "total": len(calcs),
        "verified_against_pack_starter": len(verified),
        "verified_households": sorted(verified),
        "mismatched": mismatched,
        "unmatched": unmatched,
        "note": "annualized_income compared exactly (Decimal); no tolerance applied",
    }


def accessibility_section(axe_path: Path | None) -> dict:
    if not axe_path:
        return not_run(
            "the axe-core run belongs to the ui/ stream and no results file was supplied; "
            "this harness does not run a browser and will not guess",
            "--axe <axe-core results.json>",
        )
    data = json.loads(axe_path.read_text(encoding="utf-8"))
    pages = data if isinstance(data, list) else [data]
    violations = sum(len(page.get("violations", [])) for page in pages)
    return {
        "status": "ok",
        "source": _rel(axe_path),
        "tool": "axe-core",
        "violations": violations,
        "checked_pages": len(pages),
        "note": "counts transcribed from the supplied axe-core output; nothing recomputed",
    }


def citations_section(report_path: Path | None) -> dict:
    if not report_path:
        return not_run(
            "no ReadinessReport was supplied, so there are no citations to count",
            "--report <ReadinessReport.json>",
        )
    data = json.loads(report_path.read_text(encoding="utf-8"))
    citations = data.get("citations", []) if isinstance(data, dict) else []
    verified = [c for c in citations if c.get("verified_against_source") is True]
    explicitly_false = [c for c in citations if c.get("verified_against_source") is False]
    return {
        "status": "ok",
        "source": _rel(report_path),
        "total": len(citations),
        "verified_against_live_source": len(verified),
        "not_verified": len(citations) - len(verified),
        "explicitly_false": len(explicitly_false),
        "note": (
            "verified_against_source == null (or absent) means NOT verified (CONTRACTS "
            "section 4) and is counted in not_verified, never in verified"
        ),
    }


# =====================================================================================
# payload
# =====================================================================================
def build_payload(
    pred: Path | None = None,
    adversarial_responses: Path | None = None,
    calculations: Path | None = None,
    axe: Path | None = None,
    report: Path | None = None,
    self_check_extraction: bool = False,
    now: str | None = None,
) -> dict:
    generated_at = (
        now
        or os.environ.get("REALDOOR_NOW")
        or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    payload = {
        "extraction": extraction_section(pred, self_check_extraction),
        "adversarial": adversarial_section(adversarial_responses),
        "calculations": calculations_section(calculations),
        "accessibility": accessibility_section(axe),
        "citations": citations_section(report),
        "generated_at": generated_at,
        "harness": {
            "extraction_scorer": "eval/score_extraction.py",
            "adversarial_runner": "eval/run_adversarial.py",
            "static_guard": "eval/test_no_decision.py",
            "contract": "contracts/CONTRACTS.md",
            "policy": (
                "sections with status not_run carry no numbers; no metric on this page is "
                "estimated, extrapolated or defaulted"
            ),
        },
    }
    payload["sections_not_run"] = sorted(
        name
        for name in ("extraction", "adversarial", "calculations", "accessibility", "citations")
        if payload[name]["status"] == "not_run"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pred", type=Path)
    parser.add_argument("--adversarial-responses", type=Path)
    parser.add_argument("--calculations", type=Path)
    parser.add_argument("--axe", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--self-check-extraction", action="store_true",
                        help="report the gold-vs-gold calibration in the extraction section")
    parser.add_argument("--now", help="pin generated_at (for deterministic output)")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    payload = build_payload(
        pred=args.pred,
        adversarial_responses=args.adversarial_responses,
        calculations=args.calculations,
        axe=args.axe,
        report=args.report,
        self_check_extraction=args.self_check_extraction,
        now=args.now,
    )
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
