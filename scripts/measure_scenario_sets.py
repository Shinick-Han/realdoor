# -*- coding: utf-8 -*-
"""
measure_scenario_sets.py -- the scenario corpus measured end to end: extraction
per document, and the LOGIC layer (readiness status, review reasons, threshold
comparison, annualized income) per household file.

WHY THIS FILE EXISTS
--------------------
`scripts/make_scenario_sets.py` built 50 household files whose truth -- per-field
values, per-set expected readiness/reasons/comparison -- was written at fill time.
This harness is the corpus's other half. It is modeled on
`scripts/measure_filled_forms.py` (sha verification, normalize-based comparison,
three-way field counts, seal discipline) and extends it with the set-level logic
measurement that is the corpus's point: the reasoning layer's verdicts are compared
against hand-derived expectations, not merely eyeballed.

WHAT IS MEASURED
----------------
1. EXTRACTION, per document, three ways, exactly as the sibling harnesses count:
   * a `truth_fields` value present on the page: correct / abstained / WRONG
     (compared through eval/score_extraction.normalize, the repository's one
     comparison convention);
   * an `expect_absent` field: held (abstention) or WRONG (a value was invented --
     this includes every masked-year and two-digit-year date, whose century the page
     does not print);
   * a `latent_fields` value (image-only scans -- the pixels show it, the text layer
     does not): correct / abstained / WRONG, reported in its own bucket because an
     abstention there is honest, not a miss.
   Documents are rolled up by stratum: real-carrier / generator / acroform. The
   acroform stratum (wa_dshs AcroForm letters, values in widget annotations) is
   EXPECTED to abstain wholesale today -- it is the T18 acceptance corpus -- so it is
   reported separately and never pollutes the headline.
2. LOGIC, per set, twice:
   * truth-fed: the manifest's truth_fields become DocumentViews (the same gold-fed
     discipline logic/household.load_gold_households uses), the reasoning layer runs,
     and its readiness_status / review-reason codes / comparison / annualized income
     are compared against the manifest's hand-derived expectations. A mismatch here
     is either a wrong hand derivation or a logic-layer surprise -- both are
     findings, and the harness prints which fields disagreed.
   * pipeline-fed: the same reasoning run on what extraction ACTUALLY produced from
     the PDFs, so the compound (extraction -> logic) drift is visible next to the
     isolated logic result rather than being confused with it.

THE SEAL
--------
Sets with `role: "sealed"` are never extracted and never fed to the logic layer.
Their bytes are verified against the recorded sha256 -- integrity without
measurement. `--unseal` exists for the one future measurement at the owner's call
(a hold-out is spent the first time it is used); this exercise does not pass it.

    python scripts/measure_scenario_sets.py
    python scripts/measure_scenario_sets.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from core import extract as ex  # noqa: E402
from score_extraction import normalize  # type: ignore  # noqa: E402
from logic.household import Household, document_from_view  # noqa: E402
from logic.readiness import assess_readiness  # noqa: E402

TRUTH = ROOT / "testdata" / "scenarios" / "scenario_truth.json"
SCEN_DIR = ROOT / "testdata" / "scenarios"

REAL_CARRIERS = {"seattle_housing", "mnhousing", "orangeusd", "kcha_packet"}


def _stratum(doc: dict[str, Any]) -> str:
    if doc["carrier"] == "wa_dshs_acroform":
        return "acroform"
    if doc["carrier"] in REAL_CARRIERS:
        return "real"
    return "generator"


def _matches(field: str, expected: Any, got: Any) -> bool:
    return normalize(field, expected) == normalize(field, got)


def _verify(doc: dict[str, Any], path: Path) -> str | None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return None if digest == doc["sha256"] else digest


def _truth_view(set_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """The manifest's truth as a DocumentView -- the gold-fed logic input."""
    return {
        "document_id": doc["document_id"],
        "household_id": set_id,
        "document_type": doc["document_type"],
        "file_name": doc["file_name"],
        "fields": [
            {"field": f["field"], "value": f["value"], "page": f["page"],
             "bbox": f["bbox"], "certainty": "high", "evidence_kind": "extracted"}
            for f in doc["truth_fields"]
        ],
    }


def _logic_verdict(set_id: str, views: list[dict[str, Any]],
                   required: list[str]) -> dict[str, Any]:
    docs = sorted((document_from_view(v) for v in views), key=lambda d: d.document_id)
    house = Household(household_id=set_id, documents=list(docs))
    result = assess_readiness(house, tuple(required))
    return {
        "readiness_status": result.readiness_status,
        "codes": sorted(set(result.codes)),
        "comparison": result.comparison.comparison,
        "annualized_income": result.income.total,
    }


def _logic_diff(expected_row: dict[str, Any], got: dict[str, Any]) -> list[str]:
    diffs = []
    if got["readiness_status"] != expected_row["expected_readiness_status"]:
        diffs.append(f"status: expected {expected_row['expected_readiness_status']}, "
                     f"got {got['readiness_status']}")
    if got["codes"] != sorted(expected_row["expected_review_reasons"]):
        diffs.append(f"reasons: expected {sorted(expected_row['expected_review_reasons'])}, "
                     f"got {got['codes']}")
    if got["comparison"] != expected_row["expected_comparison"]:
        diffs.append(f"comparison: expected {expected_row['expected_comparison']!r}, "
                     f"got {got['comparison']!r}")
    want_income = expected_row["expected_annualized_income"]
    have_income = got["annualized_income"]
    if (want_income is None) != (have_income is None) or (
            want_income is not None and have_income is not None
            and abs(want_income - have_income) > 0.005):
        diffs.append(f"income: expected {want_income}, got {have_income}")
    return diffs


def tally(fallback_mapper: Any, unseal: bool = False) -> dict[str, Any]:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    strata = {name: {"correct": 0, "wrong": 0, "abstained": 0,
                     "absent_held": 0,
                     "latent_correct": 0, "latent_wrong": 0, "latent_abstained": 0}
              for name in ("real", "generator", "acroform")}
    wrong_detail: list[dict[str, Any]] = []
    emitted_for_unscored: list[dict[str, Any]] = []
    tampered: list[dict[str, str]] = []
    missing: list[str] = []
    sealed_kept: list[dict[str, Any]] = []
    set_rows: list[dict[str, Any]] = []
    logic_mismatch: list[dict[str, Any]] = []
    pipeline_drift: list[dict[str, Any]] = []

    for row in truth["sets"]:
        set_id = row["id"]
        if row["role"] == "sealed" and not unseal:
            for doc in row["documents"]:
                path = SCEN_DIR / doc["file_name"]
                if not path.exists():
                    sealed_kept.append({"set": set_id, "file": doc["file_name"],
                                        "intact": False, "problem": "file missing"})
                    continue
                moved = _verify(doc, path)
                sealed_kept.append({"set": set_id, "file": doc["file_name"],
                                    "intact": moved is None,
                                    **({"problem": f"sha256 now {moved}"} if moved else {})})
            continue

        extraction_views: list[dict[str, Any]] = []
        doc_counts = {"correct": 0, "wrong": 0, "abstained": 0}
        for doc in row["documents"]:
            path = SCEN_DIR / doc["file_name"]
            if not path.exists():
                missing.append(doc["file_name"])
                continue
            moved = _verify(doc, path)
            if moved is not None:
                tampered.append({"file": doc["file_name"], "sha256": moved})

            mapper = (
                ex.tracking_layered_mapper(doc["document_type"])
                if fallback_mapper is ex.layered_mapper
                else fallback_mapper
            )
            view = ex.extract_document(
                path, document_type=doc["document_type"],
                document_id=doc["document_id"], fallback_mapper=mapper,
            )
            view["household_id"] = set_id
            extraction_views.append(view)

            bucket = strata[_stratum(doc)]
            got = {f["field"]: f for f in view["fields"]}
            reachable = ex.EXPECTED_FIELDS.get(doc["document_type"], ())
            expected_map = {f["field"]: f["value"] for f in doc["truth_fields"]
                            if f["field"] in reachable}
            latent_map = {f["field"]: f["value"] for f in doc["latent_fields"]
                          if f["field"] in reachable}
            unscored = dict(doc.get("marked_only", {}))
            unscored.update(doc.get("ambiguous", {}))

            for name in reachable:
                field = got.get(name)
                answered = field is not None and field["certainty"] != "abstain"
                if name in expected_map:
                    if not answered:
                        bucket["abstained"] += 1
                        doc_counts["abstained"] += 1
                    elif _matches(name, expected_map[name], field["value"]):
                        bucket["correct"] += 1
                        doc_counts["correct"] += 1
                    else:
                        bucket["wrong"] += 1
                        doc_counts["wrong"] += 1
                        wrong_detail.append({
                            "set": set_id, "file": doc["file_name"], "field": name,
                            "kind": "wrong value for a field that exists",
                            "expected": expected_map[name], "got": field["value"],
                            "source_text": field.get("source_text"),
                            "notes": field.get("notes")})
                elif name in latent_map:
                    if not answered:
                        bucket["latent_abstained"] += 1
                    elif _matches(name, latent_map[name], field["value"]):
                        bucket["latent_correct"] += 1
                    else:
                        bucket["latent_wrong"] += 1
                        wrong_detail.append({
                            "set": set_id, "file": doc["file_name"], "field": name,
                            "kind": "wrong value read out of an image-only scan",
                            "expected": latent_map[name], "got": field["value"],
                            "source_text": field.get("source_text"),
                            "notes": field.get("notes")})
                elif name in unscored:
                    if answered:
                        emitted_for_unscored.append({
                            "set": set_id, "file": doc["file_name"], "field": name,
                            "got": field["value"]})
                else:  # expect_absent
                    if not answered:
                        bucket["absent_held"] += 1
                    else:
                        bucket["wrong"] += 1
                        doc_counts["wrong"] += 1
                        wrong_detail.append({
                            "set": set_id, "file": doc["file_name"], "field": name,
                            "kind": "value invented for a field with no honest value",
                            "expected": None, "got": field["value"],
                            "source_text": field.get("source_text"),
                            "notes": field.get("notes")})

        # ---- logic, truth-fed (the corpus's point) --------------------------------
        truth_views = [_truth_view(set_id, d) for d in row["documents"]]
        verdict = _logic_verdict(set_id, truth_views, row["required_document_types"])
        diffs = _logic_diff(row, verdict)
        if diffs:
            logic_mismatch.append({"set": set_id, "scenario": row["scenario"],
                                   "diffs": diffs, "got": verdict})

        # ---- logic, pipeline-fed (compound drift) ---------------------------------
        pipe = _logic_verdict(set_id, extraction_views, row["required_document_types"])
        pipe_diffs = _logic_diff(row, pipe)
        if pipe_diffs:
            pipeline_drift.append({"set": set_id, "scenario": row["scenario"],
                                   "carrier_class": row["carrier_class"],
                                   "diffs": pipe_diffs})

        set_rows.append({
            "set": set_id, "layer": row["layer"], "scenario": row["scenario"],
            "carrier_class": row["carrier_class"],
            "extraction": dict(doc_counts),
            "logic_truth_fed": "agrees" if not diffs else "DISAGREES",
            "logic_pipeline": "agrees" if not pipe_diffs else "drifts",
        })

    headline = {k: strata["real"][k] + strata["generator"][k]
                for k in strata["real"]}
    scored = headline["correct"] + headline["wrong"] + headline["abstained"]
    return {
        "config_note": "extraction asserted per manifest document_type; comparison via "
                       "eval/score_extraction.normalize",
        "sets_measured": len(set_rows),
        "sets_sealed": sorted({s["set"] for s in sealed_kept}),
        "sealed_intact": all(s["intact"] for s in sealed_kept),
        "sealed_detail": sealed_kept,
        "documents_missing": missing,
        "sha256_mismatch": tampered,
        "extraction_headline": {
            **headline,
            "rate": None if not scored else round(100.0 * headline["correct"] / scored, 1),
            "note": "real + generator strata only; acroform reported separately",
        },
        "extraction_strata": strata,
        "logic_truth_fed_mismatches": logic_mismatch,
        "logic_pipeline_drift": pipeline_drift,
        "emitted_for_unscored": emitted_for_unscored,
        "per_set": set_rows,
        "wrong_detail": wrong_detail,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--config", choices=("deterministic", "with_mapper"), default="deterministic",
        help="mapper configuration, mirroring measure_filled_forms (default: "
             "deterministic = frozen tables + hand-written synonyms)")
    parser.add_argument(
        "--unseal", action="store_true",
        help="open the sealed sets. Spends the hold-out; owner's call only.")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

    if args.unseal:
        print("WARNING: --unseal opens the sealed sets; a hold-out is spent the first "
              "time it is used.")

    report = tally(
        ex.layered_mapper if args.config == "with_mapper" else ex.synonym_mapper,
        unseal=args.unseal,
    )
    problems = bool(report["wrong_detail"]) or bool(report["logic_truth_fed_mismatches"])
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 1 if problems else 0

    print("=" * 78)
    print("scenario corpus -- 50 household files, truth by construction")
    print("=" * 78)
    head = report["extraction_headline"]
    print(f"extraction headline (real+generator strata): "
          f"{head['rate']}%  correct {head['correct']}  abstain {head['abstained']}  "
          f"WRONG {head['wrong']}   (+{head['absent_held']} absences held)")
    print(f"  latent (scans): correct {head['latent_correct']}  "
          f"abstain {head['latent_abstained']}  WRONG {head['latent_wrong']}")
    for name, s in report["extraction_strata"].items():
        total = s["correct"] + s["wrong"] + s["abstained"]
        rate = "-" if not total else f"{100.0 * s['correct'] / total:.1f}%"
        print(f"  stratum {name:<10} rate {rate:>6}  correct {s['correct']:>3}  "
              f"abstain {s['abstained']:>3}  wrong {s['wrong']:>3}  "
              f"absent_held {s['absent_held']:>3}  latent c/a/w "
              f"{s['latent_correct']}/{s['latent_abstained']}/{s['latent_wrong']}")
    print("-" * 78)
    agree = sum(1 for r in report["per_set"] if r["logic_truth_fed"] == "agrees")
    pipe_ok = sum(1 for r in report["per_set"] if r["logic_pipeline"] == "agrees")
    print(f"logic layer, truth-fed : {agree}/{report['sets_measured']} sets agree with "
          f"the hand-derived expectations")
    print(f"logic layer, pipeline  : {pipe_ok}/{report['sets_measured']} sets agree "
          f"end-to-end (extraction feeding logic)")
    for row in report["per_set"]:
        e = row["extraction"]
        print(f"  {row['set']} L{row['layer']} [{row['carrier_class']:<9}] "
              f"ext c/a/w {e['correct']:>2}/{e['abstained']:>2}/{e['wrong']:>2}  "
              f"logic {row['logic_truth_fed']:<9} pipeline {row['logic_pipeline']:<7} "
              f"{row['scenario'][:44]}")
    print(f"sealed sets (never opened): {', '.join(report['sets_sealed'])}  "
          f"[bytes intact: {report['sealed_intact']}]")
    if report["documents_missing"]:
        print(f"MISSING: {report['documents_missing']}")
    if report["sha256_mismatch"]:
        print(f"SHA256 MISMATCH: {report['sha256_mismatch']}")

    if report["logic_truth_fed_mismatches"]:
        print("\nLOGIC DISAGREEMENTS (truth-fed):")
        for m in report["logic_truth_fed_mismatches"]:
            print(f"\n  {m['set']}  {m['scenario']}")
            for d in m["diffs"]:
                print(f"    {d}")
    if report["logic_pipeline_drift"]:
        print(f"\npipeline drift on {len(report['logic_pipeline_drift'])} sets "
              f"(extraction gaps compounding into the logic layer):")
        for m in report["logic_pipeline_drift"]:
            print(f"  {m['set']} [{m['carrier_class']}] {'; '.join(m['diffs'])[:120]}")
    for item in report["emitted_for_unscored"]:
        print(f"  note: {item['set']} {item['file']} :: {item['field']} emitted "
              f"{item['got']!r} (unscored field)")

    bad = report["wrong_detail"]
    if bad:
        print("\nWRONG VALUES:")
        for d in bad:
            print(f"\n  {d['set']}  {d['file']}  ::  {d['field']}   [{d['kind']}]")
            print(f"    expected : {d['expected']!r}")
            print(f"    got      : {d['got']!r}")
            print(f"    src text : {d['source_text']!r}")
    else:
        print("\nwrong values: 0")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
