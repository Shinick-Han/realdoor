"""Tests for the three reasons real published documents read as blank.

Measured on six unmodified public PDFs (ADP, UNC PeopleSoft, UTEP, federal LES, NY DOL,
VA), the extractor answered 0 of 44 fields and got 1 wrong. The three causes each have a
test class below, and each test states the geometry it is protecting rather than asserting
a total, so a failure names the mechanism rather than a score.

Runs under pytest, or standalone: `python core/test_extract_reading.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core.extract import (  # noqa: E402
    LABEL_MAP,
    LABEL_SYNONYMS,
    LineBoxConvention,
    ParseError,
    Word,
    _column_alignment,
    _label_runs,
    _mapper_stages,
    _TrackingMapper,
    extract_fields_from_page,
    group_lines,
    layered_mapper,
    looks_like_a_label,
    normalize_label,
    parse_value,
    synonym_mapper,
)

CONVENTION = LineBoxConvention()


def word(
    text: str,
    x0: float,
    x1: float,
    baseline: float,
    size: float = 8.0,
    bold: bool = False,
) -> Word:
    """One word at explicitly stated edges.

    Both edges are given rather than derived from a width model, because both edges are
    what these tests are about. Where a test reproduces a published document the numbers
    are the ones pdfplumber reports for it, so the fixture cannot drift away from the page
    it claims to represent.
    """
    return Word(
        text=text,
        x0=x0,
        x1=x1,
        baseline=baseline,
        glyph_bottom=baseline - 0.2 * size,
        glyph_top=baseline + 0.8 * size,
        size=size,
        bold=bold,
        page=1,
    )


def read(words, document_type="pay_stub", mapper=synonym_mapper):
    found, _ = extract_fields_from_page(words, document_type, CONVENTION, fallback_mapper=mapper)
    return found


# ======================================================================================
# Cause 1 -- both label paths demanded ALL CAPS, so Title Case labels were invisible
# ======================================================================================


class TestTitleCaseLabelsAreRead:
    def test_a_title_case_label_resolves_to_its_field(self) -> None:
        """`Net Pay` is how documents are actually typeset. It used to resolve to nothing."""
        words = [
            word("Net", 100.0, 114.0, 500.0),
            word("Pay", 116.0, 130.0, 500.0),
            word("1,040.23", 100.0, 132.0, 486.0),
        ]
        assert read(words)["net_pay"]["value"] == 1040.23

    def test_the_all_caps_spelling_still_resolves(self) -> None:
        """The pack's own typography must not regress while we widen to Title Case."""
        words = [
            word("NET", 100.0, 114.0, 500.0, bold=True),
            word("PAY", 116.0, 130.0, 500.0, bold=True),
            word("1,040.23", 100.0, 132.0, 486.0),
        ]
        assert read(words)["net_pay"]["value"] == 1040.23

    def test_case_folding_admits_no_string_that_is_not_already_in_a_table(self) -> None:
        """The safety argument for cause 1: comparison changed, the vocabulary did not.

        Case-normalising the comparison can only match strings the frozen tables already
        contain. A phrase in neither table maps to nothing, in any casing.
        """
        for spelling in ("Fondle Ratio", "FONDLE RATIO", "fondle ratio"):
            assert synonym_mapper("pay_stub", spelling) is None

    def test_a_recognised_label_at_any_size_or_weight_is_found(self) -> None:
        """Path 2 exists so the pack's 8pt-bold house style is not a precondition."""
        for size, bold in ((14.0, False), (6.0, True), (11.5, False)):
            words = [
                word("Gross", 100.0, 100.0 + 3.0 * size, 500.0, size=size, bold=bold),
                word("Pay", 103.0 + 3.0 * size, 105.0 + 5.0 * size, 500.0, size=size, bold=bold),
                word("707.75", 100.0, 100.0 + 3.5 * size, 500.0 - size - 4.0, size=size),
            ]
            got = read(words)
            assert got["gross_pay"]["value"] == 707.75, f"size={size} bold={bold}"


class TestOnlyLabelShapedRunsReachAMapper:
    """The deterministic gate that keeps the model leg off a page of prose."""

    def test_every_label_in_both_frozen_tables_passes_the_gate(self) -> None:
        """The gate must never narrow the vocabulary we already ship.

        This is the converse of the safety argument: the pre-filter is allowed to reduce
        what is *asked*, but never to reject something the tables can answer.
        """
        for table in (LABEL_MAP, LABEL_SYNONYMS):
            for mapping in table.values():
                for key in mapping:
                    assert looks_like_a_label(key), f"frozen label rejected by the gate: {key!r}"

    def test_prose_and_bare_numbers_are_not_offered_to_a_mapper(self) -> None:
        for prose in (
            "A total of all earnings (current pay period and any adjustments)",
            "May include regular hours, overtime hours and shift differentials.",
            "The day you receive your net check",
        ):
            assert not looks_like_a_label(prose)
        for value in ("1,627.74", "07/23/2017", "$45,000.00", "", "   "):
            assert not looks_like_a_label(value)

    def test_the_gate_is_consulted_before_the_mapper(self) -> None:
        """A prose run must not cost a network call, which is the whole point."""
        asked: list[str] = []

        def spy(document_type: str, label: str) -> str | None:
            asked.append(label)
            return None

        line = group_lines([
            word(w, 40.0 + 30.0 * i, 62.0 + 30.0 * i, 500.0)
            for i, w in enumerate(
                "Amount earned before deductions and withholdings applied".split()
            )
        ])[0]
        _label_runs(line, "pay_stub", spy)
        assert all(looks_like_a_label(label) for label in asked)


# ======================================================================================
# Cause 2 -- alignment was tested on x0 only, so the longest number won
# ======================================================================================


class TestRightAlignedColumnsAreMeasured:
    """The UNC geometry, to the point.

    Label `NET PAY` ends at x1=602.2. Beneath it sit the current-period figure (1,040.23,
    x0=577.7) and the year-to-date figure (18,396.25, x0=574.2). On x0 the YTD number is
    the closer of the two -- because it is longer -- and it was the one that got read.
    """

    # pdfplumber's own numbers for testdata/external_raw/ext_unc.pdf page 1.
    LABEL_X0, LABEL_X1 = 571.6, 602.2
    CURRENT = (577.7, 602.2, 384.86)   # 1,040.23  -- this pay period
    YTD = (574.2, 602.2, 377.05)       # 18,396.25 -- year to date

    def _unc_geometry(self):
        return [
            word("NET", self.LABEL_X0, 586.0, 393.12, size=7.0, bold=True),
            word("PAY", 587.8, self.LABEL_X1, 393.12, size=7.0, bold=True),
            word("1,040.23", *self.CURRENT, size=7.0),
            word("18,396.25", *self.YTD, size=7.0),
        ]

    def test_the_current_period_figure_wins_not_the_longer_one(self) -> None:
        got = read(self._unc_geometry())["net_pay"]
        assert got["value"] == 1040.23, "the year-to-date figure was read as net pay"

    def test_x0_alone_would_have_picked_the_wrong_one(self) -> None:
        """Guards the premise, so this test class cannot quietly stop testing anything."""
        current = word("1,040.23", *self.CURRENT, size=7.0)
        ytd = word("18,396.25", *self.YTD, size=7.0)
        assert abs(ytd.x0 - self.LABEL_X0) < abs(current.x0 - self.LABEL_X0), (
            "premise gone: x0 no longer favours the year-to-date figure"
        )
        assert abs(ytd.x1 - self.LABEL_X1) == abs(current.x1 - self.LABEL_X1) == 0.0

    def test_a_stack_sharing_a_right_edge_measures_as_right_aligned(self) -> None:
        runs = [
            [word("1,040.23", 577.7, 602.2, 384.86)],
            [word("18,396.25", 574.2, 602.2, 377.05)],
        ]
        assert _column_alignment(runs, label_x0=571.6, label_x1=602.2) == "right"

    def test_a_stack_sharing_a_left_edge_measures_as_left_aligned(self) -> None:
        # Different lengths on purpose: a shared LEFT edge and two different right edges.
        runs = [[word("Mara North", 100.0, 148.0, 486.0)], [word("Jo Vale", 100.0, 133.0, 472.0)]]
        assert _column_alignment(runs, label_x0=100.0, label_x1=140.0) == "left"

    def test_a_single_run_is_never_claimed_to_measure_an_alignment(self) -> None:
        """One value is no evidence. Saying "unknown" is what keeps the pack unchanged."""
        runs = [[word("Mara North", 100.0, 148.0, 486.0)]]
        assert _column_alignment(runs, label_x0=100.0, label_x1=140.0) == "unknown"

    def test_a_shared_right_edge_far_from_the_label_is_not_this_label_s_column(self) -> None:
        """Both halves of the verdict must agree, or it is a coincidence."""
        runs = [
            [word("1,040.23", 275.0, 300.0, 384.86)],
            [word("18,396.25", 271.0, 300.0, 377.05)],
        ]
        assert _column_alignment(runs, label_x0=571.6, label_x1=602.2) == "unknown"

    def test_a_left_aligned_value_under_a_left_aligned_label_still_reads(self) -> None:
        """The pack's own layout, which must survive every word of this change."""
        words = [
            word("NET", 100.0, 114.0, 500.0, bold=True),
            word("PAY", 116.0, 130.0, 500.0, bold=True),
            word("532.76", 100.0, 128.0, 486.0),
        ]
        assert read(words)["net_pay"]["value"] == 532.76


# ======================================================================================
# Cause 3 -- certainty counted survivors, not candidates
# ======================================================================================


class TestCertaintyCountsCandidatesBeforeFiltering:
    def test_a_value_that_beat_a_rival_is_not_reported_as_high(self) -> None:
        """The original sin: the wrong number was returned with certainty "high".

        Two figures sat under the label. The alignment filter removed one, leaving a single
        survivor, and the survivor was called unambiguous -- the competition had been
        deleted before it was counted.
        """
        words = [
            word("NET", 571.6, 586.0, 393.12, size=7.0, bold=True),
            word("PAY", 587.8, 602.2, 393.12, size=7.0, bold=True),
            word("1,040.23", 577.7, 602.2, 384.86, size=7.0),
            word("18,396.25", 574.2, 602.2, 377.05, size=7.0),
        ]
        got = read(words)["net_pay"]
        assert got["certainty"] != "high"
        assert "candidate value runs" in (got["notes"] or "")

    def test_an_uncontested_value_is_still_allowed_to_be_high(self) -> None:
        """Honesty must not collapse into never being sure of anything."""
        words = [
            word("NET", 100.0, 114.0, 500.0, bold=True),
            word("PAY", 116.0, 130.0, 500.0, bold=True),
            word("532.76", 100.0, 128.0, 486.0),
        ]
        assert read(words, mapper=None)["net_pay"]["certainty"] == "high"

    def test_the_note_says_how_many_rivals_there_were(self) -> None:
        words = [
            word("NET", 571.6, 586.0, 393.12, size=7.0, bold=True),
            word("PAY", 587.8, 602.2, 393.12, size=7.0, bold=True),
            word("1,040.23", 577.7, 602.2, 384.86, size=7.0),
            word("18,396.25", 574.2, 602.2, 377.05, size=7.0),
        ]
        assert "2 candidate value runs" in read(words)["net_pay"]["notes"]


# ======================================================================================
# Free-text fields have a type too -- the traps the six documents set
# ======================================================================================


class TestFreeTextFieldsRejectWhatCannotBeTheirValue:
    def test_a_name_field_refuses_an_address(self) -> None:
        """UNC: the `Employee Name` box is redacted and holds a street address."""
        with pytest.raises(ParseError):
            parse_value("person_name", "123 Franklin St")

    def test_a_name_field_refuses_a_sentence(self) -> None:
        with pytest.raises(ParseError):
            parse_value("person_name", "May include name, address, employee ID and job title")

    def test_a_real_name_still_parses(self) -> None:
        assert parse_value("person_name", "Mara North") == ("Mara North", True)
        assert parse_value("person_name", "STALLONE, SYLVESTER")[0] == "STALLONE, SYLVESTER"

    def test_a_frequency_field_refuses_a_glossary_definition(self) -> None:
        """The federal LES glossary pairs our vocabulary with English prose."""
        with pytest.raises(ParseError):
            parse_value(
                "pay_frequency",
                "A total of all earnings (current pay period and any adjustments)",
            )

    def test_a_real_frequency_still_parses(self) -> None:
        assert parse_value("pay_frequency", "biweekly") == ("biweekly", True)

    def test_an_address_may_contain_digits_because_addresses_do(self) -> None:
        value, clean = parse_value("address", "14 Lantern Way, Boston, MA 02118")
        assert clean and value == "14 Lantern Way, Boston, MA 02118"

    def test_the_redacted_name_box_abstains_rather_than_answering(self) -> None:
        """End to end: the trap must produce no value at all, not a wrong one."""
        words = [
            word("Employee", 27.0, 56.6, 704.68, size=7.0, bold=True),
            word("Name", 58.4, 75.8, 704.68, size=7.0, bold=True),
            word("123 Franklin St", 27.0, 70.6, 696.92, size=7.0),
            word("CHAPEL HILL, NC 27517", 27.0, 106.2, 689.11, size=7.0),
        ]
        got = read(words).get("person_name")
        assert got is None or got["certainty"] == "abstain"


class TestDatesAsTheyArePrinted:
    def test_iso_is_unambiguous(self) -> None:
        assert parse_value("pay_date", "2026-07-03") == ("2026-07-03", True)

    def test_a_us_slash_date_is_read_but_marked(self) -> None:
        """Month-first is a convention, not a fact about the page, so it is not "clean"."""
        value, clean = parse_value("pay_date", "04/10/2015")
        assert value == "2015-04-10"
        assert clean is False, "a convention-dependent reading must not report certainty high"

    def test_dash_and_single_digit_forms_are_read(self) -> None:
        assert parse_value("pay_date", "09-30-2014")[0] == "2014-09-30"
        assert parse_value("pay_period_start", "7/22/2010")[0] == "2010-07-22"

    def test_prose_is_still_not_a_date(self) -> None:
        for text in ("The day you receive your net check", "/ /", "Pay Date:"):
            with pytest.raises(ParseError):
                parse_value("pay_date", text)


class TestALabelIsNeverAValue:
    def test_the_next_row_s_label_is_not_read_as_this_row_s_value(self) -> None:
        """ADP stacks `Period Beginning:` / `Period Ending:` / `Pay Date:` in one column,
        with each value in the column to the right. Reading the label below as the value
        located a value, failed to parse it, and abstained -- and because an abstention
        stands, the real value to the right was never looked for."""
        words = [
            word("Period", 357.8, 384.0, 744.07, size=10.0),
            word("Beginning:", 386.5, 430.9, 744.07, size=10.0),
            word("03/30/2015", 443.1, 488.6, 744.07, size=10.0),
            word("Period", 357.8, 384.0, 732.07, size=10.0),
            word("Ending:", 386.5, 418.1, 732.07, size=10.0),
            word("04/05/2015", 443.1, 488.6, 732.07, size=10.0),
        ]
        got = read(words)
        assert got["pay_period_start"]["value"] == "2015-03-30"
        assert got["pay_period_end"]["value"] == "2015-04-05"


class TestFrozenTablesOutrankTheModel:
    def test_the_model_runs_as_its_own_pass_after_the_tables(self) -> None:
        """Precedence, not just cost. Inside one pass the model could take a field near the
        top of the page that a synonym would have named correctly further down."""
        stages = _mapper_stages(layered_mapper)
        assert stages[0] is synonym_mapper
        assert stages[-1] is not synonym_mapper

    def test_a_tracking_mapper_exposes_a_stable_model_leg(self) -> None:
        """`stage is tracker.model_leg` decides which fields are credited to the model. A
        freshly bound method every time would make that identity test silently never fire."""
        tracker = _TrackingMapper("pay_stub")
        assert tracker.model_leg is tracker.model_leg
        assert _mapper_stages(tracker)[-1] is tracker.model_leg


class TestNormalisation:
    def test_a_trailing_colon_and_case_are_folded(self) -> None:
        assert normalize_label("Pay Date:") == "PAY DATE"
        assert normalize_label("  net   pay  ") == "NET PAY"


def _run_standalone() -> int:
    import traceback

    failures = 0
    for container in list(globals().values()):
        if not isinstance(container, type) or not container.__name__.startswith("Test"):
            continue
        instance = container()
        for name in dir(container):
            if not name.startswith("test_"):
                continue
            try:
                getattr(instance, name)()
            except Exception:  # noqa: BLE001
                failures += 1
                print(f"FAIL {container.__name__}.{name}")
                traceback.print_exc()
    print("standalone: FAILURES" if failures else "standalone: all class tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
