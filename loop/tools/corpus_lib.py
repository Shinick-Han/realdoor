# -*- coding: utf-8 -*-
"""corpus_lib.py -- the loop's read-only view of the 77-document corpus and its truth.

Shared by `build_corpus_manifest.py`, `build_field_state.py` and `gate.py` so that the
day-0 census and the per-iteration gate cannot drift apart: G3 and G7 compare a freshly
computed field state against `baseline.field_state`, and if the two were computed by two
different pieces of code the comparison would be measuring the code, not the extractor.

THE ONE RULE THIS FILE EXISTS TO ENFORCE
----------------------------------------
**Correctness is never decided here.** Every `correct` verdict in this module comes from
a function imported out of the repository's own measuring harnesses:

    pack                 eval/score_extraction.score()          (via api.store.extract_all)
    uploads, holdout     score_extraction.normalize()           (the comparison
                                                                 scripts/measure_label_mapping.py
                                                                 itself performs, line for line)
    external             score_extraction.normalize()           (ditto, measure_external_holdout.py)
    confirm              measure_confirm_set._matches()         (imported outright)

and every corpus is reconciled against its own harness's totals by
`build_field_state.py` before anything is written. A hand-written `str == str` probe has
already produced two false failure reports in this project; the reconciliation assert is
the structural answer to that, not a comment asking the next person to be careful.

The protected trees (`eval/score_extraction.py`, `scripts/measure_*.py`,
`scripts/verify.py`, every `*_truth.json`, `pack/synthetic_documents/gold/*`) are
imported and read here, never written. Gate G6 enforces that from the outside.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent.parent
LOOP = ROOT / "loop"

for _p in (str(ROOT), str(ROOT / "eval"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

MANIFEST_PATH = LOOP / "tools" / "corpus_manifest.json"
BASELINE_PATH = LOOP / "baseline.json"
BACKLOG_PATH = LOOP / "backlog.json"

#: The five corpora and the 77 that must add up. Stated as data so that
#: `build_corpus_manifest.py` can fail loudly on the total rather than on a hunch.
EXPECTED_COUNTS = {"pack": 24, "uploads": 26, "holdout": 7, "external": 6, "confirm": 14}
EXPECTED_TOTAL = 77

#: The trees gate G6 forbids any iteration to touch. Listed here because
#: `build_corpus_manifest.py` records which of them each corpus's truth lives in, so a
#: reader can see at a glance that every corpus's truth is protected.
PROTECTED = (
    "eval/score_extraction.py",
    "scripts/verify.py",
    "scripts/measure_",
    "_truth.json",
    "pack/synthetic_documents/gold/",
)

# =====================================================================================
# corpus enumeration
# =====================================================================================


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _pack_documents() -> list[dict[str, Any]]:
    gold = ROOT / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"
    docs = []
    for line in gold.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        docs.append(
            {
                "corpus": "pack",
                "doc": record["file_name"],
                "path": str((ROOT / "pack/synthetic_documents/documents" / record["file_name"]).resolve()),
                "document_id": record["document_id"],
                "document_type": record["document_type"],
                "rasterized": bool(record.get("rasterized")),
                "truth_source": _rel(gold),
                "truth_locator": f"jsonl record document_id={record['document_id']}, key 'fields'",
                "truth_shape": "fields[] with value+page+bbox",
                "expected_field_count": len(record["fields"]),
                "expect_absent_count": 0,
            }
        )
    return docs


def _manifest_documents(corpus: str, manifest_rel: str, dir_rel: str) -> list[dict[str, Any]]:
    manifest = ROOT / manifest_rel
    data = json.loads(manifest.read_text(encoding="utf-8"))
    docs = []
    for record in data["documents"]:
        docs.append(
            {
                "corpus": corpus,
                "doc": record["file_name"],
                "path": str((ROOT / dir_rel / record["file_name"]).resolve()),
                "document_id": record["file_name"],
                "document_type": record["document_type"],
                "rasterized": bool(record.get("rasterized")),
                "truth_source": _rel(manifest),
                "truth_locator": f"documents[] entry file_name={record['file_name']}, key 'intended_fields'",
                "truth_shape": "intended_fields{} (no expect_absent)",
                "expected_field_count": len(record.get("intended_fields", {})),
                "expect_absent_count": 0,
            }
        )
    return docs


def _truth_documents(corpus: str, truth_rel: str, dir_rel: str, typed: bool) -> list[dict[str, Any]]:
    truth = ROOT / truth_rel
    data = json.loads(truth.read_text(encoding="utf-8"))
    docs = []
    for record in data["documents"]:
        docs.append(
            {
                "corpus": corpus,
                "doc": record["file_name"],
                "path": str((ROOT / dir_rel / record["file_name"]).resolve()),
                "document_id": record["file_name"],
                # confirm_truth.json carries no document_type: the manifest was written
                # without repository access. measure_confirm_set.py asserts pay_stub for
                # all 14, in the open, and this manifest records that it is an assertion.
                "document_type": record.get("document_type") or "pay_stub",
                "document_type_asserted_by_harness": not typed,
                "rasterized": not record.get("text_layer", True),
                "truth_source": _rel(truth),
                "truth_locator": f"documents[] entry file_name={record['file_name']}, keys 'expected' / 'expect_absent'",
                "truth_shape": "expected{} + expect_absent[]",
                "expected_field_count": len(record.get("expected", {})),
                "expect_absent_count": len(record.get("expect_absent", [])),
            }
        )
    return docs


def enumerate_corpus() -> list[dict[str, Any]]:
    """All 77 documents, in corpus order. Raises if any file is missing."""
    docs = (
        _pack_documents()
        + _manifest_documents("uploads", "testdata/uploads_manifest.json", "testdata/uploads")
        + _manifest_documents("holdout", "testdata/holdout_manifest.json", "testdata/holdout")
        + _truth_documents("external", "testdata/external_truth.json", "testdata/external_raw", True)
        + _truth_documents("confirm", "testdata/confirm_truth.json", "testdata/confirm_raw", False)
    )
    missing = [d["path"] for d in docs if not Path(d["path"]).exists()]
    if missing:
        raise SystemExit(f"corpus enumeration: {len(missing)} PDFs do not exist: {missing}")
    return docs


def load_manifest() -> list[dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"no corpus manifest at {MANIFEST_PATH}; run build_corpus_manifest.py")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["documents"]


# =====================================================================================
# text-layer presence -- the `image_only` test
# =====================================================================================
# "The truth value does not appear anywhere in the document's text layer."
#
# Read with raw pdfplumber, deliberately NOT through `core.extract.read_words`: the whole
# point of backlog item T1 is that `read_words` returns nothing for a page pdfplumber
# reads fine. Classifying that page's fields as `image_only` because the extractor's own
# broken reader cannot see them would bake the bug into the baseline as a law of nature.

_WS = re.compile(r"\s+")
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def page_text(pdf_path: str | Path) -> str:
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text))
    for bad, good in {"‘": "'", "’": "'", "“": '"', "”": '"',
                      "–": "-", "—": "-", "−": "-"}.items():
        text = text.replace(bad, good)
    return _WS.sub(" ", text).strip().casefold()


def _number_renderings(value: Any) -> Iterable[str]:
    try:
        dec = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except (InvalidOperation, ValueError):
        return []
    out = set()
    for form in (dec, dec.quantize(Decimal("0.01")), dec.normalize()):
        plain = format(form, "f")
        out.add(plain)
        out.add(f"${plain}")
        if abs(dec) >= 1000:
            whole, _, frac = plain.partition(".")
            grouped = f"{int(whole):,}" + (f".{frac}" if frac else "")
            out.add(grouped)
            out.add(f"${grouped}")
    return out


def _date_renderings(value: Any) -> Iterable[str]:
    from score_extraction import UNPARSABLE, normalize  # type: ignore

    norm = normalize("pay_date", value)
    if len(norm) > 2 and norm[1] == UNPARSABLE:
        return [str(value)]
    iso = norm[1]
    parts = iso.split("-")
    if len(parts) != 3:
        return [str(value), iso]
    y, m, d = (int(p) for p in parts)
    month = _MONTH_NAMES[m - 1]
    return [
        str(value), iso,
        f"{m}/{d}/{y}", f"{m:02d}/{d:02d}/{y}", f"{m}/{d}/{y % 100:02d}", f"{m:02d}/{d:02d}/{y % 100:02d}",
        f"{m}-{d}-{y}", f"{m:02d}-{d:02d}-{y}",
        f"{month} {d}, {y}", f"{month} {d} {y}", f"{month[:3]} {d}, {y}", f"{month[:3]} {d} {y}",
        f"{d} {month} {y}",
    ]


def _string_renderings(field: str, value: Any) -> Iterable[str]:
    text = str(value)
    out = {text}
    # Names print either way round, and the truth transcriber wrote down whichever the
    # page showed. "Johnson, Bob" and "Bob Johnson" are the same printed fact.
    if field == "person_name" and "," in text:
        last, _, first = text.partition(",")
        out.add(f"{first.strip()} {last.strip()}")
    if field == "person_name" and "," not in text and " " in text:
        first, _, last = text.rpartition(" ")
        out.add(f"{last}, {first}")
    return out


def _spliced_match(needle: str, haystack: str) -> bool:
    """`needle` in `haystack`, tolerating a watermark's glyphs spliced into the middle.

    Measured, not hypothetical: `up_024_pay_stub_table.pdf` prints pay_date `2026-07-07`,
    and pdfplumber hands the page back as `Jane Roe 20C26-07-07 64 17.50 1120.00` -- the
    `C` belongs to a vertical NOT-A-REAL-DOCUMENT watermark whose glyph column crosses the
    date's x-range on the same baseline. `up_013` splices a `T` into `8812 Marrow Bell
    Lane`. Both values are printed in full; a plain substring test calls them absent and
    would have classified two live abstentions as `image_only`, i.e. closed two targets by
    accident.

    The budget is one spliced character per six of the needle's own, at least one. It is
    deliberately small: this test decides whether a field is closed as unreachable, and a
    generous matcher closes fields that are actually reachable.
    """
    budget = max(1, len(needle) // 6)
    pattern = ".{0,1}".join(re.escape(c) for c in needle)
    for match in re.finditer(pattern, haystack):
        if len(match.group(0)) - len(needle) <= budget:
            return True
    return False


def appears_in_text(field: str, value: Any, text: str) -> bool:
    """Does this truth value appear, in any ordinary rendering, in the page's text layer?

    Refusal-biased in the direction that matters: a value we cannot render is reported as
    present, so a rendering gap shows up as an `abstain` (a live backlog candidate a human
    will look at) rather than as `image_only` (a closed classification nobody revisits).
    """
    from score_extraction import field_kind  # type: ignore

    kind = field_kind(field, value)
    if kind == "number":
        candidates = list(_number_renderings(value)) or [str(value)]
    elif kind == "date":
        candidates = list(_date_renderings(value))
    else:
        candidates = list(_string_renderings(field, value))

    folded = _fold(text)
    squeezed = folded.replace(" ", "")
    for candidate in candidates:
        needle = _fold(candidate)
        if not needle:
            continue
        if needle in folded or needle.replace(" ", "") in squeezed:
            return True
        if _spliced_match(needle.replace(" ", ""), squeezed):
            return True
    return False


# =====================================================================================
# classification
# =====================================================================================
# Precedence, and why it is this order:
#
#   correct           what the harness says. Nothing overrides a measured correct -- a
#                     masked date the confirm harness scores correct through its
#                     year-wildcard IS correct, and calling it `masked` would understate
#                     the extractor.
#   masked            truth carries a redacted year (`1/7/XX`). Closed by design 8.2:
#                     no century and no decade digit is printed anywhere.
#   blocked_contract  the frozen scorer cannot represent a correct answer: truth
#                     normalizes to UNPARSABLE. This is the il_dol `8/27/05` case of
#                     design 0.1 correction 2 -- an extractor emitting the right
#                     `2005-08-27` would be scored WRONG. Checked after `masked` because
#                     a masked date is also UNPARSABLE, but the confirm harness's
#                     wildcard gives it a scoreable path that `8/27/05` does not have.
#   image_only        the value is not in the text layer at all.
#   abstain           everything else: reachable, and not reached. The live backlog.


def classify(field: str, truth_value: Any, is_correct: bool, text: str) -> str:
    from measure_confirm_set import _masked_date  # type: ignore
    from score_extraction import UNPARSABLE, normalize  # type: ignore

    if is_correct:
        return "correct"
    if isinstance(truth_value, str) and _masked_date(truth_value) is not None:
        return "masked"
    norm = normalize(field, truth_value)
    if len(norm) > 2 and norm[1] == UNPARSABLE:
        return "blocked_contract"
    if not appears_in_text(field, truth_value, text):
        return "image_only"
    return "abstain"


def key(corpus: str, doc: str, field: str) -> str:
    return f"{corpus}::{doc}::{field}"
