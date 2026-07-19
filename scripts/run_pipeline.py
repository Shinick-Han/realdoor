# -*- coding: utf-8 -*-
"""
run_pipeline.py — 전 레이어 통합 실행 (P1 thin vertical slice).

PDF → (core 텍스트추출 | ocr 이미지추출) → logic(소득·한도·준비도·기권) → ReadinessReport

두 모드를 비교한다:
  --source gold  : 골드 필드를 입력으로 (로직만 검증)
  --source real  : 실제 추출 결과를 입력으로 (전체 파이프라인)
두 모드의 결과가 갈리면, 그 차이가 곧 추출 레이어의 실제 비용이다.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from core.extract import extract_document
from ocr.ocr_extract import extract_document_ocr
from logic.household import (households_from_views, load_gold_households,
                             load_pack_checklists, required_document_types)
from logic.readiness import build_report

GOLD = ROOT / "pack/synthetic_documents/gold/document_gold.jsonl"
DOCS = ROOT / "pack/synthetic_documents/documents"


def extract_all() -> list[dict]:
    """실제 추출: 텍스트 레이어가 있으면 core, 없으면 ocr."""
    views = []
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        g = json.loads(line)
        pdf = DOCS / g["file_name"]
        fn = extract_document_ocr if g.get("rasterized") else extract_document
        views.append(fn(str(pdf)))
    return views


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["gold", "real"], default="real")
    ap.add_argument("--household", help="only this household")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    if a.source == "gold":
        houses = load_gold_households()
    else:
        houses = households_from_views(extract_all())

    checklists = load_pack_checklists()
    reports = {}
    for hid in sorted(houses):
        if a.household and hid != a.household:
            continue
        reports[hid] = build_report(houses[hid],
                                    required_document_types(hid, checklists))

    print(f"{'household':<10}{'status':<18}{'income':>12}{'limit':>10}"
          f"  {'comparison':<20}{'abstained':>10}  reason")
    print("-" * 118)
    for hid, r in reports.items():
        d = r if isinstance(r, dict) else r.__dict__
        status = d.get("readiness_status", "?")
        calcs = d.get("calculations", []) or []
        inc = next((c.get("result") for c in calcs
                    if c.get("name") == "annualized_income"), None)
        thr = next((c.get("threshold") for c in calcs
                    if c.get("name") == "annualized_income"), None)
        cmp_ = next((c.get("comparison") for c in calcs
                     if c.get("name") == "annualized_income"), "-")
        abst = len(d.get("abstentions", []) or [])
        reasons = d.get("reasons") or [x.get("code") for x in d.get("reason_list", [])] or []
        if not reasons:
            reasons = [x.get("code", "") for x in (d.get("readiness_reasons") or [])]
        print(f"{hid:<10}{status:<18}"
              f"{(f'{inc:,.0f}' if inc is not None else '-'):>12}"
              f"{(f'{thr:,.0f}' if thr else '-'):>10}"
              f"  {cmp_:<20}{abst:>10}  {', '.join(r for r in reasons if r)[:34]}")

    if a.out:
        a.out.write_text(json.dumps(reports, ensure_ascii=False, indent=1, default=str),
                         encoding="utf-8")
        print(f"\nwritten: {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
