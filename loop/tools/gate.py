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

AND A THIRD OUTCOME THE GATE OWES ITS READER
--------------------------------------------
G7's iteration test only means something if the target's fields are keys `field_state`
enumerates. When they are not, "the target's fields moved" is empty by construction and
the gate returns FAIL for a change that may have been perfect -- which is what happened in
it-008, it-009 and it-010, each closed by a human override. So G7 now separates "the
target did not move" (an iteration verdict, FAIL, exit 1) from "the gate cannot see the
target" (a GATE DEFECT, exit 2, offending keys named). See `_registry_defect`. Exit codes:
0 pass, 1 rejected on substance, 2 the gate could not judge.

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
sys.path.insert(0, ".")           # import the code of the tree we were pointed at
from core import extract as ex
docs = json.load(sys.stdin)       # but read the documents from one canonical copy
out = {}
for d in docs:
    view = ex.extract_document(d["path"], document_type=d["document_type"],
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

    # Absolute paths into the working tree, deliberately, for two reasons. The weaker one:
    # G5 asks whether this CODE, with its flag off, still produces what the accepted
    # commit's code produced -- so the inputs must be one identical set of bytes, not two
    # checkouts of them. The stronger one, measured: the 14 confirm PDFs are untracked in
    # git, so they exist at no commit and a worktree-relative read finds nothing there.
    payload = json.dumps([
        {"path": str(Path(d["path"]).resolve()),
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

    def gate(name: str, condition: bool, detail: Any, defect: str | None = None) -> None:
        row = {"gate": name, "pass": bool(condition), "detail": detail}
        if defect:
            # Not an iteration verdict. See `_registry_defect`.
            row["gate_defect"] = defect
        results.append(row)

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
        registry = set(before) | set(after)
        hit = sorted(set(flips) & target_fields)
        defect, defect_detail = _registry_defect(args.target, item, target_fields,
                                                 predicted, registry)
        g7 = {"mode": "iteration", "target": args.target, "predicted": sorted(predicted),
              "observed": flips, "unpredicted": unpredicted,
              "target_fields_flipped": hit,
              "registry_fields": len(registry), **defect_detail}
        if defect:
            # A gate that cannot see the target may not pronounce on the iteration. It
            # says so, names the keys, and fails -- so the registry gets extended rather
            # than the gate overridden.
            gate("G7", False, g7, defect=defect)
        else:
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

    # A gate that could not see what it was asked to judge has not judged. If some OTHER
    # gate failed on substance, the iteration is rejected on that substance and the defect
    # is reported alongside; if the defect is the only thing wrong, there is no iteration
    # verdict to give and the run says exactly that.
    defects = [r for r in results if r.get("gate_defect")]
    substantive = [r for r in results if not r["pass"] and not r.get("gate_defect")]
    verdict = "REJECTED_GATE" if substantive else ("GATE_DEFECT" if defects else "PASS")

    return {
        "iteration": args.iteration,
        "target": args.target,
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "head": bfs.head_sha(),
        "accepted_commit": baseline["accepted_commit"],
        "verdict": verdict,
        "failed_gates": [r["gate"] for r in results if not r["pass"]],
        "gate_defects": [{"gate": r["gate"], "defect": r["gate_defect"]} for r in defects],
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
        # G3 and G7 are only as trustworthy as the baseline they diff against. If that
        # baseline was built from a working tree, it defines the accepted state as whatever
        # was on disk that day, and these two gates are comparing against unaccepted work.
        # The gate does not fail on it -- the override exists for deliberate exceptions --
        # but it never lets the fact go unsaid.
        "baseline_provenance": baseline.get(
            "provenance", {"note": "baseline predates provenance recording"}),
        "field_state_census": census["field_state_census"],
        "field_flips_observed": flips,
        "flag_off_identical": g5["identical"],
        "diff_files": considered,
    }


def _registry_defect(target: str, item: dict | None, target_fields: set[str],
                     predicted: set[str], registry: set[str]) -> tuple[str | None, dict]:
    """Can G7 see this target at all? If not, that is a defect in the gate, not a verdict.

    G7's iteration test is "observed flips are a subset of the predicted set, AND the
    target's own fields actually moved". The second half silently assumes every target
    field is a key `field_state` enumerates. When it is not, `observed & target_fields` is
    empty *by construction*: the gate returns FAIL for a change that may have worked
    perfectly, and the only way forward is for a human to override the table by reading
    harness output instead.

    That happened three iterations running -- it-008, it-009, it-010, each of which
    recorded the override honestly in its report, and each of which filed the same
    instrument gap. Those three targets lived in `testdata/filled/`, which `field_state`
    did not enumerate; it does now, along with `testdata/scenarios/`. But "now" is not
    "forever": the next corpus will arrive the same way. So the structural hole is closed
    here rather than the instance of it.

    Three outcomes, distinguished:

        target fields moved as predicted  -> PASS       (an iteration verdict)
        target fields did not move        -> FAIL       (an iteration verdict)
        the gate cannot see the target    -> GATE_DEFECT (no iteration verdict exists)

    A defect is reported with the offending keys named, so the next person extends
    `build_field_state.py` instead of arguing with the table. It still exits non-zero --
    an unseeable target must never read as a pass -- but with its own exit code and its
    own verdict word, so "the gate is broken" can never be filed as "the change failed".

    Three ways to be unseeable, all of them the same defect at bottom:
      * the backlog has no such item -- nothing to check against;
      * the item declares no fields at all -- "observed & {}" can never be non-empty, so
        the test is unsatisfiable before any measurement is taken (the it-009 case);
      * a target or predicted key names no field in the registry -- the corpus it lives in
        is not enumerated (the it-008 / it-010 case).
    """
    if item is None:
        return (f"backlog has no item {target}; G7 has nothing to test against",
                {"registry_defect": "no such backlog item"})
    if not target_fields:
        return (f"backlog item {target} declares no fields, so \"the target's fields "
                f"moved\" is unsatisfiable before anything is measured",
                {"registry_defect": "target declares no fields"})

    unknown_target = sorted(target_fields - registry)
    unknown_predicted = sorted(predicted - registry)
    if unknown_target or unknown_predicted:
        named = unknown_target + [k for k in unknown_predicted if k not in unknown_target]
        return (
            f"{len(named)} key(s) name no field the registry enumerates, so G7 cannot "
            f"observe them: {', '.join(named[:8])}"
            + (" ..." if len(named) > 8 else "")
            + ". Extend loop/tools/build_field_state.py to cover their corpus; do not "
              "override this gate.",
            {"registry_defect": "keys outside the registry",
             "target_fields_not_in_registry": unknown_target,
             "predicted_not_in_registry": unknown_predicted},
        )
    return None, {}


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
        mark = "PASS" if row["pass"] else ("DEFECT" if row.get("gate_defect") else "FAIL")
        print(f"  {row['gate']}  {mark}")
        if row.get("gate_defect"):
            print(f"        GATE DEFECT: {row['gate_defect']}")
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
    prov = report["baseline_provenance"]
    if prov.get("extraction_tree_clean") is False:
        print(f"  WARNING: the baseline G3/G7 diff against was built from a DIRTY tree "
              f"({len(prov.get('extraction_tree_dirt', []))} path(s)); it may define "
              f"unaccepted work as correct")
    elif "built_from_commit" not in prov:
        print("  WARNING: the baseline records no provenance; what commit it describes "
              "cannot be checked")
    print(f"\nVERDICT: {report['verdict']}"
          + (f"  failed: {', '.join(report['failed_gates'])}" if report["failed_gates"] else ""))
    if report["gate_defects"]:
        print("\nThis is a defect in the GATE, not a verdict on the iteration: the gate "
              "could not\nsee what it was asked to judge. Extend the registry "
              "(loop/tools/build_field_state.py)\nso the next run can answer. Do not "
              "override.")
    print(f"wrote {out}")
    # 0 pass, 1 rejected on substance, 2 the gate could not judge -- three states, three
    # codes, so a caller can never read "the gate is broken" as "the change failed".
    return {"PASS": 0, "REJECTED_GATE": 1, "GATE_DEFECT": 2}[report["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
