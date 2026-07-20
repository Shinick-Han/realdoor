# -*- coding: utf-8 -*-
"""it-011 firing predicate -- read-only, run by `run_phase.py p3 --iteration 11 --run`,
then `python loop/falsify/it-011.py --dev-corpora` for the filled/scenarios supplement.

The proposed change (loop/proposals/it-011.md section 4) does not read a value. It
changes which mapper a caller gets when it names none: the two-tier default
(`synonym_mapper`) becomes the three-tier ladder (canonical table -> synonym table ->
`core.label_llm.model_mapper`). So the predicate is not a geometry conduct -- it is the
ladder itself, run for real.

`fires(doc)` extracts the document twice in this process: once with `synonym_mapper`
(the committed default) and once with `tracking_layered_mapper` (the proposed default),
and fires iff the emitted field set differs. Because the model is the only difference,
every firing is a field the model named -- and `conflicts` falsifies each one against the
document's own truth, including `expect_absent`. A model nomination that would emit a
value contradicting truth is exactly hazard H2 and kills the proposal.

The captions are recorded too: `core.extract.unmapped_labels(mapper=synonym_mapper)`
lists every label run both tables miss, which is the exact input tier 3 consumes and the
upper bound on where this change can act. A document with no such label CANNOT fire, and
that is the specificity claim.

Requires REALDOOR_LABEL_LLM=1 and a key: with the model off the two legs are identical by
construction (core/test_label_llm.py pins it) and the sweep would fire nowhere, proving
nothing. The sealed hold-outs are never opened.
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

#: This iteration has no single target field. The claim under test is a path claim, and
#: its stop-condition is the pack: tier 3 must never reach a pack document, because the
#: canonical table holds every pack phrase. A pack firing is hazard H1.
PACK_MUST_NOT_FIRE = True


def _emitted(view: dict) -> dict[str, Any]:
    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def _model_named(view: dict) -> dict[str, Any]:
    from core.extract import MODEL_MAPPER_NOTE

    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if MODEL_MAPPER_NOTE in (f.get("notes") or "")
        and f.get("certainty") != "abstain" and f.get("value") is not None
    }


def _unknown_captions(doc: dict) -> list[str]:
    """Label runs both frozen tables return None for -- tier 3's entire input."""
    import core.extract as ex

    try:
        return sorted(set(ex.unmapped_labels(
            doc["path"], document_type=doc.get("document_type"),
            mapper=ex.synonym_mapper,
        )))
    except Exception as exc:  # a document the reader cannot open is not a firing
        return [f"<unreadable: {type(exc).__name__}>"]


def fires(doc: dict) -> dict | None:
    import core.extract as ex

    kwargs: dict[str, Any] = {"document_type": doc.get("document_type")}
    if doc.get("document_id"):
        kwargs["document_id"] = doc["document_id"]

    base = _emitted(ex.extract_document(doc["path"], fallback_mapper=ex.synonym_mapper,
                                        **kwargs))
    tracker = ex.tracking_layered_mapper(doc.get("document_type") or "")
    ladder_view = ex.extract_document(doc["path"], fallback_mapper=tracker, **kwargs)
    ladder = _emitted(ladder_view)

    if base == ladder:
        return None

    changed = sorted(
        (set(base) ^ set(ladder))
        | {k for k in set(base) & set(ladder) if base[k] != ladder[k]}
    )
    return {
        "field": ", ".join(changed),
        "value": {k: {"tables_only": base.get(k), "with_ladder": ladder.get(k)}
                  for k in changed},
        "model_named": _model_named(ladder_view),
        "unknown_captions": _unknown_captions(doc),
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ladder[k] for k in changed if k in ladder},
    }


# ------------------------------------------------------------------------------------
# truth join -- design D.1: a firing whose would-be emission contradicts truth, or lands
# on a field truth lists as absent, is a conflict and kills the proposal.
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
    if corpus == "scenarios":
        import measure_scenario_sets as mss  # type: ignore

        truth = json.loads(mss.TRUTH.read_text(encoding="utf-8"))
        for row in truth["sets"]:
            if row["role"] == "sealed":       # never opened, not even for a truth join
                continue
            for record in row["documents"]:
                if record["file_name"] == doc_name:
                    return ({f["field"]: f["value"]
                             for f in record.get("truth_fields", [])},
                            set(record.get("expect_absent", [])))
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
        # H1: the pack is the deterministic layer's own territory. Any firing there is a
        # conflict on its face, whatever truth says, because tier 3 was never supposed to
        # be reached on a document whose every phrase is in the canonical table.
        if firing.get("corpus") == "pack" and PACK_MUST_NOT_FIRE:
            out.append({
                "doc": firing["doc"], "field": firing.get("field"),
                "truth": "<H1: tier 3 must not reach a pack document>",
                "rule_would_emit": firing.get("emitted_with_rule"),
            })
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
# dev-corpora supplement -- the manifest carries neither `filled` nor `scenarios`, and
# those are the real-carrier corpora this iteration exists to measure. Dev role only;
# the sealed documents are never opened.
# ------------------------------------------------------------------------------------


def _filled_dev() -> list[dict]:
    truth = json.loads(
        (ROOT / "testdata/filled/filled_truth.json").read_text(encoding="utf-8")
    )
    return [
        {
            "corpus": "filled",
            "doc": r["file_name"],
            "path": str(ROOT / "testdata/filled" / r["file_name"]),
            "document_type": "pay_stub",  # asserted by measure_filled_forms.py
        }
        for r in truth["documents"] if r.get("role") == "dev"
    ]


def _scenarios_dev() -> list[dict]:
    """Dev scenario sets only. `measure_scenario_sets.py` owns the seal; this mirrors its
    role test and never unseals."""
    import measure_scenario_sets as mss  # type: ignore

    truth = json.loads(mss.TRUTH.read_text(encoding="utf-8"))
    docs: list[dict] = []
    for row in truth["sets"]:
        if row["role"] != "dev":       # `sealed` is skipped, never opened
            continue
        for d in row["documents"]:
            path = mss.SCEN_DIR / d["file_name"]
            if not path.exists():
                continue
            docs.append({
                "corpus": "scenarios",
                "doc": d["file_name"],
                "path": str(path),
                "document_type": d["document_type"],
                "document_id": d.get("document_id"),
            })
    return docs


def _sweep(docs: list[dict]) -> dict[str, Any]:
    fired: list[dict[str, Any]] = []
    for doc in docs:
        result = fires(doc)
        if result:
            fired.append({"corpus": doc["corpus"], "doc": doc["doc"], **result})
    return {
        "documents_swept": len(docs),
        "docs_fired": sorted({f"{f['corpus']}::{f['doc']}" for f in fired}),
        "firings": fired,
        "conflicts": conflicts(fired),
    }


if __name__ == "__main__":
    if "--dev-corpora" not in sys.argv:
        raise SystemExit("usage: python loop/falsify/it-011.py --dev-corpora "
                         "(the 77-document sweep is run_phase.py p3 --iteration 11 --run)")
    if os.environ.get("REALDOOR_LABEL_LLM") != "1":
        raise SystemExit("refusing to sweep with the model off: both legs would be "
                         "identical by construction and the sweep would prove nothing. "
                         "Set REALDOOR_LABEL_LLM=1.")

    artefact = ROOT / "loop" / "falsification" / "it-011.json"
    report = json.loads(artefact.read_text(encoding="utf-8")) if artefact.exists() else {}

    docs = _filled_dev()
    try:
        docs += _scenarios_dev()
    except Exception as exc:
        report["scenarios_sweep_error"] = f"{type(exc).__name__}: {exc}"

    supplement = _sweep(docs)
    report["dev_corpora"] = supplement
    if supplement["conflicts"]:
        report["verdict"] = "fail"

    from core import label_llm

    report["label_llm_stats"] = label_llm.stats()
    artefact.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
    print(f"dev corpora: fired on {len(supplement['docs_fired'])}/"
          f"{supplement['documents_swept']}; conflicts {len(supplement['conflicts'])}")
    print(f"updated {artefact}")
