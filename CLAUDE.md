# CLAUDE.md

Working conventions for this repo, distilled from the project's history so
far. Read this before making changes.

## Languages & frameworks

| Area | Choice |
|---|---|
| Backend | Python 3.12, plain scripts (no framework except FastAPI for the WhatsApp webhook) |
| Frontend | React 18 + Vite 5, plain JS (no TypeScript) |
| Database | Supabase (hosted Postgres) |
| LLM extraction | Groq API (model configurable via `GROQ_MODEL`, currently `openai/gpt-oss-120b`) |
| Styling | Plain CSS (`App.css`), no CSS framework, no CSS-in-JS |
| State management | React hooks only (`useState`/`useEffect`) — no Redux/Zustand/etc. |
| Backend deps | `groq`, `supabase`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `fastapi`, `uvicorn`, `python-dotenv` |
| Frontend deps | `@supabase/supabase-js`, `react`, `react-dom` (+ `vite`, `@vitejs/plugin-react` as dev deps) |

No ORMs, no component libraries, no test framework has been introduced yet.
Keep it that way unless there's a concrete need — this project has
deliberately stayed dependency-light.

## Repo layout

```
backend/
  schema.sql               # enquiries table (Gmail/WhatsApp ingestion target)
  sales-schema.sql          # Sales Enquiry / Sales Quotation module tables
  requirements.txt
  ingest/
    gmail_ingest.py          # polls Gmail, extracts, upserts into enquiries
    whatsapp_webhook.py       # FastAPI webhook for WhatsApp Business API
    extraction.py              # Groq call: category/deadline/priority/relevance
    daily_digest.py             # emails overdue/undated summary once a day
    db.py                        # Supabase client wrapper

dashboard/
  inquiry-dashboard-schema-update.sql   # notes column + RLS + realtime for enquiries
  middleware.js                          # Vercel Edge basic-auth gate
  src/
    App.jsx, App.css                      # main list/analytics/sales shell
    Analytics.jsx                          # KPI + bar-list analytics view
    supabaseClient.js                       # anon-key Supabase client
    sales/                                   # Sales Enquiry/Quotation module
      salesClient.js                           # data access + GST calc
      SalesApp.jsx, SalesEnquiryList/Form.jsx,
      SalesQuotationList/Form.jsx, CompanyPicker/Modal.jsx,
      ItemPicker/Modal.jsx, LineItemsTable.jsx

.github/workflows/
  check-mail.yml         # polls Gmail every 15 min
  daily-digest.yml        # sends digest email at 09:00 IST
```

## Coding rules

- **No comments unless the WHY is non-obvious.** Never explain what code
  does — names should do that. A short comment is fine for a hidden
  constraint, a workaround, or a genuinely surprising invariant.
- **No premature abstraction.** Don't build for hypothetical future
  requirements. Three similar lines beat a speculative helper.
- **Minimal dependencies.** Reach for a new npm/pip package only when it's
  clearly worth the weight — this project has stayed on vanilla
  React/CSS/Python deliberately.
- **Ask before schema changes.** Any change to Supabase tables/columns
  needs explicit sign-off before writing SQL — this has been a standing
  rule since the Sales module discussion. Additive changes (new column,
  new table) still need to be flagged, even if low-risk.
- **Fail open, not silent.** When an LLM call or parse can fail, default
  to the safer outcome that surfaces the item for manual review rather
  than silently dropping it (see `extraction.py`'s fail-safe JSON parse
  and `is_business_relevant` defaulting to `true`).
- **Config over code for things that drift.** Anything likely to change
  outside this repo's control (LLM model IDs, Gmail query scoping) goes
  through an env var / GitHub Actions repo variable with a sane default,
  not a hardcoded value — the Groq model outage is why.

## Design system (dashboard)

"Cardboard box" theme — earthy, printed-carton aesthetic:

- Colors: `--board`/`--surface` (cream backgrounds), `--ink`/`--ink-soft`
  (text), `--mustard` (warning/flag), `--rust` (overdue/critical),
  `--teal` (done/success), `--slate` (neutral), `--gmail`/`--whatsapp`
  (source badges).
- Fonts: **Zilla Slab** (serif) for headings, **IBM Plex Sans** for body
  text and inputs, **IBM Plex Mono** for badges/numbers/technical labels.
- Mobile breakpoints at 700px and 600px; wide tables scroll horizontally
  inside their own container rather than breaking page layout.
- New UI should reuse existing classes (`.bulk-btn`, `.btn-secondary`,
  `.sales-field`, `.modal-*`, `.status-pill`, etc.) before inventing new
  ones — check `App.css` first.

## Git / PR workflow

- Branch naming: `claude/<short-description>`, always cut from latest
  `main`.
- One logical change per PR; squash-merge into `main`.
- Draft PRs by default; skip draft only for urgent production fixes.
- PR descriptions include a "Verification" section — this project has no
  automated test suite, so changes are verified via local venvs (backend)
  or a headless Chromium run against mocked Supabase responses (frontend)
  before merging, and that verification is written into the PR body.
- If a PR conflicts with `main` because a more urgent fix landed first,
  merge `main` into the branch and resolve conflicts before merging —
  don't force through with `--force` or discard either side blindly.

## Known non-obvious constraints

- No user login anywhere in the dashboard — it's gated by shared HTTP
  Basic Auth at the Vercel Edge (`middleware.js`), explicitly called out
  as a stopgap, not real access control.
- Supabase RLS policies are permissive-by-design (`using (true)`) because
  the dashboard connects with the anon/publishable key and there's no
  per-user identity to restrict by.
- Groq periodically retires model IDs without much warning — see
  `GROQ_MODEL` in `.env.example` and the troubleshooting note in
  `backend/README.md`.
- This sandboxed environment cannot reach `console.groq.com` or
  `groq.com` (egress blocked) — model-list lookups need to happen outside
  this environment.
