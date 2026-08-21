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

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response
from dotenv import load_dotenv
load_dotenv()
from extraction import extract_fields, extract_npd_update, transcribe_audio
from db import upsert_enquiry, upsert_npd_update

app = FastAPI()

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "change-me")
# Which WhatsApp Business number NPD updates arrive on, so a single webhook
# can route two lines to two different tables (enquiries vs. npd_updates).
NPD_PHONE_NUMBER_ID = os.environ["NPD_PHONE_NUMBER_ID"]
# Needed to call the Meta Graph API directly (media download + replies) —
# separate from any BSP-specific send API a provider like Twilio might offer.
WHATSAPP_ACCESS_TOKEN = os.environ["WHATSAPP_ACCESS_TOKEN"]
# Meta deprecates old Graph API versions periodically — config, not a hardcode.
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION") or "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

# A 2-minute WhatsApp voice note (opus, low bitrate) is typically well under
# 1MB. This is a generous multiple of that meant to catch anything clearly
# oversized before spending a download + Groq call on it, not a precise budget.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 120


@app.get("/webhook")
def verify_webhook(request: Request):
    """Meta calls this once when you register the webhook URL, to confirm ownership."""
    params = request.query_params
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive_message(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming WhatsApp messages (Meta Cloud API payload shape shown
    below — adjust parsing if you use a BSP like Twilio/Gupshup instead,
    since their payload formats differ).

    Acks 200 immediately and does the actual work (Groq call, DB write) in
    a background task: Meta retries on a slow/timed-out response, and a
    retry landing mid-processing would otherwise insert the same message
    twice.
    """
    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages", [])
    except (KeyError, IndexError):
        return {"status": "ignored"}

    phone_number_id = change.get("metadata", {}).get("phone_number_id")

    for msg in messages:
        if phone_number_id == NPD_PHONE_NUMBER_ID:
            background_tasks.add_task(handle_npd_message, msg)
            continue

        if msg.get("type") != "text":
            continue  # extend later for images/documents if needed

        background_tasks.add_task(handle_enquiry_message, msg)

    return {"status": "ok"}


def handle_enquiry_message(msg: dict) -> None:
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


class AudioTooLarge(Exception):
    def __init__(self, file_size: int):
        self.file_size = file_size


def _download_whatsapp_media(media_id: str) -> tuple[bytes, str]:
    """
    Returns (content, mime_type). Two Graph API calls: media metadata (has
    the real download URL + file_size), then the download itself — both
    need the same bearer token, and the URL from the first call expires.
    """
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    meta_resp = httpx.get(f"{GRAPH_API_BASE}/{media_id}", headers=headers, timeout=30)
    meta_resp.raise_for_status()
    meta = meta_resp.json()

    if meta.get("file_size", 0) > MAX_AUDIO_BYTES:
        raise AudioTooLarge(meta["file_size"])

    content_resp = httpx.get(meta["url"], headers=headers, timeout=60)
    content_resp.raise_for_status()
    return content_resp.content, meta.get("mime_type", "audio/ogg")


def _send_whatsapp_reply(to: str, body: str) -> None:
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    resp = httpx.post(
        f"{GRAPH_API_BASE}/{NPD_PHONE_NUMBER_ID}/messages",
        headers=headers,
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        # Best-effort — don't let a failed courtesy reply mask the original issue.
        print(f"NPD webhook: reply to {to} failed ({resp.status_code}): {resp.text[:300]}")


def handle_npd_message(msg: dict) -> None:
    """
    Routes an inbound NPD-line WhatsApp message to the shared extraction/upsert
    pipeline (extract_npd_update -> db.upsert_npd_update). Text messages feed
    their body straight in; audio messages are downloaded, transcribed via
    Groq Whisper, and their transcript fed in the same way — same downstream
    logic either way, only the source text differs.
    """
    msg_type = msg.get("type")

    if msg_type == "text":
        _process_npd_update(msg, msg["text"]["body"], source="whatsapp_text", raw_transcript=None)
        return

    if msg_type == "audio":
        _handle_npd_voice_message(msg)
        return

    print(f"NPD webhook: ignoring unsupported message type {msg_type!r} from {msg.get('from')}")


def _handle_npd_voice_message(msg: dict) -> None:
    sender = msg["from"]
    media_id = msg["audio"]["id"]

    try:
        audio_bytes, mime_type = _download_whatsapp_media(media_id)
    except AudioTooLarge as exc:
        print(f"NPD webhook: voice note from {sender} skipped — {exc.file_size} bytes over the {MAX_AUDIO_BYTES} limit")
        _send_whatsapp_reply(
            sender,
            "That voice note is too large to process. Please send a shorter one "
            "(under ~2 minutes) or type your update instead.",
        )
        return
    except httpx.HTTPError as exc:
        print(f"NPD webhook: voice note from {sender} — media download failed: {exc}")
        _send_whatsapp_reply(
            sender,
            "We couldn't download your voice note. Please try sending it again "
            "or type your update instead.",
        )
        return

    extension = "ogg" if "ogg" in mime_type else mime_type.split("/")[-1].split(";")[0]

    try:
        transcript = transcribe_audio(audio_bytes, f"{media_id}.{extension}")
    except Exception as exc:
        # Fail open per CLAUDE.md: tell the sender rather than silently eating
        # their update on a Groq/network hiccup (extract_npd_update has its
        # own internal fail-safe for extraction errors, but a transcription
        # failure means there's no text to extract from at all).
        print(f"NPD webhook: voice note from {sender} — transcription failed: {exc}")
        _send_whatsapp_reply(
            sender,
            "We couldn't transcribe your voice note. Please try again or type "
            "your update instead.",
        )
        return

    duration = transcript["duration"]
    if duration is not None and duration > MAX_AUDIO_SECONDS:
        print(
            f"NPD webhook: voice note from {sender} skipped — {duration:.0f}s over the "
            f"{MAX_AUDIO_SECONDS}s limit; transcript for reference: {transcript['text'][:300]!r}"
        )
        _send_whatsapp_reply(
            sender,
            "That voice note is longer than 2 minutes. Please send a shorter "
            "update or type it instead.",
        )
        return

    _process_npd_update(msg, transcript["text"], source="whatsapp_voice", raw_transcript=transcript["text"])


def _process_npd_update(msg: dict, text: str, source: str, raw_transcript: str | None) -> None:
    msg_id = msg["id"]
    update_date = datetime.fromtimestamp(int(msg["timestamp"]), tz=timezone.utc)

    extracted = extract_npd_update(text)

    record = {
        "update_text": extracted["update_text"],
        "update_date": update_date.isoformat(),
        "next_follow_up": extracted.get("next_follow_up"),
        "source": source,
        "source_message_id": msg_id,
        "raw_transcript": raw_transcript,
    }

    upsert_npd_update(
        party_name=extracted["party_name"],
        stage_guess=extracted.get("stage_guess"),
        contact_person=extracted.get("contact_person"),
        potential_volume=extracted.get("potential_volume"),
        update=record,
    )
