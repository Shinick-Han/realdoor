# -*- coding: utf-8 -*-
"""
make_holdout.py -- documents whose labels we did NOT choose.

WHY THIS FILE EXISTS
--------------------
`core.extract.LABEL_SYNONYMS` is a hand-written table of label strings. The documents it
was first measured against -- `up_016`, `up_017`, `up_018` in `scripts/make_testdata.py`
-- were also written by hand, by us, in the same week, and every label string they use is
in that table. The label-wording cohort consequently reads 100%.

That 100% is not a measurement. It is the table reciting itself. We set the exam and we
wrote the answer key, so the score was decided before the run. Anyone who opens the two
files side by side sees it in about three minutes, and is then right to discount every
other number we publish.

This file is the correction. The labels below were transcribed from real US payroll and
verification documents -- ADP, Paychex, Gusto, Fannie Mae Form 1005, SSA -- and the
research was done BEFORE anyone opened `LABEL_SYNONYMS`. The ordering was enforced
structurally rather than by good intentions: the strings were gathered by a separate
worker that had no access to this repository and could only search the web (see
PROVENANCE below). Whoever built these documents could not have been steering toward the
table's contents, because they had not read it.

HOW TO READ THE RESULT
----------------------
A string here that turns out to be in `LABEL_SYNONYMS` is good news -- it means the table
was written well. A string that is not is the thing we wanted to find out, and it is not a
failure of the exercise; it is the exercise working. The only outcome that would be bad is
a WRONG value, which `scripts/measure_label_mapping.py` counts separately and which must
be zero.

WHAT THESE DOCUMENTS ARE NOT
----------------------------
They are not real documents, and they are not copies of real documents. Only the *label
vocabulary* is borrowed from the real world. Every person, employer, address and amount is
invented, every page carries the SYNTHETIC watermark, and the layout is our own generator's
-- deliberately, because label wording is the single variable under test here. Layout and
typography are already covered by their own cohorts in `scripts/make_testdata.py`, and
changing two things at once would tell us nothing about either.

    python scripts/make_holdout.py
    python scripts/measure_label_mapping.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_testdata import build_page  # type: ignore  # noqa: E402

OUT_DIR = ROOT / "testdata" / "holdout"
MANIFEST = ROOT / "testdata" / "holdout_manifest.json"

#: Where the label vocabulary came from. Recorded per document in the manifest so a
#: reader can check any individual string rather than taking the set on trust.
PROVENANCE = (
    "Label strings transcribed from publicly published sample documents and form "
    "templates by a researcher with no access to this repository, working only from web "
    "search, BEFORE core.extract.LABEL_SYNONYMS was read by anyone involved. Sources are "
    "listed per document under `sources`. Names, employers, addresses and amounts are "
    "invented; only the label wording is borrowed."
)

# --------------------------------------------------------------------------------------
# The documents.
# --------------------------------------------------------------------------------------
# `tier` records how the label strings were obtained, because the two are not equally
# good evidence and pretending otherwise is the exact failure this file corrects:
#
#   A -- the researcher fetched the PDF and read its text layer directly. The strings are
#        verbatim, including the source's own typos.
#   B -- the page was fetched but transcribed by a summarizing model. The wording is
#        very likely right; the capitalization may have been normalized on the way.
#
# Five of the seven documents are tier A. Nothing below is from memory alone -- strings
# the researcher could only recall, or only saw in a search snippet, were dropped rather
# than used, and the SSA benefit-letter samples were abandoned entirely because the only
# published PDFs are scans with no text layer. That gap is real and is stated here rather
# than papered over with a plausible-sounding caption we made up.
#
# On casing: `make_testdata._field` upper-cases every label as it draws it, so
# "Period Beginning" is rendered "PERIOD BEGINNING". The pack's own documents are
# ALL-CAPS and the extractor's `normalize_label` upper-cases anyway, so this changes
# nothing about what is being tested -- but it does mean the tier A/B distinction on
# capitalization is moot for our purposes. The WORDS are what is under test.
#
# On values: every amount, name and date is invented. Where a real form's field carries a
# different unit than ours -- UNC prints `Pay Rate` as an annual salary -- we kept the
# real caption and supplied an hourly value, because the caption is the variable under
# test and the value is not. This is noted per document.

DOCS: list[dict] = [
    {
        "file_name": "ho_001_pay_stub_adp_earnings_statement.pdf",
        "document_type": "pay_stub",
        "org": "Cedar Point Restaurant Group",
        "subtitle": "Earnings Statement",
        "doc_id": "HO-001",
        "modelled_on": "ADP Earnings Statement (sample published by the California Courts)",
        "tier": "A",
        "sources": [
            "https://courts.ca.gov/sites/default/files/courts/default/2024-10/"
            "lpa-adp-sample_pay_statement.pdf"
        ],
        "rows": [
            [("Period Beginning", "2026-06-01"), ("Period Ending", "2026-06-14"),
             ("Pay Date", "2026-06-19")],
            [("Rate", "21.40"), ("Hours", "74"), ("Gross Pay", "1583.60")],
            [("Net Pay", "1268.11")],
        ],
        "intended_fields": {
            "pay_period_start": "2026-06-01",
            "pay_period_end": "2026-06-14",
            "pay_date": "2026-06-19",
            "hourly_rate": 21.40,
            "regular_hours": 74,
            "gross_pay": 1583.60,
            "net_pay": 1268.11,
        },
        "intended_edge_case": (
            "ADP is the largest US payroll processor, so this is the single most likely "
            "vocabulary a judge's own document will use. Note `Rate` and `Hours` -- bare "
            "one-word captions that LABEL_SYNONYMS deliberately refuses to guess at "
            "because they are ambiguous in isolation. Here they are unambiguous only "
            "because of where they sit, which is knowledge the label mapper does not have."
        ),
    },
    {
        "file_name": "ho_002_pay_stub_cfpb_gross_income.pdf",
        "document_type": "pay_stub",
        "org": "Ridgeway Home Services",
        "subtitle": "Earnings Statement",
        "doc_id": "HO-002",
        "modelled_on": "CFPB 'How to read a pay stub' student handout sample",
        "tier": "A",
        "sources": [
            "https://files.consumerfinance.gov/f/documents/"
            "cfpb_building_block_activities_how-to-read-pay-stub_handout.pdf"
        ],
        "rows": [
            [("EMPLOYEE NAME", "Ada Lark"), None, ("PAY DATE", "2026-06-26")],
            [("RATE", "16.75"), ("HOURS", "80"), ("GROSS INCOME", "1340.00")],
            [("NET INCOME", "1094.30")],
        ],
        "intended_fields": {
            "person_name": "Ada Lark",
            "pay_date": "2026-06-26",
            "hourly_rate": 16.75,
            "regular_hours": 80,
            "gross_pay": 1340.00,
            "net_pay": 1094.30,
        },
        "intended_edge_case": (
            "`GROSS INCOME` / `NET INCOME` rather than the far commoner `PAY`/`WAGES` "
            "wording. A federal consumer-education handout teaching people what a stub "
            "looks like is about as close to a canonical US pay stub as exists."
        ),
    },
    {
        "file_name": "ho_003_pay_stub_peoplesoft_advice_date.pdf",
        "document_type": "pay_stub",
        "org": "Lakeside Facilities Management",
        "subtitle": "Payroll Advice",
        "doc_id": "HO-003",
        "modelled_on": "PeopleSoft payroll advice (UNC Finance published sample)",
        "tier": "A",
        "sources": [
            "https://finance.unc.edu/wp-content/uploads/sites/298/2017/08/paystub-sample-2017.pdf"
        ],
        "rows": [
            [("Pay Begin Date", "2026-06-01"), ("Pay End Date", "2026-06-15"),
             ("Advice Date", "2026-06-22")],
            [("Pay Rate", "23.50"), ("TOTAL GROSS", "1762.50")],
        ],
        "intended_fields": {
            "pay_period_start": "2026-06-01",
            "pay_period_end": "2026-06-15",
            "pay_date": "2026-06-22",
            "hourly_rate": 23.50,
            "gross_pay": 1762.50,
        },
        "intended_edge_case": (
            "`Advice Date` for the pay date -- PeopleSoft calls the payment an advice, and "
            "nothing in that phrase contains the word 'pay' or 'check'. `TOTAL GROSS` "
            "inverts the word order we use. Value note: the real form prints `Pay Rate` as "
            "an annual salary; we kept the caption and supplied an hourly value, since the "
            "caption is what is under test."
        ),
    },
    {
        "file_name": "ho_004_pay_stub_statement_of_earnings_and_deductions.pdf",
        "document_type": "pay_stub",
        "org": "Fairmont Textile Works",
        "subtitle": "Statement of Earnings and Deductions",
        "doc_id": "HO-004",
        "modelled_on": "Ascendium/UTEP 'Understanding your pay stub' published sample",
        "tier": "A",
        "sources": [
            "https://www.utep.edu/student-affairs/financialaid/_files/docs/"
            "understanding-your-pay-stub.pdf"
        ],
        "rows": [
            [("Name", "Milo Fenn"), None, ("Check Date", "2026-07-02")],
            [("Pay Rate", "19.80"), ("Current Hours", "68"), ("Gross Wages", "1346.40")],
            [("Net Pay", "1085.72")],
        ],
        "intended_fields": {
            "person_name": "Milo Fenn",
            "pay_date": "2026-07-02",
            "hourly_rate": 19.80,
            "regular_hours": 68,
            "gross_pay": 1346.40,
            "net_pay": 1085.72,
        },
        "intended_edge_case": (
            "`Name` on its own for the employee, and `Current Hours` for this period's "
            "hours -- 'current' doing the work that 'regular' does in our vocabulary. "
            "`Name` is the other bare caption LABEL_SYNONYMS refuses on principle, since "
            "on a real stub it could just as easily head the employer block."
        ),
    },
    {
        "file_name": "ho_005_pay_stub_federal_leave_and_earnings.pdf",
        "document_type": "pay_stub",
        "org": "Northern Basin Water District",
        "subtitle": "Leave and Earnings Statement",
        "doc_id": "HO-005",
        "modelled_on": "US Bureau of Reclamation federal Leave & Earnings Statement",
        "tier": "A",
        "sources": ["https://www.usbr.gov/gp/employment/neo/tab6/ELS2012.pdf"],
        "rows": [
            [("Pay Begin Date", "2026-06-07"), ("For Pay Period Ending", "2026-06-20"),
             ("Pay Date", "2026-06-26")],
            [("Hourly Rate", "24.15"), ("Net Pay", "1402.88")],
        ],
        "intended_fields": {
            "pay_period_start": "2026-06-07",
            "pay_period_end": "2026-06-20",
            "pay_date": "2026-06-26",
            "hourly_rate": 24.15,
            "net_pay": 1402.88,
        },
        "intended_edge_case": (
            "`For Pay Period Ending` -- a caption that is a prepositional phrase rather "
            "than a noun. Exact-match tables are brittle in exactly this way: the words "
            "'pay period' and 'ending' are both ones we know, wrapped in two we do not."
        ),
    },
    {
        "file_name": "ho_006_employment_letter_work_number_voe.pdf",
        "document_type": "employment_letter",
        "org": "Granite Ridge Distribution",
        "subtitle": "Verification of Employment",
        "doc_id": "HO-006",
        "modelled_on": (
            "The Work Number / Equifax VOE field set, plus item 15 of VA Form 26-8497 "
            "(Request for Verification of Employment)"
        ),
        "tier": "B",
        "sources": [
            "https://docs.ocrolus.com/docs/work-number",
            "https://www.vba.va.gov/pubs/forms/vba-26-8497-are.pdf",
            "https://hr.university/templates/verification-of-employment-letter-templates/",
        ],
        "rows": [
            [("Employee Name", "Rosa Quill"), None, ("Rate of Pay", "18.90")],
            [("Average Hours Worked Each Week", "32")],
        ],
        "intended_fields": {
            "person_name": "Rosa Quill",
            "hourly_rate": 18.90,
            "weekly_hours": 32,
        },
        "intended_edge_case": (
            "`Average Hours Worked Each Week` is verbatim from item 15 of VA Form 26-8497 "
            "(tier A); the other two are tier B from VOE templates. No `document_date` is "
            "claimed, because none of the sources gave a caption for the letter's own date "
            "that we actually saw -- so the field is simply absent rather than invented."
        ),
    },
    {
        "file_name": "ho_007_benefit_letter_monetary_determination.pdf",
        "document_type": "benefit_letter",
        "org": "State Benefit Determination Office",
        "subtitle": "Monetary Benefit Determination",
        "doc_id": "HO-007",
        "modelled_on": (
            "NY DOL form T402B (Unemployment Insurance Monetary Benefit Determination) "
            "for the letter date; VA award-letter wording for the monthly amount"
        ),
        "tier": "A/B",
        "sources": [
            "https://forms.labor.ny.gov/UI/T402B.pdf",
            "https://cck-law.com/blog/understanding-your-va-disability-compensation-award-letter/",
        ],
        "rows": [
            [("Date Mailed", "2026-06-30"), None,
             ("Monthly Entitlement Amount", "1247.00")],
        ],
        "intended_fields": {
            "document_date": "2026-06-30",
            "monthly_benefit": 1247.00,
        },
        "intended_edge_case": (
            "`Date Mailed` is tier A from the NY determination form; `Monthly Entitlement "
            "Amount` is tier B. This is the thinnest document in the set and that is "
            "honest: the SSA benefit-verification letters we most wanted are published "
            "only as scanned images with no text layer, so we could not read their "
            "captions and refused to guess at them. Benefit letters are the weakest-"
            "evidenced corner of this hold-out set."
        ),
    },
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for spec in DOCS:
        rows = [[cell for cell in row if cell] for row in spec.get("rows", [])]
        doc = build_page({**spec, "rows": rows})
        target = OUT_DIR / spec["file_name"]
        doc.save(target)
        doc.close()
        manifest.append(
            {
                "file_name": spec["file_name"],
                "document_type": spec["document_type"],
                "cohort": "label_wording_holdout",
                "rasterized": False,
                "degraded": False,
                "watermarked": True,
                "modelled_on": spec["modelled_on"],
                "sources": spec["sources"],
                "label_strings": sorted(
                    {label for row in rows for label, _ in row}
                ),
                "intended_fields": spec["intended_fields"],
                "intended_edge_case": spec["intended_edge_case"],
            }
        )
        print(f"wrote {target.name}")

    MANIFEST.write_text(
        json.dumps(
            {
                "generated_by": "scripts/make_holdout.py",
                "reference_date": "2026-07-18",
                "purpose": (
                    "Hold-out set for label vocabulary. The 26 documents in "
                    "uploads_manifest.json share an author with LABEL_SYNONYMS, so the "
                    "label-wording score measured on them is circular. These documents "
                    "use label strings taken from real-world payroll and verification "
                    "documents instead, gathered before the table was read."
                ),
                "provenance": PROVENANCE,
                "safety": (
                    "All names are obvious placeholders, all organisations are invented, "
                    "all street numbers are out of range for their city/ZIP, no SSNs "
                    "appear, and every page carries a visible SYNTHETIC watermark. No "
                    "real document was copied -- only label vocabulary was borrowed."
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
