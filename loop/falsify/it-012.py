# -*- coding: utf-8 -*-
"""it-012 firing predicate -- read-only, run by `run_phase.py p3 --iteration 12 --run`,
then `python loop/falsify/it-012.py --dev` for the filled and scenario supplements.

The proposed rule (loop/proposals/it-012.md section 4): values typed into interactive
form widgets are read as ordinary printed `Word`s -- their appearance streams drawn onto
a derived page at the place PDF 12.5.5 puts them, read back by `core.extract.read_words`
-- and merged into the page's word stream, where the EXISTING rules bind them. The
widget's internal field name is never consulted.

`fires(doc)` runs the full extractor twice in this process, once with
`REALDOOR_FORM_FIELDS=0` and once with it on, and fires iff the emitted field set
differs. This is a new INPUT SOURCE, not a new seam, so there is no seam to instrument:
the flag is the whole of the difference and the flag-off leg is exactly the committed
conduct (which G5 proves byte-identical to the accepted commit).

`conflicts` falsifies every changed emission against the document's own truth including
`expect_absent`. Sealed documents -- the two sealed filled forms and the eight sealed
scenario sets -- are never opened.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

FLAG = "REALDOOR_FORM_FIELDS"

#: The manifest carries no FILLED form; the targets live in the dev splits below.
FILLED_TARGET = "wa_dshs_14252_employment_verification_filled.pdf"
SCENARIO_TARGET_SETS = ("S06", "S10", "S12", "S15", "S17", "S28")


@contextlib.contextmanager
def _flag(value: str):
    prior = os.environ.get(FLAG)
    os.environ[FLAG] = value
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(FLAG, None)
        else:
            os.environ[FLAG] = prior


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    import core.extract as ex

    with _flag("1" if with_rule else "0"):
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
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
    changed = sorted(
        (set(base) ^ set(ruled)) | {k for k in set(base) & set(ruled) if base[k] != ruled[k]}
    )
    return {
        "field": ", ".join(changed),
        "value": {k: {"without_rule": base.get(k), "with_rule": ruled.get(k)}
                  for k in changed},
        "page": None,
        "bbox": None,
        "emitted_with_rule": {k: ruled[k] for k in changed if k in ruled},
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
        return _scenario_truth(doc_name)
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


def _scenario_truth(file_name: str) -> tuple[dict[str, Any], set[str]]:
    data = json.loads(
        (ROOT / "testdata/scenarios/scenario_truth.json").read_text(encoding="utf-8")
    )
    for scenario_set in data["sets"]:
        for record in scenario_set.get("documents", []):
            if record["file_name"] == file_name:
                return ({f["field"]: f["value"] for f in record.get("truth_fields", [])},
                        set(record.get("expect_absent", [])))
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
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "absent", "rule_would_emit": value})
            elif field in expected and not _values_agree(field, expected[field], value):
                out.append({"doc": firing["doc"], "field": field,
                            "truth": expected[field], "rule_would_emit": value})
    return out


# ------------------------------------------------------------------------------------
# dev supplements -- the filled dev split and the UNSEALED scenario sets, swept with the
# same predicate and recorded in the same artefact. Sealed documents are never opened.
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
        doc = {"corpus": "filled", "doc": record["file_name"],
               "path": str(ROOT / "testdata/filled" / record["file_name"]),
               "document_type": "pay_stub"}  # asserted by measure_filled_forms.py
        result = fires(doc)
        if result:
            fired.append({"corpus": "filled", "doc": record["file_name"], **result})
    return {"documents_swept": swept,
            "docs_fired": sorted({f["doc"] for f in fired}),
            "firings": fired,
            "conflicts": conflicts(fired),
            "target_fired": any(f["doc"] == FILLED_TARGET for f in fired)}


def _scenario_sweep() -> dict[str, Any]:
    data = json.loads(
        (ROOT / "testdata/scenarios/scenario_truth.json").read_text(encoding="utf-8")
    )
    sealed = {s["id"] for s in data["sets"] if s.get("role") == "sealed"}
    fired: list[dict[str, Any]] = []
    swept = 0
    sets_fired: set[str] = set()
    for scenario_set in data["sets"]:
        if scenario_set["id"] in sealed:
            continue
        for record in scenario_set.get("documents", []):
            swept += 1
            doc = {"corpus": "scenarios", "doc": record["file_name"],
                   "path": str(ROOT / "testdata/scenarios" / record["file_name"]),
                   "document_type": record["document_type"]}
            result = fires(doc)
            if result:
                fired.append({"corpus": "scenarios", "doc": record["file_name"],
                              "set": scenario_set["id"], **result})
                sets_fired.add(scenario_set["id"])
    return {"documents_swept": swept,
            "sealed_sets_untouched": sorted(sealed),
            "sets_fired": sorted(sets_fired),
            "firings": fired,
            "conflicts": conflicts(fired),
            "target_sets_fired": sorted(sets_fired & set(SCENARIO_TARGET_SETS))}


if __name__ == "__main__":
    if "--dev" not in sys.argv:
        raise SystemExit("usage: python loop/falsify/it-012.py --dev "
                         "(the 77-document sweep is run_phase.py p3 --iteration 12 --run)")
    artefact = ROOT / "loop" / "falsification" / "it-012.json"
    report = json.loads(artefact.read_text(encoding="utf-8")) if artefact.exists() else {}
    filled = _filled_dev_sweep()
    scenarios = _scenario_sweep()
    report["filled_dev"] = filled
    report["scenarios"] = scenarios
    report["target_fired"] = filled["target_fired"]
    if filled["conflicts"] or scenarios["conflicts"]:
        report["verdict"] = "fail"
    artefact.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8")
    print(f"filled dev: fired on {len(filled['docs_fired'])}/{filled['documents_swept']}; "
          f"conflicts {len(filled['conflicts'])}; target_fired {filled['target_fired']}")
    print(f"scenarios: fired on {len(scenarios['sets_fired'])} sets "
          f"({scenarios['documents_swept']} docs); conflicts {len(scenarios['conflicts'])}; "
          f"target sets {scenarios['target_sets_fired']}")
    print(f"updated {artefact}")
