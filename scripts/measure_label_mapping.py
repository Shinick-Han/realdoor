# -*- coding: utf-8 -*-
"""
measure_label_mapping.py -- how much of a document's labels can we actually name?

This script exists because of a specific way we nearly fooled ourselves.

`core.extract.LABEL_SYNONYMS` is a hand-written table, and the documents it was first
measured against (`up_016`, `up_017`, `up_018` in `scripts/make_testdata.py`) were also
written by hand, by us, in the same week. Every label string those documents use is in
the table. The label-wording cohort therefore reads 100%, and that 100% is not a
measurement -- it is the table being asked to recite itself. A reader who opens the two
files side by side sees it immediately, and is then entitled to distrust every other
number we quote.

So this script reports the same statistic over TWO sets:

  * `testdata/uploads_manifest.json`     -- the original 26, ours, table-contaminated.
  * `testdata/holdout_manifest.json`     -- labels transcribed from real payroll and
                                            verification documents BEFORE anyone opened
                                            `LABEL_SYNONYMS`. See `scripts/make_holdout.py`
                                            for the provenance of every string.

and under TWO mapper configurations:

  * deterministic  -- `LABEL_MAP` + `LABEL_SYNONYMS`, no model, no network. This column
                      must reproduce byte-for-byte on a judge's offline machine.
  * with mapper    -- the above, plus `core.label_llm.model_mapper` for labels the two
                      tables missed. Needs `OPENAI_API_KEY`; degrades to the
                      deterministic column when absent.

The number that matters most is not the recovery rate. It is `wrong`, which must be 0 in
every cell. A label mapper that renames a field wrongly produces a confident bad figure
where we used to produce an honest blank, and that trade is never worth making.

    python scripts/measure_label_mapping.py
    python scripts/measure_label_mapping.py --json
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

SETS = (
    ("existing 26", ROOT / "testdata" / "uploads_manifest.json", ROOT / "testdata" / "uploads"),
    ("hold-out", ROOT / "testdata" / "holdout_manifest.json", ROOT / "testdata" / "holdout"),
)


def _tally(
    manifest_path: Path,
    doc_dir: Path,
    fallback_mapper: Any,
    cohort: str | None,
) -> dict[str, Any]:
    """Score every document in one manifest under one mapper configuration."""
    if not manifest_path.exists():
        return {"missing": True}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    docs = [
        d
        for d in manifest["documents"]
        if not d.get("rasterized")  # OCR path is a different argument; text layer only
        # Prefix match, so `--cohort label_wording` selects the original cohort in one
        # manifest and `label_wording_holdout` in the other -- the apples-to-apples
        # comparison this script exists to make.
        and (cohort is None or str(d.get("cohort", "")).startswith(cohort))
    ]

    correct = wrong = abstained = 0
    wrong_detail: list[dict[str, Any]] = []
    provenance: dict[str, int] = {}

    for doc in docs:
        path = doc_dir / doc["file_name"]
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
        for name, expected in doc["intended_fields"].items():
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                abstained += 1
                continue
            if normalize(name, expected) == normalize(name, field["value"]):
                correct += 1
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
                wrong_detail.append(
                    {
                        "file": doc["file_name"],
                        "field": name,
                        "expected": expected,
                        "got": field["value"],
                        "notes": field.get("notes"),
                    }
                )

    total = correct + wrong + abstained
    return {
        "documents": len(docs),
        "fields_total": total,
        "correct": correct,
        "wrong": wrong,
        "abstained": abstained,
        "rate": None if total == 0 else round(100.0 * correct / total, 1),
        "wrong_detail": wrong_detail,
        "recovered_via": provenance,
    }


def measure(cohort: str | None = None) -> dict[str, Any]:
    from core import label_llm

    out: dict[str, Any] = {
        "model_mapper_enabled": label_llm.is_enabled(),
        "sets": {},
    }
    for name, manifest_path, doc_dir in SETS:
        out["sets"][name] = {
            "deterministic": _tally(manifest_path, doc_dir, ex.synonym_mapper, cohort),
            "with_mapper": _tally(manifest_path, doc_dir, ex.layered_mapper, cohort),
        }
    out["mapper_stats"] = label_llm.stats()
    return out


def _cell(result: dict[str, Any]) -> str:
    if result.get("missing"):
        return "   (no manifest)   "
    if result["rate"] is None:
        return "   (no documents)  "
    flag = "" if result["wrong"] == 0 else f"  !! WRONG {result['wrong']}"
    return f"{result['rate']:>5.1f}%  ({result['correct']}/{result['fields_total']}){flag}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--cohort",
        default=None,
        help="restrict to one manifest cohort (e.g. label_wording); default is every "
        "text-layer document in the manifest",
    )
    args = parser.parse_args(argv)

    report = measure(args.cohort)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    print("=" * 74)
    print("label mapping -- fields recovered, by document set and mapper configuration")
    if args.cohort:
        print(f"cohort filter: {args.cohort}")
    print("=" * 74)
    print(f"{'set':<16}{'deterministic only':<30}{'with model mapper':<30}")
    print("-" * 74)
    for name, _, _ in SETS:
        row = report["sets"][name]
        print(f"{name:<16}{_cell(row['deterministic']):<30}{_cell(row['with_mapper']):<30}")
    print("-" * 74)

    enabled = report["model_mapper_enabled"]
    print(f"model mapper enabled: {enabled}")
    if not enabled:
        print("  (no key / offline / under pytest -- the two columns are identical by design)")

    for name, _, _ in SETS:
        for config in ("deterministic", "with_mapper"):
            cell = report["sets"][name][config]
            if cell.get("missing"):
                continue
            if cell["recovered_via"]:
                via = "  ".join(f"{k}={v}" for k, v in sorted(cell["recovered_via"].items()))
                print(f"  {name} / {config}: {via}")

    bad = [
        (name, config, d)
        for name, _, _ in SETS
        for config in ("deterministic", "with_mapper")
        for d in report["sets"][name][config].get("wrong_detail", [])
    ]
    if bad:
        print("\nWRONG ANSWERS -- every one of these is a regression, not a trade-off:")
        for name, config, d in bad:
            print(f"  [{name}/{config}] {d['file']} {d['field']}: "
                  f"expected {d['expected']!r}, got {d['got']!r}")
        return 1
    print("\nwrong answers: 0 in every cell")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
