# todo.md

Tasks and features discussed but not yet done, as of the last session.
Checked items are shipped and merged to `main`; unchecked items are open.

## Process / agent workflow

- [x] Codify standing agent-session rules (adjacent low-risk fixes in
      scope but flagged, schema changes always print-SQL-and-stop,
      spec-checklist verification before declaring a phase done,
      design for 10-100x data volume, update `todo.md` every phase)
      into `CLAUDE.md` under a new "Agent workflow rules" section.

## Infra / deployment

- [x] `deploy/` directory: systemd unit for `whatsapp_webhook.py`, cron
      entries for `gmail_ingest.py`/`daily_digest.py`, nginx config
      (`api.kuberpack.com` webhook proxy + `dashboard.kuberpack.com`
      static dashboard with a Basic Auth gate replacing the Vercel Edge
      middleware), and a step-by-step `deploy/README.md` for an Oracle
      Cloud VM. `.github/workflows/*.yml` and Vercel are untouched and
      still live as the fallback.
- [ ] Actually provision the Oracle Cloud VM and run through
      `deploy/README.md` end to end (DNS, firewall, SSL, WhatsApp webhook
      URL) — written but not yet executed against a real box.
- [ ] Once the VM deployment is confirmed stable, disable
      `.github/workflows/check-mail.yml` and `daily-digest.yml` and the
      Vercel project, in a separate change.

## Verification / immediate follow-ups

- [ ] Confirm `check-mail` GitHub Action actually succeeds on a live run
      now that the Groq model is fixed (`openai/gpt-oss-120b`) — it had
      not had a confirmed successful run as of the last check.
- [ ] Decide on the GST discount/tax interaction in the Sales Quotation
      module: tax is currently computed on each line's full value, and
      the discount is subtracted only at the grand-total level (doesn't
      reduce the taxable base). Confirm this matches how the company
      actually wants it, or specify the alternative.
- [ ] Set `DIGEST_FROM_ACCOUNT`, `DIGEST_RECIPIENTS`, and optionally
      `DASHBOARD_URL` as GitHub Actions repo **variables** so the daily
      digest email actually sends (code is merged, config isn't set).
- [ ] Run `backend/sales-schema.sql` against the live Supabase project if
      not already done (separate migration from `schema.sql`).
- [ ] If using `GMAIL_QUERY_OVERRIDES` for a mixed personal/business
      inbox, confirm the Gmail label/filter is catching what's expected.

## Backend / ingestion

- [ ] Finish WhatsApp ingestion — `whatsapp_webhook.py` exists (FastAPI,
      ready to deploy) but isn't live; needs a public HTTPS endpoint and
      the Meta Business API (or a BSP like Twilio/Gupshup/360dialog)
      actually wired up.
- [ ] Auto-acknowledgment reply — respond to the sender the moment an
      enquiry is ingested ("we've received your enquiry, we'll respond
      within X").
- [ ] Per-customer history — index/link repeat senders by
      `sender_contact` so the dashboard can show "this is their 3rd
      enquiry this month" instead of treating every message as new.
- [ ] Server-side search — move off client-side substring filtering to a
      Postgres full-text index once enquiry volume grows past a few
      hundred open items.
- [ ] CI health-check alerting — notify if `check-mail` starts silently
      failing again (the Groq outage went undetected for over a day;
      the daily digest partially covers this but there's no direct
      "ingestion is broken" alert).
- [x] Fix `whatsapp_webhook.py` processing messages synchronously before
      acking Meta — now returns 200 immediately and does the Groq
      call/DB write in a `BackgroundTask`, so a Meta retry on a slow
      response can no longer double-insert a message.

## NPD (New Product Development) module

Leads pipeline fed by a dedicated WhatsApp Business number (voice/text)
plus manual dashboard entry. `backend/npd-schema.sql` and the
`schema.md`/`archi.md` sections are drafted; nothing has been applied to
Supabase yet.

- [x] Draft `npd_leads`/`npd_updates` schema — signed off, including the
      `stage` check constraint (7-value pipeline, documented in
      `schema.md` as the single source of truth for Phase 3/Phase 6).
- [x] `whatsapp_webhook.py` routes by `metadata.phone_number_id`:
      `NPD_PHONE_NUMBER_ID` (required env var) → `handle_npd_message()`,
      everything else → the unchanged customer-enquiry path.
- [x] Phase 3: Groq extraction for NPD text messages
      (`extract_npd_update()` — `party_name`, `update_summary`,
      `stage_guess` constrained to the `schema.md` stage list,
      `next_follow_up_date`), DB-side fuzzy party matching against
      `npd_leads` via a `match_npd_leads()` Postgres function (pg_trgm
      `%` operator + `idx_npd_leads_party_name_trgm`, not a Python loop),
      linking to a single clear match / creating a new lead / asking the
      sender to disambiguate on multiple close matches, writing
      `npd_updates`, and a WhatsApp confirmation/clarification/
      needs-review reply via `send_whatsapp_message()` (Meta Graph API —
      needs `WHATSAPP_ACCESS_TOKEN`, optional; replies are just logged
      without it). Verified end-to-end (mocked Groq + DB) for: a brand
      new party, a party name close to an existing lead, two
      similarly-named existing parties (asks to disambiguate, writes no
      update), a Groq timeout, a Meta webhook retry of the same message
      (no duplicate lead/update/reply), and a total DB outage (no crash,
      sender still told it needs manual review) — none silently drop the
      message. Required an additive schema change (applied to the
      still-unapplied `backend/npd-schema.sql`, pending sign-off):
      `npd_updates.lead_id` made nullable + a new `needs_review boolean`
      column (so a message that can't be confidently linked — no party
      name, ambiguous match, unsupported message type, or a Groq/DB
      error — can still be stored instead of dropped) plus a partial
      index on `needs_review`, and the `match_npd_leads()` function. See
      `schema.md` for the exact SQL.
- [x] Voice transcription for `whatsapp_voice` updates — `handle_npd_message()`
      detects `type: "audio"`, downloads the media via the Meta Graph API
      (reuses `WHATSAPP_ACCESS_TOKEN`), transcribes with Groq Whisper
      (`GROQ_WHISPER_MODEL`, configurable), and feeds the transcript into
      the same `extract_npd_update()`/`match_npd_leads()` path as typed
      text via a shared `_process_npd_text()` helper — no duplicated
      extraction/matching logic between the two sources. Transcript is
      stored on `npd_updates.raw_transcript` for audit. Guardrails: audio
      over ~2 minutes (checked post-transcription, since neither the
      webhook payload nor the Graph API media metadata expose duration)
      or over 8MB (checked pre-download) is flagged via
      `flag_npd_update_for_review()` (extended with `source`/
      `raw_transcript` params so a skipped voice note keeps its
      transcript for audit too) and replied to the sender explaining why
      — never silently dropped. Without `WHATSAPP_ACCESS_TOKEN` set,
      voice notes are flagged for manual review instead of transcribed
      (can't download media without it), same degrade-gracefully
      approach as text replies. Verified end-to-end (media download →
      transcription → extraction → matching → DB insert, and both
      guardrails) against a real short audio file with only the
      Meta/Groq/Supabase network calls mocked — see PR description.
- [ ] Run `backend/npd-schema.sql` against the live Supabase project,
      **including the Phase 3 amendments above** — still just a draft
      file, needs sign-off and to actually be executed.
- [ ] Set `NPD_PHONE_NUMBER_ID` in `/etc/kuberpack/.env` (and any other
      deployment env) once the NPD WhatsApp Business number is
      provisioned with Meta — the webhook won't start without it.
- [ ] Set `WHATSAPP_ACCESS_TOKEN` (Meta Graph API system-user token) once
      available, so NPD WhatsApp replies actually send and voice notes
      actually transcribe instead of being flagged for manual review.
- [ ] Phase 6: dashboard NPD Kanban view, columns driven by the same
      `schema.md` stage list, plus a "needs review" queue surfacing
      `npd_updates` rows where `needs_review` is true so someone can
      manually link/correct them.

## Frontend / dashboard

- [x] Needs Deadline filter tab
- [x] Real-time updates (Supabase Realtime, replaces manual refresh)
- [x] Bulk actions (multi-select, mark done / reassign)
- [x] Analytics view (KPIs + category/assignee breakdowns)
- [x] Load-more pagination for the enquiry list
- [x] Mobile-responsive pass (verified at 375px/1280px)
- [x] Vercel deployment + HTTP Basic Auth edge middleware
- [x] Personal/business mail filtering (`is_business_relevant` +
      `GMAIL_QUERY_OVERRIDES`)
- [ ] Real user accounts — replace shared Basic Auth with per-user
      Supabase Auth login, so assignment/edits are attributable and there
      can be a real audit log. Currently flagged as a stopgap.
- [ ] Two-way reply from the dashboard — quick-reply templates that send
      back through Gmail/WhatsApp without leaving the card.
- [ ] CSV/Excel export of enquiries for reporting outside the dashboard.
- [ ] SLA countdown on cards ("2h left") rather than a static overdue
      badge.
- [ ] PWA / installable + push notifications, now that it's on a real
      Vercel URL.

## Sales Enquiry / Sales Quotation module

- [x] Companies + items masters, with inline "add new" modals
- [x] Sales Enquiry list + form (draft/confirm workflow)
- [x] Sales Quotation list + form, converted from a confirmed enquiry
- [x] GST calc (CGST+SGST same-state vs IGST cross-state based on
      `SUPPLIER_STATE`)
- [x] "Convert to Sales Enquiry" action on existing enquiry cards

Deliberately deferred (documented at the top of `sales-schema.sql` —
build only if actually needed):

- [ ] Inventory / stock tracking ("Current Stock", "Store")
- [ ] GSTIN lookup-and-verify against a government API
- [ ] Document amendments / revision history
- [ ] Bulk upload via template
- [ ] Reverse charge (RCM) and non-taxable extra-charge line types

## Bigger, undecided direction

- [ ] Company is deciding whether to keep extending this in-house system
      (using the paid year on the third-party ERP as runway) or continue
      relying on the ERP long-term. No decision recorded yet — revisit
      once the Sales module has had real usage.
