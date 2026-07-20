# -*- coding: utf-8 -*-
"""Tests for core/skeleton.py -- the leak-proof page skeleton (T28 privacy boundary).

The falsification sweep (loop/falsify/it-014.py) proves leak-freedom over all seven
corpora; these are the fast, self-contained invariants the boundary must never lose.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from core import skeleton as sk

ROOT = Path(__file__).resolve().parent.parent
CONFIRM = ROOT / "testdata" / "confirm_raw"
PIECERATE = CONFIRM / "ca_dlse_paystub_piecerate.pdf"
HOURLY = CONFIRM / "ca_dlse_paystub_hourly.pdf"


def _skel(path) -> str:
    return sk.build_skeleton(path, respect_flag=False)


# --------------------------------------------------------------------------------------
# the promise: no value survives
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_piecerate_masks_person_and_employer_names():
    skel = _skel(PIECERATE).lower()
    # the employee and employer, both caption-shaped, both gone
    assert "johnson" not in skel
    assert "smith and company" not in skel
    assert "smith" not in skel


@pytest.mark.skipif(not HOURLY.exists(), reason="confirm corpus not present")
def test_hourly_masks_letterhead_employer_title():
    # `SMITH AND COMPANY, INC.` is printed as a 34pt letterhead title -- a free-floating
    # header, not in any value slot. It must still be redacted.
    skel = _skel(HOURLY).lower()
    assert "smith and company" not in skel
    assert "johnson" not in skel


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_skeleton_is_digit_free():
    # The core structural guarantee: no digit anywhere, so no numeric value (amount, date,
    # hours, id) can survive by construction. Page-header decoration is the CLI wrapper's;
    # the page skeletons themselves carry no digits.
    import pdfplumber
    from core.extract import read_words

    with pdfplumber.open(str(PIECERATE)) as pdf:
        for pnum, page in enumerate(pdf.pages, 1):
            body = sk.build_page_skeleton(read_words(page, pnum))
            assert not any(c.isdigit() for c in body), body


# --------------------------------------------------------------------------------------
# structure survives (not an empty redactor) and reads faithfully
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_piecerate_table_structure_survives():
    skel = _skel(PIECERATE)
    # column headers and the multi-row earnings labels stay, so the piece-rate table is
    # legible with every amount blanked
    for term in ("Rate/Hour", "Hours", "Productive", "Non-productive", "Rest Time",
                 "Gross Earnings", "Total Deductions:"):
        assert term in skel, term


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_footnote_markers_preserved_beside_placeholders():
    skel = _skel(PIECERATE)
    # `36.83 *` -> `<... > *` and `$19.37 **` -> `<...> **`: the footnote cue survives
    assert "*" in skel
    assert "**" in skel
    assert "<NUM> *" in skel or "<HRS> *" in skel


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_typed_placeholders_present():
    skel = _skel(PIECERATE)
    assert "<MONEY>" in skel
    assert "<NAME>" in skel  # the masked employee/employer
    assert "<NUM>" in skel or "<HRS>" in skel


# --------------------------------------------------------------------------------------
# vocabulary and typing units
# --------------------------------------------------------------------------------------


def test_structural_vocab_is_digit_free():
    assert not any(any(c.isdigit() for c in term) for term in sk.STRUCTURAL_VOCAB)


def test_known_captions_are_furniture():
    from core.extract import Word

    def run(text, bold=True):
        return [Word(text=text, x0=0, x1=10, baseline=100, glyph_bottom=98,
                     glyph_top=110, size=8.0, bold=bold, page=1)]

    for cap in ("GROSS WAGES", "EMPLOYEE'S NAME", "Rate/Hour", "Deductions:", "EMPLOYEE"):
        assert sk.is_furniture(run(cap)), cap


def test_entity_names_are_not_furniture():
    from core.extract import Word

    def run(text):
        return [Word(text=text, x0=0, x1=10, baseline=100, glyph_bottom=98,
                     glyph_top=110, size=8.0, bold=True, page=1)]

    for name in ("SMITH AND COMPANY, INC.", "Johnson, Bob", "Lansing Community College",
                 "BONITA UNIFIED", "ABC Staffing"):
        assert not sk.is_furniture(run(name)), name


def test_redact_value_run_typing():
    assert sk._redact_value_run("$774.85") == "<MONEY>"
    assert sk._redact_value_run("Johnson, Bob") == "<NAME>"
    assert sk._redact_value_run("36.83 *") == "<NUM> *"
    assert sk._redact_value_run("$19.37 **") == "<MONEY> **"
    assert sk._redact_value_run("1/7/XX to 1/13/XX") == "<DATE> to <DATE>"
    assert sk._redact_value_run("24.00 hours") == "<HRS>"


# --------------------------------------------------------------------------------------
# the egress gate (T25 unified) and the position extension (T21, gated)
# --------------------------------------------------------------------------------------


def test_is_furniture_text():
    assert sk.is_furniture_text("GROSS EARNINGS")
    assert sk.is_furniture_text("Deductions:")
    assert sk.is_furniture_text("Rate/Hour")
    # a name / an unknown real-form caption is NOT furniture -- it cannot leave context-free
    assert not sk.is_furniture_text("Terrence Boyd")
    assert not sk.is_furniture_text("SMITH AND COMPANY, INC.")
    assert not sk.is_furniture_text("AVERAGE HOURS PER WEEK")


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_page_sendable_labels_furniture_excludes_names_position_only_widens():
    import pdfplumber
    from core.extract import read_words, normalize_label

    furn: set = set()
    ext: set = set()
    with pdfplumber.open(str(PIECERATE)) as pdf:
        for pnum, page in enumerate(pdf.pages, 1):
            w = read_words(page, pnum)
            furn |= set(sk.page_sendable_labels(w, position_extension=False))
            ext |= set(sk.page_sendable_labels(w, position_extension=True))

    assert normalize_label("Rate/Hour") in furn        # furniture is sendable
    assert normalize_label("Johnson, Bob") not in furn  # a name is not furniture
    assert furn <= ext                                  # the position arm only widens


# --------------------------------------------------------------------------------------
# the flag gates only whether a skeleton is BUILT
# --------------------------------------------------------------------------------------


@pytest.mark.skipif(not PIECERATE.exists(), reason="confirm corpus not present")
def test_flag_gates_building_only(monkeypatch):
    monkeypatch.delenv("REALDOOR_SKELETON", raising=False)
    assert sk.build_skeleton(PIECERATE) is None          # off by default -> not built
    monkeypatch.setenv("REALDOOR_SKELETON", "1")
    assert sk.build_skeleton(PIECERATE) is not None       # on -> built
    # respect_flag=False always builds (the falsification / these tests)
    monkeypatch.delenv("REALDOOR_SKELETON", raising=False)
    assert sk.build_skeleton(PIECERATE, respect_flag=False) is not None
