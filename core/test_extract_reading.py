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
    FREE_TEXT_FIELDS,
    LABEL_MAP,
    LABEL_SYNONYMS,
    LineBoxConvention,
    MIN_HEADER_ROW_CELLS,
    ParseError,
    TYPED_VALUE_X_TOLERANCE,
    VALUE_X_TOLERANCE,
    Word,
    _caption_refusal,
    _column_alignment,
    _header_row_words,
    _split_runs,
    _x_tolerance,
    _label_runs,
    _mapper_stages,
    _TrackingMapper,
    extract_fields_from_page,
    group_lines,
    layered_mapper,
    looks_like_a_label,
    normalize_label,
    parse_value,
    read_words,
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

    def test_a_two_digit_year_is_refused_because_the_century_is_not_printed(self) -> None:
        """il_dol prints `9/2/05`. Reading it as 2005 rests on a pivot (00-68 -> 20xx) the
        page states nowhere -- the masked-year failure in a milder costume -- and the
        repository's own scorer deliberately reads only four-digit years, so the format
        was added once, measured as two wrong values on the confirmation set, and removed.
        See the note above `_DATE_FORMATS`."""
        for text in ("9/2/05", "8/27/05", "12/31/99"):
            with pytest.raises(ParseError):
                parse_value("pay_date", text)

    def test_a_masked_year_is_refused_because_the_year_is_not_printed(self) -> None:
        """The CA DLSE stubs print `1/7/XX`. Emitting an ISO date would mean inventing a
        year, which is the failure this project exists to avoid."""
        for text in ("1/7/XX", "1/13/XX", "1/20/xx"):
            with pytest.raises(ParseError):
                parse_value("pay_period_start", text)


# ======================================================================================
# A printed conjunction can name two fields at once -- see `_period_span_fields`
# ======================================================================================
# il_dol prints `Pay Period:  8/21/2005 to 8/27/05`: one label, one run, two dates joined
# by the page's own printed word "to". The split is licensed by that word plus a double
# parse -- both halves must independently parse as dates -- never by position.


class TestAPrintedConjunctionNamesTwoFields:
    @staticmethod
    def _span_line(right_text: str = "1/5/2020 to 1/11/2020"):
        """`PAY PERIOD` with a single run to its right, in the pack's own label type."""
        words = [
            word("PAY", 100.0, 118.0, 500.0, bold=True),
            word("PERIOD", 120.0, 152.0, 500.0, bold=True),
        ]
        x = 200.0
        for token in right_text.split(" "):
            width = 5.0 * len(token)
            words.append(word(token, x, x + width, 500.0))
            x += width + 3.0
        return words

    def test_both_halves_of_a_printed_span_are_read(self) -> None:
        got = read(self._span_line())
        assert got["pay_period_start"]["value"] == "2020-01-05"
        assert got["pay_period_end"]["value"] == "2020-01-11"
        for name in ("pay_period_start", "pay_period_end"):
            assert got[name]["certainty"] == "low"
            assert "printed word 'to'" in (got[name]["notes"] or "")

    def test_each_half_gets_its_own_box(self) -> None:
        """The overlay must point at the words that produced each value, not at the whole
        run for both."""
        got = read(self._span_line())
        start_box = got["pay_period_start"]["bbox"]
        end_box = got["pay_period_end"]["bbox"]
        assert start_box[2] < end_box[0], "the two boxes overlap; each half owns its glyphs"
        assert got["pay_period_start"]["source_text"] == "1/5/2020"
        assert got["pay_period_end"]["source_text"] == "1/11/2020"

    def test_one_unparsable_half_kills_the_whole_reading(self) -> None:
        """There is no "one good half": a bad half is evidence the run is not a date span."""
        got = read(self._span_line("1/5/2020 to soon"))
        assert got.get("pay_period_start", {}).get("certainty", "abstain") == "abstain"
        assert "pay_period_end" not in got

    def test_masked_years_stay_abstained(self) -> None:
        """The CA DLSE layout, reduced: `1/7/XX to 1/13/XX`. Both halves fail `_parse_date`,
        so the split never happens and no year is invented."""
        got = read(self._span_line("1/7/XX to 1/13/XX"))
        assert got.get("pay_period_start", {}).get("certainty", "abstain") == "abstain"
        assert "pay_period_end" not in got

    def test_the_il_dol_fully_printed_half_is_read_and_the_two_digit_half_is_not(self) -> None:
        """il_dol's span, reduced: `8/21/2005 to 8/27/05`. The left half prints all eight
        of its digits and is read; the right half prints no century, and no century is
        invented for it -- it stays an abstention, exactly as the note above
        `_DATE_FORMATS` promises. The right half being date-*shaped* is what licenses
        reading the left at all: it is the proof the run is a span of two dates."""
        got = read(self._span_line("8/21/2005 to 8/27/05"))
        assert got["pay_period_start"]["value"] == "2005-08-21"
        assert got["pay_period_start"]["certainty"] == "low"
        assert "stays abstained" in (got["pay_period_start"]["notes"] or "")
        assert "pay_period_end" not in got

    def test_a_masked_far_half_licenses_the_printed_near_half(self) -> None:
        """Same one-sided reading with the mask instead of a two-digit year: the masked
        half is date-shaped (the page printed a date and redacted its year), so the fully
        printed half is read and the masked half stays exactly as unread as before."""
        got = read(self._span_line("1/5/2020 to 1/13/XX"))
        assert got["pay_period_start"]["value"] == "2020-01-05"
        assert "pay_period_end" not in got

    def test_a_prose_left_half_kills_the_reading_even_with_a_good_right_half(self) -> None:
        """`prior to 8/27/2005` must not become a period end: the left side is not even
        date-shaped, so nothing printed says the run is a span of two dates."""
        got = read(self._span_line("prior to 8/27/2005"))
        assert got.get("pay_period_start", {}).get("certainty", "abstain") == "abstain"
        assert "pay_period_end" not in got

    def test_two_printed_conjunctions_are_prose_not_a_span(self) -> None:
        got = read(self._span_line("1/5/2020 to 1/11/2020 to 1/12/2020"))
        assert got.get("pay_period_start", {}).get("certainty", "abstain") == "abstain"

    def test_an_existing_period_end_is_never_overwritten(self) -> None:
        """The companion field only ever fills a blank. A `THROUGH` label that already
        resolved its own value outranks the span's right half -- the label sits above the
        span here so it resolves first, and the span must leave it alone."""
        words = [
            word("THROUGH", 100.0, 140.0, 600.0, bold=True),
            word("2020-01-12", 100.0, 145.0, 585.0),
        ] + self._span_line()
        got = read(words)
        assert got["pay_period_end"]["value"] == "2020-01-12"
        assert got["pay_period_start"]["value"] == "2020-01-05"


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


# ======================================================================================
# Cause 4 -- "a label is never a value" only ever protected labels we had a word for
# ======================================================================================
# Every wrong value on the confirmation set (14 published documents, never scored until
# after this code was written) was the same bug: a run that names a field, sitting where a
# value goes, read as a value because our vocabulary did not contain it. See the block above
# `_is_caption_cell` in `core/extract.py`.
#
# The three cases are reproduced below from the real files, and each is also asserted as a
# geometry fixture so the regression survives the PDFs being unavailable.

CONFIRM = Path(__file__).resolve().parent.parent / "testdata" / "confirm_raw"


def _header_words(words):
    return _header_row_words(group_lines(words))


class TestACaptionIsNotAValue:
    def test_a_run_ending_in_a_colon_is_refused_for_a_free_text_field(self) -> None:
        """`seattle_housing_employment_verification_blank.pdf`, reduced to its geometry.

        "Employee Name:" with an empty fill-in, and the next caption on the row read as the
        name. The colon is the document's own punctuation: it introduces something else.
        """
        run = [word("Job", 311.7, 328.0, 299.3), word("Title:", 330.0, 348.1, 299.3)]
        assert _caption_refusal("person_name", run, frozenset()) is not None

    def test_the_colon_test_does_not_reach_a_typed_field(self) -> None:
        """`parse_value` already refuses "Job Title:" as a date or an amount, so extending
        the rule there would be a rule doing no work -- and a rule doing no work is one whose
        cost nobody can measure."""
        run = [word("Job", 311.7, 328.0, 299.3), word("Title:", 330.0, 348.1, 299.3)]
        for field in ("pay_date", "gross_pay", "regular_hours"):
            assert _caption_refusal(field, run, frozenset()) is None

    def test_a_header_row_cell_is_refused_for_a_free_text_field(self) -> None:
        """`osu_sample_earnings_statement.pdf` page 2, at the x-positions pdfplumber reports.

        `Deduction Code | Description | Employee | Employer` -- the canonical label EMPLOYEE
        matched a column heading, so the run to its right is the *next column's heading*.
        It carries no colon; only the page's own table structure says what it is.
        """
        words = [
            word("Deduction", 93.0, 130.0, 178.5), word("Code", 132.0, 151.0, 178.5),
            word("Description", 255.0, 297.0, 178.5),
            word("Employee", 389.0, 425.0, 178.5),
            word("Employer", 510.1, 545.0, 178.5),
        ]
        header = _header_words(words)
        employer = [w for w in words if w.text == "Employer"]
        assert _caption_refusal("person_name", employer, header) is not None
        assert _caption_refusal("gross_pay", employer, header) is None

    def test_two_cells_are_a_label_beside_its_value_not_a_header_row(self) -> None:
        """The count that must NOT qualify, and the reason the threshold is three.

        A caption with its value to the right is the commonest layout on any form. If two
        cells made a header row, every side-by-side name on every pay stub would be refused.
        """
        words = [
            word("Employee", 100.0, 140.0, 500.0),
            word("Mara", 200.0, 224.0, 500.0), word("North", 226.0, 252.0, 500.0),
        ]
        assert len(_split_runs(words)) == 2 < MIN_HEADER_ROW_CELLS
        assert _header_words(words) == frozenset()

    def test_a_row_carrying_a_digit_is_data_not_a_header(self) -> None:
        """A row of values can line up as neatly as the row that names it. What tells them
        apart is that a heading is words: one digit anywhere and the line is data."""
        words = [
            word("Regular", 100.0, 130.0, 500.0),
            word("40.00", 200.0, 224.0, 500.0),
            word("14.9000", 300.0, 336.0, 500.0),
        ]
        assert _header_words(words) == frozenset()

    def test_the_refusal_is_shape_based_and_confined_to_free_text(self) -> None:
        """What the header-row test actually keys on, stated plainly so the trade is visible.

        Three caption-shaped cells across one line qualify, and a two-word name IS caption
        shaped -- so a name printed in such a row would be refused. That is the cost this
        rule can in principle charge. Measured across the pack, the 26 uploads, the wording
        hold-out, the external six and the confirmation 14, it charges it nowhere: all 69
        free-text values read before the change are still read after it. The corpus
        measurement is the evidence; this fixture only pins that the rule reads shape and
        page structure, never a name."""
        words = [
            word("Employee", 100.0, 140.0, 500.0),
            word("Department", 200.0, 250.0, 500.0),
            word("Payroll", 300.0, 330.0, 500.0),
        ]
        header = _header_words(words)
        payroll = [w for w in words if w.text == "Payroll"]
        assert _caption_refusal("person_name", payroll, header) is not None
        # ...and a typed field is untouched by it, because its parser already refuses.
        assert _caption_refusal("net_pay", payroll, header) is None

    def test_no_frequency_word_we_read_is_ever_caption_shaped(self) -> None:
        """`pay_frequency` is free-text and its values are bare words, which is the shape the
        header-row test keys on. They are only ever refused if the page prints them in a row
        of three captions -- never merely for being one word."""
        for text in ("biweekly", "weekly", "monthly", "fortnightly"):
            run = [word(text, 100.0, 130.0, 500.0)]
            assert _caption_refusal("pay_frequency", run, frozenset()) is None

    @pytest.mark.parametrize(
        "file_name",
        [
            "osu_sample_earnings_statement.pdf",
            "seattle_housing_employment_verification_blank.pdf",
            "mnhousing_employment_verification_blank.pdf",
        ],
    )
    def test_the_three_confirmation_set_false_positives_are_gone(self, file_name) -> None:
        """End to end, through the publishers' own bytes. Each of these read a caption as a
        person's name; all three must now abstain. `scripts/measure_confirm_set.py` scores
        the whole set."""
        from core import extract as ex

        path = CONFIRM / file_name
        if not path.exists():
            pytest.skip("confirmation-set PDFs are not in the tree")
        view = ex.extract_document(path, document_type="pay_stub")
        got = {f["field"]: f for f in view["fields"]}
        assert got["person_name"]["certainty"] == "abstain", got["person_name"]


# ======================================================================================
# Cause 5 -- one alignment tolerance for fields with a parser and fields without one
# ======================================================================================


class TestTheToleranceIsScopedToTypedFields:
    def test_typed_fields_get_the_wider_tolerance(self) -> None:
        for field in ("pay_date", "pay_period_start", "gross_pay", "net_pay", "hourly_rate"):
            assert _x_tolerance(field) == TYPED_VALUE_X_TOLERANCE

    def test_free_text_fields_keep_the_tight_one(self) -> None:
        for field in sorted(FREE_TEXT_FIELDS):
            assert _x_tolerance(field) == VALUE_X_TOLERANCE

    def test_an_unnamed_field_gets_the_tight_one(self) -> None:
        """The widening has to be asked for. A caller that has not said which field it is
        resolving must not be widened by default."""
        assert _x_tolerance("") == VALUE_X_TOLERANCE

    def test_the_scoping_is_what_stops_a_measured_false_positive(self) -> None:
        """`orangeusd_sample_paystub.pdf` is the document that made this scoped rather than
        global: at 8.0pt for every field, `person_name` reads the column heading "Employee
        ID" on a page whose name field is genuinely absent. The caption rule above refuses
        it too, so this is defence in depth -- but the scoping is the one that does not
        depend on the run happening to look like a caption."""
        from core import extract as ex

        path = CONFIRM / "orangeusd_sample_paystub.pdf"
        if not path.exists():
            pytest.skip("confirmation-set PDFs are not in the tree")
        view = ex.extract_document(path, document_type="pay_stub")
        got = {f["field"]: f for f in view["fields"]}
        answered = [name for name, f in got.items() if f["certainty"] != "abstain"]
        assert answered == [], f"invented {answered} on a page that carries none of them"


# ======================================================================================
# Two more names for the pay date, each a single-meaning compound
# ======================================================================================


class TestPayDateCompounds:
    def test_the_two_compounds_map_to_pay_date(self) -> None:
        """`PAYDATE` is il_dol's one-word spelling; `ISSUE DATE` is bonita's header-strip
        caption. Each names one thing -- unlike bare "DATE", which could date anything on
        the page and stays out of the tables for that reason."""
        assert synonym_mapper("pay_stub", "Paydate:") == "pay_date"
        assert synonym_mapper("pay_stub", "ISSUE DATE") == "pay_date"

    def test_bare_date_is_still_not_a_label(self) -> None:
        assert synonym_mapper("pay_stub", "DATE") is None

    def test_bonita_reads_its_issue_date(self) -> None:
        """bonita prints `ISSUE DATE` with `9/30/2018` beneath it at the same x, and the
        truth file transcribed 09-30-2018 before this synonym existed."""
        from core import extract as ex

        path = CONFIRM / "bonita_certificated_check_sample.pdf"
        if not path.exists():
            pytest.skip("confirmation-set PDFs are not in the tree")
        view = ex.extract_document(path, document_type="pay_stub")
        got = {f["field"]: f for f in view["fields"]}
        assert got["pay_date"]["value"] == "2018-09-30"
        assert got["pay_date"]["certainty"] == "low"


# ======================================================================================
# The watermark filter may not delete the whole page (it-001, REALDOOR_WATERMARK_SANITY)
# ======================================================================================
# `ca_dlse_paystub_hourly.pdf` is a 1756x1176 pt page whose every char reports
# 27.3-48.6 pt, so the unconditional size filter classified 100% of the text layer as
# watermark and `read_words` returned 0 of 96 words. A watermark is an overlay ON a
# body; a classification that removes everything it was meant to be distinguished from
# refutes itself, and such a page is read unfiltered instead. The fixtures below carry
# the geometry, so the regression survives the confirmation PDFs being unavailable.


class FakePage:
    """The smallest object `read_words` can read.

    Chars are pdfplumber-shaped dicts; one char stands for one word, which is all the
    filter logic under test can distinguish. `filter` narrows the char set the way
    pdfplumber's `FilteredPage` does, and `extract_words` hands each surviving char
    back in the shape `read_words` consumes.
    """

    def __init__(self, chars: list[dict], height: float = 792.0) -> None:
        self.chars = chars
        self.height = height

    def filter(self, keep) -> "FakePage":
        return FakePage([c for c in self.chars if keep(c)], self.height)

    def extract_words(self, extra_attrs=None, use_text_flow=False, return_chars=False):
        return [
            {
                "text": c["text"],
                "x0": c["x0"],
                "x1": c["x1"],
                "top": c["top"],
                "bottom": c["bottom"],
                "size": c["size"],
                "fontname": c["fontname"],
                "chars": [c],
            }
            for c in self.chars
        ]


def glyph(text: str, x0: float, size: float, top: float = 100.0) -> dict:
    return {
        "text": text,
        "x0": x0,
        "x1": x0 + 0.6 * size * len(text),
        "top": top,
        "bottom": top + size,
        "size": size,
        "fontname": "Arial",
        "matrix": [size, 0.0, 0.0, size, x0, 692.0 - top],
    }


class _flag:
    """Set REALDOOR_WATERMARK_SANITY for one test, restoring whatever was there.

    Not a pytest fixture because `_run_standalone` calls test methods with no
    arguments, and this file promises to keep working that way.
    """

    def __init__(self, value: str | None) -> None:
        self.value = value

    def __enter__(self) -> None:
        import os

        self.saved = os.environ.get("REALDOOR_WATERMARK_SANITY")
        if self.value is None:
            os.environ.pop("REALDOOR_WATERMARK_SANITY", None)
        else:
            os.environ["REALDOOR_WATERMARK_SANITY"] = self.value

    def __exit__(self, *exc) -> None:
        import os

        if self.saved is None:
            os.environ.pop("REALDOOR_WATERMARK_SANITY", None)
        else:
            os.environ["REALDOOR_WATERMARK_SANITY"] = self.saved


class TestTheWatermarkFilterMayNotDeleteTheWholePage:
    def _all_large_page(self) -> FakePage:
        """Every char at 29 pt -- the ca_dlse geometry, reduced."""
        return FakePage(
            [glyph("Johnson,", 100.0, 29.0), glyph("Bob", 260.0, 29.0)], height=1176.0
        )

    def test_a_page_the_filter_would_empty_is_read_unfiltered(self) -> None:
        with _flag(None):
            words = read_words(self._all_large_page(), 1)
        assert [w.text for w in words] == ["Johnson,", "Bob"]

    def test_the_flag_off_restores_the_blind_read_exactly(self) -> None:
        with _flag("0"):
            words = read_words(self._all_large_page(), 1)
        assert words == []

    def test_a_real_watermark_over_a_body_is_still_filtered(self) -> None:
        """The pack's contrast -- 8 pt body under a 34 pt banner -- is untouched."""
        page = FakePage(
            [
                glyph("NET", 100.0, 8.0),
                glyph("560.71", 160.0, 8.0),
                glyph("SYNTHETIC", 80.0, 34.0, top=300.0),
            ]
        )
        with _flag(None):
            words = read_words(page, 1)
        assert [w.text for w in words] == ["NET", "560.71"]

    def test_a_scan_with_no_text_layer_still_reads_empty(self) -> None:
        with _flag(None):
            assert read_words(FakePage([]), 1) == []


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
