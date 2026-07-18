"""Deterministic PDF field extraction for the RealDoor challenge.

Design rule (the one that matters): **bounding boxes come from the PDF, never from a
model.** We read words and their coordinates with pdfplumber, then use the fixture's
own visual grammar -- a small bold ALL-CAPS label with its value in the column
directly beneath it -- to decide which words constitute which field.

Consequences of that choice, on purpose:
  * Every value has a real, verifiable source box. The UI overlay cannot drift.
  * A page with no text layer (a scan) yields *abstentions*, not guesses.
  * Text embedded in the document can never steer us, because we only ever read
    the column under a label we already know (rule CH-SAFETY-001). Injected
    instructions are captured as `untrusted_instruction_text` -- quarantined data,
    never instructions.

An LLM may later be plugged in as a `FieldMapper` to resolve label strings we do not
recognise (see `FieldMapper` / `unmapped_labels`). It maps *label text to field name*
and nothing else: it never sees a value, never produces a box, and its results are
capped at `certainty="low"` by construction. This module calls no model.

Frozen constants used here are traceable to the pack:
  * REFERENCE_DATE / CURRENCY_WINDOW_DAYS / STALE_RULE_ID
    <- pack/rules/RULES_README.md and rule CH-READINESS-001 in
       pack/rules/rule_corpus.jsonl ("current ... when dated no more than 60 days
       before 2026-07-18. This is a challenge convention, not a universal LIHTC rule.")

Coordinate system: PDF points, bottom-left origin, matching the pack gold exactly
(`bbox_units="pdf_points_bottom_left_origin"`).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pdfplumber

# --------------------------------------------------------------------------------------
# Frozen challenge constants (traceable to pack/rules/)
# --------------------------------------------------------------------------------------

#: The frozen event date for the whole simulation. NOT `date.today()`. Deterministic runs
#: depend on this staying fixed. Source: pack/rules/RULES_README.md.
REFERENCE_DATE = date(2026, 7, 18)

#: A document is "current" when dated no more than this many days before REFERENCE_DATE.
#: Source: RULES_README.md line 5 / rule CH-READINESS-001.
CURRENCY_WINDOW_DAYS = 60

#: The rule id cited whenever we report staleness.
STALE_RULE_ID = "CH-READINESS-001"

#: There is NO frozen rule in the pack defining how many days before expiry counts as
#: "expiring_soon". The enum value exists in the contract but the threshold does not
#: exist in pack/rules/. We therefore never emit it unless a caller explicitly opts in.
DEFAULT_EXPIRING_SOON_DAYS: int | None = None

BBOX_UNITS = "pdf_points_bottom_left_origin"

# --------------------------------------------------------------------------------------
# The fixture's box convention
# --------------------------------------------------------------------------------------
# The pack's gold boxes are not glyph outlines. They are drawn line boxes, anchored on
# the **text baseline** -- the y in the PDF text matrix, not the bottom of the glyph
# bounding box. Measured across all 159 gold fields, the generator emits:
#
#     y0 = baseline - DESCENT_PAD
#     y1 = baseline + font_size + ASCENT_PAD
#     x1 = x0 + max(MIN_BOX_WIDTH, glyph_width + RIGHT_PAD)
#
# The distinction matters and is easy to miss: a glyph box bottom sits at
# `baseline - 0.207 * size` for Helvetica, so anchoring on it happens to agree with gold
# at 10pt (0.07pt off) and drifts visibly at 14pt (0.9pt off). Using the real baseline
# removes the size dependence entirely. The 24pt minimum width keeps a one-character
# value ("1") a usable click target.
#
# `LineBoxConvention.raw()` returns untouched glyph extents instead. `selfcheck.py`
# reports IoU under both, so the size of this convention's contribution stays visible
# rather than being quietly folded into a headline number.

DESCENT_PAD = 2.0
ASCENT_PAD = 2.0
RIGHT_PAD = 4.0
MIN_BOX_WIDTH = 24.0


@dataclass(frozen=True)
class LineBoxConvention:
    """How a run of glyphs is grown into a drawable box."""

    descent_pad: float = DESCENT_PAD
    ascent_pad: float = ASCENT_PAD
    right_pad: float = RIGHT_PAD
    min_width: float = MIN_BOX_WIDTH
    use_baseline: bool = True

    @classmethod
    def raw(cls) -> "LineBoxConvention":
        """Untouched glyph extents -- no pads, no minimum width, no baseline anchoring."""
        return cls(
            descent_pad=0.0, ascent_pad=0.0, right_pad=0.0, min_width=0.0, use_baseline=False
        )


# --------------------------------------------------------------------------------------
# Words
# --------------------------------------------------------------------------------------

#: The fixtures carry a large diagonal "SYNTHETIC - NOT A REAL DOCUMENT" watermark drawn
#: as individually-placed glyphs. Left in, it interleaves with body text and shreds word
#: grouping ("MAILING AD DRESS"). It is the only text on the page above 20pt.
WATERMARK_MIN_SIZE = 20.0

#: Field labels are 8pt Helvetica-Bold. The "TRAINING FIXTURE" banner is 9pt bold and the
#: footer is 7pt regular, so this window isolates labels cleanly.
LABEL_SIZE_RANGE = (7.5, 8.5)


@dataclass(frozen=True)
class Word:
    """One word with bottom-left-origin PDF-point coordinates.

    Carries both the typographic baseline (from the PDF text matrix) and the glyph
    bounding box, because the two answer different questions and the gold uses the first.
    """

    text: str
    x0: float
    x1: float
    baseline: float  # y of the text baseline, from the PDF text matrix
    glyph_bottom: float  # y of the bottom of the glyph bounding box
    glyph_top: float  # y of the top of the glyph bounding box
    size: float
    bold: bool
    page: int

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    def is_label(self) -> bool:
        lo, hi = LABEL_SIZE_RANGE
        return self.bold and lo <= self.size <= hi and self.text.upper() == self.text

    def bbox(self, convention: LineBoxConvention = LineBoxConvention()) -> list[float]:
        """Box in PDF points, bottom-left origin: [x0, y0, x1, y1]."""
        return _grow_box(
            self.x0,
            self.x1,
            self.baseline,
            self.glyph_bottom,
            self.glyph_top,
            self.size,
            convention,
        )


def _grow_box(
    x0: float,
    x1: float,
    baseline: float,
    glyph_bottom: float,
    glyph_top: float,
    size: float,
    convention: LineBoxConvention,
) -> list[float]:
    if convention.use_baseline:
        y0 = baseline - convention.descent_pad
        y1 = baseline + size + convention.ascent_pad
    else:
        y0, y1 = glyph_bottom, glyph_top
    width = max(convention.min_width, (x1 - x0) + convention.right_pad)
    return [round(x0, 2), round(y0, 2), round(x0 + width, 2), round(y1, 2)]


def _is_watermark(obj: dict) -> bool:
    return float(obj.get("size", 0.0) or 0.0) >= WATERMARK_MIN_SIZE


def read_words(page: Any, page_number: int) -> list[Word]:
    """Extract watermark-free words from a pdfplumber page, in bottom-left coordinates.

    Returns an empty list for a page with no text layer (a scan). That is a legitimate
    result, and the caller must abstain rather than invent anything.
    """
    height = float(page.height)
    body = page.filter(lambda obj: not _is_watermark(obj))
    words: list[Word] = []
    for w in body.extract_words(
        extra_attrs=["size", "fontname"], use_text_flow=False, return_chars=True
    ):
        text = w["text"].strip()
        if not text or text.startswith("(cid:"):
            continue
        chars = w.get("chars") or []
        # matrix[5] is the text-space translation in y: the true baseline. Fall back to
        # the glyph box bottom only if a char somehow carries no matrix.
        baseline = float(chars[0]["matrix"][5]) if chars and chars[0].get("matrix") else None
        glyph_bottom = height - float(w["bottom"])
        words.append(
            Word(
                text=text,
                x0=float(w["x0"]),
                x1=float(w["x1"]),
                baseline=baseline if baseline is not None else glyph_bottom,
                glyph_bottom=glyph_bottom,
                glyph_top=height - float(w["top"]),
                size=round(float(w["size"]), 2),
                bold="Bold" in str(w.get("fontname", "")),
                page=page_number,
            )
        )
    return words


def group_lines(words: Iterable[Word], tolerance: float = 1.5) -> list[list[Word]]:
    """Group words into visual lines by shared baseline, each sorted left to right."""
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (-w.baseline, w.x0)):
        for line in lines:
            if abs(line[0].baseline - word.baseline) <= tolerance:
                line.append(word)
                break
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def _join_run(run: Sequence[Word]) -> str:
    return " ".join(w.text for w in run)


def _split_runs(line: Sequence[Word], gap_factor: float = 0.6) -> list[list[Word]]:
    """Split one line into runs, breaking where the horizontal gap exceeds a space."""
    runs: list[list[Word]] = []
    for word in line:
        if runs and (word.x0 - runs[-1][-1].x1) <= gap_factor * word.size:
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


def _run_box(run: Sequence[Word], convention: LineBoxConvention) -> list[float]:
    return _grow_box(
        min(w.x0 for w in run),
        max(w.x1 for w in run),
        min(w.baseline for w in run),
        min(w.glyph_bottom for w in run),
        max(w.glyph_top for w in run),
        max(w.size for w in run),
        convention,
    )


# --------------------------------------------------------------------------------------
# Label -> field mapping (the swappable, optional-LLM seam)
# --------------------------------------------------------------------------------------

#: Field names are taken verbatim from pack/synthetic_documents/gold/document_gold.jsonl.
#: Nothing here is invented.
LABEL_MAP: dict[str, dict[str, str]] = {
    "application_summary": {
        "APPLICANT": "person_name",
        "HOUSEHOLD SIZE": "household_size",
        "MAILING ADDRESS": "address",
        "APPLICATION DATE": "application_date",
    },
    "pay_stub": {
        "EMPLOYEE": "person_name",
        "PAY DATE": "pay_date",
        "PAY PERIOD": "pay_period_start",
        "THROUGH": "pay_period_end",
        "PAY FREQUENCY": "pay_frequency",
        "REGULAR HOURS": "regular_hours",
        "HOURLY RATE": "hourly_rate",
        "GROSS PAY": "gross_pay",
        "NET PAY": "net_pay",
    },
    "employment_letter": {
        "EMPLOYEE": "person_name",
        "LETTER DATE": "document_date",
        "HOURS PER WEEK": "weekly_hours",
        "HOURLY RATE": "hourly_rate",
    },
    "benefit_letter": {
        "RECIPIENT": "person_name",
        "LETTER DATE": "document_date",
        "MONTHLY AMOUNT": "monthly_benefit",
        "FREQUENCY": "benefit_frequency",
    },
    "gig_statement": {
        "WORKER": "person_name",
        "STATEMENT MONTH": "statement_month",
        "GROSS RECEIPTS": "gross_receipts",
        "PLATFORM FEES": "platform_fees",
    },
}

#: Fields the gold file carries for each document type. Anything here that we fail to
#: locate is emitted as an explicit abstention rather than silently omitted.
EXPECTED_FIELDS: dict[str, tuple[str, ...]] = {
    doc_type: tuple(dict.fromkeys(mapping.values())) for doc_type, mapping in LABEL_MAP.items()
}

#: (document_type, label) -> field name, or None if the label is not understood.
FieldMapper = Callable[[str, str], str | None]


def deterministic_mapper(document_type: str, label: str) -> str | None:
    """Exact lookup in the frozen label table. No inference, no model."""
    return LABEL_MAP.get(document_type, {}).get(label.upper())


def unmapped_labels(pdf_path: str | Path, document_type: str | None = None) -> list[str]:
    """Label strings on the page that `deterministic_mapper` does not recognise.

    This is the exact input an LLM mapping step would consume: label text only, with no
    values and no coordinates attached. Use it to decide whether a model is worth adding.
    """
    path = Path(pdf_path)
    doc_type = document_type or infer_document_type(path)
    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for line in group_lines(read_words(page, page_number)):
                for run in _split_runs([w for w in line if w.is_label()]):
                    label = _join_run(run)
                    if deterministic_mapper(doc_type, label) is None:
                        out.append(label)
    return out


# --------------------------------------------------------------------------------------
# Value parsing
# --------------------------------------------------------------------------------------

MONEY_FIELDS = frozenset(
    {"hourly_rate", "gross_pay", "net_pay", "monthly_benefit", "gross_receipts", "platform_fees"}
)
INTEGER_FIELDS = frozenset({"household_size", "regular_hours", "weekly_hours"})
DATE_FIELDS = frozenset(
    {"application_date", "pay_date", "pay_period_start", "pay_period_end", "document_date"}
)
MONTH_FIELDS = frozenset({"statement_month"})
FREQUENCY_FIELDS = frozenset({"pay_frequency", "benefit_frequency"})

#: Frequencies the pack actually uses. An unrecognised frequency downgrades to "low"
#: rather than being silently accepted, because CH-INCOME-001 annualizes from this value.
KNOWN_FREQUENCIES = frozenset({"weekly", "biweekly", "semimonthly", "monthly", "annual", "yearly"})

_MONEY_RE = re.compile(r"^\$?-?[\d,]+(?:\.\d+)?$")


class ParseError(ValueError):
    """The text under a label did not parse as the type that field requires."""


def parse_value(field_name: str, text: str) -> tuple[Any, bool]:
    """Normalize raw page text into a typed value.

    Returns `(value, unambiguous)`. `unambiguous=False` means we produced a value but
    had to stretch to do it, and the caller should record `certainty="low"`.
    Raises `ParseError` when no honest value can be produced -- the caller abstains.
    """
    raw = text.strip()
    if not raw:
        raise ParseError("empty")

    if field_name in DATE_FIELDS:
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date().isoformat(), True
        except ValueError as exc:
            raise ParseError(f"not an ISO date: {raw!r}") from exc

    if field_name in MONTH_FIELDS:
        try:
            datetime.strptime(raw, "%Y-%m")
        except ValueError as exc:
            raise ParseError(f"not an ISO month: {raw!r}") from exc
        return raw, True

    if field_name in MONEY_FIELDS:
        if not _MONEY_RE.match(raw):
            raise ParseError(f"not a currency amount: {raw!r}")
        return float(raw.replace("$", "").replace(",", "")), True

    if field_name in INTEGER_FIELDS:
        cleaned = raw.replace(",", "")
        try:
            number = float(cleaned)
        except ValueError as exc:
            raise ParseError(f"not a number: {raw!r}") from exc
        if number != int(number):
            # e.g. "38.5 hours" -- real, but not the integer the gold schema carries.
            return number, False
        return int(number), True

    if field_name in FREQUENCY_FIELDS:
        token = raw.lower()
        return token, token in KNOWN_FREQUENCIES

    return raw, True


# --------------------------------------------------------------------------------------
# Untrusted embedded text (CH-SAFETY-001)
# --------------------------------------------------------------------------------------

UNTRUSTED_MARKER = "UNTRUSTED DOCUMENT TEXT"


def find_untrusted_text(
    lines: Sequence[Sequence[Word]], convention: LineBoxConvention
) -> tuple[str, list[float], int] | None:
    """Locate injected instruction text, so it can be quarantined and shown to a human.

    We capture it as *data*. It is never interpreted, and its presence never changes any
    other field we extract, because extraction only ever reads the column under a known
    label.
    """
    for index, line in enumerate(lines):
        if UNTRUSTED_MARKER in _join_run(line).upper():
            for following in lines[index + 1 :]:
                text = _join_run(following)
                if text.strip():
                    return text, _run_box(following, convention), following[0].page
            return None
    return None


# --------------------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------------------

#: A value sits 6-22pt below its label's baseline. Measured span in the pack is 14.5-15.3pt
#: (larger type sits slightly lower), so this window is tight enough to never reach the
#: next row of the form.
VALUE_Y_WINDOW = (6.0, 22.0)

#: A value is left-aligned with its label to within this many points.
VALUE_X_TOLERANCE = 3.0

_DOC_TYPE_RE = re.compile(r"^(hh-\d+)_(d\d+)_(.+)$", re.IGNORECASE)


def infer_document_type(pdf_path: str | Path) -> str:
    """Derive the document type from the pack's file naming convention."""
    stem = Path(pdf_path).stem
    match = _DOC_TYPE_RE.match(stem)
    doc_type = match.group(3).lower() if match else stem.lower()
    return doc_type if doc_type in LABEL_MAP else "unknown"


def infer_ids(pdf_path: str | Path) -> tuple[str, str]:
    """(document_id, household_id) from the file name, e.g. ("HH-001-D01", "HH-001")."""
    stem = Path(pdf_path).stem
    match = _DOC_TYPE_RE.match(stem)
    if not match:
        return stem.upper(), ""
    household = match.group(1).upper()
    return f"{household}-{match.group(2).upper()}", household


def _extracted_field(
    name: str,
    value: Any,
    page: int | None,
    bbox: list[float] | None,
    certainty: str,
    source_text: str | None,
    notes: str | None = None,
) -> dict[str, Any]:
    """One ExtractedField, per CONTRACTS.md section 2."""
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


def _abstain(name: str, reason: str) -> dict[str, Any]:
    """An honest 'we could not locate this'. Value is null; the UI asks a human."""
    return _extracted_field(name, None, None, None, "abstain", None, reason)


def extract_fields_from_page(
    words: Sequence[Word],
    document_type: str,
    convention: LineBoxConvention,
    field_mapper: FieldMapper = deterministic_mapper,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Label-anchored extraction for one page.

    Returns (fields keyed by name, labels we could not map).
    """
    lines = group_lines(words)
    found: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []

    for line in lines:
        label_runs = _split_runs([w for w in line if w.is_label()])
        if not label_runs:
            continue
        # A label's column ends where the next label on the same row begins.
        starts = [run[0].x0 for run in label_runs]
        for index, run in enumerate(label_runs):
            label = _join_run(run)
            field_name = field_mapper(document_type, label)
            if field_name is None:
                unmapped.append(label)
                continue
            if field_name in found:
                continue  # first occurrence wins; forms do not repeat labels
            column_right = starts[index + 1] if index + 1 < len(starts) else float("inf")
            resolved = _resolve_value(
                lines, run, column_right, field_name, convention, is_exact=True
            )
            if resolved is not None:
                found[field_name] = resolved

    return found, unmapped


def _resolve_value(
    lines: Sequence[Sequence[Word]],
    label_run: Sequence[Word],
    column_right: float,
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
) -> dict[str, Any] | None:
    """Find the value belonging to one label, or return None so the caller abstains."""
    label_x0 = label_run[0].x0
    label_baseline = label_run[0].baseline
    near, far = VALUE_Y_WINDOW

    candidates: list[list[Word]] = []
    for line in lines:
        delta = label_baseline - line[0].baseline
        if not (near <= delta <= far):
            continue
        in_column = [
            w
            for w in line
            if w.x0 >= label_x0 - VALUE_X_TOLERANCE and w.x0 < column_right - VALUE_X_TOLERANCE
        ]
        if not in_column:
            continue
        for run in _split_runs(in_column):
            if abs(run[0].x0 - label_x0) <= VALUE_X_TOLERANCE:
                candidates.append(run)

    if not candidates:
        return None

    # Closest line to the label wins; more than one candidate means the layout was not
    # unambiguous, so we keep the value but drop to "low".
    candidates.sort(key=lambda run: label_baseline - run[0].baseline)
    run = candidates[0]
    source_text = _join_run(run)

    try:
        value, clean = parse_value(field_name, source_text)
    except ParseError as exc:
        return _abstain(field_name, f"value under label did not parse: {exc}")

    unambiguous = clean and is_exact and len(candidates) == 1
    notes = None
    if not unambiguous:
        if not is_exact:
            notes = "label resolved by a non-exact mapper"
        elif len(candidates) > 1:
            notes = f"{len(candidates)} candidate value runs under this label"
        else:
            notes = "value did not match the expected format for this field"

    return _extracted_field(
        field_name,
        value,
        run[0].page,
        _run_box(run, convention),
        "high" if unambiguous else "low",
        source_text,
        notes,
    )


# --------------------------------------------------------------------------------------
# Document date + staleness (CH-READINESS-001)
# --------------------------------------------------------------------------------------

#: Which extracted field carries the document's own date, per document type.
DATE_FIELD_BY_TYPE: dict[str, str] = {
    "application_summary": "application_date",
    "pay_stub": "pay_date",
    "employment_letter": "document_date",
    "benefit_letter": "document_date",
    "gig_statement": "statement_month",  # month granularity -- see below
}


@dataclass(frozen=True)
class Staleness:
    document_date: str | None
    days_until_stale: int | None
    state: str
    reason: str | None = None


def assess_staleness(
    document_date_text: str | None,
    reference_date: date = REFERENCE_DATE,
    window_days: int = CURRENCY_WINDOW_DAYS,
    expiring_soon_days: int | None = DEFAULT_EXPIRING_SOON_DAYS,
) -> Staleness:
    """Apply the frozen 60-day currency convention (CH-READINESS-001).

    `days_until_stale = (document_date + window) - reference_date`. Negative means the
    document is already outside the window. A missing or non-day-precise date yields
    `state="unreadable"` -- never an assumption of freshness.
    """
    if not document_date_text:
        return Staleness(None, None, "unreadable", "no document date could be located")

    try:
        parsed = datetime.strptime(document_date_text, "%Y-%m-%d").date()
    except ValueError:
        return Staleness(
            None,
            None,
            "unreadable",
            f"document date {document_date_text!r} is not day-precise; "
            "the 60-day window cannot be applied without inventing a day",
        )

    days = (parsed + timedelta(days=window_days) - reference_date).days
    if days < 0:
        state = "expired"
    elif expiring_soon_days is not None and days <= expiring_soon_days:
        state = "expiring_soon"
    else:
        state = "present"
    return Staleness(parsed.isoformat(), days, state)


# --------------------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------------------


def extract_document(
    pdf_path: str | Path,
    document_type: str | None = None,
    field_mapper: FieldMapper = deterministic_mapper,
    convention: LineBoxConvention = LineBoxConvention(),
    reference_date: date = REFERENCE_DATE,
    window_days: int = CURRENCY_WINDOW_DAYS,
    expiring_soon_days: int | None = DEFAULT_EXPIRING_SOON_DAYS,
) -> dict[str, Any]:
    """Turn a PDF into a `DocumentView` (CONTRACTS.md section 3). Pure and deterministic.

    Same bytes in, same JSON out, on any machine, with no network and no model.
    """
    path = Path(pdf_path)
    doc_type = document_type or infer_document_type(path)
    document_id, household_id = infer_ids(path)

    with pdfplumber.open(path) as pdf:
        page_sizes = [(round(float(p.width), 2), round(float(p.height), 2)) for p in pdf.pages]
        page_count = len(pdf.pages)
        all_words: list[Word] = []
        found: dict[str, dict[str, Any]] = {}
        for page_number, page in enumerate(pdf.pages, start=1):
            words = read_words(page, page_number)
            all_words.extend(words)
            page_fields, _ = extract_fields_from_page(words, doc_type, convention, field_mapper)
            for name, value in page_fields.items():
                found.setdefault(name, value)

    fields: list[dict[str, Any]] = []
    has_text_layer = bool(all_words)

    for name in EXPECTED_FIELDS.get(doc_type, ()):
        if name in found:
            fields.append(found[name])
        elif not has_text_layer:
            fields.append(
                _abstain(
                    name,
                    "page has no text layer (scanned image); OCR is out of scope, so no "
                    "verifiable source box exists for this field",
                )
            )
        else:
            fields.append(_abstain(name, "no label for this field was found on the page"))

    untrusted = find_untrusted_text(group_lines(all_words), convention)
    if untrusted is not None:
        text, bbox, page_number = untrusted
        fields.append(
            _extracted_field(
                "untrusted_instruction_text",
                text,
                page_number,
                bbox,
                "high",
                text,
                "Embedded instruction text captured as quarantined DATA under CH-SAFETY-001. "
                "It is never executed and never influences any other field.",
            )
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
        "document_id": document_id,
        "household_id": household_id,
        "document_type": doc_type,
        "file_name": path.name,
        "page_count": page_count,
        "page_size_points": list(page_sizes[0]) if page_sizes else None,
        "fields": fields,
        "document_date": staleness.document_date,
        "state": staleness.state,
        "days_until_stale": staleness.days_until_stale,
        "stale_rule_id": STALE_RULE_ID,
    }


def main(argv: Sequence[str]) -> int:
    if len(argv) < 2:
        print("usage: python core/extract.py <document.pdf> [more.pdf ...]", file=sys.stderr)
        return 2
    for arg in argv[1:]:
        print(json.dumps(extract_document(arg), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
