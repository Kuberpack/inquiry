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
from extraction import extract_fields, extract_npd_update, transcribe_audio, NPD_STAGES
from db import (
    upsert_enquiry,
    get_npd_update_by_message_id,
    find_matching_npd_leads,
    create_npd_lead,
    update_npd_lead_stage,
    insert_npd_update,
    flag_npd_update_for_review,
)

app = FastAPI()

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "change-me")
# Which WhatsApp Business number NPD updates arrive on, so a single webhook
# can route two lines to two different tables (enquiries vs. npd_updates).
NPD_PHONE_NUMBER_ID = os.environ["NPD_PHONE_NUMBER_ID"]
# Used to call the Meta Graph API directly: sending confirmation/clarification
# replies, and downloading NPD voice note media. Not required for inbound text
# ingestion, so this stays a soft default rather than a required env var like
# NPD_PHONE_NUMBER_ID — without it, replies are just logged instead of sent,
# and voice notes are flagged for manual review instead of transcribed (see
# _handle_npd_voice_message).
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
# Meta retires old Graph API versions periodically — config over code,
# same reasoning as GROQ_MODEL.
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION") or "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"

# Similarity threshold (pg_trgm's default is 0.3) for match_npd_leads() —
# a "clear match" candidate must score above this to link automatically.
NPD_MATCH_THRESHOLD = 0.35

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


def send_whatsapp_message(to: str, text: str) -> None:
    """
    Sends a WhatsApp text reply via the Meta Cloud API. Best-effort: by
    the time this is called the npd_updates/npd_leads write has already
    happened, so a delivery failure here loses the confirmation, not the
    underlying data — it's logged, not retried.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        print(f"WHATSAPP_ACCESS_TOKEN not set — would have replied to {to}: {text!r}")
        return

    try:
        response = httpx.post(
            f"{GRAPH_API_BASE}/{NPD_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"send_whatsapp_message failed for {to}: {exc}")


def _parse_iso_date(value) -> str | None:
    """Groq is asked for YYYY-MM-DD but LLM output isn't guaranteed — validate at this DB
    insert boundary rather than trust it, since npd_updates.next_follow_up is a `date` column
    that would reject anything malformed."""
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value
    except (TypeError, ValueError):
        return None


def handle_npd_message(msg: dict) -> None:
    """
    Routes an inbound NPD-line WhatsApp message — text or a voice note —
    through one shared pipeline into a linked, confirmed npd_updates row
    (see schema.md / archi.md):

    1. Dedup against a Meta webhook retry (checked first, before any
       Groq/DB/transcription work, so a retry can't create a second lead,
       re-transcribe audio, or send a second reply).
    2. Text messages feed their body straight into _process_npd_text();
       audio messages are downloaded and transcribed first
       (_handle_npd_voice_message), then their transcript feeds into the
       same _process_npd_text() — same downstream logic either way, only
       the source text differs.
    3. _process_npd_text() extracts {party_name, update_summary,
       stage_guess, next_follow_up_date} via Groq (extract_npd_update),
       fuzzy-matches party_name against npd_leads (DB-side, pg_trgm).
       Zero matches -> create a lead. One match -> link it. More than
       one -> don't guess; ask the sender to disambiguate.
    4. Insert npd_updates and reply confirming what was logged.

    On any failure (Groq/transcription error or timeout, DB error, no
    party name, an ambiguous match, or a voice note over the size/length
    guardrails) the raw message is still stored — lead_id null,
    needs_review true — and the sender is told why, rather than the
    message being silently dropped.
    """
    msg_id = msg.get("id")
    sender = msg.get("from")
    if not msg_id or not sender:
        print(f"handle_npd_message: message missing id/from, dropping: {msg!r}")
        return

    if get_npd_update_by_message_id(msg_id) is not None:
        return  # already processed on an earlier delivery of this message

    msg_type = msg.get("type")

    if msg_type == "text":
        _process_npd_text(msg_id, sender, msg["text"]["body"], source="whatsapp_text", raw_transcript=None)
        return

    if msg_type == "audio":
        _handle_npd_voice_message(msg_id, sender, msg["audio"])
        return

    try:
        flag_npd_update_for_review(f"unsupported message type ({msg_type})", "", msg_id)
    except Exception as exc:
        print(f"flag_npd_update_for_review failed for {msg_id}: {exc}")
    send_whatsapp_message(
        sender, "That message type isn't supported yet — please send a text update or a "
                "voice note, or log this one manually on the dashboard."
    )


def _handle_npd_voice_message(msg_id: str, sender: str, audio: dict) -> None:
    if not WHATSAPP_ACCESS_TOKEN:
        try:
            flag_npd_update_for_review("voice note received but WHATSAPP_ACCESS_TOKEN not configured", "", msg_id)
        except Exception as exc:
            print(f"flag_npd_update_for_review failed for {msg_id}: {exc}")
        send_whatsapp_message(sender, "Voice notes aren't available right now — please type your update instead.")
        return

    media_id = audio["id"]

    try:
        audio_bytes, mime_type = _download_whatsapp_media(media_id)
    except AudioTooLarge as exc:
        print(f"NPD webhook: voice note from {sender} skipped — {exc.file_size} bytes over the {MAX_AUDIO_BYTES} limit")
        try:
            flag_npd_update_for_review(f"voice note too large ({exc.file_size} bytes)", "", msg_id)
        except Exception as inner_exc:
            print(f"flag_npd_update_for_review failed for {msg_id}: {inner_exc}")
        send_whatsapp_message(
            sender, "That voice note is too large to process. Please send a shorter one "
                    "(under ~2 minutes) or type your update instead.",
        )
        return
    except httpx.HTTPError as exc:
        print(f"NPD webhook: voice note from {sender} — media download failed: {exc}")
        try:
            flag_npd_update_for_review("voice note media download failed", "", msg_id)
        except Exception as inner_exc:
            print(f"flag_npd_update_for_review failed for {msg_id}: {inner_exc}")
        send_whatsapp_message(
            sender, "We couldn't download your voice note. Please try sending it again "
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
        try:
            flag_npd_update_for_review("voice note transcription failed", "", msg_id)
        except Exception as inner_exc:
            print(f"flag_npd_update_for_review failed for {msg_id}: {inner_exc}")
        send_whatsapp_message(
            sender, "We couldn't transcribe your voice note. Please try again or type "
                    "your update instead.",
        )
        return

    duration = transcript["duration"]
    if duration is not None and duration > MAX_AUDIO_SECONDS:
        print(
            f"NPD webhook: voice note from {sender} skipped — {duration:.0f}s over the "
            f"{MAX_AUDIO_SECONDS}s limit; transcript for reference: {transcript['text'][:300]!r}"
        )
        try:
            flag_npd_update_for_review(
                f"voice note too long ({duration:.0f}s)", transcript["text"], msg_id,
                source="whatsapp_voice", raw_transcript=transcript["text"],
            )
        except Exception as inner_exc:
            print(f"flag_npd_update_for_review failed for {msg_id}: {inner_exc}")
        send_whatsapp_message(
            sender, "That voice note is longer than 2 minutes. Please send a shorter "
                    "update or type it instead.",
        )
        return

    _process_npd_text(msg_id, sender, transcript["text"], source="whatsapp_voice", raw_transcript=transcript["text"])


def _process_npd_text(msg_id: str, sender: str, text: str, source: str, raw_transcript: str | None) -> None:
    """
    Shared by both the whatsapp_text and whatsapp_voice paths in
    handle_npd_message() — extract_npd_update -> fuzzy-match/create lead ->
    insert npd_updates -> reply, identical either way except which text and
    source/raw_transcript get passed in.
    """
    try:
        extracted = extract_npd_update(text)
        party_name = (extracted.get("party_name") or "").strip()
        stage_guess = extracted.get("stage_guess") if extracted.get("stage_guess") in NPD_STAGES else None
        next_follow_up = _parse_iso_date(extracted.get("next_follow_up_date"))
        update_summary = (extracted.get("update_summary") or text[:2000]).strip()

        if not party_name:
            flag_npd_update_for_review(
                "no party name identified", text, msg_id, next_follow_up,
                source=source, raw_transcript=raw_transcript,
            )
            send_whatsapp_message(
                sender, "Got your update but couldn't tell which party it's about — "
                        "flagged for manual review."
            )
            return

        matches = find_matching_npd_leads(party_name, threshold=NPD_MATCH_THRESHOLD)

        if len(matches) > 1:
            names = ", ".join(m["party_name"] for m in matches[:3])
            flag_npd_update_for_review(
                f"ambiguous party match: {names}", text, msg_id, next_follow_up,
                source=source, raw_transcript=raw_transcript,
            )
            send_whatsapp_message(
                sender, f"Found more than one similar party — {names}. Reply with the exact "
                        "party name to log this update."
            )
            return

        if matches:
            lead = matches[0]
            if stage_guess and stage_guess != lead["stage"]:
                update_npd_lead_stage(lead["id"], stage_guess)
        else:
            lead = create_npd_lead(party_name, stage_guess)

        insert_npd_update({
            "lead_id": lead["id"],
            "update_text": update_summary,
            "next_follow_up": next_follow_up,
            "source": source,
            "source_message_id": msg_id,
            "raw_transcript": raw_transcript,
        })

        follow_up_suffix = ""
        if next_follow_up:
            follow_up_suffix = f", next follow-up {datetime.strptime(next_follow_up, '%Y-%m-%d').strftime('%d %b')}"
        send_whatsapp_message(sender, f"Logged: {lead['party_name']} — {update_summary}{follow_up_suffix}")

    except Exception as exc:
        print(f"handle_npd_message failed for {msg_id}: {exc}")
        try:
            flag_npd_update_for_review("processing error", text, msg_id, source=source, raw_transcript=raw_transcript)
        except Exception as inner_exc:
            print(f"flag_npd_update_for_review also failed for {msg_id}: {inner_exc}")
        send_whatsapp_message(sender, "Something went wrong logging that update — flagged for manual review.")
