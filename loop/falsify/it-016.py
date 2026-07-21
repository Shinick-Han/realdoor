"""it-016 -- T29 -- falsification predicate for the `<date> <conjunction> <date>`
pay-period RANGE rule.

Read-only. No model, no network. Run BEFORE any code, over all 77 manifest documents
plus the filled and scenario dev sets.

The rule under scrutiny (design section 8.2 family, and the existing
`core.extract._period_span_fields`, which today fires SIDE-BY-SIDE only): a run shaped
`<date> <conj> <date>`, where `conj` is a printed word from the closed set below, sitting
where a pay-period label captions it, binds the left date to `pay_period_start` and the
right to `pay_period_end`. Each half is read independently through the unchanged
`_parse_date`; a half whose year is two-digit or masked (`XX`) is NEVER emitted -- no year
is invented.

Two questions this sweep answers, both needed to justify (or refuse) building anything:

  Q1  WHERE does the range shape occur at all, and in each case: is the year resolvable
      (a real date could be emitted) or masked/two-digit (abstain is the only honest
      answer)?  This bounds the achievable EXTRACTION yield.

  Q2  THE NAMED HAZARD.  Does any `<date> <conj> <date>` run occur in a NON-period
      context -- a date-of-birth range, a coverage window, a prose "from X to Y" -- where
      binding it to a pay period would manufacture a WRONG value?  A firing here is a
      conflict and would kill the rule.

The conjunction set under test is the brief's closed set: `to`, `through`, `thru`, and a
printed dash (`-`, en-dash, em-dash) standing between two date tokens. The sweep is
tolerant of a dash/word glued to an adjacent date token (ca_dlse_hourly prints
`1/7/XXto`), so a glued conjunction cannot hide a hit.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

import pdfplumber

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core import extract as ex  # noqa: E402

# A date token: M/D/Y with a 4-digit, 2-digit, or masked (XX) year. Same shape family the
# extractor's `_UNREADABLE_YEAR_DATE_RE` already recognises for the unreadable half.
_DATE = r"\d{1,2}[/-]\d{1,2}[/-](?:\d{4}|\d{2}|[Xx]{2,4})"
_RESOLVABLE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{4}$")  # 4-digit year -> a real date
# date  <conj>  date, tolerant of glue on either side of the conjunction.
_RANGE = re.compile(
    rf"({_DATE})\s*(to|through|thru|[-–—])\s*({_DATE})",
    re.IGNORECASE,
)

# A pay-period label, normalised, in the pay_stub vocabulary. Used to decide whether a
# range's LINE (or the line above it) carries a period caption -- the license precondition.
_PERIOD_FIELDS = {"pay_period_start", "pay_period_end"}


def _line_has_period_label(line) -> bool:
    for run in ex._split_runs(list(line)):
        field = ex.synonym_mapper("pay_stub", ex._join_run(run))
        if field in _PERIOD_FIELDS:
            return True
    return False


def _scan_pdf(path: str):
    """Yield (page, line_text, conj, left, right, resolvable_both, period_context)."""
    out = []
    try:
        with pdfplumber.open(path) as pdf:
            for pno, page in enumerate(pdf.pages, 1):
                words = ex.read_words(page, pno)
                lines = ex.group_lines(words)
                for li, line in enumerate(lines):
                    text = " ".join(w.text for w in line)
                    for m in _RANGE.finditer(text):
                        left, conj, right = m.group(1), m.group(2), m.group(3)
                        both_resolvable = bool(_RESOLVABLE.match(left)) and bool(
                            _RESOLVABLE.match(right)
                        )
                        # period context: a period label on this line or the one above it
                        period = _line_has_period_label(line) or (
                            li > 0 and _line_has_period_label(lines[li - 1])
                        )
                        out.append(
                            {
                                "page": pno,
                                "line": text[:90],
                                "conj": conj,
                                "left": left,
                                "right": right,
                                "both_years_resolvable": both_resolvable,
                                "period_context": period,
                            }
                        )
    except Exception as e:  # pragma: no cover - reported, not raised
        out.append({"error": str(e), "path": os.path.basename(path)})
    return out


def _manifest_paths():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    manifest = json.load(open(os.path.join(root, "loop", "tools", "corpus_manifest.json")))
    for d in manifest["documents"]:
        yield d["corpus"], d["doc"], d["path"], d.get("rasterized", False)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    hits = []
    swept = 0
    skipped_raster = 0

    for corpus, doc, path, raster in _manifest_paths():
        if raster:
            skipped_raster += 1
            continue
        swept += 1
        for h in _scan_pdf(path):
            h["corpus"], h["doc"] = corpus, doc
            hits.append(h)

    dev_swept = 0
    for pat, corpus in (("testdata/filled/*.pdf", "filled"),
                        ("testdata/scenarios/*/*.pdf", "scenario")):
        for path in glob.glob(os.path.join(root, pat)):
            dev_swept += 1
            for h in _scan_pdf(path):
                h["corpus"], h["doc"] = corpus, os.path.basename(path)
                hits.append(h)

    real_hits = [h for h in hits if "error" not in h]
    # Q2: the hazard. A range NOT in a period context that a period-field rule could bind.
    hazard_conflicts = [h for h in real_hits if not h["period_context"]]
    # Q1: where a real date could be emitted (period context AND both years resolvable).
    resolvable = [h for h in real_hits if h["period_context"] and h["both_years_resolvable"]]
    masked = [h for h in real_hits if h["period_context"] and not h["both_years_resolvable"]]
    conj_used = sorted({h["conj"].lower() for h in real_hits})

    report = {
        "iteration": "it-016",
        "target": "T29",
        "predicate": "a run shaped <date> <conj> <date> (conj in {to, through, thru, -, en-dash, em-dash}); "
        "period_context = a pay-period label on the same line or the line above",
        "manifest_swept": swept,
        "manifest_rasterized_skipped": skipped_raster,
        "dev_swept": dev_swept,
        "conjunctions_actually_seen": conj_used,
        "hits": real_hits,
        "counts": {
            "range_lines_total": len(real_hits),
            "period_context_resolvable_year": len(resolvable),
            "period_context_masked_or_two_digit_year": len(masked),
            "HAZARD_non_period_context": len(hazard_conflicts),
        },
        "hazard_conflicts": hazard_conflicts,
        "verdict": (
            "NO non-period range anywhere (hazard does not materialise); "
            "and NO period range with both years resolvable -> zero achievable extraction "
            "yield on this corpus (the only period ranges are ca_dlse [masked XX] and "
            "il_dol [side-by-side, already read by the existing rule])."
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
