"""
Flags NPD leads that haven't had a follow-up in a while and sends one
WhatsApp summary message to the internal team so stale leads don't get
silently forgotten. Run once a day (see deploy/npd-reminders.cron),
shortly after daily_digest.py.

Reuses send_whatsapp_message() from whatsapp_webhook.py, so reminders go
out through the same Meta Graph API call (and the same NPD WhatsApp
number, NPD_PHONE_NUMBER_ID) as NPD update confirmations/clarifications —
importing it also means this script inherits whatsapp_webhook.py's
import-time requirement on NPD_PHONE_NUMBER_ID (and, transitively via
extraction.py, GROQ_API_KEY) even though neither is otherwise used here.
"""

import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv()

from db import fetch_leads_for_staleness_check
from whatsapp_webhook import send_whatsapp_message

STALE_DAYS_THRESHOLD = int(os.environ.get("STALE_DAYS_THRESHOLD", "10"))
INTERNAL_TEAM_NUMBERS = [n.strip() for n in os.environ.get("INTERNAL_TEAM_NUMBERS", "").split(",") if n.strip()]


def _reference_point(lead: dict) -> datetime:
    """Most recent npd_updates.update_date for this lead, or npd_leads.created_at
    if it has never had one — see fetch_leads_for_staleness_check()."""
    updates = lead.get("npd_updates") or []
    raw = updates[0]["update_date"] if updates else lead["created_at"]
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def find_stale_leads() -> list[dict]:
    """
    Returns {party_name, stage, days_since_contact} for every lead whose
    reference point (see _reference_point) is more than STALE_DAYS_THRESHOLD
    days old, sorted most-stale first. Excludes leads already filtered out
    by fetch_leads_for_staleness_check() (terminal stages). A bad row
    (missing/malformed timestamp) is logged and skipped rather than
    crashing the whole run — fail open, per CLAUDE.md.
    """
    now = datetime.now(timezone.utc)
    threshold = timedelta(days=STALE_DAYS_THRESHOLD)
    stale = []

    for lead in fetch_leads_for_staleness_check():
        try:
            age = now - _reference_point(lead)
            if age > threshold:
                stale.append({
                    "party_name": lead["party_name"],
                    "stage": lead["stage"],
                    "days_since_contact": age.days,
                })
        except Exception as exc:
            print(f"npd_reminders: skipping lead {lead.get('id')!r} — bad data: {exc}")

    stale.sort(key=lambda l: l["days_since_contact"], reverse=True)
    return stale


def build_message(stale_leads: list[dict]) -> str:
    lines = [f"NPD stale leads ({len(stale_leads)}) — no contact in over {STALE_DAYS_THRESHOLD} days:"]
    for lead in stale_leads:
        lines.append(f"- {lead['party_name']} — {lead['days_since_contact']}d — {lead['stage']}")
    return "\n".join(lines)


def send_reminders() -> None:
    if not INTERNAL_TEAM_NUMBERS:
        print("INTERNAL_TEAM_NUMBERS is not set — nothing to send to.")
        return

    stale_leads = find_stale_leads()
    if not stale_leads:
        # No "all clear" message: this runs daily and silence already means
        # "nothing stale" — a confirmation every single day is noise, not
        # signal, and would train the team to skim past every NPD WhatsApp
        # message including the ones that actually matter.
        print("No stale NPD leads today.")
        return

    message = build_message(stale_leads)
    for number in INTERNAL_TEAM_NUMBERS:
        try:
            send_whatsapp_message(number, message)
        except Exception as exc:
            # send_whatsapp_message already catches its own failures, but this
            # loop can't let one bad number (or an unexpected exception it
            # doesn't catch) stop the reminder from reaching the rest.
            print(f"npd_reminders: failed to send to {number}: {exc}")


if __name__ == "__main__":
    send_reminders()
