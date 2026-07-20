"""Tests for it-013: a form's answer options are not labels, and a glossed caption is not a value.

Two refusals, each resting on something the page prints:

  * **The option band.** Three or more candidates for one field, sitting on one band of
    type, are a menu. A menu offers a choice; it does not state a fact. No run on such a
    band may anchor that field. (`REALDOOR_OPTION_BAND=0` to disable.)
  * **The glossed caption.** A run with a colon *inside* it is a caption and its own gloss
    -- a page describing a slot rather than filling one -- and is never a free-text value.
    (`REALDOOR_GLOSS_COLON=0` to disable.)

Every geometry below is the numbers pdfplumber reports for the published PDF named in the
docstring, so a fixture cannot drift away from the page it claims to represent. Both rules
only ever *withhold*, so each test that shows a value disappearing has a twin with the flag
off showing the wrong value it used to produce.

Runs under pytest, or standalone: `python core/test_option_band.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from core.extract import (  # noqa: E402
    LineBoxConvention,
    MIN_OPTION_CELLS,
    _caption_refusal,
    _on_one_band,
    _option_menu_runs,
    extract_fields_from_page,
    group_lines,
    synonym_mapper,
)
from core.test_extract_reading import word  # noqa: E402

CONVENTION = LineBoxConvention()

#: Words a mapper answers `pay_frequency` for. In production this is the model mapper --
#: asked "what field is `Monthly` the caption for?" it says `pay_frequency`, which is the
#: right answer to the question and the reason the defect exists. Stated here as a table so
#: the test needs no key and no network.
_FREQUENCY_WORDS = {
    "pay frequency", "weekly", "monthly", "hourly", "bi-weekly", "semi-monthly", "yearly",
}


#: The other nomination the model really makes, on `hi_ags`'s key page: asked what field
#: `Employee Name: Your Payroll Name` captions, it answers `person_name`.
_GLOSSED_CAPTIONS = {"employee name: your payroll name": "person_name"}


def option_mapper(document_type: str, label: str) -> str | None:
    """`synonym_mapper`, plus the nominations the model really makes on these pages."""
    if label.strip().rstrip(":").lower() in _FREQUENCY_WORDS:
        return "pay_frequency"
    glossed = _GLOSSED_CAPTIONS.get(label.strip().lower())
    if glossed is not None:
        return glossed
    return synonym_mapper(document_type, label)


def read(words, document_type="pay_stub", mapper=option_mapper):
    found, _ = extract_fields_from_page(
        words, document_type, CONVENTION, fallback_mapper=mapper
    )
    return found


# ======================================================================================
# The band: what separates a menu from a table
# ======================================================================================


class TestOneBandIsMeasuredNotGuessed:
    """`_on_one_band` is the whole discrimination, so it is tested on real numbers."""

    def test_a_staggered_menu_is_one_band(self) -> None:
        """seattle prints its options on two baselines 4.56pt apart in 8.04pt type.

        Half a line: one row to the eye, and `group_lines` cannot see it because 4.56 is
        far outside its 1.5pt line tolerance.
        """
        assert _on_one_band((256.01, 8.04), (260.57, 8.04))

    def test_a_table_s_rows_are_not_one_band(self) -> None:
        """ca_dlse's earnings rows sit 10.68pt apart in 7.68pt type -- more than a line.

        This is the case the rule must NOT catch: a rate column with one rate per row is
        not a menu, and if it read as one the refusal would start eating real tables.
        """
        assert not _on_one_band((596.77, 7.68), (586.09, 7.68))

    def test_the_threshold_is_the_smaller_of_the_two_type_sizes(self) -> None:
        """A big label does not drag distant small print onto its band.

        The gap is measured against the SMALLER type, so a 20pt heading cannot reach 9pt
        down and claim an 8pt line that is a full line of its own type away.
        """
        assert not _on_one_band((500.0, 20.0), (491.0, 8.0))   # 9.0pt gap, 8pt type
        assert _on_one_band((500.0, 20.0), (493.0, 8.0))       # 7.0pt gap, 8pt type


# ======================================================================================
# wa_dshs_14252_employment_verification.pdf -- a caption reading its own first option
# ======================================================================================


class TestACaptionDoesNotReadItsOwnOptions:
    """`Pay frequency:` followed by its answers, on one 10.4pt baseline at y=458.40.

    The options print an empty checkbox each on the baseline below. Nobody has ticked one,
    so the form states no pay frequency -- and truth records `pay_frequency` as absent.
    Before this rule the side-by-side reader took the first option on the line and the
    document reported `pay_frequency = "daily"`.
    """

    def _wa_dshs_band(self):
        return [
            word("Pay", 77.6, 96.0, 458.40, size=10.40),
            word("frequency:", 98.0, 146.1, 458.40, size=10.40),
            word("Daily", 165.6, 188.4, 458.40, size=10.40),
            word("Weekly", 215.2, 249.2, 458.40, size=10.40),
            word("Monthly", 491.2, 527.6, 458.40, size=10.40),
        ]

    def test_the_form_states_no_pay_frequency(self) -> None:
        assert "pay_frequency" not in read(self._wa_dshs_band()), (
            "an unticked option was read as the form's answer"
        )

    def test_with_the_flag_off_the_wrong_value_comes_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The twin. Without this the test above could be passing for any reason at all."""
        monkeypatch.setenv("REALDOOR_OPTION_BAND", "0")
        assert read(self._wa_dshs_band())["pay_frequency"]["value"] == "daily"

    def test_the_band_is_named_as_a_menu(self) -> None:
        lines = group_lines(self._wa_dshs_band())
        menu = _option_menu_runs(lines, "pay_stub", option_mapper)
        assert {field for field, _ in menu} == {"pay_frequency"}
        assert len(menu) == MIN_OPTION_CELLS, (
            "the caption and its two single-word options are the three candidates"
        )


# ======================================================================================
# seattle_housing_employment_verification_blank.pdf -- options read as a header row
# ======================================================================================


class TestAStaggeredMenuIsNotAColumnHeaderRow:
    """`hourly weekly monthly` on y=256.01 with `bi-weekly semi-monthly` on y=260.57.

    Three digit-free captions on one baseline satisfy `MIN_HEADER_ROW_CELLS`, so the page's
    own options read as a row that names columns, and the header-cell reader took the run
    beneath `monthly` -- the word `through` from the year-to-date line below. The form is
    blank; truth lists `pay_frequency` absent.

    **Scope of this class, stated plainly.** It tests that the stagger is seen as one
    menu, and no more. The header-cell read that produced `through` needs more of that
    page than a fixture reproduces honestly: reduced to these six words the flag-off path
    emits nothing, so an end-to-end assertion here would pass for the wrong reason and
    prove nothing. The end-to-end evidence for this document is the falsification sweep
    over the real PDF (loop/falsification/it-013.json), where `pay_frequency = "through"`
    disappears and nothing takes its place.
    """

    def _seattle_band(self):
        return [
            word("hourly", 234.3, 256.1, 256.01, size=8.04),
            word("weekly", 272.2, 296.6, 256.01, size=8.04),
            word("monthly", 453.1, 481.2, 256.01, size=8.04),
            word("bi-weekly", 312.4, 345.7, 260.57, size=8.04),
            word("semi-monthly", 358.1, 405.8, 260.57, size=8.04),
        ]

    def test_the_stagger_does_not_hide_the_menu(self) -> None:
        """Both baselines must land in one band, or only three of the five are refused."""
        lines = group_lines(self._seattle_band())
        menu = _option_menu_runs(lines, "pay_stub", option_mapper)
        assert len(menu) == 5, "the two staggered baselines are one menu, not two"


# ======================================================================================
# The threshold, and what it must not catch
# ======================================================================================


class TestTwoIsNotAMenu:
    """Two same-field candidates on a band is the commonest honest layout on any page.

    `bonita_certificated_check_sample.pdf` prints `GROSS EARN'S` twice across one row at
    x=116.9 and x=260.9 -- one header over each of two column groups. Refusing that would
    cost a real reading, which is why the threshold is three and why it is tested here
    rather than left to the sweep.
    """

    def _twin_headers(self):
        return [
            word("hourly", 116.9, 140.0, 349.92, size=7.5),
            word("weekly", 260.9, 284.0, 349.92, size=7.5),
        ]

    def test_two_candidates_on_a_band_are_not_refused(self) -> None:
        lines = group_lines(self._twin_headers())
        assert _option_menu_runs(lines, "pay_stub", option_mapper) == frozenset()

    def test_the_threshold_is_three(self) -> None:
        assert MIN_OPTION_CELLS == 3


class TestTheRefusalOnlyWithholds:
    """The rule withholds; it never substitutes.

    A menu run stays a label everywhere else it matters -- it still bounds the columns on
    its line, it is still in `label_words`, it still shields whatever sits beneath it from
    the caption rule. The failure this guards against is the rule being implemented in
    `_label_runs` instead: dropping the run entirely would stop it being a label at all,
    and the options would become readable as values, turning a withheld answer into a
    wrong one. The corpus-wide statement of the same property is that all six firings in
    loop/falsification/it-013.json have an empty `emitted_with_rule`.
    """

    def test_the_flag_off_path_is_the_committed_behaviour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With the flag off nothing in this module consults the band at all."""
        monkeypatch.setenv("REALDOOR_OPTION_BAND", "0")
        lines = group_lines([
            word("hourly", 234.3, 256.1, 256.01, size=8.04),
            word("weekly", 272.2, 296.6, 256.01, size=8.04),
            word("monthly", 453.1, 481.2, 256.01, size=8.04),
        ])
        assert _option_menu_runs(lines, "pay_stub", option_mapper) == frozenset()


# ======================================================================================
# hi_ags_pay_statement_example_2021.pdf -- a page explaining itself
# ======================================================================================


class TestAGlossedCaptionIsNotAValue:
    """Page 3 is a key to the statement's own parts, printed as `caption: what goes here`.

    The mapper reads `Employee Name: Your Payroll Name` and answers `person_name`, and the
    extractor took the next line of the key as the value -- reporting the employee's name
    as `Employee Address: Your Payroll Address` while `John Aloha` was printed on the
    sample statement two pages earlier.
    """

    def _key_lines(self):
        return [
            word("Employee Name: Your Payroll Name", 306.8, 453.8, 362.35, size=8.0),
            word("Employee Address: Your Payroll Address", 306.8, 470.8, 349.27, size=8.0),
        ]

    def test_a_run_with_an_inside_colon_is_refused_as_a_free_text_value(self) -> None:
        run = [word("Employee Address: Your Payroll Address", 306.8, 470.8, 349.27)]
        assert _caption_refusal("person_name", run, frozenset()) is not None

    def test_a_terminal_colon_still_gives_its_own_reason(self) -> None:
        """The two colon rules stay distinguishable, so a failure names which one fired."""
        run = [word("Employee Name:", 306.8, 360.0, 349.27)]
        assert "ends in a colon" in (_caption_refusal("person_name", run, frozenset()) or "")

    def test_a_typed_field_is_left_to_its_parser(self) -> None:
        """Scope is `FREE_TEXT_FIELDS`, exactly where the terminal-colon rule's scope is.

        `parse_value` already refuses `Advice Date: The date the funds are available` as
        money, so extending the refusal there would be a rule doing no work.
        """
        run = [word("Advice Date: The date the funds are available", 306.8, 490.3, 381.55)]
        assert _caption_refusal("gross_pay", run, frozenset()) is None

    def test_the_key_page_names_nobody(self) -> None:
        assert read(self._key_lines()).get("person_name", {}).get("value") is None

    def test_with_the_flag_off_the_wrong_name_comes_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REALDOOR_GLOSS_COLON", "0")
        got = read(self._key_lines())
        assert got["person_name"]["value"] == "Employee Address: Your Payroll Address"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
