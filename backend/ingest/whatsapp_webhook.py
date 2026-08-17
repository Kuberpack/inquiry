"""
WhatsApp Business API webhook receiver — for when the Business API number
is set up (Meta Cloud API or a BSP like Twilio/Gupshup/360dialog).

The exact payload shape depends on which provider you pick, but the flow
is always: Meta/provider POSTs incoming messages to this endpoint in
near-real-time, you parse sender + text, then run the same extraction and
db.upsert_enquiry() used for Gmail.

Run with: uvicorn whatsapp_webhook:app --host 0.0.0.0 --port 8000
"""

import os
from datetime import datetime, timezone

from fastapi import FastAPI, Request, Response
from dotenv import load_dotenv
load_dotenv()
from extraction import extract_fields
from db import upsert_enquiry

app = FastAPI()

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "change-me")


@app.get("/webhook")
def verify_webhook(request: Request):
    """Meta calls this once when you register the webhook URL, to confirm ownership."""
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive_message(request: Request):
    """
    Receives incoming WhatsApp messages (Meta Cloud API payload shape shown
    below — adjust parsing if you use a BSP like Twilio/Gupshup instead,
    since their payload formats differ).
    """
    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages", [])
    except (KeyError, IndexError):
        return {"status": "ignored"}

    for msg in messages:
        if msg.get("type") != "text":
            continue  # extend later for images/documents if needed

        sender = msg["from"]  # phone number
        text = msg["text"]["body"]
        msg_id = msg["id"]
        received_at = datetime.fromtimestamp(int(msg["timestamp"]), tz=timezone.utc)

        extracted = extract_fields(text)

        record = {
            "source": "whatsapp",
            "source_message_id": msg_id,
            "sender_name": sender,
            "sender_contact": sender,
            "raw_text": text[:5000],
            "received_at": received_at.isoformat(),
            "category": extracted.get("category"),
            "summary": extracted.get("summary"),
            "deadline": extracted.get("deadline"),
            "needs_deadline": extracted.get("needs_deadline", False),
            "priority": extracted.get("priority", "medium"),
        }

        upsert_enquiry(record)

    return {"status": "ok"}
