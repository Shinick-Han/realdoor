#!/usr/bin/env python3
"""Static no-decision guard over the whole repo.  Run:  pytest eval/test_no_decision.py

The brief: a submission that "approves, denies, scores, ranks, silently suppresses options,
or exposes sensitive data cannot win regardless of model quality." CONTRACTS section 0 turns
that into a hard rule: these names must never appear as response fields —

    eligible, approved, denied, score, rank, priority, qualified, recommendation

WHAT THIS GUARD CHECKS
  1. Every .json / .jsonl file we produce (repo minus pack/ minus vendor dirs): no banned
     key at any nesting depth. Compound keys are split on "_", "-" and camelCase humps, so
     ``is_approved``, ``riskScore`` and ``eligibility_status`` all fail.
  2. Every such file: values under the CONTRACTS section 1 enum keys (comparison,
     readiness_status, evidence_kind, certainty, state) must be inside the frozen enums.
     No extension, no near-misses.
  3. Source files (.py, .ts, .tsx, .js, .jsx, .json schemas): no banned name used as a
     quoted JSON/dict key literal, and none used as a schema property or pydantic field
     declaration (a bare ``<name>: <type>`` at class scope).
  4. eval/selftest.py's own payload is generated and scanned by rules 1 and 2 — our own
     report cannot smuggle a banned key in.
  5. The enum table in contracts/CONTRACTS.md still matches the constants used here, so the
     guard cannot silently drift away from the frozen contract.

WHAT THIS GUARD DOES NOT CHECK (it is a static, name-level guard, not a semantics check)
  * a decision expressed in prose ("you're all set") — no key, no enum, nothing to see
  * a differently-named key with decisive meaning ("verdict", "outcome", "greenlight",
    "readiness_index") — the banned list is exactly the 8 contract names plus obvious
    inflections; add to BANNED if the product grows a new one
  * runtime-constructed keys (``resp[prefix + "core"] = ...``)
  * anything inside pack/ (organizer data, read-only) or a virtualenv/node_modules
  * "silently suppresses options" — a behavioural property no static scan can see

DELIBERATE NEGATIVE FIXTURES
  eval/run_adversarial.py contains an intentionally non-compliant reference responder that
  emits ``"eligible"`` and ``"score"``; those lines carry the pragma ``# no-decision-fixture``
  and are allowed ONLY in files listed in FIXTURE_FILES. A pragma anywhere else fails.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL_DIR))

BANNED = {
    "eligible", "approved", "denied", "score", "rank", "priority", "qualified",
    "recommendation",
}
# inflections of the same eight concepts; a key containing any of these tokens fails
BANNED_TOKENS = BANNED | {
    "eligibility", "ineligible", "approval", "approve", "denial", "deny", "denies",
    "scored", "scoring", "ranked", "ranking", "prioritized", "prioritised", "prioritize",
    "qualify", "qualifies", "recommend", "recommended", "recommendations",
}

# CONTRACTS section 1 — frozen enums
ENUMS = {
    "comparison": {"below_or_equal", "above", "no_frozen_threshold"},
    "readiness_status": {"READY_TO_REVIEW", "NEEDS_REVIEW"},
    "evidence_kind": {"extracted", "confirmed_by_renter", "corrected_by_renter"},
    "certainty": {"high", "low", "abstain"},
    # 계약 개정(04:55) 반영: 'expiring_soon' 삭제(팩에 'soon'의 임계가 없음),
    # 'undatable' 신설(문서는 읽었으나 날짜에 일(日) 정밀도가 없음).
    "state": {"present", "missing", "expired", "undatable", "unreadable"},
}

EXCLUDED_DIRS = {
    "pack", ".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache",
    "dist", "build", ".next",
    # `.cache/extractions` holds extraction output keyed by content. It is a derived
    # artefact of files this guard already scans, so it adds no coverage -- and because
    # this walk makes one test per file, leaving it in meant the suite's SIZE followed
    # how many stale cache entries happened to sit on this disk. The count moved from
    # 2538 to 2106 on one machine without a line of product code changing. A test count
    # that answers "what is on your disk" instead of "what is in the repository" is not
    # a number we can put in a README.
    ".cache",
}
SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx"}
DATA_SUFFIXES = {".json", ".jsonl"}

FIXTURE_PRAGMA = "# no-decision-fixture"
FIXTURE_FILES = {
    "eval/run_adversarial.py",   # the deliberately non-compliant reference responder
    "eval/test_no_decision.py",  # this guard's own negative control
    "eval/test_harness.py",      # detector calibration fixtures
    "api/app.py",                # GET /api/_gate_selftest: the live negative control
                                 # that proves the runtime gate withholds a decision.
                                 # The brief requires controls be demonstrated live,
                                 # so one deliberate violation must exist to block.
}

_KEY_SPLIT = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


def rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def walk(suffixes: set[str]) -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def banned_tokens_in_key(key: str) -> set[str]:
    tokens = {t.lower() for t in _KEY_SPLIT.split(str(key)) if t}
    return tokens & BANNED_TOKENS


def scan_object(obj, path_repr: str = "$") -> tuple[list[str], list[str]]:
    """Return (banned_key_findings, enum_violations) for a decoded JSON object."""
    banned_hits: list[str] = []
    enum_hits: list[str] = []

    def walk_obj(node, where: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{where}.{key}"
                hit = banned_tokens_in_key(key)
                if hit:
                    banned_hits.append(f"{here}  (banned token(s): {sorted(hit)})")
                if key in ENUMS and isinstance(value, str) and value not in ENUMS[key]:
                    enum_hits.append(
                        f"{here} = {value!r} not in {sorted(ENUMS[key])}"
                    )
                walk_obj(value, here)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk_obj(item, f"{where}[{index}]")

    walk_obj(obj, path_repr)
    return banned_hits, enum_hits


def load_data_file(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


# =====================================================================================
# tests
# =====================================================================================
def test_repo_has_data_or_source_files_to_scan():
    """Guard against a vacuous pass (an empty scan reporting success)."""
    assert walk(SOURCE_SUFFIXES), "no source files found to scan — guard would be vacuous"


@pytest.mark.parametrize("path", walk(DATA_SUFFIXES), ids=rel)
def test_json_files_have_no_banned_keys_and_valid_enums(path: Path):
    for document in load_data_file(path):
        banned_hits, enum_hits = scan_object(document, rel(path))
        assert not banned_hits, (
            f"banned response key(s) in {rel(path)}:\n  " + "\n  ".join(banned_hits)
        )
        assert not enum_hits, (
            f"value outside CONTRACTS section 1 enums in {rel(path)}:\n  "
            + "\n  ".join(enum_hits)
        )


_KEY_LITERAL = re.compile(
    r"""["']([A-Za-z_][A-Za-z0-9_]*)["']\s*:"""      # a quoted key followed by a colon
)
_FIELD_DECL = re.compile(
    r"""^\s{0,8}([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[A-Za-z\[\{"']"""  # name: type, at class scope
)


@pytest.mark.parametrize("path", walk(SOURCE_SUFFIXES), ids=rel)
def test_source_files_declare_no_banned_response_fields(path: Path):
    findings = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FIXTURE_PRAGMA in line:
            assert rel(path) in FIXTURE_FILES, (
                f"{rel(path)}:{line_no}: {FIXTURE_PRAGMA} pragma is only allowed in "
                f"{sorted(FIXTURE_FILES)}"
            )
            continue
        for match in _KEY_LITERAL.finditer(line):
            hit = banned_tokens_in_key(match.group(1))
            if hit:
                findings.append(f"{rel(path)}:{line_no}: key {match.group(1)!r} {sorted(hit)}")
        decl = _FIELD_DECL.match(line)
        if decl:
            hit = banned_tokens_in_key(decl.group(1))
            if hit:
                findings.append(
                    f"{rel(path)}:{line_no}: field decl {decl.group(1)!r} {sorted(hit)}"
                )
    assert not findings, "banned response field(s) declared:\n  " + "\n  ".join(findings)


def test_selftest_payload_is_clean():
    """Our own scorecard must obey the same rule as everything else."""
    import selftest

    payload = selftest.build_payload(now="1970-01-01T00:00:00Z")
    banned_hits, enum_hits = scan_object(payload, "selftest")
    assert not banned_hits, "eval/selftest.py emits banned key(s): " + str(banned_hits)
    assert not enum_hits, "eval/selftest.py emits invalid enum value(s): " + str(enum_hits)


def test_scorer_and_adversarial_reports_are_clean():
    """The reports the harness itself produces must not contain banned keys."""
    import run_adversarial
    import score_extraction

    report, _problems = score_extraction.self_check()
    banned_hits, enum_hits = scan_object(report, "score_extraction")
    assert not banned_hits, str(banned_hits)
    assert not enum_hits, str(enum_hits)

    adv = run_adversarial.run_suite(run_adversarial.safe_responder)
    banned_hits, enum_hits = scan_object(adv, "run_adversarial")
    assert not banned_hits, str(banned_hits)
    assert not enum_hits, str(enum_hits)


def test_enum_table_matches_frozen_contract():
    """If CONTRACTS section 1 changes, this guard must be updated in lockstep."""
    contracts = (REPO_ROOT / "contracts" / "CONTRACTS.md").read_text(encoding="utf-8")
    block = re.search(r"## 1\..*?```(.*?)```", contracts, re.S)
    assert block, "could not find the enum block in contracts/CONTRACTS.md section 1"

    declared: dict[str, set[str]] = {}
    for line in block.group(1).splitlines():
        if "=" not in line:
            continue
        name, values = line.split("=", 1)
        key = {
            "Comparison": "comparison",
            "ReadinessStatus": "readiness_status",
            "EvidenceKind": "evidence_kind",
            "Certainty": "certainty",
            "ItemState": "state",
        }.get(name.strip())
        if key:
            declared[key] = set(re.findall(r'"([^"]+)"', values))

    assert declared == ENUMS, (
        "CONTRACTS section 1 and this guard disagree.\n"
        f"  contract: {declared}\n  guard:    {ENUMS}"
    )


def test_banned_list_matches_frozen_contract():
    contracts = (REPO_ROOT / "contracts" / "CONTRACTS.md").read_text(encoding="utf-8")
    section = contracts.split("## 1.")[0]
    declared = set(re.findall(r"`([a-z_]+)`", section.split("다음 필드가")[-1]))
    missing = BANNED - declared
    assert not missing, f"CONTRACTS section 0 no longer lists: {sorted(missing)}"


def test_guard_catches_a_planted_violation():
    """Negative control: the scanner must actually fire on a known-bad object."""
    bad = {"household_id": "HH-001",
           "eligible": True,  # no-decision-fixture
           "nested": [{"riskScore": 3}],  # no-decision-fixture
           "comparison": "definitely_below"}
    banned_hits, enum_hits = scan_object(bad)
    assert len(banned_hits) == 2, banned_hits
    assert len(enum_hits) == 1, enum_hits
