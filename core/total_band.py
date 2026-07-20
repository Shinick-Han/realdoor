# -*- coding: utf-8 -*-
"""total_band.py -- a labeled total band read off a page's own printed header cells,
emitted only when the band's arithmetic closes, with a guard for pages of
disagreeing stub instances.

THE LAYOUT THIS READS
---------------------
The Hawaii AGS pay-statement sample embeds its stub as a raster image whose summary
band is a printed header line of five cells with one value line beneath::

    TOTAL GROSS | FED TAXABLE GROSS | TOTAL TAXES | TOTAL DEDUCTIONS | NET PAY
       2,328.01 |                   |      444.00 |           372.63 | 1,511.38

No existing rule reads this shape: it is not a column run (one value per cell), not a
label-adjacent value (the identity paths do not do adjacency), and on this document
the earnings column's own total misreads (`'2.328.01'`, parse-refused), so the
verified/shredded chain is silent. The identity the band prints about itself --
444.00 + 372.63 + 1,511.38 = 2,328.01 exact -- is the license.

WHAT LICENSES THE FOUR STRINGS
------------------------------
`TOTAL GROSS`, `TOTAL TAXES`, `TOTAL DEDUCTIONS`, `NET PAY` are anchor-only strings,
the `core.shredded._ROW_LABELS` precedent: they name the identity's members and never
become fields. Matching is whole-cell, exact after `normalize_label` with spaces
removed -- the OCR engine drops word spaces (measured: `'TOTALGROSS'`), and removing
spaces adds no character. `FED TAXABLE GROSS` can never match any of the four
(whole-cell equality, no substrings): that cell is the named adjacency hazard, and a
value beneath it is owned by no band cell and ignored.

THE INSTANCE-CONFLICT GUARD, BOTH HALVES
----------------------------------------
The hi_ags document prints THREE stub instances with three different value sets, and
nothing printed selects one. (1) Within a page: any of the four labels appearing more
than once refuses the page whole -- a page whose stubs repeat the labels has not said
which band is which (page 2's two merged instances, measured, refuse exactly here).
(2) Across pages: `reconcile` withdraws every candidate when two pages disagree on
any field -- `found.setdefault`'s page order is never allowed to choose between stub
instances. What remains, said honestly: page 1 emits because page 2 refuses; the
guard guarantees no conflicting instance can ship a value, not that the surviving
instance is the transcriber's choice.

Like the other identity paths: no model, certainty capped at "low", and the whole
path lives under `REALDOOR_OCR_TOTAL_BAND` -- with the flag at `0` this module is
never imported and `extract_document` is bit-identical to what it was. It runs only
on pages that carry `core.ocr_words` injections, so the text path never sees it
(loop iteration it-005, falsified over all 77 corpus documents first --
loop/falsification/it-005.json).
"""
from __future__ import annotations

from typing import Any, Sequence

from core import arithmetic as ar
from core.extract import (
    LineBoxConvention,
    Word,
    _join_run,
    _run_box,
    _split_runs,
    group_lines,
    normalize_label,
    parse_value,
)

#: Note prefix carried by every field this module produces, so a reader counting
#: fields can separate this path from the others without reading code.
TOTAL_BAND_NOTE = "labeled total band accepted by arithmetic identity (see core/total_band.py)"

#: The four anchor-only strings, keyed by their space-stripped normalized form.
#: Closed and hand-written, like every vocabulary in this repository.
_ROLES = {
    "TOTALGROSS": "gross",
    "TOTALTAXES": "taxes",
    "TOTALDEDUCTIONS": "deductions",
    "NETPAY": "net",
}

#: The fields this module may emit. taxes/deductions exist only to close the identity.
EMITTABLE = ("gross_pay", "net_pay")


def _stripped(text: str) -> str:
    return normalize_label(text).replace(" ", "")


def recover(
    words: Sequence[Word],
    convention: LineBoxConvention,
    wanted: Sequence[str],
    known_gross: float | None = None,
) -> dict[str, dict[str, Any]]:
    """gross_pay / net_pay for one page, or {} -- meaning abstain, exactly as before.

    Everything must hold at once: each of the four labels exactly once on the page
    (the within-page instance guard); all four cells on one printed line; a value
    line beneath in which every cell owns exactly one number token and every token
    exactly one cell; all four tokens money in cents-form; the band identity
    `gross = taxes + deductions + net` at cent grain; gross > 0, 0 < net <= gross,
    taxes >= 0, deductions >= 0; and, when another path has already answered
    gross_pay (`known_gross`), agreement with it. Any refusal returns {}.
    """
    lines = group_lines(words)

    label_runs: dict[str, list[tuple[Sequence[Word], list[Word]]]] = {
        role: [] for role in _ROLES.values()
    }
    for line in lines:
        for run in _split_runs(line):
            role = _ROLES.get(_stripped(_join_run(run)))
            if role is not None:
                label_runs[role].append((line, run))

    if any(len(found_runs) != 1 for found_runs in label_runs.values()):
        return {}  # a label missing, or printed twice: no single band is named
    cells = {role: label_runs[role][0][1] for role in label_runs}
    if len({id(label_runs[role][0][0]) for role in label_runs}) != 1:
        return {}  # the four cells must be one printed header line
    header_baseline = cells["gross"][0].baseline
    page = cells["gross"][0].page

    spans = {
        role: (min(w.x0 for w in run), max(w.x1 for w in run))
        for role, run in cells.items()
    }

    def owners(token: ar.NumberToken) -> list[str]:
        return [
            role for role, (x0, x1) in spans.items()
            if not (token.x1 <= x0 or x1 <= token.x0)
        ]

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

    owned: dict[str, ar.NumberToken] = {}
    for token in row:
        who = owners(token)
        if len(who) != 1:
            return {}  # a token two cells could claim: not plain enough
        if who[0] in owned:
            return {}  # two tokens in one cell
        owned[who[0]] = token
    if set(owned) != set(_ROLES.values()):
        return {}

    values: dict[str, float] = {}
    for role, token in owned.items():
        parsed = ar.parse_number(token.text)
        if parsed is None or parsed[1] != 2:
            return {}  # money prints its cents; a separator misread never parses
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
            "notes": f"{TOTAL_BAND_NOTE} | {chain}",
        }
    return out


def reconcile(
    per_page: Sequence[dict[str, dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """The cross-page half of the instance-conflict guard.

    Candidates from different pages that disagree on ANY field withdraw everything:
    page order (`found.setdefault`) must never be what decides between two stub
    instances that each closed their own band.
    """
    merged: dict[str, dict[str, Any]] = {}
    for got in per_page:
        for name, payload in got.items():
            if name in merged and merged[name]["value"] != payload["value"]:
                return {}
            merged.setdefault(name, payload)
    return merged
