# -*- coding: utf-8 -*-
"""
export_submission.py — 팩 스키마를 만족하는 제출 레코드를 세대별로 내보낸다.

참가자 가이드 p.2: "Produce output conforming to starter/schemas/submission.schema.json."
브리프는 살아 움직이는 UI를 요구하고 팩은 기계 채점용 JSON을 요구한다. 둘은 서로를
참조하지 않으므로 **양쪽 다 낸다.**

이 스크립트는 리포트를 다시 계산하지 않는다. 파이프라인이 만든 리포트에서 스키마가
요구하는 다섯 필드를 **꺼내 올 뿐**이다. 여기서 값을 손보기 시작하면 화면에 뜬 숫자와
제출한 숫자가 갈라진다.

검증은 통과 여부만 찍고 끝내지 않는다. 실패한 레코드는 **무엇이 왜 실패했는지** 함께
출력한다. 스키마를 못 맞추는 세대가 있다면 그건 감출 게 아니라 보고할 사실이다.

    python scripts/export_submission.py            # 검증만
    python scripts/export_submission.py --write    # out/submissions/ 에 기록
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_PATH = ROOT / "pack/starter/schemas/submission.schema.json"
OUT_DIR = ROOT / "out/submissions"

REQUIRED = ("household_id", "annualized_income", "comparison", "readiness_status", "citations")


def submission_from_report(report: dict) -> dict:
    """리포트에서 스키마가 요구하는 것만 뽑는다. 계산하지 않는다."""
    return {k: report.get(k) for k in REQUIRED}


def build_all() -> list[tuple[str, dict]]:
    from api.store import STORE

    STORE.warm()
    session = STORE.new_session()
    out = []
    for row in STORE.households(session):
        hid = row["household_id"]
        report = STORE.report(session, hid)
        if report is None:
            continue
        out.append((hid, submission_from_report(report)))
    return out


def validate(records: list[tuple[str, dict]]) -> tuple[int, list[str]]:
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    passed, failures = 0, []
    for hid, rec in records:
        errors = sorted(validator.iter_errors(rec), key=lambda e: list(e.path))
        if not errors:
            passed += 1
            continue
        for err in errors:
            where = "/".join(str(p) for p in err.path) or "(root)"
            failures.append(f"{hid}  {where}: {err.message}")
    return passed, failures


def main() -> int:
    records = build_all()
    passed, failures = validate(records)

    print(f"submission records {len(records)} · schema pass {passed} · "
          f"fail {len(failures)}")
    print(f"schema: {SCHEMA_PATH.relative_to(ROOT).as_posix()}")
    for line in failures:
        print(f"  ✗ {line}")

    for hid, rec in records:
        print(f"  {hid}  income={rec['annualized_income']!r}  "
              f"{rec['comparison']}  {rec['readiness_status']}  "
              f"citations={len(rec['citations'] or [])}")

    if "--write" in sys.argv:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for hid, rec in records:
            (OUT_DIR / f"{hid}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        combined = OUT_DIR / "all_households.jsonl"
        combined.write_text(
            "\n".join(json.dumps(rec, ensure_ascii=False) for _, rec in records) + "\n",
            encoding="utf-8")
        print(f"written: {OUT_DIR.relative_to(ROOT).as_posix()}/ "
              f"({len(records)} files + jsonl)")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
