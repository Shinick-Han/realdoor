# -*- coding: utf-8 -*-
"""it-004 firing predicate -- read-only, run by `run_phase.py p3 --iteration 4 --run`.

The proposed change (loop/proposals/it-004.md section 4, design it-B of
ocr-extension-design.md, backlog T10): two completions of the existing identity chain,
active ONLY on pages that carry OCR-injected words (the it-003 injection layer), behind
`REALDOOR_OCR_BAND_ROLE`:

  (1) band-role completion -- a `rate x 1 = rate` coincidence (the multiplicative
      identity) stops testifying that a line is an earnings row, so the deductions+net
      band that shares that line becomes visible to the EXISTING net rule (the last
      term of a run summing to the accepted gross);
  (2) named-row hours -- `regular_hours` candidates are no longer every member of the
      hours column but exactly the hours factor on the anchored row that prints the
      word REGULAR, and only under a printed column header that is exactly HOURS
      (unqualified -- lcc's `Hours or Units` refuses by its own wording).

`fires(doc)` runs the full extractor twice in this process -- once as committed, once
with `verified.verify_page` patched to the candidate conduct on exactly the pages that
received injected words -- and fires iff the emitted field set differs. `conflicts`
joins every changed field against that document's own truth, INCLUDING
`expect_absent`: an invented value is exactly as fatal as a wrong one.
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

TARGET_DOC = "ou_sample_check_stub.pdf"
TARGET_DOC_2 = "osu_sample_earnings_statement.pdf"

#: The two anchor-only strings of the candidate rule. Closed, exact-match after
#: `normalize_label` (design hazard 6: no fuzzy matching of OCR label text, ever).
ROW_WORD = "REGULAR"
HOURS_HEADER = "HOURS"


# --------------------------------------------------------------------------------------
# the candidate conduct, verbatim (proposal section 4)
# --------------------------------------------------------------------------------------


def _degenerate(product) -> bool:
    """`x * 1 = x` is the multiplicative identity, not a rate-times-hours identity:
    every number beside a printed 1 satisfies it, so it cannot testify that its line
    is an earnings row."""
    return product.rate.value == 1.0 or product.hours.value == 1.0


def _is_alpha_run(run) -> bool:
    from core.extract import _join_run

    text = _join_run(run)
    return any(c.isalpha() for c in text) and not any(c.isdigit() for c in text)


def _named_regular_hours(words, item, hours_values: set, rate_values: set) -> set:
    """The hours factors on anchored rows that print the word REGULAR, admitted only
    under a printed column header that is exactly HOURS. Empty set = refuse."""
    from core import arithmetic as ar
    from core.extract import _join_run, _split_runs, group_lines, normalize_label

    if not hours_values or (set(hours_values) & set(rate_values)):
        return set()
    seen: dict[int, Any] = {}
    for p in item.products:
        for t in (p.rate, p.hours):
            if t.value in hours_values:
                seen[id(t)] = t
    hours_tokens = list(seen.values())
    if not hours_tokens:
        return set()
    span0 = min(t.x0 for t in hours_tokens)
    span1 = max(t.x1 for t in hours_tokens)
    top = max(t.baseline for t in hours_tokens)
    page = hours_tokens[0].page

    # L5: the nearest alphabetic run above the column that shares x-extent with it
    # must be exactly HOURS. Nearest-and-exact needs no distance constant: a nearer
    # foreign header ("Units", "Hours or Units") refuses by its own wording.
    best: tuple[float, list] | None = None
    for line in group_lines(words):
        if not line or line[0].page != page:
            continue
        dy = line[0].baseline - top
        if dy <= ar.BASELINE_TOLERANCE:
            continue
        overlapping = [
            run for run in _split_runs(line)
            if _is_alpha_run(run)
            and not (max(w.x1 for w in run) <= span0 or span1 <= min(w.x0 for w in run))
        ]
        if not overlapping:
            continue
        if best is None or dy < best[0]:
            best = (dy, overlapping)
    if best is None or len(best[1]) != 1:
        return set()
    if normalize_label(_join_run(best[1][0])) != HOURS_HEADER:
        return set()

    named: set = set()
    for p in item.products:
        if p.hours.value in hours_values:
            hours_factor = p.hours
        elif p.rate.value in hours_values:
            hours_factor = p.rate
        else:
            continue
        row = [
            w for w in words
            if w.page == p.amount.page
            and abs(w.baseline - p.amount.baseline) <= ar.BASELINE_TOLERANCE
        ]
        if any(normalize_label(w.text) == ROW_WORD for w in row):
            named.add(hours_factor.value)
    return named


def verify_page_band_role(words, document_type, found, convention, wanted):
    """`core.verified.verify_page` with the two it-B completions. Everything not
    marked MOD is the committed body, called through `verified`'s own helpers."""
    from core import arithmetic as ar
    from core import verified as v

    tokens = ar.number_tokens(words)
    if len(tokens) < 3:
        return {}, {}
    bound, bound_reason = v.hours_bound(found)
    anchored = v._anchored_runs(tokens, bound)

    candidates: dict[str, list] = {name: [] for name in wanted}

    # MOD (1): degenerate products do not put their line into the band exclusion set.
    anchored_lines = {
        p.amount.baseline for a in anchored for p in a.products if not _degenerate(p)
    }
    gross_token = None
    gross_candidates: list = []
    for item in anchored:
        identities = {"row_product", "column_sum"}
        bands = v._bands(tokens, item.total, anchored_lines)
        if bands:
            identities.add("total_band")
        gross_candidates.append(
            v.Candidate(
                field="gross_pay",
                token=item.total,
                supports=["S1"],
                identities=identities,
                detail=(
                    f"{' + '.join(t.text for t in item.run)} = {item.total.text} in one "
                    f"aligned column, anchored by {item.products[0].rate.text} x "
                    f"{item.products[0].hours.text} = {item.products[0].amount.text} on one "
                    f"printed line (hours ceiling {bound:g}: {bound_reason})"
                ),
            )
        )
    if "gross_pay" in candidates:
        candidates["gross_pay"].extend(gross_candidates)

    gross_values = {c.token.value for c in gross_candidates}
    gross_value = next(iter(gross_values)) if len(gross_values) == 1 else None
    if len(gross_values) == 1:
        gross_token = gross_candidates[0].token

    if gross_token is not None and "net_pay" in candidates:
        for band in v._bands(tokens, gross_token, anchored_lines):
            tail = band.run[-1]
            candidates["net_pay"].append(
                v.Candidate(
                    field="net_pay",
                    token=tail,
                    supports=["S1"],
                    identities={"total_band",
                                "column_sum" if band.kind == "column" else "line_sum"},
                    detail=(
                        f"{' + '.join(t.text for t in band.run)} = {band.total.text}, a "
                        f"consecutive run of one {band.kind} that does not touch the earnings "
                        f"rows; the last term is what is left after the deductions"
                    ),
                )
            )

    for item in anchored:
        hours_values, rate_values = v._factor_columns(tokens, item)
        if not hours_values:
            continue
        by_value: dict[float, Any] = {}
        for token in sorted(
            [p.hours for p in item.products] + [p.rate for p in item.products],
            key=lambda t: (-t.baseline, t.x0),
        ):
            by_value.setdefault(token.value, token)
        detail = (
            "the two factors were told apart by measurement: the hours on these lines add up "
            "to a printed total and the rates do not"
        )
        # MOD (2): hours candidates are the REGULAR-named row's factor, or nothing.
        named_hours = _named_regular_hours(words, item, hours_values, rate_values)
        for name, values in (("regular_hours", named_hours), ("hourly_rate", rate_values)):
            if name not in candidates:
                continue
            for value in values:
                token = by_value.get(value)
                if token is None:
                    continue
                candidates[name].append(
                    v.Candidate(
                        field=name,
                        token=token,
                        supports=["S1"],
                        identities={"row_product"} | ({"column_sum"} if name == "regular_hours" else set()),
                        detail=detail,
                    )
                )

    answers: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    for name in wanted:
        survivors = [
            c
            for c in candidates.get(name, [])
            if v._veto_grounding(words, c.token)
            and v._veto_type(name, c.token)
            and v._veto_bound(name, c.token.value, bound, gross_value)
        ]
        distinct = {c.token.value for c in survivors}
        if len(distinct) == 1:
            best = max(survivors, key=lambda c: len(c.identities))
            answers[name] = v._accept(best, words, convention, bound_reason)
            continue
        proposal = v._propose(words, document_type, name, bound, gross_value, convention)
        if proposal is not None:
            proposals[name] = proposal
    return answers, proposals


# --------------------------------------------------------------------------------------
# two extractions per document
# --------------------------------------------------------------------------------------

_MEMO: dict[tuple[str, int], list] = {}
_INJECTED_IDS: set[int] = set()
_REAL_REGION_OCR = None


def _memoized_region_ocr(pdf_source, plumber_page, page_number, text_words):
    """The committed OCR pass, memoized per (document, page) so the two runs pay the
    engine once, with every returned Word's id recorded so the patched verify_page can
    tell an injected page from a plain one -- the same condition (`bool(injected)`)
    the implementation will read directly."""
    key = (str(pdf_source), page_number)
    if key not in _MEMO:
        _MEMO[key] = _REAL_REGION_OCR(pdf_source, plumber_page, page_number, text_words)
    words = _MEMO[key]
    _INJECTED_IDS.update(id(w) for w in words)
    return words


def _emissions(doc: dict, with_rule: bool) -> dict[str, Any]:
    """Every field the extractor emits for this doc, with or without the candidate."""
    global _REAL_REGION_OCR
    import core.extract as ex
    import core.ocr_words as ow
    import core.verified as verified

    if _REAL_REGION_OCR is None:
        _REAL_REGION_OCR = ow.region_ocr_words

    original_vp = verified.verify_page

    def patched_vp(words, doc_type, found, convention, wanted):
        if with_rule and any(id(w) in _INJECTED_IDS for w in words):
            return verify_page_band_role(words, doc_type, found, convention, wanted)
        return original_vp(words, doc_type, found, convention, wanted)

    ow.region_ocr_words = _memoized_region_ocr
    verified.verify_page = patched_vp
    try:
        view = ex.extract_document(doc["path"], document_type=doc["document_type"],
                                   fallback_mapper=ex.synonym_mapper)
    finally:
        verified.verify_page = original_vp
        ow.region_ocr_words = _REAL_REGION_OCR

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
    """The same comparison the measuring harness makes, imported, not re-invented."""
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
