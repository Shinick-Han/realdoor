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
        detail = (f"  {s.get('passed')}/{s.get('total_tests')} "
                  f"({s.get('distinct_inputs')} distinct inputs)")
    elif name == "extraction":
        detail = (f"  {s.get('exact_match')}/{s.get('fields_total')} exact · "
                  f"wrong {s.get('wrong')} · abstained {s.get('abstained')} · "
                  f"IoU {s.get('bbox_iou_mean')}")
    elif name == "calculation":
        detail = (f"  {s.get('agree_with_organizer_reference')}/{s.get('checks')} "
                  f"agree with the organizer reference")
    elif name == "rule_questions":
        detail = f"  correct {s.get('correct')} · wrong {s.get('wrong')} / {s.get('total')}"
    elif name == "citations":
        # 분모는 바깥 기관 출처를 가진 인용만. 팩 자신의 규약은 재확인 대상이 아니다.
        detail = (f"  {s.get('re_fetched_and_matched')}/"
                  f"{s.get('external_citations_in_scope')} external citations "
                  f"re-fetched and matched the source · "
                  f"did not match {s.get('re_fetched_and_did_not_match')} · "
                  f"could not re-fetch {s.get('could_not_re_fetch')} · "
                  f"{s.get('self_issued_citations_out_of_scope')} pack-issued rules "
                  f"out of scope"
                  if s.get("status") == "measured" else
                  f"  No citation was checked against a source "
                  f"({s.get('rules_in_corpus')} rules in the corpus)")
    print(f"  {name:<18}{s['status']:<10}{detail}")
