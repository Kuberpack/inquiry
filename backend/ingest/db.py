"""
Thin wrapper around the Supabase client for writing enquiry and NPD records.
"""

import os

from postgrest.exceptions import APIError
from supabase import Client, create_client

_supabase: Client | None = None


def get_client() -> Client:
    global _supabase
    if _supabase is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_KEY"]  # service key, not anon key — needed for server-side writes
        _supabase = create_client(url, key)
    return _supabase


def upsert_enquiry(record: dict) -> None:
    """
    Insert a new enquiry, or silently skip if this exact source message
    was already ingested (relies on the unique(source, source_message_id)
    constraint in schema.sql).
    """
    client = get_client()
    client.table("enquiries").upsert(
        record,
        on_conflict="source,source_message_id",
        ignore_duplicates=True,
    ).execute()


def get_npd_update_by_message_id(source_message_id: str) -> dict | None:
    """
    Looks up an existing npd_updates row by source_message_id (indexed —
    see idx_npd_updates_source_message_id). Used to dedup WhatsApp
    webhook retries *before* doing any Groq/matching work, so a retry
    can't create a second npd_leads row or send a second confirmation.
    """
    client = get_client()
    response = (
        client.table("npd_updates")
        .select("id, lead_id")
        .eq("source_message_id", source_message_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def find_matching_npd_leads(party_name: str, threshold: float = 0.35, limit: int = 5) -> list[dict]:
    """
    Fuzzy-matches party_name against npd_leads.party_name via the
    match_npd_leads() Postgres function (pg_trgm, GIN-indexed) — a single
    DB round trip regardless of how many leads exist, rather than
    pulling every lead into Python and diffing strings in a loop.
    """
    client = get_client()
    response = client.rpc(
        "match_npd_leads",
        {"search_name": party_name, "match_threshold": threshold, "match_count": limit},
    ).execute()
    return response.data or []


def create_npd_lead(party_name: str, stage: str | None = None) -> dict:
    client = get_client()
    record = {"party_name": party_name}
    if stage:
        record["stage"] = stage
    response = client.table("npd_leads").insert(record).execute()
    return response.data[0]


def update_npd_lead_stage(lead_id: str, stage: str) -> None:
    client = get_client()
    client.table("npd_leads").update({"stage": stage}).eq("id", lead_id).execute()


def insert_npd_update(record: dict) -> dict | None:
    """
    Plain insert, not upsert — idx_npd_updates_source_message_id is a
    partial unique index (see npd-schema.sql), and PostgREST's
    upsert(on_conflict=...) can't target a partial index, so it would
    400 here. Callers are expected to have already deduped via
    get_npd_update_by_message_id() before calling this — but that check
    and this insert aren't atomic, so two BackgroundTasks racing on the
    same source_message_id (e.g. Meta redelivering a webhook) can both
    pass the dedup check before either has inserted. That's an expected
    outcome of acking Meta immediately and processing async, not an
    error: the loser hits this same unique constraint, and rather than
    raising into the caller's generic error handling — which would
    misfile it as needs_review and send the sender a confusing second
    reply on top of the winner's already-successful one — it's treated
    as a no-op and returns None.
    """
    client = get_client()
    try:
        response = client.table("npd_updates").insert(record).execute()
    except APIError as exc:
        if exc.code == "23505":  # unique_violation — a concurrent duplicate, not a failure
            return None
        raise
    return response.data[0]


# Leads in these stages are done (won or lost) — no further follow-up is
# expected, so they're excluded from the staleness check regardless of age.
NPD_STALE_CHECK_EXCLUDED_STAGES = ["Active/Won", "Rate Mismatch (Lost)"]


def fetch_leads_for_staleness_check() -> list[dict]:
    """
    One request: every npd_leads row not in a terminal stage, each with
    only its single most recent npd_updates row embedded (PostgREST
    applies the .order()/.limit(foreign_table=...) as a per-parent lateral
    query) — a lead with zero updates comes back with an empty list rather
    than being dropped. This avoids pulling every lead's full update
    history (or looping query-per-lead) into Python just to find the
    latest one: the embedded lookup uses idx_npd_updates_lead_id to find
    only that lead's rows and idx_npd_updates_update_date to pick the most
    recent, same as the top-N-per-group EXPLAIN plan.
    """
    client = get_client()
    response = (
        client.table("npd_leads")
        .select("id, party_name, stage, created_at, npd_updates(update_date)")
        .not_.in_("stage", NPD_STALE_CHECK_EXCLUDED_STAGES)
        .order("update_date", desc=True, foreign_table="npd_updates")
        .limit(1, foreign_table="npd_updates")
        .execute()
    )
    return response.data or []


def flag_npd_update_for_review(reason: str, raw_text: str, source_message_id: str,
                                next_follow_up: str | None = None,
                                source: str = "whatsapp_text",
                                raw_transcript: str | None = None) -> dict | None:
    """
    Records a WhatsApp NPD message that couldn't be confidently linked to
    a lead (no party name extracted, an ambiguous match, an over-limit
    voice note, or a processing error) — lead_id left null, needs_review=
    true — instead of losing it. source/raw_transcript let a skipped
    whatsapp_voice message keep its transcript for audit, same as a
    successfully-linked one would via insert_npd_update().
    """
    record = {
        "lead_id": None,
        "update_text": f"[NEEDS REVIEW: {reason}] {raw_text[:2000]}",
        "next_follow_up": next_follow_up,
        "source": source,
        "source_message_id": source_message_id,
        "raw_transcript": raw_transcript,
        "needs_review": True,
    }
    return insert_npd_update(record)
