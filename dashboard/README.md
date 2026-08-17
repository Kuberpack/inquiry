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

## 5. Deploying to Vercel

The project deploys to Vercel as a static Vite build, gated by HTTP Basic
Auth (`middleware.js`) since there's no login screen. One-time setup:

1. **Import the repo** — in the Vercel dashboard: Add New > Project > import
   `Kuberpack/inquiry`.
2. **Set the Root Directory** to `dashboard` (Project Settings > General —
   or the "Root Directory" field shown during import). This is a monorepo;
   Vercel needs to know the dashboard lives in a subfolder. Framework
   Preset should auto-detect as **Vite**; build command `npm run build`,
   output directory `dist` — leave these as the defaults.
3. **Add environment variables** (Project Settings > Environment Variables,
   applied to Production + Preview):
   | Name | Value |
   |---|---|
   | `VITE_SUPABASE_URL` | your Supabase project URL |
   | `VITE_SUPABASE_ANON_KEY` | the **publishable** key (never the secret key) |
   | `BASIC_AUTH_USER` | a username for the access gate |
   | `BASIC_AUTH_PASS` | a password for the access gate |

   `BASIC_AUTH_USER`/`BASIC_AUTH_PASS` are deliberately **not** prefixed
   `VITE_` — that prefix tells Vite to inline a variable into the browser
   bundle, which would leak these two. `middleware.js` reads them
   server-side only, on Vercel's Edge Runtime, and returns `401` with a
   `WWW-Authenticate` challenge for any request missing valid Basic Auth
   credentials. It fails closed: if the env vars aren't set, every request
   is rejected rather than served unprotected.
4. **Deploy.** Vercel builds and gives you a `*.vercel.app` URL immediately;
   attach a custom domain (e.g. `dashboard.kuberpack.com`) under Project
   Settings > Domains once you're happy with it.
5. Every push to `main` auto-deploys to Production; pushes to other
   branches get their own preview URL (also gated by the same Basic Auth).

The Basic Auth prompt is a stopgap, not a real access-control system —
anyone with the shared credentials sees everything. If this grows beyond a
couple of people, move to Cloudflare Access or a proper login instead.
