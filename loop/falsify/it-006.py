# -*- coding: utf-8 -*-
"""it-006 firing predicate -- read-only, run by `run_phase.py p3 --iteration 6 --run`.

The proposed change (loop/proposals/it-006.md section 4, design it-D of
ocr-extension-design.md, backlog T12), behind `REALDOOR_OCR_SINGLE_ROW`: on
OCR-injected pages, a single-earnings-row column may anchor. A row product
`rate x hours = amount` (both factors printed, neither equal to 1, hours within the
physical bound, factors and amount non-overlapping, amount in cents-form) whose
amount value is REPRINTED as another cents-form token on a different line of the same
page, x-aligned with it (either edge) -- the single-row column's own printed total --
forms a one-member anchored run. Everything downstream is the committed chain:
S3 one-distinct-survivor, V1/V2/V3, the band search for net, band_role, certainty
"low". Measured on lcc at native scale: page 3's crops read
31.00 x $10.510000 = $325.81 with `Total: $325.81` aligned beneath -- gross closes;
no page co-locates that anchor with the 61.36 + 264.45 band, so net stays abstained.

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with `verified.verify_page` patched so that, on exactly the pages that received
injected words, `_anchored_runs` is augmented with the single-row pseudo runs -- and
fires iff the emitted field set differs. `conflicts` joins every changed field
against that document's own truth, INCLUDING `expect_absent` (lcc lists hourly_rate
and regular_hours there: emitting 10.51 or 31.00 is exactly as fatal as a wrong
gross).
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

TARGET_DOC = "lcc_understanding_your_paycheck.pdf"


# --------------------------------------------------------------------------------------
# the candidate conduct, verbatim (proposal section 4)
# --------------------------------------------------------------------------------------


def _aligned(a, b) -> bool:
    from core.extract import VALUE_X_TOLERANCE

    return (abs(a.x0 - b.x0) <= VALUE_X_TOLERANCE
            or abs(a.x1 - b.x1) <= VALUE_X_TOLERANCE)


def single_row_runs(tokens, bound):
    """One-member anchored runs: a non-degenerate exact row product whose amount
    reprints, cents-form, x-aligned, on a different line of the same page."""
    from core import arithmetic as ar
    from core import verified as v

    out = []
    seen: set[tuple[int, int]] = set()
    for p in ar.find_row_products(tokens):
        if p.rate.value == 1.0 or p.hours.value == 1.0:
            continue  # the multiplicative identity anchors nothing (it-004)
        if not (0 < p.hours.value <= bound):
            continue
        if (v._overlaps(p.hours, p.amount) or v._overlaps(p.rate, p.amount)
                or v._overlaps(p.rate, p.hours)):
            continue
        if p.amount.decimals != 2:
            continue  # money prints its cents (L3)
        for t in tokens:
            if id(t) == id(p.amount) or t.page != p.amount.page or t.decimals != 2:
                continue
            if abs(t.value - p.amount.value) > 1e-9:
                continue
            if abs(t.baseline - p.amount.baseline) <= ar.BASELINE_TOLERANCE:
                continue  # the reprint must be another line, not a YTD twin beside it
            if not _aligned(t, p.amount):
                continue
            key = (id(p.amount), id(t))
            if key in seen:
                continue  # both factor orientations name the same pair
            seen.add(key)
            out.append(v.Anchored(run=(p.amount,), total=t, products=(p,)))
    return out


def verify_page_single_row(committed_vp, words, document_type, found, convention,
                           wanted, *, band_role=False):
    """The committed `verify_page` (passed in unpatched) with `_anchored_runs`
    augmented by the single-row pseudo runs -- the exact conduct P4 will place
    behind the flag."""
    from core import verified as v

    original = v._anchored_runs

    def augmented(tokens, bound):
        real = original(tokens, bound)
        return [*real, *single_row_runs(tokens, bound)]

    v._anchored_runs = augmented
    try:
        return committed_vp(words, document_type, found, convention, wanted,
                            band_role=band_role)
    finally:
        v._anchored_runs = original


# --------------------------------------------------------------------------------------
# two extractions per document
# --------------------------------------------------------------------------------------

_MEMO: dict[tuple[str, int], list] = {}
_INJECTED_IDS: set[int] = set()
_REAL_REGION_OCR = None


def _memoized_region_ocr(pdf_source, plumber_page, page_number, text_words):
    key = (str(pdf_source), page_number)
    if key not in _MEMO:
        _MEMO[key] = _REAL_REGION_OCR(pdf_source, plumber_page, page_number, text_words)
    words = _MEMO[key]
    _INJECTED_IDS.update(id(w) for w in words)
    return words


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    global _REAL_REGION_OCR
    import core.extract as ex
    import core.ocr_words as ow
    import core.verified as verified

    if _REAL_REGION_OCR is None:
        _REAL_REGION_OCR = ow.region_ocr_words

    original_vp = verified.verify_page

    def patched_vp(words, doc_type, found, convention, wanted, **kwargs):
        if with_rule and any(id(w) in _INJECTED_IDS for w in words):
            return verify_page_single_row(original_vp, words, doc_type, found,
                                          convention, wanted, **kwargs)
        return original_vp(words, doc_type, found, convention, wanted, **kwargs)

    ow.region_ocr_words = _memoized_region_ocr
    verified.verify_page = patched_vp
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
    finally:
        verified.verify_page = original_vp
        ow.region_ocr_words = _REAL_REGION_OCR

    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def fires(doc: dict) -> dict | None:
    base = _emissions(doc, with_rule=False)
    ruled = _emissions(doc, with_rule=True)
    if base == ruled:
        return None
    changed = sorted(set(base) ^ set(ruled) | {
        k for k in set(base) & set(ruled) if base[k] != ruled[k]
    })
    return {
        "field": ", ".join(changed),
        "value": {k: {"without_rule": base.get(k), "with_rule": ruled.get(k)}
                  for k in changed},
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ruled[k] for k in changed if k in ruled},
    }


# ------------------------------------------------------------------------------------
# truth join -- design D.1
# ------------------------------------------------------------------------------------


def _truth_for(corpus: str, doc_name: str) -> tuple[dict[str, Any], set[str]]:
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
    from measure_confirm_set import _matches  # type: ignore

    return bool(_matches(field, truth_value, emitted))


def conflicts(fired: list[dict]) -> list[dict]:
    out: list[dict] = []
    for firing in fired:
        if firing["corpus"] == "pack":
            out.append({
                "doc": firing["doc"], "field": firing.get("field"),
                "truth": "pack must never engage-and-fire",
                "rule_would_emit": firing.get("emitted_with_rule"),
            })
            continue
        expected, absent = _truth_for(firing["corpus"], firing["doc"])
        for field, value in (firing.get("emitted_with_rule") or {}).items():
            if field in absent:
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "absent", "rule_would_emit": value})
            elif field in expected and not _values_agree(field, expected[field], value):
                out.append({"doc": firing["doc"], "field": field,
                            "truth": expected[field], "rule_would_emit": value})
            elif field not in expected:
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "not in this document's truth at all",
                            "rule_would_emit": value})
    return out
