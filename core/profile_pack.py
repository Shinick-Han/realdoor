"""One-shot inventory of the organizer's synthetic document pack.

Facts only. This script does not evaluate our extractor -- it describes what is actually
in the pack, including the parts that are inconvenient for us. Anything it flags as an
anomaly is a real constraint on what any extractor can achieve, and should be read before
anyone claims a number.

Usage: python core/profile_pack.py [--pack PATH]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber  # noqa: E402

from core.extract import WATERMARK_MIN_SIZE, read_words  # noqa: E402

DEFAULT_PACK = Path(__file__).resolve().parent.parent / "pack" / "synthetic_documents"


def load_gold(gold_path: Path) -> list[dict[str, Any]]:
    with gold_path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def describe_format(value: Any) -> str:
    """A coarse shape label for a value, so format drift is visible at a glance."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10 and text[4] == "-" and text[7] == "-" and text[:4].isdigit():
            return "date YYYY-MM-DD"
        if len(text) == 7 and text[4] == "-" and text[:4].isdigit():
            return "month YYYY-MM"
        if text.startswith("$"):
            return "currency string"
        return f"str(len {len(text)})"
    if value is None:
        return "null"
    return type(value).__name__


def probe_pdf(pdf_path: Path) -> dict[str, Any]:
    """What pdfplumber can actually see in one file."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        raw_words = page.extract_words(extra_attrs=["size"])
        body_words = read_words(page, 1)
        watermark = [w for w in raw_words if float(w.get("size", 0) or 0) >= WATERMARK_MIN_SIZE]
        return {
            "page_count": len(pdf.pages),
            "page_sizes": sorted({(round(p.width, 1), round(p.height, 1)) for p in pdf.pages}),
            "raw_words": len(raw_words),
            "body_words": len(body_words),
            "watermark_glyphs": len(watermark),
            "images": len(page.images),
            "has_text_layer": bool(body_words),
        }


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    args = parser.parse_args(argv[1:])

    documents_dir = args.pack / "documents"
    gold_path = args.pack / "gold" / "document_gold.jsonl"
    manifest_path = args.pack / "gold" / "document_manifest.csv"

    if not gold_path.exists():
        print(f"gold file not found: {gold_path}", file=sys.stderr)
        return 2

    gold = load_gold(gold_path)
    pdfs = sorted(documents_dir.glob("*.pdf"))
    probes = {path.name: probe_pdf(path) for path in pdfs}

    print("=" * 78)
    print("REALDOOR SYNTHETIC DOCUMENT PACK -- INVENTORY")
    print("=" * 78)
    print(f"pack root     : {args.pack}")
    print(f"pdf files     : {len(pdfs)}")
    print(f"gold records  : {len(gold)}")
    print(f"manifest      : {'present' if manifest_path.exists() else 'MISSING'}")

    # ---------------------------------------------------------------- by type
    section("DOCUMENTS BY TYPE")
    by_type: dict[str, list[dict]] = collections.defaultdict(list)
    for row in gold:
        by_type[row["document_type"]].append(row)
    print(f"{'document_type':<22}{'docs':>6}{'raster':>8}{'adversarial':>13}{'gold fields':>13}")
    for doc_type, rows in sorted(by_type.items()):
        raster = sum(1 for r in rows if r.get("rasterized"))
        adversarial = sum(1 for r in rows if r.get("contains_adversarial_text"))
        fields = sum(len(r["fields"]) for r in rows)
        print(f"{doc_type:<22}{len(rows):>6}{raster:>8}{adversarial:>13}{fields:>13}")
    total_raster = sum(1 for r in gold if r.get("rasterized"))
    print(
        f"{'TOTAL':<22}{len(gold):>6}{total_raster:>8}"
        f"{sum(1 for r in gold if r.get('contains_adversarial_text')):>13}"
        f"{sum(len(r['fields']) for r in gold):>13}"
    )

    # ------------------------------------------------------------ field names
    section("GOLD FIELD NAMES BY DOCUMENT TYPE")
    for doc_type, rows in sorted(by_type.items()):
        counts = collections.Counter(f["field"] for r in rows for f in r["fields"])
        print(f"\n  {doc_type}  ({len(rows)} documents)")
        for name, count in sorted(counts.items()):
            marker = "" if count == len(rows) else f"   <-- only on {count}/{len(rows)}"
            print(f"    {name:<30}{count:>3}{marker}")

    # ---------------------------------------------------------- value formats
    section("VALUE FORMATS OBSERVED (per field, across all documents)")
    formats: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    samples: dict[str, list] = collections.defaultdict(list)
    for row in gold:
        for item in row["fields"]:
            formats[item["field"]][describe_format(item["value"])] += 1
            if len(samples[item["field"]]) < 3:
                samples[item["field"]].append(item["value"])
    print(f"{'field':<30}{'n':>4}  {'formats':<28}examples")
    for name in sorted(formats):
        shape = ", ".join(f"{k} x{v}" for k, v in formats[name].most_common())
        example = ", ".join(repr(v)[:22] for v in samples[name])
        print(f"{name:<30}{sum(formats[name].values()):>4}  {shape:<28}{example}")

    # ------------------------------------------------------------- page sizes
    section("PAGE GEOMETRY")
    sizes = collections.Counter(
        tuple(row["page_size_points"]) for row in gold if row.get("page_size_points")
    )
    for size, count in sizes.most_common():
        print(f"  gold says {size[0]} x {size[1]} points  ({count} documents)")
    observed = collections.Counter(
        tuple(probe["page_sizes"][0]) for probe in probes.values() if probe["page_sizes"]
    )
    for size, count in observed.most_common():
        print(f"  pdfplumber reads {size[0]} x {size[1]} points  ({count} documents)")
    page_counts = collections.Counter(probe["page_count"] for probe in probes.values())
    print(f"  page counts: {dict(page_counts)}")

    # ------------------------------------------------------------ text layers
    section("TEXT LAYER REALITY (what pdfplumber can actually read)")
    print(f"{'file':<44}{'raster':>8}{'body':>7}{'wmark':>7}{'img':>5}  text layer")
    no_text = []
    for row in gold:
        probe = probes.get(row["file_name"])
        if probe is None:
            print(f"{row['file_name']:<44}   MISSING PDF FOR GOLD RECORD")
            continue
        if not probe["has_text_layer"]:
            no_text.append(row)
        print(
            f"{row['file_name']:<44}{str(row.get('rasterized')):>8}"
            f"{probe['body_words']:>7}{probe['watermark_glyphs']:>7}{probe['images']:>5}"
            f"  {'yes' if probe['has_text_layer'] else 'NO -- image only'}"
        )

    # -------------------------------------------------------------- anomalies
    section("ANOMALIES AND CONSTRAINTS")
    lost = sum(len(r["fields"]) for r in no_text)
    total_fields = sum(len(r["fields"]) for r in gold)
    print(
        f"1. {len(no_text)}/{len(gold)} documents have NO text layer at all "
        f"(0 extractable words, 1 embedded image each).\n"
        f"   The gold file still specifies {lost} fields for them "
        f"({lost / total_fields:.0%} of all {total_fields} gold fields).\n"
        f"   No text-based extractor can reach these. Without OCR they must abstain.\n"
        f"   Affected: {', '.join(r['document_id'] for r in no_text)}"
    )

    watermarked = sum(1 for p in probes.values() if p["watermark_glyphs"])
    print(
        f"\n2. {watermarked}/{len(probes)} documents carry a large diagonal watermark drawn as "
        f"individually placed glyphs.\n"
        f"   Left unfiltered it interleaves with body text and corrupts word grouping\n"
        f'   (pdfplumber reads "MAILING ADDRESS" as "MAILING AD DRESS"). It is the only\n'
        f"   text above {WATERMARK_MIN_SIZE:.0f}pt, so size is a clean discriminator."
    )

    adversarial = [r for r in gold if r.get("contains_adversarial_text")]
    print(
        f"\n3. {len(adversarial)} documents contain embedded prompt-injection text, captured in "
        f"gold as\n   the field 'untrusted_instruction_text': "
        f"{', '.join(r['document_id'] for r in adversarial)}\n"
        f"   It is a GOLD FIELD, i.e. the pack expects it extracted and quarantined, not\n"
        f"   dropped. Note it appears on pay stubs and a gig statement -- document types\n"
        f"   whose other 9 or 4 fields are unaffected by it."
    )

    month_only = [
        (r["document_id"], f["value"])
        for r in gold
        for f in r["fields"]
        if f["field"] == "statement_month"
    ]
    if month_only:
        print(
            f"\n4. statement_month is month-precise only {month_only}.\n"
            "   The gig statement therefore has NO day-precise date, so the frozen 60-day\n"
            "   currency window (CH-READINESS-001) cannot be applied to it without\n"
            "   inventing a day. We report state='unreadable' rather than assume freshness."
        )

    date_fields = {"application_date", "pay_date", "document_date"}
    stale = [
        (r["document_id"], f["field"], f["value"])
        for r in gold
        for f in r["fields"]
        if f["field"] in date_fields and str(f["value"]) < "2026-05-19"
    ]
    print(
        f"\n5. Documents dated outside the 60-day window (before 2026-05-19): "
        f"{stale if stale else 'none'}"
    )
    for doc_id, _, _ in stale:
        row = next(r for r in gold if r["document_id"] == doc_id)
        if row.get("rasterized"):
            print(
                f"   NOTE: {doc_id} is the only stale document AND it is rasterized, so the\n"
                f"   staleness path cannot be demonstrated on readable text from this pack alone."
            )

    heights = collections.Counter()
    for row in gold:
        for item in row["fields"]:
            x0, y0, x1, y1 = item["bbox"]
            heights[round(y1 - y0, 2)] += 1
    print(
        f"\n6. Gold boxes are drawn boxes, not glyph outlines. Heights observed: "
        f"{dict(heights)}\n"
        "   These are (font size + 4pt). Widths are max(24pt, glyph width + 4pt): a 24pt\n"
        "   minimum keeps one-character values clickable. An extractor emitting raw glyph\n"
        "   extents will look wrong against gold even when it found the right words."
    )

    ints = [
        (r["document_id"], f["field"], f["value"])
        for r in gold
        for f in r["fields"]
        if isinstance(f["value"], int) and not isinstance(f["value"], bool)
    ]
    money_ints = [t for t in ints if t[1] in {"monthly_benefit", "gross_receipts"}]
    print(
        f"\n7. Numeric typing in gold is inconsistent: gross_pay is float (2166.0) while\n"
        f"   monthly_benefit and gross_receipts are int {[(f, v) for _, f, v in money_ints]}.\n"
        "   Any scorer must compare numerically (850 == 850.0), not by JSON type."
    )

    gold_names = {row["file_name"] for row in gold}
    disk_names = {p.name for p in pdfs}
    if gold_names != disk_names:
        print(f"\n8. gold/disk mismatch: only in gold {gold_names - disk_names}, "
              f"only on disk {disk_names - gold_names}")
    else:
        print(f"\n8. gold records and PDF files correspond exactly ({len(pdfs)} each).")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
