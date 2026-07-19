"""The word-space recovery path, and the one property that makes it safe to have at all.

RapidOCR reads these scans' characters correctly but sometimes runs the words together
("77 Meadow Signal Ave" -> "77MeadowSignalAve"). `recover_word_spaces` re-reads that single
line from the page bitmap at full resolution to get the spaces back.

Re-reading is a second, independent look at the pixels, so it can come back with a
DIFFERENT character ("or account" -> "0r account" was observed). The invariant below is what
makes that harmless: a recovery is accepted only if it has the same characters as the first
read. The path can therefore move spaces and nothing else.

These tests assert that property directly and drive it with deliberately hostile stand-in
readings, rather than only checking that the two pack documents happen to come out right.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr import ocr_extract  # noqa: E402
from ocr.ocr_extract import (  # noqa: E402
    Detection,
    PageImage,
    extract_fields_from_detections,
    recover_word_spaces,
    strip_spaces,
)

DOCUMENTS = Path(__file__).resolve().parent.parent / "pack" / "synthetic_documents" / "documents"

#: Both pack scans whose address the page-level read runs together.
DESPACED_ADDRESS_DOCS = [
    ("hh-002_d01_application_summary.pdf", "application_summary"),
    ("hh-005_d01_application_summary.pdf", "application_summary"),
]


def _detection(text: str) -> Detection:
    return Detection(text=text, confidence=0.98, x0=40.0, x1=200.0, y0=600.0, y1=614.0, page=1)


def _fake_page() -> PageImage:
    """A page object the stubbed `_recognize_line` never actually looks at."""
    return PageImage(image=None, scale=3.0, height_points=792.0)


# --------------------------------------------------------------------------------------
# The invariant, driven with hostile stand-in readings
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "original, reread, why",
    [
        ("81PaperMillRoad", "81 Paper Mil Road", "a dropped letter"),
        ("noorcaccount", "no 0r account", "a letter swapped for a digit"),
        ("77MeadowSignalAve", "77 MeadowS Signal Ave", "a duplicated letter"),
        ("5JuniperCourt", "5 Juniper Courts", "an added letter"),
        ("9AtlasRow", "9 Atlas Row!", "added punctuation"),
        ("MaraNorth", "Mara Nortk", "a substituted letter"),
    ],
)
def test_a_reread_that_changes_any_character_is_thrown_away(monkeypatch, original, reread, why):
    """Character drift in the second read must be rejected, not adopted.

    Each of these would be a plausible-looking wrong value if we trusted the re-read. The
    invariant is the only thing standing between us and emitting it, so it is tested with
    the drift the engine was actually measured to produce.
    """
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: reread)
    assert recover_word_spaces(_fake_page(), _detection(original)) is None, why


def test_a_reread_that_only_moves_spaces_is_accepted(monkeypatch):
    monkeypatch.setattr(
        ocr_extract, "_recognize_line", lambda page, det, pad: "81 Paper Mill Road, Cambridge"
    )
    out = recover_word_spaces(_fake_page(), _detection("81PaperMillRoad,Cambridge"))
    assert out == "81 Paper Mill Road, Cambridge"
    assert strip_spaces(out) == strip_spaces("81PaperMillRoad,Cambridge")


def test_crops_that_disagree_about_spacing_recover_nothing(monkeypatch):
    """Every rung is character-clean here, but they place the spaces differently.

    Disagreement means we do not know where the spaces go, so the honest answer is None --
    not whichever rung happened to be tried first.
    """
    readings = iter(["12 Mill Road", "12 Millroad", "12Mill Road"])
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: next(readings))
    assert recover_word_spaces(_fake_page(), _detection("12MillRoad")) is None


def test_a_single_agreeing_crop_is_not_enough(monkeypatch):
    """One clean rung out of three is a lucky sample, not a stable reading."""
    readings = iter(["12 Mill Road", "12 Mill Roadx", "12 Mill Roadx"])
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: next(readings))
    assert recover_word_spaces(_fake_page(), _detection("12MillRoad")) is None


def test_a_reread_identical_to_the_first_read_recovers_nothing(monkeypatch):
    """Nothing was recovered, so the caller must not be told a repair happened."""
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: "12MillRoad")
    assert recover_word_spaces(_fake_page(), _detection("12MillRoad")) is None


def test_a_crop_the_engine_returns_nothing_for_is_survivable(monkeypatch):
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: None)
    assert recover_word_spaces(_fake_page(), _detection("12MillRoad")) is None


# --------------------------------------------------------------------------------------
# When recovery fails we abstain -- but we still hand the reviewer the characters
# --------------------------------------------------------------------------------------

def test_failed_recovery_abstains_with_a_null_value_but_keeps_the_characters(monkeypatch):
    """CONTRACTS section 2: an abstention's `value` is null. `source_text` is not.

    We know every character here and only failed to place the spaces. Abstaining is right --
    we cannot claim the exact string -- but blanking `source_text` too would throw away
    something we genuinely hold and make the reviewer re-read the page for themselves.
    """
    monkeypatch.setattr(ocr_extract, "_recognize_line", lambda page, det, pad: None)
    raw = "77MeadowSignalAve,Quincy,MA02169"
    label = Detection("MAILING ADDRESS", 0.99, 40.0, 90.0, 620.0, 634.0, 1)
    value = Detection(raw, 0.98, 40.0, 260.0, 604.0, 618.0, 1)

    found = extract_fields_from_detections([label, value], "application_summary", page=_fake_page())

    assert found["address"]["certainty"] == "abstain"
    assert found["address"]["value"] is None
    assert found["address"]["source_text"] == raw
    assert raw in found["address"]["notes"]


# --------------------------------------------------------------------------------------
# End to end on the real scans
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("file_name, doc_type", DESPACED_ADDRESS_DOCS)
def test_the_real_scans_recover_spaces_without_changing_a_character(file_name, doc_type):
    """The property, held against real pixels rather than a stand-in.

    Deliberately asserts the INVARIANT and that spaces appeared -- not a hardcoded address.
    The exact strings are scored against the pack gold by `eval/score_extraction.py`; if this
    test also pinned them it would just be reciting its own answer.
    """
    pdf = DOCUMENTS / file_name
    page = ocr_extract.load_page_image(pdf, 1)
    detections = ocr_extract.read_detections(pdf, 1, page=page)
    found = extract_fields_from_detections(detections, doc_type, page=page)
    address = found["address"]

    assert address["certainty"] != "abstain", "the address should now be read, not abstained"
    assert " " in str(address["value"]), "word spaces should have been recovered"
    assert strip_spaces(str(address["value"])) == strip_spaces(str(address["source_text"])), (
        "recovery may move spaces and nothing else"
    )
    assert "spacing" in (address["notes"] or ""), "the reviewer must be told spacing was inferred"


def test_recovery_is_reachable_only_from_a_value_that_lost_its_spaces(monkeypatch):
    """A cleanly-read value must never be sent for a second opinion.

    This is what keeps the retry from disturbing the fields that already work: if it cannot
    be reached, it cannot regress them.
    """
    calls = []
    monkeypatch.setattr(
        ocr_extract, "_recognize_line", lambda page, det, pad: calls.append(det.text)
    )
    label = Detection("MAILING ADDRESS", 0.99, 40.0, 90.0, 620.0, 634.0, 1)
    value = Detection("12 Mill Road, Quincy, MA 02169", 0.99, 40.0, 260.0, 604.0, 618.0, 1)

    extract_fields_from_detections([label, value], "application_summary", page=_fake_page())
    assert calls == []
