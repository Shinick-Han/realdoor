# -*- coding: utf-8 -*-
"""it-005 firing predicate -- read-only, run by `run_phase.py p3 --iteration 5 --run`.

The proposed change (loop/proposals/it-005.md section 4, design it-C of
ocr-extension-design.md, backlog T11), behind `REALDOOR_OCR_TOTAL_BAND`: a labeled
total band for OCR-injected pages. A page may answer gross_pay/net_pay when it prints
a header line carrying ALL FOUR anchor-only cells TOTAL GROSS | TOTAL TAXES | TOTAL
DEDUCTIONS | NET PAY (each exactly once on the whole page -- the instance-conflict
guard: a page whose stub instances repeat the labels has not said which band is
which), a value line beneath in which each of the four cells owns exactly one number
token (a token overlapping two cells, or two tokens in one cell, refuses), and the
identity TOTAL GROSS = TOTAL TAXES + TOTAL DEDUCTIONS + NET PAY closes at cent grain.
Across pages, candidates that disagree on any field withdraw everything (the
cross-page half of the guard: page order must never pick between stub instances).

`fires(doc)` runs the committed extractor, then computes the candidate's additions
over the same word streams (the rule only ever fills blanks), and fires iff the
emitted field set differs. `conflicts` joins every changed field against that
document's own truth, INCLUDING `expect_absent`.
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

TARGET_DOC = "hi_ags_pay_statement_example_2021.pdf"

#: The four anchor-only strings, compared space-stripped after `normalize_label`:
#: OCR drops word spaces (measured: 'TOTALGROSS', 'FEDTAXABLE GROSS'), and comparing
#: with spaces removed adds no character while keeping the match exact -- the
#: strip-spaces invariant `ocr/ocr_extract.py` already relies on. FED TAXABLE GROSS
#: never matches any of these (whole-cell equality, no substrings).
ROLES = {
    "TOTALGROSS": "gross",
    "TOTALTAXES": "taxes",
    "TOTALDEDUCTIONS": "deductions",
    "NETPAY": "net",
}


def _stripped(text: str) -> str:
    from core.extract import normalize_label

    return normalize_label(text).replace(" ", "")


def band_recover(words, convention, wanted, known_gross=None) -> dict[str, dict[str, Any]]:
    """The candidate conduct: one page's labeled-band answers, or {} = abstain.

    `known_gross` is the gross another path already answered, if any: a band whose
    gross cell disagrees with it is refused whole -- the rule may fill blanks, never
    contradict an answer."""
    from core import arithmetic as ar
    from core.extract import _join_run, _run_box, _split_runs, group_lines, parse_value

    lines = group_lines(words)

    # Every run on the page that IS one of the four labels, by role.
    label_runs: dict[str, list[tuple[Any, Any]]] = {r: [] for r in ROLES.values()}
    for line in lines:
        for run in _split_runs(line):
            role = ROLES.get(_stripped(_join_run(run)))
            if role is not None:
                label_runs[role].append((line, run))

    # Each label exactly once on the page -- a page that repeats them (two stub
    # instances in one stream) has not said which band is which. Refuse.
    if any(len(v) != 1 for v in label_runs.values()):
        return {}
    cells = {role: label_runs[role][0][1] for role in label_runs}
    header_lines = {id(label_runs[role][0][0]) for role in label_runs}
    if len(header_lines) != 1:
        return {}  # the four cells must be one printed header line
    header_baseline = next(iter(label_runs.values()))[0][0][0].baseline
    page = cells["gross"][0].page

    spans = {
        role: (min(w.x0 for w in run), max(w.x1 for w in run))
        for role, run in cells.items()
    }

    def owners(token) -> list[str]:
        return [
            role for role, (x0, x1) in spans.items()
            if not (token.x1 <= x0 or x1 <= token.x0)
        ]

    # The value line: the nearest line below the header line that carries at least
    # one number token overlapping any cell.
    tokens = ar.number_tokens(words)
    below = [
        t for t in tokens
        if t.page == page
        and t.baseline < header_baseline - ar.BASELINE_TOLERANCE
        and owners(t)
    ]
    if not below:
        return {}
    value_baseline = max(t.baseline for t in below)  # the nearest line below
    row = [t for t in below if abs(t.baseline - value_baseline) <= ar.BASELINE_TOLERANCE]

    owned: dict[str, Any] = {}
    for t in row:
        who = owners(t)
        if len(who) != 1:
            return {}  # a token two cells could claim: not plain enough
        if who[0] in owned:
            return {}  # two tokens in one cell
        owned[who[0]] = t
    if set(owned) != set(ROLES.values()):
        return {}

    values = {}
    for role, t in owned.items():
        parsed = ar.parse_number(t.text)
        if parsed is None or parsed[1] != 2:
            return {}  # money is printed with its cents; anything else is not money
        values[role] = parsed[0]
    if round(values["taxes"] + values["deductions"] + values["net"], 2) != round(values["gross"], 2):
        return {}  # the band identity is the license; no closure, no answer
    if not (values["gross"] > 0 and 0 < values["net"] <= values["gross"]
            and values["taxes"] >= 0 and values["deductions"] >= 0):
        return {}
    if known_gross is not None and abs(values["gross"] - float(known_gross)) > 1e-9:
        return {}  # the band contradicts an already-answered gross: refuse whole

    chain = (
        f"printed band TOTAL GROSS = TOTAL TAXES + TOTAL DEDUCTIONS + NET PAY: "
        f"{owned['taxes'].text} + {owned['deductions'].text} + {owned['net'].text} = "
        f"{owned['gross'].text} exact, each value the single token under its own "
        f"printed header cell, each label printed exactly once on the page"
    )
    out: dict[str, dict[str, Any]] = {}
    for name, role in (("gross_pay", "gross"), ("net_pay", "net")):
        if name not in wanted:
            continue
        token = owned[role]
        value, _clean = parse_value(name, token.text)
        out[name] = {
            "field": name,
            "value": value,
            "page": token.page,
            "bbox": _run_box([words[token.index]], convention),
            "bbox_units": "pdf_points_bottom_left_origin",
            "certainty": "low",
            "evidence_kind": "extracted",
            "source_text": token.text,
            "notes": f"labeled total band accepted by arithmetic identity (see core/total_band.py) | {chain}",
        }
    return out


def reconcile(per_page: list[dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Cross-page instance-conflict guard: any disagreement on any field withdraws
    everything -- page order must never decide between stub instances."""
    merged: dict[str, dict[str, Any]] = {}
    for got in per_page:
        for name, payload in got.items():
            if name in merged and merged[name]["value"] != payload["value"]:
                return {}
            merged.setdefault(name, payload)
    return merged


# --------------------------------------------------------------------------------------
# two extractions per document
# --------------------------------------------------------------------------------------

_MEMO: dict[tuple[str, int], list] = {}
_REAL_REGION_OCR = None


def _memoized_region_ocr(pdf_source, plumber_page, page_number, text_words):
    key = (str(pdf_source), page_number)
    if key not in _MEMO:
        _MEMO[key] = _REAL_REGION_OCR(pdf_source, plumber_page, page_number, text_words)
    return _MEMO[key]


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """The committed extractor's emissions, plus -- with the rule -- the candidate's
    blank-filling additions computed over the same word streams and reconciled
    across pages, exactly as the implementation's call site will."""
    global _REAL_REGION_OCR
    import pdfplumber

    import core.extract as ex
    import core.ocr_words as ow

    if _REAL_REGION_OCR is None:
        _REAL_REGION_OCR = ow.region_ocr_words

    ow.region_ocr_words = _memoized_region_ocr
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
        base = {
            f["field"]: f["value"]
            for f in view["fields"]
            if f.get("certainty") != "abstain" and f.get("value") is not None
        }
        if not with_rule:
            return base

        doc_type = doc["document_type"]
        blanks = [
            name for name in ex.EXPECTED_FIELDS.get(doc_type, ())
            if name in ("gross_pay", "net_pay") and name not in base
        ]
        if not blanks:
            return base
        known_gross = base.get("gross_pay")
        per_page = []
        with pdfplumber.open(str(doc["path"])) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = ex.read_words(page, page_number)
                injected = _memoized_region_ocr(doc["path"], page, page_number, words)
                if not injected:
                    continue
                got = band_recover([*words, *injected], ex.LineBoxConvention(), blanks,
                                   known_gross=known_gross)
                if got:
                    per_page.append(got)
        for name, payload in reconcile(per_page).items():
            base[name] = payload["value"]
        return base
    finally:
        ow.region_ocr_words = _REAL_REGION_OCR


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
