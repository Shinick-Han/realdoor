# -*- coding: utf-8 -*-
"""it-008 firing predicate -- read-only, run by `run_phase.py p3 --iteration 8 --run`,
then `python loop/falsify/it-008.py --filled-dev` for the filled dev supplement.

The proposed rule (loop/proposals/it-008.md section 4): a pay_stub label normalizing to
`RATE OF PAY` (the period-dependent synonym) may bind a value to `hourly_rate` only when
the page itself settles the period by an arithmetic identity: the bound value `v` closes
`v x h = g` cent-exact for a printed hours-shaped token `h` (0 < h <= 744, h != 1) and a
printed cents-form money token `g`, both on the value's own page, neither the value's own
run. Unlicensed, the binding becomes an abstention.

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with the license applied to every value the five producer rules return for that binding
(the same conduct P4 places once in `_scan_page`, immediately before
`found[field_name] = resolved`; wrapping the producers instead is the only read-only
seam, and any difference between the two placements would surface as an extra flip in
P5's gate) -- and fires iff the emitted field set differs. The join in `conflicts`
falsifies real would-be emissions against each document's own truth, including
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

TARGET_DOC = "orangeusd_sample_paystub_filled.pdf"

#: The candidate table, verbatim from the proposal. pay_stub only -- the
#: employment_letter twin is out of scope by measured G3 (up_018/ho_006 correct).
PERIOD_DEPENDENT_LABELS: dict[str, dict[str, str]] = {
    "pay_stub": {"RATE OF PAY": "hourly_rate"},
}

#: Physical bound, restated the way core.columns.MAX_PERIOD_HOURS restates
#: core.verified.FALLBACK_HOURS_BOUND (31 days x 24 hours).
MAX_PERIOD_HOURS = 744.0


def _page_closure(page_words: Sequence[Any], field: dict[str, Any]) -> bool:
    """Does any printed pair h, g on the value's page close v x h = g cent-exact?

    The proposal's guards, verbatim: v > 0; h hours-shaped (no currency mark,
    0 < h <= 744, h != 1 -- the multiplicative identity testifies to nothing);
    g in printed cents form; h and g distinct tokens, neither inside the value's
    own box.
    """
    value = field.get("value")
    if not isinstance(value, (int, float)) or value <= 0:
        return False
    bbox = field.get("bbox") or [0, 0, -1, -1]
    x0, y0, x1, y1 = bbox

    def _own(w: Any) -> bool:
        return (w.x0 >= x0 - 0.5 and w.x1 <= x1 + 0.5
                and y0 - 0.5 <= w.baseline <= y1 + 0.5)

    hours: list[tuple[int, float]] = []
    money: list[tuple[int, float]] = []
    for w in page_words:
        if _own(w):
            continue
        text = w.text.strip()
        bare = text.lstrip("$").replace(",", "")
        try:
            number = float(bare)
        except ValueError:
            continue
        if not text.startswith("$") and 0 < number <= MAX_PERIOD_HOURS and number != 1:
            hours.append((id(w), number))
        if "." in bare and len(bare.rsplit(".", 1)[1]) == 2 and number > 0:
            money.append((id(w), number))
    return any(
        h_id != g_id and abs(value * h - g) < 0.005
        for h_id, h in hours
        for g_id, g in money
    )


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """Every field the extractor emits for this doc, with or without the license."""
    import pdfplumber

    import core.columns as columns
    import core.extract as ex

    doc_type = doc["document_type"]
    table = PERIOD_DEPENDENT_LABELS.get(doc_type, {})

    words_by_page: dict[int, list[Any]] = {}
    if with_rule and table:
        with pdfplumber.open(doc["path"]) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                words_by_page[number] = ex.read_words(page, number)

    def _gate(label_run: Sequence[Any], field_name: str,
              produced: dict[str, Any] | None) -> dict[str, Any] | None:
        """The candidate conduct: license or abstain. Identity when not engaged."""
        if produced is None or produced.get("certainty") == "abstain":
            return produced
        label = ex.normalize_label(ex._join_run(label_run))
        if table.get(label) != field_name:
            return produced
        page_words = words_by_page.get(produced.get("page") or 0, [])
        if _page_closure(page_words, produced):
            return produced
        return ex._abstain(
            field_name,
            "the label names a rate of an unstated period and nothing printed on the "
            "page settles it (no printed hours x this rate = a printed amount closes)",
        )

    originals = {
        "resolve": ex._resolve_value,
        "side": ex._side_by_side_value,
        "caption": ex._caption_value,
        "column": columns.column_value,
        "header": columns.header_cell_value,
    }

    def resolve(lines, label_run, column_right, field_name, *a, **k):
        return _gate(label_run, field_name,
                     originals["resolve"](lines, label_run, column_right, field_name, *a, **k))

    def side(line, label_runs, index, column_right, field_name, *a, **k):
        return _gate(label_runs[index], field_name,
                     originals["side"](line, label_runs, index, column_right, field_name, *a, **k))

    def caption(lines, label_anchors, label_run, column_right, field_name, *a, **k):
        return _gate(label_run, field_name,
                     originals["caption"](lines, label_anchors, label_run, column_right,
                                          field_name, *a, **k))

    def column(lines, label_run, column_right, field_name, *a, **k):
        return _gate(label_run, field_name,
                     originals["column"](lines, label_run, column_right, field_name, *a, **k))

    def header(lines, label_run, field_name, *a, **k):
        return _gate(label_run, field_name,
                     originals["header"](lines, label_run, field_name, *a, **k))

    if with_rule and table:
        ex._resolve_value = resolve
        ex._side_by_side_value = side
        ex._caption_value = caption
        columns.column_value = column
        columns.header_cell_value = header
    try:
        view = ex.extract_document(doc["path"], document_type=doc_type)
    finally:
        ex._resolve_value = originals["resolve"]
        ex._side_by_side_value = originals["side"]
        ex._caption_value = originals["caption"]
        columns.column_value = originals["column"]
        columns.header_cell_value = originals["header"]

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
# A withdrawal (field present without the rule, abstaining with it) has no
# `emitted_with_rule` entry and can never conflict -- the license only refuses.
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
# list is the manifest's `roles.dev`, read from the truth file, not a directory walk.
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
        "target_fired": any(f["doc"] == TARGET_DOC for f in fired),
    }


if __name__ == "__main__":
    if "--filled-dev" not in sys.argv:
        raise SystemExit("usage: python loop/falsify/it-008.py --filled-dev "
                         "(the 77-document sweep is run_phase.py p3 --iteration 8 --run)")
    artefact = ROOT / "loop" / "falsification" / "it-008.json"
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
