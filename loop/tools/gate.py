# -*- coding: utf-8 -*-
"""gate.py -- design section D.2, gates G1 through G7, as one command.

    # baseline self-check: no iteration in flight, nothing may have moved
    python loop/tools/gate.py --iteration 0

    # a real iteration
    python loop/tools/gate.py --iteration 17 --target T1 \
        --flag REALDOOR_GLYPHBOX \
        --allow core/extract.py --allow core/test_extract_reading.py \
        --predict confirm::ca_dlse_paystub_hourly.pdf::person_name \
        --predict confirm::ca_dlse_paystub_hourly.pdf::regular_hours

Exits non-zero when any gate fails, and always writes `loop/measurements/it-NNN.json`.
**No agent may argue with the table.** P6's only degrees of freedom are filling in the
report; this file is the table, and its verdict is the verdict.

TWO MODES, AND WHY
------------------
With `--target` (an iteration): G7 requires observed flips to be a subset of the
predicted set AND to intersect the target's fields -- a change that flips nothing it
aimed at is not the change its proposal described.

Without `--target` (the baseline self-check): G7 requires the observed flip set to be
**empty**. On an unchanged tree nothing may move, and a gate that cannot say so on a
known-good tree is not a gate. This is the mode the day-0 verification runs.

THE THREE FOOTGUNS THIS FILE IS BUILT AROUND (design section 9.5)
-----------------------------------------------------------------
1. `.cache/extractions` is deleted before every measurement pass. Its key
   (`api/store._cache_key`) is built from the PDF's bytes, a content hash of four engine
   sources, the label-model state and the OCR cap -- and **not** from the feature flags.
   So a `REALDOOR_X=0` run served from a warm cache reads back bytes produced with the
   flag ON, and G5 passes vacuously while proving nothing. Measured, not assumed: see
   `api/store.py` lines 115-131.
2. pdfplumber writes FontBBox warnings to stderr mid-run. Every subprocess here is parsed
   from stdout as JSON; stderr is captured and ignored.
3. The measure scripts exit non-zero when wrong > 0. A driver that read the exit code
   could not tell "wrong found" from "crashed", so every leg parses the JSON and treats a
   missing/unparsable payload as a crash, reported distinctly from a failed gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_field_state as bfs  # noqa: E402
import corpus_lib as cl  # noqa: E402

#: Design D.2 G6. Nothing an iteration does may touch these: they are the measuring
#: instruments and the truth. A change that edits its own scorer has measured nothing.
FORBIDDEN = (
    "eval/score_extraction.py",
    "scripts/verify.py",
)
FORBIDDEN_PATTERNS = (
    re.compile(r"_truth\.json$"),
    re.compile(r"^pack/synthetic_documents/gold/"),
    re.compile(r"^scripts/measure_[^/]*\.py$"),
)

#: `.cache/extractions` is gitignored but historically tracked, so `git status` shows its
#: files as deleted the moment any measurement pass runs. Those deletions are an artefact
#: of the gate's own cache-clearing, never an iteration's diff, and G6 does not count
#: them. They are reported in the measurements file so the exemption is visible.
DIFF_EXEMPT = re.compile(r"^\.cache/")


def clear_cache() -> None:
    shutil.rmtree(cl.ROOT / ".cache" / "extractions", ignore_errors=True)


def run_json(args: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> Any:
    """Run a script, parse stdout as JSON. stderr is captured and discarded (footgun 2)."""
    full_env = dict(os.environ)
    full_env["PYTHONIOENCODING"] = "utf-8"
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [sys.executable, *args], cwd=str(cwd or cl.ROOT), env=full_env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise SystemExit(
            f"CRASH (not a gate failure): {' '.join(args)} produced no JSON on stdout.\n"
            f"exit={proc.returncode}\nstdout head: {proc.stdout[:400]}\n"
            f"stderr tail: {proc.stderr[-800:]}"
        )


# =====================================================================================
# G5 -- flag-off bit identity against the last accepted commit
# =====================================================================================
# The dump is piped to the child on stdin rather than written into either tree: the
# accepted commit may predate loop/ entirely, and a temp file inside a git worktree would
# show up in that worktree's own status.

_DUMP = r'''
import json, sys
sys.path.insert(0, ".")
from core import extract as ex
docs = json.load(sys.stdin)
out = {}
for d in docs:
    view = ex.extract_document(d["rel"], document_type=d["document_type"],
                               fallback_mapper=ex.synonym_mapper)
    out[d["corpus"] + "::" + d["doc"]] = view["fields"]
sys.stdout.write(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True, default=str))
'''


def _dump_via_file(tree: Path, docs: list[dict], flags_off: list[str], scratch: Path) -> str:
    """Extraction output for all 77 documents in `tree`, with `flags_off` set to 0.

    The runner script is written into the loop's own scratch directory (gitignored, and
    outside both trees), so neither the working tree nor the temporary worktree at the
    accepted commit gains a file it does not own.
    """
    scratch.mkdir(parents=True, exist_ok=True)
    runner = scratch / "_g5_dump.py"
    runner.write_text(_DUMP, encoding="utf-8")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    for flag in flags_off:
        env[flag] = "0"

    payload = json.dumps([
        {"rel": str(Path(d["path"]).resolve().relative_to(cl.ROOT)).replace("\\", "/"),
         "corpus": d["corpus"], "doc": d["doc"], "document_type": d["document_type"]}
        for d in docs
    ])
    proc = subprocess.run(
        [sys.executable, str(runner)], cwd=str(tree), env=env, input=payload,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if not proc.stdout.strip():
        raise SystemExit(
            f"CRASH (not a gate failure): the G5 extraction dump produced nothing in "
            f"{tree}.\nexit={proc.returncode}\nstderr tail: {proc.stderr[-1200:]}"
        )
    return proc.stdout


def g5_flag_off_identity(docs, flags_off, accepted_commit, scratch) -> dict[str, Any]:
    clear_cache()
    here = _dump_via_file(cl.ROOT, docs, flags_off, scratch)

    worktree = scratch / "g5-accepted"
    shutil.rmtree(worktree, ignore_errors=True)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree)],
        cwd=str(cl.ROOT), capture_output=True, text=True,
    )
    add = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), accepted_commit],
        cwd=str(cl.ROOT), capture_output=True, text=True,
    )
    if add.returncode != 0:
        raise SystemExit(f"CRASH (not a gate failure): git worktree add failed\n{add.stderr}")
    try:
        there = _dump_via_file(worktree, docs, flags_off, scratch)
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=str(cl.ROOT), capture_output=True, text=True,
        )

    identical = here == there
    differing: list[str] = []
    if not identical:
        a, b = json.loads(here), json.loads(there)
        differing = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    return {
        "flags_off": flags_off,
        "compared_against": accepted_commit,
        "documents_compared": len(docs),
        "identical": identical,
        "documents_differing": differing[:20],
        "documents_differing_total": len(differing),
    }


# =====================================================================================
# the gate
# =====================================================================================


def evaluate(args) -> dict[str, Any]:
    baseline = json.loads(cl.BASELINE_PATH.read_text(encoding="utf-8"))
    docs = cl.load_manifest()
    scratch = cl.LOOP / "worktmp"
    results: list[dict[str, Any]] = []

    def gate(name: str, condition: bool, detail: Any) -> None:
        results.append({"gate": name, "pass": bool(condition), "detail": detail})

    # --- the measurement pass -----------------------------------------------------
    clear_cache()
    verify_pack = run_json(["-c",
        "import sys,json;sys.path[:0]=['.','eval','scripts'];"
        "from api.store import STORE;from score_extraction import score;"
        "gold=[json.loads(x) for x in open('pack/synthetic_documents/gold/document_gold.jsonl',"
        "encoding='utf-8') if x.strip()];STORE.warm();s=STORE.new_session();"
        "r=score(list(s.views.values()),gold);"
        "print(json.dumps({'exact_match':r['exact_match'],'wrong':r['wrong'],"
        "'abstained':r['abstained'],'missed':r['missed'],'fields_total':r['fields_total'],"
        "'bbox':r['bbox']}))"])
    clear_cache()
    external = run_json(["scripts/measure_external_holdout.py", "--json"])["deterministic"]
    confirm = run_json(["scripts/measure_confirm_set.py", "--json"])
    pytest_result = bfs.run_pytest()

    # --- G1: wrong == 0 everywhere -------------------------------------------------
    wrongs = {"pack": verify_pack["wrong"], "external": external["wrong"], "confirm": confirm["wrong"]}
    gate("G1", all(v == 0 for v in wrongs.values()), wrongs)

    # --- G2: the pack does not move -------------------------------------------------
    iou_mean = verify_pack["bbox"]["iou_mean"]
    g2 = {
        "correct": verify_pack["exact_match"], "correct_required": 159,
        "abstained": verify_pack["abstained"], "abstained_required": 0,
        "iou_over_05": verify_pack["bbox"]["iou_gt_0_5"], "iou_over_05_required": 159,
        "iou_mean": round(iou_mean, 6),
        "iou_mean_floor": round(baseline["pack"]["iou_mean"] - 0.0005, 6),
    }
    gate("G2", (g2["correct"] == 159 and g2["abstained"] == 0
                and g2["iou_over_05"] == 159 and iou_mean >= g2["iou_mean_floor"]), g2)

    # --- G3 / G7: field-level state, recomputed and diffed --------------------------
    clear_cache()
    census = bfs.measure(quiet=True)
    if census["problems"]:
        raise SystemExit(
            "CRASH (not a gate failure): the field-state classifier no longer reconciles "
            "with the harnesses:\n  " + "\n  ".join(census["problems"])
        )

    before = dict(baseline["field_state"])
    before.update({k: f"absent:{v}" for k, v in baseline.get("absent_state", {}).items()})
    after = dict(census["field_state"])
    after.update({k: f"absent:{v}" for k, v in census.get("absent_state", {}).items()})

    regressions = sorted(
        f"{k}: {before[k]} -> {after.get(k, '<field disappeared>')}"
        for k in before
        if before[k] in ("correct", "absent:absent") and after.get(k) != before[k]
    )
    gate("G3", not regressions, {"regressions": regressions,
                                 "fields_compared": len(before)})

    flips = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    predicted = set(args.predict or [])
    unpredicted = sorted(set(flips) - predicted)
    if args.target:
        item = _backlog_item(args.target)
        target_fields = set(item.get("fields", [])) if item else set()
        hit = sorted(set(flips) & target_fields)
        g7 = {"mode": "iteration", "target": args.target, "predicted": sorted(predicted),
              "observed": flips, "unpredicted": unpredicted,
              "target_fields_flipped": hit}
        gate("G7", not unpredicted and bool(hit), g7)
    else:
        g7 = {"mode": "baseline self-check", "observed": flips,
              "requirement": "the unchanged tree must flip nothing"}
        gate("G7", not flips, g7)

    # --- G4: pytest ------------------------------------------------------------------
    g4 = {"passed": pytest_result["passed"], "failed": pytest_result["failed"],
          "baseline_passed": baseline["pytest"]["passed"]}
    gate("G4", (pytest_result["failed"] == 0
                and pytest_result["passed"] >= baseline["pytest"]["passed"]), g4)

    # --- G6: diff scope ---------------------------------------------------------------
    changed = [
        line.strip().replace("\\", "/")
        for line in subprocess.run(
            ["git", "diff", "--name-only", "HEAD"], cwd=str(cl.ROOT),
            capture_output=True, text=True).stdout.splitlines()
        if line.strip()
    ]
    untracked = [
        line.strip().replace("\\", "/")
        for line in subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=str(cl.ROOT),
            capture_output=True, text=True).stdout.splitlines()
        if line.strip()
    ]
    everything = sorted(set(changed) | set(untracked))
    exempted = [p for p in everything if DIFF_EXEMPT.match(p)]
    # Day-0 dirt this iteration did not create. See build_field_state.preexisting_dirty
    # for why this exemption exists and why it does not extend to forbidden paths.
    preexisting = set(baseline.get("preexisting_dirty", []))
    considered = [p for p in everything if not DIFF_EXEMPT.match(p) and p not in preexisting]

    allowlist = set(args.allow or [])
    outside = [
        p for p in considered
        if not p.startswith("loop/") and p not in allowlist
    ]
    # Deliberately over `everything`, not `considered`: a protected file that was already
    # dirty on day 0 still fails G6. The instruments are frozen for everyone.
    forbidden_hit = [
        p for p in everything
        if p in FORBIDDEN or any(pattern.search(p) for pattern in FORBIDDEN_PATTERNS)
    ]
    gate("G6", not outside and not forbidden_hit,
         {"allowlist": sorted(allowlist), "changed": considered,
          "outside_allowlist": outside, "forbidden_touched": forbidden_hit,
          "cache_paths_exempted": len(exempted),
          "preexisting_dirt_exempted": len(preexisting)})

    # --- G5: flag-off identity ---------------------------------------------------------
    g5 = g5_flag_off_identity(docs, list(args.flag or []),
                              baseline["accepted_commit"], scratch)
    gate("G5", g5["identical"], g5)

    order = {f"G{i}": i for i in range(1, 8)}
    results.sort(key=lambda r: order[r["gate"]])
    return {
        "iteration": args.iteration,
        "target": args.target,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "head": bfs.head_sha(),
        "accepted_commit": baseline["accepted_commit"],
        "verdict": "PASS" if all(r["pass"] for r in results) else "REJECTED_GATE",
        "failed_gates": [r["gate"] for r in results if not r["pass"]],
        "gates": results,
        "measurements": {
            "pack": {"correct": verify_pack["exact_match"], "of": verify_pack["fields_total"],
                     "wrong": verify_pack["wrong"], "abstained": verify_pack["abstained"],
                     "iou_mean": round(iou_mean, 6),
                     "iou_over_05": verify_pack["bbox"]["iou_gt_0_5"]},
            "external": {"correct": external["correct"], "of": external["fields_total"],
                         "wrong": external["wrong"], "abstained": external["abstained"]},
            "confirm": {"correct": confirm["correct"], "of": confirm["fields_total"],
                        "wrong": confirm["wrong"], "abstained": confirm["abstained"]},
            "pytest": pytest_result,
        },
        "field_state_census": census["field_state_census"],
        "field_flips_observed": flips,
        "flag_off_identical": g5["identical"],
        "diff_files": considered,
    }


def _backlog_item(target: str) -> dict | None:
    data = json.loads(cl.BACKLOG_PATH.read_text(encoding="utf-8"))
    for item in data["items"]:
        if item["id"] == target:
            return item
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iteration", type=int, required=True, help="NNN for measurements/it-NNN.json")
    parser.add_argument("--target", default=None, help="backlog id; omit for the baseline self-check")
    parser.add_argument("--flag", action="append", default=[],
                        help="this iteration's feature flag, set to 0 for G5 (repeatable)")
    parser.add_argument("--allow", action="append", default=[],
                        help="a path from the proposal's G6 module allowlist (repeatable)")
    parser.add_argument("--predict", action="append", default=[],
                        help="a predicted flip, corpus::doc::field (repeatable)")
    args = parser.parse_args(argv)

    report = evaluate(args)

    out = cl.LOOP / "measurements" / f"it-{args.iteration:03d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 74)
    print(f"gate  it-{args.iteration:03d}  target={args.target or '(baseline self-check)'}")
    print("=" * 74)
    for row in report["gates"]:
        mark = "PASS" if row["pass"] else "FAIL"
        print(f"  {row['gate']}  {mark}")
        if not row["pass"]:
            print("        " + json.dumps(row["detail"], ensure_ascii=False)[:900])
    m = report["measurements"]
    print("-" * 74)
    print(f"  pack     {m['pack']['correct']}/{m['pack']['of']}  wrong {m['pack']['wrong']}  "
          f"IoU mean {m['pack']['iou_mean']}  IoU>0.5 {m['pack']['iou_over_05']}")
    print(f"  external {m['external']['correct']}/{m['external']['of']}  wrong {m['external']['wrong']}")
    print(f"  confirm  {m['confirm']['correct']}/{m['confirm']['of']}  wrong {m['confirm']['wrong']}")
    print(f"  pytest   {m['pytest']['passed']} passed, {m['pytest']['failed']} failed")
    print(f"  flips    {report['field_flips_observed'] or 'none'}")
    print(f"\nVERDICT: {report['verdict']}"
          + (f"  failed: {', '.join(report['failed_gates'])}" if report["failed_gates"] else ""))
    print(f"wrote {out}")
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
