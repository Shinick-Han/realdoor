# -*- coding: utf-8 -*-
"""
test_submission_schema.py — 팩 스키마 준수를 고정한다.

브리프는 조작 가능한 UI를, 참가자 가이드는 `submission.schema.json` 을 만족하는 JSON을
요구한다. 두 문서는 서로를 참조하지 않으므로 우리는 양쪽을 다 만족시키기로 했다.

이 테스트가 지키는 것은 **최상위 다섯 필드가 리포트에서 사라지지 않는 것**이다. 값들이
`calculations` 안에만 살아 있던 시절이 있었고, 화면에서는 멀쩡해 보였다. 기계 채점기는
화면을 보지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_PATH = ROOT / "pack/starter/schemas/submission.schema.json"


@pytest.fixture(scope="module")
def submissions():
    from scripts.export_submission import build_all

    return build_all()


def test_schema_file_exists():
    assert SCHEMA_PATH.is_file(), f"팩 스키마가 없다: {SCHEMA_PATH}"


def test_every_household_conforms(submissions):
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    problems = []
    for hid, record in submissions:
        for err in validator.iter_errors(record):
            where = "/".join(str(p) for p in err.path) or "(root)"
            problems.append(f"{hid} {where}: {err.message}")
    assert not problems, "스키마 위반:\n" + "\n".join(problems)


def test_all_six_households_present(submissions):
    assert len(submissions) == 6, f"세대 6개가 아니라 {len(submissions)}개"


def test_values_come_from_the_report_not_recomputed(submissions):
    """최상위 값이 `calculations` 안의 값과 **같아야** 한다.

    두 경로로 같은 숫자를 계산하면 언젠가 갈라진다. 갈라진 순간, 화면이 참인지 제출물이
    참인지 말할 수 없게 된다. 그래서 여기서는 일치를 강제한다.
    """
    from api.store import STORE

    STORE.warm()
    session = STORE.new_session()
    for hid, record in submissions:
        report = STORE.report(session, hid)
        calcs = [c for c in report["calculations"] if c.get("name") == "annualized_income"]
        assert calcs, f"{hid}: annualized_income 계산이 리포트에 없다"
        nested = calcs[-1]
        assert record["annualized_income"] == nested["result"], (
            f"{hid}: 최상위 {record['annualized_income']!r} != "
            f"calculations {nested['result']!r}")
        assert record["comparison"] == nested["comparison"], (
            f"{hid}: 최상위 {record['comparison']!r} != "
            f"calculations {nested['comparison']!r}")


def test_no_decision_language_in_submission(submissions):
    """제출 레코드에도 판정이 실리면 안 된다. 스키마를 맞추느라 원칙을 놓지 않는다."""
    from api import gate

    for hid, record in submissions:
        problems = gate.scan(record)
        assert not problems, f"{hid}: 제출 레코드에 금지 키 {problems}"
