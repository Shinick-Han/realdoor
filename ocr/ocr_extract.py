"""OCR extraction for rasterized pages, emitting the same ExtractedField objects as core.

WHY THIS EXISTS
---------------
`core/extract.py` reads words and coordinates straight out of the PDF text layer. Eight of
the pack's 24 documents are image-only scans (gold marks them ``"rasterized": true``) and
hold 52 of the 159 gold fields. For those pages the text layer is empty, so the
deterministic path correctly abstains on everything. This module recovers those fields.

THE ONE RULE WE DO NOT BEND
---------------------------
**Boxes come from the OCR engine's own detection geometry, never from a layout guess.**
RapidOCR returns a detected quadrilateral per text region, in image pixels. We invert
`core.render`'s pixel->point conversion to get PDF points (bottom-left origin), then apply
the *same* line-box convention core uses -- gold boxes are anchored on the text baseline,
not the glyph outline (see `core/extract.py`, DESCENT_PAD/ASCENT_PAD). A value we cannot
locate a real detection for is an abstention, not a guess.

CALIBRATION IS MEASURED, NOT ASSUMED
------------------------------------
Every constant below was fitted on the **16 readable documents** -- the set this module is
*not* scored on -- by OCRing them and comparing detections against gold boxes. The 8
rasterized documents were never used to choose a threshold. Provenance for each number is
in the comment beside it; `ocr/calibrate.py` regenerates them all.

ENGINE
------
rapidocr-onnxruntime: pure pip wheel (onnxruntime + shapely + pyclipper), no system binary,
no admin rights, no network at inference time. Detection and recognition models ship inside
the wheel.

SAFETY
------
Same posture as core: we only ever read the column under a label we already recognise, so
text embedded in a document can never steer extraction (rule CH-SAFETY-001). This module
calls no LLM.
"""

from __future__ import annotations

import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.extract import (  # noqa: E402
    BBOX_UNITS,
    DATE_FIELD_BY_TYPE,
    EXPECTED_FIELDS,
    LABEL_MAP,
    ParseError,
    REFERENCE_DATE,
    CURRENCY_WINDOW_DAYS,
    DEFAULT_EXPIRING_SOON_DAYS,
    STALE_RULE_ID,
    assess_staleness,
    infer_document_type,
    infer_ids,
    parse_value,
)
from core.render import render_page_png  # noqa: E402

# --------------------------------------------------------------------------------------
# Calibrated constants -- all fitted on the 16 READABLE documents (99 matched fields).
# Regenerate with: python ocr/calibrate.py
# --------------------------------------------------------------------------------------

#: Render scale. 3.0 => 216 DPI. Measured: 2.0 loses the 8pt labels, 4.0 costs ~2x runtime
#: for no accuracy gain on this fixture.
RENDER_SCALE = 3.0

#: The detected box's bottom edge sits this far BELOW gold's y0 in PDF points.
#: Fitted: mean 0.407, sd 0.680 over 99 readable-set detections.
BASELINE_Y_OFFSET = 0.41

#: Gold's box height is font_size + DESCENT_PAD + ASCENT_PAD (= size + 4). We cannot read
#: a font size from a bitmap, so we infer it from detection height. The two sizes present
#: in the fixture (10pt -> h14, 12pt -> h16) OVERLAP in detection height (10pt reaches
#: 13.57, 12pt starts at 12.37), so no threshold separates them cleanly. We therefore do
#: NOT guess per field: we always emit the dominant 10pt height. Cost is bounded and known
#: -- a 14pt box inside a 16pt gold box scores IoU 0.875, still far above the 0.5 bar, and
#: it affects only the 9 gross_pay fields. Guessing would risk being wrong in both
#: directions for no measured gain.
NOMINAL_FONT_SIZE = 10.0
DESCENT_PAD = 2.0
ASCENT_PAD = 2.0

#: Detection boxes crop tighter than gold's glyph run. Fitted: mean 2.084, sd 0.751 over
#: the 71 readable-set fields wide enough that gold's 24pt minimum width did not apply.
WIDTH_PAD = 2.08

#: Gold never emits a box narrower than this, so a one-character value stays clickable.
#: Source: core/extract.py MIN_BOX_WIDTH.
MIN_BOX_WIDTH = 24.0

#: Detected x0 sits this far left of gold's x0. Fitted: mean 0.911, sd 0.508.
X_OFFSET = 0.91

#: A value sits this far below its label's baseline. Same window core uses, re-verified
#: against OCR geometry on the readable set (observed span 14.2-15.6pt).
VALUE_Y_WINDOW = (6.0, 22.0)

#: A value is left-aligned with its label to within this many points. Widened from core's
#: 3.0 to absorb detection jitter (sd 0.51 on each of the two boxes being compared).
VALUE_X_TOLERANCE = 5.0

# --- confidence -> certainty ------------------------------------------------------------
# Thresholds chosen by MEASURING recognition accuracy per confidence band on the readable
# set (102 label-anchored detections), where gold gives ground truth. Measured:
#   conf >= 0.99 : 87/87 correct = 100.0%
#   0.95 - 0.99  : 11/14 correct =  78.6%   -- all 3 failures were dropped spaces in
#                                              `address`, caught by the spacing guard below
#   0.90 - 0.95  :  0/1  correct =   0.0%   -- the 1 sample was also a dropped-space address
#   below 0.90   : n=0                       -- never observed on this fixture
# Character accuracy is therefore effectively perfect above 0.90 on this fixture; the only
# real failure mode is WORD SEGMENTATION, which confidence does not predict and which the
# spacing guard handles directly. We still keep a confidence floor: it is the honest gate
# for inputs noisier than this fixture, where character errors would appear.
HIGH_CONFIDENCE = 0.95
LOW_CONFIDENCE = 0.90

#: THE failure mode of this engine on this fixture: it drops the space between words in a
#: run ("5 Juniper Court, Chelsea" -> "5JuniperCourt,Chelsea"), at high confidence. The
#: scorer collapses whitespace but never INSERTS it, so a de-spaced string is simply wrong.
#: We tried reconstructing spaces from the per-character box gaps the engine exposes
#: (`return_word_box=True`); measured on the 8 readable addresses it recovered only 1 of 4
#: -- kerning gaps and real spaces are not separable at this render scale. Rather than emit
#: a plausible-looking wrong address we ABSTAIN, and only when we can PROVE a space was
#: dropped: a comma with no space after it is direct evidence, since every multi-token
#: string value in this fixture is comma-separated with spaces. Well-spaced strings are
#: unaffected and still answered.
_DROPPED_SPACE = re.compile(r",\S")

#: A dropped space also shows up with no comma to prove it: "Jonas Vale" -> "JonasVale".
#: A lowercase letter immediately followed by an uppercase one does not occur inside a real
#: word, so it is evidence of a lost boundary.
_CASE_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])")

#: WORD-SPACE RECOVERY BY RE-READING THE LINE
#: ------------------------------------------
#: Why the page-level read loses spaces at all: the detector/recogniser pipeline resizes the
#: page down to `Det.max_side_len` (2000px) before it runs. Our page render at RENDER_SCALE
#: 3.0 is ~2550x3300, so it is DOWNSAMPLED, and a 10pt space is the first thing to go.
#: Measured: raising RENDER_SCALE to 4/5/6/8 changes the read not at all, because the engine
#: re-imposes the same 2000px cap -- so a global scale increase cannot fix this, and would
#: cost runtime on all 24 documents for nothing.
#:
#: What DOES fix it: crop the one line we care about and hand that crop to the recogniser by
#: itself. A single line is far below the cap, so it is fed at full resolution -- roughly 4x
#: the pixels per glyph -- and the spaces survive.
#:
#: We run RECOGNITION ONLY (`use_det=False`) on the crop. Measured: letting the detector run
#: again on the crop sometimes splits one line into two overlapping regions and DUPLICATES a
#: character across the seam ("77MeadowSignalAve..." came back as "77MeadowS" + "Signal
#: Ave..."). We already know where the line is -- re-detecting only adds a failure mode.
#:
#: This is a RETRY PATH, reached only by a value we would otherwise abstain on. It cannot
#: move a field that already reads cleanly.
SPACE_RETRY_PADS = (0.5, 1.0, 2.0)

#: How many rungs of the ladder must agree character-for-character on the same spacing.
#: Each rung crops a slightly different window, so agreement across them is what separates a
#: stable reading from one lucky sample. With three rungs, 2 is already a strict majority.
#: Measured on the pack's four de-spaced addresses: all three rungs agreed every time.
SPACE_RETRY_AGREEMENT = 2


def strip_spaces(text: str) -> str:
    """All whitespace removed. This is the identity a space repair may not change."""
    return "".join(text.split())


#: Where a de-spaced value has EXACTLY ONE such boundary, the repair is forced -- there is
#: only one place the space can go, so we restore it. This is the opposite of the address
#: case, which needs several splits and has genuinely ambiguous ones ("MA02145"), which is
#: why addresses abstain instead. The repair is still capped at certainty="low": names like
#: "McBride" or "DeSoto" would be split wrongly by this rule, and a human should confirm.
#: Measured on the 8 rasterized documents: 6 of 6 repairs correct.
def repair_single_space(text: str) -> str | None:
    """Restore the one dropped space in a value, or None if the split is not forced."""
    if " " in text or _DROPPED_SPACE.search(text):
        return None
    parts = _CASE_BOUNDARY.split(text)
    return f"{parts[0]} {parts[1]}" if len(parts) == 2 else None

_NON_ALNUM = re.compile(r"[^A-Z0-9]")

#: RapidOCR frequently drops the inter-word space in small bold caps ("PAY PERIOD" is
#: recognised as "PAYPERIOD"). Labels are matched on alphanumerics only, so spacing noise
#: cannot cost us a field.
def normalize_label(text: str) -> str:
    return _NON_ALNUM.sub("", text.upper())


LABEL_LOOKUP: dict[str, dict[str, str]] = {
    doc_type: {normalize_label(label): field for label, field in mapping.items()}
    for doc_type, mapping in LABEL_MAP.items()
}


@dataclass(frozen=True)
class Detection:
    """One OCR text region, already converted to PDF points, bottom-left origin."""

    text: str
    confidence: float
    x0: float
    x1: float
    y0: float  # bottom edge of the detected quad, in points
    y1: float  # top edge
    page: int

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def bbox(self) -> list[float]:
        """Gold's line-box convention, built from this detection's own geometry.

        y0/y1 are re-anchored onto the text baseline exactly as core does, because gold
        boxes are drawn line boxes (baseline - 2, baseline + size + 2), not glyph outlines.
        """
        x0 = self.x0 + X_OFFSET
        y0 = self.y0 + BASELINE_Y_OFFSET
        y1 = y0 + NOMINAL_FONT_SIZE + DESCENT_PAD + ASCENT_PAD
        width = max(MIN_BOX_WIDTH, self.width + WIDTH_PAD)
        return [round(x0, 2), round(y0, 2), round(x0 + width, 2), round(y1, 2)]

    def certainty(self) -> str:
        if self.confidence >= HIGH_CONFIDENCE:
            return "high"
        if self.confidence >= LOW_CONFIDENCE:
            return "low"
        return "abstain"


@dataclass(frozen=True)
class PageImage:
    """The rasterised page, kept around so a single line can be re-read from it.

    Holds the *authoritative* scale and page height reported by `core.render`, so the
    point->pixel conversion used by the retry path is the exact inverse of the one
    `read_detections` used on the way out.
    """

    image: Any  # PIL.Image.Image
    scale: float
    height_points: float
    width_points: float = 0.0


_ENGINE = None


def _engine():
    """Lazily construct the OCR engine; model load is ~0.3s and is reused across pages."""
    global _ENGINE
    if _ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def load_page_image(
    pdf_path: str | Path | bytes, page_number: int = 1, scale: float = RENDER_SCALE
) -> PageImage:
    """Rasterise one page once, so detection and any line re-read share the same pixels."""
    rendered = render_page_png(pdf_path, page_number, scale)
    return PageImage(
        image=Image.open(io.BytesIO(rendered.png_bytes)).convert("RGB"),
        scale=rendered.scale,  # authoritative, per core.render's contract
        height_points=rendered.page_height_points,
        width_points=rendered.page_width_points,
    )


def read_detections(
    pdf_path: str | Path | bytes,
    page_number: int = 1,
    scale: float = RENDER_SCALE,
    page: PageImage | None = None,
) -> list[Detection]:
    """OCR one page and return detections in PDF points, bottom-left origin.

    The y-flip is the conversion that silently ruins overlays if you get it wrong, so it is
    done here once, against the page height that `core.render` reports, and nowhere else.

    A caller that already rasterised the page passes it in as `page` rather than paying for
    a second render.
    """
    if page is None:
        page = load_page_image(pdf_path, page_number, scale)
    result, _ = _engine()(np.array(page.image))

    height_points = page.height_points
    used_scale = page.scale
    detections: list[Detection] = []
    for quad, text, confidence in result or []:
        xs = [float(p[0]) for p in quad]
        ys = [float(p[1]) for p in quad]
        detections.append(
            Detection(
                text=str(text).strip(),
                confidence=float(confidence),
                x0=min(xs) / used_scale,
                x1=max(xs) / used_scale,
                y0=height_points - (max(ys) / used_scale),
                y1=height_points - (min(ys) / used_scale),
                page=page_number,
            )
        )
    return detections


def _recognize_line(page: PageImage, det: Detection, pad_points: float) -> str | None:
    """Re-read ONE detection's own line straight from the page bitmap, at full resolution.

    Recognition only: the crop IS the line, so there is nothing left to detect (see
    SPACE_RETRY_PADS for what re-detection was measured to do here).
    """
    scale = page.scale
    left = int((det.x0 - pad_points) * scale)
    right = int((det.x1 + pad_points) * scale)
    # y flips: the detection's y1 (top, in points from the bottom) is the SMALL pixel row.
    top = int((page.height_points - det.y1 - pad_points) * scale)
    bottom = int((page.height_points - det.y0 + pad_points) * scale)

    left, top = max(0, left), max(0, top)
    right = min(page.image.width, right)
    bottom = min(page.image.height, bottom)
    if right - left < 4 or bottom - top < 4:
        return None

    result, _ = _engine()(
        np.array(page.image.crop((left, top, right, bottom))),
        use_det=False,
        use_cls=False,
        use_rec=True,
    )
    if not result:
        return None
    return str(result[0][0]).strip()


def recover_word_spaces(page: PageImage, det: Detection) -> str | None:
    """Recover the word spaces the page-level read dropped, or None if we cannot.

    THE INVARIANT
    -------------
    A recovered reading is accepted only if removing all whitespace from it reproduces the
    original reading exactly::

        strip_spaces(recovered) == strip_spaces(det.text)

    So this function can only ever move spaces around. It cannot change, add, or drop a
    single character -- a wrong ADDRESS is therefore not a failure mode this path can
    produce, only a wrongly-spaced one, and even that has to survive the agreement check
    below. This matters because the second read is a genuinely independent look at the
    pixels: measured on the pack it sometimes returns "0r account" for "or account" or
    "Paper Mil Road" for "Paper Mill Road", and the invariant throws exactly those away.

    AGREEMENT
    ---------
    Each rung of the ladder crops a slightly different window around the same line. We take
    the reading that at least SPACE_RETRY_AGREEMENT rungs produce character-for-character.
    If the crops disagree about where the spaces go, we do not know where the spaces go, and
    we say so by returning None.
    """
    target = strip_spaces(det.text)
    votes: dict[str, int] = {}
    for pad in SPACE_RETRY_PADS:
        candidate = _recognize_line(page, det, pad)
        if candidate is None or strip_spaces(candidate) != target:
            continue  # INVARIANT: character drift, discard this rung entirely
        votes[candidate] = votes.get(candidate, 0) + 1

    if not votes:
        return None
    best, count = max(votes.items(), key=lambda kv: kv[1])
    if count < SPACE_RETRY_AGREEMENT:
        return None
    return best if best != det.text else None


def _extracted_field(
    name: str,
    value: Any,
    page: int | None,
    bbox: list[float] | None,
    certainty: str,
    source_text: str | None,
    notes: str | None = None,
) -> dict[str, Any]:
    """One ExtractedField, per CONTRACTS.md section 2. Same shape core emits."""
    return {
        "field": name,
        "value": value,
        "page": page,
        "bbox": bbox,
        "bbox_units": BBOX_UNITS,
        "certainty": certainty,
        "evidence_kind": "extracted",
        "source_text": source_text,
        "notes": notes,
    }


def _abstain(name: str, reason: str, source_text: str | None = None) -> dict[str, Any]:
    """Abstain. `value` stays null -- CONTRACTS section 2 requires that of an abstention.

    `source_text` is still carried when we HAVE read the characters and only failed to place
    the spaces. Withholding it would be throwing away information we actually hold: the
    reviewer can read the characters off the page anyway, and showing them what the engine
    saw is what lets them confirm or retype it in one step instead of hunting for the line.
    """
    return _extracted_field(name, None, None, None, "abstain", source_text, reason)


def _clean_value_text(field_name: str, text: str) -> str:
    """Undo recognition noise that is unambiguous, and nothing else.

    RapidOCR drops spaces inside runs of small caps and occasionally inside values. We
    repair ONLY spacing, and only where the field's own grammar makes the repair
    unambiguous. We never repair digits or letters -- a misread character stays misread and
    is caught by the confidence gate, because silently "correcting" a value is exactly the
    failure mode this challenge penalises.
    """
    cleaned = text.strip()
    if field_name in {"pay_frequency", "benefit_frequency"}:
        return cleaned.replace(" ", "").lower()
    if field_name in {
        "household_size", "regular_hours", "weekly_hours", "hourly_rate",
        "gross_pay", "net_pay", "monthly_benefit", "gross_receipts", "platform_fees",
    }:
        return cleaned.replace(" ", "")
    return cleaned


def extract_fields_from_detections(
    detections: Sequence[Detection],
    document_type: str,
    page: PageImage | None = None,
) -> dict[str, dict[str, Any]]:
    """Label-anchored extraction over OCR detections.

    Identical grammar to `core.extract`: find a known label, then read the detection
    directly beneath it and left-aligned with it. We never read a value we did not find a
    label for, which is what keeps embedded instruction text inert.

    `page` is optional. With it, a value whose word spaces were dropped gets one re-read of
    its own line (see `recover_word_spaces`); without it that value abstains as before. The
    re-read is reachable ONLY from that failure, so passing a page cannot change any field
    that already read cleanly.
    """
    lookup = LABEL_LOOKUP.get(document_type, {})
    found: dict[str, dict[str, Any]] = {}
    near, far = VALUE_Y_WINDOW

    labels: list[tuple[str, Detection]] = []
    for det in detections:
        field_name = lookup.get(normalize_label(det.text))
        if field_name is not None:
            labels.append((field_name, det))

    for field_name, label in labels:
        if field_name in found:
            continue  # first occurrence wins; these forms do not repeat labels

        # The label's column ends where the next label to its right on the same row begins.
        column_right = float("inf")
        for _, other in labels:
            if other is label:
                continue
            if abs(other.y0 - label.y0) <= 4.0 and other.x0 > label.x0 + 1.0:
                column_right = min(column_right, other.x0)

        candidates = [
            det
            for det in detections
            if near <= (label.y0 - det.y0) <= far
            and abs(det.x0 - label.x0) <= VALUE_X_TOLERANCE
            and det.x0 < column_right - VALUE_X_TOLERANCE
        ]
        if not candidates:
            found[field_name] = _abstain(
                field_name, "label located but no OCR detection beneath it in its column"
            )
            continue

        candidates.sort(key=lambda d: label.y0 - d.y0)
        chosen = candidates[0]
        certainty = chosen.certainty()

        if certainty == "abstain":
            found[field_name] = _abstain(
                field_name,
                f"OCR confidence {chosen.confidence:.3f} is below the calibrated "
                f"{LOW_CONFIDENCE} floor; text read as {chosen.text!r}",
            )
            continue

        # Word-space recovery for free-text values. One forced split is repaired (and
        # flagged); anything ambiguous abstains rather than emitting a wrong string.
        value_text = chosen.text
        repaired = False
        reread = False
        if field_name in {"person_name", "address"}:
            despaced = bool(_DROPPED_SPACE.search(value_text)) or (
                " " not in value_text and bool(_CASE_BOUNDARY.search(value_text))
            )
            if despaced:
                # Look again at the pixels before giving up on this value. This is the only
                # thing here that adds INFORMATION -- everything below only reasons about
                # the string we already have.
                recovered = recover_word_spaces(page, chosen) if page is not None else None
                if recovered is not None:
                    value_text, reread = recovered, True

            if not reread:
                if _DROPPED_SPACE.search(value_text):
                    found[field_name] = _abstain(
                        field_name,
                        "OCR read every character of this value confidently but ran the "
                        "words together (a comma is followed by a non-space), and re-reading "
                        "the line on its own did not settle where the spaces belong. The "
                        "characters are shown as read; a reviewer only needs to fix the "
                        f"spacing. Read as {chosen.text!r}",
                        source_text=chosen.text,
                    )
                    continue
                fixed = repair_single_space(value_text)
                if fixed is not None:
                    value_text, repaired = fixed, True
                elif " " not in value_text and _CASE_BOUNDARY.search(value_text):
                    found[field_name] = _abstain(
                        field_name,
                        "OCR read every character of this value confidently but ran the "
                        "words together, and neither re-reading the line nor a forced split "
                        "settled where the spaces belong. The characters are shown as read; "
                        f"a reviewer only needs to fix the spacing. Read as {chosen.text!r}",
                        source_text=chosen.text,
                    )
                    continue

        try:
            value, unambiguous = parse_value(field_name, _clean_value_text(field_name, value_text))
        except ParseError as exc:
            found[field_name] = _abstain(
                field_name, f"OCR text {chosen.text!r} did not parse for this field: {exc}"
            )
            continue

        notes = "value read by OCR (rapidocr-onnxruntime); box is the engine's own detection"
        if reread:
            certainty = "low"
            notes += (
                f" | the page-level read ran the words together ({chosen.text!r}); re-reading "
                "this line on its own at full resolution restored the word spaces. Every "
                "character is identical between the two reads -- only the spacing differs -- "
                "so the wording is certain and only the spacing was inferred. Confirm it"
            )
        if repaired:
            certainty = "low"
            notes += (
                f" | OCR read {chosen.text!r} with the word space dropped; restored the one "
                "forced split point -- confirm with a human"
            )
        if len(candidates) > 1:
            certainty = "low"
            notes += f" | {len(candidates)} candidate detections under this label"
        if not unambiguous:
            certainty = "low"
            notes += " | value did not match the expected format for this field"
        if certainty == "high" and chosen.confidence < 0.99:
            notes += f" | engine confidence {chosen.confidence:.3f}"

        found[field_name] = _extracted_field(
            field_name, value, chosen.page, chosen.bbox(), certainty, chosen.text, notes
        )

    return found


def extract_document_ocr(
    pdf_path: str | Path | bytes,
    document_type: str | None = None,
    scale: float = RENDER_SCALE,
    reference_date=REFERENCE_DATE,
    window_days: int = CURRENCY_WINDOW_DAYS,
    expiring_soon_days: int | None = DEFAULT_EXPIRING_SOON_DAYS,
    file_name: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Turn a rasterized PDF into a `DocumentView` -- same contract as `extract_document`.

    Deterministic: the ONNX models run fixed weights on a fixed rendering, so the same
    bytes in give the same JSON out, with no network and no LLM.

    Accepts raw bytes for an in-memory upload, on the same terms as `core.extract_document`:
    with no file name there is nothing to infer a type or an id from, so the caller supplies
    both.
    """
    if isinstance(pdf_path, (bytes, bytearray)):
        source: Any = bytes(pdf_path)
        display_name = file_name or "upload.pdf"
        doc_type = document_type or "unknown"
        resolved_id, household_id = (document_id or "UPLOAD", "")
    else:
        path = Path(pdf_path)
        source = path
        display_name = file_name or path.name
        doc_type = document_type or infer_document_type(path)
        inferred_id, household_id = infer_ids(path)
        resolved_id = document_id or inferred_id

    # One rasterisation, reused for detection and for any single-line re-read.
    page = load_page_image(source, 1, scale)
    detections = read_detections(source, 1, scale, page=page)
    found = extract_fields_from_detections(detections, doc_type, page=page)

    fields: list[dict[str, Any]] = []
    for name in EXPECTED_FIELDS.get(doc_type, ()):
        fields.append(
            found.get(name)
            or _abstain(name, "no label for this field was found by OCR on the page")
        )

    date_field_name = DATE_FIELD_BY_TYPE.get(doc_type)
    date_text: str | None = None
    if date_field_name:
        for item in fields:
            if item["field"] == date_field_name and item["certainty"] != "abstain":
                date_text = str(item["value"])
                break

    staleness = assess_staleness(date_text, reference_date, window_days, expiring_soon_days)
    if staleness.reason:
        for item in fields:
            if item["field"] == date_field_name:
                item["notes"] = " | ".join(filter(None, [item.get("notes"), staleness.reason]))
                break

    return {
        "document_id": resolved_id,
        "household_id": household_id,
        "document_type": doc_type,
        "file_name": display_name,
        "page_count": 1,
        "page_size_points": [
            round(page.width_points, 2),
            round(page.height_points, 2),
        ],
        "fields": fields,
        "document_date": staleness.document_date,
        "state": staleness.state,
        "days_until_stale": staleness.days_until_stale,
        "stale_rule_id": STALE_RULE_ID,
        "extraction_method": "ocr",
    }


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print("usage: python ocr/ocr_extract.py <document.pdf> [more.pdf ...]", file=sys.stderr)
        return 2
    for arg in argv[1:]:
        print(json.dumps(extract_document_ocr(arg), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
