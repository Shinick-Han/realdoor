"""The abstention policy itself: shape, coverage, and the guarantee that it is one place."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from logic import abstain
from logic.abstain import ADVISORY, BLOCKING, POLICY, Abstention, raise_abstention, to_entries
from logic.constants import RULE_IDS

LOGIC_DIR = Path(__file__).resolve().parent


def test_every_trigger_cites_a_real_pack_rule():
    for spec in POLICY:
        assert spec.rule_id in RULE_IDS, f"{spec.name} cites {spec.rule_id}, not a pack rule"


def test_every_trigger_says_what_would_resolve_it():
    """An abstention with no route out is a dead end for the renter, not a safeguard."""
    for spec in POLICY:
        assert spec.what_would_resolve_it.strip(), f"{spec.name} offers no way forward"
        assert spec.reason.strip()
        assert spec.rationale.strip(), f"{spec.name} does not say why it exists"


def test_trigger_names_are_unique():
    names = [spec.name for spec in POLICY]
    assert len(names) == len(set(names))


def test_both_grades_are_populated():
    assert any(s.grade == BLOCKING for s in POLICY)
    assert any(s.grade == ADVISORY for s in POLICY)


def test_unknown_grade_is_rejected():
    with pytest.raises(ValueError, match="unknown grade"):
        Abstention("x", "y", "z", "maybe", "CH-INCOME-001", "t")


def test_unknown_rule_id_is_rejected():
    with pytest.raises(ValueError, match="not one of the 11 pack rules"):
        Abstention("x", "y", "z", BLOCKING, "CH-DOC-STUBS", "t")


def test_unknown_trigger_name_fails_loudly():
    """The failure mode we want: adding a branch elsewhere is harder than adding it here."""
    with pytest.raises(KeyError, match="not in the abstention policy"):
        abstain.trigger("some_ad_hoc_condition")


def test_entry_has_exactly_the_three_contract_keys():
    entry = raise_abstention("household_size_unknown", "threshold").to_entry()
    assert set(entry) == {"about", "reason", "what_would_resolve_it"}


def test_detail_is_appended_without_rewriting_the_policy_text():
    spec = abstain.trigger("household_size_outside_frozen_table")
    built = raise_abstention("household_size_outside_frozen_table", "threshold", "size 9")
    assert built.reason.startswith(spec.reason)
    assert "size 9" in built.reason


def test_entries_are_deduplicated_and_order_stable():
    items = [
        raise_abstention("household_size_unknown", "a"),
        raise_abstention("household_size_unknown", "a"),
        raise_abstention("document_unreadable", "b"),
    ]
    entries = to_entries(items)
    assert len(entries) == 2
    assert entries[0]["about"] == "a"


def test_blocking_filter():
    items = [raise_abstention("household_size_unknown", "a"),
             raise_abstention("document_not_current", "b")]
    blocked = abstain.blocking(items)
    assert len(blocked) == 1
    assert blocked[0].trigger == "household_size_unknown"


def test_the_policy_is_readable_in_one_place():
    text = abstain.policy_report()
    for spec in POLICY:
        assert spec.name in text
        assert spec.rationale in text


def test_no_abstention_text_labels_the_renter():
    """An abstention says what WE cannot do. It never says what the renter is."""
    banned = re.compile(
        r"\b(eligible|ineligible|approved|denied|qualified|unqualified|rejected)\b", re.I)
    for spec in POLICY:
        for field in (spec.reason, spec.what_would_resolve_it, spec.rationale):
            assert not banned.search(field), f"{spec.name}: {field!r}"


def test_the_extrapolation_refusal_is_explicit_about_being_deliberate():
    spec = abstain.trigger("household_size_outside_frozen_table")
    assert "deliberately" in spec.rationale or "do not use" in spec.rationale


def test_no_module_invents_its_own_abstention_shape():
    """Structural guard: only abstain.py may construct an Abstention directly.

    The value of a single policy table is entirely in nobody bypassing it. This walks the
    AST of every module in logic/ and fails if one builds an Abstention itself instead of
    going through raise_abstention().
    """
    offenders = []
    for path in sorted(LOGIC_DIR.glob("*.py")):
        if path.name in ("abstain.py", "conftest.py") or path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == "Abstention":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "these modules build an Abstention directly instead of using the policy table: "
        + ", ".join(offenders)
    )


def test_policy_covers_every_trigger_actually_used_in_the_codebase():
    """The reverse guard: no module raises a trigger name the policy does not define."""
    used = set()
    for path in sorted(LOGIC_DIR.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == "raise_abstention" and node.args:
                    first = node.args[0]
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        used.add(first.value)
    defined = {spec.name for spec in POLICY}
    assert used <= defined, f"undefined trigger(s) raised: {sorted(used - defined)}"


def test_every_defined_trigger_is_reachable_from_some_module():
    """A policy entry nothing can raise is documentation pretending to be behaviour."""
    used = set()
    for path in sorted(LOGIC_DIR.glob("*.py")):
        if path.name in ("abstain.py",) or path.name.startswith("test_"):
            continue
        text = path.read_text(encoding="utf-8")
        for spec in POLICY:
            if f'"{spec.name}"' in text or f"'{spec.name}'" in text:
                used.add(spec.name)
    unreached = {spec.name for spec in POLICY} - used
    assert not unreached, f"policy entries nothing can raise: {sorted(unreached)}"
