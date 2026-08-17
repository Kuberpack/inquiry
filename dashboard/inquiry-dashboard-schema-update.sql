-- Run this in the Supabase SQL editor before using the dashboard.

-- Add a free-text notes field (not in the original schema)
alter table enquiries add column if not exists notes text;

-- The dashboard has no login (single internal user), so it connects with the
-- publishable/anon key. If Row Level Security is still enabled on the table,
-- add permissive policies so the dashboard can read and update rows.
-- (Skip this block if you already ran `alter table enquiries disable row level security;` earlier.)

alter table enquiries enable row level security;

drop policy if exists "Allow anon read" on enquiries;
create policy "Allow anon read" on enquiries
    for select using (true);

drop policy if exists "Allow anon update" on enquiries;
create policy "Allow anon update" on enquiries
    for update using (true);

-- Required for the dashboard's real-time updates (Supabase Realtime broadcasts
-- row changes to subscribed clients only for tables in this publication).
-- Safe to run even if the table is already in the publication.
alter publication supabase_realtime add table enquiries;
