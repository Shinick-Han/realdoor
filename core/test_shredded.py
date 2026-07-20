# -*- coding: utf-8 -*-
"""What `core/shredded.py` reads, and -- mostly -- what it refuses to read.

The one wrong value this path could manufacture is a mis-grouped magnitude (a
dollars-and-cents grid concatenating to 100x the truth), so the test that matters most
here is `test_the_scale_hazard_is_refused`: every ratio identity closes at the wrong
scale, and only the rate-x-hours anchor says no.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core import extract as ex
from core import shredded as sh

ROOT = Path(__file__).resolve().parent.parent
CONFIRM = ROOT / "testdata" / "confirm_raw"
IL_DOL = CONFIRM / "il_dol_day_labor_wage_notice_sample.pdf"

CONVENTION = ex.LineBoxConvention()


@pytest.fixture()
def flag_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "1")
    monkeypatch.setenv("REALDOOR_COLUMNS", "0")
    yield


@pytest.fixture()
def flag_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REALDOOR_ARITHMETIC", "0")
    monkeypatch.setenv("REALDOOR_COLUMNS", "0")
    yield


def _w(text, x0, x1, baseline, size=5.8, bold=False, page=1):
    return ex.Word(
        text=text, x0=x0, x1=x1, baseline=baseline,
        glyph_bottom=baseline - 0.2 * size, glyph_top=baseline + 0.8 * size,
        size=size, bold=bold, page=page,
    )


def _grid(
    *,
    row1=("10", "8", ("8", "0")),
    row2=("20", "6", ("1", "20")),
    gross=("2", "00"),
    ded=("5", "0"),
    net=("1", "50"),
    with_deductions_row=True,
    net_x0=554.0,
    extra=(),
):
    """An il_dol-shaped grid, reduced. Defaults close every identity:
    10x8 + 20x6 -> 80 + 120 = 200 = 50 + 150."""

    def shredded(parts, baseline, x0=554.0):
        words, x = [], x0
        for part in parts:
            width = 3.0 * len(part)
            words.append(_w(part, x, x + width, baseline))
            x += width + 2.0
        return words

    words = [
        # the header row the page prints about its own columns
        _w("Client:", 172.0, 190.0, 490.0, bold=True),
        _w("Rate", 299.0, 311.0, 490.0, bold=True),
        _w("Hours", 317.0, 334.0, 490.0, bold=True),
        # two earnings rows: an id under Client:, rate and hours under their own cells
        _w("342", 176.0, 186.0, 475.0),
        _w(row1[0], 300.0, 308.0, 475.0),
        _w(row1[1], 324.0, 327.0, 475.0),
        *shredded(row1[2], 475.0),
        _w("541", 176.0, 186.0, 446.0),
        _w(row2[0], 300.0, 308.0, 446.0),
        _w(row2[1], 324.0, 327.0, 446.0),
        *shredded(row2[2], 446.0),
        # the three labelled total rows
        _w("Gross", 198.0, 216.0, 410.0, bold=True),
        _w("Pay:", 218.0, 232.0, 410.0, bold=True),
        *shredded(gross, 410.0),
        _w("Net", 198.0, 210.0, 320.0, bold=True),
        _w("Pay:", 212.0, 226.0, 320.0, bold=True),
        *shredded(net, 320.0, x0=net_x0),
    ]
    if with_deductions_row:
        words += [
            _w("Total", 198.0, 214.0, 336.0, bold=True),
            _w("Deductions:", 216.0, 250.0, 336.0, bold=True),
            *shredded(ded, 336.0),
        ]
    return list(words) + list(extra)


def _recover(words):
    return sh.recover(words, CONVENTION, ("gross_pay", "net_pay"))


# ─────────────────────────────────────────────────────────── what is read


class TestTheClosedChainIsRead:
    def test_the_grid_shape_is_read(self) -> None:
        got = _recover(_grid())
        assert got["gross_pay"]["value"] == 200.0
        assert got["net_pay"]["value"] == 150.0
        for name in ("gross_pay", "net_pay"):
            assert got[name]["certainty"] == "low"
            assert sh.SHREDDED_NOTE in got[name]["notes"]

    def test_the_box_wraps_the_printed_digits(self) -> None:
        """The overlay must point at the digit groups the page printed, spaces and all."""
        got = _recover(_grid())
        assert got["gross_pay"]["source_text"] == "2 00"
        x0, _, x1, _ = got["gross_pay"]["bbox"]
        assert x0 == pytest.approx(554.0, abs=1.0)
        assert x1 >= 561.0

    def test_only_wanted_fields_come_back(self) -> None:
        got = sh.recover(_grid(), CONVENTION, ("net_pay",))
        assert set(got) == {"net_pay"}


# ─────────────────────────────────────────────────────────── the refusals


class TestEveryIdentityIsLoadBearing:
    def test_the_scale_hazard_is_refused(self) -> None:
        """THE test. A dollars-and-cents grid would concatenate every amount 100x too
        big -- and the band and the column sum both still close, because they are ratios.
        The rate-x-hours anchor is the one identity with an absolute magnitude, and it is
        what refuses the whole reading."""
        words = _grid(
            row1=("10", "8", ("80", "00")),
            row2=("20", "6", ("120", "00")),
            gross=("200", "00"),
            ded=("50", "00"),
            net=("150", "00"),
        )
        assert _recover(words) == {}

    def test_a_broken_band_refuses(self) -> None:
        assert _recover(_grid(net=("1", "51"))) == {}

    def test_a_broken_column_sum_refuses(self) -> None:
        assert _recover(_grid(row2=("20", "6", ("1", "30")))) == {}

    def test_a_broken_row_product_refuses(self) -> None:
        assert _recover(_grid(row1=("11", "8", ("8", "0")))) == {}

    def test_a_missing_deductions_row_refuses(self) -> None:
        """No printed TOTAL DEDUCTIONS, no band, no answer -- however well the earnings
        column sums."""
        assert _recover(_grid(with_deductions_row=False)) == {}

    def test_a_misaligned_column_refuses(self) -> None:
        assert _recover(_grid(net_x0=580.0)) == {}

    def test_a_single_earnings_row_refuses(self) -> None:
        """One row summing to itself proves nothing about a column."""
        words = _grid(row2=("20", "6", ("1", "20")))
        words = [w for w in words if w.baseline != 446.0]  # drop the second row entirely
        # gross must now equal the one remaining row for the sum to close at all
        words = [w for w in words if not (w.baseline == 410.0 and w.text in ("2", "00"))]
        words += [_w("8", 554.0, 557.0, 410.0), _w("0", 559.0, 562.0, 410.0)]
        assert _recover(words) == {}

    def test_the_cumulative_bound_refuses(self) -> None:
        """An intact amount under a printed Year to Date column contradicting a joined
        amount kills the reading: a current period is part of its year."""
        extra = [
            _w("Year", 600.0, 613.0, 490.0, bold=True),
            _w("to", 615.0, 621.0, 490.0, bold=True),
            _w("Date", 623.0, 636.0, 490.0, bold=True),
            _w("150.00", 601.0, 623.0, 410.0),  # YTD 150 under a joined gross of 200
        ]
        assert _recover(_grid(extra=extra)) == {}

    def test_a_satisfied_cumulative_bound_still_reads(self) -> None:
        extra = [
            _w("Year", 600.0, 613.0, 490.0, bold=True),
            _w("to", 615.0, 621.0, 490.0, bold=True),
            _w("Date", 623.0, 636.0, 490.0, bold=True),
            _w("5,426.00", 601.0, 629.0, 410.0),
        ]
        got = _recover(_grid(extra=extra))
        assert got["gross_pay"]["value"] == 200.0

    def test_rate_beside_hours_is_never_joined(self) -> None:
        """`10 8` under Rate | Hours is two numbers, not 108. It never enters the column
        the labelled rows share, so no identity is ever asked about it."""
        got = _recover(_grid())
        for field in got.values():
            assert field["source_text"] not in ("10 8", "20 6")


# ─────────────────────────────────────────────────────────── the document itself


class TestIlDolEndToEnd:
    def test_gross_and_net_are_read_with_the_flag_on(self, flag_on) -> None:
        view = ex.extract_document(IL_DOL, document_type="pay_stub")
        got = {f["field"]: f for f in view["fields"]}
        assert got["gross_pay"]["value"] == 440.0
        assert got["gross_pay"]["source_text"] == "4 40"
        assert got["net_pay"]["value"] == 262.0
        assert got["net_pay"]["source_text"] == "2 62"
        for name in ("gross_pay", "net_pay"):
            assert got[name]["certainty"] == "low"
            assert sh.SHREDDED_NOTE in got[name]["notes"]

    def test_everything_abstains_with_the_flag_off(self, flag_off) -> None:
        view = ex.extract_document(IL_DOL, document_type="pay_stub")
        got = {f["field"]: f for f in view["fields"]}
        assert got["gross_pay"]["certainty"] == "abstain"
        assert got["net_pay"]["certainty"] == "abstain"
