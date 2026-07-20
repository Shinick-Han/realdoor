# -*- coding: utf-8 -*-
"""build_field_state.py -- the day-0 census, and the same census on demand for the gate.

Design section B: `field_state` enumerates every expected field of every corpus document,
classified `correct | abstain | blocked_contract | masked | image_only`, keyed
`corpus::doc::field`. It is what makes gates G3 and G7 field-level rather than
totals-level -- totals hide a swap in which a rule gains one field and quietly eats a
neighbour's.

    python loop/tools/build_field_state.py            # measure and write loop/baseline.json
    python loop/tools/build_field_state.py --print    # measure and print, write nothing

WHERE `correct` COMES FROM
--------------------------
Not from here. Every corpus is scored by the repository's own harness functions, imported:

    pack       api.store.extract_all()  ->  score_extraction.score()
    uploads    the loop that IS scripts/measure_label_mapping._tally, field by field,
    holdout    using the same score_extraction.normalize() comparison
    external   the loop that IS scripts/measure_external_holdout._tally, ditto
    confirm    measure_confirm_set._matches(), imported outright

and then every corpus is **reconciled**: this module re-runs the harness's own tally and
asserts that the number of `correct` entries it produced equals the harness's `correct`,
per corpus and (where the harness reports it) per document. A disagreement is a bug in
this classifier and exits non-zero. It is never resolved by adjusting a total.

That assert is the whole reason this file is structured the way it is. An ad-hoc
`str == str` probe has already produced two false failure reports in this project.

WHAT `expect_absent` DOES HERE
------------------------------
The design's `field_state` covers *expected* fields. external and confirm also carry
`expect_absent` lists, where the only available error is inventing a value -- caught by
G1 (wrong == 0) but invisible to a field-level flip diff. So this module writes a second,
sibling map `absent_state` (`absent` / `invented`) over those fields, and G3/G7 watch it
too. That is an addition to the design, not a change to it: `field_state` keeps exactly
the keys and values section B specifies.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_lib as cl  # noqa: E402


def _text_cache(manifest: list[dict[str, Any]]) -> dict[str, str]:
    """Raw pdfplumber text for all 77, once. ~20s; the `image_only` test needs it."""
    return {doc["doc"]: cl.page_text(doc["path"]) for doc in manifest}


# =====================================================================================
# per-corpus field state, each built on its own harness
# =====================================================================================


def _pack_state(manifest, texts) -> tuple[dict[str, str], dict[str, int], dict[str, Any]]:
    from api.store import STORE  # noqa: E402
    from score_extraction import score  # type: ignore  # noqa: E402

    gold_path = cl.ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"
    gold = [json.loads(x) for x in gold_path.read_text(encoding="utf-8").splitlines() if x.strip()]

    STORE.warm()
    session = STORE.new_session()
    report = score(list(session.views.values()), gold)

    by_id = {d["document_id"]: d["doc"] for d in manifest if d["corpus"] == "pack"}
    # Everything the scorer did not put in a failure bucket is an exact match. Taking the
    # complement (rather than re-comparing values) means `correct` here is literally the
    # scorer's verdict.
    not_correct = {
        (row["document_id"], row["field"])
        for bucket in ("wrong", "abstained", "missed")
        for row in report["traceability"][bucket]
    }

    state: dict[str, str] = {}
    for record in gold:
        doc = by_id[record["document_id"]]
        for field in record["fields"]:
            name = field["field"]
            is_correct = (record["document_id"], name) not in not_correct
            state[cl.key("pack", doc, name)] = cl.classify(
                name, field.get("value"), is_correct, texts[doc]
            )

    totals = {
        "correct": report["exact_match"], "wrong": report["wrong"],
        "of": report["fields_total"],
        "iou_mean": round(report["bbox"]["iou_mean"], 4),
        "iou_over_05": report["bbox"]["iou_gt_0_5"],
        "iou_evaluated": report["bbox"]["evaluated"],
        "abstained": report["abstained"], "missed": report["missed"],
    }
    return state, {"correct": report["exact_match"], "measured_fields": len(state)}, totals


def _intended_state(corpus, manifest_rel, dir_rel, manifest, texts):
    """uploads / holdout: the loop scripts/measure_label_mapping._tally performs."""
    import measure_label_mapping as mlm  # type: ignore  # noqa: E402
    from core import extract as ex  # noqa: E402
    from score_extraction import normalize  # type: ignore  # noqa: E402

    data = json.loads((cl.ROOT / manifest_rel).read_text(encoding="utf-8"))
    state: dict[str, str] = {}
    scored_correct = 0
    measured_fields = 0

    for record in data["documents"]:
        doc = record["file_name"]
        fields = record.get("intended_fields", {})
        if record.get("rasterized"):
            # `_tally` skips these outright ("OCR path is a different argument"). They are
            # still corpus documents and still carry truth, so they are classified -- and
            # having no text layer they classify as image_only, which is the honest word.
            for name, expected in fields.items():
                state[cl.key(corpus, doc, name)] = cl.classify(name, expected, False, texts[doc])
            continue

        view = ex.extract_document(
            cl.ROOT / dir_rel / doc,
            document_type=record["document_type"],
            fallback_mapper=ex.synonym_mapper,
        )
        got = {f["field"]: f for f in view["fields"]}
        for name, expected in fields.items():
            field = got.get(name)
            is_correct = (
                field is not None
                and field["certainty"] != "abstain"
                and normalize(name, expected) == normalize(name, field["value"])
            )
            scored_correct += int(is_correct)
            measured_fields += 1
            state[cl.key(corpus, doc, name)] = cl.classify(name, expected, is_correct, texts[doc])

    key = "existing 26" if corpus == "uploads" else "hold-out"
    harness = mlm._tally(cl.ROOT / manifest_rel, cl.ROOT / dir_rel, ex.synonym_mapper, None)
    totals = {
        "correct": harness["correct"], "wrong": harness["wrong"],
        "of": harness["fields_total"], "abstained": harness["abstained"],
        # NOT `documents_scored`: eval/test_no_decision.py bans the token "scored"
        # as a key anywhere in the repo's JSON and source, and it walks loop/ too.
        "documents_measured": harness["documents"], "harness_set_name": key,
    }
    return state, {"correct": scored_correct, "measured_fields": measured_fields}, totals


def _external_state(manifest, texts):
    """external six: the loop scripts/measure_external_holdout._tally performs."""
    import measure_external_holdout as meh  # type: ignore  # noqa: E402
    from core import extract as ex  # noqa: E402
    from score_extraction import normalize  # type: ignore  # noqa: E402

    truth = json.loads((cl.ROOT / "testdata/external_truth.json").read_text(encoding="utf-8"))
    state: dict[str, str] = {}
    absent: dict[str, str] = {}
    per_doc: dict[str, int] = {}

    for record in truth["documents"]:
        doc = record["file_name"]
        view = ex.extract_document(
            cl.ROOT / "testdata/external_raw" / doc,
            document_type=record["document_type"],
            fallback_mapper=ex.synonym_mapper,
        )
        got = {f["field"]: f for f in view["fields"]}
        hits = 0
        for name, expected in record.get("expected", {}).items():
            field = got.get(name)
            is_correct = (
                field is not None
                and field["certainty"] != "abstain"
                and normalize(name, expected) == normalize(name, field["value"])
            )
            hits += int(is_correct)
            state[cl.key("external", doc, name)] = cl.classify(name, expected, is_correct, texts[doc])
        for name in record.get("expect_absent", []):
            field = got.get(name)
            clean = field is None or field["certainty"] == "abstain"
            absent[cl.key("external", doc, name)] = "absent" if clean else "invented"
        per_doc[doc] = hits

    harness = meh._tally(ex.synonym_mapper)
    totals = {
        "correct": harness["correct"], "wrong": harness["wrong"],
        "of": harness["fields_total"], "abstained": harness["abstained"],
    }
    return (state, {"correct": sum(per_doc.values()), "per_doc": per_doc,
            "measured_fields": len(state) + len(absent)}, totals, absent, harness)


def _confirm_state(manifest, texts):
    """confirm 14: measure_confirm_set's own `_matches`, on its own extract call."""
    import measure_confirm_set as mcs  # type: ignore  # noqa: E402
    from core import extract as ex  # noqa: E402

    truth = json.loads(mcs.TRUTH.read_text(encoding="utf-8"))
    state: dict[str, str] = {}
    absent: dict[str, str] = {}
    per_doc: dict[str, int] = {}

    for record in truth["documents"]:
        doc = record["file_name"]
        view = ex.extract_document(
            mcs.RAW_DIR / doc,
            document_type=mcs.DOCUMENT_TYPE,
            fallback_mapper=ex.synonym_mapper,
        )
        got = {f["field"]: f for f in view["fields"]}
        hits = 0
        for name, expected in record.get("expected", {}).items():
            if name not in mcs.REACHABLE:
                # measure_confirm_set counts these as `unreachable`, not as abstentions:
                # they are outside EXPECTED_FIELDS['pay_stub'], so nothing ever looks for
                # them and no change to core/ could move them. They are not extraction
                # state and do not belong in field_state.
                continue
            field = got.get(name)
            is_correct = (
                field is not None
                and field["certainty"] != "abstain"
                and mcs._matches(name, expected, field["value"])
            )
            hits += int(is_correct)
            state[cl.key("confirm", doc, name)] = cl.classify(name, expected, is_correct, texts[doc])
        for name in record.get("expect_absent", []):
            if name not in mcs.REACHABLE:
                continue
            field = got.get(name)
            clean = field is None or field["certainty"] == "abstain"
            absent[cl.key("confirm", doc, name)] = "absent" if clean else "invented"
        per_doc[doc] = hits

    harness = mcs.tally()
    totals = {
        "correct": harness["correct"], "wrong": harness["wrong"],
        "of": harness["fields_total"], "abstained": harness["abstained"],
        "unreachable_expected": harness["unreachable_expected"],
        "unreachable_absent": harness["unreachable_absent"],
    }
    return (state, {"correct": sum(per_doc.values()), "per_doc": per_doc,
            "measured_fields": len(state) + len(absent)}, totals, absent, harness)


# =====================================================================================
# reconciliation -- the assert this file exists for
# =====================================================================================


def _reconcile(problems: list[str], corpus: str, mine: dict, harness_totals: dict,
               harness_per_doc: list[dict] | None = None, per_doc_key: str = "correct") -> None:
    if mine["correct"] != harness_totals["correct"]:
        problems.append(
            f"{corpus}: field_state has {mine['correct']} correct, the harness reports "
            f"{harness_totals['correct']}. The classifier is wrong; do not adjust the total."
        )
    # And the population, not just the hits: every field the harness scored must have a
    # state entry, and every state entry on a measured document must have been scored.
    # Without this a classifier that dropped a field would still reconcile on `correct`.
    if "measured_fields" in mine and mine["measured_fields"] != harness_totals["of"]:
        problems.append(
            f"{corpus}: field_state + absent_state cover {mine['measured_fields']} fields "
            f"on the documents the harness measured, the harness scored "
            f"{harness_totals['of']}"
        )
    if harness_per_doc is not None:
        for row in harness_per_doc:
            got = mine["per_doc"].get(row["file"])
            if got != row[per_doc_key]:
                problems.append(
                    f"{corpus}::{row['file']}: field_state has {got} correct, harness "
                    f"reports {row[per_doc_key]}"
                )


def measure(quiet: bool = False) -> dict[str, Any]:
    manifest = cl.load_manifest()
    if not quiet:
        print("reading text layers for all 77 documents ...", file=sys.stderr)
    texts = _text_cache(manifest)

    problems: list[str] = []
    field_state: dict[str, str] = {}
    absent_state: dict[str, str] = {}
    corpora: dict[str, Any] = {}

    if not quiet:
        print("scoring pack ...", file=sys.stderr)
    state, mine, totals = _pack_state(manifest, texts)
    field_state.update(state)
    corpora["pack"] = totals
    _reconcile(problems, "pack", mine, totals)

    for corpus, manifest_rel, dir_rel in (
        ("uploads", "testdata/uploads_manifest.json", "testdata/uploads"),
        ("holdout", "testdata/holdout_manifest.json", "testdata/holdout"),
    ):
        if not quiet:
            print(f"scoring {corpus} ...", file=sys.stderr)
        state, mine, totals = _intended_state(corpus, manifest_rel, dir_rel, manifest, texts)
        field_state.update(state)
        corpora[corpus] = totals
        _reconcile(problems, corpus, mine, totals)

    if not quiet:
        print("scoring external ...", file=sys.stderr)
    state, mine, totals, absent, harness = _external_state(manifest, texts)
    field_state.update(state)
    absent_state.update(absent)
    corpora["external"] = totals
    _reconcile(problems, "external", mine, totals, harness["per_document"])

    if not quiet:
        print("scoring confirm ...", file=sys.stderr)
    state, mine, totals, absent, harness = _confirm_state(manifest, texts)
    field_state.update(state)
    absent_state.update(absent)
    corpora["confirm"] = totals
    _reconcile(problems, "confirm", mine, totals, harness["per_document"])

    census: dict[str, Counter] = {}
    for full_key, value in field_state.items():
        census.setdefault(full_key.split("::")[0], Counter())[value] += 1

    return {
        "corpora": corpora,
        "field_state": dict(sorted(field_state.items())),
        "absent_state": dict(sorted(absent_state.items())),
        "field_state_census": {k: dict(sorted(v.items())) for k, v in sorted(census.items())},
        "problems": problems,
    }


def run_pytest() -> dict[str, int]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(cl.ROOT), capture_output=True, text=True, errors="replace",
    )
    tail = (proc.stdout or "") + (proc.stderr or "")
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", tail)) else -1
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", tail)) else 0
    return {"passed": passed, "failed": failed, "exit_code": proc.returncode}


def preexisting_dirty() -> list[str]:
    """Paths already dirty in the working tree when this baseline was taken.

    G6 asks "did THIS iteration touch something outside its allowlist". It cannot answer
    that from `git diff HEAD` alone, because this repository's working tree carries
    unrelated in-progress work (a modified README, UI scan artefacts, untracked recorder
    scripts and the confirm corpus PDFs themselves). Charging an iteration for those would
    make G6 fail on a known-good tree, which is exactly as useless as a gate that never
    fires. So the day-0 dirt is recorded here, by name, and G6 subtracts it and says how
    many it subtracted. `loop/` is excluded because G6 always allows it, and `.cache/`
    because the gate's own cache-clearing creates those deletions.

    The forbidden-path check in G6 is NOT subject to this exemption: a truth file that was
    already dirty is a problem no matter who made it dirty.
    """
    def _lines(args: list[str]) -> list[str]:
        out = subprocess.run(args, cwd=str(cl.ROOT), capture_output=True, text=True).stdout
        return [ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()]

    paths = set(_lines(["git", "diff", "--name-only", "HEAD"]))
    paths |= set(_lines(["git", "ls-files", "--others", "--exclude-standard"]))
    return sorted(
        p for p in paths if not p.startswith("loop/") and not p.startswith(".cache/")
    )


def head_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(cl.ROOT), capture_output=True, text=True
    ).stdout.strip()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print", action="store_true", dest="only_print",
                        help="measure and print the census; write nothing")
    parser.add_argument("--refresh-dirty", action="store_true",
                        help="rewrite only baseline.preexisting_dirty and exit. Committing "
                             "changes no file's contents, so the measurements stay valid; "
                             "what moves is which paths git calls dirty.")
    parser.add_argument("--no-pytest", action="store_true",
                        help="skip the pytest leg (the census does not depend on it)")
    args = parser.parse_args(argv)

    if args.refresh_dirty:
        baseline = json.loads(cl.BASELINE_PATH.read_text(encoding="utf-8"))
        baseline["preexisting_dirty"] = preexisting_dirty()
        cl.BASELINE_PATH.write_text(
            json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"preexisting_dirty = {len(baseline['preexisting_dirty'])} paths")
        for path in baseline["preexisting_dirty"]:
            print(f"  {path}")
        return 0

    # The extraction cache keys on source *content* and never on flag state; a stale hit
    # would make this census a measurement of an older tree.
    import shutil
    shutil.rmtree(cl.ROOT / ".cache" / "extractions", ignore_errors=True)

    result = measure()
    pytest_result = {"passed": None, "failed": None, "skipped": True}
    if not args.no_pytest:
        print("running pytest ...", file=sys.stderr)
        pytest_result = run_pytest()

    for corpus, counts in result["field_state_census"].items():
        total = sum(counts.values())
        print(f"{corpus:<10} {total:>4} expected fields   " +
              "  ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"{'TOTAL':<10} {len(result['field_state']):>4} expected fields   " +
          "  ".join(f"{k}={v}" for k, v in sorted(Counter(result["field_state"].values()).items())))
    print(f"absent_state {len(result['absent_state'])} expect_absent fields   " +
          "  ".join(f"{k}={v}" for k, v in sorted(Counter(result["absent_state"].values()).items())))

    if result["problems"]:
        print("\nRECONCILIATION FAILED:", file=sys.stderr)
        for line in result["problems"]:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("\nreconciliation: field_state correct counts == harness correct counts, every corpus")

    if args.only_print:
        return 0

    baseline = {
        "accepted_commit": head_sha(),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generated_by": "loop/tools/build_field_state.py",
        "pack": result["corpora"]["pack"],
        "uploads": result["corpora"]["uploads"],
        "holdout": result["corpora"]["holdout"],
        "external": result["corpora"]["external"],
        "confirm": result["corpora"]["confirm"],
        "pytest": pytest_result,
        "preexisting_dirty": preexisting_dirty(),
        "field_state_census": result["field_state_census"],
        "field_state": result["field_state"],
        "absent_state": result["absent_state"],
    }
    cl.BASELINE_PATH.write_text(
        json.dumps(baseline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {cl.BASELINE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
