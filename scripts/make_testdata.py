"""Generate synthetic upload-test documents plus their ground-truth manifest.

WHY THIS EXISTS
---------------
`pack/synthetic_documents/` is the organiser's fixture set. Re-uploading those 24 files
proves nothing about the upload path: they are the documents the extractor was built
against, and their gold labels are already baked into every score we quote. To claim the
upload path *works* we need documents the extractor has never seen, and we need to know
what is in them before we look at what came out.

So this script does two things at once, and the second is the point:

  1. renders PDFs whose visual grammar matches the pack (7.5pt bold ALL-CAPS label, value
     10pt regular on the line ~15pt below, left-aligned to the label's x, plus a >=20pt
     diagonal watermark that `core.extract` filters out by size), and
  2. writes `testdata/uploads_manifest.json` -- the ground truth -- so upload accuracy is
     a **measurement** and not a claim.

EDGE CASES ARE THE PRODUCT
--------------------------
An easy corpus would flatter us. Every document here that is not marked `clean` exists to
push one specific behaviour: month-precision dates (-> `undatable`), dates outside the
frozen 60-day window (-> `expired`), hours * rate that does not equal the stated gross,
image-only pages (-> the OCR path), an unreadable page (-> abstention), and a document
type the label table has never heard of.

NAMES AND ADDRESSES
-------------------
Every person is an obvious placeholder (John Doe / Jane Roe / Sam Poe). Every employer,
agency and platform is invented. Street numbers are deliberately out of range for the
named city/ZIP so no line resolves to a real address. No SSNs appear in any form.

Usage:  python scripts/make_testdata.py
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import fitz
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "testdata" / "uploads"
MANIFEST = ROOT / "testdata" / "uploads_manifest.json"

PAGE_W, PAGE_H = 612.0, 792.0

# --- the pack's visual grammar, measured off pack/synthetic_documents/*.pdf -------------
LABEL_SIZE = 7.5  # inside core.extract LABEL_SIZE_RANGE (7.5, 8.5); must be bold + CAPS
VALUE_SIZE = 10.0
VALUE_DROP = 15.0  # baseline gap label -> value; core's VALUE_Y_WINDOW is (6.0, 22.0)
ROW_PITCH = 60.0
WATERMARK = "SYNTHETIC - NOT A REAL DOCUMENT"
WATERMARK_SIZE = 28.0  # >= core.extract WATERMARK_MIN_SIZE (20.0) so it is filtered out
BANNER = "TRAINING FIXTURE - ALL NAMES AND ORGANIZATIONS ARE FICTIONAL"

LEFT_X = 40.0
MID_X = 200.0
RIGHT_X = 360.0
FIRST_ROW_Y = 128.0


def _watermark(page: fitz.Page) -> None:
    """Diagonal repeated watermark, drawn large enough that extraction filters it by size."""
    for origin_y in (250.0, 470.0, 690.0):
        page.insert_text(
            (60.0, origin_y),
            WATERMARK,
            fontname="hebo",
            fontsize=WATERMARK_SIZE,
            color=(0.86, 0.86, 0.86),
            morph=(fitz.Point(60.0, origin_y), fitz.Matrix(30)),
        )


def _chrome(page: fitz.Page, org: str, subtitle: str, doc_id: str) -> None:
    page.insert_text((36, 32), org, fontname="hebo", fontsize=18)
    page.insert_text((36, 53), subtitle, fontname="helv", fontsize=10)
    page.insert_text((470, 49), doc_id, fontname="helv", fontsize=10)
    page.insert_text((36, 88), BANNER, fontname="hebo", fontsize=9, color=(0.35, 0.35, 0.35))
    page.insert_text(
        (36, 757),
        f"Upload test fixture {doc_id} - synthetic - no real person, employer or address",
        fontname="helv",
        fontsize=7,
        color=(0.4, 0.4, 0.4),
    )


def _field(
    page: fitz.Page,
    x: float,
    y: float,
    label: str,
    value: str,
    label_size: float = LABEL_SIZE,
    label_bold: bool = True,
    layout: str = "stacked",
) -> None:
    """Draw one label/value pair.

    `layout` is a deliberate experimental variable, not a convenience:
      stacked      -- pack grammar: label, value on the line below, left edges aligned.
      side_by_side -- label and value share a baseline, value to the right. This is what
                      most real-world pay stubs actually do.
      caption      -- value first, label underneath it as a caption.
    """
    font = "hebo" if label_bold else "helv"
    if layout == "side_by_side":
        page.insert_text((x, y), label.upper(), fontname=font, fontsize=label_size)
        page.insert_text((x + 110.0, y), value, fontname="helv", fontsize=VALUE_SIZE)
    elif layout == "caption":
        page.insert_text((x, y), value, fontname="helv", fontsize=VALUE_SIZE)
        page.insert_text((x, y + 11.0), label.upper(), fontname=font, fontsize=label_size)
    else:
        page.insert_text((x, y), label.upper(), fontname=font, fontsize=label_size)
        page.insert_text((x, y + VALUE_DROP), value, fontname="helv", fontsize=VALUE_SIZE)


def _table(page: fitz.Page, spec: dict) -> None:
    """A real earnings table: one header row of labels, data rows well below it.

    The gap between a column header and its first data row is far larger than core's
    VALUE_Y_WINDOW (6-22pt). That is the point of this variant.
    """
    columns = spec["columns"]
    xs = [LEFT_X + 120.0 * i for i in range(len(columns))]
    header_y = FIRST_ROW_Y
    for x, (label, _) in zip(xs, columns):
        page.insert_text((x, header_y), label.upper(), fontname="hebo", fontsize=LABEL_SIZE)
    page.draw_line(
        fitz.Point(LEFT_X, header_y + 6),
        fitz.Point(LEFT_X + 120.0 * len(columns), header_y + 6),
        color=(0.6, 0.6, 0.6),
    )
    depth = max(len(values) for _, values in columns)
    for row_index in range(depth):
        row_y = header_y + 32.0 + 18.0 * row_index
        for x, (_, values) in zip(xs, columns):
            if row_index < len(values):
                page.insert_text(
                    (x, row_y), str(values[row_index]), fontname="helv", fontsize=VALUE_SIZE
                )


def _note(page: fitz.Page, y: float, text: str) -> None:
    page.insert_text((LEFT_X, y), text, fontname="helv", fontsize=9, color=(0.3, 0.3, 0.3))


def build_page(spec: dict) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    _watermark(page)
    _chrome(page, spec["org"], spec["subtitle"], spec["doc_id"])
    if spec.get("layout") == "table":
        _table(page, spec)
        return doc
    layout = spec.get("layout", "stacked")
    label_size = spec.get("label_size", LABEL_SIZE)
    label_bold = spec.get("label_bold", True)
    pitch = 34.0 if layout == "side_by_side" else ROW_PITCH
    xs = (LEFT_X, 300.0, 999.0) if layout == "side_by_side" else (LEFT_X, MID_X, RIGHT_X)
    y = FIRST_ROW_Y
    for row in spec["rows"]:
        for x, (label, value) in zip(xs, row):
            _field(page, x, y, label, str(value), label_size, label_bold, layout)
        y += pitch
    if spec.get("note"):
        _note(page, y + 10, spec["note"])
    return doc


def rasterize(doc: fitz.Document, dpi: int = 150, degrade: str | bool = False) -> fitz.Document:
    """Flatten to an image-only PDF: no text layer at all, so only OCR can read it.

    `degrade` adds camera-phone damage. Two levels, because the first turned out not to
    be damage at all:
      "mild"  -- 7 degree rotation + 1.9px blur. MEASURED: RapidOCR still recovers 7 of 9
                 fields from this. Kept in the corpus precisely because it disproved my
                 prediction that it would abstain.
      "harsh" -- 12 degree rotation, 3.4px blur, and a downsample/upsample round trip at
                 72dpi that destroys glyph interiors. This is the one that should abstain.
    """
    pix = doc[0].get_pixmap(dpi=dpi)
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    if degrade in (True, "mild"):
        image = image.rotate(-7.0, resample=Image.BICUBIC, expand=False, fillcolor=245)
        image = image.filter(ImageFilter.GaussianBlur(radius=1.9))
    elif degrade == "harsh":
        image = image.rotate(-12.0, resample=Image.BICUBIC, expand=False, fillcolor=245)
        image = image.filter(ImageFilter.GaussianBlur(radius=3.4))
        small = image.resize((image.width // 4, image.height // 4), Image.BILINEAR)
        image = small.resize((image.width, image.height), Image.BILINEAR)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    out = fitz.open()
    page = out.new_page(width=PAGE_W, height=PAGE_H)
    page.insert_image(fitz.Rect(0, 0, PAGE_W, PAGE_H), stream=buffer.getvalue())
    return out


# --------------------------------------------------------------------------------------
# The corpus. Each entry carries its own ground truth and a PREDICTION (not a hope) of
# how the system should react.
# --------------------------------------------------------------------------------------

ADDR_DOE = "8812 Marrow Bell Lane, Cambridge, MA 02139"
ADDR_ROE = "5540 Tinsmith Court, Somerville, MA 02144"

DOCS: list[dict] = [
    {
        "file_name": "up_001_application_summary_john_doe.pdf",
        "document_type": "application_summary",
        "org": "Harborlight Housing Office",
        "subtitle": "Application Summary",
        "doc_id": "UP-001",
        "rows": [
            [("APPLICANT", "John Doe"), None, ("HOUSEHOLD SIZE", "3")],
            [("MAILING ADDRESS", ADDR_DOE)],
            [("APPLICATION DATE", "2026-07-12")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "household_size": 3,
            "address": ADDR_DOE,
            "application_date": "2026-07-12",
        },
        "intended_edge_case": None,
        "expected_system_behaviour": (
            "All four fields extracted with certainty=high and real bboxes. "
            "state=present, days_until_stale=+54."
        ),
    },
    {
        "file_name": "up_002_application_summary_jane_roe_month_only.pdf",
        "document_type": "application_summary",
        "org": "Harborlight Housing Office",
        "subtitle": "Application Summary",
        "doc_id": "UP-002",
        "rows": [
            [("APPLICANT", "Jane Roe"), None, ("HOUSEHOLD SIZE", "2")],
            [("MAILING ADDRESS", ADDR_ROE)],
            [("APPLICATION DATE", "2026-06")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "household_size": 2,
            "address": ADDR_ROE,
            "application_date": "2026-06",
        },
        "intended_edge_case": "month_precision_date",
        "expected_system_behaviour": (
            "application_date FAILS to parse (DATE_FIELDS requires %Y-%m-%d) so it comes "
            "back certainty=abstain with value=null; the other three are high. "
            "core.extract reports state='unreadable'; logic/checklist maps this to "
            "'undatable' only once the doc is inside a Household."
        ),
    },
    {
        "file_name": "up_003_pay_stub_john_doe.pdf",
        "document_type": "pay_stub",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-003",
        "rows": [
            [("EMPLOYEE", "John Doe"), None, ("PAY DATE", "2026-07-03")],
            [("PAY PERIOD", "2026-06-15"), ("THROUGH", "2026-06-28"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "72"), ("HOURLY RATE", "19.25"), ("GROSS PAY", "1386.00")],
            [("NET PAY", "1121.66")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-03",
            "pay_period_start": "2026-06-15",
            "pay_period_end": "2026-06-28",
            "pay_frequency": "biweekly",
            "regular_hours": 72,
            "hourly_rate": 19.25,
            "gross_pay": 1386.00,
            "net_pay": 1121.66,
        },
        "intended_edge_case": None,
        "expected_system_behaviour": (
            "All nine fields high. 72 * 19.25 == 1386.00 reconciles. state=present."
        ),
    },
    {
        "file_name": "up_004_pay_stub_john_doe_mismatch.pdf",
        "document_type": "pay_stub",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-004",
        "rows": [
            [("EMPLOYEE", "John Doe"), None, ("PAY DATE", "2026-07-10")],
            [("PAY PERIOD", "2026-06-29"), ("THROUGH", "2026-07-12"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "80"), ("HOURLY RATE", "21.00"), ("GROSS PAY", "$1,980.00")],
            [("NET PAY", "1544.40")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-10",
            "pay_period_start": "2026-06-29",
            "pay_period_end": "2026-07-12",
            "pay_frequency": "biweekly",
            "regular_hours": 80,
            "hourly_rate": 21.00,
            "gross_pay": 1980.00,
            "net_pay": 1544.40,
        },
        "intended_edge_case": "hourly_rate_times_hours_does_not_match_total (80*21.00=1680 != 1980) "
        "+ currency formatting '$1,980.00'",
        "expected_system_behaviour": (
            "Extraction alone will NOT flag the conflict -- core/extract.py has no "
            "cross-field arithmetic; it will happily return gross_pay=1980.0 at high "
            "certainty ('$1,980.00' matches _MONEY_RE and strips to a float). The "
            "conflict only appears at logic/income.py, which raises "
            "'pay_stub_totals_conflict' when gross != hours*rate. So an upload UI that "
            "shows extraction output alone will show no warning here."
        ),
    },
    {
        "file_name": "up_005_pay_stub_jane_roe_expired.pdf",
        "document_type": "pay_stub",
        "org": "Harbor Logistics LLC",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-005",
        "rows": [
            [("EMPLOYEE", "Jane Roe"), None, ("PAY DATE", "2026-04-10")],
            [("PAY PERIOD", "2026-03-23"), ("THROUGH", "2026-04-05"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "64"), ("HOURLY RATE", "17.50"), ("GROSS PAY", "1120.00")],
            [("NET PAY", "907.20")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "pay_date": "2026-04-10",
            "pay_period_start": "2026-03-23",
            "pay_period_end": "2026-04-05",
            "pay_frequency": "biweekly",
            "regular_hours": 64,
            "hourly_rate": 17.50,
            "gross_pay": 1120.00,
            "net_pay": 907.20,
        },
        "intended_edge_case": "document_date_outside_60_day_window",
        "expected_system_behaviour": (
            "All fields extract cleanly at high certainty, but state='expired' with "
            "days_until_stale = (2026-04-10 + 60) - 2026-07-18 = -39."
        ),
    },
    {
        "file_name": "up_006_pay_stub_sam_poe_scan.pdf",
        "document_type": "pay_stub",
        "org": "Bellwether Grocery Co",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-006",
        "rasterized": True,
        "rows": [
            [("EMPLOYEE", "Sam Poe"), None, ("PAY DATE", "2026-07-01")],
            [("PAY PERIOD", "2026-06-14"), ("THROUGH", "2026-06-27"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "80"), ("HOURLY RATE", "18.00"), ("GROSS PAY", "1440.00")],
            [("NET PAY", "1170.72")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "pay_date": "2026-07-01",
            "pay_period_start": "2026-06-14",
            "pay_period_end": "2026-06-27",
            "pay_frequency": "biweekly",
            "regular_hours": 80,
            "hourly_rate": 18.00,
            "gross_pay": 1440.00,
            "net_pay": 1170.72,
        },
        "intended_edge_case": "image_only_page_no_text_layer",
        "expected_system_behaviour": (
            "core.extract abstains on all nine fields ('page has no text layer') and "
            "state='unreadable'. ocr.ocr_extract recovers most of them; digits are the "
            "risk (18.00 vs 1B.00), and low-confidence detections come back certainty=low. "
            "An upload endpoint MUST route to OCR on empty-text-layer, or the document "
            "looks empty."
        ),
    },
    {
        "file_name": "up_007_employment_letter_john_doe.pdf",
        "document_type": "employment_letter",
        "org": "Northgate Diner",
        "subtitle": "Verification of Employment",
        "doc_id": "UP-007",
        "rows": [
            [("EMPLOYEE", "John Doe"), None, ("LETTER DATE", "2026-07-08")],
            [("EMPLOYER", "Northgate Diner"), None, ("POSITION", "Line Cook")],
            [("HOURS PER WEEK", "36"), ("HOURLY RATE", "19.25")],
            [("AUTHORIZED SIGNATURE", "R. Vance, Manager")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "document_date": "2026-07-08",
            "weekly_hours": 36,
            "hourly_rate": 19.25,
        },
        "intended_edge_case": "carries EMPLOYER / POSITION / AUTHORIZED SIGNATURE labels that "
        "the frozen LABEL_MAP has no field for",
        "expected_system_behaviour": (
            "The four mapped fields come back high, state=present. EMPLOYER, POSITION and "
            "AUTHORIZED SIGNATURE are silently dropped from `fields` and surface only via "
            "core.extract.unmapped_labels() -- which extract_document() does not return. "
            "The employer name a reviewer would most want is therefore NOT in the output."
        ),
    },
    {
        "file_name": "up_008_employment_letter_jane_roe_expired.pdf",
        "document_type": "employment_letter",
        "org": "Harbor Logistics LLC",
        "subtitle": "Verification of Employment",
        "doc_id": "UP-008",
        "rows": [
            [("EMPLOYEE", "Jane Roe"), None, ("LETTER DATE", "2026-05-02")],
            [("EMPLOYER", "Harbor Logistics LLC"), None, ("POSITION", "Warehouse Associate")],
            [("HOURS PER WEEK", "28"), ("HOURLY RATE", "17.50")],
            [("AUTHORIZED SIGNATURE", "P. Ostrand, HR")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "document_date": "2026-05-02",
            "weekly_hours": 28,
            "hourly_rate": 17.50,
        },
        "intended_edge_case": "document_date_outside_60_day_window",
        "expected_system_behaviour": "Fields high; state='expired', days_until_stale = -47.",
    },
    {
        "file_name": "up_009_benefit_letter_jane_roe.pdf",
        "document_type": "benefit_letter",
        "org": "Commonwealth Family Support Office",
        "subtitle": "Benefit Award Notice",
        "doc_id": "UP-009",
        "rows": [
            [("RECIPIENT", "Jane Roe"), None, ("LETTER DATE", "2026-07-06")],
            [("ISSUING AGENCY", "Commonwealth Family Support Office")],
            [("MONTHLY AMOUNT", "742.00"), ("FREQUENCY", "monthly")],
            [("BENEFIT PERIOD", "2026-07-01"), ("THROUGH", "2027-06-30")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "document_date": "2026-07-06",
            "monthly_benefit": 742.00,
            "benefit_frequency": "monthly",
        },
        "intended_edge_case": "unmapped ISSUING AGENCY / BENEFIT PERIOD labels",
        "expected_system_behaviour": (
            "Four mapped fields high, state=present (days_until_stale=+48). The issuing "
            "agency is dropped, same blind spot as UP-007."
        ),
    },
    {
        "file_name": "up_010_benefit_letter_sam_poe_scan.pdf",
        "document_type": "benefit_letter",
        "org": "Commonwealth Family Support Office",
        "subtitle": "Benefit Award Notice",
        "doc_id": "UP-010",
        "rasterized": True,
        "rows": [
            [("RECIPIENT", "Sam Poe"), None, ("LETTER DATE", "2026-06-22")],
            [("ISSUING AGENCY", "Commonwealth Family Support Office")],
            [("MONTHLY AMOUNT", "1015.00"), ("FREQUENCY", "monthly")],
            [("BENEFIT PERIOD", "2026-07-01"), ("THROUGH", "2027-06-30")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "document_date": "2026-06-22",
            "monthly_benefit": 1015.00,
            "benefit_frequency": "monthly",
        },
        "intended_edge_case": "image_only_page_no_text_layer",
        "expected_system_behaviour": (
            "core.extract abstains on everything, state='unreadable'. OCR should recover "
            "all four; 1015.00 is the digit-error risk."
        ),
    },
    {
        "file_name": "up_011_gig_statement_sam_poe.pdf",
        "document_type": "gig_statement",
        "org": "ParcelDash",
        "subtitle": "Monthly Earnings Statement",
        "doc_id": "UP-011",
        "rows": [
            [("WORKER", "Sam Poe"), None, ("STATEMENT MONTH", "2026-06")],
            [("GROSS RECEIPTS", "1284.55"), ("PLATFORM FEES", "212.40")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "statement_month": "2026-06",
            "gross_receipts": 1284.55,
            "platform_fees": 212.40,
        },
        "intended_edge_case": "month_precision_date (statement_month is the doc's date field)",
        "expected_system_behaviour": (
            "All four fields extract at high certainty -- '2026-06' is VALID for "
            "statement_month (MONTH_FIELDS). But DATE_FIELD_BY_TYPE points gig_statement's "
            "date at statement_month, and assess_staleness cannot parse %Y-%m, so "
            "state='unreadable' with a note that the 60-day window cannot be applied "
            "without inventing a day. logic/checklist calls this 'undatable'. "
            "This is the read-fine-but-cannot-date case, and the two layers name it "
            "differently."
        ),
    },
    {
        "file_name": "up_012_gig_statement_john_doe_fees_exceed.pdf",
        "document_type": "gig_statement",
        "org": "RideMoss",
        "subtitle": "Monthly Earnings Statement",
        "doc_id": "UP-012",
        "rows": [
            [("WORKER", "John Doe"), None, ("STATEMENT MONTH", "2026-05")],
            [("GROSS RECEIPTS", "640.00"), ("PLATFORM FEES", "780.25")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "statement_month": "2026-05",
            "gross_receipts": 640.00,
            "platform_fees": 780.25,
        },
        "intended_edge_case": "platform_fees exceed gross_receipts (net income would be negative)",
        "expected_system_behaviour": (
            "Both numbers parse and come back high; nothing in extraction compares them. "
            "state='unreadable' for the same month-precision reason as UP-011. Whether the "
            "negative net is caught at all is a logic-layer question."
        ),
    },
    {
        "file_name": "up_013_utility_bill_john_doe.pdf",
        "document_type": "utility_bill",
        "org": "Tidewater Electric Cooperative",
        "subtitle": "Monthly Statement",
        "doc_id": "UP-013",
        "rows": [
            [("ACCOUNT HOLDER", "John Doe"), None, ("STATEMENT DATE", "2026-07-05")],
            [("SERVICE ADDRESS", ADDR_DOE)],
            [("AMOUNT DUE", "94.18"), ("DUE DATE", "2026-07-29")],
        ],
        "intended_fields": {
            "account_holder": "John Doe",
            "statement_date": "2026-07-05",
            "service_address": ADDR_DOE,
            "amount_due": 94.18,
        },
        "intended_edge_case": "document type the system has never heard of",
        "expected_system_behaviour": (
            "infer_document_type() returns 'unknown' (not in LABEL_MAP). EXPECTED_FIELDS "
            "has no entry, so `fields` comes back EMPTY -- not an error, not an "
            "abstention, just nothing. state='unreadable' because DATE_FIELD_BY_TYPE has "
            "no 'unknown'. An upload UI that trusts a non-empty field list will render a "
            "blank card with no explanation. This is the case most likely to look like a "
            "bug to a judge."
        ),
    },
    {
        "file_name": "up_014_pay_stub_jane_roe_unreadable.pdf",
        "document_type": "pay_stub",
        "org": "Harbor Logistics LLC",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-014",
        "rasterized": True,
        "degrade": True,
        "rows": [
            [("EMPLOYEE", "Jane Roe"), None, ("PAY DATE", "2026-07-02")],
            [("PAY PERIOD", "2026-06-15"), ("THROUGH", "2026-06-28"), ("PAY FREQUENCY", "weekly")],
            [("REGULAR HOURS", "40"), ("HOURLY RATE", "17.50"), ("GROSS PAY", "700.00")],
            [("NET PAY", "567.00")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "pay_date": "2026-07-02",
            "pay_period_start": "2026-06-15",
            "pay_period_end": "2026-06-28",
            "pay_frequency": "weekly",
            "regular_hours": 40,
            "hourly_rate": 17.50,
            "gross_pay": 700.00,
            "net_pay": 567.00,
        },
        "degrade": "mild",
        "intended_edge_case": "rotated 7 degrees and blurred -- deliberately hard to read",
        "expected_system_behaviour": (
            "core.extract abstains on all nine. OCR should ALSO abstain on most or all of "
            "them: the rotation breaks the label-above-value geometry that "
            "extract_fields_from_detections depends on (VALUE_X_TOLERANCE is only 5pt, and "
            "a 7-degree tilt moves a value 40pt to the right of its label by ~5pt at the "
            "left margin and much more further across the page). Abstention here is the "
            "correct outcome, not a failure. "
            "[MEASURED 2026-07-19: WRONG. OCR recovered 7 of 9 at high certainty, "
            "abstaining only on gross_pay and net_pay. RapidOCR's detector is "
            "rotation-tolerant and returns axis-aligned boxes, so the label/value column "
            "test still passes at this tilt. Document kept unchanged; see UP-026 for a "
            "degradation level that does abstain.]"
        ),
    },
    {
        "file_name": "up_015_pay_stub_sam_poe_odd_frequency.pdf",
        "document_type": "pay_stub",
        "org": "Bellwether Grocery Co",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-015",
        "rows": [
            [("EMPLOYEE", "Sam Poe"), None, ("PAY DATE", "2026-07-15")],
            [
                ("PAY PERIOD", "2026-06-28"),
                ("THROUGH", "2026-07-11"),
                ("PAY FREQUENCY", "fortnightly"),
            ],
            [("REGULAR HOURS", "76"), ("HOURLY RATE", "18.00"), ("GROSS PAY", "1368.00")],
            [("NET PAY", "1112.14")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "pay_date": "2026-07-15",
            "pay_period_start": "2026-06-28",
            "pay_period_end": "2026-07-11",
            "pay_frequency": "fortnightly",
            "regular_hours": 76,
            "hourly_rate": 18.00,
            "gross_pay": 1368.00,
            "net_pay": 1112.14,
        },
        "intended_edge_case": "pay_frequency outside KNOWN_FREQUENCIES",
        "expected_system_behaviour": (
            "pay_frequency='fortnightly' is returned but at certainty=low with the note "
            "'value did not match the expected format for this field', because "
            "CH-INCOME-001 annualizes from this token. Everything else high; "
            "state=present. 76*18.00=1368.00 reconciles."
        ),
    },
    # ----------------------------------------------------------------------------------
    # COHORT B -- label WORDING varies, typography and layout held identical to the pack.
    # The judges' documents will not use our vocabulary. deterministic_mapper is an exact
    # dict lookup, so a synonym is not a near-miss: it is a total miss.
    # ----------------------------------------------------------------------------------
    {
        "file_name": "up_016_pay_stub_wording_total_earnings.pdf",
        "document_type": "pay_stub",
        "cohort": "label_wording",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-016",
        "rows": [
            [("EMPLOYEE NAME", "John Doe"), None, ("CHECK DATE", "2026-07-03")],
            [
                ("PERIOD COVERED", "2026-06-15"),
                ("TO", "2026-06-28"),
                ("PAY CYCLE", "biweekly"),
            ],
            [("HOURS WORKED", "72"), ("RATE OF PAY", "19.25"), ("TOTAL EARNINGS", "1386.00")],
            [("TAKE HOME PAY", "1121.66")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-03",
            "pay_period_start": "2026-06-15",
            "pay_period_end": "2026-06-28",
            "pay_frequency": "biweekly",
            "regular_hours": 72,
            "hourly_rate": 19.25,
            "gross_pay": 1386.00,
            "net_pay": 1121.66,
        },
        "intended_edge_case": "every label is a synonym of one LABEL_MAP knows",
        "expected_system_behaviour": (
            "TOTAL COLLAPSE. Not one of the nine labels is in LABEL_MAP['pay_stub'], so "
            "all nine come back certainty=abstain, 'no label for this field was found on "
            "the page' -- even though the page has a perfect text layer and a human reads "
            "it instantly. state='unreadable' (no pay_date). unmapped_labels() should "
            "return all nine strings. This is the single most likely way we fail on a "
            "judge's own document, and it fails silently as an abstention rather than an "
            "error."
        ),
    },
    {
        "file_name": "up_017_pay_stub_wording_gross_wages.pdf",
        "document_type": "pay_stub",
        "cohort": "label_wording",
        "org": "Bellwether Grocery Co",
        "subtitle": "Statement of Earnings",
        "doc_id": "UP-017",
        "rows": [
            [("EMPLOYEE", "Sam Poe"), None, ("PAY DATE", "2026-07-01")],
            [("PAY PERIOD", "2026-06-14"), ("THROUGH", "2026-06-27"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "80"), ("BASE RATE", "18.00"), ("GROSS WAGES", "1440.00")],
            [("NET PAY", "1170.72")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "pay_date": "2026-07-01",
            "pay_period_start": "2026-06-14",
            "pay_period_end": "2026-06-27",
            "pay_frequency": "biweekly",
            "regular_hours": 80,
            "hourly_rate": 18.00,
            "gross_pay": 1440.00,
            "net_pay": 1170.72,
        },
        "intended_edge_case": "PARTIAL synonym drift -- only hourly_rate and gross_pay renamed",
        "expected_system_behaviour": (
            "Seven of nine extract at high certainty. hourly_rate ('BASE RATE') and "
            "gross_pay ('GROSS WAGES') abstain. state=present, because pay_date survived. "
            "This is the dangerous shape: the card looks populated and healthy, and the "
            "two missing fields are precisely the two CH-INCOME-001 needs."
        ),
    },
    {
        "file_name": "up_018_employment_letter_wording_company.pdf",
        "document_type": "employment_letter",
        "cohort": "label_wording",
        "org": "Harbor Logistics LLC",
        "subtitle": "Employment Verification",
        "doc_id": "UP-018",
        "rows": [
            [("EMPLOYEE NAME", "Jane Roe"), None, ("DATE OF LETTER", "2026-07-09")],
            [("COMPANY", "Harbor Logistics LLC"), None, ("JOB TITLE", "Warehouse Associate")],
            [("WEEKLY HOURS", "28"), ("RATE OF PAY", "17.50")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "document_date": "2026-07-09",
            "weekly_hours": 28,
            "hourly_rate": 17.50,
        },
        "intended_edge_case": "all four mapped labels renamed (EMPLOYEE->EMPLOYEE NAME, "
        "LETTER DATE->DATE OF LETTER, HOURS PER WEEK->WEEKLY HOURS, HOURLY RATE->RATE OF PAY)",
        "expected_system_behaviour": (
            "All four abstain; state='unreadable'. Note how near the misses are: "
            "'EMPLOYEE NAME' vs 'EMPLOYEE' and 'WEEKLY HOURS' vs 'HOURS PER WEEK' are the "
            "same words. An exact dict lookup has no notion of near."
        ),
    },
    # ----------------------------------------------------------------------------------
    # COHORT C -- TYPOGRAPHY varies, wording and layout held identical to the pack.
    # is_label() requires bold AND 7.5 <= size <= 8.5 AND text == text.upper().
    # ----------------------------------------------------------------------------------
    {
        "file_name": "up_019_pay_stub_labels_10pt.pdf",
        "document_type": "pay_stub",
        "cohort": "typography",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-019",
        "label_size": 10.0,
        "rows": [
            [("EMPLOYEE", "John Doe"), None, ("PAY DATE", "2026-07-03")],
            [("PAY PERIOD", "2026-06-15"), ("THROUGH", "2026-06-28"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "72"), ("HOURLY RATE", "19.25"), ("GROSS PAY", "1386.00")],
            [("NET PAY", "1121.66")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-03",
            "pay_period_start": "2026-06-15",
            "pay_period_end": "2026-06-28",
            "pay_frequency": "biweekly",
            "regular_hours": 72,
            "hourly_rate": 19.25,
            "gross_pay": 1386.00,
            "net_pay": 1121.66,
        },
        "intended_edge_case": "correct label TEXT at 10pt bold -- outside LABEL_SIZE_RANGE",
        "expected_system_behaviour": (
            "TOTAL COLLAPSE, and worse than the wording case: at 10pt these strings are "
            "not labels at all, so unmapped_labels() returns NOTHING either. We lose both "
            "the extraction and the diagnostic that would tell us why. All nine abstain, "
            "state='unreadable'."
        ),
    },
    {
        "file_name": "up_020_pay_stub_labels_9pt.pdf",
        "document_type": "pay_stub",
        "cohort": "typography",
        "org": "Bellwether Grocery Co",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-020",
        "label_size": 9.0,
        "rows": [
            [("EMPLOYEE", "Sam Poe"), None, ("PAY DATE", "2026-07-15")],
            [("PAY PERIOD", "2026-06-28"), ("THROUGH", "2026-07-11"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "76"), ("HOURLY RATE", "18.00"), ("GROSS PAY", "1368.00")],
            [("NET PAY", "1112.14")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "pay_date": "2026-07-15",
            "pay_period_start": "2026-06-28",
            "pay_period_end": "2026-07-11",
            "pay_frequency": "biweekly",
            "regular_hours": 76,
            "hourly_rate": 18.00,
            "gross_pay": 1368.00,
            "net_pay": 1112.14,
        },
        "intended_edge_case": "9pt bold labels -- 0.5pt outside the range",
        "expected_system_behaviour": (
            "All nine abstain. 9pt is a completely ordinary label size in real documents; "
            "the range (7.5, 8.5) was fitted to this one fixture set."
        ),
    },
    {
        "file_name": "up_021_pay_stub_labels_not_bold.pdf",
        "document_type": "pay_stub",
        "cohort": "typography",
        "org": "Harbor Logistics LLC",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-021",
        "label_bold": False,
        "rows": [
            [("EMPLOYEE", "Jane Roe"), None, ("PAY DATE", "2026-07-07")],
            [("PAY PERIOD", "2026-06-22"), ("THROUGH", "2026-07-05"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "64"), ("HOURLY RATE", "17.50"), ("GROSS PAY", "1120.00")],
            [("NET PAY", "907.20")],
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "pay_date": "2026-07-07",
            "pay_period_start": "2026-06-22",
            "pay_period_end": "2026-07-05",
            "pay_frequency": "biweekly",
            "regular_hours": 64,
            "hourly_rate": 17.50,
            "gross_pay": 1120.00,
            "net_pay": 907.20,
        },
        "intended_edge_case": "correct size (7.5pt) and correct wording, but REGULAR weight",
        "expected_system_behaviour": (
            "All nine abstain: is_label() requires bold. A document that differs from the "
            "pack in nothing but font weight extracts zero fields."
        ),
    },
    {
        "file_name": "up_022_pay_stub_labels_8pt_control.pdf",
        "document_type": "pay_stub",
        "cohort": "typography",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-022",
        "label_size": 8.4,
        "rows": [
            [("EMPLOYEE", "John Doe"), None, ("PAY DATE", "2026-07-17")],
            [("PAY PERIOD", "2026-07-01"), ("THROUGH", "2026-07-14"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "70"), ("HOURLY RATE", "19.25"), ("GROSS PAY", "1347.50")],
            [("NET PAY", "1090.48")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-17",
            "pay_period_start": "2026-07-01",
            "pay_period_end": "2026-07-14",
            "pay_frequency": "biweekly",
            "regular_hours": 70,
            "hourly_rate": 19.25,
            "gross_pay": 1347.50,
            "net_pay": 1090.48,
        },
        "intended_edge_case": "CONTROL: 8.4pt bold, just inside LABEL_SIZE_RANGE's upper bound",
        "expected_system_behaviour": (
            "All nine extract at high certainty, state=present. This is the control that "
            "proves the 9pt and 10pt failures are caused by the size gate specifically and "
            "not by something else I changed."
        ),
    },
    # ----------------------------------------------------------------------------------
    # COHORT D -- LAYOUT varies, wording and typography held identical to the pack.
    # _resolve_value() demands the value 6-22pt BELOW the label and left-aligned within
    # 3pt of it.
    # ----------------------------------------------------------------------------------
    {
        "file_name": "up_023_pay_stub_side_by_side.pdf",
        "document_type": "pay_stub",
        "cohort": "layout",
        "org": "Northgate Diner",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-023",
        "layout": "side_by_side",
        "rows": [
            [("EMPLOYEE", "John Doe")],
            [("PAY DATE", "2026-07-03")],
            [("PAY PERIOD", "2026-06-15")],
            [("THROUGH", "2026-06-28")],
            [("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "72")],
            [("HOURLY RATE", "19.25")],
            [("GROSS PAY", "1386.00")],
            [("NET PAY", "1121.66")],
        ],
        "intended_fields": {
            "person_name": "John Doe",
            "pay_date": "2026-07-03",
            "pay_period_start": "2026-06-15",
            "pay_period_end": "2026-06-28",
            "pay_frequency": "biweekly",
            "regular_hours": 72,
            "hourly_rate": 19.25,
            "gross_pay": 1386.00,
            "net_pay": 1121.66,
        },
        "intended_edge_case": "label and value on the SAME baseline, value 110pt to the right",
        "expected_system_behaviour": (
            "All nine abstain. Every label IS recognised (right size, right weight, right "
            "wording) so unmapped_labels() returns nothing -- the labels map fine, there is "
            "simply no value in the column below them. This is the most common real-world "
            "pay stub layout in existence and we score 0 on it. Distinguishing this "
            "failure from the wording failure matters: this one is fixable with geometry, "
            "not with an LLM."
        ),
    },
    {
        "file_name": "up_024_pay_stub_table.pdf",
        "document_type": "pay_stub",
        "cohort": "layout",
        "org": "Harbor Logistics LLC",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-024",
        "layout": "table",
        "columns": [
            ("EMPLOYEE", ["Jane Roe"]),
            ("PAY DATE", ["2026-07-07"]),
            ("REGULAR HOURS", ["64", "8"]),
            ("HOURLY RATE", ["17.50", "26.25"]),
            ("GROSS PAY", ["1120.00", "210.00"]),
        ],
        "intended_fields": {
            "person_name": "Jane Roe",
            "pay_date": "2026-07-07",
            "regular_hours": 64,
            "hourly_rate": 17.50,
            "gross_pay": 1120.00,
        },
        "intended_edge_case": "earnings TABLE -- column headers as labels, first data row 32pt "
        "below the header, plus a second (overtime) row",
        "expected_system_behaviour": (
            "All fields abstain: 32pt exceeds VALUE_Y_WINDOW's 22pt ceiling. If I have the "
            "geometry slightly wrong and the first data row does land inside the window, "
            "the second risk appears -- two data rows under one header means two candidate "
            "runs, which downgrades to certainty=low rather than abstaining. Either result "
            "is informative; I predict abstention."
        ),
    },
    {
        "file_name": "up_025_benefit_letter_caption_layout.pdf",
        "document_type": "benefit_letter",
        "cohort": "layout",
        "org": "Commonwealth Family Support Office",
        "subtitle": "Benefit Award Notice",
        "doc_id": "UP-025",
        "layout": "caption",
        "rows": [
            [("RECIPIENT", "Sam Poe"), None, ("LETTER DATE", "2026-07-04")],
            [("MONTHLY AMOUNT", "868.00"), ("FREQUENCY", "monthly")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "document_date": "2026-07-04",
            "monthly_benefit": 868.00,
            "benefit_frequency": "monthly",
        },
        "intended_edge_case": "value ABOVE its label (label used as a caption underneath)",
        "expected_system_behaviour": (
            "All four abstain. _resolve_value only ever looks downward "
            "(label_baseline - line_baseline must be positive), so a value above its label "
            "is invisible by construction. Labels are recognised, so unmapped_labels() is "
            "again empty."
        ),
    },
    {
        "file_name": "up_026_pay_stub_sam_poe_illegible.pdf",
        "document_type": "pay_stub",
        "cohort": "pack_form",
        "org": "Bellwether Grocery Co",
        "subtitle": "Earnings Statement",
        "doc_id": "UP-026",
        "rasterized": True,
        "degrade": "harsh",
        "rows": [
            [("EMPLOYEE", "Sam Poe"), None, ("PAY DATE", "2026-07-09")],
            [("PAY PERIOD", "2026-06-22"), ("THROUGH", "2026-07-05"), ("PAY FREQUENCY", "biweekly")],
            [("REGULAR HOURS", "78"), ("HOURLY RATE", "18.00"), ("GROSS PAY", "1404.00")],
            [("NET PAY", "1141.65")],
        ],
        "intended_fields": {
            "person_name": "Sam Poe",
            "pay_date": "2026-07-09",
            "pay_period_start": "2026-06-22",
            "pay_period_end": "2026-07-05",
            "pay_frequency": "biweekly",
            "regular_hours": 78,
            "hourly_rate": 18.00,
            "gross_pay": 1404.00,
            "net_pay": 1141.65,
        },
        "intended_edge_case": "genuinely illegible -- 12 degree rotation, heavy blur, 4x "
        "downsample round trip (added after UP-014's mild damage failed to defeat OCR)",
        "expected_system_behaviour": (
            "Both paths abstain on all nine. The interesting question is not whether it "
            "abstains but whether it abstains QUIETLY or produces a confident wrong "
            "reading -- a garbled '1404.00' recognised as '1494.00' at high confidence "
            "would be the worst outcome this corpus can produce, because nothing "
            "downstream would catch it."
        ),
    },
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for spec in DOCS:
        rows = [[cell for cell in row if cell] for row in spec.get("rows", [])]
        doc = build_page({**spec, "rows": rows})
        if spec.get("rasterized"):
            doc = rasterize(doc, degrade=spec.get("degrade", False))
        target = OUT_DIR / spec["file_name"]
        doc.save(target)
        doc.close()
        manifest.append(
            {
                "file_name": spec["file_name"],
                "document_type": spec["document_type"],
                "cohort": spec.get("cohort", "pack_form"),
                "rasterized": bool(spec.get("rasterized")),
                "degraded": bool(spec.get("degrade")),
                "watermarked": True,
                "intended_fields": spec["intended_fields"],
                "intended_edge_case": spec["intended_edge_case"],
                "expected_system_behaviour": spec["expected_system_behaviour"],
            }
        )
        print(f"wrote {target.name}")

    MANIFEST.write_text(
        json.dumps(
            {
                "generated_by": "scripts/make_testdata.py",
                "reference_date": "2026-07-18",
                "purpose": (
                    "Ground truth for the upload path. These documents are NOT in "
                    "pack/synthetic_documents/; the extractor has never seen them. Compare "
                    "intended_fields against core.extract / ocr.ocr_extract output to get a "
                    "measured upload accuracy instead of a claimed one."
                ),
                "safety": (
                    "All names are obvious placeholders, all organisations are invented, all "
                    "street numbers are out of range for their city/ZIP, no SSNs appear, and "
                    "every page carries a visible SYNTHETIC watermark."
                ),
                "documents": manifest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {MANIFEST}  ({len(manifest)} documents)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
