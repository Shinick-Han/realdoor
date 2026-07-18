"""Fixtures for logic/ tests.

``make_document`` builds a ``DocumentView`` by hand so a test can construct a household
the pack does not contain -- a size-9 family, a stub with no stated frequency, a scan
with no text layer. Those cases are where the abstention policy lives, and the pack has
no example of any of them.
"""

from __future__ import annotations

from typing import Any

import pytest

from logic.household import Household, households_from_views, load_gold_households, load_pack_checklists

#: A plausible source box. Any four numbers make a field traceable; the values only
#: matter to the UI overlay, which is not this layer's concern.
BOX = [40.0, 648.0, 94.0, 662.0]


def make_document(document_id: str, document_type: str, *, page: int = 1,
                  traceable: bool = True, certainty: str = "high",
                  **fields: Any) -> dict[str, Any]:
    """A DocumentView with the given fields. ``value=None`` marks an abstained field."""
    items = []
    for name, value in fields.items():
        items.append({
            "field": name,
            "value": value,
            "page": page if traceable else None,
            "bbox": list(BOX) if traceable else None,
            "certainty": "abstain" if value is None else certainty,
        })
    return {
        "document_id": document_id,
        "household_id": document_id.rsplit("-", 1)[0],
        "document_type": document_type,
        "file_name": f"{document_id.lower()}.pdf",
        "fields": items,
    }


def make_household(household_id: str, *views: dict[str, Any]) -> Household:
    return households_from_views(views)[household_id]


@pytest.fixture(scope="session")
def gold_households():
    return load_gold_households()


@pytest.fixture(scope="session")
def pack_checklists():
    return load_pack_checklists()


@pytest.fixture
def doc_factory():
    return make_document


@pytest.fixture
def household_factory():
    return make_household
