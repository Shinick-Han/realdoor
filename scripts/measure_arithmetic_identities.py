# -*- coding: utf-8 -*-
"""
measure_arithmetic_identities.py -- what the page's own arithmetic says, and how often it
says something by accident.

Two numbers matter here and they are printed side by side:

  * **constrained** -- consecutive runs of one aligned column (or one line) that hit a
    printed total. This is what `core/arithmetic.py` searches.
  * **free** -- the same search with the geometry constraint removed: any subset of the
    page's numbers that hits a printed total.

`--targets` is the column to read. It counts DISTINCT printed totals each search can reach,
which is the quantity the uniqueness test in `core/verified.py` actually has to survive.
Counting matching runs instead overstates the constrained search, because the same identity is
found repeatedly (a column clusters on both edges; trailing zeros extend a run without changing
its sum).

**What this script measured, and it is a correction.** The design being implemented here stated
that the geometry constraint drops coincidences to zero. It does not. It narrows the reachable
totals by roughly three to six times on a dense page and leaves real accidents standing --
`8.00 + 72.00 = 80.00` on the UNC advice is a perfectly well-formed column run joining two
unrelated year-to-date leave figures. Geometry is a filter, not a guarantee, and the safety
argument has to rest on the anchor and the uniqueness test instead.

    python scripts/measure_arithmetic_identities.py
    python scripts/measure_arithmetic_identities.py --targets  (the corrected measurement)
    python scripts/measure_arithmetic_identities.py --free     (slow: raw subset counts)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pdfplumber  # noqa: E402

from core import arithmetic as ar  # noqa: E402
from core import extract as ex  # noqa: E402

RAW = ROOT / "testdata" / "external_raw"
TRUTH = ROOT / "testdata" / "external_truth.json"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--free", action="store_true", help="also run the free-subset control")
    parser.add_argument("--targets", action="store_true", help="distinct reachable totals")
    parser.add_argument("--detail", action="store_true", help="print every identity found")
    args = parser.parse_args(argv)

    truth = json.loads(TRUTH.read_text(encoding="utf-8"))
    print("=" * 92)
    print("arithmetic identities on the six external documents")
    print("=" * 92)
    header = f"{'document':<16}{'page':>5}{'nums':>6}{'rowprod':>9}{'runsum':>8}{'free':>8}"
    if args.targets:
        header += f"{'tgt':>6}{'tgtfree':>9}"
    print(header)

    for doc in truth["documents"]:
        path = RAW / doc["file_name"]
        if not path.exists():
            continue
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                words = ex.read_words(page, page_number)
                tokens = ar.number_tokens(words)
                if len(tokens) < 3:
                    continue
                products = ar.find_row_products(tokens)
                sums = ar.find_run_sums(tokens)
                free = ar.free_subset_sums(tokens) if args.free else -1
                row = (
                    f"{doc['file_name']:<16}{page_number:>5}{len(tokens):>6}"
                    f"{len(products):>9}{len(sums):>8}"
                    f"{(free if free >= 0 else '-'):>8}"
                )
                if args.targets:
                    constrained = ar.reachable_totals(tokens, max_size=3)
                    unconstrained = ar.free_reachable_totals(tokens, max_size=3)
                    row += f"{len(constrained):>6}{len(unconstrained):>9}"
                print(row)
                if args.detail:
                    for p in products:
                        print(
                            f"      product  {p.rate.text:>12} x {p.hours.text:>9}"
                            f" = {p.amount.text:>12}   y={p.amount.baseline:.2f}"
                            f"   {'exact' if p.exact else 'rounded'}"
                        )
                    for s in sums:
                        run = " + ".join(t.text for t in s.run)
                        print(
                            f"      {s.kind:<7}{s.alignment:<6} {run} = {s.total.text}"
                            f"   {'exact' if s.exact else 'rounded'}"
                        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
