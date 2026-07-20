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

import io
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
#: footer is 7pt regular, so this window isolates labels cleanly *in the pack's own
#: typography*. It is a house style, not a property of pay stubs, and `is_label` is only
#: the first of two ways a label can be recognised -- see `_label_runs`.
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


# --------------------------------------------------------------------------------------
# A second, wider vocabulary for the same fields (the `FieldMapper` seam, filled in)
# --------------------------------------------------------------------------------------
# `LABEL_MAP` is the pack's own vocabulary and it is exact. Measured against documents
# that differ from the pack *only* in label wording -- same layout, same typography, same
# values -- it recovered 7 of 22 fields (31.8%). A synonym is not a near miss to an exact
# dict lookup; it is a total miss, so a page a human reads instantly came back blank.
#
# This table is the same kind of object as `LABEL_MAP`: a closed, hand-written set of
# strings. It is deliberately NOT merged into `LABEL_MAP`, for one concrete reason --
# `ocr/ocr_extract.py` builds its own lookup from `LABEL_MAP`, and the OCR path resolves
# labels against fuzzy character detections rather than exact text. Widening the
# vocabulary *there* would be a different argument with a different risk, and it is not
# the argument made here. Keeping the tables separate leaves the OCR path bit-identical.
#
# What is deliberately NOT in here: bare tokens whose meaning depends on context.
# "NAME" (employee's or employer's?), "RATE" (of pay or of tax?) and "TOTAL HOURS"
# (regular, or regular + overtime?) were all considered and left out. Each could name
# something other than the field it resembles, and a synonym that names the wrong thing
# is the one way this table could produce a wrong answer instead of an abstention.
LABEL_SYNONYMS: dict[str, dict[str, str]] = {
    "application_summary": {
        "APPLICANT NAME": "person_name",
        "NAME OF APPLICANT": "person_name",
        "PRIMARY APPLICANT": "person_name",
        "HEAD OF HOUSEHOLD": "person_name",
        "HOUSEHOLD MEMBERS": "household_size",
        "NUMBER IN HOUSEHOLD": "household_size",
        "NO. IN HOUSEHOLD": "household_size",
        "PERSONS IN HOUSEHOLD": "household_size",
        "FAMILY SIZE": "household_size",
        "HOUSEHOLD COUNT": "household_size",
        "ADDRESS": "address",
        "HOME ADDRESS": "address",
        "STREET ADDRESS": "address",
        "CURRENT ADDRESS": "address",
        "RESIDENCE ADDRESS": "address",
        "DATE OF APPLICATION": "application_date",
        "DATE SUBMITTED": "application_date",
        "SUBMITTED ON": "application_date",
    },
    "pay_stub": {
        "EMPLOYEE NAME": "person_name",
        "EMPLOYEE'S NAME": "person_name",
        "NAME OF EMPLOYEE": "person_name",
        "CHECK DATE": "pay_date",
        "DATE PAID": "pay_date",
        "PAYMENT DATE": "pay_date",
        "PAYCHECK DATE": "pay_date",
        "DATE OF PAY": "pay_date",
        # PeopleSoft calls the payment an "advice" and dates it accordingly; the phrase is
        # the whole entry, so it names one thing and cannot be read as "the date of what?".
        "ADVICE DATE": "pay_date",
        "PERIOD COVERED": "pay_period_start",
        "PERIOD BEGINNING": "pay_period_start",
        "PERIOD BEGIN": "pay_period_start",
        "PERIOD START": "pay_period_start",
        "PAY PERIOD BEGINNING": "pay_period_start",
        "PAY PERIOD START": "pay_period_start",
        "PAY BEGIN DATE": "pay_period_start",
        "FROM": "pay_period_start",
        "TO": "pay_period_end",
        "THRU": "pay_period_end",
        "PERIOD ENDING": "pay_period_end",
        "PERIOD END": "pay_period_end",
        "PAY PERIOD ENDING": "pay_period_end",
        "PAY PERIOD END": "pay_period_end",
        "PAY END DATE": "pay_period_end",
        "FOR PAY PERIOD ENDING": "pay_period_end",
        "PAY CYCLE": "pay_frequency",
        "PAYROLL CYCLE": "pay_frequency",
        "PAYROLL FREQUENCY": "pay_frequency",
        "PAY SCHEDULE": "pay_frequency",
        "FREQUENCY": "pay_frequency",
        "HOURS WORKED": "regular_hours",
        "HRS WORKED": "regular_hours",
        "REG HOURS": "regular_hours",
        "REGULAR HRS": "regular_hours",
        "RATE OF PAY": "hourly_rate",
        "PAY RATE": "hourly_rate",
        "BASE RATE": "hourly_rate",
        "REGULAR RATE": "hourly_rate",
        "RATE PER HOUR": "hourly_rate",
        "HOURLY WAGE": "hourly_rate",
        "TOTAL EARNINGS": "gross_pay",
        "GROSS EARNINGS": "gross_pay",
        "GROSS WAGES": "gross_pay",
        "GROSS INCOME": "gross_pay",
        "GROSS AMOUNT": "gross_pay",
        "TOTAL GROSS": "gross_pay",
        "TOTAL GROSS PAY": "gross_pay",
        "TAKE HOME PAY": "net_pay",
        "TAKE-HOME PAY": "net_pay",
        "NET AMOUNT": "net_pay",
        "NET EARNINGS": "net_pay",
        "NET WAGES": "net_pay",
    },
    "employment_letter": {
        "EMPLOYEE NAME": "person_name",
        "EMPLOYEE'S NAME": "person_name",
        "NAME OF EMPLOYEE": "person_name",
        "DATE OF LETTER": "document_date",
        "LETTER DATED": "document_date",
        "WEEKLY HOURS": "weekly_hours",
        "HOURS/WEEK": "weekly_hours",
        "HOURS PER WEEK WORKED": "weekly_hours",
        "AVERAGE WEEKLY HOURS": "weekly_hours",
        "SCHEDULED HOURS PER WEEK": "weekly_hours",
        "RATE OF PAY": "hourly_rate",
        "PAY RATE": "hourly_rate",
        "BASE RATE": "hourly_rate",
        "CURRENT RATE": "hourly_rate",
        "RATE PER HOUR": "hourly_rate",
        "HOURLY WAGE": "hourly_rate",
    },
    "benefit_letter": {
        "BENEFICIARY": "person_name",
        "CLAIMANT": "person_name",
        "RECIPIENT NAME": "person_name",
        "NAME OF RECIPIENT": "person_name",
        "DATE OF LETTER": "document_date",
        "NOTICE DATE": "document_date",
        "LETTER DATED": "document_date",
        "MONTHLY BENEFIT": "monthly_benefit",
        "MONTHLY BENEFIT AMOUNT": "monthly_benefit",
        "MONTHLY PAYMENT": "monthly_benefit",
        "MONTHLY AWARD": "monthly_benefit",
        "BENEFIT AMOUNT": "monthly_benefit",
        "PAYMENT AMOUNT": "monthly_benefit",
        "PAYMENT FREQUENCY": "benefit_frequency",
        "BENEFIT FREQUENCY": "benefit_frequency",
        "PAYMENT SCHEDULE": "benefit_frequency",
        "PAID": "benefit_frequency",
    },
    "gig_statement": {
        "DRIVER": "person_name",
        "CONTRACTOR": "person_name",
        "PARTNER": "person_name",
        "PAYEE": "person_name",
        "WORKER NAME": "person_name",
        "STATEMENT PERIOD": "statement_month",
        "REPORTING MONTH": "statement_month",
        "REPORTING PERIOD": "statement_month",
        "MONTH": "statement_month",
        "TOTAL RECEIPTS": "gross_receipts",
        "GROSS REVENUE": "gross_receipts",
        "GROSS PAYMENTS": "gross_receipts",
        "TOTAL EARNINGS": "gross_receipts",
        "GROSS EARNINGS": "gross_receipts",
        "TOTAL FARES": "gross_receipts",
        "SERVICE FEES": "platform_fees",
        "SERVICE FEE": "platform_fees",
        "PLATFORM FEE": "platform_fees",
        "PLATFORM COMMISSION": "platform_fees",
        "COMMISSION": "platform_fees",
        "FEES": "platform_fees",
    },
}

_LABEL_PUNCT_RE = re.compile(r"[\s:]+")


def normalize_label(text: str) -> str:
    """Upper-case, collapse whitespace, drop a trailing colon.

    Only ever used to compare a label against a closed set of strings. It does not widen
    what counts as a label run, so it cannot admit a string that is not already in one of
    the two tables.
    """
    return _LABEL_PUNCT_RE.sub(" ", text.upper()).strip()


#: Canonical table plus synonyms, normalized once at import.
_WIDE_LABELS: dict[str, dict[str, str]] = {
    doc_type: {
        **{normalize_label(k): v for k, v in LABEL_MAP.get(doc_type, {}).items()},
        **{normalize_label(k): v for k, v in LABEL_SYNONYMS.get(doc_type, {}).items()},
    }
    for doc_type in set(LABEL_MAP) | set(LABEL_SYNONYMS)
}


def synonym_mapper(document_type: str, label: str) -> str | None:
    """Closed-set lookup over the canonical labels *and* the hand-written synonyms.

    Same shape as `deterministic_mapper` and just as deterministic: an exact membership
    test against a table written by hand and frozen in source. No model, no network, no
    inference, no partial or fuzzy matching. A string that is in neither table returns
    `None` and the caller abstains exactly as before.
    """
    return _WIDE_LABELS.get(document_type, {}).get(normalize_label(label))


# --------------------------------------------------------------------------------------
# What is even worth asking a mapper about
# --------------------------------------------------------------------------------------
# Every run of words on the page used to be offered to the mapper. On the pack that was
# free, because `is_label()` had already cut the page down to a handful of bold ALL-CAPS
# runs. On real documents it is not free: a five-page federal guide offers ~1,745 distinct
# strings, and with the model leg attached that is ~1,745 network calls and 25 minutes for
# six documents. Almost all of them are prose.
#
# So there is a deterministic gate in front of every mapper: a run has to be *shaped* like
# a label before anything is asked about it. The three tests below are properties of the
# label vocabulary itself, not of any particular document:
#
#   * it contains a letter                -- "1,627.74" and "07/23/2017" name nothing
#   * it is short                          -- the longest string in either frozen table is
#                                             four words; a sentence is not a label
#   * it is mostly letters                 -- "$45,000.00 Annual" is a value, not a label
#
# The gate can only ever *reduce* what is asked, so it cannot admit a string that the old
# code would have rejected. `core/test_extract_reading.py` asserts the converse -- that
# every key in both frozen tables passes it -- which is what stops it silently narrowing
# the vocabulary we already ship.

#: Longest label in the frozen tables, plus one word of headroom for a mapper that knows a
#: phrasing we do not. Derived, not guessed, so it tracks the tables if they grow.
MAX_LABEL_WORDS = max(
    len(normalize_label(key).split())
    for table in (LABEL_MAP, LABEL_SYNONYMS)
    for mapping in table.values()
    for key in mapping
) + 1

#: A label is mostly letters and spaces. Measured against the frozen tables, the lowest
#: ratio is "NO. IN HOUSEHOLD" / "HOURS/WEEK", which sit well above this floor.
MIN_LABEL_LETTER_RATIO = 0.6


def looks_like_a_label(text: str) -> bool:
    """Could this run of words be a field label at all? Deterministic, offline, cheap.

    A pre-filter, not a decision. Answering True means "worth asking a mapper about";
    the mapper still has to recognise the string exactly, so this never admits anything.
    Answering False skips the mapper entirely, which is what keeps the model leg from
    being handed a page of prose one sentence at a time.
    """
    normalized = normalize_label(text)
    if not normalized:
        return False
    words = normalized.split()
    if len(words) > MAX_LABEL_WORDS:
        return False
    letters = sum(character.isalpha() for character in normalized)
    if not letters:
        return False
    return letters / len(normalized.replace(" ", "") or " ") >= MIN_LABEL_LETTER_RATIO


# --------------------------------------------------------------------------------------
# Provenance notes -- how a reader tells the three paths apart
# --------------------------------------------------------------------------------------
# Three things can name a field, and they do not deserve equal trust, so a reader must be
# able to count them separately:
#
#   canonical label   -- `LABEL_MAP`. No note. May reach certainty="high".
#   synonym table     -- `LABEL_SYNONYMS`. Hand-written, frozen, offline, reproducible.
#   model mapper      -- `core.label_llm`. Needs a key and a network; not reproducible.
#
# The last two are both capped at certainty="low", but lumping them under one note would
# hide the only distinction a sceptical reader actually cares about: which numbers they
# can reproduce on their own machine with no key. So they carry different notes and
# `scripts/measure_label_mapping.py` reports them as separate columns.
SYNONYM_NOTE = "label resolved by a non-exact mapper"
MODEL_MAPPER_NOTE = "label resolved by the model mapper (closed set; see core/label_llm.py)"


def model_mapper(document_type: str, label: str) -> str | None:
    """`FieldMapper` backed by a model, constrained to `EXPECTED_FIELDS[document_type]`.

    Imported lazily so that `core.extract` keeps its promise of importing nothing that
    can touch a network. Returns None whenever the model is off, offline, unsure, or
    answers outside the closed set -- see `core/label_llm.py` for what is withheld.
    """
    from core import label_llm

    return label_llm.model_mapper(document_type, label)


def layered_mapper(document_type: str, label: str) -> str | None:
    """Tables first, model only for what they missed.

    The order is the reproducibility argument, not a performance one. Everything the two
    frozen tables can name is named by them, identically on every machine; the model is
    consulted only for strings both tables returned None for. A judge running offline
    therefore reproduces every table-resolved field exactly, and loses only the extra
    ones -- which are marked, and countable, precisely so that loss is visible.
    """
    found = synonym_mapper(document_type, label)
    if found is not None:
        return found
    return model_mapper(document_type, label)


class _TrackingMapper:
    """Wraps a mapper and remembers which field names the *model* leg produced.

    `extract_fields_from_page` needs this to label provenance honestly. It cannot infer
    it from "which fields appeared in pass 3", because admitting more labels also shifts
    column boundaries, and a synonym-named field can surface for that reason alone.
    Attributing such a field to the model would overstate what the model did.
    """

    def __init__(self, document_type: str) -> None:
        self.document_type = document_type
        self.from_model: set[str] = set()
        # Bound once and stored, so `stage is tracker.model_leg` in
        # `extract_fields_from_page` compares one stable object. Reading `self._model_leg`
        # afresh would build a new bound method every time and the identity test -- which
        # decides which fields get credited to the model -- would silently never fire.
        self.model_leg: FieldMapper = self._model_leg

    def __call__(self, document_type: str, label: str) -> str | None:
        found = synonym_mapper(document_type, label)
        if found is not None:
            return found
        return self.model_leg(document_type, label)

    def _model_leg(self, document_type: str, label: str) -> str | None:
        """The model on its own, with no table in front of it. See `_mapper_stages`."""
        found = model_mapper(document_type, label)
        if found is not None:
            self.from_model.add(found)
        return found


def tracking_layered_mapper(document_type: str = "") -> _TrackingMapper:
    """A `layered_mapper` that also tags model-named fields with `MODEL_MAPPER_NOTE`.

    Use this rather than `layered_mapper` when the provenance of a field matters -- which
    is any time the result is being counted. `layered_mapper` maps identically but leaves
    every non-exact field carrying the generic synonym note.
    """
    return _TrackingMapper(document_type)


def unmapped_labels(
    pdf_path: str | Path,
    document_type: str | None = None,
    mapper: FieldMapper = synonym_mapper,
) -> list[str]:
    """Label strings on the page that `mapper` does not recognise.

    This is the exact input an LLM mapping step would consume: label text only, with no
    values and no coordinates attached. Use it to decide whether a model is worth adding.
    Pass `mapper=deterministic_mapper` to ask the narrower question -- what the pack's own
    frozen vocabulary alone would miss.
    """
    path = Path(pdf_path)
    doc_type = document_type or infer_document_type(path)
    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            for line in group_lines(read_words(page, page_number)):
                for run in _split_runs([w for w in line if w.is_label()]):
                    label = _join_run(run)
                    if mapper(doc_type, label) is None:
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


# --------------------------------------------------------------------------------------
# Free-text fields still have a type
# --------------------------------------------------------------------------------------
# `person_name`, `address` and the two frequency fields accept a string, and for a long
# time that meant they accepted *any* string. Every other field is protected by its parser:
# point `gross_pay` at a sentence and `_MONEY_RE` rejects it, point `pay_date` at a
# paragraph and `strptime` rejects it. The free-text fields had no such floor, so they were
# the only place where a mis-located run could become a confident answer instead of an
# abstention -- and on real documents that is exactly what happened twice:
#
#   * UNC advice: the `Employee Name` box is redacted and holds an address. The run under
#     the label is "123 Franklin St", which is a perfectly good string and a very bad name.
#   * Federal LES / UTEP: pages of glossary whose left column is our label vocabulary and
#     whose right column is an English sentence. "A total of all earnings (current pay
#     period and any adjustments)" is a perfectly good string and a very bad pay frequency.
#
# Both are the same bug -- a field whose type was never stated -- and both are fixed by
# stating it. These are properties of the values themselves, not of those documents: a
# person's name does not contain digits, and a pay frequency is a word rather than a
# paragraph. Nothing here is a match against a document we have seen; a document that puts
# a real name under a name label still reads exactly as before.

#: Free-text fields, and the widest shape the value can honestly take. The word counts sit
#: comfortably above the widest value in the pack gold (name 2, address 7, frequency 1), so
#: they reject prose without narrowing anything we already read.
TEXT_FIELD_MAX_WORDS: dict[str, int] = {
    "person_name": 5,
    "address": 12,
    "pay_frequency": 2,
    "benefit_frequency": 2,
}

#: Fields whose value cannot contain a digit. A person is not a street number, an employee
#: id or a dollar amount, and every wrong reading of this field we have measured was one of
#: those three.
DIGITLESS_FIELDS = frozenset({"person_name", "pay_frequency", "benefit_frequency"})

#: The free-text fields, derived from the two tables above rather than listed again, so that
#: typing a new field enrols it automatically. These are exactly the fields whose parser is
#: a shape test rather than a type test, and therefore exactly the fields that need
#: `_caption_refusal` -- see the block above `_is_caption_cell`.
FREE_TEXT_FIELDS = frozenset(TEXT_FIELD_MAX_WORDS) | DIGITLESS_FIELDS


def _check_text_shape(field_name: str, raw: str) -> None:
    """Raise `ParseError` when a string cannot be this field's value. Type check, no more."""
    limit = TEXT_FIELD_MAX_WORDS.get(field_name)
    if limit is not None and len(raw.split()) > limit:
        raise ParseError(
            f"{len(raw.split())} words is prose, not a {field_name} (limit {limit}): {raw!r}"
        )
    if field_name in DIGITLESS_FIELDS and any(character.isdigit() for character in raw):
        raise ParseError(f"a {field_name} does not contain digits: {raw!r}")
    # Only asked of fields we have actually typed above; an unrecognised field name keeps
    # the old "any string will do" behaviour rather than acquiring a rule by accident.
    known_text_field = field_name in TEXT_FIELD_MAX_WORDS or field_name in DIGITLESS_FIELDS
    if known_text_field and not any(character.isalpha() for character in raw):
        raise ParseError(f"no letters in a {field_name}: {raw!r}")


# --------------------------------------------------------------------------------------
# Dates as they are actually printed
# --------------------------------------------------------------------------------------
# The pack writes every date ISO, so this parser accepted ISO and nothing else. No document
# outside the pack does that: the six published PDFs print 04/10/2015, 09-30-2014,
# 7/22/2010. Every one of them raised `ParseError` and abstained, which is why not a single
# date was read on any real document.
#
# The formats below are exactly the ones `eval/score_extraction.py` already documents as the
# repository's reading convention, including its stated caveat -- a slash date is read
# US-style, month first. That caveat is a *convention*, not a fact about the page, and
# 07/03 is a real date either way round, so this is the one place where widening the parser
# could produce a wrong value rather than an abstention. It is therefore marked: only ISO
# comes back `clean=True`. Everything else resolves to `certainty="low"` carrying the note
# below, so a reader can see which dates rest on a convention and which do not.
_ISO_DATE_FORMAT = "%Y-%m-%d"
_DATE_FORMATS = (
    _ISO_DATE_FORMAT,
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


def _parse_date(raw: str) -> tuple[str, bool]:
    """ISO date string plus a flag saying whether the input was already unambiguous."""
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        return parsed.isoformat(), fmt == _ISO_DATE_FORMAT
    raise ParseError(f"not a date in any format we read: {raw!r}")


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
        return _parse_date(raw)

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
        _check_text_shape(field_name, raw)
        token = raw.lower()
        return token, token in KNOWN_FREQUENCIES

    _check_text_shape(field_name, raw)
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

#: The same tolerance for fields `parse_value` type-checks -- dates, months, money, integers.
#:
#: 3.0pt is the pack's own printing tolerance, and on documents we did not draw it is too
#: tight: a real form sets a caption in one size and the value beneath it in another, and the
#: two left edges land several points apart without either being in the wrong column. Widening
#: it recovers those, and widening it also lets a run from the *neighbouring* column reach the
#: label -- so the question is what happens when it does.
#:
#: For a typed field, nothing: the neighbouring column's content has to parse as a date or an
#: amount before it can become a value, and `parse_value` refuses it if it does not. For a
#: free-text field there is no such refusal, and the cost was measured rather than reasoned
#: about -- raising the tolerance for every field adds a `person_name` false positive on
#: `orangeusd_sample_paystub.pdf`, a document in the confirmation set. So the raise is scoped
#: to exactly the fields that carry their own guard, and `FREE_TEXT_FIELDS` keeps 3.0.
TYPED_VALUE_X_TOLERANCE = 8.0


def _x_tolerance(field_name: str) -> float:
    """How far this field's value may sit from its label's edge. See the two constants above.

    An empty name -- a caller that has not said which field it is resolving -- gets the tight
    tolerance. The widening has to be asked for by naming a field that carries a parser.
    """
    if not field_name or field_name in FREE_TEXT_FIELDS:
        return VALUE_X_TOLERANCE
    return TYPED_VALUE_X_TOLERANCE

#: Side-by-side layouts put the value in a column to the right of the label, on the label's
#: own baseline. The gap that separates a *column* from the next *word of a sentence* is the
#: only thing telling those two apart, so it is measured rather than assumed: a word space at
#: these type sizes is 2-3pt, and the pack's own columns clear 60pt. Anything under this is
#: read as prose continuing the label, and we abstain.
SIDE_BY_SIDE_MIN_GAP = 12.0

_DOC_TYPE_RE = re.compile(r"^(hh-\d+)_(d\d+)_(.+)$", re.IGNORECASE)


def _arithmetic_enabled() -> bool:
    """Is the arithmetic-verification path switched on? ON by default; `0` switches it off.

    This flag shipped default-off while the path was unproven. It was promoted after the
    promotion measurement: with it on, the pack stays 159/159 exact with bbox IoU 159/159,
    the external six and the confirmation set both gain fields, label mapping on the 26
    uploads and the wording hold-out is bit-identical, and `wrong` is 0 in every corpus
    under all four flag combinations. `REALDOOR_ARITHMETIC=0` restores the old behaviour
    exactly -- with it set, `core.verified` is never imported.

    Read through a function rather than captured at import so that a test can flip the
    environment variable and see the change.
    """
    import os

    return os.environ.get("REALDOOR_ARITHMETIC", "").strip() != "0"


def _columns_enabled() -> bool:
    """Is the column-header path switched on? ON by default; `0` switches it off.

    Promoted from default-off alongside `REALDOOR_ARITHMETIC`, on the same measurement --
    see `_arithmetic_enabled`. `REALDOOR_COLUMNS=0` restores the old behaviour exactly:
    `core.columns` is never imported when the flag is off, so with it off this module's
    output is bit-identical to what it was before that file existed.
    """
    import os

    return os.environ.get("REALDOOR_COLUMNS", "").strip() != "0"


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


def _label_runs(
    line: Sequence[Word],
    document_type: str,
    field_mapper: FieldMapper,
) -> list[list[Word]]:
    """Label runs on one line, found two ways, in left-to-right order.

    **1. By typography.** `Word.is_label` -- small, bold, ALL-CAPS. This is the pack's own
    house style and it is what the gold was measured against, so it stays first and
    unchanged.

    **2. By vocabulary.** An ALL-CAPS run whose text is a label we already have in
    `LABEL_MAP` for this document type, at any size and any weight.

    Why the second path exists: `LABEL_SIZE_RANGE` is an absolute window fitted to one
    generator's 8pt bold labels. Measured against documents that differ *only* in label
    typography, it was the sole point of failure -- 10pt bold, 9pt bold and 7.5pt regular
    labels each scored 0, while the 8.4pt control scored 9/9. The layout, the wording and
    the values were identical. That is a brittle reason to read nothing.

    Why it relaxes on vocabulary rather than on size: a looser size window admits new
    *strings* as labels, which is how an extractor starts producing values it should not
    have. This admits no new strings at all. It only stops insisting that a phrase we
    already recognise be set in the type size the pack happens to use. A run still has to
    match a known label exactly, still has to have a value in the column beneath it, and
    that value still has to parse -- so this cannot turn an abstention into a wrong answer,
    only into a right one or another abstention.

    Note `text.upper() == text` is true of every date and every amount, since digits have
    no case. The vocabulary test is what keeps those out: "2026-07-03" matches no label.

    **Why the ALL-CAPS test is gone from path 2.** It used to read
    `w.text.upper() == w.text`, and it did no work that the vocabulary test was not already
    doing better. What it *did* do was throw away every Title Case label -- `Net Pay`,
    `Employee Name`, `Pay Begin Date` -- which is how real documents are typeset. Measured
    across six published PDFs, label detection fired twice in total. Comparison is now
    case-normalised (`normalize_label` upper-cases), so `Net Pay` is tested against the
    tables as `NET PAY`.

    This admits **no new strings**. The set of runs offered to the mapper grew, but the set
    the mapper *accepts* is the same closed table it always was, compared case-insensitively.
    A run still has to match a known label exactly, still has to have a value in its column,
    and that value still has to parse as the field's type -- so the original argument holds
    unchanged: this can turn an abstention into a right answer or into another abstention,
    never into a wrong one. What it *can* do is let a known label sit next to a value we
    would not previously have looked at, and that is the risk the type guards in
    `parse_value` and the alignment measurement in `_resolve_value` exist to carry.

    Path 1 (typography) is deliberately left exactly as it was. Relaxing its size/weight
    window would admit new *strings* as labels -- runs nothing in the vocabulary recognises,
    which still act as column boundaries and as ownership anchors for `_caption_value`, and
    so can move values that resolve correctly today. Path 2 already recovers every label we
    actually know at any size and any weight, so relaxing path 1 buys nothing we do not
    already have and costs the one guarantee worth keeping.
    """
    typographic = _split_runs([w for w in line if w.is_label()])

    rest = [w for w in line if not w.is_label()]
    recovered = [
        run
        for run in _split_runs(rest)
        if looks_like_a_label(_join_run(run))
        and field_mapper(document_type, _join_run(run)) is not None
    ]

    runs = typographic + recovered
    runs.sort(key=lambda run: run[0].x0)
    return runs


def _scan_page(
    lines: Sequence[Sequence[Word]],
    document_type: str,
    convention: LineBoxConvention,
    field_mapper: FieldMapper,
    found: dict[str, dict[str, Any]],
    is_exact: bool,
) -> list[str]:
    """One pass of label-anchored extraction. Fills `found` in place, returns unmapped."""
    unmapped: list[str] = []
    anchors, label_words = _label_anchors(lines, document_type, field_mapper)
    # Computed once per page: the page's own column-header rows. See `_caption_refusal`.
    header_words = _header_row_words(lines)
    for line in lines:
        label_runs = _label_runs(line, document_type, field_mapper)
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
                lines, run, column_right, field_name, convention, is_exact, label_words,
                header_words,
            )
            # The column beneath the label is the pack's own layout and stays first. Only
            # when it yields *nothing at all* do the two other placements get a turn, and
            # each has to prove itself unambiguous on its own terms -- see `_side_by_side_value`
            # and `_caption_value`. A label whose column value was found but did not parse
            # returns an abstention, not None, and that abstention stands: we do not go
            # hunting elsewhere on the page for a value we have already located and rejected.
            if resolved is None:
                resolved = _side_by_side_value(
                    line, label_runs, index, column_right, field_name, convention, is_exact,
                    header_words,
                )
            if resolved is None:
                resolved = _caption_value(
                    lines, anchors, run, column_right, field_name, convention, is_exact,
                    label_words, header_words,
                )
            # ------------------------------------------------------------------------
            # Column headers (on by default, `REALDOOR_COLUMNS=0` to disable) -- see
            # `core/columns.py`
            # ------------------------------------------------------------------------
            # Last, and only when the three rules above produced **no value**. "No value"
            # includes an abstention, because `_resolve_value` records a run it located and
            # then refused as an abstention rather than leaving the field out -- ADP's
            # `Gross Pay` is exactly that, the run beneath the label being the word
            # "Statutory". Replacing an abstention changes no answer.
            #
            # Placing it here is the whole safety argument, and it is structural rather
            # than a matter of how careful the new code is: there is no path by which this
            # branch can replace, move or re-box a value one of the earlier rules found.
            # It turns abstentions into values, or it does nothing.
            if _columns_enabled() and (
                resolved is None or resolved.get("certainty") == "abstain"
            ):
                from core import columns

                recovered = columns.column_value(
                    lines, run, column_right, field_name, convention, is_exact, label_words,
                    header_words,
                )
                if recovered is not None:
                    resolved = recovered
            if resolved is not None:
                found[field_name] = resolved
    return unmapped


def _label_anchors(
    lines: Sequence[Sequence[Word]],
    document_type: str,
    field_mapper: FieldMapper,
) -> tuple[list[tuple[float, float]], frozenset[int]]:
    """(baseline, x0) of every label run on the page, plus the id of every label word.

    The anchors answer one question -- "is this run of words already spoken for by a label
    sitting above it?" -- so they deliberately include labels we cannot map. An unmappable
    label still owns the value underneath it, and that ownership is what blocks the caption
    rule from stealing it.

    The word ids answer the mirror question -- "is this run of words itself a label?" -- for
    `_runs_in_window`, and include unmappable labels for the same reason.
    """
    anchors: list[tuple[float, float]] = []
    words: set[int] = set()
    for line in lines:
        for run in _label_runs(line, document_type, field_mapper):
            anchors.append((run[0].baseline, run[0].x0))
            words.update(id(w) for w in run)
    return anchors, frozenset(words)


def extract_fields_from_page(
    words: Sequence[Word],
    document_type: str,
    convention: LineBoxConvention,
    field_mapper: FieldMapper = deterministic_mapper,
    fallback_mapper: FieldMapper | None = synonym_mapper,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Label-anchored extraction for one page.

    Returns (fields keyed by name, labels neither mapper could map).

    Two passes, and the order is the whole safety argument. The first pass uses
    `field_mapper` -- the pack's own exact vocabulary -- and is byte-for-byte the pass
    this function has always made. The second pass runs `fallback_mapper` over the same
    lines and may only fill fields the first pass **left empty**, because `found` carries
    over and `field_name in found` short-circuits. A canonical label therefore always
    beats a synonym no matter where the two sit on the page, so no field that resolves
    today can be re-resolved to a different value tomorrow.

    Everything the second pass does after naming a field is the unchanged code path: the
    value must still sit in the column directly beneath the label, still within
    `VALUE_Y_WINDOW`, still left-aligned to `VALUE_X_TOLERANCE`, and still parse as the
    type the field requires. Widening the vocabulary moves no box and relaxes no geometry.

    Pass 2 results carry `is_exact=False`, so they land at `certainty="low"` with the note
    "label resolved by a non-exact mapper" -- a reader can see which fields were recovered
    this way and which came from the pack's own words. Pass `fallback_mapper=None` to turn
    the second pass off entirely and get the original behaviour for comparison.
    """
    lines = group_lines(words)
    found: dict[str, dict[str, Any]] = {}

    unmapped = _scan_page(
        lines, document_type, convention, field_mapper, found, is_exact=True
    )
    if fallback_mapper is not None:
        tracker = fallback_mapper if isinstance(fallback_mapper, _TrackingMapper) else None
        # Provenance is credited per stage, not at the end. `tracker.from_model` records
        # every field the model *named*, and once the model runs as its own pass over the
        # whole page that includes fields the synonym pass had already filled -- crediting
        # those to the model would overstate what it did, which is the one thing this
        # bookkeeping exists to prevent.
        model_named: set[str] = set()
        for stage in _mapper_stages(fallback_mapper):
            before_stage = set(found)
            unmapped = _scan_page(
                lines, document_type, convention, stage, found, is_exact=False
            )
            if tracker is not None and stage is tracker.model_leg:
                model_named |= set(found) - before_stage
        if tracker is not None:
            _retag_model_provenance(found, model_named, tracker.from_model)

    # ----------------------------------------------------------------------------------
    # Two-axis table cells (part of the column path: `REALDOOR_COLUMNS=0` disables it)
    # ----------------------------------------------------------------------------------
    # Last of all, and only for fields every label pass left with **no value** -- absent,
    # or recorded as an abstention. This is the same abstention-only gate the header-column
    # branch in `_scan_page` uses, applied at the page level because the fields this rule
    # reads have no label anywhere on the page to anchor a `_scan_page` visit: an earnings
    # matrix names `regular_hours` by crossing a `Regular` row with an `Hours` header
    # rather than by printing a label. Placing it after every mapper pass is structural
    # safety, not politeness -- a field any label (canonical, synonym or model-named) can
    # reach is decided by that label before this rule is allowed to look, so there is no
    # path by which a table cell can replace, move or re-box a label-anchored value.
    # See `core.columns.table_cell_value` for the rule and its refusals.
    if _columns_enabled():
        from core import columns

        for name in EXPECTED_FIELDS.get(document_type, ()):
            existing = found.get(name)
            if existing is not None and existing.get("certainty") != "abstain":
                continue
            recovered = columns.table_cell_value(lines, name, convention)
            if recovered is not None:
                found[name] = recovered
    return found, unmapped


def _mapper_stages(fallback_mapper: FieldMapper) -> list[FieldMapper]:
    """Split a layered mapper into separate passes: frozen tables first, model last.

    `layered_mapper` consults the tables before the model *for one label*, which is a cost
    argument. It is not a precedence argument, and the difference showed up as soon as label
    detection stopped requiring ALL-CAPS. Inside a single pass, `found` fills in page order
    and first occurrence wins, so a label the model named near the top of the page took a
    field that a *synonym* would have named correctly further down. Measured: the model
    column of `scripts/measure_label_mapping.py` fell from 134 to 131 on the 26 existing
    documents and from 26 to 24 on the wording hold-out, while the deterministic column --
    which has no model in it -- did not move at all.

    Running them as two passes over the same page makes the precedence explicit and matches
    the ordering the rest of this module already promises: **everything the frozen tables can
    name is named by them, on every machine, before the model is allowed to name anything.**
    A field the tables can fill is therefore never displaced by one the model guessed, and
    turning the model off can only ever remove fields, never change them.
    """
    if isinstance(fallback_mapper, _TrackingMapper):
        return [synonym_mapper, fallback_mapper.model_leg]
    if fallback_mapper is layered_mapper:
        return [synonym_mapper, model_mapper]
    return [fallback_mapper]


def _retag_model_provenance(
    found: dict[str, dict[str, Any]],
    newly_found: set[str],
    named_by_model: set[str],
) -> None:
    """Rewrite the note on fields the *model* named, leaving synonym-named ones alone.

    Only the note changes. The value, the box, the page and the certainty were all decided
    by the unchanged geometry before this runs, so this cannot turn an abstention into an
    answer or move a number -- it only records which of the two non-exact paths got there.
    """
    for name in newly_found & named_by_model:
        field = found.get(name)
        if not field:
            continue
        note = field.get("notes")
        field["notes"] = (
            note.replace(SYNONYM_NOTE, MODEL_MAPPER_NOTE)
            if note and SYNONYM_NOTE in note
            else " | ".join(filter(None, [note, MODEL_MAPPER_NOTE]))
        )


# --------------------------------------------------------------------------------------
# Which edge of a column is the column (rule: measure it, do not assume it)
# --------------------------------------------------------------------------------------
# The alignment test used to read one number: `abs(run.x0 - label.x0) <= 3`. That is the
# right test for a left-aligned text column and the wrong test for a right-aligned number
# column, where **x0 is a function of how many digits the number has**. Measured on the UNC
# advice, under the `NET PAY` label at x0=571.6:
#
#     1,040.23    x0=577.7  ->  |6.1| > 3  rejected   <- the current-period net pay, correct
#     18,396.25   x0=574.2  ->  |2.6| <= 3 accepted   <- the year-to-date figure, wrong
#
# The longer number won because it was longer. Both runs end at x1=602.2: the column is
# right-aligned, and its right edge is the only edge that means anything.
#
# So the edge is measured rather than assumed, per column, from the runs themselves: if the
# runs stacked in a column agree with each other on x1 more than they agree on x0, and the
# label agrees with them on x1 too, the column is right-aligned. Failing a clear reading we
# say so ("unknown") and accept either edge, which is what the pack's own single-value
# columns do -- so the pack's behaviour is bit-for-bit what it was.


def _cluster_size(values: Sequence[float], tolerance: float) -> int:
    """Size of the largest group of values that agree to within `tolerance`."""
    return max(
        (sum(abs(other - anchor) <= tolerance for other in values) for anchor in values),
        default=0,
    )


def _column_alignment(
    runs: Sequence[Sequence[Word]],
    label_x0: float,
    label_x1: float,
    tolerance: float = VALUE_X_TOLERANCE,
) -> str:
    """"left", "right" or "unknown", read off the runs stacked in one column.

    Deliberately conservative in both directions. A verdict of "right" requires two things
    to agree -- the runs share x1 more than they share x0, *and* the label's own right edge
    sits on that shared edge. One of them alone is a coincidence; a column whose values line
    up on the right but nowhere near the label is not this label's column. Anything less
    than a clear reading is "unknown", which accepts either edge and therefore cannot reject
    a value the old code would have found.
    """
    if len(runs) < 2:
        return "unknown"
    left = _cluster_size([run[0].x0 for run in runs], tolerance)
    right = _cluster_size([max(w.x1 for w in run) for run in runs], tolerance)
    if right > left and any(
        abs(max(w.x1 for w in run) - label_x1) <= tolerance for run in runs
    ):
        return "right"
    if left > right and any(abs(run[0].x0 - label_x0) <= tolerance for run in runs):
        return "left"
    return "unknown"


def _aligned_with_label(
    run: Sequence[Word],
    label_x0: float,
    label_x1: float,
    alignment: str,
    tolerance: float = VALUE_X_TOLERANCE,
) -> bool:
    """Does this run sit in the label's column, under the measured alignment?"""
    if alignment != "right" and abs(run[0].x0 - label_x0) <= tolerance:
        return True
    if alignment != "left" and abs(max(w.x1 for w in run) - label_x1) <= tolerance:
        return True
    return False


# --------------------------------------------------------------------------------------
# A caption is a label, wherever our vocabulary happens to stop
# --------------------------------------------------------------------------------------
# "A label is never a value" is the rule `_runs_in_window` enforces, and it is the property
# this extractor's zero-wrong claim rests on. It protects only *recognised* labels. A run
# that names a field we have no word for is invisible as a label, and therefore readable as
# a value -- and the free-text fields have no parser that can refuse it. Measured on the
# confirmation set, that one hole produced every wrong value on the whole set:
#
#   * `osu_sample_earnings_statement.pdf` p2 -- the canonical label `EMPLOYEE` matched the
#     header cell "Employee" in `Deduction Code | Description | Employee | Employer`, and
#     the one run to its right is the *next column's header*. person_name = "Employer",
#     certainty **high**.
#   * `seattle_housing_employment_verification_blank.pdf` -- "Employee Name:" with an empty
#     fill-in; the next caption on the row, "Job Title:", read as the name.
#   * `mnhousing_employment_verification_blank.pdf` -- "Employee Name:" with the next
#     question's caption, "Presently Employed:", sitting 21.6pt below inside
#     `VALUE_Y_WINDOW`.
#
# The two tests below are deliberately not a vocabulary. Neither one knows what "Employer"
# or "Job Title" mean; both read something the document itself printed:
#
#   1. **The colon.** A run ending in ':' is punctuated by its author as an introduction to
#      something else. No name, address or frequency word is ever printed with one.
#   2. **The header row.** A line whose every run is a short, digit-free caption, three or
#      more of them across the line, is a row that names columns. Its cells are captions by
#      the page's own structure -- the thing that makes it a header row is that it holds no
#      data at all. Nothing on such a line is a value, including the cell we happened to
#      recognise and the cell beside it.
#
# Scope is deliberate: this applies only to `FREE_TEXT_FIELDS`. Every other field is already
# protected by `parse_value` -- "Employer" is not money and "Job Title:" is not a date -- so
# extending the refusal there would be a rule doing no work, and a rule doing no work is a
# rule whose cost nobody can measure.

#: How many cells make a line a header row rather than a label sitting beside its value. A
#: two-cell line is the commonest layout on any form -- caption, then the value -- so two is
#: exactly the count that must NOT qualify. Three captions in a row, and the line is naming
#: columns.
MIN_HEADER_ROW_CELLS = 3


def _is_caption_cell(run: Sequence[Word]) -> bool:
    """Is this run shaped like the name of something, rather than like a value?

    Same three properties `looks_like_a_label` tests, for the same reason -- it has a
    letter, it is short, it is not a number. A digit anywhere disqualifies it, which is what
    keeps a row of amounts or dates from being mistaken for the row that names them.
    """
    text = _join_run(run)
    if any(character.isdigit() for character in text):
        return False
    return looks_like_a_label(text)


def _header_row_words(lines: Sequence[Sequence[Word]]) -> frozenset[int]:
    """Every word on this page that sits in a row of three or more captions.

    Computed once per page and threaded like `label_words`, because the question it answers
    -- "is this run one of the page's own column headings?" -- is a property of the page and
    not of the label being resolved.
    """
    out: set[int] = set()
    for line in lines:
        runs = _split_runs(line)
        if len(runs) < MIN_HEADER_ROW_CELLS:
            continue
        if all(_is_caption_cell(run) for run in runs):
            out.update(id(word) for run in runs for word in run)
    return frozenset(out)


def _caption_refusal(
    field_name: str, run: Sequence[Word], header_words: frozenset[int]
) -> str | None:
    """Why this run cannot be this field's value, or None if nothing objects.

    Returns a reason string rather than a bool so the refusal can be said out loud in a
    note if a caller ever wants to, and so the two tests never collapse into one opaque
    predicate.
    """
    if field_name not in FREE_TEXT_FIELDS:
        return None
    text = _join_run(run).strip()
    if text.endswith(":"):
        return "the page punctuates this run as a caption (it ends in a colon)"
    if run and all(id(word) in header_words for word in run):
        return "this run is a cell in one of the page's own column-header rows"
    return None


def _first_caption_run(
    runs: Sequence[Sequence[Word]], header_words: frozenset[int]
) -> float | None:
    """x0 of the leftmost caption-shaped run, or None if there is not one.

    Asked with no field name, so it applies the two caption tests on their own terms -- this
    is a question about the page ("where does this cell end?"), not about a field. It reads
    the same two properties `_caption_refusal` reads, which is the point: one idea of what a
    caption is, used both to refuse one as a value and to let one bound a cell.
    """
    for run in runs:
        text = _join_run(run).strip()
        if text.endswith(":") or (run and all(id(word) in header_words for word in run)):
            return run[0].x0
    return None


def _runs_in_window(
    lines: Sequence[Sequence[Word]],
    label_x0: float,
    label_baseline: float,
    column_right: float,
    above: bool = False,
    label_words: frozenset[int] = frozenset(),
    field_name: str = "",
    header_words: frozenset[int] = frozenset(),
) -> list[list[Word]]:
    """Every run inside the label's column and vertical window, with no alignment test.

    This is the honest denominator for `certainty`. The old code counted candidates only
    *after* the alignment filter had already thrown some away, so a label with two numbers
    under it could report `high` on the strength of having exactly one survivor -- the
    competition had been deleted before it was counted. See `_resolve_value`.

    `label_words` carries every word on the page that belongs to some label run, and a run
    made entirely of those is skipped. **A label is never a value.** On a stacked form the
    line below `Period Beginning` is `Period Ending`, and reading it as the value produced a
    located-but-unparseable result, which under the rule in `_scan_page` is an abstention
    that stands -- so the real value, sitting to the right on the label's own line, was never
    looked for. Skipping label runs here does not admit them anywhere else: they remain
    labels, they still bound columns, and they still shield their own values from
    `_caption_value`.

    A run refused by `_caption_refusal` is dropped here for the same reason and with the
    same consequences: an unrecognised caption is a label we have no word for, so it is not
    a candidate, it does not count towards `contested`, and it cannot win by being the only
    thing in the window. It is dropped rather than merely out-ranked because a caption is
    never the right answer -- picking the runner-up instead would be choosing between two
    readings, which this module does not do.
    """
    near, far = VALUE_Y_WINDOW
    tolerance = _x_tolerance(field_name)
    out: list[list[Word]] = []
    for line in lines:
        delta = (line[0].baseline - label_baseline) if above else (label_baseline - line[0].baseline)
        if not (near <= delta <= far):
            continue
        in_column = [
            w
            for w in line
            if w.x0 >= label_x0 - tolerance and w.x0 < column_right - tolerance
        ]
        if in_column:
            out.extend(
                run
                for run in _split_runs(in_column)
                if not all(id(w) in label_words for w in run)
                and _caption_refusal(field_name, run, header_words) is None
            )
    return out


def _resolve_value(
    lines: Sequence[Sequence[Word]],
    label_run: Sequence[Word],
    column_right: float,
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
    label_words: frozenset[int] = frozenset(),
    header_words: frozenset[int] = frozenset(),
) -> dict[str, Any] | None:
    """Find the value belonging to one label, or return None so the caller abstains."""
    label_x0 = label_run[0].x0
    label_x1 = max(w.x1 for w in label_run)
    label_baseline = label_run[0].baseline

    in_window = _runs_in_window(
        lines, label_x0, label_baseline, column_right, label_words=label_words,
        field_name=field_name, header_words=header_words,
    )
    tolerance = _x_tolerance(field_name)
    alignment = _column_alignment(in_window, label_x0, label_x1, tolerance)
    candidates = [
        run
        for run in in_window
        if _aligned_with_label(run, label_x0, label_x1, alignment, tolerance)
    ]

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

    # `len(in_window)`, not `len(candidates)`: a value that only won because the alignment
    # test removed its rivals was never unambiguous, and saying "high" about it is the one
    # failure mode that is worse than being wrong -- being wrong *and* confident.
    contested = len(in_window) > 1
    unambiguous = clean and is_exact and len(candidates) == 1 and not contested
    notes = None
    if not unambiguous:
        parts = []
        if not is_exact:
            parts.append("label resolved by a non-exact mapper")
        if contested:
            parts.append(
                f"{len(in_window)} candidate value runs sat in this label's column "
                f"({len(candidates)} aligned with it; column read as {alignment}-aligned)"
            )
        if not clean:
            parts.append("value did not match the expected format for this field")
        notes = " | ".join(parts) or "value did not match the expected format for this field"

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
# Two other places a value is allowed to sit (rule CH-SAFETY-001 still holds)
# --------------------------------------------------------------------------------------
# The column-beneath-the-label rule above is the pack's own visual grammar, and against
# documents that differ from the pack *only* in where the value sits it recovered 0 of 22
# fields. Every label was recognised; there was simply nothing underneath it.
#
# Widening the geometry is a different kind of change from widening the vocabulary, and
# more dangerous. A vocabulary miss abstains. A geometry miss can read the *wrong cell* --
# find "GROSS PAY", look right, and pick up the neighbouring column's number. That failure
# produces a confident wrong figure where the old code produced an honest blank, and one
# wrong figure costs more than twenty abstentions.
#
# So each rule below fires only when its layout is unambiguous *by measurement*, and every
# test is a refusal: more than one candidate, another label in the way, a gap too small to
# be a column, a value already owned by another label -- any one of them and we abstain
# exactly as before. Neither rule ever chooses between two candidates. That is the whole
# safety argument, and it is why the earnings-TABLE layout is deliberately left unsolved:
# see `_side_by_side_value` for what a table row does to these tests.


def _build_value_field(
    run: Sequence[Word],
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
    layout_note: str,
    header_words: frozenset[int] = frozenset(),
) -> dict[str, Any] | None:
    """Turn a located run into a field, or None if it does not parse as this field's type.

    Returning None rather than an abstention matters: these rules are speculative, so a run
    that fails to parse is evidence the geometry guess was wrong, and the caller should fall
    through to the next rule (and ultimately to the ordinary "no label found" abstention)
    rather than record this run as the located-but-unreadable value.

    `_caption_refusal` is checked here, before `parse_value`, and returns None for the same
    reason: a caption is evidence the geometry guess landed on the next field's name rather
    than on this field's value. Every speculative rule -- side-by-side, caption-above, and
    the opt-in column reader -- passes through this function, so stating the refusal once
    here covers all three.
    """
    if _caption_refusal(field_name, run, header_words) is not None:
        return None
    source_text = _join_run(run)
    try:
        value, clean = parse_value(field_name, source_text)
    except ParseError:
        return None
    notes = layout_note
    if not is_exact:
        notes += " | label resolved by a non-exact mapper"
    if not clean:
        notes += " | value did not match the expected format for this field"
    return _extracted_field(
        field_name,
        value,
        run[0].page,
        _run_box(run, convention),
        "high" if (clean and is_exact) else "low",
        source_text,
        notes,
    )


def _side_by_side_value(
    line: Sequence[Word],
    label_runs: Sequence[Sequence[Word]],
    index: int,
    column_right: float,
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
    header_words: frozenset[int] = frozenset(),
) -> dict[str, Any] | None:
    """Value on the label's own baseline, in a column to its right.

    This is the most common pay stub layout in existence, and it is the one the pack does
    not use. Three measurements have to agree before we read anything:

    **One candidate.** The words between this label and the next label on the row must form
    exactly one run. Two runs means two things sit in the cell and we cannot say which is
    the value, so we abstain.

    **No label in the way.** `column_right` is the next label's x0, so a table header row
    (`EMPLOYEE | PAY DATE | REGULAR HOURS | ...`) leaves an empty span between neighbouring
    headers and produces no candidate at all. This is the test that keeps the earnings-table
    layout abstaining rather than pairing a header with whatever number is nearest.

    **A column gap, not a word space.** The gap between the end of the label and the start of
    the run must clear `SIDE_BY_SIDE_MIN_GAP`. Without it, prose that happens to open with a
    known label ("PAY DATE has not been assigned yet") reads as a label-value pair and the
    trailing words become the value. Free-text fields such as `person_name` and `address`
    accept any string, so parsing would not catch it -- only the geometry can.

    **An unrecognised caption closes the cell.** `column_right` is the next *recognised*
    label's x0, so a caption we have no word for does not bound anything, and everything past
    it stays in the cell -- which makes the cell look like it holds two things, and we abstain.
    The UNC advice is exactly that: `Pay Begin Date  07/10/2017  Advice #: 0000123456` reads as
    two runs in one cell because "Advice #:" is not in either table. `_caption_refusal`'s two
    tests already say what a caption is without needing a word for it, so the same reading that
    stops a caption becoming a value also lets it act as the boundary it visually is.

    That is a change to this rule's semantics rather than a consequence of the refusal, so it
    was measured on its own: across the pack, the 26 uploads, the wording hold-out, the
    external six and the confirmation 14, under both flag settings, it moves exactly one field
    -- UNC's `pay_period_start`, from an abstention to 2017-07-10, which is what the page
    prints and what `testdata/external_truth.json` records. It can only ever *narrow* the cell,
    so like every other test here it turns readings into abstentions or abstentions into
    readings, never one value into another.
    """
    label_run = label_runs[index]
    label_end = max(w.x1 for w in label_run)
    label_words = {id(w) for run in label_runs for w in run}

    right = [
        w
        for w in line
        if w.x0 >= label_end and w.x0 < column_right - _x_tolerance(field_name)
        and id(w) not in label_words
    ]
    if not right:
        return None

    runs = _split_runs(right)
    barrier = _first_caption_run(runs, header_words)
    if barrier is not None:
        runs = [run for run in runs if run[0].x0 < barrier]
    if len(runs) != 1:
        return None

    run = runs[0]
    if run[0].x0 - label_end < SIDE_BY_SIDE_MIN_GAP:
        return None

    return _build_value_field(
        run, field_name, convention, is_exact,
        "value read from the same line as its label, in the column to its right",
        header_words=header_words,
    )


def _caption_value(
    lines: Sequence[Sequence[Word]],
    label_anchors: Sequence[tuple[float, float]],
    label_run: Sequence[Word],
    column_right: float,
    field_name: str,
    convention: LineBoxConvention,
    is_exact: bool,
    label_words: frozenset[int] = frozenset(),
    header_words: frozenset[int] = frozenset(),
) -> dict[str, Any] | None:
    """Value *above* its label, with the label used as a caption underneath it.

    Looking upward is the most dangerous thing in this module, because in an ordinary
    top-down form the line above a label is the *previous* label's value. Reading it would
    shift every field up by one row and report a whole page of confident wrong answers --
    the exact failure this codebase exists to avoid.

    What makes it safe is the ownership test. A value in a top-down form has its own label
    sitting directly above it, inside the same `VALUE_Y_WINDOW` and left-aligned to the same
    tolerance. A caption layout's value has nothing above it at all. So before reading a run
    that sits above a label, we ask whether some other label already owns it, and if anything
    does, we abstain. In a top-down form that test fails for every row, and the rule never
    fires. `_label_anchors` deliberately counts labels we could not map, so an unrecognised
    label still shields its own value.

    The remaining tests match `_resolve_value`: the run must be left-aligned with the label,
    inside the label's column, and it must be the only candidate.
    """
    label_x0 = label_run[0].x0
    label_x1 = max(w.x1 for w in label_run)
    label_baseline = label_run[0].baseline

    in_window = _runs_in_window(
        lines, label_x0, label_baseline, column_right, above=True, label_words=label_words,
        field_name=field_name, header_words=header_words,
    )
    tolerance = _x_tolerance(field_name)
    alignment = _column_alignment(in_window, label_x0, label_x1, tolerance)
    candidates = [
        run
        for run in in_window
        if _aligned_with_label(run, label_x0, label_x1, alignment, tolerance)
    ]

    # Unchanged, and stricter than `_resolve_value` on purpose: looking upward is only ever
    # allowed when the layout leaves exactly one reading. Counting `in_window` here as well
    # means a caption rule that had rivals removed by the alignment test does not fire at all.
    if len(candidates) != 1 or len(in_window) != 1:
        return None

    run = candidates[0]
    if _claimed_from_above(label_anchors, run):
        return None

    return _build_value_field(
        run, field_name, convention, is_exact,
        "value read from the line above its label, which is used as a caption beneath it",
        header_words=header_words,
    )


def _claimed_from_above(
    label_anchors: Sequence[tuple[float, float]], run: Sequence[Word]
) -> bool:
    """Does some label sit directly above this run, in the position that would own it?

    Same window and same alignment tolerance as `_resolve_value`, because this is asking the
    inverse of the question `_resolve_value` asks. If the answer is yes, the run is another
    field's value and the caption rule must not touch it.

    Deliberately left at the tight `VALUE_X_TOLERANCE` rather than following the field's own
    `_x_tolerance`. This is not asking "could this be my value?" but "is this already someone
    else's?", and the two do not want the same number. Widening it would shield *more* runs
    and so only ever produce more abstentions -- but it is also not what any measurement
    asked for, and an unmeasured change to the ownership test is exactly the kind of quiet
    move that shifts a whole form up by one row. It stays where it was.
    """
    near, far = VALUE_Y_WINDOW
    x0 = run[0].x0
    baseline = run[0].baseline
    return any(
        near <= (anchor_baseline - baseline) <= far and abs(anchor_x0 - x0) <= VALUE_X_TOLERANCE
        for anchor_baseline, anchor_x0 in label_anchors
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
    pdf_path: str | Path | bytes,
    document_type: str | None = None,
    field_mapper: FieldMapper = deterministic_mapper,
    fallback_mapper: FieldMapper | None = synonym_mapper,
    convention: LineBoxConvention = LineBoxConvention(),
    reference_date: date = REFERENCE_DATE,
    window_days: int = CURRENCY_WINDOW_DAYS,
    expiring_soon_days: int | None = DEFAULT_EXPIRING_SOON_DAYS,
    file_name: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Turn a PDF into a `DocumentView` (CONTRACTS.md section 3). Pure and deterministic.

    Same bytes in, same JSON out, on any machine, with no network and no model.

    `pdf_path` may be raw bytes, for a document that exists only in memory (an upload).
    In that case there is no file name to read a type or an id out of, so `document_type`
    and `document_id` must be supplied by the caller -- see `infer_document_type`, which
    answers "unknown" for anything not named the way the pack names its files.
    """
    in_memory = isinstance(pdf_path, (bytes, bytearray))
    if in_memory:
        source: Any = io.BytesIO(bytes(pdf_path))
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

    with pdfplumber.open(source) as pdf:
        page_sizes = [(round(float(p.width), 2), round(float(p.height), 2)) for p in pdf.pages]
        page_count = len(pdf.pages)
        all_words: list[Word] = []
        words_by_page: list[list[Word]] = []
        found: dict[str, dict[str, Any]] = {}
        for page_number, page in enumerate(pdf.pages, start=1):
            words = read_words(page, page_number)
            all_words.extend(words)
            words_by_page.append(words)
            page_fields, _ = extract_fields_from_page(
                words, doc_type, convention, field_mapper, fallback_mapper
            )
            for name, value in page_fields.items():
                found.setdefault(name, value)

    # ----------------------------------------------------------------------------------
    # Arithmetic verification (on by default, `REALDOOR_ARITHMETIC=0` to disable)
    # ----------------------------------------------------------------------------------
    # Runs AFTER the label-anchored passes and may only fill fields they left empty. It runs
    # after rather than before because its physical bound is derived from values the label
    # path has already read: the pay period is what tells 74.50 hours from a year-to-date
    # 28,707.21.
    #
    # With the flag off, nothing below this line executes and `core.verified` is not even
    # imported, so this function's output is bit-identical to what it was before.
    if _arithmetic_enabled():
        from core import verified

        # "Blank" means no answer, which includes a field the label path *located* and then
        # refused -- `_resolve_value` records those in `found` as abstentions rather than
        # leaving them out. ADP is exactly that case: `Gross Pay` is found as a label, the run
        # beneath it is not money, and the abstention that follows is what used to sit here.
        # Replacing an abstention changes no answer, so this still only ever fills blanks.
        def _blank(name: str) -> bool:
            existing = found.get(name)
            return existing is None or existing.get("certainty") == "abstain"

        wanted = [
            name
            for name in EXPECTED_FIELDS.get(doc_type, ())
            if name in verified.VERIFIABLE_FIELDS and _blank(name)
        ]
        if wanted:
            all_proposals: list[dict[str, dict[str, Any]]] = []
            for words in words_by_page:
                answers, proposals = verified.verify_page(
                    words, doc_type, found, convention, wanted
                )
                for name, value in answers.items():
                    if _blank(name):
                        found[name] = value
                all_proposals.append(proposals)
            # Every page's answers before any page's proposal -- see `verify_page`.
            for proposals in all_proposals:
                for name, value in proposals.items():
                    if _blank(name):
                        found[name] = value

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
        "document_id": resolved_id,
        "household_id": household_id,
        "document_type": doc_type,
        "file_name": display_name,
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
