-- Unified inquiry table for Gmail + WhatsApp enquiries
-- Run this in the Supabase SQL editor (or any Postgres instance) to set up.

create table if not exists enquiries (
    id                  uuid primary key default gen_random_uuid(),

    -- Source tracking
    source              text not null check (source in ('gmail', 'whatsapp')),
    source_message_id   text not null,          -- Gmail message id / WhatsApp message id (for de-duplication)

    -- Who it's from
    sender_name         text,
    sender_contact       text,                   -- email address or phone number

    -- Raw content
    raw_text            text not null,
    received_at         timestamptz not null,

    -- LLM-extracted fields
    category            text,                   -- e.g. 'enquiry', 'order', 'complaint', 'other'
    summary             text,                   -- one-line summary
    deadline            timestamptz,             -- extracted deadline, null if none found
    needs_deadline      boolean not null default false,  -- true if message implies urgency but no clear deadline was extracted
    priority            text check (priority in ('low', 'medium', 'high')) default 'medium',

    -- Workflow / status
    status              text not null default 'new' check (status in ('new', 'in_progress', 'done')),
    assigned_to         text,

    -- Bookkeeping
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),

    unique (source, source_message_id)          -- prevents the same email/WhatsApp message being inserted twice
);

-- Speeds up the dashboard's main queries: "show me open items sorted by deadline"
create index if not exists idx_enquiries_status_deadline on enquiries (status, deadline);
create index if not exists idx_enquiries_source on enquiries (source);

-- Keep updated_at fresh automatically on every row change
create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_enquiries_updated_at on enquiries;
create trigger trg_enquiries_updated_at
    before update on enquiries
    for each row
    execute function set_updated_at();
