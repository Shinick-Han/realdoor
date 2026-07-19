# -*- coding: utf-8 -*-
"""
verify.py — 지휘자 검증용. 워커 보고 숫자를 믿지 않고 직접 재실행한다.

`/gate` 규율: "worker 보고 숫자를 믿지 마라. acceptance 스크립트를 지휘자가 직접 재실행."
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def line(label: str, value: str) -> None:
    print(f"{label:<34}{value}")


def main() -> int:
    from run_adversarial import run_suite, safe_responder, unsafe_responder  # type: ignore
    from api import ask as ask_mod
    from logic.answer_rules import score_against_gold
    from logic.household import load_gold_households
    from score_extraction import score  # type: ignore
    from api.store import STORE

    print("=" * 62)
    print("지휘자 독립 검증")
    print("=" * 62)

    houses = load_gold_households()

    # 1. 적대적 스위트 — 우리 응답자
    res = run_suite(lambda t: ask_mod.handle(t, None, houses))
    dirty = [r["test_id"] for r in res["results"] if not r.get("must_not_clean", True)]
    line("적대적 (우리 응답자)", f"{res['passed']}/{res['total']}  must_not 위반 {len(dirty)}건")

    # 2. 음성 대조군 — 탐지기가 약해지지 않았는지
    for name, responder in (("safe", safe_responder), ("unsafe", unsafe_responder)):
        try:
            r = run_suite(responder)
            caught = sum(1 for x in r["results"] if not x["passed"])
            line(f"  대조군 {name}", f"{r['passed']}/{r['total']} 통과 · {caught} 적발")
        except Exception as exc:  # 대조군 이름이 바뀌었으면 조용히 넘어가지 않는다
            line(f"  대조군 {name}", f"확인 불가 — {type(exc).__name__}")

    # 3. qa_gold
    q = score_against_gold()
    line("규칙 질문 (qa_gold)",
         f"정답 {q['correct']} · 오답 {q['wrong']} · 기권 {q['abstained']} / {q['total']}")

    # 4. 추출 — 실제 파이프라인
    STORE.warm()
    s = STORE.new_session()
    gold = [json.loads(x) for x in
            (ROOT / "pack/synthetic_documents/gold/document_gold.jsonl")
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    e = score(list(s.views.values()), gold)
    b = e.get("bbox", {})
    line("추출", f"{e['exact_match']}/{e['fields_total']} 정확 · 오답 {e['wrong']} · "
                 f"기권 {e['abstained']} · 누락 {e['missed']}")
    line("  bbox", f"IoU>0.5 {b.get('iou_gt_0_5')}/{b.get('evaluated')} · "
                   f"평균 {round(b.get('iou_mean', 0), 4)}")

    # 5. 6세대 회귀
    from logic.household import load_pack_checklists, required_document_types
    from logic.readiness import build_report
    cl = load_pack_checklists()
    statuses = []
    for hid in sorted(houses):
        rep = build_report(houses[hid], required_document_types(hid, cl))
        statuses.append(f"{hid[-3:]}:{'R' if rep['readiness_status'].startswith('READY') else 'N'}")
    line("6세대 준비도", " ".join(statuses))

    print("=" * 62)
    ok = (res["passed"] == res["total"] and not dirty
          and q["wrong"] == 0 and e["wrong"] == 0)
    print("판정:", "전부 통과" if ok else "확인 필요")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
