# -*- coding: utf-8 -*-
"""
Tests for the closed-set label mapper.

None of these call a model. They test the properties that must hold *whether or not* a
model is reachable, which is the only kind of property worth asserting about a component
whose remote half we do not control:

  * it is off unless explicitly switched on, and off means bit-identical to before;
  * a reply outside the field set is discarded rather than trusted;
  * values never leave the process;
  * the table path stays reproducible offline.

The model's own accuracy is not tested here -- it is *measured*, on documents whose
labels were transcribed before anyone read our synonym table, by
`scripts/measure_label_mapping.py`. A unit test written by the same people who wrote the
table would only repeat the mistake that script exists to correct.
"""
from __future__ import annotations

import pytest

from core import extract as ex
from core import label_llm


# ─────────────────────────────────────────────────── off by default

def test_disabled_under_pytest_without_explicit_optin(monkeypatch):
    """The suite must never depend on a network, and must prove the tables stand alone."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.delenv("REALDOOR_LABEL_LLM", raising=False)
    assert label_llm.is_enabled() is False
    assert label_llm.model_mapper("pay_stub", "TOTAL EARNINGS") is None


def test_disabled_without_a_key(monkeypatch):
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert label_llm.is_enabled() is False


def test_explicit_zero_beats_everything(monkeypatch):
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "0")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    assert label_llm.is_enabled() is False


def test_layered_mapper_equals_synonym_mapper_when_model_is_off():
    """With the model off, the new seam must be indistinguishable from the old path."""
    for doc_type in ("pay_stub", "employment_letter", "benefit_letter"):
        for label in ("GROSS WAGES", "TAKE HOME PAY", "NONSENSE STRING", "EMPLOYEE"):
            assert ex.layered_mapper(doc_type, label) == ex.synonym_mapper(doc_type, label)


# ───────────────────────────────────────── the model cannot invent a field

@pytest.mark.parametrize(
    "reply",
    [
        {"field": "employer_name"},        # plausible, but not a field we have
        {"field": "gross_pay_ytd"},        # near miss on a real field
        {"field": ""},
        {"field": "unknown"},
        {"field": None},
        {"field": 7},
        {"not_the_key": "gross_pay"},
        "employer_name",                   # bare string, and outside the set
        None,
    ],
)
def test_reply_outside_the_closed_set_is_discarded(monkeypatch, reply):
    """Structured output is requested, not believed. Anything unexpected -> abstain."""
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    label_llm.reset_stats()
    monkeypatch.setattr(label_llm, "_providers", lambda: _FakeProviders(reply))

    assert label_llm.model_mapper("pay_stub", "TOTAL EARNINGS") is None


@pytest.mark.parametrize(
    "reply",
    [
        {"field": "gross_pay"},
        "gross_pay",  # a bare string is tolerated -- but only because the closed-set
                      # membership test below still has to pass. Same tolerance as
                      # `api.route_llm.classify`.
    ],
)
def test_a_reply_inside_the_set_is_accepted(monkeypatch, reply):
    """The control for the test above -- the rejection is selective, not blanket."""
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    label_llm.reset_stats()
    monkeypatch.setattr(label_llm, "_providers", lambda: _FakeProviders(reply))

    assert label_llm.model_mapper("pay_stub", "TOTAL EARNINGS") == "gross_pay"


def test_accepted_field_is_always_in_known_fields(monkeypatch):
    """Property form of the above, over every document type."""
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    for doc_type in ex.EXPECTED_FIELDS:
        for candidate in ("person_name", "gross_pay", "monthly_benefit", "made_up_field"):
            label_llm.reset_stats()
            monkeypatch.setattr(
                label_llm, "_providers", lambda: _FakeProviders({"field": candidate})
            )
            got = label_llm.model_mapper(doc_type, "SOME LABEL")
            assert got is None or got in label_llm.known_fields(doc_type)


def test_schema_enum_is_exactly_the_known_field_set():
    for doc_type in ex.EXPECTED_FIELDS:
        enum = label_llm._schema(doc_type)["properties"]["field"]["enum"]
        assert enum == list(label_llm.known_fields(doc_type)) + [label_llm.UNKNOWN]


def test_field_set_is_collected_not_copied():
    """A hard-coded second copy could drift; there must not be one."""
    for doc_type, fields in ex.EXPECTED_FIELDS.items():
        assert label_llm.known_fields(doc_type) == tuple(fields)


# ─────────────────────────────────────────────── values never leave

@pytest.mark.parametrize(
    "leaky",
    [
        "$1,440.00",
        "1440.00",
        "2026-07-03",
        "07/03/2026",
        "123-45-6789",
        "sam.poe@example.com",
        "",
        "   ",
        "A label so long that it is plainly a sentence of document prose rather than a "
        "caption printed beside a value",
    ],
)
def test_value_shaped_strings_are_refused(leaky):
    with pytest.raises(label_llm.ValueLeak):
        label_llm.assert_no_values(leaky)


@pytest.mark.parametrize(
    "caption",
    ["GROSS WAGES", "Period Ending", "TOTAL EARNINGS", "YTD GROSS", "Pay Date", "NET PAY"],
)
def test_real_captions_pass_the_leak_check(caption):
    label_llm.assert_no_values(caption)


def test_every_label_in_both_tables_passes_the_leak_check():
    """If a table string cannot be sent, the guard is miscalibrated -- catch it here."""
    for table in (ex.LABEL_MAP, ex.LABEL_SYNONYMS):
        for mapping in table.values():
            for label in mapping:
                label_llm.assert_no_values(label)


def test_value_shaped_label_never_reaches_the_provider(monkeypatch):
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    label_llm.reset_stats()
    fake = _FakeProviders({"field": "gross_pay"})
    monkeypatch.setattr(label_llm, "_providers", lambda: fake)

    assert label_llm.model_mapper("pay_stub", "$1,440.00") is None
    assert fake.calls == [], "a value-shaped string was sent to the model"
    assert label_llm.stats()["rejected_value_shaped"] == 1


def test_only_the_label_is_sent(monkeypatch):
    """The content argument must be the caption alone -- no page text, no values."""
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    label_llm.reset_stats()
    fake = _FakeProviders({"field": "gross_pay"})
    monkeypatch.setattr(label_llm, "_providers", lambda: fake)

    label_llm.model_mapper("pay_stub", "TOTAL EARNINGS")

    assert len(fake.calls) == 1
    instruction, content = fake.calls[0]
    assert content == "TOTAL EARNINGS"
    # The instruction is field names and glosses. It must carry no document content.
    assert "1440" not in instruction and "John Doe" not in instruction


# ─────────────────────────────────────── failures degrade to abstention

#: The gateway raises `CacheMiss` when offline with a cold cache. That is a designed
#: ending, not a fault, and it must land in the same place as a crash: abstention.
class _CacheMiss(Exception):
    pass


@pytest.mark.parametrize("exc", [RuntimeError("boom"), _CacheMiss("offline, no cache"), TimeoutError()])
def test_provider_failure_is_an_abstention(monkeypatch, exc):
    monkeypatch.setenv("REALDOOR_LABEL_LLM", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    label_llm.reset_stats()
    monkeypatch.setattr(label_llm, "_providers", lambda: _FailingProviders(exc))

    assert label_llm.model_mapper("pay_stub", "TOTAL EARNINGS") is None


# ─────────────────────────────────────────────────────── audits

def test_gloss_audit_has_no_stale_entries():
    audit = label_llm.gloss_audit()
    assert audit["glosses_for_unknown_fields"] == [], audit
    assert audit["ok"] is True


def test_provenance_notes_are_distinguishable():
    assert ex.SYNONYM_NOTE != ex.MODEL_MAPPER_NOTE
    assert ex.SYNONYM_NOTE not in ex.MODEL_MAPPER_NOTE


def test_retag_only_touches_model_named_fields():
    found = {
        "gross_pay": {"notes": ex.SYNONYM_NOTE, "value": 1},
        "net_pay": {"notes": ex.SYNONYM_NOTE, "value": 2},
    }
    ex._retag_model_provenance(found, {"gross_pay", "net_pay"}, {"gross_pay"})
    assert ex.MODEL_MAPPER_NOTE in found["gross_pay"]["notes"]
    assert found["net_pay"]["notes"] == ex.SYNONYM_NOTE
    assert found["gross_pay"]["value"] == 1 and found["net_pay"]["value"] == 2


# ──────────────────────────────────────────── the hold-out measurement

def test_holdout_deterministic_score_is_pinned():
    """The offline number must not drift silently, in either direction.

    19/34 is what `LABEL_SYNONYMS` reaches on labels it was not written against. If a
    later change to the table moves this, that is a real result and the number here
    should be updated deliberately -- but it must not move without anyone noticing,
    because the whole point of the hold-out set is that its score is not ours to choose.

    Skipped when the fixtures have not been generated (`python scripts/make_holdout.py`),
    since they are build artefacts rather than source.
    """
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    manifest = root / "testdata" / "holdout_manifest.json"
    if not manifest.exists():
        pytest.skip("hold-out fixtures not generated; run scripts/make_holdout.py")

    import sys

    sys.path.insert(0, str(root / "eval"))
    from score_extraction import normalize  # type: ignore

    docs = json.loads(manifest.read_text(encoding="utf-8"))["documents"]
    correct = wrong = total = 0
    for doc in docs:
        view = ex.extract_document(
            root / "testdata" / "holdout" / doc["file_name"],
            document_type=doc["document_type"],
            fallback_mapper=ex.synonym_mapper,
        )
        got = {f["field"]: f for f in view["fields"]}
        for name, expected in doc["intended_fields"].items():
            total += 1
            field = got.get(name)
            if field is None or field["certainty"] == "abstain":
                continue
            if normalize(name, expected) == normalize(name, field["value"]):
                correct += 1
            else:
                wrong += 1

    assert wrong == 0, "a wrong answer on the hold-out set is a regression, not a trade-off"
    assert (correct, total) == (19, 34)


# ─────────────────────────────────────────────────────── fakes

class _FakeProviders:
    """Stands in for `tools/providers.py`. Records what would have been sent."""

    USAGE_LOG = "nonexistent-usage.jsonl"

    def __init__(self, reply):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, instruction, content="", **kwargs):
        self.calls.append((instruction, content))
        return self.reply


class _FailingProviders:
    USAGE_LOG = "nonexistent-usage.jsonl"

    def __init__(self, exc):
        self.exc = exc

    def complete(self, instruction, content="", **kwargs):
        raise self.exc
