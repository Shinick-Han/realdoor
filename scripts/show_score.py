# -*- coding: utf-8 -*-
"""Print a scoring report in a form a person can read.

The report file is an artefact, not something the repository carries: it is written by
`eval/score_extraction.py`. Saying so is the whole job of the missing-file branch below —
a traceback tells a reader that something is broken, when in fact they have simply not run
the step that produces the input yet.
"""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/_score24.json")
if not path.exists():
    print(f"No scoring report at {path}.")
    print("Nothing is wrong — this file is produced by a run, not stored in the repository.")
    print("Produce it with:  python eval/score_extraction.py")
    print(f"Or point this script at one:  python {Path(sys.argv[0]).name} <report.json>")
    raise SystemExit(1)
r = json.loads(path.read_text(encoding="utf-8"))
o = r.get("overall", r)

for k in ["fields_total", "exact_match", "wrong", "abstained", "missed",
          "accuracy", "selective_accuracy", "coverage"]:
    if k in o:
        v = o[k]
        print(f"{k:22}: {round(v, 4) if isinstance(v, float) else v}")

b = o.get("bbox", {})
print(f"{'bbox evaluated':22}: {b.get('evaluated')}")
print(f"{'bbox iou>0.5':22}: {b.get('iou_gt_0_5')}")
print(f"{'bbox iou_mean':22}: {round(b.get('iou_mean', 0), 4)}")

t = r.get("traceability", {})
print()
print("WRONG    :", t.get("wrong") or "none")
ab = t.get("abstained", [])
print("ABSTAINED:", [(a.get("document_id"), a.get("field")) for a in ab] or "none")
print("MISSED   :", t.get("missed") or "none")
