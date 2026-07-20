# -*- coding: utf-8 -*-
"""test_gate_registry.py -- G7's three outcomes, and the two refusals that protect them.

The gap these cover, stated plainly: for three iterations running (it-008, it-009, it-010)
G7 returned FAIL for a target whose fields `field_state` did not enumerate. "Observed flips
intersect the target's fields" is empty by construction when the target is not in the
registry, so the gate could not distinguish "the change did nothing" from "I cannot see the
change". A human closed each iteration by reading harness output instead -- an override
that had become routine, which is a gate nobody believes.

These tests pin the distinction itself, not the instance of it. They are unit tests on
`gate._registry_defect` and `build_field_state._dev_records` precisely because the
end-to-end demonstration costs a quarter of an hour of extraction: the expensive run proves
the wiring once, and these keep it honest thereafter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_field_state as bfs  # noqa: E402
import gate  # noqa: E402

REGISTRY = {
    "filled::orangeusd_sample_paystub_filled.pdf::hourly_rate",
    "scenarios::S01_w_complete/S01-D01_application_summary.pdf::person_name",
    "confirm::ca_dlse_paystub_hourly.pdf::person_name",
}


# =====================================================================================
# G7 outcome 3: the gate cannot see the target
# =====================================================================================


def test_target_outside_the_registry_is_a_defect_not_a_verdict():
    """The it-008 / it-010 case: the target's corpus is not enumerated."""
    key = "somecorpus::doc.pdf::person_name"
    defect, detail = gate._registry_defect("T99", {"fields": [key]}, {key}, set(), REGISTRY)
    assert defect is not None
    assert detail["registry_defect"] == "keys outside the registry"
    # The missing key must be NAMED, or the next person cannot extend the registry.
    assert detail["target_fields_not_in_registry"] == [key]
    assert key in defect


def test_a_predicted_key_outside_the_registry_is_also_a_defect():
    """A predicted flip on a key nothing enumerates can never be observed."""
    known = "confirm::ca_dlse_paystub_hourly.pdf::person_name"
    ghost = "nowhere::doc.pdf::regular_hours"
    defect, detail = gate._registry_defect(
        "T99", {"fields": [known]}, {known}, {ghost}, REGISTRY)
    assert defect is not None
    assert detail["predicted_not_in_registry"] == [ghost]
    assert detail["target_fields_not_in_registry"] == []


def test_target_declaring_no_fields_is_a_defect():
    """The it-009 case: 'observed & {}' is unsatisfiable before anything is measured."""
    defect, detail = gate._registry_defect("T16", {"fields": []}, set(), set(), REGISTRY)
    assert defect is not None
    assert detail["registry_defect"] == "target declares no fields"


def test_unknown_backlog_item_is_a_defect():
    defect, detail = gate._registry_defect("T404", None, set(), set(), REGISTRY)
    assert defect is not None
    assert detail["registry_defect"] == "no such backlog item"


# =====================================================================================
# G7 outcomes 1 and 2: a real verdict, on a target the gate can see
# =====================================================================================


@pytest.mark.parametrize("key", sorted(REGISTRY))
def test_a_target_inside_the_registry_yields_no_defect(key):
    """Including the filled and scenarios keys -- the corpora that used to be invisible.

    This is the regression test for the whole change: if either new corpus ever falls out
    of `field_state` again, a target in it goes back to being unjudgeable and this fails.
    """
    defect, detail = gate._registry_defect("T15", {"fields": [key]}, {key}, {key}, REGISTRY)
    assert defect is None
    assert detail == {}


def test_the_three_outcomes_are_distinguishable():
    """moved / did not move / cannot see -- three states, not two."""
    seen = "filled::orangeusd_sample_paystub_filled.pdf::hourly_rate"
    unseen = "elsewhere::doc.pdf::hourly_rate"

    # (1) and (2) both reach a real verdict: no defect, and the verdict then turns on
    # whether the field actually flipped -- which is gate.evaluate's `bool(hit)`.
    assert gate._registry_defect("T15", {"fields": [seen]}, {seen}, set(), REGISTRY)[0] is None
    # (3) never reaches a verdict at all.
    assert gate._registry_defect("T15", {"fields": [unseen]}, {unseen}, set(), REGISTRY)[0]


# =====================================================================================
# the seal: `_dev_records` refuses rather than guesses
# =====================================================================================


def _manifest(dev, sealed):
    return {"roles": {"dev": dev, "sealed": sealed}}


def _rec(name, role):
    return {"file_name": name, "role": role}


def _ident(record):
    return record["file_name"]


def test_dev_and_sealed_split_when_record_and_roster_agree():
    manifest = _manifest(["a.pdf"], ["b.pdf"])
    records = [_rec("a.pdf", "dev"), _rec("b.pdf", "sealed")]
    dev, sealed = bfs._dev_records(manifest, records, _ident, "filled")
    assert [_ident(r) for r in dev] == ["a.pdf"]
    assert [_ident(r) for r in sealed] == ["b.pdf"]


def test_a_missing_roster_stops_the_build():
    with pytest.raises(SystemExit, match="no dev/sealed roster"):
        bfs._dev_records({}, [_rec("a.pdf", "dev")], _ident, "filled")


def test_a_record_with_no_role_stops_the_build():
    """Quietly skipping it would shrink the registry -- the exact failure being closed."""
    manifest = _manifest(["a.pdf"], [])
    with pytest.raises(SystemExit, match="neither 'dev' nor 'sealed'"):
        bfs._dev_records(manifest, [{"file_name": "a.pdf"}], _ident, "filled")


def test_record_and_roster_disagreeing_stops_the_build():
    """A sealed hold-out that a record calls dev must never be opened on the record's word."""
    manifest = _manifest([], ["b.pdf"])
    with pytest.raises(SystemExit, match="roster says"):
        bfs._dev_records(manifest, [_rec("b.pdf", "dev")], _ident, "filled")


def test_a_record_the_roster_does_not_name_stops_the_build():
    manifest = _manifest(["a.pdf"], [])
    with pytest.raises(SystemExit, match="roster does not name it"):
        bfs._dev_records(manifest, [_rec("a.pdf", "dev"), _rec("c.pdf", "dev")],
                         _ident, "filled")


def test_a_roster_entry_with_no_record_stops_the_build():
    """The seal must be accounted for in both directions, or a hold-out could vanish."""
    manifest = _manifest(["a.pdf"], ["gone.pdf"])
    with pytest.raises(SystemExit, match="no record matched"):
        bfs._dev_records(manifest, [_rec("a.pdf", "dev")], _ident, "filled")


# =====================================================================================
# the baseline may not describe a tree nobody accepted
# =====================================================================================


def test_extraction_bearing_paths_cover_the_trees_that_decide_an_extraction():
    """core/ is the one that actually bit: an untracked reader there redefined `correct`."""
    for tree in ("core/", "api/", "eval/", "scripts/"):
        assert tree in bfs.EXTRACTION_BEARING


def test_dirt_probe_reports_paths_as_repo_relative_posix():
    """The guard's output is read by a human under pressure; it must be pasteable."""
    for path in bfs.extraction_tree_dirt():
        assert "\\" not in path
        assert not path.startswith("/")
