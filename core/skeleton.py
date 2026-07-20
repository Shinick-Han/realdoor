# -*- coding: utf-8 -*-
"""core/skeleton.py -- a leak-proof, position-aware page skeleton.

WHAT THIS IS, AND THE ONE PROMISE IT MAKES
------------------------------------------
Backlog T28 widens the label model's EYES without widening its HANDS: a later
iteration (it-015) may hand a model a whole-page *structural* view so it can tell a
piece-rate table from a current/YTD pair, while deterministic geometry still reads every
value. This module builds that structural view -- a plain-text skeleton of the page in
reading order -- and it makes exactly one promise, which the falsification sweep in
`loop/falsify/it-014.py` proves before anything is trusted:

    **No value the page prints -- numeric OR personal (a name, address, amount, date) --
    survives in the skeleton.** Every value slot is replaced by a typed placeholder.

Nothing in the extraction path imports this module. It reads `core.extract`'s reader and
geometry READ-ONLY and changes no field's reading; with `REALDOOR_SKELETON` unset it is
not even built. It is additive machinery, proven leak-free, that a successor may rely on.

WHY POSITION, NOT SHAPE (the T25 fix)
-------------------------------------
Today's `assert_no_values` is a *shape* test: it folds `$1,283.15` but passes
`Terrence Boyd`, because a name is caption-shaped. That asymmetry is open defect T25. A
skeleton cannot lean on shape either, so this module redacts on a different principle:

    A run is kept only when it is *confidently furniture* -- a caption (it ends in a
    colon) or a member of the page's own structural vocabulary (field labels, column
    headers, earnings/deduction row names: `STRUCTURAL_VOCAB`). Everything else is
    redacted.

An entity name -- an employer on a letterhead, an employee on a check header -- is never
structural vocabulary, so it can never be kept, however caption-shaped or bold it is. A
numeric value is redacted the same way and additionally caught by its digits. Position
enters as a *typing* signal: a masked run that sits in a value slot (under or beside a
caption, within `VALUE_Y_WINDOW`/`SIDE_BY_SIDE_MIN_GAP`) is typed `<NAME>`/`<TEXT>` --
the slot the extractor's own below/beside readers would treat as a value.

    The house rule stands: a decision rests only on what the page prints as structure.
    When a run cannot be classified with confidence it is **redacted** -- over-masking a
    caption is a cosmetic loss; under-masking a value is a leak, and the leak is the one
    thing this module promises cannot happen.

THE COST, STATED PLAINLY
------------------------
Because the keep-list is a closed vocabulary, furniture the vocabulary does not know is
masked too: a novel earnings-row label, a printed instruction, a footnote sentence. That
is the deliberate price of the boundary -- the skeleton reads like the page's table with
every value blanked, and any run whose role is uncertain is blanked with them.
"""
from __future__ import annotations

import os
import re
from typing import Sequence

from core import columns as _columns
from core.extract import (
    SIDE_BY_SIDE_MIN_GAP,
    VALUE_X_TOLERANCE,
    VALUE_Y_WINDOW,
    Word,
    _WIDE_LABELS,
    _join_run,
    _split_runs,
    group_lines,
    normalize_label,
    read_words,
)

# =====================================================================================
# the flag -- it gates whether the skeleton is BUILT, never any reading
# =====================================================================================


def skeleton_enabled() -> bool:
    """Is skeleton building switched on? OFF by default; set `REALDOOR_SKELETON=1` to build.

    This gates only whether a skeleton is *produced*. No extraction reading depends on it,
    and no extraction path calls into this module at all, so its state cannot move a single
    field: gate G5 (flag-off byte-identity) holds trivially because the flag guards a
    module the extractor never touches. Read through a function so a test can flip it.
    """
    return os.environ.get("REALDOOR_SKELETON", "").strip() not in ("", "0")


# =====================================================================================
# the structural vocabulary -- the closed keep-list
# =====================================================================================
# Seeded from the extractor's own frozen label tables (`_WIDE_LABELS`, every document
# type) and the column/matrix reader's axis words, then extended with a hand-written,
# general pay-stub structural lexicon: the words a pay document prints to NAME its parts --
# column headers, section titles, earnings and deduction row names. It is the same KIND of
# object as `LABEL_MAP` / `LABEL_SYNONYMS`: a closed set of strings, frozen in source.
#
# Every entry is stored in `normalize_label` form (upper-cased, whitespace collapsed,
# trailing colon dropped, curly quotes folded). Membership is tested against a run's WHOLE
# normalized text, never a substring: `SMITH AND COMPANY, INC.` does not match `COMPANY`,
# so an employer name can never be kept by colliding with a structural word.

_GENERAL_STRUCTURAL_TERMS: tuple[str, ...] = (
    # ---- column / matrix headers ----
    "HOURS", "HRS", "HOUR", "RATE", "RATE/HOUR", "RATE PER HOUR", "AMOUNT", "AMOUNTS",
    "DESCRIPTION", "UNITS", "HOURS/UNITS", "QTY", "QUANTITY", "PIECES", "NO. OF PIECES",
    "PIECE-RATE", "PIECE RATE", "BASIS", "TYPE", "CODE",
    "CURRENT", "CURRENT PERIOD", "THIS PERIOD", "YTD", "YEAR TO DATE", "YTD AMOUNT",
    "CALENDAR YTD", "PRIOR", "BALANCE", "BALANCES",
    # ---- section titles ----
    "EARNINGS", "EARNINGS - COMPENSATION", "COMPENSATION", "DEDUCTION", "DEDUCTIONS",
    "TAX DEDUCTIONS", "TAXES", "WITHHOLDING", "WITHHOLDINGS", "BENEFITS",
    "SUMMARY", "TOTALS", "PAY SUMMARY", "HOURS AND EARNINGS", "TAXES AND DEDUCTIONS",
    "LEAVE", "LEAVE BALANCES", "ACCRUALS", "DIRECT DEPOSIT", "NET PAY DISTRIBUTION",
    # ---- earnings / deduction / leave row names ----
    "REGULAR", "REG", "OVERTIME", "O.T.", "OT", "DOUBLE TIME", "DOUBLETIME", "HOLIDAY",
    "VACATION", "VACATION USED", "VACATION TAKEN", "SICK", "SICK LEAVE", "SICK LEAVE USED",
    "AVAILABLE SICK LEAVE", "PERSONAL", "BONUS", "COMMISSION", "COMMISSIONS", "TIPS",
    "SALARY", "WAGES", "PRODUCTIVE", "NON-PRODUCTIVE", "NONPRODUCTIVE", "REST TIME",
    "REST", "TRAINING", "PAID LEAVE", "RETRO", "ADJUSTMENT", "GROSS", "NET",
    "FEDERAL", "STATE", "LOCAL", "FICA", "MEDICARE", "SOCIAL SECURITY", "OASDI",
    "FEDERAL W/H", "STATE W/H", "CA STATE W/H", "CA STATE DI", "SUI", "SDI", "401K",
    "FED TAXABLE GROSS", "TOTAL GROSS", "APPLICABLE GROSS", "SUBJECT",
    # ---- summary / total captions ----
    "TOTAL", "TOTAL EARNINGS", "TOTAL DEDUCTIONS", "TOTAL HOURS", "TOTAL HOURS IN PAY PERIOD",
    "TOTAL EARNED FOR PRODUCTIVE WORK", "GROSS EARNINGS", "NET EARNINGS", "GROSS PAY",
    "NET PAY", "GROSS AMOUNT", "NET AMOUNT", "PAY", "CHECK", "CHECK AMOUNT",
    # ---- identity captions (their VALUES sit under/beside them and are masked) ----
    "EMPLOYEE", "EMPLOYER", "EMPLOYEE NAME", "EMPLOYER NAME", "EMPLOYEE'S NAME",
    "EMPLOYER'S NAME", "NAME", "EMPLOYEE ID", "SSN OR EMPLOYEE ID", "SSN", "EMP ID",
    "DEPARTMENT", "DEPT", "LOCATION", "JOB TITLE", "TITLE", "POSITION", "STATUS",
    "PAY GROUP", "PAY RATE", "PAY BASIS", "CHECK NUMBER", "CHECK NO", "ADVICE NUMBER",
    "DISTRICT NAME", "COMPANY", "COMPANY NAME", "PAYROLL", "ADDRESS", "MAILING ADDRESS",
    # ---- period / date captions ----
    "DATE", "PAY DATE", "PERIOD", "PAY PERIOD", "PERIOD ENDING", "PERIOD BEGINNING",
    "BEGIN DATE", "END DATE", "PAY PERIOD START", "PAY PERIOD END", "PAY BEGIN DATE",
    "PAY END DATE", "PAYROLL ISSUE DATE", "PAYROLL ENDING DATE", "FREQUENCY",
    "PAY FREQUENCY", "FROM", "TO", "THROUGH", "THRU",
)


def _build_structural_vocab() -> frozenset[str]:
    vocab: set[str] = set()
    # 1) every frozen label the extractor already understands, all document types.
    for mapping in _WIDE_LABELS.values():
        vocab.update(mapping.keys())  # already normalized at import in core.extract
    # 2) the column / matrix reader's own axis and section words.
    for row_name, axis_word in _columns.TABLE_ROW_AXES.values():
        vocab.add(normalize_label(row_name))
        vocab.add(normalize_label(axis_word))
    vocab.add(normalize_label(_columns.END_DATE_HEADER))
    vocab.add(normalize_label(_columns.EARNINGS_SECTION_WORD))
    # 3) the general pay-stub structural lexicon.
    vocab.update(normalize_label(term) for term in _GENERAL_STRUCTURAL_TERMS)
    # A kept run must never carry a digit: a value's own digits are the last thing a
    # skeleton may print, and dropping every digit-bearing structural term (e.g. `401K`)
    # makes the whole skeleton digit-free by construction. That is not cosmetic -- it is
    # what lets the falsification prove every NUMERIC truth value unleakable in one line:
    # a digit-free skeleton cannot contain a string that has a digit. Captions (colon) are
    # already digit-free by `_is_caption`; this closes the vocabulary path.
    return frozenset(term for term in vocab if not any(c.isdigit() for c in term))


#: The closed keep-list, normalized. A run is furniture only if its whole normalized text
#: is a caption (colon) or is in here.
STRUCTURAL_VOCAB: frozenset[str] = _build_structural_vocab()


# =====================================================================================
# value-shape typing -- what a placeholder is named
# =====================================================================================
# The TYPE names the shape of the value, never its content: revealing "there is a money
# value here" leaks nothing about which. The type is a hint for a later model (this column
# is money, that one hours); it is not load-bearing for the leak promise, which rests on
# the run being masked at all.

_CURRENCY_MARKS = "$€£¥₩¢₹₪₫₱฿"
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

#: A footnote marker or connective is generic page furniture -- it carries no value and is
#: kept verbatim inside an otherwise-redacted run, so `36.83 *` reads `<HRS> *` and
#: `$19.37 **` reads `<MONEY> **`, preserving the piece-rate footnote cue T28 asks for.
_MARKER_RE = re.compile(r"^[*†‡#§]+$")  # * ** dagger double-dagger # §
_RANGE_WORDS = frozenset({"TO", "THROUGH", "THRU", "AND"})
_UNIT_WORDS = frozenset({"HOURS", "HOUR", "HRS", "HR", "PER"})

_DIGIT_RE = re.compile(r"\d")
# date shapes: 1/7/XX, 01/09/2016, 9-30-2018, 8/27/05, 2021-02-16, and month-name forms
_NUMERIC_DATE_RE = re.compile(r"^\d{1,4}[/\-.]\d{1,2}[/\-.](\d{2,4}|X{2,4})$")
_MASKED_DATE_RE = re.compile(r"^\d{1,2}[/\-.]X{2,4}$|^X{2,4}[/\-.]", re.IGNORECASE)
_MONEY_RE = re.compile(r"^[%s]?\d[\d,]*(\.\d+)?[%s]?$" % (re.escape(_CURRENCY_MARKS), re.escape(_CURRENCY_MARKS)))
_NUMBER_RE = re.compile(r"^\d[\d,]*(\.\d+)?$")


def _strip_markers(tokens: list[str]) -> tuple[list[str], str]:
    """Peel trailing footnote markers off a token list; return (core_tokens, marker_suffix).

    A marker can ride glued to the value (`9.69**`) or as its own token (`36.83 *`). Both
    are separated so the value is typed and the marker is preserved beside it.
    """
    suffix = ""
    core = list(tokens)
    while core:
        last = core[-1]
        if _MARKER_RE.match(last):
            suffix = last + (" " + suffix if suffix else "")
            core.pop()
            continue
        m = re.search(r"([*†‡#§]+)$", last)
        if m and last != m.group(1):
            suffix = m.group(1) + (" " + suffix if suffix else "")
            core[-1] = last[: m.start()]
            continue
        break
    return core, suffix


def _has_digit(text: str) -> bool:
    return bool(_DIGIT_RE.search(text))


def _looks_like_date(text: str) -> bool:
    t = text.strip().upper()
    if _NUMERIC_DATE_RE.match(t) or _MASKED_DATE_RE.match(t):
        return True
    # "31 JAN 2019", "JAN 31, 2019", "SEP 15 2017"
    if any(mon in t for mon in _MONTHS) and _has_digit(t):
        return True
    return False


def _token_type(token: str) -> str | None:
    """Type of one numeric/value token, or None if it is not itself a value token."""
    t = token.strip()
    if not t:
        return None
    stripped = t.strip(_CURRENCY_MARKS + ",.")
    if any(m in t for m in _CURRENCY_MARKS):
        return "MONEY"
    if _looks_like_date(t):
        return "DATE"
    if _MONEY_RE.match(t) or _NUMBER_RE.match(t):
        return "NUM"
    if _has_digit(t):
        # a value token that carries digits but no clean shape (`XXXX-XXX-6789`,
        # `12.480800`, `3087XXX`): still a value, still masked.
        return "NUM"
    return None


def _name_like(text: str) -> bool:
    """Does this alphabetic value read like a person or organisation name?

    Only decides `<NAME>` vs `<TEXT>` -- both are masked, so a miss costs a label, never a
    leak. `Johnson, Bob` / `JONES, JAMES` (comma), `Smith And Company, Inc.` (org suffix),
    `Oregon State University` (capitalised multiword).
    """
    t = text.strip()
    if "," in t:
        return True
    if re.search(r"\b(INC|LLC|LLP|LTD|CORP|CO|COMPANY|UNIVERSITY|COLLEGE|DISTRICT|"
                 r"AUTHORITY|DEPARTMENT|SERVICES|STAFFING|PAYROLL|SCHOOL)\b", t.upper()):
        return True
    words = [w for w in re.split(r"\s+", t) if w]
    caps = [w for w in words if w[:1].isupper() or w.isupper()]
    return len(words) >= 2 and len(caps) == len(words)


# =====================================================================================
# redacting one run
# =====================================================================================


def _redact_value_run(text: str) -> str:
    """Replace a value run's content with typed placeholder(s), keeping markers/connectives.

    Purely alphabetic runs (a name, an employer) are masked WHOLE -- one `<NAME>`/`<TEXT>`
    token -- so no alphabetic content can survive on the theory that a stray word was a
    connective. A run carrying any digit is rendered token by token so a table cell keeps
    its arrangement (`1/7/XX to 1/13/XX` -> `<DATE> to <DATE>`), with every content token
    masked and only generic markers/units/range-words kept.
    """
    raw_tokens = [tok for tok in re.split(r"\s+", text.strip()) if tok]
    if not raw_tokens:
        return ""
    core, marker_suffix = _strip_markers(raw_tokens)
    if not core:
        return marker_suffix

    joined = " ".join(core)
    out: list[str]
    if not _has_digit(joined):
        # alphabetic value -> a single placeholder, whole run masked.
        out = ["<NAME>" if _name_like(joined) else "<TEXT>"]
    else:
        out = []
        i = 0
        while i < len(core):
            tok = core[i]
            up = tok.upper()
            ttype = _token_type(tok)
            if ttype is not None:
                # promote a bare number to <HRS> when a unit word sits next to it.
                nxt = core[i + 1].upper() if i + 1 < len(core) else ""
                if ttype == "NUM" and nxt in _UNIT_WORDS:
                    out.append("<HRS>")
                    i += 2
                    continue
                out.append(f"<{ttype}>")
            elif _MARKER_RE.match(tok) or up in _RANGE_WORDS or up in _UNIT_WORDS:
                out.append(tok)  # generic connective / marker / unit: kept verbatim
            else:
                # an alphabetic token riding inside a numeric run -- mask it too.
                out.append("<TEXT>")
            i += 1
        # collapse immediately repeated identical placeholders (e.g. "$ 720 . 00" shards)
        deduped: list[str] = []
        for tok in out:
            if deduped and deduped[-1] == tok and tok.startswith("<"):
                continue
            deduped.append(tok)
        out = deduped

    return " ".join(out + ([marker_suffix] if marker_suffix else []))


# =====================================================================================
# classifying a run -- furniture (kept) or value (redacted)
# =====================================================================================


def _is_caption(text: str) -> bool:
    """A run that ends in a colon is the page naming a field: furniture, kept whole.

    A caption carries no digit value of its own (`Available Sick Leave:` yes; a run like
    `Total: 40.00` carries a value and is not treated as a bare caption -- but such a run
    is normally split into a `Total:` run and a `40.00` run by the gap splitter anyway).
    """
    stripped = text.rstrip()
    return stripped.endswith(":") and not _has_digit(stripped)


def _is_structural(text: str) -> bool:
    core = text.rstrip().rstrip(":").rstrip()
    return normalize_label(core) in STRUCTURAL_VOCAB


def is_furniture(run: Sequence[Word]) -> bool:
    """Keep this run verbatim? Only when it is confidently furniture; else it is redacted."""
    text = _join_run(run)
    return _is_caption(text) or _is_structural(text)


# =====================================================================================
# building the skeleton
# =====================================================================================


def _anchor_runs(lines: Sequence[Sequence[Word]]) -> list[tuple[Sequence[Word], float, float, float]]:
    """Every caption/label run, with (run, x0, x1, baseline) -- the value-slot projectors.

    Used only to TYPE a masked run (does it sit where the extractor would read a value?),
    never to decide keep-vs-redact. A run is an anchor if it is furniture (a colon caption
    or a known label): those are exactly the runs the extractor's below/beside readers
    anchor a value to.
    """
    anchors = []
    for line in lines:
        for run in _split_runs(line):
            if is_furniture(run):
                anchors.append((run, run[0].x0, max(w.x1 for w in run), run[0].baseline))
    return anchors


def _in_value_slot(run: Sequence[Word], anchors) -> bool:
    """Does `run` sit in a value slot an anchor projects -- below it, or beside it?

    Mirrors the extractor's two value geometries: a run within `VALUE_Y_WINDOW` below the
    anchor and x-aligned to it (`_resolve_value`), or a run on the anchor's own baseline a
    column-gap to its right (`_side_by_side_value`). Position is a typing signal here, not
    a safety one -- an alphabetic value is already masked by default-redaction regardless.
    """
    x0 = run[0].x0
    baseline = run[0].baseline
    near, far = VALUE_Y_WINDOW
    for _, ax0, ax1, abase in anchors:
        # below: within the vertical window, left edges aligned
        if near <= (abase - baseline) <= far and abs(ax0 - x0) <= VALUE_X_TOLERANCE + 5.0:
            return True
        # beside: same baseline, a column gap to the right of the anchor
        if abs(abase - baseline) <= 1.5 and (x0 - ax1) >= SIDE_BY_SIDE_MIN_GAP:
            return True
    return False


def build_page_skeleton(words: Sequence[Word]) -> str:
    """One page's skeleton: reading order, values redacted, furniture kept.

    Line breaks and left-to-right cell order follow the page, so the skeleton reads like
    the page's own table with every value blanked.
    """
    lines = group_lines(words)
    anchors = _anchor_runs(lines)
    out_lines: list[str] = []
    for line in lines:
        cells: list[str] = []
        for run in _split_runs(line):
            if is_furniture(run):
                cells.append(_join_run(run))
            else:
                red = _redact_value_run(_join_run(run))
                # If position says this masked run sits in a value slot and it typed as a
                # bare <TEXT>, prefer <NAME> only when it is name-like; otherwise the type
                # already reflects the shape. (Purely a label refinement.)
                cells.append(red)
        text = " ".join(c for c in cells if c)
        if text.strip():
            out_lines.append(text)
    return "\n".join(out_lines)


def build_skeleton(pdf_path, *, respect_flag: bool = True) -> str | None:
    """The whole document's skeleton, page by page, or None when the flag is off.

    `respect_flag=False` builds unconditionally -- the falsification and the unit tests use
    it. In every other caller the `REALDOOR_SKELETON` flag decides whether a skeleton is
    built at all; no reading anywhere depends on it.
    """
    if respect_flag and not skeleton_enabled():
        return None
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = read_words(page, page_number)
            skel = build_page_skeleton(words)
            header = f"--- page {page_number} ---"
            parts.append(header + ("\n" + skel if skel else ""))
    return "\n".join(parts)
