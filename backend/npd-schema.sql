-- New Product Development (NPD) leads pipeline.
-- Run this in the Supabase SQL editor AFTER schema.sql (reuses the
-- set_updated_at() trigger function created there). Purely additive —
-- doesn't modify enquiries or the Sales module tables.
--
-- Feeds two places: a future NPD dashboard view (anon key, no login, same
-- security model as enquiries) and whatsapp_webhook.py, which will route
-- inbound messages from a dedicated WhatsApp number (NPD_PHONE_NUMBER_ID)
-- into npd_updates instead of enquiries.

create extension if not exists pg_trgm;

-- ---------------------------------------------------------------------
-- npd_leads
-- ---------------------------------------------------------------------

create table if not exists npd_leads (
    id                  uuid primary key default gen_random_uuid(),
    party_name          text not null,
    contact_person      text,
    contact_phone       text,
    stage               text not null default 'New Lead' check (stage in (
                             'New Lead',
                             'In Progress (Samples/Rates)',
                             'Awaiting Response',
                             'Rate Negotiation',
                             'On Hold',
                             'Active/Won',
                             'Rate Mismatch (Lost)'
                         )),
    potential_volume    text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists idx_npd_leads_stage on npd_leads (stage);

-- Trigram GIN index so "which existing lead is this WhatsApp message
-- about" can be a fuzzy-matched query (pg_trgm % / similarity()) at any
-- table size, instead of pulling every lead into Python and diffing
-- strings in a loop.
create index if not exists idx_npd_leads_party_name_trgm
    on npd_leads using gin (party_name gin_trgm_ops);

-- ---------------------------------------------------------------------
-- npd_updates
-- ---------------------------------------------------------------------

create table if not exists npd_updates (
    id                  uuid primary key default gen_random_uuid(),
    -- Nullable: Phase 3 (handle_npd_message) inserts a lead_id-less row,
    -- flagged via needs_review, when it can't confidently identify or
    -- disambiguate a party — keeps the raw message instead of dropping it.
    lead_id             uuid references npd_leads(id) on delete cascade,
    update_text         text not null,
    update_date         timestamptz not null default now(),
    next_follow_up      date,
    source              text not null check (source in ('whatsapp_text', 'whatsapp_voice', 'manual')),
    source_message_id   text,
    raw_transcript      text,
    needs_review        boolean not null default false,
    created_at          timestamptz not null default now()
);

create index if not exists idx_npd_updates_lead_id on npd_updates (lead_id);
create index if not exists idx_npd_updates_update_date on npd_updates (update_date);

-- Fast lookup for the dashboard's "needs manual review" queue. Partial
-- because needs_review=true rows are expected to be a small minority.
create index if not exists idx_npd_updates_needs_review
    on npd_updates (needs_review)
    where needs_review;

-- Dedup for webhook retries, same pattern as enquiries.source_message_id.
-- Partial (not a plain unique column) because manual dashboard entries
-- have no source message to key off. NOTE: because this is a partial
-- index, backend code must dedup with a plain SELECT-then-INSERT rather
-- than an upsert(on_conflict=...) — PostgREST's ON CONFLICT target can't
-- express the partial index's WHERE predicate, so a naive upsert() 400s.
create unique index if not exists idx_npd_updates_source_message_id
    on npd_updates (source_message_id)
    where source_message_id is not null;

-- ---------------------------------------------------------------------
-- match_npd_leads — fuzzy party-name lookup for handle_npd_message()
-- ---------------------------------------------------------------------
-- Used instead of pulling every lead into Python and diffing strings in
-- a loop, so matching stays fast as the lead count grows. The `%`
-- operator (rather than a bare similarity() > threshold predicate) is
-- what lets Postgres use idx_npd_leads_party_name_trgm; setting
-- pg_trgm.similarity_threshold makes that operator honor match_threshold
-- for this call instead of the default (0.3). Uses set_config(..., true)
-- rather than pg_trgm's own set_limit() because set_limit() changes the
-- setting for the whole session — on a pooled connection (PgBouncer/
-- Supavisor, which Supabase sits behind) that session outlives this
-- function call, so it would leak match_threshold into whatever
-- unrelated request happens to reuse the same pooled connection next.
-- set_config's third argument (is_local = true) scopes the change to
-- the current transaction only; it's reverted automatically on commit.
create or replace function match_npd_leads(
    search_name text,
    match_threshold real default 0.35,
    match_count int default 5
)
returns table (id uuid, party_name text, stage text, similarity real)
language plpgsql
as $$
begin
    perform set_config('pg_trgm.similarity_threshold', match_threshold::text, true);
    return query
        select l.id, l.party_name, l.stage, similarity(l.party_name, search_name) as similarity
        from npd_leads l
        where l.party_name % search_name
        order by similarity desc
        limit match_count;
end;
$$;

-- ---------------------------------------------------------------------
-- Keep updated_at fresh (reuses the function created in schema.sql)
-- ---------------------------------------------------------------------

drop trigger if exists trg_npd_leads_updated_at on npd_leads;
create trigger trg_npd_leads_updated_at
    before update on npd_leads
    for each row
    execute function set_updated_at();

-- ---------------------------------------------------------------------
-- RLS — same permissive, single-internal-user model as enquiries
-- (dashboard connects with the anon/publishable key, no login).
-- ---------------------------------------------------------------------

alter table npd_leads enable row level security;
alter table npd_updates enable row level security;

drop policy if exists "Allow anon all" on npd_leads;
create policy "Allow anon all" on npd_leads for all using (true) with check (true);

drop policy if exists "Allow anon all" on npd_updates;
create policy "Allow anon all" on npd_updates for all using (true) with check (true);

-- Required for the dashboard's real-time updates, same as enquiries.
alter publication supabase_realtime add table npd_leads;
alter publication supabase_realtime add table npd_updates;
