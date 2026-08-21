"""
Thin wrapper around the Supabase client for writing enquiry records.
"""

import os

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


def insert_npd_update(record: dict) -> dict:
    """
    Plain insert, not upsert — idx_npd_updates_source_message_id is a
    partial unique index (see npd-schema.sql), and PostgREST's
    upsert(on_conflict=...) can't target a partial index, so it would
    400 here. Callers are expected to have already deduped via
    get_npd_update_by_message_id() before calling this.
    """
    client = get_client()
    response = client.table("npd_updates").insert(record).execute()
    return response.data[0]


def flag_npd_update_for_review(reason: str, raw_text: str, source_message_id: str,
                                next_follow_up: str | None = None) -> dict:
    """
    Records a WhatsApp NPD message that couldn't be confidently linked to
    a lead (no party name extracted, an ambiguous match, or a processing
    error) — lead_id left null, needs_review=true — instead of losing it.
    """
    record = {
        "lead_id": None,
        "update_text": f"[NEEDS REVIEW: {reason}] {raw_text[:2000]}",
        "next_follow_up": next_follow_up,
        "source": "whatsapp_text",
        "source_message_id": source_message_id,
        "needs_review": True,
    }
    return insert_npd_update(record)
