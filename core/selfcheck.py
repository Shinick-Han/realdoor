"""Measure `core.extract` against the pack gold, and report the failures first.

This is the core stream's own instrumentation, kept deliberately separate from `eval/`,
which is an independent scorer owned by another stream. If the two disagree, `eval/` is
the one that counts and the disagreement is a finding.

The rule for reading this output: an abstention is a correct, designed outcome; a WRONG
value is the only real failure. They are counted separately and never merged, because a
single "accuracy" number would let a wrong value hide behind an honest abstention.

Usage: python core/selfcheck.py [--pack PATH] [--verbose]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extract import LineBoxConvention, extract_document, unmapped_labels  # noqa: E402

DEFAULT_PACK = Path(__file__).resolve().parent.parent / "pack" / "synthetic_documents"


def iou(a: Sequence[float] | None, b: Sequence[float] | None) -> float | None:
    """Intersection over union of two [x0, y0, x1, y1] boxes in the same coordinate space."""
    if a is None or b is None:
        return None
    ax0, ay0, ax1, ay1 = (float(v) for v in a)
    bx0, by0, bx1, by1 = (float(v) for v in b)
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union > 0 else 0.0


#: Date formats this comparison will read on either side. Deliberately the same list the
#: extractor parses (`core.extract._DATE_FORMATS`), not a superset: a scorer that understands
#: more spellings than the extractor produces would be measuring itself.
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y")


def _as_date(value: Any) -> date | None:
    """The date this value denotes, or None if it does not denote one."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def values_match(predicted: Any, gold: Any) -> bool:
    """Type-aware equality: compare dates as dates and numbers as numbers.

    A value and the truth it is checked against are two spellings of one fact, and the
    spelling is not the thing being measured. The gold's own number types are already
    inconsistent (850 vs 850.0), which is why the numeric leg has always been here; dates
    have exactly the same problem and had no leg at all. `2015-04-10` and `04/10/2015` are
    the same day, and the extractor normalises every date it reads to ISO while a truth file
    transcribed from a page render holds whatever the page printed. Comparing those as
    strings scores a correct reading as a miss.

    Measured before the rule was written, so that it is a rule rather than a fit: across the
    pack gold, the 26 upload fixtures and the 6 published PDFs, exactly four fields are
    scored differently by string and by type, and all four are the same date in two
    spellings -- ADP's pay date and both ends of its pay period, and UTEP's pay date.

    **It recovers nothing today**, and that is worth stating plainly rather than leaving to
    be discovered. This function's only caller is `summarize` below, which scores the pack,
    and the pack writes its dates ISO on both sides. All four affected fields live in the
    external hold-out, which is scored by `eval/score_extraction.normalize` -- already
    type-aware -- and therefore already counts them correct. What changes is that a latent
    trap is closed: the day a non-ISO date reaches this comparison it would otherwise report
    a correct extraction as a wrong value, which is the one error this repository most cares
    about not making, and it would be the *scorer* making it.

    Implemented here rather than imported from `eval/` on purpose. This module's own
    docstring keeps the two scorers independent so that a disagreement between them is a
    finding; sharing the comparator would delete the finding rather than resolve it.
    """
    if isinstance(predicted, bool) or isinstance(gold, bool):
        return predicted == gold
    if isinstance(predicted, (int, float)) and isinstance(gold, (int, float)):
        return abs(float(predicted) - float(gold)) < 1e-6
    predicted_date, gold_date = _as_date(predicted), _as_date(gold)
    if predicted_date is not None and gold_date is not None:
        return predicted_date == gold_date
    return str(predicted).strip() == str(gold).strip()


def summarize(pack: Path, convention: LineBoxConvention, verbose: bool) -> dict[str, Any]:
    gold_rows = [
        json.loads(line)
        for line in (pack / "gold" / "document_gold.jsonl").open(encoding="utf-8")
        if line.strip()
    ]

    stats = collections.Counter()
    ious: list[float] = []
    ious_by_field: dict[str, list[float]] = collections.defaultdict(list)
    wrong: list[tuple[str, str, Any, Any]] = []
    abstained_by_field: collections.Counter = collections.Counter()
    missed_by_field: collections.Counter = collections.Counter()
    docs_with_high: list[str] = []
    docs_without_high: list[str] = []
    unmapped: collections.Counter = collections.Counter()
    per_doc: list[dict[str, Any]] = []

    for row in gold_rows:
        pdf_path = pack / "documents" / row["file_name"]
        view = extract_document(pdf_path, convention=convention)
        predicted = {item["field"]: item for item in view["fields"]}

        doc_high = doc_low = doc_abstain = doc_wrong = 0
        for gold_field in row["fields"]:
            name = gold_field["field"]
            stats["gold_fields"] += 1
            item = predicted.get(name)
            if item is None or item["certainty"] == "abstain":
                stats["abstained"] += 1
                doc_abstain += 1
                abstained_by_field[name] += 1
                if item is None:
                    missed_by_field[name] += 1
                continue
            if values_match(item["value"], gold_field["value"]):
                stats["correct"] += 1
                score = iou(item["bbox"], gold_field["bbox"])
                if score is not None:
                    ious.append(score)
                    ious_by_field[name].append(score)
            else:
                stats["wrong"] += 1
                doc_wrong += 1
                wrong.append((row["document_id"], name, item["value"], gold_field["value"]))
            if item["certainty"] == "high":
                doc_high += 1
                stats["high"] += 1
            else:
                doc_low += 1
                stats["low"] += 1

        # Fields we emitted that gold does not list for this document.
        gold_names = {f["field"] for f in row["fields"]}
        for name, item in predicted.items():
            if name not in gold_names and item["certainty"] != "abstain":
                stats["extra"] += 1
                if verbose:
                    print(f"  extra field {row['document_id']}.{name} = {item['value']!r}")

        (docs_with_high if doc_high else docs_without_high).append(row["document_id"])
        per_doc.append(
            {
                "document_id": row["document_id"],
                "type": row["document_type"],
                "rasterized": row.get("rasterized"),
                "gold": len(row["fields"]),
                "high": doc_high,
                "low": doc_low,
                "abstain": doc_abstain,
                "wrong": doc_wrong,
                "state": view["state"],
                "document_date": view["document_date"],
                "days_until_stale": view["days_until_stale"],
            }
        )
        for label in unmapped_labels(pdf_path):
            unmapped[label] += 1

    return {
        "stats": stats,
        "ious": ious,
        "ious_by_field": ious_by_field,
        "wrong": wrong,
        "abstained_by_field": abstained_by_field,
        "missed_by_field": missed_by_field,
        "docs_with_high": docs_with_high,
        "docs_without_high": docs_without_high,
        "unmapped": unmapped,
        "per_doc": per_doc,
        "gold_rows": gold_rows,
    }


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv[1:])

    result = summarize(args.pack, LineBoxConvention(), args.verbose)
    raw = summarize(args.pack, LineBoxConvention.raw(), False)
    stats = result["stats"]

    print("=" * 78)
    print("CORE EXTRACTION SELF-CHECK (deterministic, no LLM, no network)")
    print("=" * 78)

    print("\nPER DOCUMENT")
    print(
        f"{'document':<14}{'type':<22}{'rast':>6}{'gold':>6}{'high':>6}{'low':>5}"
        f"{'abst':>6}{'wrong':>7}  {'state':<11}days"
    )
    for row in result["per_doc"]:
        days = "-" if row["days_until_stale"] is None else str(row["days_until_stale"])
        print(
            f"{row['document_id']:<14}{row['type']:<22}{str(row['rasterized'])[0]:>6}"
            f"{row['gold']:>6}{row['high']:>6}{row['low']:>5}{row['abstain']:>6}"
            f"{row['wrong']:>7}  {row['state']:<11}{days}"
        )

    total_docs = len(result["per_doc"])
    print("\nHEADLINE NUMBERS")
    print(f"  documents                                : {total_docs}")
    print(
        f"  documents with >=1 high-certainty field   : "
        f"{len(result['docs_with_high'])}/{total_docs}"
    )
    print(f"  documents with none                      : {len(result['docs_without_high'])}")
    if result["docs_without_high"]:
        print(f"      {', '.join(result['docs_without_high'])}")
    print(f"  gold fields                              : {stats['gold_fields']}")
    print(
        f"  correct values                           : {stats['correct']} "
        f"({stats['correct'] / stats['gold_fields']:.1%} of gold)"
    )
    print(f"  WRONG values                             : {stats['wrong']}")
    print(f"  abstained                                : {stats['abstained']}")
    print(f"  certainty=high                           : {stats['high']}")
    print(f"  certainty=low                            : {stats['low']}")
    print(f"  fields emitted beyond gold               : {stats['extra']}")
    attempted = stats["correct"] + stats["wrong"]
    if attempted:
        print(
            f"  precision on non-abstained               : "
            f"{stats['correct'] / attempted:.1%}  ({stats['correct']}/{attempted})"
        )

    print("\nBOUNDING BOX ACCURACY vs GOLD (correct values only)")
    ious = result["ious"]
    if ious:
        exact = sum(1 for v in ious if v >= 0.99)
        print(f"  boxes compared                           : {len(ious)}")
        print(f"  mean IoU (line-box convention)           : {mean(ious):.4f}")
        print(f"  min  IoU                                 : {min(ious):.4f}")
        print(f"  IoU >= 0.99                              : {exact}/{len(ious)}")
        print(f"  IoU >= 0.90                              : {sum(1 for v in ious if v >= 0.90)}")
        print(f"  IoU >= 0.50                              : {sum(1 for v in ious if v >= 0.50)}")
        print(
            f"  mean IoU (raw glyph extents, no pad)     : {mean(raw['ious']):.4f}"
            "   <- what you get without reproducing the fixture's box convention"
        )
        worst = sorted(
            ((name, mean(v)) for name, v in result["ious_by_field"].items()), key=lambda t: t[1]
        )[:5]
        print("  lowest-IoU fields:")
        for name, score in worst:
            print(f"      {name:<30}{score:.4f}")

    print("\nWHAT WE COULD NOT LOCATE (abstentions by field)")
    if result["abstained_by_field"]:
        for name, count in result["abstained_by_field"].most_common():
            reason = (
                "no text layer" if result["missed_by_field"][name] == 0 else "not found on page"
            )
            print(f"  {name:<30}{count:>4}   ({reason})")
    else:
        print("  none")

    print("\nWRONG VALUES (the only real failures)")
    if result["wrong"]:
        for doc_id, name, got, expected in result["wrong"]:
            print(f"  {doc_id}.{name}: got {got!r}, gold {expected!r}")
    else:
        print("  none")

    print("\nLABELS THE DETERMINISTIC MAPPER DID NOT RECOGNISE")
    print("(this is exactly what an optional LLM mapping step would be handed)")
    if result["unmapped"]:
        for label, count in result["unmapped"].most_common(20):
            print(f"  {label!r:<50}x{count}")
    else:
        print("  none -- every label on every page mapped to a known gold field name")

    print("\nDETERMINISM")
    first = extract_document(args.pack / "documents" / result["gold_rows"][0]["file_name"])
    second = extract_document(args.pack / "documents" / result["gold_rows"][0]["file_name"])
    identical = json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    print(f"  repeated extraction is byte-identical      : {identical}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
