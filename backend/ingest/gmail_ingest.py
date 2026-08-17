"""
Polls one or more Gmail accounts for new messages, extracts structured
fields via Groq, and writes them into the `enquiries` table.

Run this on a schedule (Task Scheduler / cron) every 2-5 minutes.

Setup required (one-time per Gmail account):
1. In Google Cloud Console, enable the Gmail API and create OAuth 2.0
   Desktop credentials. Download as `credentials.json` into this folder
   (this one file is shared across all accounts).
2. List every enquiry-receiving Gmail address in GMAIL_ACCOUNTS in .env,
   comma-separated.
3. First run will, for EACH account listed, open a browser to authorize —
   log in with that specific account when the browser opens. Each account
   gets its own saved token (token_<account>.json), so future runs are
   silent for all of them.
"""

import base64
import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from extraction import extract_fields
from db import upsert_enquiry

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CREDENTIALS_PATH = "credentials.json"

# Comma-separated list of every Gmail address that receives enquiries,
# e.g. GMAIL_ACCOUNTS=sales@kuberpack.com,info@kuberpack.com
# Falls back to a single default account (token.json) if not set.
GMAIL_ACCOUNTS = [a.strip() for a in os.environ.get("GMAIL_ACCOUNTS", "default").split(",") if a.strip()]

# Only pull mail matching this Gmail search query — narrow it to the inbox
# or label you actually want tracked (e.g. a label like "Enquiries").
GMAIL_QUERY = os.environ.get("GMAIL_QUERY", "is:unread")


def token_path_for(account: str) -> str:
    safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", account)
    return f"token_{safe_name}.json"


def get_gmail_service(account: str):
    token_path = token_path_for(account)
    creds = None
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print(f"\n--- Authorizing {account} — log in with THIS account in the browser window ---")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def get_header(headers: list[dict], name: str) -> str | None:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def get_message_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload, handling
    both simple and multipart messages."""
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")

    for part in payload.get("parts", []) or []:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")

    # Fall back to any nested parts (e.g. multipart/alternative inside multipart/mixed)
    for part in payload.get("parts", []) or []:
        text = get_message_body(part)
        if text:
            return text

    return ""


def poll_account(account: str) -> None:
    service = get_gmail_service(account)
    results = service.users().messages().list(userId="me", q=GMAIL_QUERY, maxResults=25).execute()
    messages = results.get("messages", [])

    if not messages:
        print(f"[{account}] No new messages.")
        return

    for msg_meta in messages:
        msg_id = msg_meta["id"]
        message = service.users().messages().get(userId="me", id=msg_id, format="full").execute()

        headers = message["payload"].get("headers", [])
        sender = get_header(headers, "From") or "unknown"
        subject = get_header(headers, "Subject") or ""
        body = get_message_body(message["payload"])
        full_text = f"Subject: {subject}\n\n{body}"

        received_at = datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=timezone.utc)

        extracted = extract_fields(full_text)

        record = {
            "source": "gmail",
            # Prefix with the account so message IDs can never collide across mailboxes
            "source_message_id": f"{account}:{msg_id}",
            "sender_name": sender,
            "sender_contact": sender,
            "raw_text": full_text[:5000],  # cap length for storage
            "received_at": received_at.isoformat(),
            "category": extracted.get("category"),
            "summary": extracted.get("summary"),
            "deadline": extracted.get("deadline"),
            "needs_deadline": extracted.get("needs_deadline", False),
            "priority": extracted.get("priority", "medium"),
        }

        upsert_enquiry(record)

        # Mark as read so this message isn't re-picked-up on the next poll
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()

        print(f"[{account}] Ingested: {subject[:60]}")


def poll_gmail() -> None:
    for account in GMAIL_ACCOUNTS:
        poll_account(account)


if __name__ == "__main__":
    poll_gmail()