# -*- coding: utf-8 -*-
"""자기 성적표 픽스처를 사람이 읽는 형태로. 데모 마지막 화면에 뜰 숫자다."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
p = Path(sys.argv[1] if len(sys.argv) > 1 else "ui/fixtures/selftest.json")
d = json.loads(p.read_text(encoding="utf-8"))

for name, s in d["sections"].items():
    detail = ""
    if name == "adversarial":
        detail = f"  {s.get('passed')}/{s.get('total_tests')} (고유 입력 {s.get('distinct_inputs')}종)"
    elif name == "extraction":
        detail = (f"  {s.get('exact_match')}/{s.get('fields_total')} 정확 · "
                  f"오답 {s.get('wrong')} · 기권 {s.get('abstained')} · "
                  f"IoU {s.get('bbox_iou_mean')}")
    elif name == "calculation":
        detail = f"  {s.get('agree_with_organizer_reference')}/{s.get('checks')} 일치"
    elif name == "rule_questions":
        detail = f"  정답 {s.get('correct')} · 오답 {s.get('wrong')} / {s.get('total')}"
    elif name == "citations":
        detail = f"  {s.get('verified_against_live_source')}/{s.get('rules_in_corpus')} 원문 확인"
    print(f"  {name:<16}{s['status']:<10}{detail}")
