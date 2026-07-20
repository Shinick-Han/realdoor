# -*- coding: utf-8 -*-
"""it-009 firing predicate -- read-only, run by `run_phase.py p3 --iteration 9 --run`,
then `python loop/falsify/it-009.py --filled-dev` for the filled dev supplement.

The proposed rule (loop/proposals/it-009.md section 4), carried verbatim:

* the quote fold -- `normalize_label` maps the frozen scorer's four quote glyphs
  (`‘ ’ -> '`, `“ ” -> "`, eval/score_extraction.py `_QUOTE_MAP` lines 156-159)
  to ASCII before matching, admitting glyph variants of strings already in the
  closed tables and nothing else;
* the parallel-caption refusal -- a candidate run beside a recognised label that
  is caption-shaped (`_is_caption_cell`) AND repeats the label's own final
  normalized token is the page printing the next column's caption, not a value,
  and is refused at the two seams the measured misread flows through
  (`_side_by_side_run`, `columns.column_value`).

`fires(doc)` reports a document when EITHER (a) the fold changes the set of
vocabulary-recognised label runs on any line -- the engagement condition, which
is what makes a zero-flip iteration falsifiable at all -- or (b) the full
extractor, run twice in-process (committed conduct vs fold + both guards, the
same conduct P4 places), emits a different field set. The join in `conflicts`
falsifies every changed emission against the document's own truth including
`expect_absent`. The two sealed filled documents are never opened.
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

TARGET_DOC = "wa_dshs_14252_employment_verification.pdf"

#: The candidate fold table, verbatim from the proposal: the scorer's own quote
#: rows (eval/score_extraction.py `_QUOTE_MAP`), quotes only, no dashes.
QUOTE_FOLD = {"‘": "'", "’": "'", "“": '"', "”": '"'}


def _engagement(doc: dict) -> list[str]:
    """Lines on which the fold changes the vocabulary-recognised label-run set."""
    import pdfplumber

    import core.columns as cols
    import core.extract as ex
    import core.shredded as shr

    orig = ex.normalize_label

    def folded(text: str) -> str:
        for bad, good in QUOTE_FOLD.items():
            text = text.replace(bad, good)
        return orig(text)

    changed: list[str] = []
    with pdfplumber.open(doc["path"]) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            lines = ex.group_lines(ex.read_words(page, number))
            for line in lines:
                before = [
                    ex._join_run(r)
                    for r in ex._label_runs(line, doc["document_type"], ex.synonym_mapper)
                ]
                ex.normalize_label = folded
                cols.normalize_label = folded
                shr.normalize_label = folded
                try:
                    after = [
                        ex._join_run(r)
                        for r in ex._label_runs(line, doc["document_type"], ex.synonym_mapper)
                    ]
                finally:
                    ex.normalize_label = orig
                    cols.normalize_label = orig
                    shr.normalize_label = orig
                if before != after:
                    changed.append(
                        f"p{number}: {sorted(set(after) - set(before))} newly recognised"
                    )
    return changed


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """Every field the extractor emits for this doc, with or without the candidate."""
    import core.columns as cols
    import core.extract as ex
    import core.shredded as shr

    orig = ex.normalize_label

    def folded(text: str) -> str:
        for bad, good in QUOTE_FOLD.items():
            text = text.replace(bad, good)
        return orig(text)

    def parallel_caption(label_run: Sequence[Any], run: Sequence[Any]) -> bool:
        label_tokens = folded(ex._join_run(label_run)).split()
        run_tokens = folded(ex._join_run(run)).split()
        return (
            bool(label_tokens and run_tokens)
            and run_tokens[-1] == label_tokens[-1]
            and ex._is_caption_cell(run)
        )

    orig_sbr = ex._side_by_side_run
    orig_cv = cols.column_value

    def guarded_sbr(line, label_runs, index, column_right, field_name,
                    header_words=frozenset()):
        run = orig_sbr(line, label_runs, index, column_right, field_name, header_words)
        if run is None or parallel_caption(label_runs[index], run):
            return None
        return run

    def guarded_cv(lines, label_run, column_right, field_name, convention, is_exact,
                   label_words, header_words=frozenset()):
        field = orig_cv(lines, label_run, column_right, field_name, convention,
                        is_exact, label_words, header_words)
        if field is None:
            return None
        source = field.get("source_text", "")
        run_tokens = folded(orig(source)).split()
        label_tokens = folded(ex._join_run(label_run)).split()
        caption_shaped = (
            not any(c.isdigit() for c in source) and ex.looks_like_a_label(source)
        )
        if (label_tokens and run_tokens and run_tokens[-1] == label_tokens[-1]
                and caption_shaped):
            return None
        return field

    if with_rule:
        ex.normalize_label = folded
        cols.normalize_label = folded
        shr.normalize_label = folded
        ex._side_by_side_run = guarded_sbr
        cols.column_value = guarded_cv
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
    finally:
        ex.normalize_label = orig
        cols.normalize_label = orig
        shr.normalize_label = orig
        ex._side_by_side_run = orig_sbr
        cols.column_value = orig_cv

    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def fires(doc: dict) -> dict | None:
    engaged = _engagement(doc)
    base = _emissions(doc, with_rule=False)
    ruled = _emissions(doc, with_rule=True)
    if base == ruled and not engaged:
        return None
    changed = sorted(
        (set(base) ^ set(ruled)) | {k for k in set(base) & set(ruled) if base[k] != ruled[k]}
    )
    return {
        "field": ", ".join(changed) or "(none -- engagement only)",
        "value": {k: {"without_rule": base.get(k), "with_rule": ruled.get(k)}
                  for k in changed},
        "engagement": engaged,
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ruled[k] for k in changed if k in ruled},
    }


# ------------------------------------------------------------------------------------
# truth join -- design D.1: a firing whose would-be emission contradicts truth, or
# lands on a field truth lists as absent, is a conflict and kills the proposal.
# Engagement-only firings and withdrawals have no `emitted_with_rule` entries and can
# never conflict -- the fold plus its guard only refuses or leaves things alone.
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
        "filled": ("testdata/filled/filled_truth.json", "expected"),
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


# ------------------------------------------------------------------------------------
# filled dev supplement -- the 3 dev documents of testdata/filled, swept with the same
# predicate and recorded in the same artefact. The sealed two are never opened: this
# list is the truth file's own `role: dev` marking, not a directory walk.
# ------------------------------------------------------------------------------------

FILLED_TARGET = "wa_dshs_14252_employment_verification_filled.pdf"


def _filled_dev_sweep() -> dict[str, Any]:
    truth = json.loads(
        (ROOT / "testdata/filled/filled_truth.json").read_text(encoding="utf-8")
    )
    fired: list[dict[str, Any]] = []
    swept = 0
    for record in truth["documents"]:
        if record.get("role") != "dev":
            continue
        swept += 1
        doc = {
            "corpus": "filled",
            "doc": record["file_name"],
            "path": str(ROOT / "testdata/filled" / record["file_name"]),
            "document_type": "pay_stub",  # asserted by measure_filled_forms.py
        }
        result = fires(doc)
        if result:
            fired.append({"corpus": "filled", "doc": record["file_name"], **result})
    return {
        "documents_swept": swept,
        "docs_fired": sorted({f"{f['corpus']}::{f['doc']}" for f in fired}),
        "firings": fired,
        "conflicts": conflicts(fired),
        "target_fired": any(f["doc"] == FILLED_TARGET for f in fired),
    }


if __name__ == "__main__":
    if "--filled-dev" not in sys.argv:
        raise SystemExit("usage: python loop/falsify/it-009.py --filled-dev "
                         "(the 77-document sweep is run_phase.py p3 --iteration 9 --run)")
    artefact = ROOT / "loop" / "falsification" / "it-009.json"
    report = json.loads(artefact.read_text(encoding="utf-8")) if artefact.exists() else {}
    supplement = _filled_dev_sweep()
    report["filled_dev"] = supplement
    if supplement["conflicts"]:
        report["verdict"] = "fail"
    artefact.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
    print(f"filled dev: fired on {len(supplement['docs_fired'])}/{supplement['documents_swept']}; "
          f"conflicts {len(supplement['conflicts'])}; "
          f"filled target fired {supplement['target_fired']}")
    print(f"updated {artefact}")
