# -*- coding: utf-8 -*-
"""it-001 firing predicate -- read-only, run by `run_phase.py p3 --iteration 1 --run`.

The proposed rule (loop/proposals/it-001.md section 4): in `core.extract.read_words`,
skip the watermark size filter on a page iff the page has at least one text char and
every char reports size >= WATERMARK_MIN_SIZE -- the filter would otherwise delete the
page's entire text layer, which refutes its own classification.

`fires(doc)` answers: would that rule change how this document is read? It fires on the
first page whose whole char set sits at or above the threshold. On firing it ALSO runs
the full extractor with the rule monkeypatched in (in-process only; nothing on disk
changes) and reports every field the extractor would then emit, so that `conflicts`
can join real would-be emissions -- not a hand-simulation of them -- against truth.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGET_DOC = "ca_dlse_paystub_hourly.pdf"

#: Mirrors core.extract.WATERMARK_MIN_SIZE. The rule adds no constant of its own; this
#: predicate must test the same bound the filter already applies.
WATERMARK_MIN_SIZE = 20.0


def _all_chars_at_or_above_threshold(page: Any) -> bool:
    chars = page.chars
    if not chars:
        return False  # a scan cannot fire: there is nothing the filter deletes
    return all(float(c.get("size", 0.0) or 0.0) >= WATERMARK_MIN_SIZE for c in chars)


def _emitted_with_rule(doc: dict) -> dict[str, Any]:
    """Every field the extractor would emit for this doc with the rule active.

    The rule is applied by monkeypatching `core.extract.read_words` in this process
    only: when the filtered page comes back empty and the raw char set is entirely at
    or above the threshold, the page is re-read unfiltered. This is the exact conduct
    the implementation will adopt, so the join below falsifies the rule, not a proxy.
    """
    import core.extract as ex

    original = ex.read_words

    def with_rule(page: Any, page_number: int):
        words = original(page, page_number)
        if not words and _all_chars_at_or_above_threshold(page):
            height = float(page.height)
            out = []
            for w in page.extract_words(
                extra_attrs=["size", "fontname"], use_text_flow=False, return_chars=True
            ):
                text = w["text"].strip()
                if not text or text.startswith("(cid:"):
                    continue
                cs = w.get("chars") or []
                baseline = float(cs[0]["matrix"][5]) if cs and cs[0].get("matrix") else None
                glyph_bottom = height - float(w["bottom"])
                out.append(
                    ex.Word(
                        text=text,
                        x0=float(w["x0"]),
                        x1=float(w["x1"]),
                        baseline=baseline if baseline is not None else glyph_bottom,
                        glyph_bottom=glyph_bottom,
                        glyph_top=height - float(w["top"]),
                        size=round(float(w["size"]), 2),
                        bold="Bold" in str(w.get("fontname", "")),
                        page=page_number,
                    )
                )
            return out
        return words

    ex.read_words = with_rule
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"])
    finally:
        ex.read_words = original

    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def fires(doc: dict) -> dict | None:
    import pdfplumber

    with pdfplumber.open(doc["path"]) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            if _all_chars_at_or_above_threshold(page):
                n = len(page.chars)
                sizes = [round(float(c.get("size", 0.0) or 0.0), 2) for c in page.chars]
                return {
                    "field": "(page reader -- the rule alters visibility, not one field)",
                    "value": f"all {n} chars on page {page_number} report size >= "
                             f"{WATERMARK_MIN_SIZE} (min {min(sizes)}, max {max(sizes)})",
                    "page": page_number,
                    "bbox": None,
                    "emitted_with_rule": _emitted_with_rule(doc),
                }
    return None


# ------------------------------------------------------------------------------------
# truth join -- design D.1: a firing whose would-be emission contradicts truth, or
# lands on a field truth lists as absent, is a conflict and kills the proposal.
# ------------------------------------------------------------------------------------


def _truth_for(corpus: str, doc_name: str) -> tuple[dict[str, Any], set[str]]:
    """(expected values, expect_absent fields) for one document, from its own truth."""
    if corpus == "pack":
        gold = ROOT / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"
        for line in gold.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record["file_name"] == doc_name:
                return {f["field"]: f["value"] for f in record["fields"]}, set()
        return {}, set()
    sources = {
        "uploads": ("testdata/uploads_manifest.json", "intended_fields"),
        "holdout": ("testdata/holdout_manifest.json", "intended_fields"),
        "external": ("testdata/external_truth.json", "expected"),
        "confirm": ("testdata/confirm_truth.json", "expected"),
    }
    rel, key = sources[corpus]
    data = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    for record in data["documents"]:
        if record["file_name"] == doc_name:
            return dict(record.get(key, {})), set(record.get("expect_absent", []))
    return {}, set()


def _values_agree(field: str, truth_value: Any, emitted: Any) -> bool:
    """The same comparison the measuring harnesses make, imported, not re-invented."""
    from measure_confirm_set import _matches  # type: ignore

    return bool(_matches(field, truth_value, emitted))


def conflicts(fired: list[dict]) -> list[dict]:
    out: list[dict] = []
    for firing in fired:
        expected, absent = _truth_for(firing["corpus"], firing["doc"])
        for field, value in (firing.get("emitted_with_rule") or {}).items():
            if field in absent:
                out.append({
                    "doc": firing["doc"], "field": field,
                    "truth": "absent", "rule_would_emit": value,
                })
            elif field in expected and not _values_agree(field, expected[field], value):
                out.append({
                    "doc": firing["doc"], "field": field,
                    "truth": expected[field], "rule_would_emit": value,
                })
    return out
