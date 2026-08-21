# archi.md

Tech stack and deployment architecture summary.

## Overview

A monorepo (`kuberpack/inquiry`) with two halves that share one Supabase
database:

- **`backend/`** — Python scripts that pull messages from Gmail (and
  eventually WhatsApp) into a single `enquiries` table, using an LLM to
  extract structured fields. Runs as scheduled GitHub Actions, not a
  long-running server (except the WhatsApp webhook, which isn't deployed
  yet).
- **`dashboard/`** — a React/Vite single-page app deployed to Vercel that
  reads and edits `enquiries`, plus a Sales Enquiry/Sales Quotation module
  on its own tables.

## Data flow

```
Gmail inbox(es)                WhatsApp Business API
      |                                |
      v                                v
 gmail_ingest.py               whatsapp_webhook.py
 (GitHub Actions,               (FastAPI — not yet
  every 15 min)                  deployed publicly)
      |                                |
      +----------------+---------------+
                       |
                 extraction.py
            (Groq API: category, summary,
             deadline, priority,
             is_business_relevant)
                       |
                       v
              Supabase (Postgres)
              `enquiries` table
                       |
        +--------------+---------------+
        |                               |
        v                               v
  React dashboard                daily_digest.py
  (Vercel, reads/writes            (GitHub Actions,
   via anon key)                    09:00 IST — emails
        |                            overdue/undated
        v                            summary via Gmail)
  "Convert to Sales Enquiry"
        |
        v
  Sales Enquiry / Sales Quotation
  tables (companies, items,
  sales_enquiries(_items),
  sales_quotations(_items))
```

## Backend

- **Language/runtime**: Python 3.12, no framework except FastAPI for the
  (not-yet-deployed) WhatsApp webhook.
- **Scheduling**: GitHub Actions, not a persistent server —
  `check-mail.yml` runs `gmail_ingest.py` every 15 minutes;
  `daily-digest.yml` runs `daily_digest.py` once a day at 09:00 IST.
  Both write Google OAuth credentials from repo secrets into the runner's
  filesystem at the start of each run.
- **LLM extraction**: Groq API. Model is configurable via `GROQ_MODEL`
  (defaults to `openai/gpt-oss-120b`), read at runtime in
  `extraction.py`. Groq periodically retires model IDs — this is why the
  model is env-configurable rather than hardcoded.
- **Auth to Gmail**: OAuth2, one token per account (`token_<account>.json`),
  supports multiple mailboxes via `GMAIL_ACCOUNTS`.
- **Auth to Supabase**: `service_role` key (full write access), stored as
  a GitHub Actions secret — never exposed to the frontend.
- **Mail filtering**: two layers — an LLM relevance classification
  (`is_business_relevant`) that runs on every message regardless of
  source, plus an optional per-account Gmail query override
  (`GMAIL_QUERY_OVERRIDES`) to scope a mixed personal/business inbox to a
  label before it's even fetched.
- **WhatsApp routing**: one webhook, two WhatsApp Business numbers.
  `whatsapp_webhook.py` reads `metadata.phone_number_id` off each inbound
  payload and compares it to `NPD_PHONE_NUMBER_ID` (required env var) —
  a match routes to `handle_npd_message()` (stub, pending `npd_leads`/
  `npd_updates` — see `schema.md`), anything else keeps going through the
  existing customer-enquiry path into `enquiries`.
- **Webhook processing model**: `receive_message()` acks Meta with `200`
  immediately and hands each message to a FastAPI `BackgroundTask` for
  the actual work (Groq extraction, Supabase write). Meta retries a
  slow/timed-out webhook response, and without this a retry landing
  mid-processing would insert the same message twice.

## Frontend

- **Framework**: React 18 + Vite 5, plain JavaScript (no TypeScript), no
  component library, no client-side router (view switching is local
  React state).
- **Data access**: `@supabase/supabase-js`, connected with the
  **publishable/anon key** (never the service key). Supabase Realtime
  subscriptions keep the list live without manual refresh.
- **Hosting**: Vercel, deployed from the `dashboard/` subdirectory of the
  monorepo (Root Directory setting). Every push to `main` auto-deploys to
  Production; other branches get preview URLs.
- **Access control**: no user accounts. `middleware.js` runs on Vercel's
  Edge Runtime and gates every request behind HTTP Basic Auth
  (`BASIC_AUTH_USER`/`BASIC_AUTH_PASS`, not the `VITE_` prefix so they
  never reach the client bundle). Fails closed if those env vars aren't
  set. Documented as a stopgap, not real access control.

## Database (Supabase / Postgres)

Two logically separate schemas in the same project:

1. **Enquiry ingestion** (`enquiries` table) — written by the backend
   ingestion scripts, read/written by the dashboard.
2. **Sales module** (`companies`, `items`, `sales_enquiries(_items)`,
   `sales_quotations(_items)`) — written and read entirely by the
   dashboard; `sales_enquiries.source_enquiry_id` links back to the
   originating `enquiries` row when created via "Convert to Sales
   Enquiry".
3. **NPD module** (`npd_leads`, `npd_updates`, `backend/npd-schema.sql`,
   **draft — not yet applied**) — leads pipeline fed by a dedicated
   WhatsApp Business number (voice and text) plus manual dashboard entry,
   independent of `enquiries` and the Sales module. `npd_leads.stage` is
   the single source of truth for the pipeline stage vocabulary, reused
   verbatim by the Groq `stage_guess` extraction and the dashboard Kanban
   columns — see `schema.md`.

Row Level Security is enabled on every table with permissive
`using (true)` policies — access control is via the anon key's
capabilities plus the Basic Auth edge gate, not RLS-based user
restriction. Full column-level detail is in `schema.md`.

## External services

| Service | Role | Credential type |
|---|---|---|
| Supabase | Postgres database + Realtime | `service_role` (backend), anon/publishable (frontend) |
| Groq | LLM extraction (category/deadline/priority/relevance) | API key, GitHub Actions secret |
| Gmail API | Mail ingestion + digest sending | OAuth2 per account, GitHub Actions secret |
| Vercel | Dashboard hosting + Edge Middleware | Connected via Vercel's GitHub integration |
| GitHub Actions | Scheduled ingestion + digest jobs | Repo secrets/variables |

## Environments

There is no separate staging environment. `main` is production for both
halves: pushing to `main` triggers a Vercel Production deploy and is what
the GitHub Actions workflows run against. Feature branches get Vercel
preview deployments but the backend has no equivalent preview/staging
mechanism — GitHub Actions workflows only run against `main`.
