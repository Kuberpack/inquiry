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
    lead_id             uuid not null references npd_leads(id) on delete cascade,
    update_text         text not null,
    update_date         timestamptz not null default now(),
    next_follow_up      date,
    source              text not null check (source in ('whatsapp_text', 'whatsapp_voice', 'manual')),
    source_message_id   text,
    raw_transcript      text,
    created_at          timestamptz not null default now()
);

create index if not exists idx_npd_updates_lead_id on npd_updates (lead_id);
create index if not exists idx_npd_updates_update_date on npd_updates (update_date);

-- Dedup for webhook retries, same pattern as enquiries.source_message_id.
-- Partial (not a plain unique column) because manual dashboard entries
-- have no source message to key off.
create unique index if not exists idx_npd_updates_source_message_id
    on npd_updates (source_message_id)
    where source_message_id is not null;

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
