"""Leak tests; each goes red if its control is removed. AWS is faked, so no credentials needed."""

import json
import re

import pytest
from botocore.exceptions import EndpointConnectionError

import controls
import store
import tools

NAME = "Ada Placeholder"
EMAIL = "ada.placeholder@example.invalid"
PHONE = "+44 7700 900456"
ADDRESS = "7 Fiction Row"
POSTCODE = "ZZ99 1AB"
CARD = "4111 1111 1111 1111"
LOAN_TITLE = "Coping With Debt"

# What the SMS provider must never see. Name and phone are allow-listed.
NOT_FOR_SMS_PROVIDER = [EMAIL, ADDRESS, POSTCODE, CARD, LOAN_TITLE]
# What must never be written down raw.
NEVER_STORED = [NAME, EMAIL, PHONE, ADDRESS, CARD]

_PII_PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("CREDIT_DEBIT_NUMBER", re.compile(r"\b(?:\d{4} ){3}\d{4}\b")),
    ("PHONE", re.compile(r"\+\d{2} \d{4} \d{6}")),
    ("NAME", re.compile(re.escape(NAME))),
    ("ADDRESS", re.compile(re.escape(ADDRESS))),
]


class FakeComprehend:
    """Returns entities with real offsets, like detect_pii_entities."""

    def detect_pii_entities(self, Text, LanguageCode):
        return {"Entities": [
            {"Type": kind, "BeginOffset": m.start(), "EndOffset": m.end(), "Score": 0.99}
            for kind, pattern in _PII_PATTERNS
            for m in pattern.finditer(Text)
        ]}


class BrokenComprehend:
    def detect_pii_entities(self, Text, LanguageCode):
        raise EndpointConnectionError(endpoint_url="https://comprehend.invalid")


class FakeGuardrail:
    """Intervenes when the text contains PII, like apply_guardrail with a
    sensitive-information policy set to mask or block."""

    def apply_guardrail(self, *, guardrailIdentifier, guardrailVersion, source, content):
        text = content[0]["text"]["text"]
        hit = any(p.search(text) for _, p in _PII_PATTERNS)
        return {"action": "GUARDRAIL_INTERVENED" if hit else "NONE"}


class BlindGuardrail:
    """A guardrail that misses everything."""

    def apply_guardrail(self, **kwargs):
        return {"action": "NONE"}


@pytest.fixture
def sms_provider(monkeypatch, tmp_path):
    """Route send_hold_text through fake Comprehend and capture what the provider receives."""
    monkeypatch.setattr(controls, "_default_comprehend_client", lambda: FakeComprehend())
    monkeypatch.setattr(tools, "SMS_PROVIDER_INBOX_FILE", tmp_path / "sms_inbox.jsonl")
    tools.SMS_PROVIDER_INBOX.clear()
    yield tools.SMS_PROVIDER_INBOX
    tools.SMS_PROVIDER_INBOX.clear()


@pytest.fixture
def guardrail_configured(monkeypatch):
    monkeypatch.setenv("GUARDRAIL_ID", "fake-guardrail")


# --- OUT ---------------------------------------------------------------------

def test_sms_provider_receives_no_personal_data_it_does_not_need(sms_provider):
    # The model over-shares: the member's email ends up in the text.
    result = tools.send_hold_text.invoke({
        "member_id": "LIB-1234",
        "message": f"Hi Ada, hold H-5531 is ready at Central Library. Questions? {EMAIL}",
    })

    assert result == "Text sent."
    received = json.dumps(sms_provider)
    for value in NOT_FOR_SMS_PROVIDER:
        assert value not in received, f"SMS provider received {value!r}"
    # Still got what it needs to do the job.
    assert sms_provider[0]["phone"] == PHONE
    assert "H-5531" in sms_provider[0]["message"]


def test_card_number_in_the_message_stops_the_text(sms_provider):
    result = tools.send_hold_text.invoke({
        "member_id": "LIB-1234",
        "message": f"Your fine was paid with card {CARD}. Hold H-5531 is ready.",
    })

    assert result.startswith("Text not sent")
    assert CARD not in result, "the refusal must not echo the value back to the model"
    assert sms_provider == []


def test_sms_fails_closed_when_comprehend_is_unavailable(sms_provider, monkeypatch):
    monkeypatch.setattr(controls, "_default_comprehend_client", lambda: BrokenComprehend())

    result = tools.send_hold_text.invoke({"member_id": "LIB-1234", "message": f"Hi {EMAIL}"})

    assert result.startswith("Text not sent")
    assert sms_provider == []


# --- STORED ------------------------------------------------------------------

def _a_turn_full_of_pii():
    return {
        "event": "turn",
        "session_id": "test-session",
        "prompt": f"Hi, I'm {NAME} ({EMAIL}, {PHONE}). Member LIB-1234. Is my book ready?",
        "response": f"Yes {NAME}, hold H-5531 is ready. We'll text {PHONE}.",
    }


def test_persisted_record_contains_no_raw_personal_data(tmp_path, guardrail_configured):
    log = tmp_path / "turns.jsonl"

    store.write(_a_turn_full_of_pii(), path=log, guardrail_client=FakeGuardrail())
    store.write({"event": "turn", "session_id": "test-session",
                 "prompt": "When does Central Library open?", "response": "9am."},
                path=log, guardrail_client=FakeGuardrail())

    on_disk = log.read_text(encoding="utf-8")
    for value in NEVER_STORED:
        assert value not in on_disk, f"{value!r} was written to disk"
    # Withheld, not silently dropped - and a clean turn is still kept.
    first, second = (json.loads(line) for line in on_disk.splitlines())
    assert first["withheld"] is True
    assert second["prompt"] == "When does Central Library open?"


def test_unlisted_fields_never_reach_disk_even_if_the_guardrail_misses(tmp_path, guardrail_configured):
    log = tmp_path / "turns.jsonl"
    record = {"event": "turn", "session_id": "s", "prompt": "Is my book ready?", "response": "Yes.",
              # A field nobody chose to log: the raw account, IN-leak card number included.
              "tool_result": tools.read_account.invoke({"member_id": "LIB-1234"})}

    store.write(record, path=log, guardrail_client=BlindGuardrail())

    on_disk = log.read_text(encoding="utf-8")
    for value in NEVER_STORED:
        assert value not in on_disk, f"{value!r} was written to disk"
    assert json.loads(on_disk)["dropped_fields"] == ["tool_result"]


def test_storage_fails_closed_without_a_guardrail(tmp_path, monkeypatch):
    monkeypatch.delenv("GUARDRAIL_ID", raising=False)
    log = tmp_path / "turns.jsonl"

    store.write(_a_turn_full_of_pii(), path=log)

    on_disk = log.read_text(encoding="utf-8")
    for value in NEVER_STORED:
        assert value not in on_disk, f"{value!r} was written to disk"
    assert json.loads(on_disk)["withheld"] is True
