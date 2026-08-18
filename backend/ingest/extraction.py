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

    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=1024,
        temperature=0,
        response_format={"type": "json_object"},  # Groq enforces valid JSON output with this
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Fail safe: flag for manual review rather than silently dropping the message
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