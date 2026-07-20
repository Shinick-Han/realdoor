# -*- coding: utf-8 -*-
"""run_phase.py -- how each of the six phases is invoked, in one executable place.

The loop's phases are short-lived agents that talk only through disk artefacts. This
driver is not an orchestrator that runs them; it is the written contract for what each
phase reads, what it must write, and which model it runs on -- printable, so a cold agent
can be handed `python loop/tools/run_phase.py p3 --iteration 17` and see exactly what its
job is and what mechanical step (if any) the harness performs for it.

    python loop/tools/run_phase.py                 # the whole contract, all six phases
    python loop/tools/run_phase.py p2 --iteration 17
    python loop/tools/run_phase.py next            # which backlog item is up, and why

Two phases have a mechanical body and actually execute here:

    p3   runs the proposal's firing predicate over the 77-document manifest and writes
         loop/falsification/it-NNN.json
    p5   is loop/tools/gate.py; this driver prints the exact command with the flags,
         allowlist and predicted flips filled in from the proposal's front matter

The rest print their contract and exit. That asymmetry is deliberate: P2 is judgment
work, P4 is code, P6 applies a table it is forbidden to argue with, and none of the three
becomes more reliable for being wrapped in a script.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import corpus_lib as cl  # noqa: E402

PHASES: dict[str, dict[str, Any]] = {
    "p2": {
        "name": "DIAGNOSE + PROPOSE",
        "model": "EXPENSIVE (Opus-class) -- one call per iteration, hard cap 2 with REVIEW",
        "why_this_model": (
            "The only judgment-heavy step. Constraint 2 -- a rule may only rest on what "
            "the page prints -- is exactly what cheap models fail: they reach for "
            "proximity ('nearest number to the right') because it works on the page in "
            "front of them."
        ),
        "reads": [
            "loop/baseline.json (~2 KB)",
            "the ONE backlog item, including its prior_attempts digest (<=10 lines/attempt)",
            "loop/worktmp/<doc>.words.json -- the target document's word dump, ONE pdf, not fourteen",
            "the truth entries for that document only",
            "only the core/ regions the diagnosis needs -- grep extract.py, do not read "
            "2,100 lines of it",
        ],
        "writes": ["loop/proposals/it-NNN.md (<=150 lines)", "loop/falsify/it-NNN.py"],
        "must": [
            "fill section 3 with exactly ONE of the five licenses: printed label / printed "
            "header row / printed conjunction / printed total closed by an arithmetic "
            "identity / physical bound. If none fits, return NO_SAFE_RULE -- that is a "
            "result, not a failure.",
            "name the hazard: the specific wrong value this rule could manufacture, and "
            "which part of the license refuses it. An empty hazard section is rejected by "
            "P6 without running anything.",
            "write the firing predicate as runnable read-only Python at loop/falsify/it-NNN.py.",
            "predict flips as an exact corpus::doc::field set, plus an explicit 'no other "
            "field changes on any corpus' claim.",
            "list the modules to be touched -- that list IS the G6 allowlist.",
            "be self-sufficient: P4 reads the proposal, never this phase's reasoning.",
        ],
    },
    "p3": {
        "name": "FALSIFY",
        "model": "CHEAP -- purely mechanical once P2 wrote the predicate",
        "why_this_model": (
            "Execute over 77 docs, join firings against truth, report conflicts. If the "
            "predicate is not mechanically executable that is a defect returned to P2, "
            "never something P3 interprets."
        ),
        "reads": ["loop/falsify/it-NNN.py", "loop/tools/corpus_manifest.json"],
        "writes": ["loop/falsification/it-NNN.json"],
        "must": [
            "run BEFORE any product code exists. The loop cannot reach P4 without a "
            "committed falsification artefact.",
            "conflicts >= 1  =>  verdict REJECTED_FALSIFIED. P4 never runs. The "
            "counterexample goes into the backlog item's prior_attempts digest so the next "
            "P2 attempt starts from it.",
            "record the firing COUNT even at zero conflicts: 'fired on 1 of 77' is strong "
            "specificity; 'fired on 40 of 77' is a red flag P6 surfaces in the report.",
            "the predicate must fire on the target document -- if it does not, the proposal "
            "does not describe the change it claims to.",
        ],
    },
    "p4": {
        "name": "IMPLEMENT",
        "model": "CHEAP -- fresh context, behind a flag",
        "why_this_model": "The proposal already specifies the rule, module, flag and tests.",
        "reads": ["loop/proposals/it-NNN.md", "the target module region -- NOT P2's transcript"],
        "writes": ["product code inside the proposal's allowlist, plus its tests"],
        "must": [
            "put the change behind REALDOOR_<NAME>, with the flag off restoring bit-identical "
            "behaviour. G5 checks this against the last accepted commit.",
            "stay inside the allowlist. G6 checks this.",
            "add tests, never remove them. G4 checks this.",
        ],
    },
    "p5": {
        "name": "MEASURE",
        "model": "SCRIPTS -- a cheap agent as driver only, zero judgment",
        "why_this_model": (
            "The previous attempt stalled twice waiting on its own measurements inside one "
            "context. Here measurement is a fresh agent that does nothing else, and no "
            "phase both edits and measures."
        ),
        "reads": ["nothing but the command line"],
        "writes": ["loop/measurements/it-NNN.json (written by gate.py itself)"],
        "must": [
            "run loop/tools/gate.py -- it clears .cache/extractions before every pass, "
            "parses stdout JSON only, and runs the flag-off identity leg against the "
            "accepted commit in a temporary git worktree.",
        ],
    },
    "p6": {
        "name": "VERDICT + BOOKKEEPING",
        "model": "CHEAP -- the gate is a table",
        "why_this_model": "Applying it must not be a judgment call. That is constraint 1.",
        "reads": ["loop/measurements/it-NNN.json", "loop/falsification/it-NNN.json"],
        "writes": [
            "loop/reports/it-NNN.md (<=80 lines, the section E template)",
            "one appended line in loop/ledger.jsonl",
            "updated loop/backlog.json (status, attempts, prior_attempts digest)",
            "on ACCEPT only: one commit on improve-loop and a rebuilt loop/baseline.json",
        ],
        "must": [
            "NOT argue with the table. Its only degrees of freedom are filling in the report.",
            "on REJECT: git restore --source=<accepted> --worktree -- . EXCLUDING loop/, "
            "increment the item's attempt counter, name the failed gate in the ledger.",
            "write the prior_attempts digest as 'what was proposed, which gate killed it, "
            "why', three lines per attempt. It is the ONLY channel by which failure history "
            "reaches the next P2.",
            "never state a gain without the wrong-count on the same line, and never without "
            "the corpus's inspection status.",
            "G7 anomaly (an unpredicted flip, EVEN A GAIN) => one expensive REVIEW call. "
            "Default on ambiguity: reject.",
        ],
    },
    "review": {
        "name": "REVIEW (conditional)",
        "model": "EXPENSIVE -- entered only on the G7 anomaly condition",
        "why_this_model": (
            "An unpredicted flip means the change does something its author did not "
            "understand, and that diagnosis is judgment work. Budgeted at <=1 per iteration."
        ),
        "reads": ["the diff", "loop/proposals/it-NNN.md", "the predicted and observed flip lists"],
        "writes": ["an amended proposal that re-enters at P3 as a new attempt, OR a rejection"],
        "must": [
            "treat an unpredicted GAIN as suspicion: a rule that helps where its author did "
            "not expect is a rule whose firing condition nobody understands, which is one "
            "document away from a wrong value.",
            "an amended proposal must carry its own license and its own falsification pass "
            "for the flips it now covers.",
        ],
    },
}

STOP_CONDITIONS = [
    "1. Ceiling: backlog has no OPEN items -> write STOP.md, done.",
    "2. NO_SAFE_RULE from P2 -> item closed immediately. No cheap-model second opinion, no "
    "retry with a 'creative' framing. (Prevents an agent reframing until proximity sneaks "
    "in wearing a license's clothes.)",
    "3. Repeated failure: 2 falsification rejections or 3 total rejected attempts on one "
    "target -> NO_SAFE_RULE, closed, digests to STOP.md.",
    "4. Thrash: 3 consecutive iterations without an ACCEPT across DIFFERENT targets -> pause, "
    "human decision required.",
    "5. Hard halt: any measurement at the branch head shows wrong > 0 -> the gate itself is "
    "broken. Freeze everything, human required. Should be unreachable.",
]


def print_phase(pid: str, iteration: int | None) -> None:
    phase = PHASES[pid]
    tag = f"it-{iteration:03d}" if iteration is not None else "it-NNN"
    print("=" * 78)
    print(f"{pid.upper()}  {phase['name']}   [{tag}]")
    print("=" * 78)
    print(f"MODEL: {phase['model']}")
    print(f"  {phase['why_this_model']}")
    for heading, key in (("READS", "reads"), ("WRITES", "writes"), ("MUST", "must")):
        print(f"\n{heading}:")
        for line in phase[key]:
            print(f"  - {line.replace('NNN', f'{iteration:03d}') if iteration is not None else line}")
    print()


def next_target() -> None:
    data = json.loads(cl.BACKLOG_PATH.read_text(encoding="utf-8"))
    openish = [i for i in data["items"] if i["status"] == "OPEN"]
    print(f"selection rule: {data['selection_rule']}\n")
    if not openish:
        print("No OPEN items. Stop condition 1: write loop/STOP.md and finish.")
        return
    openish.sort(key=lambda i: (-i.get("expected_yield", 0), i.get("attempts", 0), i["id"]))
    for item in openish:
        print(f"  {item['id']:<4} yield {item.get('expected_yield', 0):>2}  "
              f"attempts {item.get('attempts', 0)}  {item['title']}")
    chosen = openish[0]
    print(f"\nNEXT: {chosen['id']} -- {chosen['title']}")
    print(f"  corpus {chosen['corpus']}  doc {chosen['doc']}")
    for field in chosen["fields"]:
        print(f"    {field}")
    closed = [i for i in data["items"] if i["status"] != "OPEN"]
    if closed:
        print("\nalready closed, day 0, zero iterations spent:")
        for item in closed:
            print(f"  {item['id']:<4} {item['status']:<26} {len(item['fields'])} field(s)")


def run_p3(iteration: int) -> int:
    """Execute the proposal's firing predicate over all 77 documents.

    The predicate module must expose `fires(doc) -> None | dict`, where `doc` is one
    manifest entry and a dict result reports {"field", "value", "page", "bbox"}. Anything
    else is a defect in the proposal and is returned to P2, not interpreted here.
    """
    predicate_path = cl.LOOP / "falsify" / f"it-{iteration:03d}.py"
    if not predicate_path.exists():
        print(f"no predicate at {predicate_path} -- P2 has not produced one. "
              f"That is a defect in the proposal, returned to P2.", file=sys.stderr)
        return 2

    spec = importlib.util.spec_from_file_location(f"falsify_{iteration}", predicate_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "fires"):
        print(f"{predicate_path} exposes no `fires(doc)`; not mechanically executable. "
              f"Returned to P2 as a defect.", file=sys.stderr)
        return 2

    docs = cl.load_manifest()
    fired: list[dict[str, Any]] = []
    for doc in docs:
        result = module.fires(doc)
        if result:
            fired.append({"corpus": doc["corpus"], "doc": doc["doc"], **result})

    target_doc = getattr(module, "TARGET_DOC", None)
    report = {
        "predicate": f"loop/falsify/it-{iteration:03d}.py",
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents_swept": len(docs),
        "docs_fired": sorted({f"{f['corpus']}::{f['doc']}" for f in fired}),
        "firing_count": len(fired),
        "firings": fired,
        "conflicts": getattr(module, "conflicts", lambda f: [])(fired),
        "target_fired": any(f["doc"] == target_doc for f in fired) if target_doc else None,
    }
    report["verdict"] = "pass" if not report["conflicts"] else "fail"
    out = cl.LOOP / "falsification" / f"it-{iteration:03d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
                   encoding="utf-8")
    print(f"fired on {len(report['docs_fired'])}/{len(docs)} documents; "
          f"conflicts {len(report['conflicts'])}; verdict {report['verdict']}")
    if len(report["docs_fired"]) > 8:
        print("  RED FLAG: a predicate firing this widely is one P6 surfaces in the report "
              "even with zero conflicts (design D.1).")
    print(f"wrote {out}")
    return 0 if report["verdict"] == "pass" else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("phase", nargs="?", default="all",
                        choices=["all", "next", *PHASES.keys()])
    parser.add_argument("--iteration", type=int, default=None)
    parser.add_argument("--run", action="store_true",
                        help="p3 only: actually execute the predicate sweep")
    args = parser.parse_args(argv)

    if args.phase == "next":
        next_target()
        return 0
    if args.phase == "p3" and args.run:
        if args.iteration is None:
            parser.error("--iteration is required to run the p3 sweep")
        return run_p3(args.iteration)
    if args.phase == "all":
        for pid in PHASES:
            print_phase(pid, args.iteration)
        print("=" * 78)
        print("STOP CONDITIONS -- the loop MUST stop rather than continue when:")
        print("=" * 78)
        for line in STOP_CONDITIONS:
            print(f"  {line}")
        print("\nExpensive-call budget: 1 per iteration, +1 on anomaly, HARD CAP 2.")
        return 0

    print_phase(args.phase, args.iteration)
    if args.phase == "p5":
        it = f"{args.iteration:03d}" if args.iteration is not None else "NNN"
        print("COMMAND (fill the flag, allowlist and predictions from the proposal):")
        print(f"  python loop/tools/gate.py --iteration {it} --target <Tn> \\")
        print("      --flag REALDOOR_<NAME> \\")
        print("      --allow core/<module>.py --allow core/test_<module>.py \\")
        print("      --predict <corpus>::<doc>::<field>")
    if args.phase == "p3":
        it = f"{args.iteration:03d}" if args.iteration is not None else "NNN"
        print("COMMAND:")
        print(f"  python loop/tools/run_phase.py p3 --iteration {it} --run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
