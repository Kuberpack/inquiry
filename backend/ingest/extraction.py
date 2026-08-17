"""
Uses the Groq API (free tier) to turn raw message text (from Gmail or
WhatsApp) into structured fields ready to insert into the `enquiries` table.
"""

import json
import os
from datetime import datetime, timezone

from groq import Groq

client = Groq(api_key=os.environ["GROQ_API_KEY"])

MODEL = "llama-3.3-70b-versatile"  # good balance of quality/speed on Groq's free tier

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
        max_tokens=350,
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