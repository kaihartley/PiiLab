"""PII controls, named for where the data is going.

for_partner -> SMS provider. Comprehend (transformation): the action depends on
               the PII type - mask an email, block a card - and only Comprehend
               gives each entity's type and position.
for_storage -> our log. ApplyGuardrail (decision): the log is optional, so the
               only question is write or withhold.

Both fail closed.
"""

import os
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = os.environ.get("AWS_REGION", "us-east-1")


class PartnerPayloadBlocked(Exception):
    """Raised when a payload must not be sent to the SMS provider."""


# Created on first use so tests can swap in fakes.
def _default_comprehend_client():
    return boto3.client("comprehend", region_name=REGION)


def _default_guardrail_client():
    return boto3.client("bedrock-runtime", region_name=REGION)


# --- SMS provider ------------------------------------------------------------

# Allow-list, not deny-list: the account already holds fields nobody planned
# for (a card number in staff_notes). A deny-list forwards anything new; an
# allow-list keeps it home. The provider needs a phone to text, a name to greet.
PARTNER_MAY_SEE = ("name", "phone")

# Per-type action for PII in the model-written message.
MESSAGE_POLICY = {
    "NAME": "allow",   # provider already has these
    "PHONE": "allow",
    "EMAIL": "mask",
    "ADDRESS": "mask",
    "CREDIT_DEBIT_NUMBER": "block",
    "CREDIT_DEBIT_CVV": "block",
    "CREDIT_DEBIT_EXPIRY": "block",
    "BANK_ACCOUNT_NUMBER": "block",
    "BANK_ROUTING": "block",
    "PIN": "block",
    "PASSWORD": "block",
}
DEFAULT_ACTION = "mask"  # unlisted types: nothing goes as-is unless allowed


def for_partner(account: dict, message: str, *, comprehend_client=None) -> dict:
    """Allow-listed account fields plus the message with MESSAGE_POLICY applied.
    Raises PartnerPayloadBlocked if it must not be sent."""
    payload = {k: account[k] for k in PARTNER_MAY_SEE if k in account}
    client = comprehend_client or _default_comprehend_client()
    try:
        payload["message"] = _apply_message_policy(message, client)
    except (BotoCoreError, ClientError) as exc:
        raise PartnerPayloadBlocked(f"could not scrub message ({type(exc).__name__})")
    return payload


def _apply_message_policy(text: str, client) -> str:
    if not text.strip():
        return text
    entities = client.detect_pii_entities(Text=text, LanguageCode="en")["Entities"]

    blocked = sorted({e["Type"] for e in entities
                      if MESSAGE_POLICY.get(e["Type"], DEFAULT_ACTION) == "block"})
    if blocked:
        # Types only, never values - this goes back to the model.
        raise PartnerPayloadBlocked(f"message contains {', '.join(blocked)}")

    spans = sorted((e["BeginOffset"], e["EndOffset"], e["Type"]) for e in entities
                   if MESSAGE_POLICY.get(e["Type"], DEFAULT_ACTION) == "mask")

    # Merge overlaps so one entity can't leave part of another visible.
    merged: list[list] = []
    for begin, end, kind in spans:
        if merged and begin < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([begin, end, kind])

    for begin, end, kind in reversed(merged):
        text = text[:begin] + f"[{kind}]" + text[end:]
    return text


# --- Our log -----------------------------------------------------------------

STORAGE_METADATA = ("ts", "event", "session_id")  # ours; always kept
STORAGE_MAY_KEEP = ("prompt", "response")         # allow-list; anything else is dropped


def for_storage(record: dict, *, guardrail_client=None) -> dict:
    """Allow-listed fields if the guardrail finds no PII, else metadata only."""
    metadata = {k: record[k] for k in STORAGE_METADATA if k in record}
    metadata.setdefault("ts", datetime.now(timezone.utc).isoformat())
    dropped = sorted(k for k in record if k not in STORAGE_METADATA + STORAGE_MAY_KEEP)
    if dropped:
        metadata["dropped_fields"] = dropped  # names only
    content = {k: record[k] for k in STORAGE_MAY_KEEP if k in record}

    text = "\n".join(_strings(content))
    if not text.strip():
        return {**metadata, **content}

    guardrail_id = os.environ.get("GUARDRAIL_ID")
    if not guardrail_id:
        return {**metadata, "withheld": True, "reason": "no guardrail configured"}

    client = guardrail_client or _default_guardrail_client()
    try:
        resp = client.apply_guardrail(
            guardrailIdentifier=guardrail_id,
            guardrailVersion=os.environ.get("GUARDRAIL_VERSION", "DRAFT"),
            source="INPUT",  # as in this morning's check_guardrail.py
            content=[{"text": {"text": text}}],
        )
    except (BotoCoreError, ClientError) as exc:
        return {**metadata, "withheld": True,
                "reason": f"guardrail unavailable ({type(exc).__name__})"}

    # Decision only: read action, never the masked outputs.
    if resp.get("action") == "GUARDRAIL_INTERVENED":
        return {**metadata, "withheld": True, "reason": "personal data detected"}
    return {**metadata, **content}


def _strings(value):
    """Every string in value, including nested ones."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
