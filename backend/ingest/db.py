"""
Thin wrapper around the Supabase client for writing enquiry and NPD records.
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


def _find_or_create_npd_lead(
    party_name: str, stage_guess: str | None, contact_person: str | None, potential_volume: str | None
) -> dict:
    client = get_client()

    exact = (
        client.table("npd_leads")
        .select("id,party_name,stage")
        .ilike("party_name", party_name)
        .limit(1)
        .execute()
    )
    if exact.data:
        return exact.data[0]

    # party_name gets a GIN trigram index specifically so this can be an ILIKE
    # index scan instead of pulling every lead into Python to diff strings —
    # see idx_npd_leads_party_name_trgm in npd-schema.sql. This only catches
    # same-substring variants, not typo/phonetic ones (that needs a
    # similarity()-based RPC, not exposed by supabase-py's filter API — revisit
    # if substring matching proves too weak in practice). Guarded to names of
    # at least 4 chars so a short/garbled guess doesn't wildcard-match everything.
    if len(party_name) >= 4:
        fuzzy = (
            client.table("npd_leads")
            .select("id,party_name,stage")
            .ilike("party_name", f"%{party_name}%")
            .limit(1)
            .execute()
        )
        if fuzzy.data:
            return fuzzy.data[0]

    created = (
        client.table("npd_leads")
        .insert(
            {
                "party_name": party_name,
                "stage": stage_guess or "New Lead",
                "contact_person": contact_person,
                "potential_volume": potential_volume,
            }
        )
        .execute()
    )
    return created.data[0]


def upsert_npd_update(
    party_name: str,
    stage_guess: str | None,
    contact_person: str | None,
    potential_volume: str | None,
    update: dict,
) -> None:
    """
    Matches (or creates) the npd_leads row this update is about, inserts the
    npd_updates row against it (skipping if source_message_id was already
    ingested, same dedup pattern as upsert_enquiry), and advances the lead's
    stage if the extraction confidently guessed a new one.
    """
    lead = _find_or_create_npd_lead(party_name, stage_guess, contact_person, potential_volume)

    client = get_client()
    update["lead_id"] = lead["id"]
    client.table("npd_updates").upsert(
        update,
        on_conflict="source_message_id",
        ignore_duplicates=True,
    ).execute()

    if stage_guess and stage_guess != lead["stage"]:
        client.table("npd_leads").update({"stage": stage_guess}).eq("id", lead["id"]).execute()
