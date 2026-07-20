# -*- coding: utf-8 -*-
"""
measure_filled_forms.py -- extraction measured on the filled counterparts of the
corpus's real blank forms.

WHY THIS FILE EXISTS
--------------------
The blank forms in `testdata/confirm_raw/` only ever tested the refusal side: 80 empty
fields where every correct answer is an abstention. `scripts/make_filled_forms.py`
produced their filled counterparts -- real layouts we did not draw, carrying values we
know by construction because we placed them, with the truth manifest
(`testdata/filled/filled_truth.json`) written at fill time. This script asks the
question the blanks never could: when a value IS on a foreign layout, do we read it?

WHAT IS SCORED, AND WHAT IS NOT
-------------------------------
Scored exactly as `scripts/measure_confirm_set.py` scores the confirmation set:

* Every document is extracted as `pay_stub` -- the type whose EXPECTED_FIELDS the
  manifest's field vocabulary matches, asserted here in the open, exactly as the
  confirmation harness asserts it.
* `employer_name` and `document_date` are structurally unreachable (not in
  EXPECTED_FIELDS["pay_stub"]); they are counted in their own bucket, never as
  abstentions, and the headline rate covers reachable fields only.
* A concrete value for a field in `expect_absent` is a WRONG value, not an abstention.
* Additionally, per the manifest's own rules (see `truth_discipline` there):
  - `marked_only` fields (value exists only as a graphical mark -- a drawn circle, a
    checkbox state) are NOT scored either way. But if the extractor EMITS a value for
    one, that emission is reported under `emitted_for_unscored`: it read a menu, and a
    reader deserves to see that even though no scoring credit or blame attaches.
  - `ambiguous` fields (genuinely ambiguous meaning on that form) are handled the same
    way.

THE SEAL
--------
Documents with `role: "sealed"` are NEVER extracted here. This harness verifies they
exist and still match their recorded sha256 -- integrity without measurement -- and
excludes them from every number it prints. They are held for one future measurement at
the owner's call (a hold-out is spent the first time it is used).

    python scripts/measure_filled_forms.py
    python scripts/measure_filled_forms.py --json
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

TRUTH = ROOT / "testdata" / "filled" / "filled_truth.json"
RAW_DIR = ROOT / "testdata" / "filled"

#: Asserted by this harness, not carried by the truth file -- same rule and same value
#: as scripts/measure_confirm_set.py, because these are the same documents' filled twins.
DOCUMENT_TYPE = "pay_stub"

#: Derived, not listed, so it tracks EXPECTED_FIELDS if that grows.
REACHABLE = frozenset(ex.EXPECTED_FIELDS.get(DOCUMENT_TYPE, ()))


def _matches(field: str, expected: Any, got: Any) -> bool:
    """Same comparison the sibling harnesses use: eval/score_extraction.normalize."""
    return normalize(field, expected) == normalize(field, got)


def _verify_bytes(doc: dict[str, Any], path: Path) -> str | None:
    """The generator recorded a sha256 at fill time. If the bytes moved, truth-by-
    construction no longer describes this file and the measurement is void."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return None if digest == doc.get("sha256") else digest


def tally(fallback_mapper: Any = ex.synonym_mapper) -> dict[str, Any]:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    correct = wrong = abstained = 0
    unreachable_expected = unreachable_absent = 0
    wrong_detail: list[dict[str, Any]] = []
    emitted_for_unscored: list[dict[str, Any]] = []
    per_doc: list[dict[str, Any]] = []
    missing: list[str] = []
    tampered: list[dict[str, str]] = []
    sealed_kept: list[dict[str, Any]] = []

    for doc in truth["documents"]:
        path = RAW_DIR / doc["file_name"]
        if doc.get("role") == "sealed":
            # Integrity only. No open, no render, no extraction -- the seal holds.
            if not path.exists():
                sealed_kept.append({"file": doc["file_name"], "intact": False,
                                    "problem": "file missing"})
            else:
                moved = _verify_bytes(doc, path)
                sealed_kept.append({"file": doc["file_name"],
                                    "intact": moved is None,
                                    **({"problem": f"sha256 now {moved}"} if moved else {})})
            continue

        if not path.exists():
            missing.append(doc["file_name"])
            continue
        moved = _verify_bytes(doc, path)
        if moved is not None:
            tampered.append({"file": doc["file_name"], "sha256": moved})

        mapper = (
            ex.tracking_layered_mapper(DOCUMENT_TYPE)
            if fallback_mapper is ex.layered_mapper
            else fallback_mapper
        )
        view = ex.extract_document(
            path, document_type=DOCUMENT_TYPE, fallback_mapper=mapper
        )
        got = {f["field"]: f for f in view["fields"]}
        d_correct = d_wrong = d_abstain = 0
        unscored = dict(doc.get("marked_only", {}))
        unscored.update(doc.get("ambiguous", {}))

        for name, expected in doc.get("expected", {}).items():
            if name not in REACHABLE:
                unreachable_expected += 1
                continue
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                abstained += 1
                d_abstain += 1
                continue
            if _matches(name, expected, field["value"]):
                correct += 1
                d_correct += 1
            else:
                wrong += 1
                d_wrong += 1
                wrong_detail.append(
                    {
                        "file": doc["file_name"],
                        "field": name,
                        "kind": "wrong value for a field that exists",
                        "expected": expected,
                        "got": field["value"],
                        "certainty": field.get("certainty"),
                        "page": field.get("page"),
                        "bbox": field.get("bbox"),
                        "source_text": field.get("source_text"),
                        "notes": field.get("notes"),
                    }
                )

        for name in doc.get("expect_absent", []):
            if name not in REACHABLE:
                unreachable_absent += 1
                continue
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                abstained += 1
                d_abstain += 1
                continue
            wrong += 1
            d_wrong += 1
            wrong_detail.append(
                {
                    "file": doc["file_name"],
                    "field": name,
                    "kind": "value invented for a field that is not on the page",
                    "expected": None,
                    "got": field["value"],
                    "certainty": field.get("certainty"),
                    "page": field.get("page"),
                    "bbox": field.get("bbox"),
                    "source_text": field.get("source_text"),
                    "notes": field.get("notes"),
                }
            )

        # Not scored either way, but an emission here must be visible: for a
        # marked_only field it means the extractor read a printed menu, not the mark.
        for name, why in unscored.items():
            field = got.get(name)
            if field is not None and field["certainty"] != "abstain":
                emitted_for_unscored.append(
                    {
                        "file": doc["file_name"],
                        "field": name,
                        "got": field["value"],
                        "certainty": field.get("certainty"),
                        "source_text": field.get("source_text"),
                        "why_unscored": (why.get("why_not_expected")
                                         if isinstance(why, dict) else why),
                    }
                )

        per_doc.append(
            {
                "file": doc["file_name"],
                "kind": doc.get("kind"),
                "technique": doc.get("technique"),
                "correct": d_correct,
                "abstained": d_abstain,
                "wrong": d_wrong,
            }
        )

    total = correct + wrong + abstained
    return {
        "document_type_assumed": DOCUMENT_TYPE,
        "documents_measured": len(per_doc),
        "documents_missing": missing,
        "sha256_mismatch": tampered,
        "sealed_excluded": sealed_kept,
        "fields_total": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "rate": None if total == 0 else round(100.0 * correct / total, 1),
        "unreachable_expected": unreachable_expected,
        "unreachable_absent": unreachable_absent,
        "emitted_for_unscored": emitted_for_unscored,
        "per_document": per_doc,
        "wrong_detail": wrong_detail,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--config",
        choices=("deterministic", "with_mapper"),
        default="deterministic",
        help="which mapper configuration to measure (default: deterministic)",
    )
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass

    report = tally(
        ex.layered_mapper if args.config == "with_mapper" else ex.synonym_mapper
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0 if report["wrong"] == 0 else 1

    print("=" * 78)
    print("filled forms -- blank-form layouts, invented values, truth by construction")
    print("=" * 78)
    print(f"document_type asserted by this harness : {report['document_type_assumed']}")
    print(
        f"{report['rate']:>5.1f}%  correct {report['correct']:>3}  "
        f"abstain {report['abstained']:>3}  WRONG {report['wrong']:>3}   "
        f"(of {report['fields_total']} reachable fields, "
        f"{report['documents_measured']} dev docs)"
    )
    print(
        f"       not scored: {report['unreachable_expected']} expected + "
        f"{report['unreachable_absent']} expect_absent values name fields outside "
        f"EXPECTED_FIELDS['{DOCUMENT_TYPE}'] and are structurally unreachable"
    )
    for sealed in report["sealed_excluded"]:
        mark = "intact, never extracted" if sealed["intact"] else \
            f"INTEGRITY PROBLEM: {sealed.get('problem')}"
        print(f"       sealed (excluded from every number above): {sealed['file']}  "
              f"[{mark}]")
    if report["documents_missing"]:
        print(f"       MISSING PDFs: {', '.join(report['documents_missing'])}")
    if report["sha256_mismatch"]:
        print(f"       SHA256 MISMATCH: {report['sha256_mismatch']}")
    print("-" * 78)
    for row in report["per_document"]:
        print(
            f"  {row['file'][:40]:<42} [{row['technique']:<8}] correct {row['correct']:>2}  "
            f"abstain {row['abstained']:>2}  wrong {row['wrong']:>2}"
        )
    for item in report["emitted_for_unscored"]:
        print(
            f"  note: {item['file']} :: {item['field']} emitted {item['got']!r} "
            f"(unscored: {item['why_unscored']})"
        )

    bad = report["wrong_detail"]
    if bad:
        print("\nWRONG VALUES:")
        for d in bad:
            print(f"\n  {d['file']}  ::  {d['field']}   [{d['kind']}]")
            print(f"    expected : {d['expected']!r}")
            print(f"    got      : {d['got']!r}   (certainty {d['certainty']}, page {d['page']})")
            print(f"    src text : {d['source_text']!r}")
            print(f"    bbox     : {d['bbox']}")
        return 1
    print("\nwrong values: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
