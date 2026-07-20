# -*- coding: utf-8 -*-
"""
make_scenario_sets.py -- the systematic scenario corpus: 50 household FILES, each a set
of documents, with the truth written in the same run that draws the pages.

WHY THIS FILE EXISTS
--------------------
Every earlier instrument measured one document at a time. The product's actual unit of
work is a FILE: several documents that must agree with each other before a readiness
status, a reason list and a threshold comparison can be stated. This generator builds 50
such files as a designed matrix (not a random sample), and writes
`testdata/scenarios/scenario_truth.json` in the same breath, so the truth is true by
construction rather than by transcription.

Two owner decisions are operationalized here:

  1. The set count is determined by DOCUMENT COMBINATIONS, not by field cross-products.
     Layer 1 below is exactly the income-mix x completeness lattice (20 sets); layers 2-4
     add state overlays, interactions and boundaries on top of those combinations.
  2. Real internet-sourced blank forms carry the fills wherever we hold one
     (`testdata/confirm_raw/`), so layout variance produces corners our own generator
     style cannot. Techniques are lifted from `scripts/make_filled_forms.py`, which
     already solved overlay vs AcroForm per carrier.

THE 50-SET MATRIX
-----------------
Layer 1 (20) -- income-mix x completeness. Mixes W (wage) / WB (+benefit) / WG (+gig) /
  WBG. Required document types follow the organizer's own conditional pattern
  (pack/evaluation/application_checklists.json): base {application_summary, pay_stub,
  employment_letter}; +benefit_letter iff benefit income; +gig_income_corroboration iff
  a gig_statement exists (the statement never satisfies its own corroboration). For each
  mix: the complete file, plus one-missing variants of every required type.
  4 + 5 + 5 + 6 = 20 -- the count IS the combination count.
Layer 2 (17) -- one state deviation each, on the complete baselines.
Layer 3 (5)  -- interaction pairs the reasoning code actually reads together.
Layer 4 (8)  -- boundary / structural sets (empty file, out-of-scope document,
  conflicting summaries, household-size table edges, threshold equality to the cent).

CARRIERS
--------
employment-letter slots rotate the three real verification forms (seattle overlay,
mnhousing overlay, wa_dshs AcroForm -- filled through its widgets, NEVER flattened);
pay-stub slots rotate the real orangeusd stub grid plus two NEW generator styles that
deliberately break the pack's visual grammar; application_summary / benefit_letter /
gig documents use generator styles A/B/C (three visually distinct templates);
gig-corroboration slots rotate the kcha Section-8 packet (page-8 excerpt overlay) and a
generator bank-deposit summary. md_labor is not fillable (established earlier) and is
not used. Documents carried by wa_dshs are invisible to today's text-layer extractor
(values live in widget annotations -- the T18 backlog); that is EXPECTED, and every set
carrying one is marked `"carrier_class": "acroform"` so measurement reports them as a
separate stratum. Those sets are the T18 acceptance corpus.

TRUTH DISCIPLINE
----------------
* Borrowed layout, invented content: no real person, all employers fictional.
* `truth_fields` carries what a correct reader of the page would hold, with page+bbox
  recorded at draw time (the logic layer's traceability condition needs the box).
  Dates in `truth_fields` are ISO -- the repository's reading convention -- whatever
  format the page prints.
* A date printed with a masked or two-digit year is UNUSABLE: no truth value exists for
  it (we never invent a century), so the field goes to `expect_absent` -- emitting any
  ISO date for it is an invented value. Four-digit years are used wherever the currency
  logic needs a computable date.
* Scanned (image-only) documents move their values to `latent_fields`: the pixels show
  them, the text layer does not. Reading one correctly is correct; abstaining is
  honest; only a mismatched value is wrong. They feed the logic layer NOTHING.
* `expected_readiness_status` / `expected_review_reasons` / `expected_comparison` are
  derived BY HAND from the reasoning layer's own documented conventions
  (logic/constants.py CONVENTIONS, the pack checklist vocabulary, and the repo's own
  recorded extra -- a gig statement's month-precision date always raises
  DOCUMENT_UNDATABLE, exactly as logic/test_pack_agreement.py KNOWN_EXTRA_REASONS
  records for HH-004). They are NOT produced by running logic/ -- that would make the
  measurement circular.
* Eight sets are `role: "sealed"` (>=1 per layer, >=1 per carrier class): generated,
  truth recorded, and never measured by this exercise; the harness refuses to open them
  without an explicit --unseal.

    python scripts/make_scenario_sets.py
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "testdata" / "confirm_raw"
OUT_DIR = ROOT / "testdata" / "scenarios"
MANIFEST = OUT_DIR / "scenario_truth.json"

INK = (0.05, 0.05, 0.35)
PAGE_W, PAGE_H = 612.0, 792.0

# Frozen 60% AMI table, restated from pack/rules/rule_corpus.jsonl (HUD-MTSP-002) so this
# generator does not import logic/ (whose files a concurrent agent owns). Values verified
# against logic/constants.py LIMITS_60_PCT at the time of writing.
LIMITS_60 = {1: 72000, 2: 82320, 3: 92580, 4: 102840, 5: 111120, 6: 119340,
             7: 127560, 8: 135780}

BASE_REQUIRED = ("application_summary", "pay_stub", "employment_letter")

WATERMARK = "SYNTHETIC - NOT A REAL DOCUMENT"
BANNER = "SCENARIO FIXTURE - ALL NAMES AND ORGANIZATIONS ARE FICTIONAL"

# The extractor's reachable-field universe per document type, restated from
# core/extract.py EXPECTED_FIELDS so `expect_absent` can be computed at build time
# without importing core/ (same read-only discipline as LIMITS_60 above).
REACHABLE = {
    "application_summary": ("person_name", "household_size", "address", "application_date"),
    "pay_stub": ("person_name", "pay_date", "pay_period_start", "pay_period_end",
                 "pay_frequency", "regular_hours", "hourly_rate", "gross_pay", "net_pay"),
    "employment_letter": ("person_name", "document_date", "weekly_hours", "hourly_rate"),
    "benefit_letter": ("person_name", "document_date", "monthly_benefit", "benefit_frequency"),
    "gig_statement": ("person_name", "statement_month", "gross_receipts", "platform_fees"),
    # gig_income_corroboration / utility_bill: no entry -- structurally unreachable today.
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _us(iso: str) -> str:
    """ISO -> the US format most real forms print (MM/DD/YYYY)."""
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def _money(amount: float) -> str:
    return f"{amount:,.2f}"


# =====================================================================================
# truth-field bookkeeping
# =====================================================================================
def _tf(field: str, value: Any, page: int, bbox: list[float]) -> dict[str, Any]:
    return {"field": field, "value": value, "page": page,
            "bbox": [round(v, 1) for v in bbox]}


def _text_bbox(x: float, y: float, text: str, size: float, font: str) -> list[float]:
    width = fitz.get_text_length(str(text), fontname=font, fontsize=size)
    return [x, y - size, x + width, y + 0.25 * size]


class Sheet:
    """One generator page plus the truth records for everything drawn on it."""

    def __init__(self) -> None:
        self.doc = fitz.open()
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        self.truth: list[dict[str, Any]] = []

    def watermark(self) -> None:
        for oy in (250.0, 470.0, 690.0):
            self.page.insert_text((60.0, oy), WATERMARK, fontname="hebo", fontsize=28.0,
                                  color=(0.87, 0.87, 0.87),
                                  morph=(fitz.Point(60.0, oy), fitz.Matrix(30)))

    def chrome(self, org: str, subtitle: str, tag: str, font: str = "hebo") -> None:
        self.page.insert_text((36, 34), org, fontname=font, fontsize=17)
        self.page.insert_text((36, 54), subtitle, fontname="helv", fontsize=10)
        self.page.insert_text((470, 50), tag, fontname="helv", fontsize=9)
        self.page.insert_text((36, 86), BANNER, fontname="hebo", fontsize=8.5,
                              color=(0.35, 0.35, 0.35))
        self.page.insert_text(
            (36, 762), f"Scenario fixture {tag} - synthetic - no real person or employer",
            fontname="helv", fontsize=7, color=(0.4, 0.4, 0.4))

    def put(self, x: float, y: float, text: str, size: float, font: str,
            field: str | None = None, gold: Any = None) -> None:
        """Draw text; when `field` is named, record the truth with the drawn bbox."""
        self.page.insert_text((x, y), str(text), fontname=font, fontsize=size, color=INK
                              if field else (0, 0, 0))
        if field is not None:
            value = gold if gold is not None else text
            self.truth.append(_tf(field, value, 1, _text_bbox(x, y, text, size, font)))

    def bytes(self) -> bytes:
        data = self.doc.tobytes(deflate=True)
        self.doc.close()
        return data


def rasterize(pdf_bytes: bytes, dpi: int = 150) -> bytes:
    """Flatten page 1 to an image-only PDF: the values survive only as pixels."""
    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = src[0].get_pixmap(dpi=dpi)
    width, height = src[0].rect.width, src[0].rect.height
    src.close()
    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    out = fitz.open()
    page = out.new_page(width=width, height=height)
    page.insert_image(fitz.Rect(0, 0, width, height), stream=buffer.getvalue())
    data = out.tobytes(deflate=True)
    out.close()
    return data


# =====================================================================================
# document record
# =====================================================================================
class DocRecord:
    def __init__(self, document_type: str, carrier: str, data: bytes,
                 truth_fields: list[dict[str, Any]],
                 render: str = "text",
                 deviation: str | None = None,
                 corner: str | None = None,
                 marked_only: dict[str, Any] | None = None,
                 ambiguous: dict[str, Any] | None = None,
                 note: str = "") -> None:
        self.document_type = document_type
        self.carrier = carrier
        self.data = data
        self.truth_fields = truth_fields
        self.latent_fields: list[dict[str, Any]] = []
        self.render = render
        self.deviation = deviation
        self.corner = corner
        self.marked_only = marked_only or {}
        self.ambiguous = ambiguous or {}
        self.note = note

    def scanned(self) -> "DocRecord":
        """Rasterize: truth moves to latent (pixels only), the text layer goes away."""
        self.data = rasterize(self.data)
        self.latent_fields = self.truth_fields
        self.truth_fields = []
        self.render = "scan"
        return self

    def expect_absent(self) -> list[str]:
        reachable = REACHABLE.get(self.document_type, ())
        holds = {f["field"] for f in self.truth_fields} | \
                {f["field"] for f in self.latent_fields} | \
                set(self.marked_only) | set(self.ambiguous)
        return [name for name in reachable if name not in holds]


# =====================================================================================
# generator styles -- application_summary A/B/C
# =====================================================================================
def summary_a(p: dict[str, Any]) -> DocRecord:
    """Pack visual grammar: 7.5pt bold CAPS label, 10pt value 15pt below."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Application Summary", p["tag"])
    rows = [
        (40, 130, "APPLICANT", p["name"], "person_name", None),
        (360, 130, "HOUSEHOLD SIZE", str(p["size"]), "household_size", p["size"]),
        (40, 190, "MAILING ADDRESS", p["address"], "address", None),
        (40, 250, "APPLICATION DATE", p["app_date"], "application_date", None),
    ]
    for x, y, label, value, field, gold in rows:
        s.put(x, y, label, 7.5, "hebo")
        s.put(x, y + 15.0, value, 10.0, "helv", field, gold)
    return DocRecord("application_summary", "generator_summary_a", s.bytes(), s.truth)


def summary_b(p: dict[str, Any]) -> DocRecord:
    """Municipal serif: mixed-case colon labels inline with the value, 11pt Times.

    The label vocabulary uses a curly apostrophe when the `curly` corner is on --
    "Applicant’s Name:" -- a string no table in core/extract.py contains.
    """
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Summary of Application", p["tag"], font="tibo")
    apos = "’" if p.get("curly") else "'"
    rows = [
        (f"Applicant{apos}s Name:", p["name"], "person_name", None),
        ("Persons residing in household:", str(p["size"]), "household_size", p["size"]),
        ("Mailing address:", p["address"], "address", None),
        ("Date of submission:", p["app_date"], "application_date", None),
    ]
    y = 140.0
    for label, value, field, gold in rows:
        s.put(54, y, label, 11.0, "tibo")
        lw = fitz.get_text_length(label, fontname="tibo", fontsize=11.0)
        s.put(54 + lw + 8, y, value, 11.0, "tiro", field, gold)
        y += 30.0
    return DocRecord("application_summary", "generator_summary_b", s.bytes(), s.truth,
                     corner="curly_apostrophe_label" if p.get("curly") else None)


def summary_c(p: dict[str, Any]) -> DocRecord:
    """Boxed caption grid: Courier, VALUE first, caption printed underneath it."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Household Intake Card", p["tag"], font="cobo")
    cells = [
        (44, 150, p["name"], "NAME OF APPLICANT", "person_name", None),
        (330, 150, str(p["size"]), "TOTAL IN HOUSEHOLD", "household_size", p["size"]),
        (44, 220, p["address"], "RESIDENCE", "address", None),
        (44, 290, p["app_date"], "FILED ON", "application_date", None),
    ]
    for x, y, value, caption, field, gold in cells:
        s.put(x, y, value, 10.0, "cour", field, gold)
        s.put(x, y + 12.0, caption, 7.0, "cobo")
    return DocRecord("application_summary", "generator_summary_c", s.bytes(), s.truth)


# =====================================================================================
# generator styles -- pay stub X/Y (both deliberately off the pack grammar)
# =====================================================================================
def stub_x(p: dict[str, Any]) -> DocRecord:
    """Style X: colon-terminated inline labels, 9pt bold mixed case -- outside the label
    gate on size AND case AND geometry (value on the same baseline). Vocabulary strays
    from LABEL_SYNONYMS ("Team Member", "Wages this Period", "Take-Home")."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Wage & Earnings Slip", p["tag"])
    truth_map = p["truth"]      # field -> gold value (ISO dates), or absent
    printed = p["printed"]      # label -> (printed value, field name or None)
    y = 132.0
    for label, (value, field) in printed.items():
        s.put(46, y, label, 9.0, "hebo")
        lw = fitz.get_text_length(label, fontname="hebo", fontsize=9.0)
        x = 46 + lw + 10
        if p.get("split_field") == field:
            # digit-group splitting: the amount is drawn as two runs with a gap wider
            # than a space, so the text layer shreds it ("1," + "482.00").
            cut = value.index(",") + 1 if "," in value else len(value) // 2
            head, tail = value[:cut], value[cut:]
            s.put(x, y, head, 10.0, "helv")
            hw = fitz.get_text_length(head, fontname="helv", fontsize=10.0)
            s.put(x + hw + 14.0, y, tail, 10.0, "helv")
            if field in truth_map:
                s.truth.append(_tf(field, truth_map[field], 1,
                                   _text_bbox(x, y, value, 10.0, "helv")))
        else:
            s.put(x, y, value, 10.0, "helv",
                  field if field in truth_map else None,
                  truth_map.get(field))
        y += 26.0
    return DocRecord("pay_stub", "generator_stub_x", s.bytes(), s.truth,
                     corner=p.get("corner"))


def stub_y(p: dict[str, Any]) -> DocRecord:
    """Style Y: ledger. Identity block side-by-side (label CAPS bold 8pt -- inside the
    size gate! -- value on the SAME baseline 130pt right); earnings table with headers
    30pt above the data row, far outside the 6-22pt value window."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Payroll Ledger", p["tag"])
    truth_map = p["truth"]
    y = 128.0
    for label, (value, field) in p["side"].items():
        s.put(46, y, label, 8.0, "hebo")
        s.put(176, y, value, 9.5, "helv",
              field if field in truth_map else None, truth_map.get(field))
        y += 24.0
    header_y = y + 24.0
    cols = p["table"]  # list of (header, printed value, field or None)
    xs = [46 + 128.0 * i for i in range(len(cols))]
    for x, (header, _v, _f) in zip(xs, cols):
        s.put(x, header_y, header, 8.0, "hebo")
    s.page.draw_line(fitz.Point(44, header_y + 5), fitz.Point(44 + 128.0 * len(cols),
                     header_y + 5), color=(0.5, 0.5, 0.5))
    row_y = header_y + 30.0
    for x, (_h, value, field) in zip(xs, cols):
        if value is None:
            continue
        s.put(x, row_y, value, 9.5, "helv",
              field if field in truth_map else None, truth_map.get(field))
    return DocRecord("pay_stub", "generator_stub_y", s.bytes(), s.truth,
                     corner=p.get("corner"))


def make_stub(style: str, ctx: dict[str, Any]) -> DocRecord:
    """One generator pay stub from a scenario context.

    ctx keys: name, org, tag, pay_date (ISO), start/end (ISO or unusable print string),
    freq, hours, rate, gross, net, plus corner switches.
    """
    hours, rate, gross = ctx.get("hours"), ctx.get("rate"), ctx["gross"]
    truth: dict[str, Any] = {"person_name": ctx["name"], "pay_date": ctx["pay_date"],
                             "pay_frequency": ctx["freq"], "gross_pay": gross,
                             "net_pay": ctx["net"]}
    if ctx.get("start_iso"):
        truth["pay_period_start"] = ctx["start_iso"]
    if ctx.get("end_iso"):
        truth["pay_period_end"] = ctx["end_iso"]
    if hours is not None:
        truth["regular_hours"] = hours
    if rate is not None:
        truth["hourly_rate"] = rate
    if ctx.get("month_only_date"):
        truth.pop("pay_date")  # printed "YYYY-MM": no day exists to hold
    corner = ctx.get("corner")

    if style == "x":
        printed: dict[str, tuple[str, str | None]] = {
            "Team Member:": (ctx["name"], "person_name"),
            "Check Date:": (ctx["pay_date_print"], "pay_date"),
            "Period Start:": (ctx["start_print"], "pay_period_start"),
            "Period End:": (ctx["end_print"], "pay_period_end"),
            "Pay Basis:": (ctx["freq"], "pay_frequency"),
        }
        if hours is not None:
            printed["Hours (Reg):"] = (str(hours), "regular_hours")
        if rate is not None:
            printed["Rate/Hr:"] = (_money(rate), "hourly_rate")
        if ctx.get("rate_bait"):
            printed["Rate of Pay:"] = (_money(gross), None)
        printed["Wages this Period:"] = (_money(gross), "gross_pay")
        printed["Take-Home:"] = (_money(ctx["net"]), "net_pay")
        return stub_x({"org": ctx["org"], "tag": ctx["tag"], "truth": truth,
                       "printed": printed, "corner": corner,
                       "split_field": ctx.get("split_field")})

    side = {
        "EMPLOYEE": (ctx["name"], "person_name"),
        "PAY DATE": (ctx["pay_date_print"], "pay_date"),
    }
    if ctx.get("start_print"):
        side["PERIOD OPEN"] = (ctx["start_print"], "pay_period_start")
    else:
        truth.pop("pay_period_start", None)
    side["PERIOD CLOSE"] = (ctx["end_print"], "pay_period_end")
    side["PAY BASIS"] = (ctx["freq"], "pay_frequency")
    table = [
        ("EARNING", "Regular", None),
        ("HOURS", None if hours is None else str(hours), "regular_hours"),
        ("RATE", None if rate is None else _money(rate), "hourly_rate"),
        ("WAGES THIS PERIOD", ctx.get("gross_print", _money(gross)), "gross_pay"),
    ]
    net_extra = [("NET DUE", _money(ctx["net"]), "net_pay")]
    return stub_y({"org": ctx["org"], "tag": ctx["tag"], "truth": truth,
                   "side": side, "table": table + net_extra, "corner": corner})


# =====================================================================================
# generator styles -- benefit letter A/B/C
# =====================================================================================
def benefit_a(p: dict[str, Any]) -> DocRecord:
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Benefit Award Notice", p["tag"])
    rows = [
        (40, 132, "RECIPIENT", p["name"], "person_name", None),
        (360, 132, "LETTER DATE", p["date_print"], "document_date", p["date_gold"]),
        (40, 192, "MONTHLY AMOUNT", p["amount_print"], "monthly_benefit", p["amount"]),
        (240, 192, "FREQUENCY", "monthly", "benefit_frequency", None),
    ]
    for x, y, label, value, field, gold in rows:
        s.put(x, y, label, 7.5, "hebo")
        s.put(x, y + 15.0, value, 10.0, "helv", field, gold)
    return DocRecord("benefit_letter", "generator_benefit_a", s.bytes(), s.truth,
                     corner=p.get("corner"))


def benefit_b(p: dict[str, Any]) -> DocRecord:
    """Letterhead prose with inline serif labels."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Notice of Award", p["tag"], font="tibo")
    rows = [
        ("Notice Date:", p["date_print"], "document_date", p["date_gold"]),
        ("Beneficiary of Record:", p["name"], "person_name", None),
        ("Monthly Award:", p["amount_print"], "monthly_benefit", p["amount"]),
        ("Paid:", "monthly", "benefit_frequency", None),
    ]
    y = 150.0
    for label, value, field, gold in rows:
        s.put(54, y, label, 11.0, "tibo")
        lw = fitz.get_text_length(label, fontname="tibo", fontsize=11.0)
        s.put(54 + lw + 8, y, value, 11.0, "tiro", field, gold)
        y += 30.0
    s.put(54, y + 12, "This award continues until superseded by a later notice.",
          9.0, "tiro")
    return DocRecord("benefit_letter", "generator_benefit_b", s.bytes(), s.truth,
                     corner=p.get("corner"))


def benefit_c(p: dict[str, Any]) -> DocRecord:
    """Caption grid, Courier."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Award Statement", p["tag"], font="cobo")
    cells = [
        (44, 150, p["name"], "RECIPIENT OF RECORD", "person_name", None),
        (330, 150, p["date_print"], "STATEMENT ISSUED", "document_date", p["date_gold"]),
        (44, 220, p["amount_print"], "AMOUNT EACH MONTH", "monthly_benefit", p["amount"]),
        (330, 220, "monthly", "CADENCE", "benefit_frequency", None),
    ]
    for x, y, value, caption, field, gold in cells:
        s.put(x, y, value, 10.0, "cour", field, gold)
        s.put(x, y + 12.0, caption, 7.0, "cobo")
    return DocRecord("benefit_letter", "generator_benefit_c", s.bytes(), s.truth,
                     corner=p.get("corner"))


# =====================================================================================
# generator styles -- gig statement A/B/C
# =====================================================================================
def gig_a(p: dict[str, Any]) -> DocRecord:
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Monthly Earnings Statement", p["tag"])
    rows = [
        (40, 132, "WORKER", p["name"], "person_name", None),
        (360, 132, "STATEMENT MONTH", p["month"], "statement_month", None),
        (40, 192, "GROSS RECEIPTS", p["receipts_print"], "gross_receipts", p["receipts"]),
        (240, 192, "PLATFORM FEES", p["fees_print"], "platform_fees", p["fees"]),
    ]
    for x, y, label, value, field, gold in rows:
        s.put(x, y, label, 7.5, "hebo")
        s.put(x, y + 15.0, value, 10.0, "helv", field, gold)
    return DocRecord("gig_statement", "generator_gig_a", s.bytes(), s.truth,
                     corner=p.get("corner"))


def gig_b(p: dict[str, Any]) -> DocRecord:
    """Dashboard: 10pt bold caps labels (outside the size gate), value to the right."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Partner Earnings Dashboard (print view)", p["tag"])
    rows = [
        ("PARTNER", p["name"], "person_name", None),
        ("REPORTING MONTH", p["month"], "statement_month", None),
        ("TOTAL COLLECTED", p["receipts_print"], "gross_receipts", p["receipts"]),
        ("SERVICE CHARGES", p["fees_print"], "platform_fees", p["fees"]),
    ]
    y = 140.0
    for label, value, field, gold in rows:
        s.put(46, y, label, 10.0, "hebo")
        s.put(240, y, value, 10.0, "helv", field, gold)
        y += 34.0
    return DocRecord("gig_statement", "generator_gig_b", s.bytes(), s.truth,
                     corner=p.get("corner"))


def gig_c(p: dict[str, Any]) -> DocRecord:
    """Compact inline: colon labels, small type."""
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Earnings Summary", p["tag"], font="cobo")
    rows = [
        ("Worker on record:", p["name"], "person_name", None),
        ("Covers:", p["month"], "statement_month", None),
        ("Collected before fees:", p["receipts_print"], "gross_receipts", p["receipts"]),
        ("Fees withheld:", p["fees_print"], "platform_fees", p["fees"]),
    ]
    y = 150.0
    for label, value, field, gold in rows:
        s.put(48, y, label, 8.5, "cobo")
        lw = fitz.get_text_length(label, fontname="cobo", fontsize=8.5)
        s.put(48 + lw + 8, y, value, 9.5, "cour", field, gold)
        y += 24.0
    return DocRecord("gig_statement", "generator_gig_c", s.bytes(), s.truth,
                     corner=p.get("corner"))


# =====================================================================================
# generator -- gig corroboration (bank deposit summary), utility bill, garbage page
# =====================================================================================
def corrob_gen(p: dict[str, Any]) -> DocRecord:
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Deposit History Summary", p["tag"])
    s.put(40, 132, "ACCOUNT HOLDER", 7.5, "hebo")
    s.put(40, 147, p["name"], 10.0, "helv", "person_name")
    s.put(40, 190, "Deposits credited from gig platform payouts:", 9.0, "helv")
    y = 212.0
    for date_text, amount in p["deposits"]:
        s.put(52, y, date_text, 9.0, "helv")
        s.put(180, y, amount, 9.0, "helv")
        y += 16.0
    s.put(40, y + 10, f"Total for period: {p['total']}", 9.0, "hebo")
    return DocRecord("gig_income_corroboration", "generator_corroboration",
                     s.bytes(), s.truth,
                     note="no reachable extraction field exists for this type today; "
                          "the logic layer receives person_name from truth_fields")


def utility_bill(p: dict[str, Any]) -> DocRecord:
    s = Sheet()
    s.watermark()
    s.chrome(p["org"], "Monthly Statement", p["tag"])
    rows = [
        (40, 132, "ACCOUNT HOLDER", p["name"]),
        (360, 132, "STATEMENT DATE", p["date"]),
        (40, 192, "SERVICE ADDRESS", p["address"]),
        (40, 252, "AMOUNT DUE", p["amount"]),
        (240, 252, "DUE DATE", p["due"]),
    ]
    for x, y, label, value in rows:
        s.put(x, y, label, 7.5, "hebo")
        s.put(x, y + 15.0, value, 10.0, "helv")
    return DocRecord("utility_bill", "generator_utility", s.bytes(), s.truth,
                     note="out-of-scope type: extraction has no field table for it and "
                          "the truth feeds the logic layer nothing")


def garbage_page(doc_type: str, seed: str) -> DocRecord:
    """A page whose text layer exists but carries no readable statement: shredded
    photocopy noise. Every reachable field is expect_absent -- any value emitted for
    this page is an invention."""
    rng = random.Random(seed)
    s = Sheet()
    glyphs = "#@%&*+=~^<>|/\\"
    consonants = "bcdfghjklmnpqrstvwxz"
    y = 90.0
    while y < 740.0:
        x = 40.0 + rng.random() * 60.0
        chunks = []
        for _ in range(rng.randint(3, 7)):
            token = "".join(rng.choice(consonants + glyphs) for _ in range(rng.randint(2, 9)))
            chunks.append(token)
        s.put(x, y, " ".join(chunks), 6.0 + rng.random() * 8.0, "helv")
        y += 14.0 + rng.random() * 12.0
    for _ in range(6):
        x0 = 40 + rng.random() * 400
        y0 = 100 + rng.random() * 560
        s.page.draw_rect(fitz.Rect(x0, y0, x0 + 60 + rng.random() * 120, y0 + 8 +
                                   rng.random() * 20), color=(0.15, 0.15, 0.15),
                         fill=(0.2, 0.2, 0.2))
    return DocRecord(doc_type, "generator_garbage", s.bytes(), [],
                     deviation="unreadable_garbage",
                     note="text layer present but content-free; a correct reader "
                          "abstains on every field")


# =====================================================================================
# real carriers -- parameterized fills (technique lifted from make_filled_forms.py)
# =====================================================================================
def _anchor(page: fitz.Page, needle: str, occurrence: int = 0) -> fitz.Rect:
    hits = page.search_for(needle)
    if not hits or occurrence >= len(hits):
        raise SystemExit(f"anchor {needle!r} (occ {occurrence}) not found on page "
                         f"{page.number + 1}")
    return hits[occurrence]


def _put_at(page: fitz.Page, spec: dict[str, Any]) -> list[float]:
    rect = _anchor(page, spec["anchor"], spec.get("occ", 0))
    point = fitz.Point(rect.x1 + spec.get("dx", 3.0), rect.y1 - 1.5 + spec.get("dy", 0.0))
    if "abs_x" in spec:
        point.x = spec["abs_x"]
    size = spec.get("size", 8.0)
    font = spec.get("font", "helv")
    page.insert_text(point, spec["text"], fontsize=size, fontname=font, color=INK)
    return _text_bbox(point.x, point.y, spec["text"], size, font)


def fill_seattle(p: dict[str, Any]) -> DocRecord:
    """Seattle Housing employment verification (flat overlay).

    p: name, date_iso (or date_print for undatable), employer, addr1, addr2, job,
    rate (or None), hours (or None), signer, circle_hourly.
    """
    doc = fitz.open(RAW_DIR / "seattle_housing_employment_verification_blank.pdf")
    page = doc[0]
    truth: list[dict[str, Any]] = []
    date_print = p.get("date_print") or _us(p["date_iso"])

    def put(spec: dict[str, Any], field: str | None = None, gold: Any = None) -> None:
        bbox = _put_at(page, spec)
        if field:
            truth.append(_tf(field, gold if gold is not None else spec["text"], 1, bbox))

    put({"anchor": "Head of Household Name:", "text": p["name"], "size": 10, "dx": 8},
        "person_name", p["name"])
    put({"anchor": "Date:", "occ": 0, "text": date_print, "size": 10, "dx": 6},
        "document_date", p.get("date_iso") or p.get("date_gold"))
    put({"anchor": "(Name & address of employer)", "text": p["employer"],
         "abs_x": 125, "dy": 16, "size": 9})
    put({"anchor": "(Name & address of employer)", "text": p["addr1"],
         "abs_x": 125, "dy": 31, "size": 9})
    put({"anchor": "Employee Name:", "text": p["name"], "dx": 5})
    put({"anchor": "Job Title:", "text": p["job"], "dx": 5})
    put({"anchor": "Employed:", "occ": 1, "text": p["since"], "dx": 6})
    if p.get("rate") is not None:
        put({"anchor": "Current Wages/Salary: $", "text": _money(p["rate"]), "dx": 2},
            "hourly_rate", p["rate"])
    if p.get("hours") is not None:
        put({"anchor": "Average # of regular hours per week:", "text": str(p["hours"]),
             "dx": 5}, "weekly_hours", p["hours"])
    put({"anchor": "Employer’s Signature", "text": p["signer"], "abs_x": 120,
         "dy": -13, "size": 10, "font": "heit"})
    put({"anchor": "Employer’s Printed Name", "text": p["signer"], "abs_x": 330,
         "dy": -13, "size": 9})
    put({"anchor": "Employer’s Printed Name", "text": date_print, "abs_x": 500,
         "dy": -13, "size": 9})
    put({"anchor": "Employer (Company) Name and Address",
         "text": f"{p['employer']}, {p['addr1']}", "abs_x": 150, "dy": -13, "size": 8})
    marked_only = {}
    if p.get("rate") is not None and p.get("circle_hourly", True):
        rect = _anchor(page, "hourly", 0)
        page.draw_oval(fitz.Rect(rect.x0 - 4, rect.y0 - 2.5, rect.x1 + 4, rect.y1 + 2.5),
                       color=INK, width=1.1)
        marked_only["wage_basis"] = {
            "value_by_mark": "hourly",
            "why_unscored": "the basis exists only as a drawn circle on a printed menu; "
                            "emitting the word under the mark would credit menu-reading"}
    data = doc.tobytes(deflate=True)
    doc.close()
    return DocRecord("employment_letter", "seattle_housing", data, truth,
                     marked_only=marked_only,
                     note="Seattle Housing Authority blank; agency name/fax on the page "
                          "are publisher identity, not the employer. Curly apostrophes "
                          "are the form's own printed captions.")


def fill_mnhousing(p: dict[str, Any]) -> DocRecord:
    """MN Housing employment verification (flat overlay). States weekly hours and a
    gross wage per circled period, but NO base hourly rate -- the only $/hr on the page
    is the overtime rate, retained as the form's own trap."""
    doc = fitz.open(RAW_DIR / "mnhousing_employment_verification_blank.pdf")
    page = doc[0]
    truth: list[dict[str, Any]] = []
    date_print = p.get("date_print") or f"{int(p['date_iso'][5:7])}/{int(p['date_iso'][8:10])}/{p['date_iso'][:4]}"

    def put(spec: dict[str, Any], field: str | None = None, gold: Any = None) -> None:
        bbox = _put_at(page, spec)
        if field:
            truth.append(_tf(field, gold if gold is not None else spec["text"], 1, bbox))

    put({"anchor": "TO:", "text": p["employer"], "abs_x": 95, "dy": 26, "size": 9})
    put({"anchor": "Applicant/Tenant Name", "text": p["name"], "abs_x": 100,
         "dy": -13, "size": 9})
    put({"anchor": "Employee Name:", "text": p["name"], "dx": 8}, "person_name", p["name"])
    put({"anchor": "Job Title:", "text": p["job"], "dx": 8})
    put({"anchor": "Presently Employed:", "occ": 0, "text": "X", "dx": 32})
    put({"anchor": "Date First Employed", "text": p["since"], "dx": 6})
    put({"anchor": "Current gross wages/salary:", "text": _money(p["wage"]), "dx": 14})
    put({"anchor": "Average # of regular hours per week:", "text": str(p["hours"]),
         "dx": 6}, "weekly_hours", p["hours"])
    put({"anchor": "Overtime Rate:", "text": _money(p["overtime"]), "dx": 14})
    put({"anchor": "Signature:", "text": p["signer"], "abs_x": 200, "dy": -2,
         "size": 10, "font": "heit"})
    put({"anchor": "Print your name:", "text": p["signer"], "abs_x": 200, "dy": -2,
         "size": 9})
    put({"anchor": "Date:", "occ": 1, "text": date_print, "dx": 10, "size": 9},
        "document_date", p.get("date_iso") or p.get("date_gold"))
    rect = _anchor(page, "semi-monthly", 0)
    page.draw_oval(fitz.Rect(rect.x0 - 3, rect.y0 - 2.5, rect.x1 + 3, rect.y1 + 2.5),
                   color=INK, width=1.1)
    data = doc.tobytes(deflate=True)
    doc.close()
    return DocRecord(
        "employment_letter", "mnhousing", data, truth,
        marked_only={"wage_basis": {
            "value_by_mark": "semi-monthly",
            "why_unscored": "drawn circle on a printed fourteen-word menu"}},
        note="TRAP RETAINED: the overtime rate is the only per-hour figure on the page; "
             "hourly_rate is expect_absent and the overtime number is its natural wrong "
             "answer.")


# WA DSHS 14252 -- real AcroForm; values live in widget annotations, never flattened.
_DSHS_TEXT_WIDGETS = {
    "DATE": "date_print",
    "EMPLOYEES NAME": "name",
    "EMPLOYERS NAME": "employer",
    "EMPLOYEES JOB TITLE": "job",
    "EMPLOYERS ADDRESS": "addr",
    "DATE EMPLOYEE STARTED WORK": "since",
    "AVERAGE HOURS PER WEEK": "hours_text",
    "RATE OF PAY OR SALARY HOURLY DAILY OR PIECE RATE": "rate_text",
    "EMPLOYERREPRESENTATIVES PRINTED NAME AND TITLE": "signer",
    "DATE of Employer / Representative's Signature": "date_print",
    "PHONE NUMBER": "phone",
}


def fill_wa_dshs(p: dict[str, Any]) -> DocRecord:
    doc = fitz.open(RAW_DIR / "wa_dshs_14252_employment_verification.pdf")
    values = dict(p)
    values.setdefault("date_print", _us(p["date_iso"]) if p.get("date_iso") else p["date_gold"])
    values["hours_text"] = str(p["hours"])
    values["rate_text"] = f"${_money(p['rate'])} hourly"
    values.setdefault("addr", "1408 SE Mill Plain Blvd, Vancouver, WA 98683")
    values.setdefault("phone", "(360) 555-0177")
    filled = []
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name or ""
            if widget.field_type_string == "Text" and name in _DSHS_TEXT_WIDGETS:
                widget.field_value = str(values[_DSHS_TEXT_WIDGETS[name]])
                widget.update()
                filled.append(name)
    data = doc.tobytes(deflate=True)
    doc.close()
    # Truth: what a reader of the RENDERED form holds. bbox is nominal (widget rects are
    # real boxes but we record a stable placeholder per field -- traceability needs the
    # four numbers, and the widget grid is not part of what this corpus scores).
    nominal = [72.0, 700.0, 220.0, 712.0]
    truth = [
        _tf("person_name", p["name"], 1, nominal),
        _tf("weekly_hours", p["hours"], 1, nominal),
        _tf("hourly_rate", p["rate"], 1, nominal),
    ]
    gold_date = p.get("date_iso") or p.get("date_gold")
    if gold_date:
        truth.append(_tf("document_date", gold_date, 1, nominal))
    return DocRecord(
        "employment_letter", "wa_dshs_acroform", data, truth,
        note="real AcroForm filled through its own widgets (never flattened). Field "
             "values live in widget annotations, NOT the page content stream, so "
             "today's text-layer extractor sees the blank form -- the T18 backlog. "
             f"widgets filled: {sorted(set(filled))}")


def fill_orangeusd(p: dict[str, Any]) -> DocRecord:
    """Orange USD sample pay stub grid (flat overlay). A monthly certificated stub:
    'Rate of Pay' holds the MONTHLY salary (equal to gross) and 'Hours/Units' holds
    working DAYS -- the two baits are filled at most one per instance, per the
    one-corner-per-document rule."""
    doc = fitz.open(RAW_DIR / "orangeusd_sample_paystub.pdf")
    page = doc[0]
    truth: list[dict[str, Any]] = []

    def put(spec: dict[str, Any], field: str | None = None, gold: Any = None) -> None:
        bbox = _put_at(page, spec)
        if field:
            truth.append(_tf(field, gold if gold is not None else spec["text"], 1, bbox))

    gross, net = 4812.00, 4166.12
    put({"anchor": "Employee Name", "occ": 0, "text": p["name"], "abs_x": 30,
         "dy": 9, "size": 6.5}, "person_name", p["name"])
    put({"anchor": "District Name", "occ": 0, "text": p["district"], "abs_x": 213,
         "dy": 9, "size": 6.5})
    put({"anchor": "Payroll Issue Date", "occ": 0, "text": _us(p["date_iso"]),
         "abs_x": 94, "dy": 8, "size": 6}, "pay_date", p["date_iso"])
    put({"anchor": "Payroll Ending Date", "occ": 0, "text": _us(p["date_iso"]),
         "abs_x": 155, "dy": 8, "size": 6}, "pay_period_end", p["date_iso"])
    put({"anchor": "Description", "occ": 0, "text": "REGULAR EARNINGS", "abs_x": 34,
         "dy": 12, "size": 6})
    corner = None
    if p.get("rate_bait"):
        corner = "salary_as_rate_bait"
        put({"anchor": "Rate of Pay", "occ": 0, "text": _money(gross), "abs_x": 103,
             "dy": 12, "size": 6})
    if p.get("days_bait"):
        corner = "hours_units_days_bait"
        put({"anchor": "Hours/Units", "occ": 0, "text": "21.00", "abs_x": 168,
             "dy": 12, "size": 6})
    put({"anchor": "Description", "occ": 0, "text": _money(gross), "abs_x": 224,
         "dy": 12, "size": 6})
    put({"anchor": "Description", "occ": 2, "text": "STRS RETIREMENT", "abs_x": 34,
         "dy": 12, "size": 6})
    put({"anchor": "Description", "occ": 2, "text": "553.38", "abs_x": 106, "dy": 12,
         "size": 6})
    put({"anchor": "Description", "occ": 3, "text": "UNION DUES", "abs_x": 166,
         "dy": 12, "size": 6})
    put({"anchor": "Description", "occ": 3, "text": "92.50", "abs_x": 228, "dy": 12,
         "size": 6})
    put({"anchor": "Gross Pay", "occ": 0, "text": _money(gross), "abs_x": 101,
         "dy": 23, "size": 6}, "gross_pay", gross)
    put({"anchor": "NET PAY", "occ": 0, "text": _money(net), "abs_x": 538, "dy": 12,
         "size": 8}, "net_pay", net)
    data = doc.tobytes(deflate=True)
    doc.close()
    return DocRecord(
        "pay_stub", "orangeusd", data, truth, corner=corner,
        note="monthly certificated stub: issue date == ending date; NO explicit pay "
             "frequency is printed anywhere (the CH-INCOME-001 explicit-frequency rule "
             "therefore cannot annualize this stub on its own). "
             + ("'Rate of Pay' 4,812.00 is the monthly salary -- hourly_rate must stay "
                "abstained (post-it-008)." if p.get("rate_bait") else "")
             + ("'Hours/Units' 21.00 is working DAYS -- regular_hours must stay "
                "abstained." if p.get("days_bait") else ""))


def fill_kcha_corrob(p: dict[str, Any]) -> DocRecord:
    """KCHA Section-8 packet, PART III income page only (page-8 excerpt overlay), used
    as independent corroboration of gig income: member name, source, monthly amount."""
    doc = fitz.open(RAW_DIR / "kcha_section8_doc21.pdf")
    doc.select([7])
    page = doc[0]
    truth: list[dict[str, Any]] = []

    emp = _anchor(page, "EMPLOYMENT/WAGES")
    page.insert_text(fitz.Point(emp.x0 - 30, emp.y1 - 1.5), "X", fontsize=9,
                     fontname="helv", color=INK)
    name_h = _anchor(page, "NAME OF FAMILY MEMBER")
    source_h = _anchor(page, "SOURCE OF INCOME")
    gross_h = _anchor(page, "GROSS AMT OF")
    month_h = _anchor(page, "PER MONTH")
    row_y = name_h.y1 + 16.0
    page.insert_text(fitz.Point(name_h.x0, row_y), p["name"], fontsize=7.5,
                     fontname="helv", color=INK)
    truth.append(_tf("person_name", p["name"], 1,
                     _text_bbox(name_h.x0, row_y, p["name"], 7.5, "helv")))
    page.insert_text(fitz.Point(source_h.x0 - 2, row_y), p["source"], fontsize=7.5,
                     fontname="helv", color=INK)
    page.insert_text(fitz.Point(gross_h.x0 + 4, row_y), p["amount"], fontsize=7.5,
                     fontname="helv", color=INK)
    page.insert_text(fitz.Point(month_h.x0 + 14, row_y), "X", fontsize=7.5,
                     fontname="helv", color=INK)

    def put(spec: dict[str, Any]) -> None:
        _put_at(page, spec)

    put({"anchor": "PERSON EMPLOYED", "occ": 0, "text": p["name"], "abs_x": 190,
         "dy": -2, "size": 9})
    put({"anchor": "EMPLOYER'S NAME", "occ": 0, "text": p["platform"], "abs_x": 190,
         "dy": -2, "size": 9})
    note_extra = ""
    if p.get("date_note"):
        put({"anchor": "TELEPHONE #", "occ": 0, "text": p["date_note"], "abs_x": 190,
             "dy": 12, "size": 9})
        note_extra = (f" A verification date '{p['date_note']}' is written on the page; "
                      "the reasoning layer has no date field for this document type, so "
                      "the staleness it states is structurally invisible -- recorded as "
                      "a discovered gap, not scored as one.")
    data = doc.tobytes(deflate=True)
    doc.close()
    return DocRecord(
        "gig_income_corroboration", "kcha_packet", data, truth,
        deviation=p.get("deviation"),
        note="KCHA recertification packet page 8 (PART III) as returned by a resident: "
             "one X on EMPLOYMENT/WAGES, one chart row, employer block." + note_extra)


# =====================================================================================
# scenario context helpers
# =====================================================================================
NAMES = [
    "Mara Voss", "Elio Brandt", "Tamsin Reyes", "Colm Ferris", "Adaeze Okon",
    "Petra Lindqvist", "Rufus Adler", "Ines Marchetti", "Dario Selk", "Yuki Tanahara",
    "Odette Brill", "Casper Nwosu", "Livia Grant", "Emrys Vale", "Sana Idrisov",
    "Theo Marden", "Priya Chandrasek", "Jonas Feld", "Aster Colvin", "Renate Osei",
    "Milo Draper", "Halima Yusuf", "Sorrel Antone", "Kaveh Rostami", "Bess Whitlow",
    "Arlo Jensen", "Noor Haddad", "Felix Trask", "Imara Solon", "Gideon Park",
    "Wren Castellan", "Zofia Brenner", "Hollis Nakamura", "Delia Fontaine", "Barnaby Cole",
    "Suvi Aaltonen", "Ezra Mbeki", "Coralie Dunn", "Anselm Rijker", "Freya Woodard",
    "Nora Quill", "Idris Fenwick", "Maribel Santos", "Oskar Lindt", "Tallis Grey",
    "Juniper Wolde", "Ansel Marek", "Roxana Petrov", "Corin Vasquez", "Amara Diallo",
]
EMPLOYERS = [
    "Bluestone Bindery", "Halcyon Transit Co", "Fernbrook Kitchens", "Quarry Lane Press",
    "Northtide Fisheries", "Copperbeam Electric", "Willowmere Care", "Saltbox Grocers",
    "Ironvale Logistics", "Meridian Stitchworks", "Larkspur Foods", "Granite Row Cafe",
    "Tidewalk Marine", "Cinder & Oak", "Pelham Courier", "Brightwell Nursery",
    "Vantage Roofing Co", "Stonebridge Deli", "Harrow & Finch", "Cloverfield Dairy",
    "Redloam Landscaping", "Gullwing Print Shop", "Basalt Brewing", "Milldale Textiles",
    "Owl Creek Outfitters",
]
AGENCIES = ["Commonwealth Family Support Office", "Harbor County Assistance Bureau",
            "Metro Benefits Administration"]
PLATFORMS = ["ParcelDash", "RideMoss", "CartHopper"]

CURRENT_PAY = ("2026-06-15", "2026-06-28", "2026-07-03")   # start, end, pay date
LETTER_DATE = "2026-06-24"
APP_DATE = "2026-07-08"
BENEFIT_DATE = "2026-07-02"
GIG_MONTH = "2026-06"


def wage_ctx(i: int, hours: int | None, rate: float | None, freq: str = "biweekly",
             gross: float | None = None, **kw: Any) -> dict[str, Any]:
    """Context for one generator stub. gross defaults to hours*rate (cent-exact)."""
    if gross is None:
        gross = round(hours * rate, 2)
    net = round(gross * 0.81, 2)
    start, end, pay = kw.pop("dates", CURRENT_PAY)
    ctx = {
        "name": NAMES[i], "org": EMPLOYERS[i % len(EMPLOYERS)], "tag": f"SC-{i + 1:02d}",
        "freq": freq, "hours": hours, "rate": rate, "gross": gross, "net": net,
        "pay_date": pay, "pay_date_print": pay,
        "start_iso": start, "start_print": start,
        "end_iso": end, "end_print": end,
    }
    ctx.update(kw)
    return ctx


# =====================================================================================
# set assembly
# =====================================================================================
class SetBuilder:
    def __init__(self, index: int, slug: str, layer: int, scenario: str, mix: str,
                 size: int | None, role: str = "dev") -> None:
        self.sid = f"S{index:02d}"
        self.index = index
        self.slug = slug
        self.layer = layer
        self.scenario = scenario
        self.mix = mix
        self.size = size
        self.role = role
        self.docs: list[DocRecord] = []
        self.expected_status = "READY_TO_REVIEW"
        self.expected_codes: list[str] = []
        self.expected_comparison = "below_or_equal"
        self.expected_income: float | None = None
        self.required: tuple[str, ...] = BASE_REQUIRED
        self.notes: list[str] = []

    @property
    def name(self) -> str:
        return NAMES[self.index - 1]

    def add(self, doc: DocRecord) -> DocRecord:
        self.docs.append(doc)
        return doc

    def expect(self, status: str, codes: list[str], comparison: str,
               income: float | None) -> None:
        self.expected_status = status
        self.expected_codes = sorted(set(codes))
        self.expected_comparison = comparison
        self.expected_income = income
        # arithmetic self-check against the frozen table, at build time
        if comparison == "below_or_equal":
            assert income is not None and self.size in LIMITS_60 \
                and income <= LIMITS_60[self.size], f"{self.sid}: bad boundary arithmetic"
        elif comparison == "above":
            assert income is not None and income > LIMITS_60[self.size], self.sid
        else:
            assert income is None or self.size not in LIMITS_60, self.sid


def _summary(i: int, style: str, size: int, name: str | None = None,
             curly: bool = False, app_date: str = APP_DATE) -> DocRecord:
    p = {"org": "Harborlight Housing Office", "tag": f"SC-{i:02d}",
         "name": name or NAMES[i - 1], "size": size,
         "address": f"{700 + i * 3} Marrow Bell Lane, Cambridge, MA 02139",
         "app_date": app_date, "curly": curly}
    return {"a": summary_a, "b": summary_b, "c": summary_c}[style](p)


def _benefit(i: int, style: str, amount: float, date_iso: str | None = BENEFIT_DATE,
             date_print: str | None = None, amount_print: str | None = None,
             corner: str | None = None) -> DocRecord:
    p = {"org": AGENCIES[i % 3], "tag": f"SC-{i:02d}", "name": NAMES[i - 1],
         "amount": amount, "amount_print": amount_print or _money(amount),
         "date_print": date_print or date_iso, "date_gold": date_iso, "corner": corner}
    # NOTE: when date_iso is None and date_print is "YYYY-MM", the builders record the
    # printed month string as the truth -- a month IS a true statement of what the page
    # says, and the reasoning layer treats it as month precision.
    return {"a": benefit_a, "b": benefit_b, "c": benefit_c}[style](p)


def _gig(i: int, style: str, receipts: float, fees: float, month: str = GIG_MONTH,
         name: str | None = None, receipts_print: str | None = None,
         corner: str | None = None) -> DocRecord:
    p = {"org": PLATFORMS[i % 3], "tag": f"SC-{i:02d}", "name": name or NAMES[i - 1],
         "month": month, "receipts": receipts,
         "receipts_print": receipts_print or _money(receipts),
         "fees": fees, "fees_print": _money(fees), "corner": corner}
    return {"a": gig_a, "b": gig_b, "c": gig_c}[style](p)


def _corrob_g(i: int, monthly: float) -> DocRecord:
    a, b = round(monthly * 0.6, 2), 0.0
    b = round(monthly - a, 2)
    return corrob_gen({"org": "Granite Harbor Savings", "tag": f"SC-{i:02d}",
                       "name": NAMES[i - 1],
                       "deposits": [("06/09/2026", _money(a)), ("06/23/2026", _money(b))],
                       "total": _money(monthly)})


def _letter(i: int, carrier: str, hours: int | None, rate: float | None,
            date_iso: str | None = LETTER_DATE, date_print: str | None = None,
            deviation: str | None = None, name: str | None = None) -> DocRecord:
    name = name or NAMES[i - 1]
    employer = EMPLOYERS[(i + 7) % len(EMPLOYERS)]
    if carrier == "seattle":
        doc = fill_seattle({"name": name, "date_iso": date_iso, "date_print": date_print,
                            "employer": employer, "addr1": "2217 Rainier Ave S, Seattle WA",
                            "job": "Associate", "since": "3/14/2023", "rate": rate,
                            "hours": hours, "signer": "Daniel Okafor"})
    elif carrier == "mnhousing":
        wage = round((hours or 36) * (rate or 19.0) * 26 / 24, 2)  # semi-monthly figure
        doc = fill_mnhousing({"name": name, "date_iso": date_iso, "date_print": date_print,
                              "employer": employer, "job": "Associate",
                              "since": "11/04/2021", "wage": wage,
                              "hours": hours if hours is not None else 36,
                              "overtime": round((rate or 19.0) * 1.5, 2),
                              "signer": "Lorna Prentiss"})
    else:
        doc = fill_wa_dshs({"name": name, "date_iso": date_iso, "date_gold": date_print,
                            "employer": employer, "job": "Grounds Crew",
                            "since": "02/03/2025", "hours": hours, "rate": rate,
                            "signer": "Gail Munson, Office Manager"})
        if date_print and len(date_print) == 7:
            # month-only widget: gold keeps the month string (a real statement of month)
            pass
    doc.deviation = deviation
    return doc


# =====================================================================================
# the matrix
# =====================================================================================
def build_sets() -> list[SetBuilder]:
    sets: list[SetBuilder] = []

    def new(index: int, slug: str, layer: int, scenario: str, mix: str,
            size: int | None, role: str = "dev") -> SetBuilder:
        b = SetBuilder(index, slug, layer, scenario, mix, size, role)
        sets.append(b)
        return b

    def required_for(mix: str) -> tuple[str, ...]:
        req = list(BASE_REQUIRED)
        if "B" in mix:
            req.append("benefit_letter")
        if "G" in mix:
            req.append("gig_income_corroboration")
        return tuple(req)

    # ---------------------------------------------------------------- Layer 1: W
    b = new(1, "w_complete", 1, "complete wage file", "W", 2)
    b.add(_summary(1, "a", 2))
    b.add(make_stub("x", wage_ctx(0, 76, 19.50)))
    b.add(_letter(1, "seattle", 38, 19.50))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 38532.00)

    b = new(2, "w_missing_summary", 1, "wage file, application summary missing", "W",
            None, role="sealed")
    b.add(make_stub("y", wage_ctx(1, 64, 18.25)))
    b.add(_letter(2, "wa_dshs", 32, 18.25))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "NO_FROZEN_THRESHOLD"],
             "no_frozen_threshold", 30368.00)
    b.notes.append("household size is stated nowhere, so no frozen threshold applies "
                   "even though the income is computable")

    b = new(3, "w_missing_stub", 1, "wage file, pay stub missing", "W", 2)
    b.add(_summary(3, "b", 2))
    b.add(_letter(3, "seattle", 32, 19.75))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING"], "below_or_equal", 32864.00)
    b.notes.append("wage income derives from the letter's hours x rate x 52 -- a "
                   "documented recurring wage even without a stub")

    b = new(4, "w_missing_letter", 1, "wage file, employment letter missing", "W", 3)
    b.add(_summary(4, "c", 3))
    b.add(make_stub("x", wage_ctx(3, 72, 21.00, corner="colon_inline_value")))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING"], "below_or_equal", 39312.00)
    b.notes.append("ONE stub only: the two-agreeing-stubs substitution cannot apply")

    # ---------------------------------------------------------------- Layer 1: WB
    b = new(5, "wb_complete", 1, "wage + benefit, complete", "WB", 3)
    b.add(_summary(5, "b", 3, curly=True))
    b.add(make_stub("x", wage_ctx(4, 76, 20.50, end_print="10/03/XX", end_iso=None,
                                  corner="masked_year_date")))
    b.add(_letter(5, "mnhousing", 38, 20.50))
    b.add(_benefit(5, "a", 850.00))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 50708.00)
    b.notes.append("the stub's period-end year is masked (10/03/XX): no truth value "
                   "exists for pay_period_end and any ISO emission is an invention")

    b = new(6, "wb_missing_summary", 1, "wage + benefit, summary missing", "WB", None)
    b.add(make_stub("y", wage_ctx(5, 70, 19.00, start_print="7/1/26", start_iso=None,
                                  corner="two_digit_year_date")))
    b.add(_letter(6, "wa_dshs", 35, 19.00))
    b.add(_benefit(6, "b", 640.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "NO_FROZEN_THRESHOLD"],
             "no_frozen_threshold", 42260.00)

    b = new(7, "wb_missing_stub", 1, "wage + benefit, stub missing", "WB", 3,
            role="sealed")
    b.add(_summary(7, "a", 3))
    b.add(_letter(7, "seattle", 36, 19.25))
    b.add(_benefit(7, "c", 725.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING"], "below_or_equal", 44736.00)

    b = new(8, "wb_missing_letter", 1, "wage + benefit, letter missing", "WB", 2)
    b.add(_summary(8, "b", 2))
    b.add(make_stub("x", wage_ctx(7, 68, 17.75)))
    b.add(_benefit(8, "a", 910.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING"], "below_or_equal", 42302.00)

    b = new(9, "wb_missing_benefit", 1, "wage + benefit income, benefit letter missing",
            "WB", 4)
    b.add(_summary(9, "c", 4))
    b.add(make_stub("x", wage_ctx(8, 80, 22.25, split_field="gross_pay",
                                  corner="digit_group_split")))
    b.add(_letter(9, "mnhousing", 40, 22.25))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING"], "below_or_equal", 46280.00)
    b.notes.append("the benefit award the summary declares has no letter behind it; "
                   "only the wage annualizes")

    # ---------------------------------------------------------------- Layer 1: WG
    b = new(10, "wg_complete", 1, "wage + gig, complete", "WG", 4)
    b.add(_summary(10, "a", 4))
    b.add(make_stub("y", wage_ctx(9, 72, 20.25)))
    b.add(_letter(10, "wa_dshs", 36, 20.25))
    b.add(_gig(10, "a", 1150.00, 0.00, corner="zero_amount"))
    b.add(fill_kcha_corrob({"name": NAMES[9], "source": f"Gig - {PLATFORMS[1]}",
                            "amount": _money(1150.00), "platform": PLATFORMS[1]}))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 51708.00)
    b.notes.append("complete by the organizer's conditional pattern, yet never READY "
                   "under this repo's conventions: a gig statement's coverage month has "
                   "no day (HH-004 precedent, KNOWN_EXTRA_REASONS), and the "
                   "corroboration document type has no date field at all -- both raise "
                   "DOCUMENT_UNDATABLE. Recorded as the corpus's expected truth.")

    b = new(11, "wg_missing_summary", 1, "wage + gig, summary missing", "WG", None)
    b.add(make_stub("x", wage_ctx(10, 64, 19.50)))
    b.add(_letter(11, "mnhousing", 32, 19.50))
    b.add(_gig(11, "b", 980.00, 88.20))
    b.add(_corrob_g(11, 980.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE",
                              "NO_FROZEN_THRESHOLD"], "no_frozen_threshold", 44208.00)

    b = new(12, "wg_missing_stub", 1, "wage + gig, stub missing", "WG", 3)
    b.add(_summary(12, "b", 3))
    b.add(_letter(12, "wa_dshs", 38, 17.10))
    b.add(_gig(12, "c", 1200.00, 96.00, corner="colon_inline_value"))
    b.add(fill_kcha_corrob({"name": NAMES[11], "source": f"Gig - {PLATFORMS[0]}",
                            "amount": _money(1200.00), "platform": PLATFORMS[0]}))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 48189.60)

    b = new(13, "wg_missing_letter", 1, "wage + gig, letter missing", "WG", 2)
    b.add(_summary(13, "c", 2))
    b.add(make_stub("y", wage_ctx(12, 70, 18.50)))
    b.add(_gig(13, "a", 875.00, 61.25))
    b.add(_corrob_g(13, 875.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 44170.00)

    b = new(14, "wg_missing_corroboration", 1, "wage + gig, corroboration missing",
            "WG", 3)
    b.add(_summary(14, "a", 3))
    b.add(make_stub("x", wage_ctx(13, 76, 19.00)))
    b.add(_letter(14, "mnhousing", 38, 19.00))
    b.add(_gig(14, "b", 1050.00, 94.50))
    b.expect("NEEDS_REVIEW", ["GIG_INCOME_UNCORROBORATED", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 50144.00)
    b.notes.append("the statement never satisfies its own corroboration: the missing "
                   "required corroboration surfaces in the pack's own vocabulary")

    # ---------------------------------------------------------------- Layer 1: WBG
    b = new(15, "wbg_complete", 1, "wage + benefit + gig, complete", "WBG", 5)
    b.add(_summary(15, "b", 5))
    b.add(make_stub("y", wage_ctx(14, 80, 21.50, end_print="09/14/XX", end_iso=None,
                                  corner="masked_year_date")))
    b.add(_letter(15, "wa_dshs", 40, 21.50))
    b.add(_benefit(15, "a", 780.00))
    b.add(_gig(15, "c", 990.00, 49.50))
    b.add(fill_kcha_corrob({"name": NAMES[14], "source": f"Gig - {PLATFORMS[0]}",
                            "amount": _money(990.00), "platform": PLATFORMS[0]}))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 65960.00)

    b = new(16, "wbg_missing_summary", 1, "wage + benefit + gig, summary missing",
            "WBG", None)
    b.add(make_stub("x", wage_ctx(15, 72, 18.00)))
    b.add(_letter(16, "seattle", 36, 18.00))
    b.add(_benefit(16, "b", 705.00))
    b.add(_gig(16, "a", 1100.00, 99.00, receipts_print="1 100.00",
               corner="thousands_separator_variant"))
    b.add(_corrob_g(16, 1100.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE",
                              "NO_FROZEN_THRESHOLD"], "no_frozen_threshold", 55356.00)

    b = new(17, "wbg_missing_stub", 1, "wage + benefit + gig, stub missing", "WBG", 4)
    b.add(_summary(17, "c", 4))
    b.add(_letter(17, "wa_dshs", 38, 19.90))
    b.add(_benefit(17, "c", 615.00))
    b.add(_gig(17, "b", 1010.00, 80.80))
    b.add(fill_kcha_corrob({"name": NAMES[16], "source": f"Gig - {PLATFORMS[2]}",
                            "amount": _money(1010.00), "platform": PLATFORMS[2]}))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 58822.40)

    b = new(18, "wbg_missing_letter", 1, "wage + benefit + gig, letter missing", "WBG",
            3, role="sealed")
    b.add(_summary(18, "a", 3))
    b.add(make_stub("x", wage_ctx(17, 74, 19.75, split_field="gross_pay",
                                  corner="digit_group_split")))
    b.add(_benefit(18, "a", 560.00))
    b.add(_gig(18, "c", 940.00, 84.60))
    b.add(_corrob_g(18, 940.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 55999.00)

    b = new(19, "wbg_missing_benefit", 1, "wage + benefit + gig, benefit letter missing",
            "WBG", 4)
    b.add(_summary(19, "b", 4, curly=True))
    b.add(make_stub("y", wage_ctx(18, 78, 20.00)))
    b.add(_letter(19, "mnhousing", 39, 20.00))
    b.add(_gig(19, "a", 1075.00, 96.75))
    b.add(_corrob_g(19, 1075.00))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 53460.00)

    b = new(20, "wbg_missing_corroboration", 1,
            "wage + benefit + gig, corroboration missing", "WBG", 5)
    b.add(_summary(20, "c", 5))
    b.add(make_stub("x", wage_ctx(19, 80, 19.25)))
    b.add(_letter(20, "seattle", 40, 19.25))
    b.add(_benefit(20, "b", 830.00))
    b.add(_gig(20, "b", 1250.00, 100.00, receipts_print="1 250.00",
               corner="thousands_separator_variant"))
    b.expect("NEEDS_REVIEW", ["GIG_INCOME_UNCORROBORATED", "DOCUMENT_UNDATABLE"],
             "below_or_equal", 65000.00)

    # ---------------------------------------------------------------- Layer 2
    b = new(21, "ps_expired", 2, "pay stub outside the 60-day window", "W", 2)
    b.add(_summary(21, "a", 2))
    b.add(make_stub("x", wage_ctx(20, 72, 19.50,
                                  dates=("2026-03-23", "2026-04-05", "2026-04-10"))))
    b.docs[-1].deviation = "expired"
    b.add(_letter(21, "mnhousing", 36, 19.50))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_NOT_CURRENT"], "below_or_equal", 36504.00)

    b = new(22, "ps_month_only", 2, "pay stub dated to the month only", "W", 2,
            role="sealed")
    ctx = wage_ctx(21, 76, 18.75)
    ctx.update(pay_date_print="2026-06", month_only_date=True,
               start_print="2026-06", start_iso=None, end_print="2026-06", end_iso=None)
    b.add(make_stub("x", ctx))
    b.docs[-1].deviation = "month_only_date"
    b.docs[-1].truth_fields.append(_tf("pay_date", "2026-06", 1,
                                       [46.0, 150.0, 120.0, 162.0]))
    b.add(_summary(22, "b", 2))
    b.add(_letter(22, "seattle", 38, 18.75))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 37050.00)
    b.notes.append("the month IS a true statement (2026-06), so it stays in "
                   "truth_fields; the 60-day window simply cannot be applied to it")

    b = new(23, "ps_unreadable_garbage", 2, "pay stub page is noise", "W", 2)
    b.add(_summary(23, "a", 2))
    b.add(garbage_page("pay_stub", "S23-stub"))
    b.add(_letter(23, "mnhousing", 36, 18.25))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE", "INCOME_NOT_COMPUTABLE"],
             "no_frozen_threshold", None)
    b.notes.append("a stub document EXISTS, so the letter-only wage path never runs; "
                   "with the stub unreadable no income is computable at all")

    b = new(24, "ps_image_scan", 2, "pay stub is an image-only scan", "W", 3)
    b.add(_summary(24, "b", 3))
    b.add(fill_orangeusd({"name": NAMES[23], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-06-30", "rate_bait": False,
                          "days_bait": False}).scanned())
    b.docs[-1].deviation = "image_scan"
    b.add(_letter(24, "seattle", 34, 19.25))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE", "INCOME_NOT_COMPUTABLE"],
             "no_frozen_threshold", None)

    b = new(25, "ps_second_stub_conflicting", 2, "second stub conflicts with the first",
            "W", 3)
    b.add(_summary(25, "c", 3))
    b.add(make_stub("x", wage_ctx(24, 76, 20.00)))
    b.add(fill_orangeusd({"name": NAMES[24], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-06-30", "rate_bait": True,
                          "days_bait": False}))
    b.docs[-1].deviation = "conflicting_total"
    b.add(_letter(25, "mnhousing", 38, 20.00))
    b.expect("NEEDS_REVIEW", ["PAY_STUB_TOTAL_CONFLICT"], "below_or_equal", 39520.00)
    b.notes.append("the generator stub reconciles with its own hours x rate and becomes "
                   "the recurring base; the orangeusd monthly figure is set aside")

    b = new(26, "ps_second_stub_consistent", 2, "second stub agrees with the first",
            "W", 2)
    b.add(_summary(26, "a", 2))
    b.add(make_stub("y", wage_ctx(25, 150, 32.08, freq="monthly",
                                  dates=("2026-06-01", "2026-06-30", "2026-06-30"))))
    b.add(fill_orangeusd({"name": NAMES[25], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-06-30", "rate_bait": False,
                          "days_bait": True}))
    b.add(_letter(26, "seattle", None, None))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 57744.00)
    b.notes.append("both stubs state 4,812.00; the letter deliberately states no hours "
                   "or rate (a monthly wage has no cent-exact weekly decomposition)")

    b = new(27, "el_expired", 2, "employment letter outside the 60-day window", "W", 2)
    b.add(_summary(27, "b", 2))
    b.add(make_stub("x", wage_ctx(26, 70, 19.50)))
    b.add(_letter(27, "seattle", 35, 19.50, date_iso="2026-05-02",
                  deviation="expired"))
    b.expect("NEEDS_REVIEW", ["EMPLOYMENT_LETTER_EXPIRED"], "below_or_equal", 35490.00)

    b = new(28, "el_month_only", 2, "employment letter dated to the month only", "W", 3)
    b.add(_summary(28, "c", 3))
    b.add(make_stub("y", wage_ctx(27, 76, 17.10)))
    b.add(_letter(28, "wa_dshs", 38, 17.10, date_iso=None, date_print="2026-06",
                  deviation="month_only_date"))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 33789.60)

    b = new(29, "el_unreadable_garbage", 2, "employment letter page is noise", "W", 2)
    b.add(_summary(29, "a", 2))
    b.add(make_stub("x", wage_ctx(28, 72, 18.25)))
    b.add(garbage_page("employment_letter", "S29-letter"))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE"], "below_or_equal", 34164.00)

    b = new(30, "el_image_scan", 2, "employment letter is an image-only scan", "W", 2)
    b.add(_summary(30, "b", 2))
    b.add(make_stub("y", wage_ctx(29, 68, 19.00)))
    b.add(_letter(30, "mnhousing", 34, 19.00).scanned())
    b.docs[-1].deviation = "image_scan"
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE"], "below_or_equal", 33592.00)

    b = new(31, "as_unreadable_garbage", 2, "application summary page is noise", "W",
            None)
    b.add(garbage_page("application_summary", "S31-summary"))
    b.add(make_stub("x", wage_ctx(30, 74, 18.50)))
    b.add(_letter(31, "seattle", 37, 18.50))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE", "NO_FROZEN_THRESHOLD"],
             "no_frozen_threshold", 35594.00)

    b = new(32, "as_image_scan", 2, "application summary is an image-only scan", "W",
            None)
    b.add(_summary(32, "a", 2).scanned())
    b.docs[-1].deviation = "image_scan"
    b.add(make_stub("y", wage_ctx(31, 66, 19.75)))
    b.add(_letter(32, "mnhousing", 33, 19.75))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE", "NO_FROZEN_THRESHOLD"],
             "no_frozen_threshold", 33891.00)

    b = new(33, "bl_expired", 2, "benefit letter outside the 60-day window", "WB", 3)
    b.add(_summary(33, "b", 3))
    b.add(make_stub("x", wage_ctx(32, 72, 19.25, end_print="6/28/26", end_iso=None,
                                  corner="two_digit_year_date")))
    b.add(_letter(33, "seattle", 36, 19.25))
    b.add(_benefit(33, "c", 700.00, date_iso="2026-04-20"))
    b.docs[-1].deviation = "expired"
    b.expect("NEEDS_REVIEW", ["DOCUMENT_NOT_CURRENT"], "below_or_equal", 44436.00)
    b.notes.append("an expired benefit letter still annualizes -- currency gates "
                   "readiness, not arithmetic -- so the income includes the benefit")

    b = new(34, "bl_month_only", 2, "benefit letter dated to the month only", "WB", 3,
            role="sealed")
    b.add(_summary(34, "c", 3))
    b.add(make_stub("y", wage_ctx(33, 70, 20.50)))
    b.add(_letter(34, "mnhousing", 35, 20.50))
    b.add(_benefit(34, "a", 655.00, date_iso=None, date_print="2026-06"))
    b.docs[-1].deviation = "month_only_date"
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 45170.00)

    b = new(35, "bl_unreadable_garbage", 2, "benefit letter page is noise", "WB", 4)
    b.add(_summary(35, "a", 4))
    b.add(make_stub("x", wage_ctx(34, 78, 19.50)))
    b.add(_letter(35, "seattle", 39, 19.50))
    b.add(garbage_page("benefit_letter", "S35-benefit"))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE"], "below_or_equal", 39546.00)
    b.notes.append("the unreadable benefit letter contributes nothing to income; only "
                   "the wage annualizes")

    b = new(36, "gs_month_only", 2, "gig statement covers a calendar month", "WG", 3)
    b.add(_summary(36, "b", 3))
    b.add(make_stub("y", wage_ctx(35, 72, 19.00)))
    b.add(_letter(36, "mnhousing", 36, 19.00))
    b.add(_gig(36, "c", 1020.00, 0.00, month="2026-05", corner="zero_amount"))
    b.docs[-1].deviation = "month_only_date"
    b.add(_corrob_g(36, 1020.00))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 47808.00)
    b.notes.append("named in the owner's matrix as its own row: the deviation "
                   "coincides with a gig statement's intrinsic month precision, so the "
                   "expectation matches the WG-complete baseline by construction")

    b = new(37, "gc_expired_dated", 2, "gig corroboration carries a stale date", "WG", 4)
    b.add(_summary(37, "a", 4))
    b.add(make_stub("x", wage_ctx(36, 74, 20.25)))
    b.add(_letter(37, "seattle", 37, 20.25))
    b.add(_gig(37, "a", 1105.00, 99.45))
    b.add(fill_kcha_corrob({"name": NAMES[36], "source": f"Gig - {PLATFORMS[1]}",
                            "amount": _money(1105.00), "platform": PLATFORMS[1],
                            "date_note": "Verified 01/12/2026",
                            "deviation": "expired_dated"}))
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNDATABLE"], "below_or_equal", 52221.00)
    b.notes.append("DISCOVERED GAP, recorded not scored: the corroboration page states "
                   "a January date -- stale under the 60-day convention -- but the "
                   "reasoning layer has no date field for this document type, so "
                   "staleness here is structurally invisible and the item can only "
                   "ever be 'undatable'")

    # ---------------------------------------------------------------- Layer 3
    b = new(38, "expired_letter_and_missing_corroboration", 3,
            "two reasons at once: stale letter, uncorroborated gig", "WG", 4,
            role="sealed")
    b.add(_summary(38, "b", 4))
    b.add(make_stub("x", wage_ctx(37, 72, 17.10)))
    b.add(_letter(38, "wa_dshs", 36, 17.10, date_iso="2026-04-30",
                  deviation="expired"))
    b.add(_gig(38, "b", 1150.00, 103.50))
    b.expect("NEEDS_REVIEW", ["EMPLOYMENT_LETTER_EXPIRED", "GIG_INCOME_UNCORROBORATED",
                              "DOCUMENT_UNDATABLE"], "below_or_equal", 45811.20)

    b = new(39, "stub_conflict_and_expired_letter", 3,
            "conflicting stubs and a stale letter together", "W", 2)
    b.add(_summary(39, "c", 2))
    b.add(make_stub("x", wage_ctx(38, 74, 19.50)))
    b.add(fill_orangeusd({"name": NAMES[38], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-06-30", "rate_bait": True,
                          "days_bait": False}))
    b.docs[-1].deviation = "conflicting_total"
    b.add(_letter(39, "seattle", 37, 19.50, date_iso="2026-05-05",
                  deviation="expired"))
    b.expect("NEEDS_REVIEW", ["PAY_STUB_TOTAL_CONFLICT", "EMPLOYMENT_LETTER_EXPIRED"],
             "below_or_equal", 37518.00)

    b = new(40, "all_documents_are_scans", 3, "every page is an image-only scan", "WG",
            None)
    b.add(_summary(40, "a", 3).scanned())
    ctx = wage_ctx(39, 70, 19.25)
    b.add(make_stub("x", ctx).scanned())
    b.add(_letter(40, "seattle", 35, 19.25).scanned())
    b.add(_gig(40, "a", 1000.00, 90.00).scanned())
    b.add(fill_kcha_corrob({"name": NAMES[39], "source": f"Gig - {PLATFORMS[1]}",
                            "amount": _money(1000.00),
                            "platform": PLATFORMS[1]}).scanned())
    for doc in b.docs:
        doc.deviation = "image_scan"
    b.expect("NEEDS_REVIEW", ["DOCUMENT_UNREADABLE", "INCOME_NOT_COMPUTABLE"],
             "no_frozen_threshold", None)
    b.notes.append("the four REQUIRED types raise unreadable; the gig statement, an "
                   "extra, blocks nothing -- an unreadable non-required page is "
                   "invisible to the presence check (recorded asymmetry)")

    b = new(41, "benefit_present_letter_missing_ready", 3,
            "the HH-003 redundancy rule: substituted letter, READY", "WB", 3)
    b.add(_summary(41, "a", 3))
    b.add(make_stub("y", wage_ctx(40, 150, 32.08, freq="monthly",
                                  dates=("2026-06-01", "2026-06-30", "2026-06-30"))))
    b.add(fill_orangeusd({"name": NAMES[40], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-06-30", "rate_bait": False,
                          "days_bait": True}))
    b.add(_benefit(41, "b", 900.00))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 68544.00)
    b.notes.append("ASSERTED READY: employment_letter is required and missing, but two "
                   "stubs stating the same gross already document the wage source "
                   "(constants.CONVENTIONS REDUNDANT_REQUIRED_DOCUMENT_DOES_NOT_BLOCK_"
                   "READINESS, the pack's own HH-003/HH-006 pattern)")

    b = new(42, "kitchen_sink", 3, "every deviation at once", "WBG", 4)
    b.add(_summary(42, "a", 4))
    b.add(_summary(42, "b", 4).scanned())
    b.docs[-1].deviation = "image_scan"
    b.add(make_stub("x", wage_ctx(41, 76, 19.75)))
    b.add(fill_orangeusd({"name": NAMES[41], "district": "CANYON GLEN UNIFIED",
                          "date_iso": "2026-03-31", "rate_bait": True,
                          "days_bait": False}))
    b.docs[-1].deviation = "expired_and_conflicting"
    b.add(_letter(42, "mnhousing", 38, 19.75, date_iso="2026-04-22",
                  deviation="expired"))
    b.add(_benefit(42, "c", 720.00, date_iso=None, date_print="2026-06"))
    b.docs[-1].deviation = "month_only_date"
    b.add(_gig(42, "b", 995.00, 89.55, name="Rosa Vann"))
    b.docs[-1].deviation = "person_name_mismatch"
    b.expect("NEEDS_REVIEW",
             ["DOCUMENT_UNREADABLE", "DOCUMENT_NOT_CURRENT", "PAY_STUB_TOTAL_CONFLICT",
              "EMPLOYMENT_LETTER_EXPIRED", "DOCUMENT_UNDATABLE",
              "GIG_INCOME_UNCORROBORATED", "PERSON_NAME_MISMATCH"],
             "below_or_equal", 59606.00)
    b.notes.append("one deviation per DOCUMENT, spread so each check fires: scan "
                   "summary copy (unreadable), expired+conflicting second stub, expired "
                   "letter, month-only benefit letter, mismatched gig worker name, "
                   "missing corroboration. The seven expected codes are the full list.")

    # ---------------------------------------------------------------- Layer 4
    b = new(43, "empty_file", 4, "no documents at all", "W", None)
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "INCOME_NOT_COMPUTABLE"],
             "no_frozen_threshold", None)

    b = new(44, "summary_only", 4, "application summary alone", "W", 2)
    b.add(_summary(44, "a", 2))
    b.expect("NEEDS_REVIEW", ["REQUIRED_DOCUMENT_MISSING", "INCOME_NOT_COMPUTABLE"],
             "no_frozen_threshold", None)
    b.notes.append("household size IS known, but with no income the comparison slot "
                   "still carries the no-threshold abstention")

    b = new(45, "out_of_scope_document", 4, "utility bill mixed into a complete file",
            "W", 2)
    b.add(_summary(45, "b", 2))
    b.add(make_stub("x", wage_ctx(44, 70, 19.25)))
    b.add(_letter(45, "mnhousing", 35, 19.25))
    b.add(utility_bill({"org": "Tidewater Electric Cooperative", "tag": "SC-45",
                        "name": NAMES[44],
                        "address": f"{835} Marrow Bell Lane, Cambridge, MA 02139",
                        "date": "2026-07-05", "amount": "94.18", "due": "2026-07-29"}))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 35035.00)
    b.notes.append("an out-of-scope document must not block a complete file; today it "
                   "does not ONLY because extraction reads nothing from an unknown type "
                   "(a readable extra with no date field would raise DOCUMENT_UNDATABLE "
                   "through the currency check -- recorded asymmetry)")

    b = new(46, "conflicting_summaries", 4, "two application summaries, two names", "W",
            2, role="sealed")
    b.add(_summary(46, "a", 2, name="Nora Quill"))
    b.add(_summary(46, "c", 2, name="Nora Quinn"))
    b.add(make_stub("y", wage_ctx(45, 72, 19.50, name="Nora Quill")))
    b.add(_letter(46, "seattle", 36, 19.50, name="Nora Quill"))
    b.expect("NEEDS_REVIEW", ["PERSON_NAME_MISMATCH"], "below_or_equal", 36504.00)

    b = new(47, "household_size_8", 4, "the frozen table's last row", "W", 8)
    b.add(_summary(47, "b", 8))
    b.add(make_stub("x", wage_ctx(46, 78, 21.00)))
    b.add(_letter(47, "mnhousing", 39, 21.00))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 42588.00)

    b = new(48, "household_size_9", 4, "one past the frozen table", "W", 9,
            role="sealed")
    b.add(_summary(48, "c", 9))
    b.add(make_stub("y", wage_ctx(47, 74, 19.25)))
    b.add(_letter(48, "seattle", 37, 19.25))
    b.expect("NEEDS_REVIEW", ["NO_FROZEN_THRESHOLD"], "no_frozen_threshold", 37037.00)
    b.notes.append("sizes above 8 are deliberately NOT extrapolated; the abstention "
                   "names who can supply the number")

    b = new(49, "income_equals_threshold", 4, "annualized income exactly at the limit",
            "W", 1)
    ctx = wage_ctx(48, None, None, freq="monthly", gross=6000.00,
                   dates=("2026-06-01", "2026-06-30", "2026-06-30"))
    ctx["rate_bait"] = True
    ctx["corner"] = "salary_as_rate_bait"
    b.add(_summary(49, "a", 1))
    b.add(make_stub("x", ctx))
    b.add(_letter(49, "mnhousing", 36, None))
    b.expect("READY_TO_REVIEW", [], "below_or_equal", 72000.00)
    b.notes.append("6,000.00 monthly x 12 = 72,000.00 == the frozen size-1 limit; "
                   "equal is below_or_equal by the organizer's own comparator. The "
                   "stub prints 'Rate of Pay: 6,000.00' with no hours anywhere -- the "
                   "salary-as-rate bait; hourly_rate must stay abstained (post-it-008)")

    b = new(50, "income_one_cent_above", 4, "annualized income one cent over", "W", 1)
    ctx = wage_ctx(49, None, None, freq="monthly", gross=6000.01,
                   dates=("2026-06-01", "2026-06-30", "2026-06-30"))
    ctx["rate_bait"] = True
    ctx["corner"] = "salary_as_rate_bait"
    b.add(_summary(50, "b", 1))
    b.add(make_stub("x", ctx))
    b.add(_letter(50, "seattle", None, None))
    b.expect("READY_TO_REVIEW", [], "above", 72000.12)
    b.notes.append("6,000.01 x 12 = 72,000.12 > 72,000: comparison 'above'. Readiness "
                   "is unaffected -- a comparison is not an eligibility judgement, and "
                   "this set exists to prove the two never merge")

    # required types per mix
    for b in sets:
        b.required = required_for(b.mix)
    return sets


# =====================================================================================
# manifest
# =====================================================================================
REAL_CARRIERS = ("seattle_housing", "mnhousing", "wa_dshs_acroform", "orangeusd",
                 "kcha_packet")


def carrier_class_of(b: SetBuilder) -> str:
    carriers = {d.carrier for d in b.docs}
    if "wa_dshs_acroform" in carriers:
        return "acroform"
    if carriers & set(REAL_CARRIERS):
        return "real"
    return "generator"


def build() -> None:
    sets = build_sets()
    assert len(sets) == 50, len(sets)
    layer_counts = {n: sum(1 for s in sets if s.layer == n) for n in (1, 2, 3, 4)}
    assert layer_counts == {1: 20, 2: 17, 3: 5, 4: 8}, layer_counts
    sealed = [s for s in sets if s.role == "sealed"]
    assert len(sealed) == 8, [s.sid for s in sealed]
    assert {s.layer for s in sealed} == {1, 2, 3, 4}
    sealed_classes = {carrier_class_of(s) for s in sealed}
    assert sealed_classes == {"acroform", "real", "generator"}, sealed_classes

    # carrier coverage: every real carrier in >=6 sets, >=3 deviation states
    coverage: dict[str, set[str]] = {c: set() for c in REAL_CARRIERS}
    states: dict[str, set[str]] = {c: set() for c in REAL_CARRIERS}
    corner_sets: dict[str, set[str]] = {}
    for b in sets:
        for d in b.docs:
            if d.carrier in coverage:
                coverage[d.carrier].add(b.sid)
                states[d.carrier].add(d.deviation or ("scan" if d.render == "scan"
                                                      else "present"))
            if d.corner:
                corner_sets.setdefault(d.corner, set()).add(b.sid)
    for carrier in REAL_CARRIERS:
        assert len(coverage[carrier]) >= 6, (carrier, sorted(coverage[carrier]))
        assert len(states[carrier]) >= 3, (carrier, sorted(states[carrier]))
    for corner, where in corner_sets.items():
        assert len(where) >= 2, (corner, sorted(where))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for b in sets:
        set_dir = OUT_DIR / f"{b.sid}_{b.slug}"
        set_dir.mkdir(parents=True, exist_ok=True)
        documents = []
        for n, doc in enumerate(b.docs, start=1):
            document_id = f"{b.sid}-D{n:02d}"
            file_name = f"{document_id}_{doc.document_type}.pdf"
            path = set_dir / file_name
            path.write_bytes(doc.data)
            with fitz.open(path) as check:
                pages = check.page_count
            for tf in doc.truth_fields + doc.latent_fields:
                assert tf.get("page") and tf.get("bbox") and len(tf["bbox"]) == 4, \
                    (b.sid, document_id, tf)
            documents.append({
                "document_id": document_id,
                "file_name": f"{set_dir.name}/{file_name}",
                "document_type": doc.document_type,
                "carrier": doc.carrier,
                "render": doc.render,
                "deviation": doc.deviation,
                "corner": doc.corner,
                "sha256": _sha(doc.data),
                "bytes": len(doc.data),
                "pages": pages,
                "truth_fields": doc.truth_fields,
                "latent_fields": doc.latent_fields,
                "expect_absent": doc.expect_absent(),
                "marked_only": doc.marked_only,
                "ambiguous": doc.ambiguous,
                "note": doc.note,
            })
        entries.append({
            "id": b.sid,
            "slug": b.slug,
            "layer": b.layer,
            "scenario": b.scenario,
            "income_mix": b.mix,
            "household_size": b.size,
            "role": b.role,
            "carrier_class": carrier_class_of(b),
            "carriers": sorted({d.carrier for d in b.docs}),
            "corners": sorted({d.corner for d in b.docs if d.corner}),
            "required_document_types": list(b.required),
            "present_document_types": sorted({d.document_type for d in b.docs}),
            "expected_annualized_income": b.expected_income,
            "expected_readiness_status": b.expected_status,
            "expected_review_reasons": b.expected_codes,
            "expected_comparison": b.expected_comparison,
            "notes": b.notes,
            "documents": documents,
        })

    corner_placements = {
        corner: sorted(where) for corner, where in sorted(corner_sets.items())
    }
    manifest = {
        "manifest_version": 1,
        "name": "scenario corpus: 50 household files, truth by construction",
        "created": "2026-07-21",
        "generator": "scripts/make_scenario_sets.py",
        "reference_date": "2026-07-18",
        "purpose": (
            "50 designed document COMBINATIONS (not field cross-products): income-mix x "
            "completeness (20), single state overlays (17), interaction pairs (5), "
            "boundary/structural (8). Fills ride real downloaded blanks wherever one "
            "exists; generator styles deliberately break the pack's visual grammar. "
            "This corpus measures the LOGIC layer (readiness, reasons, comparison) as "
            "well as extraction."
        ),
        "truth_discipline": {
            "statement": "Truth written at fill time by the generator that drew the "
                         "pages. Expected statuses, reason codes and comparisons are "
                         "hand-derived from the reasoning layer's DOCUMENTED "
                         "conventions (logic/constants.py CONVENTIONS, the pack "
                         "checklist vocabulary, and the HH-004 KNOWN_EXTRA precedent "
                         "for month-precision gig statements). They are not produced "
                         "by running logic/ -- that would make the measurement "
                         "circular.",
            "identities": "All invented; employers fictional; no SSN anywhere.",
            "unusable_dates": "A printed date with a masked or two-digit year has no "
                              "truth value (we never invent a century); the field is "
                              "expect_absent and any ISO emission for it is wrong.",
            "scans": "Image-only documents carry latent_fields: pixels only. A correct "
                     "reading is correct, an abstention is honest, a mismatch is "
                     "wrong. They feed the reasoning layer nothing.",
            "gig_undatable_convention": "Any set containing a gig_statement or a "
                                        "gig_income_corroboration document expects "
                                        "DOCUMENT_UNDATABLE: statement months have no "
                                        "day, and the corroboration type has no date "
                                        "field at all. This follows the repository's "
                                        "own recorded treatment of HH-004.",
        },
        "acroform_stratum": (
            "Sets with carrier_class 'acroform' carry a wa_dshs 14252 letter filled "
            "through its real AcroForm widgets. Their values are invisible to the "
            "text-layer extractor BY CONSTRUCTION (T18 backlog); the measurement "
            "harness reports them as a separate stratum so they never pollute the "
            "headline. These sets are the T18 acceptance corpus: when widget reading "
            "lands, they are the before/after measure."
        ),
        "roles": {
            "dev": [s.sid for s in sets if s.role == "dev"],
            "sealed": [s.sid for s in sets if s.role == "sealed"],
            "statement": "Sealed sets are generated and their truth recorded, then "
                         "never measured by this exercise. "
                         "scripts/measure_scenario_sets.py verifies their bytes and "
                         "refuses to open them without an explicit --unseal; a "
                         "hold-out is spent the first time it is used.",
        },
        "corner_placements": corner_placements,
        "sets": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    total_docs = sum(len(e["documents"]) for e in entries)
    print(f"wrote {len(entries)} sets, {total_docs} documents, manifest "
          f"{MANIFEST.relative_to(ROOT)}")
    print("layers:", layer_counts)
    print("sealed:", [s.sid for s in sealed])
    for carrier in REAL_CARRIERS:
        print(f"  {carrier:<18} sets={len(coverage[carrier]):>2} "
              f"deviations={sorted(states[carrier])}")
    for corner, where in corner_placements.items():
        print(f"  corner {corner:<28} {where}")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass
    build()
