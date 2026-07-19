# -*- coding: utf-8 -*-
"""
test_contract.py — API 응답 모양을 못박는다.

이 테스트가 존재하는 이유:
  UI는 `contracts/CONTRACTS.md`의 JSON 모양에만 의존하고 코어 내부는 모른다.
  그래서 코어를 계속 고쳐도 UI는 안전하다 — **단, 모양이 안 변할 때만.**
  실제로 한 번 변했다(`expiring_soon` 삭제, `undatable` 추가).

  그러니 모양을 사람의 기억이 아니라 테스트로 지킨다. 앞으로 코어 변경이 UI를
  깨뜨리려 하면, 데모 중에 조용히 깨지는 대신 **여기서 빨간불**이 켜진다.

규칙: **추가는 되고, 삭제·개명은 안 된다.**
  필수 키가 있는지만 검사하고 여분 키는 허용한다. 새 필드를 붙이는 것은 UI를
  깨지 않지만, 이름을 바꾸거나 지우는 것은 깨뜨리기 때문이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.gate import BANNED_KEYS, ENUMS, scan
from api.store import STORE

FIXTURES = ROOT / "ui" / "fixtures"

REPORT_KEYS = {
    "household_id", "generated_at", "ruleset_version", "reference_date",
    "readiness_status", "review_reasons", "documents", "calculations",
    "checklist", "citations", "abstentions", "human_decision_notice",
    "engine_version",
}
DOCUMENT_KEYS = {"document_id", "document_type", "file_name", "fields"}
FIELD_KEYS = {"field", "value", "certainty", "evidence_kind"}
CALC_KEYS = {"name", "inputs", "formula", "result"}
CITATION_KEYS = {"rule_id", "authority", "effective_date", "text", "source_url",
                 "source_locator", "verified_against_source"}
ABSTENTION_KEYS = {"about", "reason", "what_would_resolve_it"}
REASON_KEYS = {"check", "code", "message", "rule_id"}


def report_fixtures() -> list[Path]:
    return sorted(FIXTURES.glob("report_*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixtures_exist():
    """빈 스캔이 통과로 보이는 것을 막는다."""
    assert report_fixtures(), "no report fixtures — run scripts/export_fixtures.py"


@pytest.mark.parametrize("path", report_fixtures(), ids=lambda p: p.stem)
def test_report_shape(path: Path):
    rep = load(path)
    missing = REPORT_KEYS - set(rep)
    assert not missing, f"{path.name}: ReadinessReport is missing {sorted(missing)}"

    for doc in rep["documents"]:
        assert not (DOCUMENT_KEYS - set(doc)), \
            f"{path.name}: document {doc.get('document_id')} missing " \
            f"{sorted(DOCUMENT_KEYS - set(doc))}"
        for f in doc["fields"]:
            assert not (FIELD_KEYS - set(f)), \
                f"{path.name}: field {f.get('field')} missing {sorted(FIELD_KEYS - set(f))}"
            # 값을 못 읽었으면 상자도 없어야 하고, 읽었으면 상자가 있어야 한다.
            if f.get("certainty") != "abstain":
                assert f.get("bbox"), \
                    f"{path.name}: {f.get('field')} has a value but no source box"

    for calc in rep["calculations"]:
        assert not (CALC_KEYS - set(calc)), \
            f"{path.name}: calculation missing {sorted(CALC_KEYS - set(calc))}"

    for cite in rep["citations"]:
        assert not (CITATION_KEYS - set(cite)), \
            f"{path.name}: citation missing {sorted(CITATION_KEYS - set(cite))}"

    for ab in rep["abstentions"]:
        assert not (ABSTENTION_KEYS - set(ab)), \
            f"{path.name}: abstention missing {sorted(ABSTENTION_KEYS - set(ab))}"

    for r in rep["review_reasons"]:
        assert not (REASON_KEYS - set(r)), \
            f"{path.name}: review reason missing {sorted(REASON_KEYS - set(r))}"
        assert r["message"], f"{path.name}: review reason {r['code']} has no message"


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_no_decision_anywhere_in_fixtures(path: Path):
    problems = scan(load(path))
    assert not problems, f"{path.name}: " + "; ".join(problems)


@pytest.mark.parametrize("path", report_fixtures(), ids=lambda p: p.stem)
def test_enums_are_frozen(path: Path):
    rep = load(path)
    assert rep["readiness_status"] in ENUMS["readiness_status"]
    for doc in rep["documents"]:
        for f in doc["fields"]:
            assert f["certainty"] in ENUMS["certainty"]
            assert f["evidence_kind"] in ENUMS["evidence_kind"]
    for calc in rep["calculations"]:
        if "comparison" in calc:
            assert calc["comparison"] in ENUMS["comparison"]


@pytest.mark.parametrize("path", report_fixtures(), ids=lambda p: p.stem)
def test_every_citation_is_a_real_pack_rule(path: Path):
    from logic.household import load_rule_corpus

    rules = load_rule_corpus()
    for cite in load(path)["citations"]:
        assert cite["rule_id"] in rules, \
            f"{path.name}: cites {cite['rule_id']}, which is not one of the 11 pack rules"


def test_fixtures_still_match_the_live_pipeline():
    """픽스처가 현실에서 떨어져 나가는 것을 막는다.

    UI는 픽스처를 보고 만들어진다. 픽스처가 낡으면 UI는 존재하지 않는 모양에
    맞춰 만들어진다. 그래서 살아있는 파이프라인과 키가 같은지 매 실행 확인한다.
    """
    STORE.warm()
    s = STORE.new_session()
    live = STORE.report(s, "HH-001")
    fixture = load(FIXTURES / "report_HH-001.json")

    assert set(fixture) - {"session_id"} <= set(live) | {"session_id"}, \
        "fixture has keys the live pipeline no longer produces — re-export fixtures"
    assert REPORT_KEYS <= set(live), \
        f"live pipeline is missing {sorted(REPORT_KEYS - set(live))}"
    assert live["readiness_status"] == fixture["readiness_status"], \
        "live readiness no longer matches the fixture — re-export and re-check the UI"


def test_banned_key_list_is_not_empty():
    """게이트가 비어 있으면 모든 검사가 무의미하게 통과한다."""
    assert len(BANNED_KEYS) >= 10
