# -*- coding: utf-8 -*-
"""인용 재확인 장치 자체를 잰다. **네트워크를 쓰지 않는다.**

여기서 확인하는 것은 "HUD 가 지금 뭐라고 쓰여 있나"가 아니라 이쪽 장치가
정직하게 구는가다. 특히 두 가지:

  * 네트워크가 없거나 막히면 결과가 **not_run 으로 강등**되는가. 조용히 0 이 되거나,
    더 나쁘게는 통과로 보이지 않는가. 이게 깨지면 "네트워크 없이 돈다"는 주장이
    같이 깨진다.
  * 팩 자신의 규약을 외부 출처 재확인 분모에 **넣지 않는가**. 우리가 쓴 것을 우리가
    읽고 맞다고 하는 것은 확인이 아니다.

바깥으로 나가는 시험은 `python eval/citation_recheck.py --refresh` 가 맡는다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "eval")):
    if path not in sys.path:
        sys.path.insert(0, path)

import citation_recheck as recheck  # noqa: E402
from api import gate, selftest  # noqa: E402


def _stamp(days_ago: float = 0.0) -> str:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


# =====================================================================================
# 분류 — 무엇이 재확인 대상인가
# =====================================================================================
def test_corpus_splits_into_outside_authority_and_our_own_rules():
    kinds = [recheck.classify(rule) for rule in recheck.load_corpus()]
    assert len(kinds) == 11
    assert kinds.count("external_authority") == 7
    assert kinds.count("self_issued") == 4


def test_our_own_rules_are_never_classified_as_outside_authority():
    for rule in recheck.load_corpus():
        if rule["authority"] == "hackathon_simulation":
            assert recheck.classify(rule) == "self_issued"
        # 저장소 안의 파일을 가리키는 인용은 링크가 아니므로 재확인 대상이 아니다
        if not rule["source_url"].startswith("http"):
            assert recheck.classify(rule) == "self_issued"


def test_every_outside_citation_has_something_specific_to_look_for():
    """대조 명세 없는 외부 인용이 남아 있으면 안 된다 — 링크가 200 을 준다는 것과
    우리가 인용한 문장이 거기 있다는 것은 다른 주장이다."""
    for rule in recheck.load_corpus():
        if recheck.classify(rule) == "external_authority":
            spec = recheck.CHECKS.get(rule["rule_id"])
            assert spec, f"{rule['rule_id']} has no re-check spec"
            assert spec.get("phrases"), f"{rule['rule_id']} looks for nothing in particular"


# =====================================================================================
# 대조 로직
# =====================================================================================
def test_a_missing_phrase_is_a_mismatch_not_a_pass():
    result = recheck.compare("the source now says something else entirely",
                             {"phrases": ["FY 2026 MFI: $164,600"]})
    assert result["matched"] is False
    assert result["missing"] == ["FY 2026 MFI: $164,600"]


def test_an_anchor_that_vanished_is_reported_as_such():
    result = recheck.compare("a page without our region on it",
                             {"anchor": "Boston-Cambridge-Quincy, MA-NH HMFA",
                              "phrases": ["anything"]})
    assert result["matched"] is False
    assert "anchor" in result["detail"]


def test_the_anchor_window_keeps_a_neighbouring_region_from_counting_as_ours():
    """같은 페이지의 다른 지역 블록에 있는 숫자를 우리 것으로 읽으면 안 된다."""
    page = ("Amherst Town-Northampton, MA MSA FY 2026 MFI: $124,400 "
            + "filler " * 120
            + "Boston-Cambridge-Quincy, MA-NH HMFA FY 2026 MFI: $164,600")
    spec = {"anchor": "Amherst Town-Northampton, MA MSA", "window": 200,
            "phrases": ["FY 2026 MFI: $164,600"]}
    assert recheck.compare(page, spec)["matched"] is False


def test_curly_quotes_and_dashes_do_not_manufacture_a_mismatch():
    spec = {"phrases": ["'R' - Interpolated rooftop"]}
    assert recheck.compare("codes: ‘R’ – Interpolated rooftop", spec)["matched"]


def test_a_word_the_rule_says_is_absent_breaks_the_match():
    spec = {"phrases": ["the database describes projects"],
            "absent": ["waitlist"]}
    result = recheck.compare("the database describes projects and the waitlist", spec)
    assert result["matched"] is False
    assert result["unexpected"] == ["waitlist"]


# =====================================================================================
# 오프라인 강등
# =====================================================================================
def test_offline_run_marks_every_outside_citation_not_run(tmp_path):
    payload = recheck.run(offline=True, artefact=tmp_path / "none.json")
    external = [r for r in payload["citations"] if r["classification"] == "external_authority"]
    assert external and all(r["outcome"] == "not_run" for r in external)
    assert payload["matched"] == 0
    assert payload["could_not_check"] == len(external)
    # 팩 자신의 규약은 네트워크와 무관하므로 오프라인에서도 대상 아님 그대로다
    ours = [r for r in payload["citations"] if r["classification"] == "self_issued"]
    assert ours and all(r["outcome"] == "not_applicable" for r in ours)


def test_offline_run_never_reports_a_citation_as_matched(tmp_path):
    payload = recheck.run(offline=True, artefact=tmp_path / "none.json")
    assert not any(r["outcome"] == "matched" for r in payload["citations"])


def test_scorecard_reads_not_run_when_nothing_could_be_checked(tmp_path):
    artefact = tmp_path / "cold.json"
    artefact.write_text(json.dumps(recheck.run(offline=True, artefact=artefact)),
                        encoding="utf-8")
    section = selftest.citations_section(artefact)
    assert section["status"] == "not_run"
    assert "re_fetched_and_matched" not in section  # not_run 절은 숫자를 달지 않는다


def test_scorecard_reads_not_run_when_there_is_no_artefact_at_all(tmp_path):
    section = selftest.citations_section(tmp_path / "absent.json")
    assert section["status"] == "not_run"
    assert "re_fetched_and_matched" not in section


# =====================================================================================
# 캐시 — 시연이 네트워크에 매달리지 않게, 다만 언제 확인한 것인지 달고
# =====================================================================================
def _artefact(tmp_path: Path, outcome: str, checked_at: str) -> Path:
    rows = []
    for rule in recheck.load_corpus():
        kind = recheck.classify(rule)
        rows.append({
            "rule_id": rule["rule_id"],
            "classification": kind,
            "outcome": outcome if kind == "external_authority" else "not_applicable",
            "checked_at": checked_at,
            "detail": "written by a test",
        })
    path = tmp_path / "artefact.json"
    path.write_text(json.dumps({"checked_at": checked_at, "citations": rows}),
                    encoding="utf-8")
    return path


def test_a_fresh_cached_result_is_kept_and_no_request_is_made(tmp_path):
    path = _artefact(tmp_path, "matched", _stamp(days_ago=1))
    payload = recheck.run(offline=True, artefact=path, max_age_days=7)
    assert payload["matched"] == 7
    assert all(r.get("from_cache") for r in payload["citations"])


def test_a_stale_cached_result_survives_a_run_that_could_not_reach_the_source(tmp_path):
    """지난번에 확인한 사실이 이번에 못 갔다고 사라지지는 않는다. 다만 지난번 시각을
    그대로 달고 남고, 이번에 왜 못 갔는지가 함께 적힌다."""
    path = _artefact(tmp_path, "matched", _stamp(days_ago=30))
    payload = recheck.run(offline=True, artefact=path, max_age_days=7)
    external = [r for r in payload["citations"] if r["classification"] == "external_authority"]
    assert all(r["outcome"] == "matched" for r in external)
    assert all(r["from_cache"] for r in external)
    assert all("could not be reached on this run" in r["last_attempt_detail"]
               for r in external)


def test_every_result_carries_the_time_it_was_checked(tmp_path):
    path = _artefact(tmp_path, "matched", _stamp(days_ago=3))
    section = selftest.citations_section(path)
    assert section["oldest_result_checked_at"]
    assert section["newest_result_checked_at"]
    assert section["oldest_result_age_days"] >= 2.9
    # 항목별 결과도 화면에 남아야 한다 — 총계만 있으면 어느 것이 안 됐는지 알 수 없다
    for rule in recheck.load_corpus():
        assert rule["rule_id"] in section["outcome_by_citation"]


def test_the_screen_says_which_citations_are_not_confirmed_and_why(tmp_path):
    path = _artefact(tmp_path, "matched", _stamp())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["citations"][0]["outcome"] = "not_run"
    data["citations"][0]["detail"] = "the source did not answer in time"
    path.write_text(json.dumps(data), encoding="utf-8")

    section = selftest.citations_section(path)
    assert data["citations"][0]["rule_id"] in section["citations_not_confirmed"]
    assert "did not answer in time" in section["citations_not_confirmed"]


def test_all_confirmed_says_so_in_words_rather_than_leaving_a_blank(tmp_path):
    section = selftest.citations_section(_artefact(tmp_path, "matched", _stamp()))
    assert "none" in section["citations_not_confirmed"]


# =====================================================================================
# 성적표에 실린 숫자가 무엇을 세는지
# =====================================================================================
def test_the_denominator_is_the_outside_citations_only(tmp_path):
    section = selftest.citations_section(_artefact(tmp_path, "matched", _stamp()))
    assert section["status"] == "measured"
    assert section["rules_in_corpus"] == 11
    assert section["external_citations_in_scope"] == 7
    assert section["self_issued_citations_out_of_scope"] == 4
    assert section["re_fetched_and_matched"] == 7
    assert "7 of 7 external citations" in section["headline"]


def test_a_partial_result_is_reported_as_partial(tmp_path):
    path = _artefact(tmp_path, "matched", _stamp())
    data = json.loads(path.read_text(encoding="utf-8"))
    data["citations"][5]["outcome"] = "not_run"
    data["citations"][6]["outcome"] = "did_not_match"
    path.write_text(json.dumps(data), encoding="utf-8")

    section = selftest.citations_section(path)
    assert section["re_fetched_and_matched"] == 5
    assert section["could_not_re_fetch"] == 1
    assert section["re_fetched_and_did_not_match"] == 1
    assert "5 of 7 external citations" in section["headline"]
    assert "1 no longer match" in section["headline"]
    assert "1 could not be reached" in section["headline"]


def test_the_section_never_carries_a_decision_shaped_key(tmp_path):
    for artefact in (_artefact(tmp_path, "matched", _stamp()), tmp_path / "absent.json"):
        assert gate.scan(selftest.citations_section(artefact)) == []


def test_building_the_scorecard_does_not_reach_the_network(monkeypatch):
    """이 화면은 심사위원이 열 때마다 HUD 로 요청을 내보내면 안 된다."""
    def explode(*_args, **_kwargs):
        raise AssertionError("the scorecard made a network request")

    monkeypatch.setattr(recheck, "fetch_bytes", explode)
    section = selftest.citations_section()
    assert section["status"] in {"measured", "not_run"}
