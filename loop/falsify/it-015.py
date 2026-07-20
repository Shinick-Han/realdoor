# -*- coding: utf-8 -*-
"""loop/falsify/it-015.py -- the leak predicate for T28 part 2 (the caption channel).

NAMED HAZARD
------------
A value string -- numeric OR personal (a name, address, SSN, date, amount) -- leaves the
process. it-015 opens TWO outbound channels, and both must be swept:

  1. the SKELETON, sent to the model as context (unchanged from it-014; re-run here to
     prove the wiring moved nothing); and
  2. the CAPTION, the one target string the model is asked to name. it-014's redactor was
     tuned for the skeleton and masks unknown captions too; T21 needs those unknown
     captions to SURVIVE on the caption channel, so this iteration widens what may be sent
     to `furniture OR a run that anchors a value slot` (the position extension). That
     re-opens the leak it-014 closed: a free-floating employer name that anchors an address
     would leave as a "caption". This predicate is what decides whether the extension ships.

PREDICATE (over every corpus we own, BEFORE the wider gate is trusted)
---------------------------------------------------------------------
For every document with truth values:
  * (channel 1) assert no truth value survives in the skeleton -- it-014's exact predicate.
  * (channel 2) build the POSITION-EXTENDED sendable caption set (`core.skeleton.
    page_sendable_labels(..., position_extension=True)`) and assert no truth value appears
    as, or wholly inside, a sendable caption -- UNLESS that caption is furniture-by-string
    (a colon caption or a `STRUCTURAL_VOCAB` member), which is page structure the house
    rule already permits disclosing and which prints blank-or-filled. A truth value that
    reaches the sendable set through the POSITION arm alone is the leak the extension must
    not produce: it is a value anchoring another value.

The furniture-only sendable set is swept too, so the safe fallback's cleanliness is on the
record next to the extension's.

SEAL DISCIPLINE
---------------
filled/ and scenarios/ are read DEV-ONLY via `build_field_state._dev_records`, exactly as
it-014; no sealed hold-out truth is opened.

    python loop/falsify/it-015.py            # sweep and print a summary
    python loop/falsify/it-015.py --run      # also write loop/falsification/it-015.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts"), str(ROOT / "loop" / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Reuse it-014's proven machinery verbatim (truth enumeration, folding, skeleton sweep).
_spec = importlib.util.spec_from_file_location("_it014", Path(__file__).with_name("it-014.py"))
it014 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(it014)  # type: ignore

from core.skeleton import (  # noqa: E402
    is_furniture_text,
    page_sendable_labels,
    STRUCTURAL_VOCAB,
)
from core.extract import read_words, normalize_label  # noqa: E402
import pdfplumber  # noqa: E402

_fold = it014._fold


def _doc_sendable(path: Path, *, position_extension: bool) -> set[str]:
    """The union of every page's sendable caption set for one document."""
    out: set[str] = set()
    with pdfplumber.open(str(path)) as pdf:
        for pnum, page in enumerate(pdf.pages, start=1):
            words = read_words(page, pnum)
            out |= set(page_sendable_labels(words, position_extension=position_extension))
    return out


def _caption_leaks(sendable: set[str], truth_values) -> tuple[list[dict], list[dict]]:
    """Split truth-value hits in the sendable set into real leaks and furniture coincidences.

    A truth value that appears as, or wholly inside, a sendable caption is a REAL LEAK
    unless every caption it appears in is furniture-by-string (colon or STRUCTURAL_VOCAB) --
    page structure the house rule permits and which prints regardless of this document's
    private value. A value that reaches the sendable set through the POSITION arm (a
    non-furniture caption) discloses the datum: that is the extension leaking.
    """
    folded = {cap: _fold(cap) for cap in sendable}
    real: list[dict] = []
    coincidences: list[dict] = []
    for field, value in truth_values:
        needle = _fold(value)
        if not needle:
            continue
        hits = [cap for cap, f in folded.items()
                if needle == f or (needle in f) or (needle.replace(" ", "") in f.replace(" ", ""))]
        if not hits:
            continue
        # Furniture-by-string captions are the permitted disclosure. If EVERY caption the
        # value lands in is furniture, it is a coincidence; if any is position-only, leak.
        position_only = [c for c in hits if not is_furniture_text(c)]
        record = {"field": field, "value": str(value), "captions": hits}
        if position_only:
            real.append({**record, "position_only_captions": position_only})
        else:
            coincidences.append(record)
    return real, coincidences


def sweep() -> dict:
    # channel 1: the skeleton, it-014's predicate, re-run unchanged.
    skeleton_result = it014.sweep()

    # channel 2: the caption egress set, furniture-only and position-extended.
    per_corpus: dict[str, dict] = {}
    ext_leaks: list[dict] = []
    ext_coincidences: list[dict] = []
    furn_leaks: list[dict] = []
    for corpus, doc, path, truth in it014.enumerate_truth():
        if not path.exists():
            raise SystemExit(f"missing document: {path}")
        c = per_corpus.setdefault(corpus, {
            "documents": 0, "truth_values_checked": 0,
            "furniture_sendable_captions": 0, "position_sendable_captions": 0,
            "extension_only_captions": 0,
            "furniture_leaks": 0, "extension_leaks": 0, "caption_coincidences": 0,
        })
        furn = _doc_sendable(path, position_extension=False)
        ext = _doc_sendable(path, position_extension=True)
        c["documents"] += 1
        c["truth_values_checked"] += len(truth)
        c["furniture_sendable_captions"] += len(furn)
        c["position_sendable_captions"] += len(ext)
        c["extension_only_captions"] += len(ext - furn)
        if truth:
            f_real, _ = _caption_leaks(furn, truth)
            e_real, e_coinc = _caption_leaks(ext, truth)
            c["furniture_leaks"] += len(f_real)
            c["extension_leaks"] += len(e_real)
            c["caption_coincidences"] += len(e_coinc)
            for hit in f_real:
                furn_leaks.append({"corpus": corpus, "doc": doc, **hit})
            for hit in e_real:
                ext_leaks.append({"corpus": corpus, "doc": doc, **hit})
            for hit in e_coinc:
                ext_coincidences.append({"corpus": corpus, "doc": doc, **hit})

    totals = {
        k: sum(cc[k] for cc in per_corpus.values())
        for k in ("documents", "truth_values_checked", "furniture_sendable_captions",
                  "position_sendable_captions", "extension_only_captions",
                  "furniture_leaks", "extension_leaks", "caption_coincidences")
    }
    return {
        "hazard": "a truth value leaves the process on the skeleton channel OR the caption channel",
        "channel_1_skeleton": {
            "predicate": "it-014's leak predicate, re-run unchanged to prove the wiring moved nothing",
            "leaks": skeleton_result["totals"]["leaks"],
            "per_corpus": skeleton_result["per_corpus"],
            "detail": skeleton_result["leaks"],
        },
        "channel_2_caption": {
            "predicate": "no truth value appears as/inside a sendable caption unless that "
                         "caption is furniture-by-string; a value reaching the sendable set "
                         "through the POSITION arm alone is a leak (a value anchoring a value)",
            "per_corpus": per_corpus,
            "totals": totals,
            "furniture_only_leaks": furn_leaks,
            "position_extension_leaks": ext_leaks,
            "caption_coincidences": ext_coincidences,
        },
        "seal": "filled/scenarios read DEV-ONLY via build_field_state._dev_records; no seal opened",
        "verdict_skeleton": "PASS" if skeleton_result["totals"]["leaks"] == 0 else "FAIL",
        "verdict_caption_furniture_only": "PASS" if totals["furniture_leaks"] == 0 else "FAIL",
        "verdict_caption_position_extension": "PASS" if totals["extension_leaks"] == 0 else "FAIL",
    }


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", action="store_true", help="write loop/falsification/it-015.json")
    args = ap.parse_args(argv)

    r = sweep()
    c1 = r["channel_1_skeleton"]
    c2 = r["channel_2_caption"]
    t = c2["totals"]
    print(f"channel 1 (skeleton)  leaks: {c1['leaks']}   -> {r['verdict_skeleton']}")
    print()
    print(f"channel 2 (caption)   documents: {t['documents']}  truth: {t['truth_values_checked']}")
    print(f"  furniture sendable captions   : {t['furniture_sendable_captions']}")
    print(f"  position sendable captions    : {t['position_sendable_captions']}"
          f"  (extension-only: {t['extension_only_captions']})")
    print(f"  caption coincidences (furniture, not leaks): {t['caption_coincidences']}")
    print(f"  furniture-only LEAKS          : {t['furniture_leaks']}   -> {r['verdict_caption_furniture_only']}")
    print(f"  position-extension LEAKS      : {t['extension_leaks']}   -> {r['verdict_caption_position_extension']}")
    print()
    print(f"{'corpus':<12}{'docs':>6}{'truth':>7}{'furn':>7}{'pos':>6}{'ext':>6}{'coinc':>7}{'fLEAK':>7}{'pLEAK':>7}")
    for corpus, cc in c2["per_corpus"].items():
        print(f"{corpus:<12}{cc['documents']:>6}{cc['truth_values_checked']:>7}"
              f"{cc['furniture_sendable_captions']:>7}{cc['position_sendable_captions']:>6}"
              f"{cc['extension_only_captions']:>6}{cc['caption_coincidences']:>7}"
              f"{cc['furniture_leaks']:>7}{cc['extension_leaks']:>7}")
    if c2["position_extension_leaks"]:
        print("\nPOSITION-EXTENSION LEAK DETAIL (value reaching sendable set via anchoring):")
        for lk in c2["position_extension_leaks"][:20]:
            print(f"  {lk['corpus']}::{lk['doc']}::{lk['field']} = {lk['value']!r} "
                  f"via {lk['position_only_captions']}")
        if len(c2["position_extension_leaks"]) > 20:
            print(f"  ... and {len(c2['position_extension_leaks']) - 20} more")

    if args.run:
        out = ROOT / "loop" / "falsification" / "it-015.json"
        out.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")
    leaked = (c1["leaks"] or t["furniture_leaks"])  # the SHIPPABLE claim: skeleton + furniture-only
    return 1 if leaked else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
