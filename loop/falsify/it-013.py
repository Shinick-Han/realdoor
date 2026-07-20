# -*- coding: utf-8 -*-
"""it-013 firing predicate -- read-only, run by `run_phase.py p3 --iteration 13 --run`,
then `python loop/falsify/it-013.py --dev-corpora` for the filled/scenarios supplement.

The proposed change (loop/proposals/it-013.md section 4) is a REFUSAL: on a band that
offers three or more candidates for one field, no run may anchor that field. It reads no
value and it can only ever withhold one, so the sweep is a diff of the flag against
itself: `REALDOOR_OPTION_BAND=0` (the committed behaviour) against `=1` (the proposal),
both with the model mapper ON, and it fires iff the emitted field set differs.

**The hazard is inverted, and so is the truth join.** For a rule that adds a reading, a
conflict is an emission contradicting truth. For a rule that removes one, the thing that
must not happen is losing a CORRECT value -- so `conflicts()` reports both directions:

  1. flag-on emits a value that truth contradicts, or that truth lists as absent. (A
     refusal cannot really do this, but the check is kept: it is what would catch the rule
     shifting a column boundary and moving some other field's answer.)
  2. flag-off emitted a value that AGREES with truth, and flag-on no longer emits it or
     emits something else. That is a correct reading destroyed, it is exactly what G3
     fails on, and for this iteration it is the only conflict that is likely.

Requires REALDOOR_LABEL_LLM=1 and a key. With the model off the option words in
`wa_dshs`/`seattle`/`mnhousing` are not named by either frozen table, so the menu never
forms, the rule has nothing to refuse, and the sweep would prove nothing about the
defect it exists to close. The sealed hold-outs are never opened.
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

#: The iteration ships two refusals, each with its own flag because each rests on a
#: different printed thing. The sweep toggles them together, because what G5 and G7 ask
#: about is this iteration's whole diff.
#:
#: A third refusal was written, measured and DROPPED: refusing a column whose aligned
#: candidates parse to different values would have closed `ca_dlse_paystub_piecerate`'s
#: `hourly_rate`, and it fired nowhere else in 77 documents -- but it is falsified by
#: `core/test_extract_reading.py::TestRightAlignedColumnsAreMeasured`, where `ext_unc.pdf`
#: prints the current-period figure and its year-to-date rival in one right-aligned column
#: under `NET PAY` and reading the closer one is a deliberate, tested capability. The
#: corpus sweep did not catch that; the test suite did. See loop/reports/it-013.md.
FLAGS = ("REALDOOR_OPTION_BAND", "REALDOOR_GLOSS_COLON")

#: The pack is the deterministic layer's own territory and its phrases are all canonical.
#: A pack firing would mean the refusal reached a document whose every label the frozen
#: table names, which is a menu we invented -- worth failing on rather than explaining.
PACK_MUST_NOT_FIRE = True


def _emitted(view: dict) -> dict[str, Any]:
    return {
        f["field"]: f["value"]
        for f in view["fields"]
        if f.get("certainty") != "abstain" and f.get("value") is not None
    }


def _extract(doc: dict, flag: str) -> dict[str, Any]:
    import core.extract as ex

    previous = {name: os.environ.get(name) for name in FLAGS}
    for name in FLAGS:
        os.environ[name] = flag
    try:
        kwargs: dict[str, Any] = {"document_type": doc.get("document_type")}
        if doc.get("document_id"):
            kwargs["document_id"] = doc["document_id"]
        tracker = ex.tracking_layered_mapper(doc.get("document_type") or "")
        return _emitted(ex.extract_document(doc["path"], fallback_mapper=tracker, **kwargs))
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def fires(doc: dict) -> dict | None:
    base = _extract(doc, "0")     # committed behaviour
    ruled = _extract(doc, "1")    # the proposal

    if base == ruled:
        return None

    changed = sorted(
        (set(base) ^ set(ruled))
        | {k for k in set(base) & set(ruled) if base[k] != ruled[k]}
    )
    return {
        "field": ", ".join(changed),
        "value": {k: {"flag_off": base.get(k), "flag_on": ruled.get(k)} for k in changed},
        "withheld": {k: base[k] for k in changed if k in base and k not in ruled},
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
        if firing.get("corpus") == "pack" and PACK_MUST_NOT_FIRE:
            out.append({
                "doc": firing["doc"], "field": firing.get("field"),
                "truth": "<the refusal must not reach a pack document>",
                "rule_would_emit": firing.get("emitted_with_rule"),
            })
        expected, absent = _truth_for(firing["corpus"], firing["doc"])

        # direction 1: the rule leaves a value truth contradicts
        for field, value in (firing.get("emitted_with_rule") or {}).items():
            if field in absent:
                out.append({"doc": firing["doc"], "field": field,
                            "truth": "absent", "rule_would_emit": value,
                            "direction": "emits against truth"})
            elif field in expected and not _values_agree(field, expected[field], value):
                out.append({"doc": firing["doc"], "field": field,
                            "truth": expected[field], "rule_would_emit": value,
                            "direction": "emits against truth"})

        # direction 2 -- the one that matters here: a CORRECT value destroyed
        for field, value in (firing.get("withheld") or {}).items():
            if field in expected and _values_agree(field, expected[field], value):
                out.append({"doc": firing["doc"], "field": field,
                            "truth": expected[field], "rule_withheld": value,
                            "direction": "withholds a correct value"})
    return out


# ------------------------------------------------------------------------------------
# dev-corpora supplement -- the manifest carries neither `filled` nor `scenarios`
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
        raise SystemExit("usage: python loop/falsify/it-013.py --dev-corpora "
                         "(the 77-document sweep is run_phase.py p3 --iteration 13 --run)")
    if os.environ.get("REALDOOR_LABEL_LLM") != "1":
        raise SystemExit("refusing to sweep with the model off: the menus this rule "
                         "refuses are named by the model, not by either frozen table, so "
                         "the sweep would prove nothing. Set REALDOOR_LABEL_LLM=1.")

    artefact = ROOT / "loop" / "falsification" / "it-013.json"
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
