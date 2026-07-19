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
        # 분모는 바깥 기관 출처를 가진 인용만. 팩 자신의 규약은 재확인 대상이 아니다.
        detail = (f"  외부 {s.get('re_fetched_and_matched')}/"
                  f"{s.get('external_citations_in_scope')} 원문 재확인 · "
                  f"불일치 {s.get('re_fetched_and_did_not_match')} · "
                  f"확인 못 함 {s.get('could_not_re_fetch')} · "
                  f"팩 자체 규약 {s.get('self_issued_citations_out_of_scope')}건 대상 외"
                  if s.get("status") == "measured" else
                  f"  대조한 인용 없음 (전체 {s.get('rules_in_corpus')}건)")
    print(f"  {name:<16}{s['status']:<10}{detail}")
