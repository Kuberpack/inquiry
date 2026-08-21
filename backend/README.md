# Unified enquiry backend — Gmail + WhatsApp ingestion

Gets messages from Gmail (and later WhatsApp) into one `enquiries` table,
with category/deadline/priority extracted automatically via Groq (model
configurable — see `GROQ_MODEL` below, since Groq periodically retires
model IDs).

## 1. Set up Supabase (database)

1. Create a free project at supabase.com.
2. Open the SQL editor and run `schema.sql` from this folder — creates the
   `enquiries` table.
3. Go to Project Settings > API and copy the Project URL and the
   `service_role` key (not the anon key — this backend needs write access).

## 2. Set up environment

```bash
cp .env.example .env
# fill in GROQ_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
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

## 5. Filtering personal mail out of the dashboard

If every account in `GMAIL_ACCOUNTS` is a dedicated business inbox, `GMAIL_QUERY`
alone is usually enough. For an account that's someone's actual personal
inbox (mixed with business mail), two layers work together:

1. **Every message is triaged by the LLM either way** — `extraction.py` asks
   Groq to classify `is_business_relevant` alongside the other fields, and
   `gmail_ingest.py` never inserts a message flagged as personal/promotional
   into `enquiries`. No setup needed; this alone catches most of it.
2. **For an inbox that's mostly non-business mail**, cut Groq calls and be
   more certain nothing personal is even considered: create a Gmail filter
   that labels business-relevant senders (known customer/supplier domains,
   or subject keywords like "enquiry"/"quotation"/"order"), then scope that
   one account to the label via `GMAIL_QUERY_OVERRIDES` in `.env`:
   ```
   GMAIL_QUERY_OVERRIDES={"rahul@personal-domain.com": "label:Business is:unread"}
   ```
   Accounts not listed here keep using the global `GMAIL_QUERY`.

## 6. WhatsApp (once Business API is ready)

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

`NPD_PHONE_NUMBER_ID` is **required** (read at import time, so the
server won't start without it) — set it to the `phone_number_id` Meta
reports in each payload's `entry[0].changes[0].value.metadata` for the
dedicated NPD WhatsApp Business number. Messages arriving on that number
are routed to `handle_npd_message()`, which extracts a structured update
via Groq, fuzzy-matches the party against `npd_leads`, writes
`npd_updates`, and replies on WhatsApp confirming what was logged (or
asking the sender to clarify, or flagging the message for manual review
— see `schema.md`/`archi.md`). This requires `backend/npd-schema.sql`
(still a draft, pending sign-off) to actually be applied to Supabase
first.

Set `WHATSAPP_ACCESS_TOKEN` (a Meta Graph API system-user token) to let
the webhook send those replies and download NPD voice note media —
without it, replies are just printed to the log instead of sent, and
voice notes are flagged for manual review instead of transcribed; typed
text still works either way. `WHATSAPP_API_VERSION` optionally overrides
the Graph API version if Meta retires the default.

Voice notes on the NPD line (`type: "audio"`) are downloaded via the Meta
Graph API media endpoint and transcribed with Groq's Whisper endpoint
(`GROQ_WHISPER_MODEL` optionally overrides the default model) before
going through the same `extract_npd_update()`/fuzzy-matching path as
typed text — the transcript is stored on `npd_updates.raw_transcript` so
a mis-transcription is auditable later. A voice note over ~2 minutes or
over a sane file-size limit is flagged for manual review rather than
silently dropped: the sender gets a WhatsApp reply explaining why.

## 7. Daily digest (reminder emails)

`ingest/daily_digest.py` sends one email a day (see
`.github/workflows/daily-digest.yml`, runs at 09:00 IST) summarizing every
open enquiry that's overdue, due within 2 days, or missing a deadline —
grouped by who it's assigned to. It reuses the same Gmail OAuth token as
ingestion, so no new auth setup is needed.

In `.env` (or as GitHub Actions repo **variables**, not secrets — see
below):

- `DIGEST_FROM_ACCOUNT` — which of your `GMAIL_ACCOUNTS` to send from
- `DIGEST_RECIPIENTS` — comma-separated list of who receives it
- `DASHBOARD_URL` — optional, linked at the top of the email

Run it manually to test: `cd ingest && python daily_digest.py`.

## What's next

Once messages are flowing into `enquiries`, the dashboard just reads from
this table. The Gmail poll and daily digest both run as scheduled GitHub
Actions — see the repo's Settings > Secrets and variables > Actions to
configure:

**Secrets** (sensitive): `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_OAUTH_TOKENS_JSON`,
`GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `GMAIL_ACCOUNTS`

**Variables** (not sensitive): `GMAIL_QUERY`, `GMAIL_QUERY_OVERRIDES`,
`GROQ_MODEL`, `DIGEST_FROM_ACCOUNT`, `DIGEST_RECIPIENTS`, `DASHBOARD_URL`

If `check-mail` starts failing with a Groq `model_not_found` (404) error,
Groq has retired the model `extraction.py` defaults to. Check
https://console.groq.com/docs/models for a currently supported model ID
and set it as the `GROQ_MODEL` repo variable — no code change needed.
