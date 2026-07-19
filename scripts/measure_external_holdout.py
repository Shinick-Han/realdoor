# -*- coding: utf-8 -*-
"""
measure_external_holdout.py -- extraction measured on documents we did not draw.

WHY THIS FILE EXISTS
--------------------
`scripts/make_holdout.py` externalised ONE variable: label wording. It took label strings
from real payroll documents and then rendered them through `make_testdata.build_page` --
our own generator. Its own docstring says so: "the layout is our own generator's --
deliberately, because label wording is the single variable under test here." As a
single-variable control that is legitimate, and the 55.9% / 76.5% it produced is a fair
measurement OF LABEL WORDING.

But it leaves a second claim resting on nothing. The reason we can publish a hold-out with
zero wrong values is the geometry guard: a candidate value must sit under its label inside
`VALUE_Y_WINDOW`, left-aligned to `VALUE_X_TOLERANCE`, and parse as the field's type.
Every document that guard has ever been measured against was drawn by the same code that
defines the guard's idea of where a value goes. The guard has been asked to find values in
a world built to its own specification.

On a real ADP two-column statement there may be a DIFFERENT number inside that window, and
then the round trip does not abstain -- it confirms the wrong value with a source box that
honestly points at the wrong number. That failure mode has never been tested. This script
tests it, on the publishers' own bytes.

WHAT IS DIFFERENT HERE
----------------------
* The PDFs in `testdata/external_raw/` were downloaded unmodified from the publishers.
  We did not re-render, re-typeset or re-key them. `testdata/external_truth.json` records
  each source URL.
* Ground truth was transcribed by a human reading page images, and saved BEFORE this
  script was run for the first time. The ordering matters: truth written after seeing the
  output is not truth, it is a transcript.
* This script counts a class of error that `scripts/measure_label_mapping.py` STRUCTURALLY
  CANNOT SEE. That script loops over `intended_fields` -- fields we assert are present. A
  value invented for a field that does not exist on the page is never looked at, because
  the field is not in the loop. Two of the six documents here are BLANK FORMS, where the
  only possible error is exactly that invention. `expect_absent` fields are scored: a
  concrete value for one is a WRONG value, not an abstain.

    python scripts/measure_external_holdout.py
    python scripts/measure_external_holdout.py --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

from core import extract as ex  # noqa: E402
from score_extraction import normalize  # type: ignore  # noqa: E402

TRUTH = ROOT / "testdata" / "external_truth.json"
RAW_DIR = ROOT / "testdata" / "external_raw"


def _tally(fallback_mapper: Any) -> dict[str, Any]:
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    correct = wrong = abstained = 0
    wrong_detail: list[dict[str, Any]] = []
    per_doc: list[dict[str, Any]] = []
    provenance: dict[str, int] = {}

    for doc in truth["documents"]:
        path = RAW_DIR / doc["file_name"]
        if not path.exists():
            continue
        mapper = (
            ex.tracking_layered_mapper(doc["document_type"])
            if fallback_mapper is ex.layered_mapper
            else fallback_mapper
        )
        view = ex.extract_document(
            path,
            document_type=doc["document_type"],
            fallback_mapper=mapper,
        )
        got = {f["field"]: f for f in view["fields"]}
        d_correct = d_wrong = d_abstain = 0

        # Fields the page really does carry.
        for name, expected in doc.get("expected", {}).items():
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                abstained += 1
                d_abstain += 1
                continue
            if normalize(name, expected) == normalize(name, field["value"]):
                correct += 1
                d_correct += 1
                note = field.get("notes") or ""
                key = (
                    "model mapper"
                    if ex.MODEL_MAPPER_NOTE in note
                    else "synonym table"
                    if ex.SYNONYM_NOTE in note
                    else "canonical label"
                )
                provenance[key] = provenance.get(key, 0) + 1
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

        # Fields the page does NOT carry. Any concrete answer is a false positive.
        for name in doc.get("expect_absent", []):
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
                "correct": d_correct,
                "abstained": d_abstain,
                "wrong": d_wrong,
                "has_text_layer": any(
                    f.get("certainty") != "abstain"
                    or "no text layer" not in (f.get("notes") or "")
                    for f in view["fields"]
                ),
            }
        )

    total = correct + wrong + abstained
    return {
        "documents": len(per_doc),
        "fields_total": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "rate": None if total == 0 else round(100.0 * correct / total, 1),
        "per_document": per_doc,
        "wrong_detail": wrong_detail,
        "recovered_via": provenance,
    }


def measure(configs: tuple[str, ...]) -> dict[str, Any]:
    from core import label_llm

    out: dict[str, Any] = {"model_mapper_enabled": label_llm.is_enabled()}
    if "deterministic" in configs:
        out["deterministic"] = _tally(ex.synonym_mapper)
    if "with_mapper" in configs:
        # NOTE: on these documents the layered mapper issues one network call per
        # unrecognised label, and a blank government form carries hundreds of them. The
        # run takes minutes, which is why it is opt-in rather than always-on.
        out["with_mapper"] = _tally(ex.layered_mapper)
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--config",
        choices=("deterministic", "with_mapper", "both"),
        default="deterministic",
        help="which mapper configuration to score (default: deterministic, which is the "
        "one that must reproduce offline)",
    )
    args = parser.parse_args(argv)

    configs = ("deterministic", "with_mapper") if args.config == "both" else (args.config,)
    report = measure(configs)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0

    primary = configs[0]
    print("=" * 78)
    print("external hold-out -- real published PDFs, geometry we did not draw")
    print("=" * 78)
    for config in configs:
        cell = report[config]
        print(
            f"{config:<16}{cell['rate']:>6.1f}%  correct {cell['correct']:>3}  "
            f"abstain {cell['abstained']:>3}  WRONG {cell['wrong']:>3}   "
            f"(of {cell['fields_total']} fields, {cell['documents']} docs)"
        )
    print("-" * 78)
    for row in report[primary]["per_document"]:
        print(
            f"  {row['file']:<18} correct {row['correct']:>2}  "
            f"abstain {row['abstained']:>2}  wrong {row['wrong']:>2}"
        )

    bad = report[primary]["wrong_detail"]
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
