# schema.md

Current Supabase (Postgres) schema. Source of truth is the SQL files —
this is a readable summary of them:

- `backend/schema.sql` — `enquiries`
- `dashboard/inquiry-dashboard-schema-update.sql` — additive changes to `enquiries`
- `backend/sales-schema.sql` — everything else (Sales module)

All tables use `uuid` primary keys (`gen_random_uuid()`) and have Row
Level Security enabled with permissive `using (true)` policies (anon-key
access, no per-user restriction — see `archi.md`).

---

## `enquiries`

The single table both Gmail and WhatsApp ingestion write into, and the
dashboard's main list reads/edits.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `source` | `text` | `'gmail'` \| `'whatsapp'` |
| `source_message_id` | `text` | Gmail/WhatsApp message id, for de-dup |
| `sender_name` | `text` | |
| `sender_contact` | `text` | email address or phone number |
| `raw_text` | `text` | original message, capped at 5000 chars on insert |
| `received_at` | `timestamptz` | |
| `category` | `text` | `'enquiry'` \| `'order'` \| `'complaint'` \| `'follow_up'` \| `'other'` (LLM-extracted) |
| `summary` | `text` | one-line LLM summary |
| `deadline` | `timestamptz` | nullable — LLM-extracted |
| `needs_deadline` | `boolean` | true if urgency implied but no deadline extracted |
| `priority` | `text` | `'low'` \| `'medium'` \| `'high'`, default `'medium'` |
| `status` | `text` | `'new'` \| `'in_progress'` \| `'done'`, default `'new'` |
| `assigned_to` | `text` | free text, no FK to a users table (none exists) |
| `notes` | `text` | free-text, added by the dashboard-schema-update migration |
| `created_at` | `timestamptz` | default `now()` |
| `updated_at` | `timestamptz` | auto-updated by `set_updated_at()` trigger on every row change |

**Constraints**: `unique (source, source_message_id)` — prevents the same
email/WhatsApp message being ingested twice.

**Indexes**: `(status, deadline)`, `(source)`.

**Realtime**: added to the `supabase_realtime` publication so the
dashboard updates live.

---

## Sales module

Added by `backend/sales-schema.sql`, run separately after `schema.sql`.
Purely additive — doesn't modify `enquiries`.

### `companies`

Buyer/supplier master.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `name` | `text` | not null |
| `email` | `text` | |
| `phone` | `text` | |
| `role` | `text` | `'buyer'` \| `'supplier'` \| `'both'` |
| `gstin` | `text` | |
| `gst_type` | `text` | `'regular'` \| `'composition'` \| `'unregistered'`, default `'regular'` |
| `address_line1` / `address_line2` | `text` | |
| `city` / `state` / `pincode` | `text` | |
| `country` | `text` | default `'India'` |
| `created_at` | `timestamptz` | |

Index: `(role)`.

### `items`

Product catalog.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `description` | `text` | not null |
| `hsn_sac_code` | `text` | |
| `unit` | `text` | default `'Nos'` |
| `default_price` | `numeric(12,2)` | nullable |
| `created_at` | `timestamptz` | |

### `sales_enquiries`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `doc_number` | `text` | unique, auto-generated `SEQ00001`, `SEQ00002`, … via `sales_enquiry_seq` |
| `doc_date` | `date` | default `current_date` |
| `buyer_id` | `uuid` | FK → `companies(id)` |
| `delivery_address` | `text` | |
| `payment_term` | `text` | |
| `poc_name` / `poc_contact` | `text` | |
| `customer_enquiry_number` | `text` | |
| `customer_enquiry_date` | `date` | |
| `expected_reply_date` | `date` | |
| `kind_attention` | `text` | |
| `status` | `text` | `'draft'` \| `'confirmed'` |
| `source_enquiry_id` | `uuid` | FK → `enquiries(id)`, set when created via "Convert to Sales Enquiry" |
| `created_at` / `updated_at` | `timestamptz` | `updated_at` auto-updated by trigger |

Indexes: `(status)`, `(buyer_id)`.

### `sales_enquiry_items`

Line items for a Sales Enquiry.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `sales_enquiry_id` | `uuid` | FK → `sales_enquiries(id)`, `on delete cascade` |
| `item_id` | `uuid` | FK → `items(id)` |
| `description` | `text` | not null |
| `quantity` | `numeric(12,2)` | default `1` |
| `unit` | `text` | default `'Nos'` |
| `price` | `numeric(12,2)` | default `0` |
| `sort_order` | `int` | default `0` |

Index: `(sales_enquiry_id)`.

### `sales_quotations`

Converted from a confirmed Sales Enquiry; adds pricing/discount.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `doc_number` | `text` | unique, auto-generated `SQ00001`, `SQ00002`, … via `sales_quotation_seq` |
| `doc_date` | `date` | default `current_date` |
| `sales_enquiry_id` | `uuid` | FK → `sales_enquiries(id)` |
| `buyer_id` | `uuid` | FK → `companies(id)` |
| `delivery_address` | `text` | |
| `payment_term` | `text` | |
| `poc_name` / `poc_contact` | `text` | |
| `discount_amount` | `numeric(12,2)` | default `0` |
| `status` | `text` | `'draft'` \| `'confirmed'` |
| `created_at` / `updated_at` | `timestamptz` | `updated_at` auto-updated by trigger |

Indexes: `(status)`, `(buyer_id)`, `(sales_enquiry_id)`.

### `sales_quotation_items`

Line items for a Sales Quotation — same shape as enquiry items plus tax.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `sales_quotation_id` | `uuid` | FK → `sales_quotations(id)`, `on delete cascade` |
| `item_id` | `uuid` | FK → `items(id)` |
| `description` | `text` | not null |
| `quantity` | `numeric(12,2)` | default `1` |
| `unit` | `text` | default `'Nos'` |
| `price` | `numeric(12,2)` | default `0` |
| `tax_rate` | `numeric(5,2)` | default `18` — single combined GST % (CGST+SGST or IGST, split at query time) |
| `sort_order` | `int` | default `0` |

Index: `(sales_quotation_id)`.

**Realtime**: `sales_enquiries` and `sales_quotations` are both added to
the `supabase_realtime` publication (their line-item tables are not).

---

## GST calc (not stored, computed client-side)

`dashboard/src/sales/salesClient.js` computes totals at read time from
`sales_quotation_items`, not stored as columns:

- `SUPPLIER_STATE` constant (currently `'Maharashtra'`) — Kuberpack's own
  registered state.
- If the buyer's `state` matches `SUPPLIER_STATE`: split each line's tax
  into CGST + SGST (half each).
- Otherwise: full line tax goes to IGST.
- **Known open question**: tax is computed on each line's full
  (undiscounted) value; `discount_amount` is subtracted once at the
  grand-total level rather than reducing the taxable base. Flagged in
  `todo.md` as unconfirmed against actual company policy.

## Explicitly out of scope (v1)

Per the comment block at the top of `sales-schema.sql`: no
inventory/stock tables, no GSTIN-verification data, no amendment/revision
history tables, no bulk-upload staging tables, no RCM or non-taxable
extra-charge line types. Add only if actually needed later.

---

## NPD module

Added by `backend/npd-schema.sql` (**draft — not yet applied to
Supabase**, pending sign-off). Purely additive — doesn't modify
`enquiries` or the Sales module tables. Tracks New Product Development
leads and the WhatsApp/manual updates logged against them.

### `npd_leads`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `party_name` | `text` | not null |
| `contact_person` | `text` | |
| `contact_phone` | `text` | |
| `stage` | `text` | not null, default `'New Lead'` — see stage list below |
| `potential_volume` | `text` | |
| `created_at` / `updated_at` | `timestamptz` | `updated_at` auto-updated by trigger |

Indexes: `(stage)`, plus a `pg_trgm` GIN trigram index on `party_name` for
fuzzy-matching an inbound message's party name against existing leads at
any table size, without a Python-side scan.

**`stage` values — single source of truth.** Enforced by a `check`
constraint on `npd_leads.stage`. Phase 3 (Groq extraction's
`stage_guess`) and Phase 6 (dashboard Kanban columns) both reuse this
exact list — pull from here, don't redefine it elsewhere, so the DB
constraint, the LLM prompt, and the UI can't drift apart:

1. `New Lead`
2. `In Progress (Samples/Rates)`
3. `Awaiting Response`
4. `Rate Negotiation`
5. `On Hold`
6. `Active/Won`
7. `Rate Mismatch (Lost)`

### `npd_updates`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `lead_id` | `uuid` | FK → `npd_leads(id)`, `on delete cascade`, not null |
| `update_text` | `text` | not null |
| `update_date` | `timestamptz` | not null, default `now()` |
| `next_follow_up` | `date` | nullable |
| `source` | `text` | not null, `'whatsapp_text'` \| `'whatsapp_voice'` \| `'manual'`, no default (always set explicitly, same as `enquiries.source`) |
| `source_message_id` | `text` | nullable — WhatsApp message id, for de-dup |
| `raw_transcript` | `text` | nullable — original Whisper-style transcript, only set for `'whatsapp_voice'` |
| `created_at` | `timestamptz` | default `now()` |

**Constraints**: partial `unique (source_message_id) where
source_message_id is not null` — dedups webhook retries the same way
`enquiries` does, without blocking manual entries that have no source
message.

Indexes: `(lead_id)`, `(update_date)`.

**Realtime**: `npd_leads` and `npd_updates` are both added to the
`supabase_realtime` publication.
