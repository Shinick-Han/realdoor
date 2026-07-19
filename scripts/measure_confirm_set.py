# -*- coding: utf-8 -*-
"""
measure_confirm_set.py -- extraction measured on the untuned confirmation hold-out.

WHY THIS FILE EXISTS
--------------------
`testdata/confirm_truth.json` is 14 real published US income documents, collected by a
worker who had web access and nothing else: `core/extract.py`, `core/label_llm.py`,
`logic/**`, `testdata/external_truth.json` and `scripts/measure_external_holdout.py` were
deliberately not read, and the extractor was never run. Every value in `expected` /
`expect_absent` was transcribed from a rendered page image before any code was seen.

That ordering is the only thing that makes the set worth anything, and it is spent the
first time the set is used to *choose* something. This script measures; it does not tune.

WHAT HAD TO BE DECIDED TO MAKE IT SCOREABLE
-------------------------------------------
The manifest was written without repository access, so it does not speak the extractor's
schema. Three gaps had to be closed here, in the harness, rather than by editing the truth
file -- editing the truth after seeing the output is how a hold-out stops being one.

1. **No `document_type`.** `extract_document` needs one and the manifest carries none, so
   every document is scored as `pay_stub`. That is the type whose `EXPECTED_FIELDS` the
   manifest's own `field_vocabulary` matches, and it is the type a housing caseworker
   would file all 14 of these under. It is asserted here, once, in the open.

2. **`employer_name` and `document_date` are structurally unreachable.** Neither is in
   `EXPECTED_FIELDS["pay_stub"]`, so the extractor cannot emit them under any
   configuration; it is not that it fails to find them, it is that nothing ever looks.
   Scoring them as ordinary abstentions would quietly pad the abstain column with 10
   expected values (and 24 `expect_absent` ones) that no change to `core/` could ever
   move. They are counted in their own bucket, `unreachable`, and the headline rate is
   computed over the reachable fields only. Both totals are printed.

3. **Masked years.** Five expected values are printed on the page with a redacted year --
   `1/7/XX`, `1/13/XX`, `1/20/XX`. `eval/score_extraction.normalize` can never match
   those, and dropping them would hide false positives rather than count them. They are
   compared with the year as a wildcard: month and day must match exactly, the year is
   not tested. A value with the wrong month/day is still WRONG. See `_masked_date`.

Everything else is scored exactly as `scripts/measure_external_holdout.py` scores the
external six, including the rule that matters most: a concrete value for a field listed in
`expect_absent` is a WRONG value, not an abstention. Four of these 14 documents are blank
forms, where inventing a value is the only error available.

    python scripts/measure_confirm_set.py
    python scripts/measure_confirm_set.py --json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from core import extract as ex  # noqa: E402
from score_extraction import normalize  # type: ignore  # noqa: E402

TRUTH = ROOT / "testdata" / "confirm_truth.json"
RAW_DIR = ROOT / "testdata" / "confirm_raw"

#: See point 1 above. Asserted by this harness, not carried by the truth file.
DOCUMENT_TYPE = "pay_stub"

#: See point 2 above. Derived, not listed, so it tracks `EXPECTED_FIELDS` if that grows.
REACHABLE = frozenset(ex.EXPECTED_FIELDS.get(DOCUMENT_TYPE, ()))

_MASKED_DATE_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*[Xx]{2,4}\s*$")


def _masked_date(expected: str) -> tuple[int, int] | None:
    """(month, day) if this expected value is a date printed with a redacted year."""
    match = _MASKED_DATE_RE.match(str(expected))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _matches(field: str, expected: Any, got: Any) -> bool:
    """Does the extracted value match the transcribed one? Year-wildcard for masked dates."""
    masked = _masked_date(expected) if isinstance(expected, str) else None
    if masked is not None:
        # The extractor emits ISO. Anything else cannot be checked against a masked date,
        # so it is not a match -- an unparsed string is not evidence of agreement.
        try:
            _, month, day = str(got).split("-")
            return (int(month), int(day)) == masked
        except (ValueError, AttributeError):
            return False
    return normalize(field, expected) == normalize(field, got)


def _verify_bytes(doc: dict[str, Any], path: Path) -> str | None:
    """The collector recorded a sha256. If the bytes moved, the measurement is void."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return None if digest == doc.get("sha256") else digest


def tally(fallback_mapper: Any = ex.synonym_mapper) -> dict[str, Any]:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    correct = wrong = abstained = 0
    unreachable_expected = unreachable_absent = 0
    wrong_detail: list[dict[str, Any]] = []
    unverified: list[str] = []
    per_doc: list[dict[str, Any]] = []
    missing: list[str] = []
    tampered: list[dict[str, str]] = []

    for doc in truth["documents"]:
        path = RAW_DIR / doc["file_name"]
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
                if _masked_date(expected) is not None:
                    unverified.append(
                        f"{doc['file_name']}::{name} matched month/day only "
                        f"(expected {expected!r}, year not checked)"
                    )
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

        per_doc.append(
            {
                "file": doc["file_name"],
                "kind": doc.get("kind"),
                "correct": d_correct,
                "abstained": d_abstain,
                "wrong": d_wrong,
            }
        )

    total = correct + wrong + abstained
    return {
        "document_type_assumed": DOCUMENT_TYPE,
        "documents": len(per_doc),
        "documents_missing": missing,
        "sha256_mismatch": tampered,
        "fields_total": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "rate": None if total == 0 else round(100.0 * correct / total, 1),
        "unreachable_expected": unreachable_expected,
        "unreachable_absent": unreachable_absent,
        "year_masked_matches": unverified,
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
        help="which mapper configuration to score (default: deterministic)",
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
    print("confirmation set -- 14 published documents, untuned, scored once")
    print("=" * 78)
    print(f"document_type asserted by this harness : {report['document_type_assumed']}")
    print(
        f"{report['rate']:>5.1f}%  correct {report['correct']:>3}  "
        f"abstain {report['abstained']:>3}  WRONG {report['wrong']:>3}   "
        f"(of {report['fields_total']} reachable fields, {report['documents']} docs)"
    )
    print(
        f"       not scored: {report['unreachable_expected']} expected + "
        f"{report['unreachable_absent']} expect_absent values name fields outside "
        f"EXPECTED_FIELDS['{DOCUMENT_TYPE}'] and are structurally unreachable"
    )
    if report["documents_missing"]:
        print(f"       MISSING PDFs: {', '.join(report['documents_missing'])}")
    if report["sha256_mismatch"]:
        print(f"       SHA256 MISMATCH: {report['sha256_mismatch']}")
    print("-" * 78)
    for row in report["per_document"]:
        print(
            f"  {row['file'][:44]:<46} correct {row['correct']:>2}  "
            f"abstain {row['abstained']:>2}  wrong {row['wrong']:>2}"
        )
    for note in report["year_masked_matches"]:
        print(f"  note: {note}")

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
