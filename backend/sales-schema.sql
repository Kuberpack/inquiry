-- Sales Enquiry / Sales Quotation module.
-- Run this in the Supabase SQL editor AFTER schema.sql (references the
-- enquiries table). Adds company/item masters plus enquiry and quotation
-- documents with line items — a simplified subset of a typical ERP's
-- Lead Management module, built for the dashboard (anon key, no login,
-- same security model as enquiries).
--
-- Deliberately NOT included in v1 (add later only if actually needed):
-- inventory/stock tracking, GSTIN lookup-and-verify against a government
-- API, document amendments/revision history, bulk upload, reverse charge
-- (RCM) and non-taxable extra-charge line types.

-- ---------------------------------------------------------------------
-- Masters
-- ---------------------------------------------------------------------

create table if not exists companies (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    email           text,
    phone           text,
    role            text not null check (role in ('buyer', 'supplier', 'both')),
    gstin           text,
    gst_type        text not null default 'regular' check (gst_type in ('regular', 'composition', 'unregistered')),
    address_line1   text,
    address_line2   text,
    city            text,
    state           text,
    country         text not null default 'India',
    pincode         text,
    created_at      timestamptz not null default now()
);

create index if not exists idx_companies_role on companies (role);

create table if not exists items (
    id              uuid primary key default gen_random_uuid(),
    description     text not null,
    hsn_sac_code    text,
    unit            text not null default 'Nos',
    default_price   numeric(12, 2),
    created_at      timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- Sales Enquiry
-- ---------------------------------------------------------------------

create sequence if not exists sales_enquiry_seq start 1;

create table if not exists sales_enquiries (
    id                      uuid primary key default gen_random_uuid(),
    doc_number              text not null unique default ('SEQ' || lpad(nextval('sales_enquiry_seq')::text, 5, '0')),
    doc_date                date not null default current_date,

    buyer_id                uuid references companies(id),
    delivery_address        text,

    payment_term            text,
    poc_name                text,
    poc_contact             text,
    customer_enquiry_number text,
    customer_enquiry_date   date,
    expected_reply_date     date,
    kind_attention          text,

    status                  text not null default 'draft' check (status in ('draft', 'confirmed')),

    -- Set when this enquiry was created from a row in the Gmail/WhatsApp
    -- `enquiries` table via "Convert to Sales Enquiry".
    source_enquiry_id       uuid references enquiries(id),

    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

create index if not exists idx_sales_enquiries_status on sales_enquiries (status);
create index if not exists idx_sales_enquiries_buyer on sales_enquiries (buyer_id);

create table if not exists sales_enquiry_items (
    id                  uuid primary key default gen_random_uuid(),
    sales_enquiry_id    uuid not null references sales_enquiries(id) on delete cascade,
    item_id             uuid references items(id),
    description         text not null,
    quantity            numeric(12, 2) not null default 1,
    unit                text not null default 'Nos',
    price               numeric(12, 2) not null default 0,
    sort_order          int not null default 0
);

create index if not exists idx_sales_enquiry_items_enquiry on sales_enquiry_items (sales_enquiry_id);

-- ---------------------------------------------------------------------
-- Sales Quotation (converted from a Sales Enquiry, adds pricing/tax)
-- ---------------------------------------------------------------------

create sequence if not exists sales_quotation_seq start 1;

create table if not exists sales_quotations (
    id                  uuid primary key default gen_random_uuid(),
    doc_number          text not null unique default ('SQ' || lpad(nextval('sales_quotation_seq')::text, 5, '0')),
    doc_date            date not null default current_date,

    sales_enquiry_id    uuid references sales_enquiries(id),
    buyer_id            uuid references companies(id),
    delivery_address    text,

    payment_term        text,
    poc_name            text,
    poc_contact         text,

    discount_amount     numeric(12, 2) not null default 0,
    status              text not null default 'draft' check (status in ('draft', 'confirmed')),

    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

create index if not exists idx_sales_quotations_status on sales_quotations (status);
create index if not exists idx_sales_quotations_buyer on sales_quotations (buyer_id);
create index if not exists idx_sales_quotations_enquiry on sales_quotations (sales_enquiry_id);

create table if not exists sales_quotation_items (
    id                      uuid primary key default gen_random_uuid(),
    sales_quotation_id     uuid not null references sales_quotations(id) on delete cascade,
    item_id                 uuid references items(id),
    description             text not null,
    quantity                numeric(12, 2) not null default 1,
    unit                    text not null default 'Nos',
    price                   numeric(12, 2) not null default 0,
    tax_rate                numeric(5, 2) not null default 18, -- GST %, single combined rate (CGST+SGST or IGST)
    sort_order              int not null default 0
);

create index if not exists idx_sales_quotation_items_quotation on sales_quotation_items (sales_quotation_id);

-- ---------------------------------------------------------------------
-- Keep updated_at fresh (reuses the function created in schema.sql)
-- ---------------------------------------------------------------------

drop trigger if exists trg_sales_enquiries_updated_at on sales_enquiries;
create trigger trg_sales_enquiries_updated_at
    before update on sales_enquiries
    for each row
    execute function set_updated_at();

drop trigger if exists trg_sales_quotations_updated_at on sales_quotations;
create trigger trg_sales_quotations_updated_at
    before update on sales_quotations
    for each row
    execute function set_updated_at();

-- ---------------------------------------------------------------------
-- RLS — same permissive, single-internal-user model as enquiries
-- (dashboard connects with the anon/publishable key, no login).
-- ---------------------------------------------------------------------

alter table companies enable row level security;
alter table items enable row level security;
alter table sales_enquiries enable row level security;
alter table sales_enquiry_items enable row level security;
alter table sales_quotations enable row level security;
alter table sales_quotation_items enable row level security;

drop policy if exists "Allow anon all" on companies;
create policy "Allow anon all" on companies for all using (true) with check (true);

drop policy if exists "Allow anon all" on items;
create policy "Allow anon all" on items for all using (true) with check (true);

drop policy if exists "Allow anon all" on sales_enquiries;
create policy "Allow anon all" on sales_enquiries for all using (true) with check (true);

drop policy if exists "Allow anon all" on sales_enquiry_items;
create policy "Allow anon all" on sales_enquiry_items for all using (true) with check (true);

drop policy if exists "Allow anon all" on sales_quotations;
create policy "Allow anon all" on sales_quotations for all using (true) with check (true);

drop policy if exists "Allow anon all" on sales_quotation_items;
create policy "Allow anon all" on sales_quotation_items for all using (true) with check (true);

-- Required for the dashboard's real-time updates, same as enquiries.
alter publication supabase_realtime add table sales_enquiries;
alter publication supabase_realtime add table sales_quotations;
