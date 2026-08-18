"""
Uses the Groq API (free tier) to turn raw message text (from Gmail or
WhatsApp) into structured fields ready to insert into the `enquiries` table.
"""

import json
import os
from datetime import datetime, timezone

from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

# Groq periodically retires model IDs (this pipeline broke in production when
# "llama-3.3-70b-versatile" stopped being accessible — a 404 model_not_found).
# Configurable so a future retirement is a config change, not a code change:
# check https://console.groq.com/docs/models for currently supported models
# and set GROQ_MODEL if the default below is ever retired too.
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

EXTRACTION_PROMPT = """You are extracting structured data from a business enquiry message
received by a corrugated packaging company. Read the message below and return ONLY a JSON
object (no markdown fences, no preamble, no explanation) with these exact fields:

{{
  "category": one of "enquiry", "order", "complaint", "follow_up", "other",
  "summary": a one-sentence summary of what the sender wants,
  "deadline": an ISO 8601 date (YYYY-MM-DD) if the message states or clearly implies a
              deadline/date by which something is needed, otherwise null,
  "needs_deadline": true if the message sounds like it requires action/response but no
                     deadline could be extracted, otherwise false,
  "priority": one of "low", "medium", "high" based on urgency of the language used
}}

Today's date is {today}.

Message:
---
{message_text}
---

Return only the JSON object.
"""


def extract_fields(message_text: str) -> dict:
    """Call Groq to extract structured fields from a raw message."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = EXTRACTION_PROMPT.format(today=today, message_text=message_text)

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        temperature=0,
        response_format={"type": "json_object"},  # Groq enforces valid JSON output with this
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fail safe: flag for manual review rather than dropping the message
        data = {
            "category": "other",
            "summary": message_text[:140],
            "deadline": None,
            "needs_deadline": True,
            "priority": "medium",
        }

    return data