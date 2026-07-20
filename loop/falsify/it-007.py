# -*- coding: utf-8 -*-
"""it-007 firing predicate -- read-only, run by `run_phase.py p3 --iteration 7 --run`.

The proposed change (loop/proposals/it-007.md, flag `REALDOOR_OCR_SKIP_SATISFIED`):
after the text pass has settled every page, and before any OCR-words work begins,
skip the OCR-words collection entirely when none of the fields an OCR consumer
can ask for is blank. "Blank" is the arithmetic block's own `_blank` test --
missing from `found` or `certainty == "abstain"` -- and the consumer field set
is read off the call sites, not assumed: `verified.verify_page` is called only
for `wanted` = blank expected fields in `verified.VERIFIABLE_FIELDS`;
`shredded.recover` and `core.total_band` are gated on blank expected fields in
`("gross_pay", "net_pay")`. So the exact precondition is: no blank field in
`EXPECTED_FIELDS[doc_type]` ∩ (`VERIFIABLE_FIELDS` ∪ {gross_pay, net_pay}).

Deliberately NOT the wider "no expected field abstaining at all": that phrasing
is also exact but strictly narrower (fires 36 of 77 instead of 46), and neither
phrasing may skip bonita -- its expect-absent `hourly_rate`/`regular_hours` stay
abstaining after the text pass, both are VERIFIABLE, and the OCR-injected
`verify_page` is structurally licensed to answer or attach adjacency proposals
to exactly those fields. The sanity expectations below pin that refusal.

`fires(doc)` computes the precondition by replicating the committed text pass
verbatim (`read_words` + `extract_fields_from_page` with the deterministic and
synonym mappers, `found.setdefault` per page -- the exact calls
`extract_document` makes before its arithmetic block), and fires iff the skip
would trigger. For every firing document it then runs the full extractor twice:

  * committed conduct -- `extract_document` exactly as shipped;
  * skip conduct, emulated exactly -- `REALDOOR_OCR_WORDS=0`, which produces the
    identical all-empty `ocr_by_page` the skip would produce, without importing
    `core.ocr_words` (the same structural end state; proposal section 4);

and byte-compares the two full-document JSON dumps. `conflicts` reports every
fired document whose dumps differ by even one byte. One byte on one document
kills the proposal; zero conflicts is the output-identity claim.

Documents where the skip would NOT fire are not run twice: with the precondition
false the proposed code takes today's path literally (the same collection calls
in the same order), so the second run would compare a deterministic function
with itself. The deferral-purity argument for that case is proposal section 5
(verified empirically: eager and post-loop collection on bonita produce
identical Word streams) and is pinned end-to-end by `core/test_ocr_skip.py`.

Sanity expectations: fires on ca_dlse_paystub_hourly (numeric four all read
from text; carries one embedded image), does NOT fire on bonita, ou, hi_ags or
lcc. Expected to fire widely -- the whole pack is text-complete -- and that is
the point: wide firing is wide savings; the safety claim is the byte-identity
join, not the firing count.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGET_DOC = "ca_dlse_paystub_hourly.pdf"

#: Documents the precondition must refuse: each keeps a blank numeric-four field
#: after the text pass, so their OCR consumers stay reachable.
MUST_NOT_FIRE = (
    "bonita_certificated_check_sample.pdf",
    "ou_sample_check_stub.pdf",
    "hi_ags_pay_statement_example_2021.pdf",
    "lcc_understanding_your_paycheck.pdf",
)


# --------------------------------------------------------------------------------------
# the precondition, replicated verbatim from extract_document's text pass
# --------------------------------------------------------------------------------------


def _skip_would_fire(doc: dict) -> bool:
    """True iff, after the committed text pass, no OCR-consumable field is blank.

    Mirrors `extract_document` exactly: `read_words` per page,
    `extract_fields_from_page(words, doc_type, LineBoxConvention(),
    deterministic_mapper, synonym_mapper)`, first page wins via `setdefault`.
    Blank is the arithmetic block's own `_blank`: missing or certainty abstain.
    The consumable set is the union the three consumer gates ask for.
    """
    import pdfplumber

    import core.extract as ex
    from core import verified

    consumable = set(verified.VERIFIABLE_FIELDS) | {"gross_pay", "net_pay"}
    doc_type = doc["document_type"]
    found: dict[str, dict[str, Any]] = {}
    with pdfplumber.open(doc["path"]) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = ex.read_words(page, page_number)
            page_fields, _ = ex.extract_fields_from_page(
                words, doc_type, ex.LineBoxConvention(),
                ex.deterministic_mapper, ex.synonym_mapper,
            )
            for name, value in page_fields.items():
                found.setdefault(name, value)

    def blank(name: str) -> bool:
        existing = found.get(name)
        return existing is None or existing.get("certainty") == "abstain"

    return not any(
        blank(name)
        for name in ex.EXPECTED_FIELDS.get(doc_type, ())
        if name in consumable
    )


# --------------------------------------------------------------------------------------
# two full extractions, byte-compared
# --------------------------------------------------------------------------------------


def _dump(doc: dict, ocr_words_off: bool) -> str:
    """The full DocumentView as canonical JSON bytes (a str; comparison is exact)."""
    import core.extract as ex

    saved = os.environ.get("REALDOOR_OCR_WORDS")
    try:
        if ocr_words_off:
            os.environ["REALDOOR_OCR_WORDS"] = "0"
        elif "REALDOOR_OCR_WORDS" in os.environ:
            del os.environ["REALDOOR_OCR_WORDS"]
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
    finally:
        if saved is None:
            os.environ.pop("REALDOOR_OCR_WORDS", None)
        else:
            os.environ["REALDOOR_OCR_WORDS"] = saved
    return json.dumps(view, indent=1, ensure_ascii=False, sort_keys=True, default=str)


def fires(doc: dict) -> dict | None:
    if not _skip_would_fire(doc):
        return None  # the skip would not trigger; today's path runs literally
    committed = _dump(doc, ocr_words_off=False)
    skipped = _dump(doc, ocr_words_off=True)
    identical = committed == skipped
    return {
        "field": "(none -- the skip fires; no field may change)",
        "value": {"byte_identical": identical},
        "page": None,
        "bbox": None,
        "byte_identical": identical,
    }


def conflicts(fired: list[dict]) -> list[dict]:
    """Any byte difference on any fired document is a conflict -- reject.

    Additionally treats a firing on any MUST_NOT_FIRE document as a conflict:
    those documents keep a blank numeric-four field, so a predicate that fires
    there does not implement the precondition it claims to.
    """
    out = [
        {
            "doc": firing["doc"],
            "field": "(whole-document byte identity)",
            "truth": "skip conduct must be byte-identical to committed conduct",
            "rule_would_emit": "a differing extraction JSON",
        }
        for firing in fired
        if not firing.get("byte_identical", False)
    ]
    out.extend(
        {
            "doc": firing["doc"],
            "field": "(sanity: must not fire)",
            "truth": "a blank numeric-four field keeps the OCR consumers reachable",
            "rule_would_emit": "a skip on a document whose OCR pass is live",
        }
        for firing in fired
        if firing["doc"] in MUST_NOT_FIRE
    )
    return out
