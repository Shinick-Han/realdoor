# -*- coding: utf-8 -*-
"""build_corpus_manifest.py -- enumerate the 77-document falsification universe, once.

Design section D.1: before any product code exists, a proposal's firing predicate is run
over *every* document in the corpus, not over the one that motivated it. That sweep needs
a list, and the list has to be built from the truth files rather than from a directory
walk, so that every document arrives with a pointer to where its ground truth lives.

    python loop/tools/build_corpus_manifest.py            # write loop/tools/corpus_manifest.json
    python loop/tools/build_corpus_manifest.py --check    # verify without writing

Fails loudly, with a non-zero exit, if the total is not 77 or any per-corpus count moves.
The number is load-bearing: `core/shredded.py` and `core/columns.py` both state
falsification results as "across all 77 corpus documents", and a sweep that silently ran
over 73 would make those sentences false without making anything red.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_lib as cl  # noqa: E402


def build() -> dict:
    docs = cl.enumerate_corpus()

    counts: dict[str, int] = {}
    for doc in docs:
        counts[doc["corpus"]] = counts.get(doc["corpus"], 0) + 1

    problems = []
    if counts != cl.EXPECTED_COUNTS:
        problems.append(f"per-corpus counts are {counts}, expected {cl.EXPECTED_COUNTS}")
    if len(docs) != cl.EXPECTED_TOTAL:
        problems.append(f"total is {len(docs)}, expected {cl.EXPECTED_TOTAL}")
    seen = [d["path"] for d in docs]
    if len(set(seen)) != len(seen):
        problems.append("the same PDF path appears in two corpora")
    if problems:
        for line in problems:
            print(f"FAIL: {line}", file=sys.stderr)
        raise SystemExit(1)

    truth_sources = sorted({d["truth_source"] for d in docs})
    return {
        "generated_by": "loop/tools/build_corpus_manifest.py",
        "total": len(docs),
        "counts": counts,
        "truth_sources": truth_sources,
        "truth_sources_all_protected": all(
            any(token in source for token in cl.PROTECTED)
            or source.endswith("_manifest.json")
            for source in truth_sources
        ),
        "note": (
            "uploads_manifest.json and holdout_manifest.json are not named in the design's "
            "protected list, but they are truth for 33 of the 77 documents and this loop "
            "never writes them. G6's forbidden list is the design's, unchanged."
        ),
        "documents": docs,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only, write nothing")
    args = parser.parse_args(argv)

    manifest = build()
    if not args.check:
        cl.MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        cl.MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {cl.MANIFEST_PATH}")

    print(f"{manifest['total']} documents:", end=" ")
    print("  ".join(f"{k} {v}" for k, v in manifest["counts"].items()))
    expected = sum(d["expected_field_count"] for d in manifest["documents"])
    absent = sum(d["expect_absent_count"] for d in manifest["documents"])
    print(f"expected fields {expected}   expect_absent fields {absent}")
    for source in manifest["truth_sources"]:
        print(f"  truth: {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
