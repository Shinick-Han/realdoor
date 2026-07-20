# -*- coding: utf-8 -*-
"""
make_filled_forms.py -- filled counterparts of the corpus's real blank forms.

WHY THIS FILE EXISTS
--------------------
The four blank forms in `testdata/confirm_raw/` have only ever tested the refusal side:
80 empty fields, every correct answer an abstention. Their FILLED counterparts -- real
layouts we did not draw, carrying values we know by construction because we placed them --
had never existed. This generator creates them, and writes the truth manifest
(`testdata/filled/filled_truth.json`) in the same breath, so the truth is true by
construction rather than by transcription. It also rehearses the organizer's announced
hidden-test class: "perturb names and values while retaining the schemas" -- these are
exactly retained schemas (the agencies' own typography and captions) with perturbed
(invented) names and values.

DISCIPLINE
----------
* Borrowed layout, invented content. Every identity, employer, amount and date below is
  invented. No real person appears; employers are fictional; the only real strings are
  the forms' own printed captions.
* Formats vary the way real filler-humans vary them: some "$2,105.00", some "19.75",
  some "38"; dates as "3/14/2022", "02/03/2025", "10/31/2025" -- each in the convention
  the form itself suggests.
* Partial fills are deliberate. Real forms come back with blanks, and the blanks keep the
  no-invention check alive: every field listed in `expect_absent` genuinely has no value
  on the filled page.
* Truth is written AT FILL TIME by this script. `expected` carries the scoreable value;
  each entry in `fills` records the exact string placed and where. A value that exists
  only as a graphical mark (a drawn circle around a menu word, a ticked AcroForm
  checkbox) goes to `marked_only`, never to `expected` -- a text-layer reader cannot see
  the mark, and crediting it for emitting the word under the mark would credit
  menu-reading, the exact failure the blank forms exist to catch.
* Fields whose meaning on a given form is genuinely ambiguous in the pay-stub vocabulary
  go to `ambiguous` with the reason, rather than being forced into either bucket.

TECHNIQUE, PER DOCUMENT (decided by inspection, recorded in the manifest)
-------------------------------------------------------------------------
* wa_dshs_14252: a real AcroForm (72 widgets). Filled through the form fields, the way
  the agency built it to be filled. NOTE what that implies: field values live in widget
  annotations, not in the page content stream, so a text-layer reader sees none of them.
* seattle, mnhousing, orangeusd, kcha: flat pages. Filled by drawing text at the blank
  positions, at each form's own type size, anchored to the form's own printed captions
  (found by text search, not hard-coded from a screenshot).
* md_labor_paystatement_template_instructions: judged NOT fillable -- three pages of
  prose instructing employers how to fill a template that is not itself in the PDF.
  There is no blank position on any page. Recorded in `not_filled` with this reason.

ROLES -- the load-bearing split
-------------------------------
Most documents are `role: "dev"`. Two are `role: "sealed"`: generated here, truth
written here, and then NOT measured -- `scripts/measure_filled_forms.py` refuses to
extract them, and no number reported from this exercise includes them. They are held for
one future measurement at the owner's call, after which they retire (the consumed-holdout
rule).

    python scripts/make_filled_forms.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "testdata" / "confirm_raw"
OUT_DIR = ROOT / "testdata" / "filled"
MANIFEST = OUT_DIR / "filled_truth.json"

INK = (0.05, 0.05, 0.35)  # blue-black "pen" so a human diffing the page sees the fill


# =====================================================================================
# placement helpers -- everything is anchored to the form's own printed captions
# =====================================================================================
def _anchor(page: fitz.Page, needle: str, occurrence: int = 0) -> fitz.Rect:
    hits = page.search_for(needle)
    if not hits or occurrence >= len(hits):
        raise SystemExit(
            f"anchor {needle!r} (occurrence {occurrence}) not found on page "
            f"{page.number + 1} -- the source form is not the one this spec was written for"
        )
    return hits[occurrence]


def _put(page: fitz.Page, spec: dict[str, Any]) -> dict[str, Any]:
    """Draw one text fill anchored to a printed caption. Returns the placement record."""
    rect = _anchor(page, spec["anchor"], spec.get("occ", 0))
    dx, dy = spec.get("dx", 3.0), spec.get("dy", 0.0)
    point = fitz.Point(rect.x1 + dx, rect.y1 - 1.5 + dy)
    if "abs_x" in spec:
        point.x = spec["abs_x"]
    size = spec.get("size", 8.0)
    font = spec.get("font", "helv")
    page.insert_text(point, spec["text"], fontsize=size, fontname=font, color=INK)
    return {
        "page": page.number + 1,
        "anchor": spec["anchor"],
        "text": spec["text"],
        "x": round(point.x, 1),
        "y": round(point.y, 1),
        "size": size,
        "font": font,
    }


def _oval(page: fitz.Page, spec: dict[str, Any]) -> dict[str, Any]:
    """Draw a circle-one ellipse around a printed menu word."""
    rect = _anchor(page, spec["anchor"], spec.get("occ", 0))
    pad_x, pad_y = spec.get("pad_x", 3.0), spec.get("pad_y", 2.5)
    oval = fitz.Rect(rect.x0 - pad_x, rect.y0 - pad_y, rect.x1 + pad_x, rect.y1 + pad_y)
    page.draw_oval(oval, color=INK, width=1.1)
    return {
        "page": page.number + 1,
        "mark": "ellipse",
        "around": spec["anchor"],
        "occ": spec.get("occ", 0),
    }


def _fill_widgets(doc: fitz.Document, text_values: dict[str, str],
                  checks: list[tuple[str, int]]) -> list[dict[str, Any]]:
    """Fill AcroForm text fields by field name, and set check/radio widgets.

    `checks` entries are (field_name, widget_index_among_that_name); the widget's own
    on-state is used, so radios select the intended member of the group.
    """
    records: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for page in doc:
        for widget in page.widgets() or []:
            name = widget.field_name or ""
            index = seen.get(name, 0)
            seen[name] = index + 1
            if widget.field_type_string == "Text" and name in text_values:
                # A few DSHS field names repeat ('Actual gross income MONTH 1 $' names
                # three cells); the spec keys those as name#index.
                widget.field_value = text_values[name]
                widget.update()
                records.append({"page": page.number + 1, "widget": name,
                                "text": text_values[name]})
            keyed = f"{name}#{index}"
            if widget.field_type_string == "Text" and keyed in text_values:
                widget.field_value = text_values[keyed]
                widget.update()
                records.append({"page": page.number + 1, "widget": keyed,
                                "text": text_values[keyed]})
            if (name, index) in checks:
                widget.field_value = widget.on_state()
                widget.update()
                records.append({"page": page.number + 1, "widget": name,
                                "mark": "checked", "widget_index": index})
    return records


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# =====================================================================================
# the fills -- invented identities, one per document
# =====================================================================================
# Identity roster (all invented):
#   seattle   : Marisol Vega, prep cook, Cascade Fresh Foods LLC (Seattle WA)
#   wa_dshs   : Terrence Boyd, grounds crew, Harbor Ridge Landscaping (Vancouver WA)
#   orangeusd : Ruth A. Delgado, certificated staff, Canyon Glen Unified (invented district)
#   mnhousing : Aisha Renner, customer service rep, Cedar Loop Insurance Services (MN)
#   kcha      : Denise Okafor, Pacific Rim Catering (Seattle WA)

SEATTLE = {
    "source": "seattle_housing_employment_verification_blank.pdf",
    "out": "seattle_housing_employment_verification_filled.pdf",
    "role": "dev",
    "kind": "filled_employment_verification",
    "technique": "overlay",
    "technique_detail": "flat page; values drawn at the blank ruled lines, 8-10pt to match "
                        "the form's own Arial captions; circle-one answered with a drawn "
                        "ellipse, exactly as a pen would",
    "text_fills": [
        {"anchor": "Head of Household Name:", "text": "Marisol Vega", "size": 10, "dx": 8},
        {"anchor": "Date:", "occ": 0, "text": "06/12/2026", "size": 10, "dx": 6},
        # TO: employer name & address on the three ruled lines
        {"anchor": "(Name & address of employer)", "text": "Cascade Fresh Foods LLC",
         "abs_x": 125, "dy": 16, "size": 9},
        {"anchor": "(Name & address of employer)", "text": "2217 Rainier Ave S",
         "abs_x": 125, "dy": 31, "size": 9},
        {"anchor": "(Name & address of employer)", "text": "Seattle, WA 98144",
         "abs_x": 125, "dy": 46, "size": 9},
        # RE: three ruled columns; values sit ON the line, captions under it
        {"anchor": "Household Member Name", "text": "Marisol Vega", "abs_x": 120,
         "dy": -13, "size": 9},
        {"anchor": "Signature of Household Member", "text": "Marisol Vega", "abs_x": 150,
         "dy": -13, "size": 10, "font": "heit"},
        {"anchor": "Signature of Household Member", "text": "06/12/2026", "abs_x": 480,
         "dy": -13, "size": 9},
        # employer section
        {"anchor": "Employee Name:", "text": "Marisol Vega", "dx": 5},
        {"anchor": "Job Title:", "text": "Prep Cook", "dx": 5},
        {"anchor": "Employed:", "occ": 1, "text": "3/14/2022", "dx": 6},
        {"anchor": "Current Wages/Salary: $", "text": "19.75", "dx": 2},
        {"anchor": "Average # of regular hours per week:", "text": "32", "dx": 5},
        {"anchor": "Year-to-date earnings: $", "text": "21,335.40", "dx": 2},
        {"anchor": "Overtime Rate:", "text": "29.63", "dx": 30},
        {"anchor": "Average # of overtime hours per week:", "text": "4", "dx": 5},
        # signature block (the form prints curly apostrophes)
        {"anchor": "Employer’s Signature", "text": "Daniel Okafor", "abs_x": 120,
         "dy": -13, "size": 10, "font": "heit"},
        {"anchor": "Employer’s Printed Name", "text": "Daniel Okafor", "abs_x": 330,
         "dy": -13, "size": 9},
        {"anchor": "Employer’s Printed Name", "text": "6/16/2026", "abs_x": 500,
         "dy": -13, "size": 9},
        {"anchor": "Employer (Company) Name and Address",
         "text": "Cascade Fresh Foods LLC, 2217 Rainier Ave S, Seattle, WA 98144",
         "abs_x": 150, "dy": -13, "size": 8},
        {"anchor": "Phone #", "text": "(206) 555-0142", "abs_x": 100, "dy": -13, "size": 8},
        {"anchor": "eMail", "text": "payroll@cascadefresh.example.com", "abs_x": 440,
         "dy": -13, "size": 8},
    ],
    "ovals": [
        # Presently Employed: Yes  -- the bold Yes right after the caption
        {"anchor": "Yes", "occ": 0, "pad_x": 4},
        # Current Wages/Salary basis: hourly (first 'hourly' on the page)
        {"anchor": "hourly", "occ": 0, "pad_x": 4},
    ],
    "expected": {
        "person_name": "Marisol Vega",
        "hourly_rate": "19.75",
        "regular_hours": "32",
        "employer_name": "Cascade Fresh Foods LLC",
        "document_date": "06/12/2026",
    },
    "expect_absent": [
        "pay_date", "pay_period_start", "pay_period_end", "gross_pay", "net_pay",
    ],
    "marked_only": {
        "pay_frequency": {
            "value_by_mark": "hourly",
            "mark": "drawn ellipse around the menu word 'hourly'",
            "why_not_expected": "the value exists only as a graphical circle; a text "
                                "reader emitting 'hourly' would be reading the menu, "
                                "not the mark, and must not be credited",
        },
    },
    "ambiguous": {},
    "deliberately_blank": [
        "Head of Household SS#", "Social Security Number", "Unit #",
        "Last Day of Employment", "Shift Differential Rate",
        "Commissions, bonuses, tips", "anticipated rate change", "layoff period",
        "Additional remarks", "Fax #", "YTD through-dates",
    ],
    "note": "TRAPS RETAINED FROM THE BLANK: the seven-word frequency menu is still printed "
            "(one word now circled in ink); 'Seattle Housing Authority' is still the "
            "publisher logo, not the employer; FAX (206) 256-7026 is still the agency's "
            "fax. NEW TRAPS BY CONSTRUCTION: Year-to-date earnings 21,335.40 is the most "
            "gross-pay-shaped number on the page and gross_pay is absent; Overtime Rate "
            "29.63 is a second per-hour rate next to the real 19.75.",
}

WA_DSHS = {
    "source": "wa_dshs_14252_employment_verification.pdf",
    "out": "wa_dshs_14252_employment_verification_filled.pdf",
    "role": "dev",
    "kind": "filled_employment_verification",
    "technique": "acroform",
    "technique_detail": "real AcroForm (72 widgets) filled through its own form fields "
                        "with appearance streams regenerated; checkboxes/radios set via "
                        "their on-states. Field values therefore live in widget "
                        "annotations, NOT in the page content stream.",
    "widget_text": {
        "DATE": "07/02/2026",
        "CASE  CLIENT ID NUMBER": "4471250",
        "EMPLOYEES SIGNATURE": "Terrence Boyd",
        "Employees Signature Date for authorization to release information": "06/28/2026",
        "EMPLOYEES NAME": "Terrence Boyd",
        "EMPLOYERS NAME": "Harbor Ridge Landscaping",
        "EMPLOYEES JOB TITLE": "Grounds Crew",
        "EMPLOYERS ADDRESS": "1408 SE Mill Plain Blvd, Vancouver, WA 98683",
        "DATE EMPLOYEE STARTED WORK": "02/03/2025",
        "DATE FIRST CHECK WAS RECEIVED": "02/21/2025",
        "AVERAGE HOURS PER WEEK": "38",
        "RATE OF PAY OR SALARY HOURLY DAILY OR PIECE RATE": "$17.10 hourly",
        # The last-three-months gross grid is NOT filled, and the reason is a property
        # of the real form worth keeping on the record: its three '$' cells share the
        # single field name 'Actual gross income MONTH 1 $' (and two month captions
        # share 'Actual gross income MONTH 2'), and same-named AcroForm fields hold ONE
        # value -- type into any cell and every cell mirrors it. A digital filler
        # cannot complete this grid independently, so a plausible digital fill leaves
        # it blank, as here. Only the uniquely-named current-month cells are filled.
        "Actual gross income Current MONTH 1": "July 1-15",
        "Actual gross income Current MONTH 1 $": "1,283.15",
        "EMPLOYERREPRESENTATIVES PRINTED NAME AND TITLE": "Gail Munson, Office Manager",
        "DATE of Employer / Representative's Signature": "07/02/2026",
        "PHONE NUMBER": "(360) 555-0177",
    },
    # (field_name, widget_index within that name) -> tick its on-state
    "widget_checks": [
        ("Is this a new job", 0),                # No
        ("No, job has not ended", 0),
        ("Every two weeks", 0),                  # pay frequency
        ("No, this job is not work study", 0),
        ("No tips", 0),
        ("No commissions", 0),
        ("No bonuses", 0),
        # The overtime row's widget names are SWAPPED relative to the printed words (a
        # bug in the agency's own form): the widget named 'Yes overtime' sits beside the
        # printed word 'No', where every other row's 'No ...' widget sits. Truth is what
        # a reader of the page sees, so we tick the widget that VISIBLY marks 'No' --
        # the one the form internally calls 'Yes overtime'.
        ("Yes overtime", 0),
        ("Is Health Insurance available", 0),    # Yes
        ("If yes is employee enrolled in the health plan", 1),  # No
    ],
    "expected": {
        "person_name": "Terrence Boyd",
        "hourly_rate": "$17.10",
        "regular_hours": "38",
        "employer_name": "Harbor Ridge Landscaping",
        "document_date": "07/02/2026",
    },
    "expect_absent": [
        "pay_date", "pay_period_start", "pay_period_end", "net_pay",
    ],
    "marked_only": {
        "pay_frequency": {
            "value_by_mark": "Every two weeks",
            "mark": "AcroForm checkbox 'Every two weeks' set to its on-state",
            "why_not_expected": "the value is a checkbox state; the five frequency words "
                                "are all still printed, so emitting one of them is "
                                "menu-reading unless the mark itself was read",
        },
    },
    "ambiguous": {
        "gross_pay": "the only income figure on the form is 1,283.15 for 'July 1-15', a "
                     "part-month total typed into the current-month widget; it is neither "
                     "a pay-period gross nor a full-month gross, so calling any answer "
                     "right or wrong would manufacture a result",
    },
    "deliberately_blank": [
        "SOCIAL SECURITY NUMBER OPTIONAL", "DSHS PHONE NUMBER", "If yes, Ended when?",
        "If yes, Ended why?", "work-study details", "WHEN WILL YOUR POSITION END",
        "last-three-months gross grid (unfillable digitally: its cells share one field "
        "name and mirror a single value -- see widget_text comment)",
        "tips/commissions/bonuses/overtime amounts", "work schedule grid",
        "When does coverage begin?", "What is employee portion of premiums?",
        "employer signature (Signature-type field, left unsigned)",
    ],
    "expected_note": "hourly_rate: the exact string typed into the rate widget is "
                     "'$17.10 hourly' (an employer states the basis because the caption "
                     "asks for it); the scoreable value is $17.10. person_name: "
                     "'Terrence Boyd' also appears in the signature widget. "
                     "document_date: the form's own top-right DATE widget.",
    "note": "TRAPS RETAINED: the five-frequency checkbox menu is still printed; DSHS "
            "PO BOX and fax 888-338-7410 are still agency identity. NEW BY CONSTRUCTION: "
            "'DATE EMPLOYEE STARTED WORK' 02/03/2025 and 'DATE FIRST CHECK WAS RECEIVED' "
            "02/21/2025 are date-shaped non-pay-dates. STRUCTURAL: every filled value "
            "lives in a widget annotation; the page content stream is byte-identical to "
            "the blank form, so a content-stream reader sees the blank document.",
}

ORANGEUSD = {
    "source": "orangeusd_sample_paystub.pdf",
    "out": "orangeusd_sample_paystub_filled.pdf",
    "role": "dev",
    "kind": "filled_pay_stub",
    "technique": "overlay",
    "technique_detail": "flat page; the empty stub template's cells written at the "
                        "template's own 6-7pt cell sizes, under the template's own "
                        "captions; the explainer key below the stub is untouched",
    "text_fills": [
        {"anchor": "Employee Name", "occ": 0, "text": "DELGADO, RUTH A", "abs_x": 30,
         "dy": 9, "size": 6.5},
        {"anchor": "District Name", "occ": 0, "text": "CANYON GLEN UNIFIED", "abs_x": 213,
         "dy": 9, "size": 6.5},
        {"anchor": "Check Number", "occ": 0, "text": "00458213", "abs_x": 517,
         "dy": 9, "size": 6.5},
        {"anchor": "Employee ID", "occ": 0, "text": "204871", "abs_x": 42, "dy": 8,
         "size": 6},
        {"anchor": "Pay Site", "occ": 0, "text": "012", "abs_x": 108, "dy": 8, "size": 6},
        {"anchor": "Sequence Number", "occ": 0, "text": "0044", "abs_x": 158, "dy": 8,
         "size": 6},
        {"anchor": "Payroll Number", "occ": 0, "text": "10", "abs_x": 40, "dy": 8,
         "size": 6},
        {"anchor": "Payroll Issue Date", "occ": 0, "text": "10/31/2025", "abs_x": 94,
         "dy": 8, "size": 6},
        {"anchor": "Payroll Ending Date", "occ": 0, "text": "10/31/2025", "abs_x": 155,
         "dy": 8, "size": 6},
        # Hours and Earnings row 1
        {"anchor": "Description", "occ": 0, "text": "REGULAR EARNINGS", "abs_x": 34,
         "dy": 12, "size": 6},
        {"anchor": "Rate of Pay", "occ": 0, "text": "4,812.00", "abs_x": 103, "dy": 12,
         "size": 6},
        {"anchor": "Hours/Units", "occ": 0, "text": "21.00", "abs_x": 168, "dy": 12,
         "size": 6},
        # 'Earnings' occ 0 is inside the 'Hours and Earnings' title, so the earnings
        # cell is anchored to the same row's Description caption instead
        {"anchor": "Description", "occ": 0, "text": "4,812.00", "abs_x": 224, "dy": 12,
         "size": 6},
        # Pre-Tax Deductions / Other Deductions block (anchored to the block's own
        # Description captions at y~327; the Amount captions are ambiguous because
        # 'Additional Amount' and 'Current Amount' also match)
        {"anchor": "Description", "occ": 2, "text": "STRS RETIREMENT", "abs_x": 34,
         "dy": 12, "size": 6},
        {"anchor": "Description", "occ": 2, "text": "553.38", "abs_x": 106, "dy": 12,
         "size": 6},
        {"anchor": "Description", "occ": 3, "text": "UNION DUES", "abs_x": 166, "dy": 12,
         "size": 6},
        {"anchor": "Description", "occ": 3, "text": "92.50", "abs_x": 228, "dy": 12,
         "size": 6},
        # bottom summary band, 'Current' row (columns measured off the band captions:
        # Gross Pay 101, Pre-Tax Deductions 165, Other Deductions 287, Tax Ded. 348,
        # NET PAY 538)
        {"anchor": "Gross Pay", "occ": 0, "text": "4,812.00", "abs_x": 101, "dy": 23,
         "size": 6},
        {"anchor": "Gross Pay", "occ": 0, "text": "553.38", "abs_x": 168, "dy": 23,
         "size": 6},
        {"anchor": "Gross Pay", "occ": 0, "text": "92.50", "abs_x": 292, "dy": 23,
         "size": 6},
        {"anchor": "Gross Pay", "occ": 0, "text": "0.00", "abs_x": 352, "dy": 23,
         "size": 6},
        {"anchor": "NET PAY", "occ": 0, "text": "4,166.12", "abs_x": 538, "dy": 12,
         "size": 8},
    ],
    "ovals": [],
    "expected": {
        "person_name": "DELGADO, RUTH A",
        "employer_name": "CANYON GLEN UNIFIED",
        "pay_date": "10/31/2025",
        "pay_period_end": "10/31/2025",
        "gross_pay": "4,812.00",
        "net_pay": "4,166.12",
    },
    "expect_absent": [
        "pay_period_start", "pay_frequency", "hourly_rate", "regular_hours",
        "document_date",
    ],
    "marked_only": {},
    "ambiguous": {},
    "deliberately_blank": [
        "Important Message", "Federal/State marital status and exemptions",
        "Pre-Tax Retirement block", "Advance Earned Income Credit", "ESA Gross Advance",
        "second and later earnings rows",
    ],
    "note": "This is the bonita trap rebuilt by construction, on a layout we did not "
            "draw: 'Rate of Pay' 4,812.00 is a MONTHLY salary rate (equal to gross), so "
            "hourly_rate is absent and 4,812.00 is its natural wrong answer; "
            "'Hours/Units' 21.00 is working DAYS, so regular_hours is absent and 21.00 "
            "is its natural wrong answer. Only an END date is given (issue = ending "
            "date, a monthly certificated stub), so pay_period_start is absent. The "
            "template's own printed zeros (FEDERAL 0.00 etc.) remain; deductions here "
            "are pre-tax/other, and 4,812.00 - 553.38 - 92.50 = 4,166.12 exactly.",
}

MNHOUSING = {
    "source": "mnhousing_employment_verification_blank.pdf",
    "out": "mnhousing_employment_verification_filled.pdf",
    "role": "sealed",
    "kind": "filled_employment_verification",
    "technique": "overlay",
    "technique_detail": "flat page; employer-section blanks written at the form's own "
                        "9-10pt size; circle-one answered with a drawn ellipse; Yes/No "
                        "answered by writing X on the printed underscore line",
    "text_fills": [
        {"anchor": "TO:", "text": "Cedar Loop Insurance Services", "abs_x": 95, "dy": 26,
         "size": 9},
        {"anchor": "TO:", "text": "88 Sibley St NW", "abs_x": 95, "dy": 44, "size": 9},
        {"anchor": "TO:", "text": "St. Cloud, MN 56301", "abs_x": 95, "dy": 62, "size": 9},
        {"anchor": "Applicant/Tenant Name", "text": "Aisha Renner", "abs_x": 100,
         "dy": -13, "size": 9},
        {"anchor": "Signature of Applicant/Tenant", "text": "Aisha Renner", "abs_x": 100,
         "dy": -13, "size": 10, "font": "heit"},
        {"anchor": "Signature of Applicant/Tenant", "text": "1/6/2026", "abs_x": 500,
         "dy": -13, "size": 9},
        {"anchor": "Employee Name:", "text": "Aisha Renner", "dx": 8},
        {"anchor": "Job Title:", "text": "Customer Service Representative", "dx": 8},
        {"anchor": "Presently Employed:", "occ": 0, "text": "X", "dx": 32},
        {"anchor": "Date First Employed", "text": "11/04/2019", "dx": 6},
        {"anchor": "Current gross wages/salary:", "text": "2,105.00", "dx": 14},
        {"anchor": "Average # of regular hours per week:", "text": "40", "dx": 6},
        {"anchor": "Overtime Rate:", "text": "23.68", "dx": 14},
        {"anchor": "not included in regular hours):", "occ": 0, "text": "0", "dx": 6},
        {"anchor": "Signature:", "text": "Lorna Prentiss", "abs_x": 200, "dy": -2,
         "size": 10, "font": "heit"},
        {"anchor": "Print your name:", "text": "Lorna Prentiss", "abs_x": 200, "dy": -2,
         "size": 9},
        # 'Title:' occ 0 is inside 'Job Title:'; occ 1 is the signature block's own.
        {"anchor": "Title:", "occ": 1, "text": "HR Generalist", "abs_x": 200, "dy": -2,
         "size": 9},
        {"anchor": "Company Name", "text": "Cedar Loop Insurance Services", "abs_x": 200,
         "dy": -2, "size": 9},
        # 'Address' occ 0/1 sit in the TO/FROM headers; occ 2 is the signature block's.
        {"anchor": "Address", "occ": 2, "text": "88 Sibley St NW, St. Cloud, MN 56301",
         "abs_x": 200, "dy": -2, "size": 9},
        # 'Date:' occ 0 is '; Effective date:' (search is case-insensitive); occ 1 is
        # the signature block's Date.
        {"anchor": "Date:", "occ": 1, "text": "1/9/2026", "dx": 10, "size": 9},
        {"anchor": "Tel. #:", "text": "(320) 555-0164", "dx": 10, "size": 9},
    ],
    "ovals": [
        # Current gross wages/salary basis: semi-monthly (first menu's fourth word)
        {"anchor": "semi-monthly", "occ": 0, "pad_x": 3},
    ],
    "expected": {
        "person_name": "Aisha Renner",
        "gross_pay": "2,105.00",
        "regular_hours": "40",
        "employer_name": "Cedar Loop Insurance Services",
        "document_date": "1/9/2026",
    },
    "expect_absent": [
        "pay_date", "pay_period_start", "pay_period_end", "net_pay", "hourly_rate",
    ],
    "marked_only": {
        "pay_frequency": {
            "value_by_mark": "semi-monthly",
            "mark": "drawn ellipse around the first menu's 'semi-monthly'",
            "why_not_expected": "graphical circle over a printed fourteen-word menu; "
                                "emitting the word without reading the mark is "
                                "menu-reading",
        },
    },
    "ambiguous": {},
    "deliberately_blank": [
        "FROM block", "Email / Contact lines", "Unit Number", "Shift Differential Rate",
        "shift differential hours", "Commissions, bonuses, tips", "YTD earnings and "
        "date-range skeleton", "rate-change line", "seasonal/retirement Yes-No pairs",
        "Additional remarks",
    ],
    "expected_note": "gross_pay: 'Current gross wages/salary $2,105.00' with "
                     "'semi-monthly' circled -- the amount is the gross wages of one "
                     "semi-monthly period, the closest thing to gross pay this form can "
                     "state. hourly_rate is ABSENT by construction: the only per-hour "
                     "figure on the page is the 23.68 OVERTIME rate. document_date: the "
                     "employer signature-block 'Date: 1/9/2026' (the date the form "
                     "itself was completed).",
    "note": "SEALED. Generated and recorded here; never extracted by this exercise's "
            "measurement runs. TRAPS: overtime rate 23.68 is the only $/hour on the "
            "page; the second frequency menu (commissions line) stays uncircled; the "
            "YTD date-range skeleton '__/__/__ through __/__/__' stays empty.",
}

KCHA = {
    "source": "kcha_section8_doc21.pdf",
    "out": "kcha_section8_doc21_filled.pdf",
    "role": "sealed",
    "kind": "housing_packet_partially_completed",
    "technique": "overlay",
    "technique_detail": "flat pages; only the recertification form's PART III income "
                        "page (page 8 of 15) is completed, the way a resident returns a "
                        "packet -- income-type checkmark, one income-chart row, and "
                        "employer block C; the other 14 pages untouched",
    "page_index": 7,
    "text_fills": [
        {"anchor": "UNEMPLOYMENT BENEFITS", "occ": 0, "text": "", "dx": 0},  # placeholder, replaced below
    ],
    "ovals": [],
    "expected": {
        "person_name": "Denise Okafor",
        "employer_name": "Pacific Rim Catering",
    },
    "expect_absent": [
        "pay_date", "pay_period_start", "pay_period_end", "regular_hours",
        "hourly_rate", "net_pay", "document_date",
    ],
    "marked_only": {
        "pay_frequency": {
            "value_by_mark": "monthly",
            "mark": "X written in the income chart's PER MONTH column",
            "why_not_expected": "the frequency is stated by which column the X sits "
                                "under -- a geometric mark, not a printed frequency word "
                                "with a value",
        },
    },
    "ambiguous": {
        "gross_pay": "the 1,987.20 in GROSS AMT OF INCOME is a household member's "
                     "monthly income on an application chart, not the gross pay of a "
                     "pay period document; calling either answer right or wrong would "
                     "manufacture a result",
    },
    "deliberately_blank": [
        "all of pages 1-7 and 9-15", "PART III question checkboxes B(1)-(7)",
        "student table", "second family-member income rows", "second employer column",
    ],
    "note": "SEALED. Generated and recorded here; never extracted by this exercise's "
            "measurement runs. The one X on the EMPLOYMENT/WAGES line and one filled "
            "chart row are exactly how these packets come back: nearly blank, with the "
            "load-bearing values buried on one page.",
}

NOT_FILLED = [
    {
        "file_name": "md_labor_paystatement_template_instructions.pdf",
        "why": "judged not fillable on inspection: three pages of prose instructing "
               "employers how to complete Maryland's pay-statement template; the "
               "template itself is not in the PDF, and no page carries a blank position "
               "a filler could write into. A 'filled' version would require authoring "
               "the layout ourselves, which is exactly what this corpus exists to avoid "
               "(borrowed layout, invented content -- here there is no layout to borrow).",
    },
]


# =====================================================================================
# per-document builders
# =====================================================================================
def _build_overlay(spec: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]]:
    doc = fitz.open(RAW_DIR / spec["source"])
    page = doc[spec.get("page_index", 0)]
    records = []
    for fill in spec["text_fills"]:
        if fill.get("text") == "":
            continue
        records.append(_put(page, fill))
    for oval in spec["ovals"]:
        records.append(_oval(page, oval))
    data = doc.tobytes(deflate=True)
    doc.close()
    return data, records


def _build_kcha() -> tuple[bytes, list[dict[str, Any]]]:
    """kcha needs row placement measured off the income chart's own column headers."""
    doc = fitz.open(RAW_DIR / KCHA["source"])
    page = doc[KCHA["page_index"]]
    records = []

    def put(spec):
        records.append(_put(page, spec))

    # A. income types: X on the blank before EMPLOYMENT/WAGES
    emp = _anchor(page, "EMPLOYMENT/WAGES")
    page.insert_text(fitz.Point(emp.x0 - 30, emp.y1 - 1.5), "X", fontsize=9,
                     fontname="helv", color=INK)
    records.append({"page": page.number + 1, "anchor": "EMPLOYMENT/WAGES",
                    "text": "X (on the blank line before the caption)",
                    "x": round(emp.x0 - 30, 1), "y": round(emp.y1 - 1.5, 1),
                    "size": 9, "font": "helv"})

    # B. income chart, first row under the headers
    name_h = _anchor(page, "NAME OF FAMILY MEMBER")
    source_h = _anchor(page, "SOURCE OF INCOME")
    gross_h = _anchor(page, "GROSS AMT OF")
    month_h = _anchor(page, "PER MONTH")
    row_y = name_h.y1 + 16.0
    for x, text in (
        (name_h.x0, "Denise Okafor"),
        (source_h.x0 - 2, "Wages - Pacific Rim Catering"),
        (gross_h.x0 + 4, "1,987.20"),
        (month_h.x0 + 14, "X"),
    ):
        page.insert_text(fitz.Point(x, row_y), text, fontsize=7.5, fontname="helv",
                         color=INK)
        records.append({"page": page.number + 1, "anchor": "income chart row 1",
                        "text": text, "x": round(x, 1), "y": round(row_y, 1),
                        "size": 7.5, "font": "helv"})

    # C. employer block, left column
    put({"anchor": "PERSON EMPLOYED", "occ": 0, "text": "Denise Okafor", "abs_x": 190,
         "dy": -2, "size": 9})
    put({"anchor": "EMPLOYER'S NAME", "occ": 0, "text": "Pacific Rim Catering",
         "abs_x": 190, "dy": -2, "size": 9})
    put({"anchor": "ADDRESS", "occ": 0, "text": "301 S Jackson St", "abs_x": 190,
         "dy": -2, "size": 9})
    put({"anchor": "CITY, STATE, ZIP", "occ": 0, "text": "Seattle, WA 98104",
         "abs_x": 190, "dy": -2, "size": 9})
    put({"anchor": "TELEPHONE #", "occ": 0, "text": "(206) 555-0119", "abs_x": 190,
         "dy": -2, "size": 9})

    data = doc.tobytes(deflate=True)
    doc.close()
    return data, records


def _build_acroform(spec: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]]:
    doc = fitz.open(RAW_DIR / spec["source"])
    records = _fill_widgets(doc, spec["widget_text"], spec["widget_checks"])
    data = doc.tobytes(deflate=True)
    doc.close()
    return data, records


# =====================================================================================
# manifest
# =====================================================================================
def build() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    for spec in (SEATTLE, WA_DSHS, ORANGEUSD, MNHOUSING, KCHA):
        if spec is KCHA:
            data, records = _build_kcha()
        elif spec["technique"] == "acroform":
            data, records = _build_acroform(spec)
        else:
            data, records = _build_overlay(spec)
        out_path = OUT_DIR / spec["out"]
        out_path.write_bytes(data)
        with fitz.open(out_path) as check:
            pages = check.page_count
        entry = {
            "file_name": spec["out"],
            "source_file": spec["source"],
            "source_sha256": _sha(RAW_DIR / spec["source"]),
            "sha256": _sha(out_path),
            "bytes": out_path.stat().st_size,
            "pages": pages,
            "kind": spec["kind"],
            "role": spec["role"],
            "technique": spec["technique"],
            "technique_detail": spec["technique_detail"],
            "expected": spec["expected"],
            "expect_absent": spec["expect_absent"],
            "marked_only": spec["marked_only"],
            "ambiguous": spec["ambiguous"],
            "deliberately_blank": spec["deliberately_blank"],
            "fills": records,
            "note": spec["note"],
        }
        if "expected_note" in spec:
            entry["expected_note"] = spec["expected_note"]
        documents.append(entry)
        print(f"wrote {out_path.name}  ({entry['bytes']} bytes, {pages} pages, "
              f"role={entry['role']}, {len(records)} placements)")

    manifest = {
        "manifest_version": 1,
        "name": "filled-forms corpus (blank forms completed with invented values)",
        "created": "2026-07-20",
        "purpose": "The corpus's real blank forms, filled with invented identities and "
                   "values by scripts/make_filled_forms.py. Layout borrowed from the "
                   "publishing agencies; every value invented; truth written at fill "
                   "time, so it is true by construction. The blanks tested the refusal "
                   "side only; these test whether values on foreign layouts are read.",
        "generator": "scripts/make_filled_forms.py",
        "truth_discipline": {
            "statement": "Truth by construction: every entry in `expected` is a string "
                         "this generator placed on the page (or its scoreable core -- "
                         "see per-document expected_note), recorded in the same run "
                         "that wrote the PDF. Nothing was transcribed after the fact.",
            "identities": "All invented. No real person; employers fictional; amounts "
                          "plausible; formats varied the way real filler-humans vary "
                          "them.",
            "marked_only_rule": "A value that exists only as a graphical mark (drawn "
                                "circle, checkbox state) is recorded under marked_only "
                                "and is NOT scored: crediting a text reader for the "
                                "word under a mark would credit menu-reading.",
            "ambiguous_rule": "A field whose meaning on a given form is genuinely "
                               "ambiguous in the pay-stub vocabulary is excluded with "
                               "its reason rather than forced into either bucket.",
        },
        "field_vocabulary": [
            "person_name", "pay_date", "pay_period_start", "pay_period_end",
            "pay_frequency", "regular_hours", "hourly_rate", "gross_pay", "net_pay",
            "document_date", "employer_name",
        ],
        "roles": {
            "dev": [d["file_name"] for d in documents if d["role"] == "dev"],
            "sealed": [d["file_name"] for d in documents if d["role"] == "sealed"],
            "statement": "The sealed documents are generated and their truth recorded, "
                         "but they are EXCLUDED from every measurement run and every "
                         "number reported in this exercise. They are held for one "
                         "future measurement at the owner's call, after which they "
                         "retire (a hold-out is spent the first time it is used). "
                         "scripts/measure_filled_forms.py verifies they exist and "
                         "match their sha256 without ever extracting them.",
        },
        "documents": documents,
        "not_filled": NOT_FILLED,
    }
    MANIFEST.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {MANIFEST.relative_to(ROOT)}  ({len(documents)} documents, "
          f"{len(NOT_FILLED)} judged not fillable)")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # pragma: no cover
        pass
    build()
