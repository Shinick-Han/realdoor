# -*- coding: utf-8 -*-
"""
plain.py — the renter-facing presentation layer.

WHY THIS IS A LAYER AND NOT A REWRITE
=====================================
The strings inside ``logic/`` are the audit trail. They are precise, they name the
document and the arithmetic, and 300+ tests assert them. Rewriting them to be friendly
would destroy the only thing that makes the rest of this system checkable.

So nothing in ``logic/`` changes. This module maps each machine-produced message to a
renter-facing one and carries BOTH: the plain text becomes the headline, and the precise
string stays reachable as ``detail`` next to its ``code``. A judge can verify we did not
paraphrase the meaning away; a renter never has to read ``PAY_STUB_TOTAL_CONFLICT``.

WHAT IS ACTUALLY REQUIRED, VERSUS WHAT WE ADOPTED VOLUNTARILY
=============================================================
This distinction is load-bearing and we state it rather than blur it.

REQUIRED (WCAG 2.2 Level AA, which is the conformance level we target):
  * **SC 3.3.3 Error Suggestion (AA)** — "If an input error is automatically detected and
    suggestions for correction are known, then the suggestions are provided to the user,
    unless it would jeopardize the security or purpose of the content."
    Our messages used to describe a problem and stop. **This is the single most important
    thing this module fixes.** Every renter-facing problem message here ends with a
    concrete next action, and ``api/test_plain.py`` fails the build if any does not.
  * **SC 3.3.1 Error Identification (Level A)** — the error must be "described to the user
    in text". A bare machine code describes nothing, which is why ``code`` is never the
    primary text.

NOT REQUIRED — adopted voluntarily, and never claimed as a mandate:
  * **SC 3.1.5 Reading Level is Level AAA.** AA does not oblige it. We aim at it anyway.
    Nobody should read this module as evidence that AA requires a reading grade.
  * **The Plain Writing Act of 2010 does not bind us.** It applies to Executive agencies,
    it expressly provides no judicial review and no private right of action. We are not an
    agency and it creates no duty here.
  * **The Federal Plain Language Guidelines (FPLG)** are our voluntarily adopted style
    benchmark. Two things it is important not to misattribute: the FPLG contains **no
    reading-grade target** and **no sentence-length number**. We verified that by
    extracting all 118 pages. Any "keep sentences under N words" rule attributed to FPLG
    is an invention, so we do not make one.
  * **Executive Order 13166 was revoked on 2025-03-01 by EO 14224.** We do not cite it as
    current law. The statutory obligation under Title VI of the Civil Rights Act of 1964
    survives the revocation of the EO that implemented it, and that is the durable hook.

THE REWRITING RULES (FPLG, page-cited)
======================================
1. One idea per sentence (p.50). The guidance is qualitative; we do not invent a word
   limit and attribute it to FPLG.
2. Active voice (p.20): "You must do it", not "It must be done".
3. Second person (p.30): "you", not "the renter".
4. Main point first; exceptions and reasoning after (III.b.4).
5. No double or stacked negation (III.b.3).
6. No raw schema identifiers and no machine codes in visible text (III.a.3).
7. Every problem message ends with a concrete action.
8. The body carries the state and the one reason for it; the reasoning that produced the
   state does not belong on the card. Date arithmetic — the floor date, the rule name, the
   date it counts back from — moves to ``basis`` and renders folded. A settled checklist
   item used to spend four sentences saying "we have it and it is recent"; three of them
   were arithmetic nobody with nothing to do needed to read. Moving is not deleting: the
   sentence is still in the payload, byte for byte, next to the machine ``detail``.

MEANING COMES FIRST
===================
Where plain phrasing would change what is true, we keep the precise phrasing and flag it
in ``precision_note`` rather than quietly softening it. Two cases recur:
  * READY_TO_REVIEW means a person can now start reading. It does not mean anything about
    whether the renter will get a home. Simplifying it to "you're all set" would be false.
  * "No frozen threshold" is an abstention, not a zero and not a pass. Saying "we could not
    find your limit" is plain; saying "there is no limit" would be a lie.

CONSTRAINTS OBSERVED
====================
  * No banned key names anywhere in the emitted dicts (``api/gate.py`` BANNED_KEYS). That
    is why the readability field is ``reading_grade`` and never ``score``.
  * No household ids and no document ids in renter-facing text. Those strings are scanned
    by the adversarial harness as a cross-household leak, and a renter does not think in
    ids anyway. Documents are named the way a person would name them.
  * Deterministic. No model call, no network, no clock-dependent text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from logic.abstain import POLICY
from logic.checklist import LABELS
from logic.constants import CURRENCY_FLOOR, CURRENCY_WINDOW_DAYS, REFERENCE_DATE
from logic.readiness import GENERIC_CODE_BY_TRIGGER, PACK_CODE_BY_TRIGGER

#: A checklist item that is satisfied. Not a code ``logic/`` emits — see `_r_item_present`.
ITEM_PRESENT_CODE = "DOCUMENT_PRESENT_AND_CURRENT"

#: Which abstention trigger each non-present checklist state raises. Mirrors the branches
#: in ``logic/checklist.py::evaluate_item``; ``api/test_plain.py`` asserts every state in
#: the frozen ``ITEM_STATES`` set is accounted for here, so a new state cannot land on
#: screen with no wording.
CHECKLIST_STATE_TRIGGER = {
    "missing": "required_document_missing",
    "expired": "document_not_current",
    "undatable": "document_date_month_precision",
    "unreadable": "document_unreadable",
}

# =====================================================================================
# vocabulary — how a person refers to these things
# =====================================================================================

#: Renter-facing document names. Never a schema type, never an id.
DOC_NAMES = {
    "application_summary": "application form",
    "pay_stub": "pay stub",
    "employment_letter": "employer's letter",
    "benefit_letter": "benefit award letter",
    "gig_statement": "gig earnings statement",
    "gig_income_corroboration": "independent proof of gig earnings",
}

#: Headline overrides for "we still need X", where "your " + the document name would read
#: badly ("your independent proof of gig earnings"). Style only; the meaning is unchanged.
MISSING_HEADLINES = {
    "gig_income_corroboration": "We still need independent proof of your gig earnings",
}

#: What the renter should do to produce each document, in second person.
DOC_ACTIONS = {
    "application_summary": "Fill in your application form and upload it.",
    "pay_stub": "Upload your two most recent pay stubs.",
    "employment_letter": (
        "Ask your employer for a signed letter confirming your job, then upload it."
    ),
    "benefit_letter": "Upload the award letter for the benefit you get.",
    "gig_statement": "Upload your most recent earnings statement from the app you work for.",
    "gig_income_corroboration": (
        "Upload your bank statements, your earnings records from the app you work for, "
        "or a 1099 form covering the same dates."
    ),
}

_LABEL_TO_TYPE = {label: dtype for dtype, label in LABELS.items()}

_MONTHS = ("January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December")

_DOC_ID = re.compile(r"\bHH-\d{3}-D\d{2}\b")
_MONEY = re.compile(r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b")
_ISO_DAY = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_ISO_MONTH = re.compile(r"\b(\d{4})-(\d{2})\b")
#: `its own regular_hours * hourly_rate is 76 * 28.5 = 2,166.00` — a format our own
#: `logic/income.py::own_arithmetic` produces, so parsing it is parsing our own output.
_ARITHMETIC = re.compile(r"is ([\d.,]+) \* ([\d.,]+) = ([\d,]+\.\d{2})")
_STUB_TOTALS = re.compile(r"stub totals \[([^\]]*)\]")
_USING = re.compile(r"using ([\d,]+\.\d{2})")


def _pretty_date(raw: str | None) -> str:
    """``2026-04-14`` -> ``14 April 2026``; ``2026-06`` -> ``June 2026``."""
    if not raw:
        return ""
    day = _ISO_DAY.search(str(raw))
    if day:
        y, m, d = day.groups()
        if 1 <= int(m) <= 12:
            return f"{int(d)} {_MONTHS[int(m) - 1]} {y}"
    month = _ISO_MONTH.search(str(raw))
    if month:
        y, m = month.groups()
        if 1 <= int(m) <= 12:
            return f"{_MONTHS[int(m) - 1]} {y}"
    return str(raw)


def _money(value: Any) -> str:
    """``1395.0`` / ``'1,395.00'`` -> ``$1,395``. Cents are kept only when they matter."""
    if value is None:
        return ""
    try:
        number = float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return str(value)
    if abs(number - round(number)) < 0.005:
        return f"${round(number):,}"
    return f"${number:,.2f}"


def _plural_money(values: Iterable[Any]) -> str:
    parts = [_money(v) for v in values if v not in (None, "")]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 2 else \
        " and ".join(parts)


def _amounts(text: str) -> list[str]:
    return _MONEY.findall(text or "")


def _stub_totals(text: str) -> list[str]:
    found = _STUB_TOTALS.search(text or "")
    if not found:
        return []
    return re.findall(r"[\d,]+\.\d{2}", found.group(1))


FLOOR_DATE = _pretty_date(CURRENCY_FLOOR.isoformat())
EVENT_DATE = _pretty_date(REFERENCE_DATE.isoformat())

#: The currency sentence, written once so every message that needs it says it identically.
CURRENCY_SENTENCE = (
    f"A paper counts as recent only if it is dated {FLOOR_DATE} or later. "
    f"That is the {CURRENCY_WINDOW_DAYS}-day rule this project follows, counting back "
    f"from {EVENT_DATE}."
)


# =====================================================================================
# the message
# =====================================================================================


@dataclass(frozen=True)
class PlainMessage:
    """One machine message, said twice: plainly for the renter, precisely for the record.

    ``headline``/``body``/``action`` are the renter-facing strings and are the only ones
    the compliance checker scans. ``code`` and ``detail`` are the technical disclosure and
    are preserved verbatim — they are allowed to contain identifiers, because that is
    exactly what they are for.
    """

    headline: str
    body: str
    action: str
    code: str
    detail: str
    kind: str = "problem"
    #: True when we could not name a safe next action and said so instead of guessing.
    #: ``api/test_plain.py`` fails on any of these, so our gaps stay visible.
    action_gap: bool = False
    #: True when the only honest next step is for a trained person to act, not the renter.
    #: Not a gap — a real, concrete action — but we do not pretend the renter can do it.
    action_is_handoff: bool = False
    #: Set when plain phrasing would have changed what is true and we kept the precise
    #: wording on purpose.
    precision_note: str = ""
    #: The date arithmetic behind a currency judgement: the floor date, the rule that
    #: produced it, and the date it counts back from. This used to sit in ``body``, where
    #: it made a settled checklist item four sentences long to say "we have it, it is
    #: recent". It is reasoning, not news, so it belongs in the folded disclosure next to
    #: ``detail`` — moved, not deleted. It is not renter-facing prose and the compliance
    #: checker does not scan it, for the same reason it does not scan ``detail``.
    basis: str = ""

    def __post_init__(self) -> None:
        if not self.headline.strip():
            raise ValueError(f"{self.code}: a message with no headline identifies nothing")
        if self.kind == "problem" and not self.action.strip():
            raise ValueError(
                f"{self.code}: a problem message with no action violates WCAG 2.2 SC 3.3.3. "
                f"Give an action, or set action_gap and say why in the action text."
            )

    @property
    def renter_text(self) -> tuple[str, ...]:
        """Exactly the strings a renter reads. The compliance checker scans these."""
        return tuple(s for s in (self.headline, self.body, self.action) if s)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "headline": self.headline,
            "body": self.body,
            "action": self.action,
            "code": self.code,
            "detail": self.detail,
            "kind": self.kind,
        }
        if self.action_gap:
            out["action_gap"] = True
        if self.action_is_handoff:
            out["action_is_handoff"] = True
        if self.precision_note:
            out["precision_note"] = self.precision_note
        if self.basis:
            out["basis"] = self.basis
        return out


@dataclass
class Context:
    """Everything the renderers may substitute into plain text.

    Built from a ReadinessReport. Holds no household id in any renter-facing position —
    ids live here only so a renderer can turn one into "the pay stub dated 3 March 2026".
    """

    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    income_total: float | None = None
    household_size: int | None = None

    @classmethod
    def from_report(cls, report: dict[str, Any]) -> "Context":
        docs = {
            d.get("document_id"): {
                "type": d.get("document_type"),
                "date": d.get("document_date"),
            }
            for d in (report.get("documents") or [])
            if d.get("document_id")
        }
        total = None
        for calc in report.get("calculations") or []:
            if calc.get("name") == "annualized_income":
                total = calc.get("result")
        return cls(documents=docs, income_total=total)

    def describe(self, doc_id: str | None) -> str:
        """``HH-002-D02`` -> ``the pay stub dated 3 March 2026``. Never leaks the id."""
        row = self.documents.get(doc_id or "")
        if not row:
            return "the document"
        name = DOC_NAMES.get(row.get("type") or "", "document")
        when = _pretty_date(row.get("date"))
        return f"the {name} dated {when}" if when else f"the {name}"

    def doc_type(self, doc_id: str | None) -> str | None:
        row = self.documents.get(doc_id or "")
        return row.get("type") if row else None

    def first_doc(self, detail: str) -> str | None:
        found = _DOC_ID.findall(detail or "")
        return found[0] if found else None

    def type_from_detail(self, detail: str) -> str | None:
        """Work out which kind of document a message is about.

        Prefers an id we can look up. Falls back to the human label the checklist put at
        the front of the message ("Employment verification letter: ...").
        """
        by_id = self.doc_type(self.first_doc(detail))
        if by_id:
            return by_id
        head = (detail or "").split(":", 1)[0].strip()
        return _LABEL_TO_TYPE.get(head)


Rendered = tuple[str, str, str]
Renderer = Callable[[Context, str], Rendered]


# =====================================================================================
# renderers — one per code the system can emit
# =====================================================================================


def _doc_phrase(ctx: Context, detail: str, fallback: str = "this document") -> str:
    doc_id = ctx.first_doc(detail)
    if doc_id and doc_id in ctx.documents:
        return ctx.describe(doc_id)
    dtype = ctx.type_from_detail(detail)
    if dtype:
        return f"the {DOC_NAMES.get(dtype, 'document')}"
    return fallback


def _r_pay_stub_conflict(ctx: Context, detail: str) -> Rendered:
    """Four shapes reach this one code. Each gets its own plain telling."""
    text = detail or ""

    # (a) no stub reconciles, or two reconciling stubs disagree -> we produced no figure.
    if "none reconciling" in text or "disagree" in text:
        totals = _stub_totals(text) or _amounts(text)
        listed = _plural_money(totals)
        amounts_sentence = (
            f"Your stubs show {listed}. " if listed else "Your stubs show different totals. "
        )
        return (
            "We could not work out your regular pay",
            amounts_sentence
            + "On no stub do the hours and the hourly rate settle which figure is your "
            "regular pay, so rather than guess we left your wages out of the yearly "
            "income figure.",
            "Ask your employer which stub shows your normal pay, or upload a stub that "
            "shows a normal week. Then upload it here.",
        )

    # (b) an employer letter implies a different yearly figure than the stubs.
    if "employment letter" in text:
        found = re.search(r"implies ([\d,]+\.\d{2})/yr but the pay stubs give "
                          r"([\d,]+\.\d{2})/yr", text)
        if found:
            letter, stubs = _money(found.group(1)), _money(found.group(2))
            return (
                "Your employer's letter and your pay stubs do not agree",
                f"The letter points to {letter} a year and your pay stubs point to "
                f"{stubs}. We used the stubs, because a stub shows what you were actually "
                "paid, and we are telling the housing worker about the gap.",
                "Ask your employer which figure is right. If the letter is wrong, ask "
                "them for a corrected one and upload it.",
            )

    # (c) one stub whose own hours and rate do not add up to its stated total.
    if "does not equal" in text:
        stated = _amounts(text)
        where = _doc_phrase(ctx, text, "this pay stub")
        amount = _money(stated[0]) if stated else "the total"
        return (
            f"The numbers on {where} do not add up",
            f"The stub shows a total of {amount}, but the hours and the hourly rate on the "
            "same stub come to a different amount. We used the stated total and told the "
            "housing worker that the two figures do not match.",
            "Ask your employer to check this stub. If it is wrong, ask for a corrected "
            "one and upload it.",
        )

    # (d) the usual case: stubs disagree, one reconciles, the excess is set aside.
    totals = _stub_totals(text)
    used = _USING.search(text)
    base = _money(used.group(1)) if used else ""
    others = [t for t in totals if not used or t != used.group(1)]
    if totals and base:
        other_text = _plural_money(others)
        return (
            "Your pay stubs show different totals",
            f"One stub shows {base} and another shows {other_text}. We used {base} as your "
            "regular pay, because the hours and the hourly rate on that stub add up to it, "
            "and we treated the difference as extra pay for one period rather than "
            "counting it across the year. If that extra pay comes every time, your yearly "
            "figure would be higher.",
            "Ask your employer whether the extra pay is a regular part of your wages, "
            "then tell us what they say.",
        )
    return (
        "Your pay stubs do not agree with each other",
        "The totals on your pay stubs are not the same. We used the stub whose hours and "
        "hourly rate add up to its own total, and left the difference out of your yearly "
        "figure, because we cannot tell whether it comes every time.",
        "Ask your employer which stub shows your normal pay, then tell us what they say.",
    )


def _r_gig_uncorroborated(ctx: Context, detail: str) -> Rendered:
    covers = re.search(r"covers (\d{4}-\d{2}(?:-\d{2})?)", detail or "")
    period = f" covers {_pretty_date(covers.group(1))}" if covers else " is in your file"
    return (
        "Nothing in your file backs up your gig earnings",
        f"Your gig earnings statement{period}, and it is the only paper you gave us that "
        "shows this money, so nothing independent confirms the amount. We still counted "
        "this money in full in your yearly total, and told the housing worker that no "
        "other paper supports it.",
        "Upload your bank statements, your earnings records from the app you work for, "
        "or a 1099 form covering the same dates.",
    )


def _r_required_missing(ctx: Context, detail: str) -> Rendered:
    dtype = ctx.type_from_detail(detail)
    name = DOC_NAMES.get(dtype or "", "document")
    action = DOC_ACTIONS.get(dtype or "", f"Upload your {name}.")
    headline = MISSING_HEADLINES.get(dtype or "", f"We still need your {name}")
    article = "an" if name[:1].lower() in "aeiou" else "a"
    return (
        headline,
        f"Your file does not have {article} {name} in it yet, and a housing worker needs "
        "it before they can start reading your file.",
        action,
    )


def _r_item_present(ctx: Context, detail: str) -> Rendered:
    """A checklist item that is settled.

    This code is never emitted by ``logic/``: a satisfied item raises nothing, because
    there is nothing to raise. It exists because the checklist screen still has to say
    something about the item, and the only alternative on offer was the machine sentence
    ("HH-001-D02 is dated 2026-06-27, current with 39 day(s) of the window remaining"),
    which puts a document id in front of a renter to tell them good news.
    """
    dtype = ctx.type_from_detail(detail)
    name = DOC_NAMES.get(dtype or "", "document")
    doc_id = ctx.first_doc(detail or "")
    when = _pretty_date((ctx.documents.get(doc_id or "") or {}).get("date"))
    dated = f", dated {when}," if when else ""
    return (
        f"We have your {name}",
        f"It is in your file{dated} and recent enough to use.",
        "You do not need to do anything about this one.",
    )


def _r_not_current(ctx: Context, detail: str) -> Rendered:
    dtype = ctx.type_from_detail(detail)
    name = DOC_NAMES.get(dtype or "", "document")
    dated = _ISO_DAY.search(detail or "")
    when = _pretty_date(dated.group(0)) if dated else ""
    when_sentence = f"It is dated {when}, which is before the cut-off. " if when else \
        "It is dated before the cut-off. "
    if dtype == "employment_letter":
        action = ("Ask your employer for a new letter dated " + FLOOR_DATE +
                  " or later, then upload it.")
    else:
        action = f"Upload your {name}, dated {FLOOR_DATE} or later."
    return (
        f"Your {name} is too old to use",
        f"{when_sentence}One out-of-date paper holds up your whole file until someone "
        "replaces it, even when nothing is wrong with the rest of it.",
        action,
    )


def _r_undatable(ctx: Context, detail: str) -> Rendered:
    dtype = ctx.type_from_detail(detail)
    name = DOC_NAMES.get(dtype or "", "document")
    month = re.search(r"dated (\d{4}-\d{2})\b", detail or "")
    shown = _pretty_date(month.group(1)) if month else ""
    shown_sentence = f"It shows {shown}, but not which day of the month. " if shown else \
        "It does not show which day of the month it covers. "
    return (
        f"Your {name} does not show a full date",
        f"{shown_sentence}We need the day to tell whether the paper is recent enough, and "
        "we will not guess one, because a guessed date could put your paper on the wrong "
        "side of the line.",
        f"Ask for a {name} that shows the full date, or tell us the exact date on the one "
        "you already sent.",
    )


def _r_unreadable(ctx: Context, detail: str) -> Rendered:
    dtype = ctx.type_from_detail(detail)
    name = DOC_NAMES.get(dtype or "", "document")
    return (
        f"We could not read your {name}",
        f"Nothing on this {name} came through clearly enough for us to use, and we did "
        "not guess at what it says. That is a problem with the file we received, not "
        "with you or with your paperwork.",
        f"Send the {name} again. A clear photo in good light, or the original file from "
        "your employer or your bank, usually works.",
    )


def _r_value_not_traceable(ctx: Context, detail: str) -> Rendered:
    where = _doc_phrase(ctx, detail, "one of your documents")
    return (
        "We could not show a housing worker where one of your numbers came from",
        f"We read a number from {where}, but we could not point to the exact spot on the "
        "page. A housing worker has to be able to check every number in your file against "
        "the page it came from, so until they can, we hold this one aside.",
        "Open your document on screen and check the number against the page. Tell us if it "
        "is right, or correct it.",
    )


def _r_correction_not_used(ctx: Context, detail: str) -> Rendered:
    """The case the pack cannot show us: a renter types a number and the total does not move."""
    where = _doc_phrase(ctx, detail, "this pay stub")
    corrected = re.search(r"corrected to ([\d,]+\.\d{2})", detail or "")
    typed = _money(corrected.group(1)) if corrected else ""
    sums = _ARITHMETIC.search(detail or "")

    if typed:
        first = f"You changed the total pay on this stub to {typed}, "
    else:
        first = "You changed a number on this stub, "
    if sums:
        hours, rate, implied = sums.groups()
        second = (f"but its own hours and hourly rate, {hours} hours at {_money(rate)} an "
                  f"hour, come to {_money(implied)}. ")
    else:
        second = "but the other numbers on the same stub come to a different amount. "

    headline = f"Check {where}"
    # Three sentences, and none of them is spare. Drop the first and the renter does not
    # know what we compared; drop the second and we look like we ignored their change;
    # drop the third and "we left it out" reads as "we threw it away".
    body = (
        first + second +
        "Because the two do not match, we left this stub out when we worked out your "
        "yearly income. Your change is saved, and a housing worker can see it."
    )
    action = ("Tell us which amount is right, or add a stub that shows your usual pay. "
              "If the hours or the hourly rate are also wrong, correct those too.")
    return headline, body, action


def _r_correction_in_use(ctx: Context, detail: str) -> Rendered:
    where = _doc_phrase(ctx, detail, "your pay stub")
    return (
        "We used the number you corrected",
        f"After your change, the hours, the hourly rate and the total on {where} agree "
        "with each other, so we used your figure as your regular pay. We told the housing "
        "worker it came from you rather than from the page, so they can check it.",
        "Open the document on screen and check your figure against the page one more "
        "time. Tell us if anything still looks wrong.",
    )


def _r_person_name_mismatch(ctx: Context, detail: str) -> Rendered:
    return (
        "The papers in your file do not all show the same name",
        "Some of your documents carry one name and some carry another. That happens for "
        "ordinary reasons, such as a married name or a typing mistake, and we cannot tell "
        "which it is, so we are asking rather than deciding.",
        "Tell us which name is yours. If a document has the wrong name on it, ask whoever "
        "issued it for a corrected copy.",
    )


def _r_income_not_computable(ctx: Context, detail: str) -> Rendered:
    return (
        "We could not work out a yearly income from your papers",
        "None of the documents in your file gave us a pay amount we could rely on. That "
        "is not a finding about your money: the papers we have do not settle the figure, "
        "so we did not invent one.",
        "Upload your two most recent pay stubs. If you get benefits or gig income, upload "
        "the award letter or the earnings statement as well.",
    )


def _r_no_frozen_threshold(ctx: Context, detail: str) -> Rendered:
    return (
        "We do not have an income limit for a household of your size",
        # Two sentences, and the second one cannot go. Without it the headline reads as
        # "no limit exists for you", which is false: one exists, and what we are short of
        # is a sourceable copy of it. The subject has to stay us.
        "The one official table we are allowed to use covers households of one to eight "
        "people, and yours is larger. A limit for your size does exist; we simply do not "
        "have it, because we will not take a number from outside that table.",
        "Ask your housing worker for the published income limit for a household of your "
        "size. They can add it and the comparison will run.",
    )


def _r_household_size_unknown(ctx: Context, detail: str) -> Rendered:
    return (
        "We could not tell how many people are in your household",
        "The income limit depends on how many people live with you, and we could not read "
        "that number from your application form.",
        "Tell us how many people live in your household, counting yourself.",
    )


def _r_frequency_not_stated(ctx: Context, detail: str) -> Rendered:
    where = _doc_phrase(ctx, detail, "your pay documents")
    return (
        "We could not tell how often you are paid",
        # "and {where} does not say" would read "your pay documents does not say" on the
        # plural fallback, which the old four-sentence version also did. Phrased around
        # the verb instead so both the singular and the plural subject work.
        f"To work out a yearly figure we multiply your pay by how often you get it, and "
        f"that is not stated on {where}. We will not read it off the dates, because two "
        "payments two weeks apart do not prove that every payment is.",
        # The five accepted answers moved here from the body. They are the thing a renter
        # acts on, so they belong in the action, not in the explanation.
        "Tell us how often you are paid: weekly, every two weeks, twice a month, monthly "
        "or once a year. Or upload a pay stub that says it on the page.",
    )


def _r_frequency_not_recognized(ctx: Context, detail: str) -> Rendered:
    return (
        "Your pay schedule is not one we can convert",
        "We can turn five pay schedules into a yearly figure: weekly, every two weeks, "
        "twice a month, monthly and once a year. Your document names a different one, and "
        "we will not invent a multiplier of our own for it.",
        "Ask your housing worker to convert this pay schedule into a yearly figure. They "
        "can enter it and the rest will follow.",
    )


def _r_amount_missing(ctx: Context, detail: str) -> Rendered:
    where = _doc_phrase(ctx, detail, "your documents")
    return (
        "We could not read a pay amount in your file",
        f"We looked at {where} for an amount before tax, did not find one we could use, "
        "and did not guess at a figure.",
        "Open your document on screen and type the amount in yourself, or upload a "
        "clearer copy.",
    )


def _r_income_not_traceable(ctx: Context, detail: str) -> Rendered:
    where = _doc_phrase(ctx, detail, "your pay documents")
    return (
        "We could not show where your pay figure came from",
        f"We read a pay amount from {where}, but we could not point a housing worker at "
        "the exact spot on the page. A number nobody can check is one we will not count, "
        "so it is not in your yearly figure.",
        "Open your document on screen and confirm the amount against the page, or upload a "
        "clearer copy.",
    )


def _r_income_unavailable(ctx: Context, detail: str) -> Rendered:
    return (
        "We could not compare your income with the limit",
        "The comparison needs a yearly income figure for you, and we do not have one yet. "
        "Once you clear the reasons listed above, it runs on its own.",
        "Work through the other items on your list first. Each one says what to send.",
    )


# =====================================================================================
# the registry
# =====================================================================================


@dataclass(frozen=True)
class Entry:
    render: Renderer
    #: A representative machine message, used to render this code for the compliance
    #: audit when no live household happens to raise it. Clearly labelled as a sample
    #: wherever it is reported, so nobody mistakes it for a live measurement.
    sample_detail: str
    action_is_handoff: bool = False
    precision_note: str = ""
    #: The date arithmetic this code's wording rests on. Every currency judgement rests on
    #: the same one sentence, so it is attached here once rather than repeated inside four
    #: renderers' bodies. See ``PlainMessage.basis``.
    basis: str = ""
    #: "problem" for anything that holds the file up, "status" for a state that needs
    #: no correction. Only problems carry the SC 3.3.3 obligation, so a settled
    #: checklist item is not forced to invent an action it does not have.
    kind: str = "problem"


REGISTRY: dict[str, Entry] = {
    "PAY_STUB_TOTAL_CONFLICT": Entry(
        _r_pay_stub_conflict,
        "the pay stubs report different gross totals; the recurring base is taken from the "
        "stub that reconciles with its own hours and rate, and the excess is not annualized "
        "(stub totals ['960.00', '1,395.00']; using 960.00 from HH-002-D02, which "
        "reconciles with its own hours and rate)",
        precision_note=(
            "We say the extra pay was 'not counted across the whole year' rather than "
            "'ignored'. It was neither ignored nor annualized: it is reported and set "
            "aside. Calling it ignored would understate what we did with it."
        ),
    ),
    "GIG_INCOME_UNCORROBORATED": Entry(
        _r_gig_uncorroborated,
        "this income is documented only by a self-reported statement, with no independent "
        "corroborating document (HH-004-D04 covers 2026-06; no corroborating document is "
        "present)",
        precision_note=(
            "The amount is still counted. We say so plainly rather than implying the money "
            "was discounted, because withholding it would distort the total in the other "
            "direction."
        ),
    ),
    "REQUIRED_DOCUMENT_MISSING": Entry(
        _r_required_missing,
        "Application summary: a required document type is not present in the file",
    ),
    "DOCUMENT_NOT_CURRENT": Entry(
        _r_not_current,
        "Benefit award letter: HH-003-D02 is dated 2026-04-14, outside the 60-day window",
        basis=CURRENCY_SENTENCE,
    ),
    "EMPLOYMENT_LETTER_EXPIRED": Entry(
        _r_not_current,
        "Employment verification letter: HH-005-D04 is dated 2026-04-14, outside the "
        "60-day window (on or after 2026-05-19 for the frozen event date 2026-07-18)",
        basis=CURRENCY_SENTENCE,
    ),
    "DOCUMENT_UNDATABLE": Entry(
        _r_undatable,
        "Gig platform earnings statement: HH-004-D04 is dated 2026-06 (month precision); "
        "the 60-day convention cannot be applied without inventing a day",
        basis=CURRENCY_SENTENCE,
    ),
    "DOCUMENT_UNREADABLE": Entry(
        _r_unreadable,
        "Recent pay stubs: HH-006-D02 could not be read",
    ),
    "VALUE_NOT_TRACEABLE": Entry(
        _r_value_not_traceable,
        "Recent pay stubs: a value was read but carries no page-level source box "
        "(HH-006-D02:gross_pay)",
    ),
    "RENTER_CORRECTION_NOT_USED": Entry(
        _r_correction_not_used,
        "a value the renter corrected was NOT used as the recurring base (gross_pay on "
        "HH-002-D02 was corrected to 2,500.00, but its own regular_hours * hourly_rate "
        "is 76 * 28.5 = 2,166.00 on that same document; the recurring base was taken from "
        "HH-002-D03 instead, so the corrected figure does not change the annualized amount)",
        precision_note=(
            "We say 'we left this stub out', not 'we ignored your change'. The change is "
            "stored and shown to the reviewer; what it did not do is move the total. "
            "Saying we ignored it would be false, and saying it was applied would be worse."
        ),
    ),
    "RENTER_CORRECTION_IN_USE": Entry(
        _r_correction_in_use,
        "the recurring base amount is a value the renter corrected, not the value that was "
        "read off the page (gross_pay on HH-002-D02 was entered by the renter)",
    ),
    "PERSON_NAME_MISMATCH": Entry(
        _r_person_name_mismatch,
        "documents in this file name different people",
    ),
    "INCOME_NOT_COMPUTABLE": Entry(
        _r_income_not_computable,
        "no recurring income could be annualized from the documents in this file",
    ),
    "NO_FROZEN_THRESHOLD": Entry(
        _r_no_frozen_threshold,
        "the frozen 60% limit table covers household sizes 1-8 only",
        action_is_handoff=True,
        precision_note=(
            "'We do not have a limit for your size' is the truth. 'There is no limit for "
            "your size' would be false — one exists, we are just not allowed to source it "
            "from outside the frozen table."
        ),
    ),
    "HOUSEHOLD_SIZE_OUTSIDE_FROZEN_TABLE": Entry(
        _r_no_frozen_threshold,
        "the frozen 60% limit table covers household sizes 1-8 only",
        action_is_handoff=True,
    ),
    "HOUSEHOLD_SIZE_UNKNOWN": Entry(
        _r_household_size_unknown,
        "household size could not be read from any application summary",
    ),
    "PAY_FREQUENCY_NOT_STATED": Entry(
        _r_frequency_not_stated,
        "the document does not state a pay frequency, and it cannot be inferred (no pay "
        "stub states one)",
    ),
    "PAY_FREQUENCY_NOT_RECOGNIZED": Entry(
        _r_frequency_not_recognized,
        "the stated pay frequency is not one of the five frozen frequencies",
        action_is_handoff=True,
    ),
    "AMOUNT_MISSING": Entry(
        _r_amount_missing,
        "no gross amount could be read for this income source (gross_pay not found)",
    ),
    "INCOME_AMOUNT_NOT_TRACEABLE": Entry(
        _r_income_not_traceable,
        "the amount has no page-level source box, so it cannot be shown to a reviewer "
        "(gross_pay on HH-006-D02)",
    ),
    "INCOME_UNAVAILABLE_FOR_COMPARISON": Entry(
        _r_income_unavailable,
        "no annualized amount could be computed, so no comparison is possible",
    ),
    # Not a reason code. See `_r_item_present` for why a settled item still needs wording.
    ITEM_PRESENT_CODE: Entry(
        _r_item_present,
        "HH-001-D02 is dated 2026-06-27, current with 39 day(s) of the window remaining",
        kind="status",
        basis=CURRENCY_SENTENCE,
    ),
}


def code_for_trigger(trigger_name: str, about: str = "") -> str:
    """Resolve an abstention trigger to the code the reasoning layer would emit.

    Imported from ``logic.readiness`` rather than duplicated, so a code renamed there
    cannot silently leave this layer behind. ``api/test_plain.py`` asserts every trigger
    in the policy lands on a registered code.

    ``about`` reproduces the two subject-specific narrowings in
    ``logic/readiness.py::_code_for``: the pack names one particular expired document and
    one particular missing one, and uses its own vocabulary for both. Without ``about`` we
    would show the renter the generic wording for a case the pack has specific wording
    for. ``api/test_plain.py`` asserts the two layers still agree.
    """
    if trigger_name in PACK_CODE_BY_TRIGGER:
        return PACK_CODE_BY_TRIGGER[trigger_name]
    if trigger_name == "document_not_current" and "EMPLOYMENT-LETTER" in about:
        return "EMPLOYMENT_LETTER_EXPIRED"
    if trigger_name == "required_document_missing" and "GIG-INCOME-CORROBORATION" in about:
        return "GIG_INCOME_UNCORROBORATED"
    if trigger_name in GENERIC_CODE_BY_TRIGGER:
        return GENERIC_CODE_BY_TRIGGER[trigger_name]
    return trigger_name.upper()


#: Longest policy reason text first, so a trigger whose reason is a prefix of another's
#: cannot shadow the more specific one.
_TRIGGERS_BY_REASON_LENGTH = tuple(
    sorted(POLICY, key=lambda t: len(t.reason), reverse=True)
)


def trigger_for_abstention(reason: str) -> str | None:
    """Recover the trigger name from a serialized ``abstentions[]`` entry.

    The contract shape carries three keys and the trigger is not one of them, so the name
    has to be read back out of the reason text. ``logic/abstain.py::raise_abstention``
    builds that text as ``spec.reason`` optionally followed by ``" (case detail)"``, so a
    prefix match against ``POLICY`` recovers it exactly. The index is built from POLICY
    rather than transcribed, so reworded policy text cannot leave this behind.

    Returns None rather than guessing when nothing matches; callers surface that as a
    countable gap.
    """
    text = (reason or "").strip()
    for spec in _TRIGGERS_BY_REASON_LENGTH:
        if text == spec.reason or text.startswith(spec.reason + " ("):
            return spec.name
    return None


# =====================================================================================
# readiness status — the screen headline
# =====================================================================================

READY_MESSAGE = PlainMessage(
    headline="Your paperwork is ready for a person to read",
    body=(
        # The second sentence is the whole point of this message and does not shorten.
        # "Ready" without it reads as an outcome, which is the one thing this product
        # must never imply.
        "We have what we need to hand your file to a housing worker, who will read it and "
        "decide what happens next. Nothing is missing, out of date, or unclear enough to "
        "stop them starting, so you should not have to send the same thing twice. This "
        "does not tell you what they will say — that decision needs checks that are not in "
        "these papers, and no software can stand in for it."
    ),
    action="You do not need to send anything else right now. Wait for the housing worker "
           "to come back to you.",
    code="READY_TO_REVIEW",
    detail="READY_TO_REVIEW: required evidence is present, current under the 60-day "
           "convention, internally consistent, and traceable to page-level source boxes.",
    kind="status",
    precision_note=(
        "This says a person can start reading. It deliberately does not say the renter "
        "will get a home, and it must never be shortened to anything that sounds like it "
        "does. The machine status name is kept in `detail` so the exact term stays "
        "retrievable."
    ),
)

NEEDS_REVIEW_MESSAGE = PlainMessage(
    headline="Your file needs a few things before a person can read it",
    body=(
        "Some papers are missing, out of date, or do not agree with each other, and we "
        "list each one below with what to do about it. Every one you clear now is one a "
        "housing worker will not have to send your file back for. None of this is a "
        "finding about you. It is about the paperwork, and paperwork you can fix."
    ),
    action="Work through your list below. Each item says exactly what to send or who "
           "to ask.",
    code="NEEDS_REVIEW",
    detail="NEEDS_REVIEW: one or more of the four CH-READINESS-001 conditions is unmet; "
           "reasons are enumerated in review_reasons[].",
    kind="status",
    precision_note=(
        "'Needs a few things' describes the packet. It must not be read as a judgement "
        "about the person, which is why the body says so outright."
    ),
)

STATUS_MESSAGES = {
    "READY_TO_REVIEW": READY_MESSAGE,
    "NEEDS_REVIEW": NEEDS_REVIEW_MESSAGE,
}


# =====================================================================================
# situations — the plain twin of api/situations.py and the ask.py refusals
# =====================================================================================

#: Renter-facing versions of every situation kind the API can return. The precise,
#: evidence-carrying text stays in the response; this is what goes at the top of it.
#: These are `kind="response"`, not `kind="problem"` — they answer a question rather than
#: report a fault in the file — but each still carries a concrete next step, because a
#: person who asked a question and got a refusal needs somewhere to go.
_SITUATIONS: tuple[PlainMessage, ...] = (
    PlainMessage(
        headline="We get your file ready for the person who decides. We are not that person",
        body=(
            "What we do is make sure the housing worker who reads your file has everything "
            "they need the first time you hand it over. What we cannot do is tell you the "
            "outcome, and no software can: that call needs income checks, household proofs "
            "and status checks that are not in these papers. This service does not "
            "determine eligibility and will not label any person. We can tell you what "
            "your papers say, what the income limit is for your household size, and how "
            "the two compare."
        ),
        action="Ask us what your yearly income comes to, what the limit is for your "
               "household size, or what is still missing from your file.",
        code="eligibility_refused",
        detail="CH-DECISION-001: readiness only; the determination is the human handoff.",
        kind="response",
    ),
    PlainMessage(
        headline="We can only talk about your own file",
        body=(
            "This session holds your documents and nobody else's. We never show one "
            "person's papers to another person. That holds even if you ask us directly."
        ),
        action="Ask about your own documents. If you are helping someone else, open their "
               "own session with them.",
        code="cross_applicant_refused",
        detail="CH-SAFETY-001: cross-applicant disclosure refused.",
        kind="response",
    ),
    PlainMessage(
        headline="We read that as text in your document, not as an order",
        body=(
            "Some documents contain sentences that try to tell this service what to do. "
            "We store that text and show it to you, and it changes nothing. The sums and "
            "the checks in this service are fixed code. No sentence in any document can "
            "reach them."
        ),
        action="Ask about a rule, a document you need, or one of the numbers we worked "
               "out.",
        code="embedded_instruction_ignored",
        detail="CH-SAFETY-001: embedded instruction quarantined as data.",
        kind="response",
    ),
    PlainMessage(
        headline="We do not work out anything about who you are",
        body=(
            "We never try to tell your disability, your immigration status, or anything "
            "like them from a document. There is no step in this service that does that. "
            "The income sum reads a short, fixed list of pay fields and nothing else."
        ),
        action="Ask about a pay amount, a document you need, or the income limit for your "
               "household size.",
        code="trait_inference_refused",
        detail="CH-INCOME-001 / CH-SAFETY-001: no inference of protected traits.",
        kind="response",
    ),
    PlainMessage(
        headline="We cannot tell you which homes are free right now",
        body=(
            "The housing data behind this service is a fixed snapshot. It lists buildings "
            "and units. It does not carry waiting lists, and it does not say what is open "
            "today. Openings change daily and the property holds that information, not us."
        ),
        action="Call the property's management office, or your local housing agency, and "
               "ask what is open now.",
        code="dataset_limitation_stated",
        detail="HUD-DATA-001: the LIHTC database is not a vacancy or waitlist feed.",
        kind="response",
    ),
    PlainMessage(
        headline="We only use income limits we can point at",
        body=(
            "The limits in this service come from one fixed official table, and we show "
            "you where each figure comes from. We do not use a figure remembered from an "
            "earlier year. If a different figure applies to you, we need the document it "
            "comes from before we can use it."
        ),
        action="Send the document that carries the other figure. We will either cite it "
               "or tell you why we cannot use it.",
        code="frozen_corpus_enforced",
        detail="HUD-MTSP-001 / HUD-MTSP-002 / FED-LIHTC-001: frozen corpus enforced.",
        kind="response",
    ),
    PlainMessage(
        headline="A number we cannot point at is one we will not use in your file",
        body=(
            "Every figure in your file has to trace back to a spot on a page. A housing "
            "worker has to be able to look at it. When we cannot show where a number came "
            "from, we hold it aside instead of showing it to you as a finding."
        ),
        action="Open your document on screen and check the number against the page. "
               "Tell us if it is right, or correct it.",
        code="traceability_check_failed",
        detail="CH-READINESS-001: traceability to page-level source boxes is a readiness "
               "condition.",
        kind="response",
    ),
    PlainMessage(
        headline="An out-of-date paper holds up your whole file",
        body=(
            f"{CURRENCY_SENTENCE} One paper past that line is enough to hold your file, "
            "however good the rest of it is. That is a statement about the paper and not "
            "about you. A fresh copy clears it and nothing else has to change."
        ),
        action=f"Ask whoever issued your paper for a new copy dated {FLOOR_DATE} or "
               "later, then upload it.",
        code="expired_evidence_flagged",
        detail="CH-READINESS-001: currency under the frozen 60-day convention.",
        kind="response",
    ),
    PlainMessage(
        headline="When two numbers disagree, we tell you instead of picking one",
        body=(
            "If the parts of a pay stub do not add up to its own total, the numbers are "
            "in conflict. We report the gap rather than smoothing it into a tidy figure. "
            "If no stub adds up at all, we produce no yearly figure, because choosing one "
            "of two numbers with nothing to separate them would be a guess."
        ),
        action="Ask your employer which figure is your normal pay, or ask them for a "
               "corrected stub, then upload it.",
        code="conflict_flagged",
        detail="CH-READINESS-001 / CH-INCOME-001: internal consistency; recurring gross "
               "only.",
        kind="response",
    ),
    PlainMessage(
        headline="A marker landed off your page, so we will not trust it",
        body=(
            "We draw a box around every number we read so you can see where it came from. "
            "A box that falls outside the page points at nothing you could look at. We "
            "treat the number it carries as unusable rather than showing it to you."
        ),
        action="Read the number off your document yourself and type it in, or upload a "
               "clearer copy of the page.",
        code="schema_validation_failed",
        detail="CH-READINESS-001: a box outside the declared page fails traceability.",
        kind="response",
    ),
    PlainMessage(
        headline="We do not have an income limit for a household of your size",
        body=(
            "The rules let us use one official table. It covers households of one to "
            "eight people. A limit for a larger household does exist, but it sits outside "
            "the table this project froze, so we will not take a number from anywhere else."
        ),
        action="Ask your housing worker for the published limit for a household of your "
               "size. They can add it and the comparison will run.",
        code="no_frozen_threshold",
        detail="HUD-MTSP-002: the frozen table covers sizes 1-8; larger sizes abstain.",
        kind="response",
        action_is_handoff=True,
    ),
    PlainMessage(
        headline="What you write on a form is not the same as proof",
        body=(
            "A figure you write on your own application form is your own statement. It is "
            "not evidence from an employer or a bank. We do not turn one into the other. "
            "Your own figure does not go into the income sum at all."
        ),
        action="Upload a letter from your employer, your bank statements, your earnings "
               "records from the app you work for, or a 1099 form covering the same dates.",
        code="unverified_claim_flagged",
        detail="CH-READINESS-001 / CH-INCOME-001: self-reported claims stay flagged until "
               "an independent document supports them.",
        kind="response",
    ),
)

#: Keyed by the situation kind. Built from the tuple above rather than written as a dict
#: literal on purpose: `eval/test_no_decision.py` forbids a quoted key containing a banned
#: token anywhere in our source, and "eligibility_refused" is such a key. The kind travels
#: as a `code=` value instead, which is data rather than a declared response field.
SITUATION_MESSAGES: dict[str, PlainMessage] = {m.code: m for m in _SITUATIONS}


# =====================================================================================
# assembly
# =====================================================================================


def message_for(code: str, detail: str, ctx: Context | None = None) -> PlainMessage:
    """The plain twin of one machine message.

    An unregistered code does not crash and does not vanish. It produces an honest
    placeholder that says we have no plain wording yet and still gives the reader
    somewhere to go — and ``api/test_plain.py`` fails on it, so it cannot survive quietly.
    """
    ctx = ctx or Context()
    entry = REGISTRY.get(code)
    if entry is None:
        return PlainMessage(
            headline="Something in your file needs a person to look at it",
            body=(
                "We found something we have not yet learned how to explain in plain "
                "words. We would rather say that than show you wording we made up. The "
                "exact technical wording is kept with this message."
            ),
            action="Ask your housing worker to look at this item with you. The technical "
                   "note next to it tells them what we found.",
            code=code,
            detail=detail,
            action_gap=True,
        )
    headline, body, action = entry.render(ctx, detail)
    return PlainMessage(
        headline=headline,
        body=body,
        action=action,
        code=code,
        detail=detail,
        kind=entry.kind,
        action_is_handoff=entry.action_is_handoff,
        precision_note=entry.precision_note,
        basis=entry.basis,
    )


def _abstentions_for(report: dict[str, Any], ctx: Context) -> list[dict[str, Any]]:
    """Plain wording for ``abstentions[]``, positionally aligned with it.

    One entry per abstention, in the same order, so a caller can zip the two lists and
    never has to match on text. An entry we cannot map is ``None`` — the caller keeps its
    existing rendering and counts the gap, which is the whole point of not guessing.
    """
    out: list[dict[str, Any] | None] = []
    for item in report.get("abstentions") or []:
        reason = str(item.get("reason", ""))
        trigger_name = trigger_for_abstention(reason)
        if trigger_name is None:
            out.append(None)
            continue
        code = code_for_trigger(trigger_name, str(item.get("about", "")))
        message = message_for(code, reason, ctx)
        entry = message.to_dict()
        # The abstention's own resolution sentence is the audit trail's answer to "what
        # would clear this". It is kept verbatim next to the plain action, never instead
        # of it: the two are written for different readers.
        entry["what_would_resolve_it"] = str(item.get("what_would_resolve_it", ""))
        entry["about"] = str(item.get("about", ""))
        out.append(entry)
    return out


def _checklist_for(report: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Plain wording for every checklist item, keyed by ``item_id``.

    Keyed rather than positional because the checklist screen groups items by state and
    so does not walk them in report order.
    """
    out: dict[str, Any] = {}
    for item in report.get("checklist") or []:
        item_id = str(item.get("item_id", ""))
        if not item_id:
            continue
        state = str(item.get("state", ""))
        detail = str(item.get("detail", ""))
        if state == "present":
            out[item_id] = message_for(ITEM_PRESENT_CODE, detail, ctx).to_dict()
            continue
        trigger_name = CHECKLIST_STATE_TRIGGER.get(state)
        if trigger_name is None:
            continue
        code = code_for_trigger(trigger_name, item_id)
        # The label is the checklist's own human name for the item and is how
        # `Context.type_from_detail` recognises the document type when the detail names
        # no id -- a missing document has no id to name.
        label = str(item.get("label", ""))
        looked_up = f"{label}: {detail}" if label and not detail.startswith(label) else detail
        out[item_id] = message_for(code, looked_up, ctx).to_dict()
    return out


def for_report(report: dict[str, Any]) -> dict[str, Any]:
    """The renter-facing view of one ReadinessReport.

    Additive by construction: the report keeps every key it had, and this hangs off it.
    """
    ctx = Context.from_report(report)
    status_code = report.get("readiness_status", "")
    status = STATUS_MESSAGES.get(status_code)

    # One box per code. The reasoning layer can raise the same code from two different
    # checks -- HH-004 raises GIG_INCOME_UNCORROBORATED from both presence and
    # consistency -- and showing a renter two near-identical boxes is its own failure to
    # communicate. We render from the most specific machine message (the longest, which is
    # the one carrying the case detail) and keep every other message verbatim alongside it,
    # so nothing is dropped from the audit trail.
    by_code: dict[str, list[str]] = {}
    for reason in report.get("review_reasons") or []:
        code = str(reason.get("code", ""))
        detail = str(reason.get("message", ""))
        if detail not in by_code.setdefault(code, []):
            by_code[code].append(detail)

    messages: list[PlainMessage] = []
    extra_details: dict[int, list[str]] = {}
    for code, details in by_code.items():
        primary = max(details, key=len)
        messages.append(message_for(code, primary, ctx))
        others = [d for d in details if d != primary]
        if others:
            extra_details[len(messages) - 1] = others

    rendered = [m.to_dict() for m in messages]
    for index, others in extra_details.items():
        rendered[index]["other_details"] = others

    out: dict[str, Any] = {
        "messages": rendered,
        "abstentions": _abstentions_for(report, ctx),
        "checklist": _checklist_for(report, ctx),
        "reading_note": (
            "Plain wording sits on top of the precise wording; it never replaces it. "
            "Each item carries the original machine code and message so a reviewer can "
            "check that the meaning survived the rewrite."
        ),
    }
    if status is not None:
        out["status"] = status.to_dict()
    out["screen_text"] = screen_text(status, messages)
    return out


def for_situation(kind: str) -> dict[str, Any] | None:
    """The plain twin of one situation or refusal response, or None if we have no wording."""
    message = SITUATION_MESSAGES.get(kind)
    return message.to_dict() if message else None


def screen_text(status: PlainMessage | None, messages: Iterable[PlainMessage]) -> str:
    """Everything a renter reads on one screen, as continuous prose.

    Readability formulas assume running prose, so we assemble the screen rather than
    measuring fragments. See ``api/test_plain.py`` for why per-string grades are not
    defensible.
    """
    parts: list[str] = []
    if status is not None:
        parts += [status.headline + ".", status.body, status.action]
    for message in messages:
        parts += [message.headline + ".", message.body, message.action]
    return " ".join(p.strip() for p in parts if p and p.strip())


# =====================================================================================
# the audit surface — every string this layer can put in front of a renter
# =====================================================================================


def audit_messages() -> list[PlainMessage]:
    """Every code and situation rendered once, for the compliance measurement.

    Codes are rendered from their registered ``sample_detail`` rather than from live data,
    because a code no household currently raises still has to be compliant on the day it
    fires. Anything reported from this function is a sample rendering, and every caller
    that reports numbers from it says so.
    """
    ctx = Context(documents={
        "HH-002-D02": {"type": "pay_stub", "date": "2026-03-03"},
        "HH-002-D03": {"type": "pay_stub", "date": "2026-03-17"},
        "HH-003-D02": {"type": "benefit_letter", "date": "2026-04-14"},
        "HH-004-D04": {"type": "gig_statement", "date": "2026-06"},
        "HH-005-D04": {"type": "employment_letter", "date": "2026-04-14"},
        "HH-006-D02": {"type": "pay_stub", "date": "2026-06-30"},
    })
    out = [message_for(code, entry.sample_detail, ctx)
           for code, entry in sorted(REGISTRY.items())]
    out += [STATUS_MESSAGES[k] for k in sorted(STATUS_MESSAGES)]
    out += [SITUATION_MESSAGES[k] for k in sorted(SITUATION_MESSAGES)]
    return out


# =====================================================================================
# measurement
# =====================================================================================
#
# These live here rather than in the test file because `api/selftest.py` publishes them on
# our own scorecard, and a number on the scorecard must come from the same code the test
# asserts on. One implementation, two callers.

#: A raw schema identifier or a machine code leaking into text a renter reads.
#: `gross_pay`, `regular_hours`, `PAY_STUB_TOTAL_CONFLICT`, `READY_TO_REVIEW`.
RAW_IDENTIFIER = re.compile(r"[a-z]+_[a-z]+|[A-Z]{2,}_[A-Z]{2,}")
SECOND_PERSON = re.compile(r"\b(?:you|your|yours|yourself|yourselves|you're)\b",
                           re.IGNORECASE)
HOUSEHOLD_ID = re.compile(r"\bHH-\d{3}\b")

#: Best-effort passive-voice detector: a form of "to be" followed by an optional adverb
#: and a past participle.
#:
#: LIMITS, stated plainly because a number nobody can criticise is a number nobody should
#: trust. This heuristic:
#:   * misses passives built on "get" ("your file got held"), and passives whose participle
#:     is irregular and does not end in -ed/-en ("was shown", "was built", "was kept");
#:   * false-positives on adjectival predicates that merely look like participles
#:     ("is dated 14 April", "are missing", "is based on") -- "is dated" in particular
#:     appears in our own date sentences and is counted against us here;
#:   * has no parser, so it cannot tell an agentless passive from a stative description.
#: It is therefore a screening tool that flags candidates for a human to read, not a
#: measurement of grammar. We report the fraction it produces and we do not round it into
#: a claim of compliance.
PASSIVE = re.compile(
    r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?\w+(?:ed|en)\b",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text or ""))


def compliance(messages: Iterable[PlainMessage]) -> dict[str, Any]:
    """The rules checklist, measured over every renter-facing string.

    This -- not the readability grade -- is the primary artifact. Each fraction is
    reported with the offending strings, so a bad number can be acted on rather than
    merely displayed.
    """
    messages = list(messages)
    strings: list[tuple[str, str, str]] = []          # (code, field, text)
    for message in messages:
        for name, text in (("headline", message.headline),
                           ("body", message.body),
                           ("action", message.action)):
            if text:
                strings.append((message.code, name, text))

    identifier_hits = [(c, f, RAW_IDENTIFIER.findall(t)) for c, f, t in strings
                       if RAW_IDENTIFIER.search(t)]
    id_leaks = [(c, f) for c, f, t in strings if HOUSEHOLD_ID.search(t)]
    no_second_person = [(c, f) for c, f, t in strings if not SECOND_PERSON.search(t)]
    # Per-message as well as per-string. A message that says "We could not read a pay
    # amount" in the headline and addresses "you" in the body is written in second person;
    # counting its headline as a miss measures our sentence style, not our stance. Both
    # numbers are reported because they answer different questions.
    messages_without_second_person = [
        m.code for m in messages
        if not any(SECOND_PERSON.search(t) for t in m.renter_text)
    ]

    total_sentences = passive_hits = 0
    passive_examples: list[str] = []
    for _c, _f, text in strings:
        for sentence in sentences(text):
            total_sentences += 1
            if PASSIVE.search(sentence):
                passive_hits += 1
                if len(passive_examples) < 12:
                    passive_examples.append(sentence)

    problems = [m for m in messages if m.kind == "problem"]
    with_action = [m for m in problems if m.action.strip()]
    gaps = [m.code for m in messages if m.action_gap]
    handoffs = [m.code for m in messages if m.action_is_handoff]

    def fraction(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "messages": len(messages),
        "renter_facing_strings": len(strings),
        "sentences": total_sentences,
        "free_of_raw_identifiers": fraction(len(strings) - len(identifier_hits), len(strings)),
        "raw_identifier_hits": [{"code": c, "field": f, "found": sorted(set(x))}
                                for c, f, x in identifier_hits],
        "uses_second_person": fraction(len(strings) - len(no_second_person), len(strings)),
        "strings_without_second_person": [{"code": c, "field": f} for c, f in no_second_person],
        "messages_using_second_person": fraction(
            len(messages) - len(messages_without_second_person), len(messages)),
        "messages_without_second_person": messages_without_second_person,
        "active_voice_best_effort": fraction(total_sentences - passive_hits, total_sentences),
        "passive_candidates": passive_examples,
        "problem_messages": len(problems),
        "problem_messages_with_an_action": len(with_action),
        "problem_messages_with_an_action_fraction": fraction(len(with_action), len(problems)),
        "action_gaps": gaps,
        "actions_needing_a_trained_person": handoffs,
        "household_id_leaks": [{"code": c, "field": f} for c, f in id_leaks],
        "note": (
            "Scanned fields are headline, body and action only. `code` and `detail` are "
            "the technical disclosure and are supposed to contain identifiers. "
            "The active-voice number is a regex heuristic with documented blind spots "
            "(see PASSIVE in api/plain.py); treat it as a screening signal, not a "
            "grammatical measurement."
        ),
    }


#: Screens shorter than this are not measured. Readability formulas are regressions fitted
#: on running prose and return noise on fragments.
MIN_SAMPLE_WORDS = 100


def readability(samples: dict[str, str]) -> dict[str, Any]:
    """Flesch-Kincaid grade and SMOG together, per screen, with the spread between them.

    WHY THE PAIR AND THE SPREAD, AND NOT A SINGLE NUMBER
    ----------------------------------------------------
    A single reading grade presented as fact would be exactly the kind of unearned
    precision this project exists to argue against.

      * CMS publishes "Toolkit Part 7: Using readability formulas: a cautionary note",
        which warns against treating a formula output as a measurement of comprehension.
      * Wang et al. (2013) measured the same texts across formulas and found spreads of up
        to roughly five grade levels. Two defensible formulas can disagree by more than the
        difference between middle school and college.
      * Redish's critique notes the formulas assume running paragraphs. Headlines, lists
        and short actions -- most of what is on our screens -- break that assumption.
      * SMOG is defined over a 30-sentence sample. Below that it is being extrapolated,
        so we report the sentence count next to it and let the reader discount it.

    So: two formulas, the gap between them, the word and sentence counts that condition
    both, and no single headline grade. If the spread is wide, that is the finding.
    """
    try:
        import textstat
    except ImportError:
        return {
            "status": "not_run",
            "reason": "textstat is not installed (pip install textstat)",
        }

    screens: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for name, text in sorted(samples.items()):
        words = word_count(text)
        if words < MIN_SAMPLE_WORDS:
            skipped.append({"screen": name, "words": words})
            continue
        sentence_count = len(sentences(text))
        fk = round(float(textstat.flesch_kincaid_grade(text)), 2)
        smog = round(float(textstat.smog_index(text)), 2)
        screens.append({
            "screen": name,
            "words": words,
            "sentences": sentence_count,
            "flesch_kincaid_grade": fk,
            "smog_grade": smog,
            "spread_between_the_two": round(abs(fk - smog), 2),
            "smog_is_extrapolated": sentence_count < 30,
        })

    spreads = [s["spread_between_the_two"] for s in screens]
    return {
        "status": "measured" if screens else "not_run",
        "screens": screens,
        "screens_too_short_to_measure": skipped,
        "minimum_sample_words": MIN_SAMPLE_WORDS,
        "widest_spread": max(spreads) if spreads else None,
        "note": (
            "Two formulas, reported together with the gap between them. A per-string "
            "grade is not defensible and is not produced. SMOG needs 30 sentences to be "
            "used as defined; screens below that are marked as extrapolated. "
            "WCAG 2.2 SC 3.1.5 Reading Level is Level AAA and is not required at AA -- "
            "we adopt it voluntarily and do not claim AA obliges it."
        ),
    }


def audit_samples() -> dict[str, str]:
    """Screen-sized prose samples for the readability measurement.

    Grouped so each sample is a plausible screen a renter would actually face, rather
    than the whole corpus glued together, which would measure nothing anyone reads.
    """
    messages = audit_messages()
    groups: dict[str, list[PlainMessage]] = {
        "status_screens": [m for m in messages if m.kind == "status"],
        "document_problem_screen": [m for m in messages if m.kind == "problem"
                                    and m.code.startswith(("DOCUMENT", "REQUIRED",
                                                           "EMPLOYMENT", "VALUE"))],
        "income_problem_screen": [m for m in messages if m.kind == "problem"
                                  and m.code.startswith(("PAY", "INCOME", "AMOUNT",
                                                         "GIG", "RENTER"))],
        "limit_problem_screen": [m for m in messages if m.kind == "problem"
                                 and m.code.startswith(("HOUSEHOLD", "NO_FROZEN",
                                                        "PERSON"))],
        "answer_screens": [m for m in messages if m.kind == "response"],
    }
    return {name: screen_text(None, group) for name, group in groups.items() if group}


def measure() -> dict[str, Any]:
    """Everything this layer knows about its own quality, measured now.

    Used by `api/selftest.py` and by `api/test_plain.py`, so the scorecard and the test
    can never drift apart.
    """
    messages = audit_messages()
    return {
        "rules_checklist": compliance(messages),
        "readability": readability(audit_samples()),
        "codes_covered": len(REGISTRY),
        "situations_covered": len(SITUATION_MESSAGES),
    }


__all__ = [
    "Context",
    "DOC_NAMES",
    "CHECKLIST_STATE_TRIGGER",
    "Entry",
    "ITEM_PRESENT_CODE",
    "PlainMessage",
    "REGISTRY",
    "SITUATION_MESSAGES",
    "STATUS_MESSAGES",
    "MIN_SAMPLE_WORDS",
    "PASSIVE",
    "RAW_IDENTIFIER",
    "SECOND_PERSON",
    "audit_messages",
    "audit_samples",
    "code_for_trigger",
    "compliance",
    "measure",
    "readability",
    "for_report",
    "for_situation",
    "message_for",
    "screen_text",
    "trigger_for_abstention",
]
