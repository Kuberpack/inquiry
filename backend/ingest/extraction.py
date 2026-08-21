"""
Uses the Groq API (free tier) to turn raw message text (from Gmail or
WhatsApp) into structured fields ready to insert into the `enquiries` table,
plus NPD-specific extraction and voice-note transcription for the NPD
WhatsApp line (see extract_npd_update() / transcribe_audio() below).
"""

import json
import os
from datetime import datetime, timezone

from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

# Groq periodically retires model IDs (this pipeline broke in production when
# "llama-3.3-70b-versatile" was retired — a 404 model_not_found; as of writing
# Groq's production lineup for general chat/extraction has moved to OpenAI's
# GPT-OSS models, gpt-oss-120b being the closest equivalent to the old
# flagship). Configurable so the next retirement is a config change, not a
# code change — check https://console.groq.com/docs/models for currently
# supported (Production-tier, not Preview) models and set GROQ_MODEL if this
# default is ever retired too.
MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"

EXTRACTION_PROMPT = """You are triaging an inbox for a corrugated packaging company, which
receives a mix of genuine business messages (enquiries, orders, complaints, supplier/customer
follow-ups) and messages that have nothing to do with the business (personal correspondence,
newsletters, personal shopping/travel/bank notifications, spam, automated notices unrelated to
the business). Read the message below and return ONLY a JSON object (no markdown fences, no
preamble, no explanation) with these exact fields:

{{
  "is_business_relevant": true if this is a genuine business message for the company (an
                           enquiry, order, complaint, or follow-up from a customer, supplier,
                           or business contact), false if it's personal, promotional, or
                           otherwise unrelated to running the business,
  "category": one of "enquiry", "order", "complaint", "follow_up", "other" — only meaningful
              when is_business_relevant is true, otherwise use "other",
  "summary": a one-sentence summary of what the sender wants (or, if not business relevant, a
             one-sentence note of what the message actually is, e.g. "Personal email from a
             friend" or "Newsletter/promotional email"),
  "deadline": an ISO 8601 date (YYYY-MM-DD) if the message states or clearly implies a
              deadline/date by which something is needed, otherwise null,
  "needs_deadline": true if the message sounds like it requires action/response but no
                     deadline could be extracted, otherwise false,
  "priority": one of "low", "medium", "high" based on urgency of the language used
}}

When in doubt about whether something is business-relevant, prefer true — a false negative
hides a real enquiry from the team, which is worse than a false positive they can dismiss.

Today's date is {today}.

Message:
---
{message_text}
---

Return only the JSON object.
"""


def extract_fields(message_text: str) -> dict:
    """Call Groq to extract structured fields from a raw message, including whether it's
    business-relevant at all (used to filter personal/promotional mail out of the dashboard)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = EXTRACTION_PROMPT.format(today=today, message_text=message_text)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=1024,
            temperature=0,
            response_format={"type": "json_object"},  # Groq enforces valid JSON output with this
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()

        data = json.loads(raw)
    except Exception as exc:
        # Fail safe: flag for manual review rather than crashing the whole ingestion
        # run over one bad message (Groq API errors and JSON parse failures alike)
        print(f"extract_fields failed for {message_text[:120]!r}: {exc}")
        data = {
            "is_business_relevant": True,
            "category": "other",
            "summary": message_text[:140],
            "deadline": None,
            "needs_deadline": True,
            "priority": "medium",
        }

    data.setdefault("is_business_relevant", True)
    return data


# Single source of truth is the `check` constraint on npd_leads.stage in
# backend/npd-schema.sql (documented in schema.md). Mirrored here because a
# Postgres check constraint isn't queryable at runtime without another round
# trip — keep this list in sync if the constraint ever changes.
NPD_STAGES = [
    "New Lead",
    "In Progress (Samples/Rates)",
    "Awaiting Response",
    "Rate Negotiation",
    "On Hold",
    "Active/Won",
    "Rate Mismatch (Lost)",
]

NPD_EXTRACTION_PROMPT = """You are logging an update on a New Product Development (NPD) lead for a
corrugated packaging company, from a WhatsApp message sent by a salesperson in the field (typed, or
transcribed from a voice note — expect some transcription noise). Read the message below and return
ONLY a JSON object (no markdown fences, no preamble, no explanation) with these exact fields:

{{
  "party_name": the name of the company/party this update is about, best guess even if it's only a
                partial or informal name (e.g. "Sharma Traders"). If genuinely no party is
                identifiable, use "Unknown — needs review",
  "contact_person": the name of a specific contact person mentioned, otherwise null,
  "update_text": a one-sentence summary of what happened or was discussed, written in third person
                 (e.g. "Quoted samples of 5-ply boxes, awaiting their feedback."),
  "stage_guess": one of {stages} if the message clearly implies the lead has moved to that pipeline
                 stage, otherwise null (null means "leave the existing stage alone"),
  "next_follow_up": an ISO 8601 date (YYYY-MM-DD) if the message states or clearly implies when to
                     follow up next, otherwise null,
  "potential_volume": a rough volume/quantity mentioned for this lead (e.g. "5000 boxes/month"),
                       otherwise null
}}

Today's date is {today}.

Message:
---
{message_text}
---

Return only the JSON object.
"""


def extract_npd_update(message_text: str) -> dict:
    """
    Groq call turning a raw NPD WhatsApp message into structured fields for npd_leads/npd_updates.
    Shared by both whatsapp_text and whatsapp_voice sources in whatsapp_webhook.py — the caller
    just picks which text (typed body or transcript) to feed in, so this logic exists once.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = NPD_EXTRACTION_PROMPT.format(
        stages=json.dumps(NPD_STAGES), today=today, message_text=message_text
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=512,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)

        if data.get("stage_guess") not in NPD_STAGES:
            data["stage_guess"] = None
    except Exception as exc:
        # Fail safe: flag for manual review (via the fallback party name below)
        # rather than dropping the update entirely on a Groq error or bad parse.
        print(f"extract_npd_update failed for {message_text[:120]!r}: {exc}")
        data = {
            "party_name": "Unknown — needs review",
            "contact_person": None,
            "update_text": message_text[:280],
            "stage_guess": None,
            "next_follow_up": None,
            "potential_volume": None,
        }

    if not data.get("party_name"):
        data["party_name"] = "Unknown — needs review"
    if not data.get("update_text"):
        data["update_text"] = message_text[:280]
    return data


# Groq periodically retires model IDs (see MODEL above) — same reasoning applies
# to the Whisper models, so this is configurable rather than hardcoded too.
WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL") or "whisper-large-v3-turbo"


def transcribe_audio(audio_bytes: bytes, filename: str) -> dict:
    """
    Transcribes a WhatsApp voice note via Groq's Whisper endpoint. Returns
    {"text": ..., "duration": seconds}. verbose_json is the only response_format
    that reports duration — WhatsApp's webhook payload and Graph API media
    metadata don't expose it — so whatsapp_webhook.py's length guardrail checks
    the duration in this result rather than before making the call.
    """
    response = client.audio.transcriptions.create(
        model=WHISPER_MODEL,
        file=(filename, audio_bytes),
        response_format="verbose_json",
        temperature=0,
        prompt=(
            "Corrugated packaging business call log: party names, box "
            "specifications (ply, GSM, size), rates, and follow-up dates."
        ),
    )
    return {"text": response.text.strip(), "duration": getattr(response, "duration", None)}