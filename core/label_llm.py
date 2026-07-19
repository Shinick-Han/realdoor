# -*- coding: utf-8 -*-
"""
label_llm.py -- the last inch of label vocabulary, and nothing else.

`core.extract` maps a label string to a field name with two hand-written tables:
`LABEL_MAP` (the pack's own words) and `LABEL_SYNONYMS` (a wider set of the same kind).
Both are exact membership tests. A string in neither is a total miss, and the page comes
back blank even though a human reads it instantly.

Those tables are closed sets we invented. Real documents are written by ADP, Paychex,
Gusto, the SSA and ten thousand employers with a word processor, and they do not consult
us. `scripts/make_holdout.py` measures exactly how far our tables reach. This module is
for what is left over.

What is deliberately withheld from the model -- this list is the module, the rest is
plumbing:

  1. **It picks a field name from a closed set. It cannot invent one.** The set is
     collected at runtime from `core.extract.EXPECTED_FIELDS`, which is itself derived
     from `LABEL_MAP`. There is no hard-coded copy here, so the list shown to the model
     and the list we validate against cannot drift apart. A name outside the set is
     discarded and we abstain -- exactly as `api.route_llm` discards an unknown intent.

  2. **Label strings go out. Values never do.** The prompt carries one caption -- "GROSS
     WAGES", "Period Ending" -- and nothing else. No amount, no name, no date, no page
     text, no household record, no coordinates. `pack/governance/DATA_USE_AND_SAFETY.md`
     makes sending pack data to a hosted model conditional; sending a caption does not
     approach that condition. `assert_no_values()` is the enforcement, and
     `core/test_label_llm.py` runs it over every document we own.

  3. **It names a field. It never reads a value.** A field named here goes through the
     unchanged geometry: the value must sit in the column under the label, inside
     `VALUE_Y_WINDOW`, aligned to `VALUE_X_TOLERANCE`, and it must still parse as the
     type that field requires. That parse is this module's analogue of the anchor
     round-trip in `api.route_llm.confirm()` -- the model can only point at a value the
     deterministic code was already willing to read, and a wrong guess produces an
     abstention rather than a wrong figure, because "SUPERVISOR" mapped to `gross_pay`
     yields text that is not money and is thrown away.

  4. **It runs last and it may only fill blanks.** `LABEL_MAP`, then `LABEL_SYNONYMS`,
     then this. `extract_fields_from_page` carries `found` across passes, so a label a
     table recognised can never be re-decided by the model. This ordering is what keeps
     the deterministic numbers reproducible: a judge with no key runs the first two
     passes and gets our exact figures.

  5. **When unsure it abstains.** `unknown` is offered as an explicit choice and the
     instruction tells the model to prefer it. "Probably this one" is the failure mode
     that turns an honest blank into a confident wrong answer.

Off by default in three ways: no `OPENAI_API_KEY`, `REALDOOR_LABEL_LLM=0`, or running
under pytest without `REALDOOR_LABEL_LLM=1`. Any of them and `model_mapper` returns
`None` for everything, which is the same thing the tables already do for an unknown
string -- so the extractor's behaviour with this module switched off is bit-identical to
its behaviour before the module existed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from pathlib import Path
from typing import Any

MODEL = os.environ.get("REALDOOR_LABEL_MODEL", "gpt-4o-mini")
TIMEOUT_SECONDS = float(os.environ.get("REALDOOR_LABEL_TIMEOUT", "6"))
UNKNOWN = "unknown"

#: A label is a caption. Anything longer is a sentence, and a sentence is document
#: content rather than a field name -- we refuse to send it. Real captions are short;
#: the longest in either table is well under this.
MAX_LABEL_CHARS = 48


def _providers_dir() -> Path:
    override = os.environ.get("HN_PROVIDERS_DIR")
    if override:
        return Path(override)
    vendored = Path(__file__).resolve().parent.parent / "tools"
    if (vendored / "providers.py").is_file():
        return vendored
    return Path.home() / "source" / "hacknation-cmd" / "tools"


_PROVIDERS_DIR = _providers_dir()


# ───────────────────────────────────────────────── the closed set (collected)

def known_fields(document_type: str) -> tuple[str, ...]:
    """Every field name this document type may legally produce. **Read from the code.**

    `core.extract.EXPECTED_FIELDS` is derived from `LABEL_MAP`, which is the same table
    the gold file was measured against. If a field is added or removed there, this set
    follows, so what we show the model and what we accept back cannot diverge.
    """
    from core.extract import EXPECTED_FIELDS

    return tuple(EXPECTED_FIELDS.get(document_type, ()))


#: field name -> one line telling the model what the field is *about*.
#:
#: **Not the source of the set.** The source is `known_fields()`. This only adds a gloss;
#: a field with no entry here is still offered, by name alone. `gloss_audit()` checks the
#: two have not drifted and a test enforces it.
#:
#: The glosses are deliberately written as *distinctions* -- "for this period, not
#: year-to-date", "gross, before deductions" -- because the confusable pairs are where a
#: mapper produces a wrong answer instead of a blank. Every one of these pairs is a real
#: mistake seen on a real stub.
GLOSSES: dict[str, str] = {
    "person_name": "the person the document is about (employee, applicant, claimant) -- "
                   "NOT the employer, supervisor, or preparer",
    "household_size": "how many people are in the household, as a count",
    "address": "the person's street address",
    "application_date": "the date the application was filed",
    "pay_date": "the date this paycheck was issued or deposited -- NOT the period it covers",
    "pay_period_start": "the first day of the period this cheque covers",
    "pay_period_end": "the last day of the period this cheque covers",
    "pay_frequency": "how often the person is paid (weekly, biweekly, monthly)",
    "regular_hours": "hours worked in THIS period at the regular rate -- NOT overtime "
                     "hours, NOT year-to-date hours, NOT a total that includes overtime",
    "hourly_rate": "the rate of pay per hour -- NOT a tax rate and NOT a total",
    "gross_pay": "total earnings for THIS period BEFORE deductions -- NOT net, NOT "
                 "year-to-date, NOT a single earnings line such as regular or overtime",
    "net_pay": "what the person actually receives for THIS period AFTER deductions -- "
               "NOT year-to-date",
    "document_date": "the date the letter itself was written or signed",
    "weekly_hours": "hours worked per week",
    "monthly_benefit": "the benefit amount paid per month",
    "benefit_frequency": "how often the benefit is paid",
    "statement_month": "the month this statement covers",
    "gross_receipts": "total money taken in before the platform's cut",
    "platform_fees": "what the platform deducted",
}

_INSTRUCTION = (
    "You are naming form fields for a document extractor. You will be given ONE label -- "
    "the caption printed next to a value on a US income document -- and a list of field "
    "names. Reply with the one field name that this label is the caption for.\n\n"
    "Rules:\n"
    "- Answer `unknown` unless you are confident. A wrong name is far worse than "
    "`unknown`, because `unknown` makes the system ask a human while a wrong name makes "
    "it report a wrong figure.\n"
    "- Answer `unknown` for a label that is a heading, a company name, a section title, "
    "an address block, a deduction line (tax, insurance, garnishment), a year-to-date "
    "figure, or anything not in the list.\n"
    "- Answer `unknown` for a bare ambiguous word whose meaning depends on where it sits "
    "on the page -- for example `NAME`, `RATE`, `TOTAL`, `AMOUNT`, `DATE` on their own.\n"
    "- Do not explain, do not write a sentence, do not repeat the label.\n\n"
    "Field names:\n"
)


def _prompt(document_type: str) -> str:
    lines = []
    for field in known_fields(document_type):
        gloss = GLOSSES.get(field)
        lines.append(f"- {field}" + (f" -- {gloss}" if gloss else ""))
    lines.append(f"- {UNKNOWN} -- none of the above, or not sure")
    return _INSTRUCTION + "\n".join(lines)


def _schema(document_type: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "field": {"type": "string", "enum": list(known_fields(document_type)) + [UNKNOWN]},
        },
        "required": ["field"],
        "additionalProperties": False,
    }


# ─────────────────────────────────────────── what may leave this process

#: Shapes that are values, not captions. A caption may contain a digit ("YTD 2026" is a
#: heading; "PERIOD 2" happens) so digits alone are not disqualifying -- but a run that
#: parses as money, a date, or a bare decimal is a value that has been mistaken for a
#: label, and it does not leave.
_VALUE_SHAPES = (
    re.compile(r"\$\s*\d"),                       # $1,440.00
    re.compile(r"^\s*-?[\d,]+\.\d+\s*$"),         # 1440.00
    re.compile(r"\d{4}-\d{2}-\d{2}"),             # 2026-07-03
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),       # 07/03/2026
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),         # SSN shape
    re.compile(r"[\w.+-]+@[\w-]+\.\w+"),          # email
)


class ValueLeak(AssertionError):
    """A string headed for the model looked like document content, not a caption."""


def assert_no_values(label: str) -> None:
    """Refuse to send anything that is not a bare caption. Raises `ValueLeak`.

    This is a shape test, not a privacy filter, and the difference matters. It reliably
    stops amounts, dates, SSN-shaped digits and email addresses. It cannot stop a caption
    that is itself sensitive, because deciding that requires reading it. What makes the
    exposure small is not this function -- it is that only ~20 short captions per document
    type are ever eligible, and every one of them is printed form furniture that the
    employer put on a template, not data about the applicant.
    """
    text = (label or "").strip()
    if not text:
        raise ValueLeak("empty label")
    if len(text) > MAX_LABEL_CHARS:
        raise ValueLeak(f"too long to be a caption ({len(text)} chars): {text[:30]!r}...")
    for shape in _VALUE_SHAPES:
        if shape.search(text):
            raise ValueLeak(f"looks like a value, not a caption: {text!r}")


# ─────────────────────────────────────────────────────────────── metering

_STATS: dict[str, Any] = {
    "enabled": None,
    "asked": 0,               # labels that reached this module (both tables missed them)
    "calls": 0,               # gateway calls actually made
    "cache_hits": 0,
    "cache_hits_measurable": True,
    "returned_unknown": 0,
    "rejected_not_in_field_set": 0,
    "rejected_value_shaped": 0,   # refused to send; looked like content
    "accepted": 0,
    "offline_or_uncached": 0,
    "timeouts": 0,
    "errors": 0,
}

#: (document_type, normalized label) -> field name or None. Within one process a label is
#: asked once. Documents repeat captions and pages are scanned more than once.
_MEMO: dict[tuple[str, str], str | None] = {}


def stats() -> dict[str, Any]:
    out = dict(_STATS)
    out["enabled"] = is_enabled()
    out["model"] = MODEL
    out["memoized_labels"] = len(_MEMO)
    return out


def reset_stats() -> None:
    for key, value in list(_STATS.items()):
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            _STATS[key] = 0
    _STATS["cache_hits_measurable"] = True
    _MEMO.clear()


# ────────────────────────────────────────────────────────────── on / off

def is_enabled() -> bool:
    """Narrow conditions. When in doubt this falls to the off side.

    Off under pytest unless asked for explicitly. The test suite must not depend on a
    network, and more importantly the suite passing is our evidence that **the
    deterministic path still stands on its own**. That evidence is worth more than the
    coverage we would gain by leaving it on.
    """
    flag = os.environ.get("REALDOOR_LABEL_LLM", "").strip()
    if flag == "0":
        return False
    if "pytest" in sys.modules and flag != "1":
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    return True


_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="realdoor-label")


def _providers():
    if str(_PROVIDERS_DIR) not in sys.path:
        sys.path.insert(0, str(_PROVIDERS_DIR))
    import providers  # type: ignore

    return providers


def _usage_tail_cached(providers, offset: int) -> bool | None:
    """Read the `cached` flag the gateway just logged rather than guessing at it."""
    try:
        log = Path(providers.USAGE_LOG)
        if not log.exists():
            return None
        with log.open("r", encoding="utf-8") as f:
            f.seek(offset)
            added = [l for l in f.read().splitlines() if l.strip()]
        for line in reversed(added):
            record = json.loads(line)
            if record.get("provider") == "openai":
                return bool(record.get("cached"))
        return None
    except Exception:
        return None


# ───────────────────────────────────────────────── the mapper itself

def model_mapper(document_type: str, label: str) -> str | None:
    """`FieldMapper`: (document_type, label) -> a known field name, or None.

    The return value is **always** an element of `known_fields(document_type)` or None.
    Every other outcome -- disabled, offline, timeout, malformed reply, a name outside
    the set, `unknown`, a label that looked like a value -- is None, and None is the
    abstention the extractor already produces for a label it cannot read.
    """
    if not is_enabled():
        return None

    from core.extract import normalize_label

    fields = known_fields(document_type)
    if not fields:
        return None

    key = (document_type, normalize_label(label))
    if key in _MEMO:
        return _MEMO[key]

    _STATS["asked"] += 1

    try:
        assert_no_values(label)
    except ValueLeak:
        _STATS["rejected_value_shaped"] += 1
        _MEMO[key] = None
        return None

    providers = _providers()
    try:
        offset = Path(providers.USAGE_LOG).stat().st_size
    except OSError:
        offset = 0

    def _call():
        return providers.complete(
            _prompt(document_type),
            label.strip(),
            model=MODEL,
            json_schema=_schema(document_type),
            max_tokens=24,
            temperature=0.0,
        )

    _STATS["calls"] += 1
    try:
        # No `with` on the pool: `__exit__` waits for the worker, which would make the
        # timeout cosmetic. Abandon the slow call and move on -- if it lands later it
        # only warms the cache.
        raw = _POOL.submit(_call).result(timeout=TIMEOUT_SECONDS)
    except _FutureTimeout:
        _STATS["timeouts"] += 1
        _MEMO[key] = None
        return None
    except Exception as exc:
        if type(exc).__name__ == "CacheMiss":
            _STATS["offline_or_uncached"] += 1
        else:
            _STATS["errors"] += 1
        _MEMO[key] = None
        return None

    hit = _usage_tail_cached(providers, offset)
    if hit is None:
        _STATS["cache_hits_measurable"] = False
    elif hit:
        _STATS["cache_hits"] += 1

    # ── Re-check the reply. Structured output is requested, not trusted. ──
    name = raw.get("field") if isinstance(raw, dict) else raw
    if not isinstance(name, str):
        _STATS["rejected_not_in_field_set"] += 1
        _MEMO[key] = None
        return None
    name = name.strip()
    if name == UNKNOWN:
        _STATS["returned_unknown"] += 1
        _MEMO[key] = None
        return None
    if name not in fields:
        _STATS["rejected_not_in_field_set"] += 1
        _MEMO[key] = None
        return None

    _STATS["accepted"] += 1
    _MEMO[key] = name
    return name


# ────────────────────────────────────────────────────────────── audit

def gloss_audit() -> dict[str, Any]:
    """Check the gloss table against the collected field set. Runs with no model.

    Two failures matter: a gloss for a field that no longer exists (dead weight that
    would mislead the model), and -- harmlessly but worth seeing -- a field with no gloss.
    """
    every = {f for doc_type in _all_types() for f in known_fields(doc_type)}
    return {
        "fields": len(every),
        "glossed": sorted(every & set(GLOSSES)),
        "fields_without_a_gloss": sorted(every - set(GLOSSES)),
        "glosses_for_unknown_fields": sorted(set(GLOSSES) - every),
        "ok": not (set(GLOSSES) - every),
    }


def _all_types() -> tuple[str, ...]:
    from core.extract import EXPECTED_FIELDS

    return tuple(EXPECTED_FIELDS)


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(gloss_audit(), ensure_ascii=False, indent=1))
    print(json.dumps(stats(), ensure_ascii=False, indent=1))
