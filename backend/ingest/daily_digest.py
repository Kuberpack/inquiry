"""
Sends one daily email summarizing enquiries that need attention: overdue,
due within 2 days, or missing a deadline entirely. Run once a day on a
schedule (see .github/workflows/daily-digest.yml).

Reuses the same Gmail OAuth token as gmail_ingest.py (DIGEST_FROM_ACCOUNT
must be one of the accounts already authorized there — see backend/README.md)
and the same Supabase service-role access as db.py. No new setup beyond
setting DIGEST_FROM_ACCOUNT and DIGEST_RECIPIENTS in .env.
"""

import base64
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText

from dotenv import load_dotenv
load_dotenv()

from gmail_ingest import get_gmail_service
from db import get_client

DIGEST_FROM_ACCOUNT = os.environ.get("DIGEST_FROM_ACCOUNT")
DIGEST_RECIPIENTS = [a.strip() for a in os.environ.get("DIGEST_RECIPIENTS", "").split(",") if a.strip()]
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")

DUE_SOON_DAYS = 2


def fetch_open_enquiries() -> list[dict]:
    """Everything not done that's either overdue or flagged as needing a deadline."""
    client = get_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    resp = (
        client.table("enquiries")
        .select("*")
        .neq("status", "done")
        .or_(f"deadline.lt.{now_iso},needs_deadline.eq.true")
        .order("deadline")
        .execute()
    )
    return resp.data or []


def parse_deadline(deadline: str) -> datetime:
    dl = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    if dl.tzinfo is None:
        dl = dl.replace(tzinfo=timezone.utc)
    return dl


def categorize(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    now = datetime.now(timezone.utc)
    overdue, due_soon, flagged = [], [], []
    for r in rows:
        deadline = r.get("deadline")
        if deadline:
            diff_days = (parse_deadline(deadline) - now).total_seconds() / 86400
            if diff_days < 0:
                overdue.append(r)
            elif diff_days <= DUE_SOON_DAYS:
                due_soon.append(r)
        elif r.get("needs_deadline"):
            flagged.append(r)
    return overdue, due_soon, flagged


def format_section(title: str, rows: list[dict]) -> str:
    if not rows:
        return ""
    header = f"{title} ({len(rows)})"
    lines = [header, "-" * len(header)]
    for r in rows:
        who = r.get("assigned_to") or "Unassigned"
        sender = r.get("sender_name") or "Unknown sender"
        summary = r.get("summary") or "(no summary)"
        deadline = (r.get("deadline") or "")[:10] or "no deadline"
        lines.append(f"- [{who}] {sender} — {summary} (deadline: {deadline})")
    return "\n".join(lines)


def build_body(overdue: list[dict], due_soon: list[dict], flagged: list[dict]) -> str:
    total = len(overdue) + len(due_soon) + len(flagged)
    if total == 0:
        return "No overdue, due-soon, or undated enquiries right now. Nothing needs attention today."

    sections = [
        format_section("OVERDUE", overdue),
        format_section(f"DUE WITHIN {DUE_SOON_DAYS} DAYS", due_soon),
        format_section("NO DEADLINE FOUND", flagged),
    ]
    body = "\n\n".join(s for s in sections if s)
    if DASHBOARD_URL:
        body = f"Dashboard: {DASHBOARD_URL}\n\n{body}"
    return body


def send_email(service, to_addrs: list[str], subject: str, body: str) -> None:
    message = MIMEText(body)
    message["to"] = ", ".join(to_addrs)
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def send_digest() -> None:
    if not DIGEST_RECIPIENTS:
        print("DIGEST_RECIPIENTS is not set — nothing to send to.")
        return
    if not DIGEST_FROM_ACCOUNT:
        print("DIGEST_FROM_ACCOUNT is not set — don't know which Gmail account to send from.")
        return

    rows = fetch_open_enquiries()
    overdue, due_soon, flagged = categorize(rows)

    today = datetime.now(timezone.utc).strftime("%d %b %Y")
    subject = (
        f"Enquiry digest {today} — {len(overdue)} overdue, "
        f"{len(due_soon)} due soon, {len(flagged)} undated"
    )
    body = build_body(overdue, due_soon, flagged)

    service = get_gmail_service(DIGEST_FROM_ACCOUNT)
    send_email(service, DIGEST_RECIPIENTS, subject, body)
    print(f"Sent digest to {', '.join(DIGEST_RECIPIENTS)}.")


if __name__ == "__main__":
    send_digest()
