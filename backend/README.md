# Unified enquiry backend — Gmail + WhatsApp ingestion

Gets messages from Gmail (and later WhatsApp) into one `enquiries` table,
with category/deadline/priority extracted automatically by Claude.

## 1. Set up Supabase (database)

1. Create a free project at supabase.com.
2. Open the SQL editor and run `schema.sql` from this folder — creates the
   `enquiries` table.
3. Go to Project Settings > API and copy the Project URL and the
   `service_role` key (not the anon key — this backend needs write access).

## 2. Set up environment

```bash
cp .env.example .env
# fill in ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
pip install -r requirements.txt
```

## 3. Set up Gmail access

1. In Google Cloud Console, create a project, enable the **Gmail API**.
2. Create OAuth 2.0 credentials (type: Desktop app), download as
   `credentials.json`, place it in `ingest/`.
3. First run opens a browser to authorize once; after that it's silent
   (token cached in `ingest/token.json`).

## 4. Run Gmail ingestion

```bash
cd ingest
python gmail_ingest.py
```

Run this on a schedule — simplest is a cron job every 2-5 minutes:

```
*/3 * * * * cd /path/to/inquiry-backend/ingest && /usr/bin/python3 gmail_ingest.py >> ingest.log 2>&1
```

Adjust `GMAIL_QUERY` in `.env` to scope which mail gets pulled — e.g. a
label you create just for enquiries, instead of the whole inbox.

## 5. WhatsApp (once Business API is ready)

`ingest/whatsapp_webhook.py` is a ready-to-deploy FastAPI webhook. Once
you've set up WhatsApp Business API (Meta Cloud API directly, or a BSP
like Twilio/Gupshup/360dialog):

```bash
cd ingest
uvicorn whatsapp_webhook:app --host 0.0.0.0 --port 8000
```

Point Meta's webhook configuration at `https://your-server/webhook` with
the same `WHATSAPP_VERIFY_TOKEN` you set in `.env`. You'll need this
running behind a public HTTPS URL (a reverse proxy or a tunnel like
ngrok for testing).

## What's next

Once messages are flowing into `enquiries`, the dashboard just reads from
this table, and the reminder engine is a scheduled job that queries for
`status != 'done' AND (deadline < now() OR needs_deadline = true)`.
