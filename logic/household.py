"""Adapter: a list of ``DocumentView`` dicts becomes queryable household facts.

This layer never opens a PDF. It consumes whatever ``core/extract.py`` (or, for
measurement, the pack's own gold file) produced, so the reasoning layer can be scored
independently of extraction quality.

Every fact carries the document it came from and whether it is traceable to a
page-level source box, because CH-READINESS-001 makes traceability a readiness
condition and CH-INCOME-001 makes provenance a condition on income inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from logic.constants import CURRENCY_FLOOR, REFERENCE_DATE


@dataclass(frozen=True)
class FieldRef:
    """One extracted field, with the provenance CH-READINESS-001 requires."""

    document_id: str
    document_type: str
    name: str
    value: Any
    page: int | None = None
    bbox: tuple[float, ...] | None = None
    certainty: str = "high"

    @property
    def traceable(self) -> bool:
        """True when this value can be pointed at on a page (page + source box)."""
        return (
            self.certainty != "abstain"
            and self.value is not None
            and self.page is not None
            and self.bbox is not None
            and len(self.bbox) == 4
        )

    def as_input(self, label: str) -> dict[str, Any]:
        """Shape for ``Calculation.inputs`` (CONTRACTS.md section 5)."""
        return {"label": label, "value": self.value, "from_document": self.document_id}


@dataclass(frozen=True)
class Document:
    document_id: str
    household_id: str
    document_type: str
    file_name: str | None
    fields: dict[str, FieldRef]

    def get(self, name: str) -> FieldRef | None:
        ref = self.fields.get(name)
        if ref is None or ref.certainty == "abstain" or ref.value is None:
            return None
        return ref

    def value(self, name: str, default: Any = None) -> Any:
        ref = self.get(name)
        return default if ref is None else ref.value

    @property
    def readable(self) -> bool:
        """False when nothing on this document could be read (e.g. a scan, no OCR yet)."""
        return any(f.certainty != "abstain" and f.value is not None for f in self.fields.values())

    @property
    def untraceable_fields(self) -> list[str]:
        return sorted(
            name
            for name, ref in self.fields.items()
            if ref.certainty != "abstain" and ref.value is not None and not ref.traceable
        )


#: Which field carries the document's own date, per document type.
DATE_FIELD_BY_TYPE = {
    "application_summary": "application_date",
    "pay_stub": "pay_date",
    "employment_letter": "document_date",
    "benefit_letter": "document_date",
    "gig_statement": "statement_month",
}


@dataclass(frozen=True)
class DocumentDate:
    """The result of trying to date a document under the 60-day convention."""

    raw: str | None
    parsed: date | None
    precision: str  # "day" | "month" | "none"

    @property
    def datable(self) -> bool:
        return self.precision == "day" and self.parsed is not None

    @property
    def current(self) -> bool | None:
        """True/False under CH-READINESS-001, or None when the question cannot be asked."""
        if not self.datable:
            return None
        return self.parsed >= CURRENCY_FLOOR

    @property
    def days_until_stale(self) -> int | None:
        if not self.datable:
            return None
        return (self.parsed - CURRENCY_FLOOR).days


def read_document_date(doc: Document) -> DocumentDate:
    """Never invents a day. Month precision stays month precision."""
    name = DATE_FIELD_BY_TYPE.get(doc.document_type)
    raw = doc.value(name) if name else None
    if raw is None:
        return DocumentDate(None, None, "none")
    text = str(raw)
    try:
        return DocumentDate(text, datetime.strptime(text, "%Y-%m-%d").date(), "day")
    except ValueError:
        pass
    try:
        datetime.strptime(text, "%Y-%m")
    except ValueError:
        return DocumentDate(text, None, "none")
    return DocumentDate(text, None, "month")


@dataclass
class Household:
    household_id: str
    documents: list[Document] = dc_field(default_factory=list)

    def of_type(self, document_type: str) -> list[Document]:
        return [d for d in self.documents if d.document_type == document_type]

    @property
    def present_types(self) -> set[str]:
        return {d.document_type for d in self.documents}

    @property
    def size(self) -> int | None:
        """Household size, only from an application summary that actually states it."""
        for doc in self.of_type("application_summary"):
            ref = doc.get("household_size")
            if ref is not None:
                try:
                    return int(ref.value)
                except (TypeError, ValueError):
                    return None
        return None

    def size_ref(self) -> FieldRef | None:
        for doc in self.of_type("application_summary"):
            ref = doc.get("household_size")
            if ref is not None:
                return ref
        return None


# =====================================================================================
# loading
# =====================================================================================


def document_from_view(view: dict[str, Any]) -> Document:
    """Accept a DocumentView (CONTRACTS section 3) or a pack gold record; same shape."""
    fields: dict[str, FieldRef] = {}
    for item in view.get("fields", []):
        name = item.get("field")
        if name is None:
            continue
        bbox = item.get("bbox")
        fields[name] = FieldRef(
            document_id=view["document_id"],
            document_type=view.get("document_type", ""),
            name=name,
            value=item.get("value"),
            page=item.get("page"),
            bbox=tuple(bbox) if isinstance(bbox, (list, tuple)) else None,
            # A prediction with no certainty key is an ANSWER, not an abstention -- the
            # same reading eval/CONTRACT_CONFLICTS.md section 2 settled on.
            certainty=item.get("certainty", "high"),
        )
    return Document(
        document_id=view["document_id"],
        household_id=view.get("household_id", str(view["document_id"]).rsplit("-", 1)[0]),
        document_type=view.get("document_type", ""),
        file_name=view.get("file_name"),
        fields=fields,
    )


def households_from_views(views: Iterable[dict[str, Any]]) -> dict[str, Household]:
    out: dict[str, Household] = {}
    for view in views:
        doc = document_from_view(view)
        out.setdefault(doc.household_id, Household(doc.household_id)).documents.append(doc)
    for house in out.values():
        house.documents.sort(key=lambda d: d.document_id)
    return dict(sorted(out.items()))


def load_gold_households(gold_path: str | Path | None = None) -> dict[str, Household]:
    """Load the pack's gold documents as the input to this layer.

    Using gold here is deliberate: it measures the REASONING layer without folding in
    extraction error. Extraction is measured separately by core/ and eval/.
    """
    path = Path(gold_path) if gold_path else default_gold_path()
    views = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return households_from_views(views)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_gold_path() -> Path:
    return repo_root() / "pack" / "synthetic_documents" / "gold" / "document_gold.jsonl"


def load_pack_checklists(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    p = Path(path) if path else repo_root() / "pack" / "evaluation" / "application_checklists.json"
    rows = json.loads(p.read_text(encoding="utf-8"))
    return {row["household_id"]: row for row in rows}


def load_rule_corpus(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    p = Path(path) if path else repo_root() / "pack" / "rules" / "rule_corpus.jsonl"
    rules: dict[str, dict[str, Any]] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rules[row["rule_id"]] = row
    return rules


def required_document_types(household_id: str, checklists: dict[str, dict[str, Any]] | None = None) -> Sequence[str]:
    checklists = checklists if checklists is not None else load_pack_checklists()
    row = checklists.get(household_id)
    return tuple(row["required_document_types"]) if row else ()


__all__ = [
    "REFERENCE_DATE",
    "Document",
    "DocumentDate",
    "FieldRef",
    "Household",
    "document_from_view",
    "households_from_views",
    "load_gold_households",
    "load_pack_checklists",
    "load_rule_corpus",
    "read_document_date",
    "required_document_types",
]
