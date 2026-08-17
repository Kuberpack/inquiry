# Kuberpack Enquiry Dashboard

A single-page dashboard that reads and edits the same `enquiries` table your
backend (Gmail + WhatsApp ingestion) writes into. No login — built for one
internal user.

## 1. Update the database

Run `inquiry-dashboard-schema-update.sql` (in the parent folder) in the
Supabase SQL editor — it adds a `notes` column and sets up access policies
so the dashboard can read/update using the publishable key.

## 2. Set up environment

```bash
cp .env.example .env
```

Fill in `.env` with your Supabase Project URL and the **publishable** key
(Project Settings > API > "Publishable key", the one starting `sb_publishable_...`).
Do NOT use the secret key here — this file ships to the browser.

## 3. Install and run locally

```bash
npm install
npm run dev
```

Opens at `http://localhost:5173`.

## 4. What it does

- Lists every enquiry, newest first, sorted so overdue and no-deadline
  items float to the top
- Tabs to filter Open / Done / All, plus a source filter and search
- Click into any card to edit category, priority, deadline, status, or
  who it's assigned to — saves automatically on change/blur
- "Notes & original message" expands to show the raw message text and a
  free-text notes field

## 5. Deploying it for real use

Since it's a static site (no server-side code), the simplest path is:

```bash
npm run build
```

This produces a `dist/` folder — upload its contents to the same VPS you're
using for the backend (serve it via the same Nginx/Caddy you set up for the
webhook, on a path like `dashboard.kuberpack.com`), or to a static host like
Netlify/Vercel/Cloudflare Pages (all have generous free tiers for a
single-page app like this).

**Security note:** there's no login screen. Since the publishable key only
allows what the RLS policies permit (read + update on `enquiries`, nothing
else), the real exposure is that anyone who finds the dashboard's URL can
view and edit enquiry data. Fine for now while testing, but before sharing
the live URL beyond yourself, put it behind something like Cloudflare
Access, a VPN, or basic auth at the Nginx/Caddy level.
