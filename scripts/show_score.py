# -*- coding: utf-8 -*-
"""지휘자 검증용: 채점 리포트를 사람이 읽는 형태로 출력한다."""
import json, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
path = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/_score24.json")
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
print("WRONG    :", t.get("wrong") or "없음")
ab = t.get("abstained", [])
print("ABSTAINED:", [(a.get("document_id"), a.get("field")) for a in ab] or "없음")
print("MISSED   :", t.get("missed") or "없음")
