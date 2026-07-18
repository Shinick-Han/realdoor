"""Page rasterization and the PDF-points <-> image-pixels bridge.

The whole overlay feature rests on one conversion, and it is exactly the conversion
people get wrong: PDF space has its origin at the **bottom left** with y increasing
upward, while image space has its origin at the **top left** with y increasing downward.
A silent y-flip here would put every highlight box on the wrong side of the page while
still looking plausible, so the conversion is isolated in one pure function, is exactly
invertible, and is covered by `core/test_bbox.py`.

Rendering uses pypdfium2 (already a pdfplumber dependency) so there is no Poppler or
ImageMagick binary to install and no network access.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pypdfium2

#: 1 PDF point = 1/72 inch. Scale 2.0 renders at 144 DPI, which is sharp enough to read
#: a 7pt footnote on screen without producing enormous PNGs.
DEFAULT_SCALE = 2.0


@dataclass(frozen=True)
class PixelRect:
    """A rectangle in image space: top-left origin, y increasing downward."""

    left: float
    top: float
    width: float
    height: float

    def as_css(self) -> dict[str, str]:
        """Ready to splat onto an absolutely-positioned overlay div."""
        return {
            "left": f"{self.left:.2f}px",
            "top": f"{self.top:.2f}px",
            "width": f"{self.width:.2f}px",
            "height": f"{self.height:.2f}px",
        }


@dataclass(frozen=True)
class PageImage:
    """A rendered page plus everything needed to place boxes on it."""

    png_bytes: bytes
    width_px: int
    height_px: int
    scale: float
    page_width_points: float
    page_height_points: float
    page_number: int


def pdf_bbox_to_pixels(
    bbox: Sequence[float],
    page_height_points: float,
    scale: float = DEFAULT_SCALE,
) -> PixelRect:
    """Convert a bottom-left-origin PDF box into a top-left-origin pixel rect.

    `bbox` is `[x0, y0, x1, y1]` in PDF points with y measured **up** from the bottom of
    the page, exactly as the pack gold and `core.extract` emit it.

    The y-flip is the whole point: the *top* edge of the rect comes from `y1`, the box's
    upper edge in PDF space, because a larger PDF y means a smaller image y.
    """
    x0, y0, x1, y1 = (float(v) for v in bbox)
    left, right = min(x0, x1), max(x0, x1)
    bottom, top = min(y0, y1), max(y0, y1)
    return PixelRect(
        left=left * scale,
        top=(page_height_points - top) * scale,
        width=(right - left) * scale,
        height=(top - bottom) * scale,
    )


def pixels_to_pdf_bbox(
    rect: PixelRect,
    page_height_points: float,
    scale: float = DEFAULT_SCALE,
) -> list[float]:
    """Exact inverse of `pdf_bbox_to_pixels`, for click-to-select in the UI."""
    x0 = rect.left / scale
    x1 = (rect.left + rect.width) / scale
    y1 = page_height_points - (rect.top / scale)
    y0 = page_height_points - ((rect.top + rect.height) / scale)
    return [x0, y0, x1, y1]


def render_page_png(
    pdf_path: str | Path,
    page_number: int = 1,
    scale: float = DEFAULT_SCALE,
) -> PageImage:
    """Render one 1-indexed page to PNG bytes at a known, reported scale.

    The returned `scale` is authoritative: callers must use it (not a hardcoded value)
    when converting boxes, so that changing DPI can never desynchronise the overlay.
    """
    path = Path(pdf_path)
    document = pypdfium2.PdfDocument(path)
    try:
        if not 1 <= page_number <= len(document):
            raise ValueError(
                f"page {page_number} out of range for {path.name} ({len(document)} pages)"
            )
        page = document[page_number - 1]
        width_points, height_points = float(page.get_width()), float(page.get_height())
        image = page.render(scale=scale).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return PageImage(
            png_bytes=buffer.getvalue(),
            width_px=image.width,
            height_px=image.height,
            scale=scale,
            page_width_points=width_points,
            page_height_points=height_points,
            page_number=page_number,
        )
    finally:
        document.close()


def render_page_to_file(
    pdf_path: str | Path,
    output_path: str | Path,
    page_number: int = 1,
    scale: float = DEFAULT_SCALE,
) -> PageImage:
    """Render a page and write the PNG to disk. Returns the same metadata."""
    rendered = render_page_png(pdf_path, page_number, scale)
    Path(output_path).write_bytes(rendered.png_bytes)
    return rendered


def overlay_rects(
    document_view: dict,
    page_number: int = 1,
    scale: float = DEFAULT_SCALE,
) -> list[dict]:
    """Pixel rects for every located field on one page of a `DocumentView`.

    Abstained fields have no box and are skipped -- the UI should render those as a
    prompt for a human, not as a highlight.
    """
    page_height = float(document_view["page_size_points"][1])
    rects = []
    for item in document_view.get("fields", []):
        if item.get("bbox") is None or item.get("page") != page_number:
            continue
        rect = pdf_bbox_to_pixels(item["bbox"], page_height, scale)
        rects.append(
            {
                "field": item["field"],
                "certainty": item["certainty"],
                "rect": rect,
                "css": rect.as_css(),
            }
        )
    return rects
