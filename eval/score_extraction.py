#!/usr/bin/env python3
"""RealDoor extraction scorer — compares DocumentView predictions against the pack gold.

CONTRACT: see contracts/CONTRACTS.md sections 2 (ExtractedField) and 3 (DocumentView).
GOLD:     pack/synthetic_documents/gold/document_gold.jsonl (24 records, 159 fields).

Design rules this file obeys
----------------------------
1. An ABSTENTION IS NOT A WRONG ANSWER. A predicted field with ``certainty == "abstain"``
   is counted in its own bucket and never in ``wrong``. Two accuracies are reported:
     - accuracy_incl_abstentions = exact_match / gold_fields_total   (how much we got right
       out of everything that existed)
     - selective_accuracy        = exact_match / attempted           (how right we were when
       we chose to answer; ``attempted = exact_match + wrong``)
     - coverage                  = attempted / gold_fields_total
   Reporting selective_accuracy alone would let a system abstain on everything and claim
   100%; reporting only accuracy_incl_abstentions would punish honest abstention. Both are
   printed together, always.
2. Every reported number is traceable. The report carries a ``traceability`` block that
   lists the exact (document_id, field, ordinal) keys behind every non-exact bucket, plus
   the sha256 of the gold file the numbers came from.
3. Matching is deliberately STRICT. See NORMALISATION RULES below; leniency we did not
   implement is listed explicitly, because silently lenient matching inflates our own score.

NORMALISATION RULES (implemented in ``normalize(field, value)``)
---------------------------------------------------------------
Each field name is mapped to a kind by ``FIELD_KINDS`` (a static table derived from the 20
field names present in the gold file). Unknown field names fall back to inference from the
Python type of the value.

  kind "number"  — hourly_rate, regular_hours, weekly_hours, gross_pay, net_pay,
                   household_size, monthly_benefit, gross_receipts, platform_fees
      * accepts int, float, Decimal, or str
      * strips: leading/trailing whitespace, "$", ",", "_", NBSP, and a trailing "USD"
      * "(1,234.50)" is read as -1234.50 (accounting negative)
      * unicode minus U+2212 is read as "-"
      * compared as Decimal quantised to 2 decimal places, ROUND_HALF_UP
        => 2166, 2166.0, "2166.00", "$2,166.00" all match; 2166.004 matches 2166.00;
           2166.01 does NOT match 2166.00
      * a non-parsable string does NOT silently become a string comparison — it is
        returned as ("number", UNPARSABLE, original) and can only match an identical
        unparsable string. It never matches a real number.

  kind "date"    — pay_date, pay_period_start, pay_period_end, application_date,
                   document_date, statement_month
      * accepted input formats, normalised to ISO:
          YYYY-MM-DD, YYYY/MM/DD, YYYY-MM (month precision, kept as YYYY-MM),
          MM/DD/YYYY and M/D/YYYY  (US convention — see caveat),
          MM-DD-YYYY, "July 10, 2026", "Jul 10 2026", "10 July 2026"
      * CAVEAT: slash dates are read US-style (month first). The gold is ISO, so this
        convention is only exercised by predictions. A prediction of "07/10/2026" matches
        gold "2026-07-10"; a prediction of "10/07/2026" is read as 2026-10-07 and FAILS.
        We accept that risk rather than guess per value.
      * an unparsable date string is returned as ("date", UNPARSABLE, original) and can
        only match an identical unparsable string.

  kind "string"  — person_name, address, pay_frequency, benefit_frequency,
                   untrusted_instruction_text, and any unknown field holding a str
      * unicode NFKC normalisation
      * all whitespace runs (incl. newline/tab/NBSP) collapsed to a single space, then strip
      * casefold() (case-insensitive)
      * curly quotes/apostrophes folded to ASCII, en/em dash folded to "-"

  None / missing value
      * normalises to the NULL sentinel and matches only another NULL.

DELIBERATELY NOT IMPLEMENTED (would be lenient; each would inflate our score)
  * no fuzzy / edit-distance / token-overlap matching of any kind
  * no punctuation stripping in strings — "Boston, MA" != "Boston MA"
  * no synonym or hyphen folding — "bi-weekly" != "biweekly", "bi weekly" != "biweekly"
  * no name reordering — "North, Mara" != "Mara North"
  * no address abbreviation expansion — "14 Lantern Wy" != "14 Lantern Way"
  * no numeric tolerance beyond rounding to cents
  * no cross-field inference (a missing gross_pay is never recomputed from rate * hours)

BBOX LOCALISATION
  * Boxes are [x0, y0, x1, y1] in PDF points, bottom-left origin (gold's own coordinate
    system, per CONTRACTS section 2). Corner order is normalised via min/max, so a box
    given as [x1, y1, x0, y0] is accepted.
  * IoU is computed only for gold fields that received a non-abstaining prediction carrying
    a bbox. A prediction on the WRONG PAGE scores IoU 0.0 (it is not skipped).
  * Reported: bbox_evaluated, bbox_iou_gt_0_5 (strictly > 0.5), bbox_iou_mean.
    Fields with no predicted bbox are counted in bbox_no_box, never as a pass.

USAGE
  python eval/score_extraction.py --self-check          # gold scored against itself
  python eval/score_extraction.py --pred preds.jsonl    # one DocumentView JSON per line
  python eval/score_extraction.py --pred preds.json     # or a JSON list of DocumentViews
  python eval/score_extraction.py --self-check --out r.json
  python eval/score_extraction.py --rules               # print the normalisation rules
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_PATH = REPO_ROOT / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"

# --- sentinels ---------------------------------------------------------------------
NULL = ("null",)
UNPARSABLE = "<unparsable>"

# --- static field kind table (derived from the 20 field names in the gold file) ------
FIELD_KINDS: dict[str, str] = {
    "person_name": "string",
    "address": "string",
    "pay_frequency": "string",
    "benefit_frequency": "string",
    "untrusted_instruction_text": "string",
    "household_size": "number",
    "regular_hours": "number",
    "weekly_hours": "number",
    "hourly_rate": "number",
    "gross_pay": "number",
    "net_pay": "number",
    "monthly_benefit": "number",
    "gross_receipts": "number",
    "platform_fees": "number",
    "pay_date": "date",
    "pay_period_start": "date",
    "pay_period_end": "date",
    "application_date": "date",
    "document_date": "date",
    "statement_month": "date",
}

ABSTAIN = "abstain"  # CONTRACTS section 1, Certainty enum

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ]
    )
}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})

_WS_RE = re.compile(r"\s+", re.UNICODE)
_QUOTE_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-",
}


# =====================================================================================
# normalisation
# =====================================================================================
def field_kind(field: str, value: Any = None) -> str:
    """Kind for a field name; falls back to the value's Python type for unknown fields."""
    if field in FIELD_KINDS:
        return FIELD_KINDS[field]
    if isinstance(value, bool):
        return "string"
    if isinstance(value, (int, float, Decimal)):
        return "number"
    return "string"


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    for bad, good in _QUOTE_MAP.items():
        text = text.replace(bad, good)
    return _WS_RE.sub(" ", text).strip()


def _as_number(value: Any) -> tuple:
    if isinstance(value, bool):
        return ("number", UNPARSABLE, str(value))
    if isinstance(value, (int, float, Decimal)):
        dec = Decimal(str(value))
    else:
        raw = _fold(str(value))
        cleaned = raw.replace("$", "").replace(",", "").replace("_", "")
        cleaned = cleaned.replace(" ", "").strip()
        if cleaned.upper().endswith("USD"):
            cleaned = cleaned[:-3].strip()
        negative = False
        if cleaned.startswith("(") and cleaned.endswith(")"):
            negative, cleaned = True, cleaned[1:-1].strip()
        cleaned = cleaned.replace(" ", "")
        try:
            dec = Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return ("number", UNPARSABLE, raw.casefold())
        if negative:
            dec = -dec
    return ("number", str(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)))


def _as_date(value: Any) -> tuple:
    raw = _fold(str(value))
    text = raw.replace(",", " ")
    text = _WS_RE.sub(" ", text).strip()

    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return _iso(y, mo, d, raw)
    m = re.fullmatch(r"(\d{4})[-/](\d{1,2})", text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return ("date", f"{y:04d}-{mo:02d}")
        return ("date", UNPARSABLE, raw.casefold())
    m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", text)  # US: month first
    if m:
        mo, d, y = (int(g) for g in m.groups())
        return _iso(y, mo, d, raw)
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{4})", text)  # July 10 2026
    if m and m.group(1).casefold() in _MONTHS:
        return _iso(int(m.group(3)), _MONTHS[m.group(1).casefold()], int(m.group(2)), raw)
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)  # 10 July 2026
    if m and m.group(2).casefold() in _MONTHS:
        return _iso(int(m.group(3)), _MONTHS[m.group(2).casefold()], int(m.group(1)), raw)
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", text)  # July 2026
    if m and m.group(1).casefold() in _MONTHS:
        return ("date", f"{int(m.group(2)):04d}-{_MONTHS[m.group(1).casefold()]:02d}")
    return ("date", UNPARSABLE, raw.casefold())


def _iso(year: int, month: int, day: int, raw: str) -> tuple:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ("date", UNPARSABLE, raw.casefold())
    return ("date", f"{year:04d}-{month:02d}-{day:02d}")


def normalize(field: str, value: Any) -> tuple:
    """Type-aware normalisation. Returns a hashable tuple; equality == a match.

    Rules are documented in this module's docstring and printed by ``--rules``.
    """
    if value is None:
        return NULL
    kind = field_kind(field, value)
    if kind == "number":
        return _as_number(value)
    if kind == "date":
        return _as_date(value)
    return ("string", _fold(str(value)).casefold())


# =====================================================================================
# bbox
# =====================================================================================
def _rect(box: Iterable[float]) -> tuple[float, float, float, float] | None:
    try:
        x0, y0, x1, y1 = (float(v) for v in list(box)[:4])
    except (TypeError, ValueError):
        return None
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def iou(box_a: Iterable[float] | None, box_b: Iterable[float] | None) -> float:
    """Intersection-over-union of two [x0,y0,x1,y1] boxes. 0.0 if either is unusable."""
    a, b = (_rect(box_a) if box_a else None), (_rect(box_b) if box_b else None)
    if a is None or b is None:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    if union <= 0.0:
        return 0.0
    return inter / union


# =====================================================================================
# loading
# =====================================================================================
def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return records


def load_predictions(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise SystemExit(f"{path}: expected a JSON list of DocumentView objects")
        return data
    return load_jsonl(path)


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gold_as_predictions(gold: list[dict]) -> list[dict]:
    """Turn gold records into DocumentView predictions — the self-check instrument.

    Gold field objects carry no ``certainty``/``evidence_kind`` (see
    eval/CONTRACT_CONFLICTS.md #2), so we stamp the CONTRACTS section 1 values that mean
    "we answered and we are sure". Nothing else about the record is altered.
    """
    out = []
    for record in gold:
        fields = []
        for field in record["fields"]:
            item = dict(field)
            item["certainty"] = "high"
            item["evidence_kind"] = "extracted"
            fields.append(item)
        out.append(
            {
                "document_id": record["document_id"],
                "household_id": record["household_id"],
                "document_type": record["document_type"],
                "file_name": record["file_name"],
                "page_count": record.get("page_count"),
                "page_size_points": record.get("page_size_points"),
                "fields": fields,
            }
        )
    return out


# =====================================================================================
# scoring
# =====================================================================================
def _keyed(fields: list[dict]) -> dict[tuple[str, int], dict]:
    """Key fields by (field_name, ordinal) so repeated field names stay distinguishable."""
    seen: dict[str, int] = defaultdict(int)
    keyed = {}
    for field in fields:
        name = field.get("field")
        keyed[(name, seen[name])] = field
        seen[name] += 1
    return keyed


def score(predictions: list[dict], gold: list[dict]) -> dict:
    """Score DocumentView predictions against gold records. Pure function."""
    pred_by_doc = {p.get("document_id"): p for p in predictions}

    buckets = ("exact_match", "wrong", "abstained", "missed")
    overall = {b: 0 for b in buckets}
    per_field: dict[str, dict[str, int]] = defaultdict(lambda: {b: 0 for b in buckets})
    per_doc: dict[str, dict[str, int]] = defaultdict(lambda: {b: 0 for b in buckets})

    bbox_eval = 0
    bbox_pass = 0
    bbox_no_box = 0
    bbox_iou_sum = 0.0
    trace: dict[str, list] = {"wrong": [], "abstained": [], "missed": [], "bbox_iou_le_0_5": []}
    unexpected: list[dict] = []
    documents_missing: list[str] = []

    for record in sorted(gold, key=lambda r: r["document_id"]):
        doc_id = record["document_id"]
        prediction = pred_by_doc.get(doc_id)
        if prediction is None:
            documents_missing.append(doc_id)
        pred_fields = _keyed(prediction.get("fields", []) if prediction else [])
        gold_fields = _keyed(record["fields"])

        for key in sorted(gold_fields, key=lambda k: (k[0], k[1])):
            name, ordinal = key
            gold_field = gold_fields[key]
            ref = {"document_id": doc_id, "field": name, "ordinal": ordinal}
            pred_field = pred_fields.get(key)

            if pred_field is None:
                bucket = "missed"
                trace["missed"].append(dict(ref, gold_value=gold_field.get("value")))
            elif pred_field.get("certainty") == ABSTAIN:
                bucket = "abstained"
                trace["abstained"].append(
                    dict(ref, gold_value=gold_field.get("value"),
                         notes=pred_field.get("notes"))
                )
            else:
                gold_norm = normalize(name, gold_field.get("value"))
                pred_norm = normalize(name, pred_field.get("value"))
                if gold_norm == pred_norm:
                    bucket = "exact_match"
                else:
                    bucket = "wrong"
                    trace["wrong"].append(
                        dict(ref, gold_value=gold_field.get("value"),
                             predicted_value=pred_field.get("value"),
                             gold_normalized=list(gold_norm),
                             predicted_normalized=list(pred_norm))
                    )

            overall[bucket] += 1
            per_field[name][bucket] += 1
            per_doc[doc_id][bucket] += 1

            # bbox localisation: only for fields we actually answered
            if pred_field is not None and pred_field.get("certainty") != ABSTAIN:
                if pred_field.get("bbox") is None:
                    bbox_no_box += 1
                else:
                    value = 0.0
                    if pred_field.get("page") == gold_field.get("page"):
                        value = iou(pred_field.get("bbox"), gold_field.get("bbox"))
                    bbox_eval += 1
                    bbox_iou_sum += value
                    if value > 0.5:
                        bbox_pass += 1
                    else:
                        trace["bbox_iou_le_0_5"].append(
                            dict(ref, iou=round(value, 6),
                                 gold_page=gold_field.get("page"),
                                 predicted_page=pred_field.get("page"),
                                 gold_bbox=gold_field.get("bbox"),
                                 predicted_bbox=pred_field.get("bbox"))
                        )

        for key in sorted(set(pred_fields) - set(gold_fields), key=lambda k: (k[0], k[1])):
            unexpected.append(
                {"document_id": doc_id, "field": key[0], "ordinal": key[1],
                 "predicted_value": pred_fields[key].get("value")}
            )

    for prediction in predictions:
        if prediction.get("document_id") not in {r["document_id"] for r in gold}:
            unexpected.append(
                {"document_id": prediction.get("document_id"), "field": None,
                 "ordinal": None, "predicted_value": "<document not in gold>"}
            )

    total = sum(overall.values())
    attempted = overall["exact_match"] + overall["wrong"]

    def ratio(num: int, den: int):
        return None if den == 0 else round(num / den, 6)

    report = {
        "gold_file": str(GOLD_PATH.relative_to(REPO_ROOT)).replace("\\", "/"),
        "gold_sha256": sha256_of(GOLD_PATH),
        "documents_in_gold": len(gold),
        "documents_predicted": len([p for p in predictions if p.get("document_id")]),
        "documents_with_no_prediction": documents_missing,
        "fields_total": total,
        "exact_match": overall["exact_match"],
        "wrong": overall["wrong"],
        "abstained": overall["abstained"],
        "missed": overall["missed"],
        "attempted": attempted,
        "accuracy_incl_abstentions": ratio(overall["exact_match"], total),
        "selective_accuracy": ratio(overall["exact_match"], attempted),
        "coverage": ratio(attempted, total),
        "abstention_rate": ratio(overall["abstained"], total),
        "miss_rate": ratio(overall["missed"], total),
        "bbox": {
            "evaluated": bbox_eval,
            "iou_gt_0_5": bbox_pass,
            "iou_gt_0_5_fraction": ratio(bbox_pass, bbox_eval),
            "iou_mean": None if bbox_eval == 0 else round(bbox_iou_sum / bbox_eval, 6),
            "answered_without_bbox": bbox_no_box,
            "iou_threshold": 0.5,
        },
        "by_field": {},
        "by_document": {},
        "unexpected_predicted_fields": unexpected,
        "traceability": trace,
    }

    for name in sorted(per_field):
        counts = per_field[name]
        sub_total = sum(counts.values())
        sub_attempted = counts["exact_match"] + counts["wrong"]
        report["by_field"][name] = {
            "kind": field_kind(name),
            "fields_total": sub_total,
            **counts,
            "accuracy_incl_abstentions": ratio(counts["exact_match"], sub_total),
            "selective_accuracy": ratio(counts["exact_match"], sub_attempted),
            "coverage": ratio(sub_attempted, sub_total),
        }
    for doc_id in sorted(per_doc):
        counts = per_doc[doc_id]
        report["by_document"][doc_id] = dict(counts, fields_total=sum(counts.values()))
    return report


def self_check() -> tuple[dict, list[str]]:
    """Score the gold file against itself. Returns (report, list_of_problems)."""
    gold = load_jsonl(GOLD_PATH)
    report = score(gold_as_predictions(gold), gold)
    problems = []
    if report["fields_total"] != report["exact_match"]:
        problems.append(
            f"exact_match {report['exact_match']} != fields_total {report['fields_total']}"
        )
    for key in ("wrong", "abstained", "missed"):
        if report[key] != 0:
            problems.append(f"{key} == {report[key]}, expected 0")
    if report["accuracy_incl_abstentions"] != 1.0:
        problems.append(f"accuracy {report['accuracy_incl_abstentions']} != 1.0")
    if report["selective_accuracy"] != 1.0:
        problems.append(f"selective_accuracy {report['selective_accuracy']} != 1.0")
    if report["coverage"] != 1.0:
        problems.append(f"coverage {report['coverage']} != 1.0")
    if report["bbox"]["iou_mean"] != 1.0:
        problems.append(f"bbox iou_mean {report['bbox']['iou_mean']} != 1.0")
    if report["bbox"]["iou_gt_0_5_fraction"] != 1.0:
        problems.append(f"bbox pass fraction {report['bbox']['iou_gt_0_5_fraction']} != 1.0")
    if report["bbox"]["evaluated"] != report["fields_total"]:
        problems.append("not every gold field carried a bbox")
    if report["unexpected_predicted_fields"]:
        problems.append("self-check produced unexpected fields")
    return report, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pred", type=Path, help="DocumentView predictions (.jsonl or .json)")
    parser.add_argument("--self-check", action="store_true",
                        help="score the gold file against itself (instrument calibration)")
    parser.add_argument("--rules", action="store_true", help="print normalisation rules and exit")
    parser.add_argument("--out", type=Path, help="also write the JSON report here")
    args = parser.parse_args(argv)

    if args.rules:
        print(__doc__)
        return 0
    if not args.pred and not args.self_check:
        parser.error("give --pred PATH or --self-check")

    if args.self_check:
        report, problems = self_check()
        report["mode"] = "self_check"
        report["self_check_ok"] = not problems
        report["self_check_problems"] = problems
    else:
        gold = load_jsonl(GOLD_PATH)
        report = score(load_predictions(args.pred), gold)
        report["mode"] = "predictions"
        report["predictions_file"] = str(args.pred)
        problems = []

    text = json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
