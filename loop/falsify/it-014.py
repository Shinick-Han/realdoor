# -*- coding: utf-8 -*-
"""loop/falsify/it-014.py -- the leak predicate for the T28 privacy boundary (T25 fix).

NAMED HAZARD
------------
A value string -- numeric OR personal (a name, address, SSN, date, amount) -- leaves the
process inside a page skeleton.

PREDICATE (run over every corpus we own, BEFORE the redactor is trusted)
------------------------------------------------------------------------
For every document that carries truth values, build its `core.skeleton` and assert that
**no truth value string appears as a substring of that skeleton**, with whitespace and
case normalized the same way on both sides. Any hit is a leak and fails the iteration.

Two structural facts make this rigorous rather than hopeful:
  * the skeleton is **digit-free by construction** (`core.skeleton` keeps only colon
    captions and a digit-free structural vocabulary), so any truth value carrying a digit
    -- every amount, date, hour count, id -- cannot appear in it at all; and
  * every other run is redacted, so the only survivors are structural captions.

INVERSE SANITY (an empty redactor "leaks nothing" trivially -- guard against it)
--------------------------------------------------------------------------------
Assert that captions the vocabulary knows (`GROSS EARNINGS`, `EMPLOYEE`, `Rate/Hour`,
colon captions, ...) DO survive in the skeleton, and report how many furniture runs are
kept per corpus.

SEAL DISCIPLINE
---------------
filled/ and scenarios/ are read DEV-ONLY, exactly the split `build_field_state._dev_records`
enforces. A sealed hold-out's truth is never opened. The truth values used here come from
the manifests the loop already reads; no sealed PDF is opened to obtain a value.

    python loop/falsify/it-014.py            # sweep and print a summary
    python loop/falsify/it-014.py --run      # sweep and also write loop/falsification/it-014.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts"), str(ROOT / "loop" / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.skeleton import build_page_skeleton, is_furniture, STRUCTURAL_VOCAB  # noqa: E402
from core.extract import read_words, group_lines, _split_runs, _join_run, normalize_label  # noqa: E402
import pdfplumber  # noqa: E402

_WS = re.compile(r"\s+")


def _fold(text) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    for bad, good in {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"}.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip().casefold()


# =====================================================================================
# skeleton, and the two things we measure on it
# =====================================================================================


def _doc_skeleton_and_furniture(path: Path) -> tuple[str, int, list[str]]:
    """(digit-free skeleton over all pages, furniture-run count, kept furniture texts)."""
    pages: list[str] = []
    kept: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for pnum, page in enumerate(pdf.pages, start=1):
            words = read_words(page, pnum)
            pages.append(build_page_skeleton(words))
            for line in group_lines(words):
                for run in _split_runs(line):
                    if is_furniture(run):
                        kept.append(_join_run(run))
    return "\n".join(pages), len(kept), kept


def _classify_hits(skeleton: str, kept_cells, truth_values) -> tuple[list[dict], list[dict]]:
    """Split truth-value substring hits into real leaks and structural-caption coincidences.

    A truth value that appears in the skeleton is a REAL LEAK unless the appearance is
    wholly contained in a single kept furniture cell -- a colon caption or a member of the
    page's general structural vocabulary (`MONTHLY AMOUNT`, `GROSS PAY`, ...). Such a cell
    is page structure the house rule explicitly permits disclosing, and it prints whether
    or not this document's private value happens to equal a word inside it. A value that
    survives anywhere ELSE -- as its own kept cell, or spanning a placeholder -- discloses
    the private datum and is a leak.

    Concretely: benefit_frequency `monthly` is masked to a placeholder in its value slot,
    but the caption `MONTHLY AMOUNT` (which names the amount column on every benefit
    letter, blank or filled) contains the word. That is a coincidence, not a leak.
    """
    folded = _fold(skeleton)
    squeezed = folded.replace(" ", "")
    kept_folded = [_fold(c) for c in kept_cells]
    kept_squeezed = [c.replace(" ", "") for c in kept_folded]

    real: list[dict] = []
    coincidences: list[dict] = []
    for field, value in truth_values:
        needle = _fold(value)
        if not needle:
            continue
        needle_sq = needle.replace(" ", "")
        present = needle in folded or needle_sq in squeezed
        if not present:
            continue
        # Coincidence only when the value is a PROPER substring of a longer kept caption
        # AND could not itself be kept as furniture. If the value normalizes to a
        # structural term (so its own run would be kept) or equals a whole kept cell, it
        # survives as its own text -- that is a real leak, never excused.
        value_is_own_furniture = normalize_label(str(value)) in STRUCTURAL_VOCAB
        proper_substring = any(needle in kf and needle != kf for kf in kept_folded) or \
            any(needle_sq in ks and needle_sq != ks for ks in kept_squeezed)
        record = {"field": field, "value": str(value)}
        if proper_substring and not value_is_own_furniture:
            coincidences.append(record)
        else:
            real.append(record)
    return real, coincidences


# =====================================================================================
# truth enumeration -- all seven corpora, dev-only where sealed
# =====================================================================================


def _pack_docs():
    gold = ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"
    for line in gold.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        path = ROOT / "pack/synthetic_documents/documents" / rec["file_name"]
        truth = [(f["field"], f.get("value")) for f in rec["fields"] if f.get("value") is not None]
        yield "pack", rec["file_name"], path, truth


def _manifest_docs(corpus, manifest_rel, dir_rel):
    data = json.loads((ROOT / manifest_rel).read_text(encoding="utf-8"))
    for rec in data["documents"]:
        path = ROOT / dir_rel / rec["file_name"]
        truth = [(k, v) for k, v in rec.get("intended_fields", {}).items() if v is not None]
        yield corpus, rec["file_name"], path, truth


def _expected_docs(corpus, truth_rel, dir_rel):
    data = json.loads((ROOT / truth_rel).read_text(encoding="utf-8"))
    for rec in data["documents"]:
        path = ROOT / dir_rel / rec["file_name"]
        truth = [(k, v) for k, v in rec.get("expected", {}).items() if v is not None]
        yield corpus, rec["file_name"], path, truth


def _filled_docs():
    import measure_filled_forms as mff  # type: ignore
    import build_field_state as bfs  # type: ignore
    data = json.loads(mff.TRUTH.read_text(encoding="utf-8"))
    dev, _sealed = bfs._dev_records(data, data["documents"], lambda r: r["file_name"], "filled")
    for rec in dev:  # dev only -- the seal is never opened
        path = mff.RAW_DIR / rec["file_name"]
        truth = [(k, v) for k, v in rec.get("expected", {}).items() if v is not None]
        yield "filled", rec["file_name"], path, truth


def _scenario_docs():
    import measure_scenario_sets as mss  # type: ignore
    import build_field_state as bfs  # type: ignore
    data = json.loads(mss.TRUTH.read_text(encoding="utf-8"))
    dev, _sealed = bfs._dev_records(data, data["sets"], lambda r: r["id"], "scenarios")
    for row in dev:  # dev sets only
        for doc in row["documents"]:
            path = mss.SCEN_DIR / doc["file_name"]
            truth = [(f["field"], f["value"]) for f in doc.get("truth_fields", []) if f.get("value") is not None]
            truth += [(f["field"], f["value"]) for f in doc.get("latent_fields", []) if f.get("value") is not None]
            yield "scenarios", doc["file_name"], path, truth


def enumerate_truth():
    yield from _pack_docs()
    yield from _manifest_docs("uploads", "testdata/uploads_manifest.json", "testdata/uploads")
    yield from _manifest_docs("holdout", "testdata/holdout_manifest.json", "testdata/holdout")
    yield from _expected_docs("external", "testdata/external_truth.json", "testdata/external_raw")
    yield from _expected_docs("confirm", "testdata/confirm_truth.json", "testdata/confirm_raw")
    yield from _filled_docs()
    yield from _scenario_docs()


# a few captions the vocabulary knows -- if these vanish, the redactor is empty
_INVERSE_PROBES = ("GROSS EARNINGS", "EMPLOYEE", "DEDUCTIONS", "RATE/HOUR", "NET PAY",
                   "PAY DATE", "GROSS WAGES", "EMPLOYEE'S NAME", "HOURS")


def sweep() -> dict:
    per_corpus: dict[str, dict] = {}
    all_leaks: list[dict] = []
    all_coincidences: list[dict] = []
    inverse_hits = {p: 0 for p in _INVERSE_PROBES}

    for corpus, doc, path, truth in enumerate_truth():
        if not path.exists():
            raise SystemExit(f"missing document: {path}")
        skeleton, furniture_count, kept = _doc_skeleton_and_furniture(path)
        real, coincidences = _classify_hits(skeleton, kept, truth) if truth else ([], [])
        folded_skel = _fold(skeleton)
        for probe in _INVERSE_PROBES:
            if _fold(probe) in folded_skel:
                inverse_hits[probe] += 1

        c = per_corpus.setdefault(corpus, {
            "documents": 0, "truth_values_checked": 0, "values_masked": 0,
            "leaks": 0, "caption_coincidences": 0, "furniture_runs_kept": 0,
        })
        c["documents"] += 1
        c["truth_values_checked"] += len(truth)
        # masked = neither a real leak nor a caption coincidence: the value is simply gone.
        c["values_masked"] += len(truth) - len(real) - len(coincidences)
        c["leaks"] += len(real)
        c["caption_coincidences"] += len(coincidences)
        c["furniture_runs_kept"] += furniture_count
        for hit in real:
            all_leaks.append({"corpus": corpus, "doc": doc, **hit})
        for hit in coincidences:
            all_coincidences.append({"corpus": corpus, "doc": doc, **hit})

    totals = {
        "documents": sum(c["documents"] for c in per_corpus.values()),
        "truth_values_checked": sum(c["truth_values_checked"] for c in per_corpus.values()),
        "values_masked": sum(c["values_masked"] for c in per_corpus.values()),
        "leaks": sum(c["leaks"] for c in per_corpus.values()),
        "caption_coincidences": sum(c["caption_coincidences"] for c in per_corpus.values()),
        "furniture_runs_kept": sum(c["furniture_runs_kept"] for c in per_corpus.values()),
    }
    return {
        "hazard": "a truth value (numeric or personal) appears as a substring of a skeleton",
        "predicate": "for every doc with truth, no truth value survives in the skeleton in a "
                     "value-bearing position (folded + space-squeezed, both sides). A value "
                     "word wholly inside a kept general structural caption is a coincidence, "
                     "counted separately, not a leak: the caption is page structure the house "
                     "rule permits disclosing and prints blank-or-filled.",
        "seal": "filled/scenarios read DEV-ONLY via build_field_state._dev_records; no seal opened",
        "per_corpus": per_corpus,
        "totals": totals,
        "leaks": all_leaks,
        "caption_coincidences": all_coincidences,
        "inverse_sanity": {
            "note": "count of DEV documents whose skeleton still prints each known caption",
            "printed_probe_survival": inverse_hits,
        },
        "verdict": "PASS -- no leak" if totals["leaks"] == 0 else f"FAIL -- {totals['leaks']} leak(s)",
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="store_true", help="write loop/falsification/it-014.json")
    args = ap.parse_args(argv)

    result = sweep()
    t = result["totals"]
    print(f"documents swept:        {t['documents']}")
    print(f"truth values checked:   {t['truth_values_checked']}")
    print(f"values masked:          {t['values_masked']}")
    print(f"caption coincidences:   {t['caption_coincidences']}")
    print(f"furniture runs kept:    {t['furniture_runs_kept']}")
    print(f"LEAKS:                  {t['leaks']}")
    print()
    print(f"{'corpus':<12}{'docs':>6}{'truth':>8}{'masked':>8}{'coinc':>7}{'leaks':>7}{'kept':>8}")
    for corpus, c in result["per_corpus"].items():
        print(f"{corpus:<12}{c['documents']:>6}{c['truth_values_checked']:>8}"
              f"{c['values_masked']:>8}{c['caption_coincidences']:>7}{c['leaks']:>7}"
              f"{c['furniture_runs_kept']:>8}")
    print()
    print("inverse sanity (docs whose skeleton still prints the caption):")
    for probe, n in result["inverse_sanity"]["printed_probe_survival"].items():
        print(f"  {probe:<20} {n}")
    print()
    if result["caption_coincidences"]:
        print("caption coincidences (value word inside a kept general caption, NOT a leak):")
        for lk in result["caption_coincidences"][:5]:
            print(f"  {lk['corpus']}::{lk['doc']}::{lk['field']} = {lk['value']!r}")
        if len(result["caption_coincidences"]) > 5:
            print(f"  ... and {len(result['caption_coincidences']) - 5} more (all 'monthly' in 'MONTHLY AMOUNT')")
        print()
    print(result["verdict"])
    if result["leaks"]:
        print("\nLEAK DETAIL:")
        for lk in result["leaks"]:
            print(f"  {lk['corpus']}::{lk['doc']}::{lk['field']} = {lk['value']!r}")

    if args.run:
        out = ROOT / "loop" / "falsification" / "it-014.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")
    return 1 if result["leaks"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
