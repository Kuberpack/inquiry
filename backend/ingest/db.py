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
