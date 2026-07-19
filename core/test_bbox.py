"""Tests for the PDF-points <-> image-pixels conversion.

A flipped y-axis here is the failure mode that stays invisible: boxes still land on the
page, still look like boxes, and are simply on the wrong content. So these tests assert
direction explicitly rather than only checking round-trips, which a double flip would
pass happily.

Runs under pytest, or standalone: `python core/test_bbox.py`
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extract import (  # noqa: E402
    REFERENCE_DATE,
    LineBoxConvention,
    Word,
    assess_staleness,
    parse_value,
)
from core.render import (  # noqa: E402
    PixelRect,
    pdf_bbox_to_pixels,
    pixels_to_pdf_bbox,
)

LETTER_HEIGHT = 792.0
LETTER_WIDTH = 612.0


def test_top_of_page_maps_to_top_of_image() -> None:
    """A box at the very top of the PDF must land at y=0 in the image, not at the bottom."""
    top_box = [0.0, LETTER_HEIGHT - 10.0, 100.0, LETTER_HEIGHT]
    rect = pdf_bbox_to_pixels(top_box, LETTER_HEIGHT, scale=1.0)
    assert rect.top == 0.0, f"top-of-page box rendered at y={rect.top}, expected 0"
    assert rect.height == 10.0


def test_bottom_of_page_maps_to_bottom_of_image() -> None:
    bottom_box = [0.0, 0.0, 100.0, 10.0]
    rect = pdf_bbox_to_pixels(bottom_box, LETTER_HEIGHT, scale=1.0)
    assert rect.top == LETTER_HEIGHT - 10.0
    assert rect.top + rect.height == LETTER_HEIGHT


def test_y_axis_is_inverted() -> None:
    """Higher in PDF space must mean smaller image y. This is the whole risk."""
    lower = pdf_bbox_to_pixels([0, 100, 10, 110], LETTER_HEIGHT, scale=1.0)
    higher = pdf_bbox_to_pixels([0, 600, 10, 610], LETTER_HEIGHT, scale=1.0)
    assert higher.top < lower.top, "y-axis was not inverted: the overlay would be upside down"


def test_x_axis_is_not_inverted() -> None:
    left = pdf_bbox_to_pixels([10, 100, 20, 110], LETTER_HEIGHT, scale=1.0)
    right = pdf_bbox_to_pixels([500, 100, 510, 110], LETTER_HEIGHT, scale=1.0)
    assert left.left < right.left


def test_scale_multiplies_every_component() -> None:
    box = [40.0, 648.0, 94.01, 662.0]
    one = pdf_bbox_to_pixels(box, LETTER_HEIGHT, scale=1.0)
    two = pdf_bbox_to_pixels(box, LETTER_HEIGHT, scale=2.0)
    for a, b in (
        (one.left, two.left),
        (one.top, two.top),
        (one.width, two.width),
        (one.height, two.height),
    ):
        assert abs(b - a * 2.0) < 1e-9


def test_round_trip_is_exact() -> None:
    for box in (
        [40.0, 648.0, 94.01, 662.0],
        [0.0, 0.0, LETTER_WIDTH, LETTER_HEIGHT],
        [330.0, 658.0, 385.14, 672.0],
        [45.0, 138.0, 314.33, 149.0],
    ):
        for scale in (1.0, 1.5, 2.0, 3.0):
            rect = pdf_bbox_to_pixels(box, LETTER_HEIGHT, scale)
            back = pixels_to_pdf_bbox(rect, LETTER_HEIGHT, scale)
            for original, restored in zip(box, back):
                assert abs(original - restored) < 1e-9, f"round trip drifted: {box} -> {back}"


def test_gold_box_lands_where_the_text_is() -> None:
    """The real gold box for HH-001-D01 person_name sits in the upper third of the page."""
    rect = pdf_bbox_to_pixels([40, 648, 94.01, 662], LETTER_HEIGHT, scale=2.0)
    assert rect.top == (792 - 662) * 2.0 == 260.0
    assert rect.left == 80.0
    assert 0 < rect.top < LETTER_HEIGHT * 2.0 / 3.0


def test_denormalised_bbox_is_tolerated() -> None:
    """Reversed corners must not produce a negative-size rect."""
    rect = pdf_bbox_to_pixels([94.01, 662, 40, 648], LETTER_HEIGHT, scale=1.0)
    assert rect.width > 0 and rect.height > 0
    assert rect.left == 40.0


def test_pixel_rect_css_is_pixel_suffixed() -> None:
    css = PixelRect(1.0, 2.0, 3.0, 4.0).as_css()
    assert css == {"left": "1.00px", "top": "2.00px", "width": "3.00px", "height": "4.00px"}


# ---------------------------------------------------------------------------
# The word -> box convention, which must reproduce the pack's gold geometry
# ---------------------------------------------------------------------------


def test_word_box_matches_gold_convention_at_10pt() -> None:
    """HH-001-D01 person_name: gold is [40, 648, 94.01, 662], baseline 650."""
    word = Word("Mara North", 40.0, 90.0, 650.0, 647.93, 657.93, 10.0, False, 1)
    assert word.bbox(LineBoxConvention()) == [40.0, 648.0, 94.0, 662.0]


def test_word_box_matches_gold_convention_at_14pt() -> None:
    """HH-003-D04 monthly_benefit: gold is [40, 498, 94.6, 516], baseline 500.

    This is the case that exposes glyph-box anchoring: the glyph bottom sits at 497.1,
    which would put the box 0.9pt low and cost ~0.10 IoU.
    """
    word = Word("$850.00", 40.0, 90.6, 500.0, 497.1, 511.1, 14.0, False, 1)
    assert word.bbox(LineBoxConvention()) == [40.0, 498.0, 94.6, 516.0]


def test_box_height_is_size_plus_four_at_every_size() -> None:
    """Height must not drift with font size -- that was the original bug."""
    for size in (7.0, 9.0, 10.0, 12.0, 14.0, 18.0):
        word = Word("x", 40.0, 60.0, 500.0, 500.0 - 0.207 * size, 500.0 + size, size, False, 1)
        box = word.bbox(LineBoxConvention())
        assert abs((box[3] - box[1]) - (size + 4.0)) < 1e-9, f"size {size} drifted"


def test_minimum_box_width_for_single_characters() -> None:
    """A one-glyph value ("1") still needs a clickable box: gold uses 24pt."""
    word = Word("1", 360.0, 365.6, 650.0, 647.93, 657.93, 10.0, False, 1)
    box = word.bbox(LineBoxConvention())
    assert abs((box[2] - box[0]) - 24.0) < 0.01


def test_raw_convention_does_not_pad() -> None:
    word = Word("1", 360.0, 365.6, 650.0, 647.93, 657.93, 10.0, False, 1)
    box = word.bbox(LineBoxConvention.raw())
    assert abs((box[2] - box[0]) - 5.6) < 0.01
    assert abs((box[3] - box[1]) - 10.0) < 0.01


# ---------------------------------------------------------------------------
# Staleness, per the frozen 60-day convention (CH-READINESS-001)
# ---------------------------------------------------------------------------


def test_reference_date_is_the_frozen_event_date() -> None:
    assert REFERENCE_DATE.isoformat() == "2026-07-18"


def test_document_exactly_at_the_window_edge_is_current() -> None:
    """Dated 60 days before 2026-07-18 -> still current, with 0 days left."""
    result = assess_staleness("2026-05-19")
    assert result.days_until_stale == 0
    assert result.state == "present"


def test_document_one_day_past_the_window_is_expired() -> None:
    result = assess_staleness("2026-05-18")
    assert result.days_until_stale == -1
    assert result.state == "expired"


def test_known_stale_fixture_is_expired() -> None:
    """HH-005-D04 is dated 2026-04-14, well outside the 60-day window."""
    result = assess_staleness("2026-04-14")
    assert result.state == "expired"
    assert result.days_until_stale == -35


def test_missing_date_is_never_assumed_fresh() -> None:
    result = assess_staleness(None)
    assert result.state == "unreadable"
    assert result.days_until_stale is None
    assert result.document_date is None


def test_month_precision_date_does_not_invent_a_day() -> None:
    """The gig statement carries "2026-06". We refuse to pick a day for it."""
    result = assess_staleness("2026-06")
    assert result.state == "unreadable"
    assert result.days_until_stale is None
    assert result.reason and "day-precise" in result.reason


def test_expiring_soon_requires_an_explicit_opt_in() -> None:
    """No pack rule defines this threshold, so it is off unless a caller supplies one."""
    assert assess_staleness("2026-05-20").state == "present"
    assert assess_staleness("2026-05-20", expiring_soon_days=7).state == "expiring_soon"


# ---------------------------------------------------------------------------
# Value parsing: abstaining beats guessing
# ---------------------------------------------------------------------------


def test_money_and_integer_parsing() -> None:
    assert parse_value("gross_pay", "$2,166.00") == (2166.0, True)
    assert parse_value("hourly_rate", "$28.50") == (28.5, True)
    assert parse_value("household_size", "1") == (1, True)
    assert parse_value("regular_hours", "76") == (76, True)


def test_unparseable_value_raises_rather_than_guessing() -> None:
    for field_name, text in (
        ("gross_pay", "see attached"),
        ("pay_date", "June 27th"),
        ("application_date", "2026-13-45"),
        ("statement_month", "2026-06-01"),
        ("household_size", "two"),
    ):
        try:
            parse_value(field_name, text)
        except Exception as exc:
            assert type(exc).__name__ == "ParseError", f"{field_name}: unexpected {exc!r}"
        else:
            raise AssertionError(f"{field_name}={text!r} should not have produced a value")


def test_unknown_frequency_is_downgraded_not_rejected() -> None:
    value, clean = parse_value("pay_frequency", "fortnightly")
    assert value == "fortnightly" and clean is False
    assert parse_value("pay_frequency", "biweekly") == ("biweekly", True)


# ---------------------------------------------------------------------------
# Integration: the conversion must land on actual ink in an actual rendering.
# Arithmetic tests alone cannot catch a page-size or scale mix-up.
# ---------------------------------------------------------------------------

_PACK = Path(__file__).resolve().parent.parent / "pack" / "synthetic_documents"
_SAMPLE = _PACK / "documents" / "hh-001_d01_application_summary.pdf"


def test_overlay_boxes_land_on_ink() -> None:
    """Every predicted box must cover dark pixels; the un-flipped box must not.

    The second half is what makes this test meaningful: without it, a double y-flip
    would pass silently.
    """
    if not _SAMPLE.exists():
        print("   (skipped: pack not present)")
        return

    import io

    from PIL import Image

    from core.extract import extract_document
    from core.render import PixelRect, overlay_rects, render_page_png

    rendered = render_page_png(_SAMPLE, 1, scale=2.0)
    assert rendered.width_px == 1224 and rendered.height_px == 1584
    image = Image.open(io.BytesIO(rendered.png_bytes)).convert("L")

    def ink_fraction(rect: PixelRect) -> float:
        crop = image.crop(
            (
                int(rect.left),
                int(rect.top),
                int(rect.left + rect.width),
                int(rect.top + rect.height),
            )
        )
        pixels = crop.tobytes()  # mode "L": one byte per pixel
        return sum(1 for p in pixels if p < 128) / max(1, len(pixels))

    view = extract_document(_SAMPLE)
    overlays = overlay_rects(view, page_number=1, scale=2.0)
    assert overlays, "no overlay rects produced"

    page_px_height = rendered.page_height_points * 2.0
    for overlay in overlays:
        rect = overlay["rect"]
        correct = ink_fraction(rect)
        unflipped = ink_fraction(
            PixelRect(rect.left, page_px_height - rect.top - rect.height, rect.width, rect.height)
        )
        assert correct > 0.01, f"{overlay['field']}: box covers no ink ({correct:.4f})"
        assert unflipped < correct, (
            f"{overlay['field']}: un-flipped box has as much ink as the flipped one; "
            "this test cannot detect a y-flip regression on this document"
        )


def _run_standalone() -> int:
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = 0
    for name, func in tests:
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run_standalone())
