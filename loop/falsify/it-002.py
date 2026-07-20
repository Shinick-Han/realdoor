# -*- coding: utf-8 -*-
"""it-002 firing predicate -- read-only, run by `run_phase.py p3 --iteration 2 --run`.

The proposed rule (loop/proposals/it-002.md section 4): a vocabulary label that is one
whole cell of a printed column-header row (a line `_header_row_words` marks: >= 3 short
digit-free caption cells) licenses the single run beneath it, within
`HEADER_SEARCH_BAND`, whose x-span shares extent with exactly that cell and no other.
One candidate or nothing; caption refusal and type parse unchanged; certainty "low".

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with the rule monkeypatched in at exactly the `_scan_page` call site it will occupy
(appended to the `columns.column_value` branch, same abstention-only gate) -- and fires
iff the emitted field set differs. The join in `conflicts` therefore falsifies real
would-be emissions, not a hand-simulation of them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TARGET_DOC = "ca_dlse_paystub_hourly.pdf"


def _header_cell_value(
    lines: Sequence[Sequence[Any]],
    label_run: Sequence[Any],
    field_name: str,
    convention: Any,
    is_exact: bool,
    label_words: frozenset[int],
    header_words: frozenset[int],
) -> dict[str, Any] | None:
    """The proposed rule, verbatim -- P4 implements exactly this conduct."""
    import core.extract as ex
    from core.columns import HEADER_SEARCH_BAND, _span, _x_overlap
    from core.extract import (
        FREE_TEXT_FIELDS,
        ParseError,
        _caption_refusal,
        _join_run,
        _split_runs,
        parse_value,
    )

    # The label must be one WHOLE cell of one of the page's own column-header rows.
    if not label_run or not all(id(w) in header_words for w in label_run):
        return None
    header_line = next((l for l in lines if any(w is label_run[0] for w in l)), None)
    if header_line is None:
        return None
    cells = _split_runs(header_line)
    label_ids = {id(w) for w in label_run}
    ours = next((c for c in cells if {id(w) for w in c} & label_ids), None)
    if ours is None or {id(w) for w in ours} != label_ids:
        return None

    baseline = label_run[0].baseline
    page = label_run[0].page
    candidates: list[list[Any]] = []
    for line in lines:
        if not line or line[0].page != page:
            continue
        delta = baseline - line[0].baseline
        if not (0 < delta <= HEADER_SEARCH_BAND):
            continue
        for run in _split_runs(line):
            if all(id(w) in label_words for w in run):
                continue  # a label is never a value
            if _caption_refusal(field_name, run, header_words) is not None:
                continue  # a caption is never a value
            hits = [c for c in cells if _x_overlap(_span(run), _span(c))]
            if len(hits) != 1 or hits[0] is not ours:
                continue  # the page has not attributed this run to our column
            if field_name not in FREE_TEXT_FIELDS:
                try:
                    parse_value(field_name, _join_run(run))
                except ParseError:
                    continue  # not a reading this rule could emit; triggers no refusal
            candidates.append(run)
    if len(candidates) != 1:
        return None  # zero: nothing printed there. Two or more: ambiguous. Abstain.

    field = ex._build_value_field(
        candidates[0], field_name, convention, is_exact,
        f"value read from the single row beneath the header cell "
        f"{_join_run(label_run)!r} in one of the page's own column-header rows",
        header_words=header_words,
    )
    if field is None:
        return None
    field["certainty"] = "low"  # no gold-measured label geometry names it
    return field


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """Every field the extractor emits for this doc, with or without the rule."""
    import core.columns as columns
    import core.extract as ex

    original = columns.column_value

    def wrapped(lines, label_run, column_right, field_name, convention, is_exact,
                label_words, header_words=frozenset()):
        got = original(lines, label_run, column_right, field_name, convention,
                       is_exact, label_words, header_words)
        if got is not None:
            return got
        return _header_cell_value(lines, label_run, field_name, convention,
                                  is_exact, label_words, header_words)

    if with_rule:
        columns.column_value = wrapped
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"])
    finally:
        columns.column_value = original

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
