# -*- coding: utf-8 -*-
"""it-010 firing predicate -- read-only, run by `run_phase.py p3 --iteration 10 --run`,
then `python loop/falsify/it-010.py --filled-dev` for the filled dev supplement.

The proposed rule (loop/proposals/it-010.md section 4), carried verbatim: a
colon-terminated recognised label may read the immediately following run on its own
baseline at a word-space gap, and for that read its own line is a fill-in line, not a
column-header row (the own-line amnesty). Every other refusal stands: sole-run cell,
colon barriers, colon-candidate refusal, other lines' header rows, the it-009
parallel-caption refusal, the field's parse gates. Bare labels keep the 12pt gap.

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with `_side_by_side_run`/`_side_by_side_value` replaced by the licensed pair (the same
conduct P4 places) -- and fires iff the emitted field set differs OR the licensed seam
diverged from the committed seam anywhere inside the real flow (engagement without a
flip is recorded, not hidden). The join in `conflicts` falsifies every changed emission
against the document's own truth including `expect_absent`. The two sealed filled
documents are never opened.
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

#: The manifest carries no filled documents; the target lives in the dev split below.
TARGET_DOC = "seattle_housing_employment_verification_filled.pdf"
FILLED_TARGET = TARGET_DOC


import contextlib
import os


@contextlib.contextmanager
def _flag_off():
    """Force the committed conduct. Once P4 lands, the tree carries the license behind
    `REALDOOR_COLON_GAP` (default on); G5 proves flag-off is byte-identical to the
    accepted commit, so a flag-off leg IS the committed conduct on any tree, and this
    predicate measures the same comparison before and after implementation."""
    prior = os.environ.get("REALDOOR_COLON_GAP")
    os.environ["REALDOOR_COLON_GAP"] = "0"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("REALDOOR_COLON_GAP", None)
        else:
            os.environ["REALDOOR_COLON_GAP"] = prior


def _emissions(doc: dict, with_rule: bool) -> tuple[dict[str, Any], list[str]]:
    """Emitted fields for this doc, plus the seam-divergence log when the rule is on."""
    import core.extract as ex

    divergences: list[str] = []
    orig_sbr = ex._side_by_side_run
    orig_sbv = ex._side_by_side_value

    def colon_license(label_run: Sequence[Any]) -> bool:
        return ex._join_run(label_run).strip().endswith(":")

    def licensed_sbr(line, label_runs, index, column_right, field_name,
                     header_words=frozenset()):
        label_run = label_runs[index]
        label_end = max(w.x1 for w in label_run)
        label_words = {id(w) for run in label_runs for w in run}
        right = [w for w in line
                 if w.x0 >= label_end and w.x0 < column_right - ex._x_tolerance(field_name)
                 and id(w) not in label_words]
        if not right:
            return None
        runs = ex._split_runs(right)
        barrier = ex._first_caption_run(runs, header_words)
        if barrier is not None:
            runs = [run for run in runs if run[0].x0 < barrier]
        if len(runs) != 1:
            return None
        run = runs[0]
        if run[0].x0 - label_end < ex.SIDE_BY_SIDE_MIN_GAP and not colon_license(label_run):
            return None
        if ex._parallel_caption_refusal(label_run, run):
            return None
        return run

    def licensed_sbv(line, label_runs, index, column_right, field_name, convention,
                     is_exact, header_words=frozenset()):
        effective = header_words
        if colon_license(label_runs[index]):
            own = {id(w) for w in line}
            effective = frozenset(w for w in header_words if w not in own)
        run = licensed_sbr(line, label_runs, index, column_right, field_name, effective)
        if run is not None and effective is not header_words and any(
            w.text.strip().endswith(":") for w in run
        ):
            # the interior-colon refusal: a licensed read is a clean fill or nothing
            run = None
        # The committed conduct, recomputed with the COMMITTED run-finder under the
        # committed flag state (orig_sbv's own body is exactly this pair) -- calling
        # orig_sbv here would re-enter the patched module global and measure the
        # licensed seam against itself.
        with _flag_off():
            committed_run = orig_sbr(line, label_runs, index, column_right, field_name,
                                     header_words)
            committed = None if committed_run is None else ex._build_value_field(
                committed_run, field_name, convention, is_exact,
                "value read from the same line as its label, in the column to its right",
                header_words=header_words,
            )
        if run is None:
            if committed is not None:
                divergences.append(
                    f"{field_name}: licensed refuses where committed read "
                    f"{committed.get('source_text')!r}"
                )
            return None
        field = ex._build_value_field(
            run, field_name, convention, is_exact,
            "value read from the same line as its label, in the column to its right",
            header_words=effective,
        )
        if (field is None) != (committed is None) or (
            field is not None and committed is not None
            and field.get("value") != committed.get("value")
        ):
            divergences.append(
                f"{field_name}: licensed {(field or {}).get('value')!r} vs committed "
                f"{(committed or {}).get('value')!r} at {ex._join_run(run)!r}"
            )
        return field

    if with_rule:
        ex._side_by_side_run = licensed_sbr
        ex._side_by_side_value = licensed_sbv
        try:
            view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                       fallback_mapper=ex.synonym_mapper)
        finally:
            ex._side_by_side_run = orig_sbr
            ex._side_by_side_value = orig_sbv
    else:
        with _flag_off():
            view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                       fallback_mapper=ex.synonym_mapper)

    emitted = {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }
    return emitted, divergences


def fires(doc: dict) -> dict | None:
    base, _ = _emissions(doc, with_rule=False)
    ruled, divergences = _emissions(doc, with_rule=True)
    if base == ruled and not divergences:
        return None
    changed = sorted(
        (set(base) ^ set(ruled)) | {k for k in set(base) & set(ruled) if base[k] != ruled[k]}
    )
    return {
        "field": ", ".join(changed) or "(none -- seam engagement only)",
        "value": {k: {"without_rule": base.get(k), "with_rule": ruled.get(k)}
                  for k in changed},
        "seam_divergences": divergences,
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ruled[k] for k in changed if k in ruled},
    }


# ------------------------------------------------------------------------------------
# truth join -- design D.1: a firing whose would-be emission contradicts truth, or
# lands on a field truth lists as absent, is a conflict and kills the proposal.
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
# predicate and recorded in the same artefact. The sealed two are never opened.
# ------------------------------------------------------------------------------------


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
        raise SystemExit("usage: python loop/falsify/it-010.py --filled-dev "
                         "(the 77-document sweep is run_phase.py p3 --iteration 10 --run)")
    artefact = ROOT / "loop" / "falsification" / "it-010.json"
    report = json.loads(artefact.read_text(encoding="utf-8")) if artefact.exists() else {}
    supplement = _filled_dev_sweep()
    report["filled_dev"] = supplement
    report["target_fired"] = supplement["target_fired"]
    if supplement["conflicts"]:
        report["verdict"] = "fail"
    artefact.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
    print(f"filled dev: fired on {len(supplement['docs_fired'])}/{supplement['documents_swept']}; "
          f"conflicts {len(supplement['conflicts'])}; target_fired {supplement['target_fired']}")
    print(f"updated {artefact}")
