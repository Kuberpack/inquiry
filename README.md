# Inquiry — Kuberpack monorepo

Unified enquiry pipeline: ingest messages from Gmail (and WhatsApp), store them in
Supabase, and manage them from a web dashboard.

## Layout

| Path | Purpose |
|------|---------|
| `backend/` | Python API and ingestion services — Gmail polling (`ingest/gmail_ingest.py`), WhatsApp webhook, Groq extraction, Supabase writes |
| `dashboard/` | React + Vite frontend for viewing and editing enquiries |

## Quick start

### Backend

```bash
cd backend
cp .env.example .env          # fill in keys (see backend/README.md)
pip install -r requirements.txt
cd ingest
python gmail_ingest.py        # poll Gmail once
```

### Dashboard

```bash
cd dashboard
cp .env.example .env          # Supabase publishable key only
npm install
npm run dev
```

See `backend/README.md` and `dashboard/README.md` for full setup (Gmail OAuth,
database schema, deployment).

## Scheduled mail check

GitHub Actions runs `backend/ingest/gmail_ingest.py` on a schedule (see
`.github/workflows/check-mail.yml`). Configure the required secrets in the repo
Settings before enabling.
