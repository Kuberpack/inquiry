# Deploying to an always-on Oracle Cloud VM

Replaces GitHub Actions + ngrok (`.github/workflows/check-mail.yml`,
`daily-digest.yml`) and the Vercel dashboard deployment with everything
running on one free-tier Ubuntu VM:

- `whatsapp_webhook.py` as a systemd service, reverse-proxied by nginx
- `gmail_ingest.py` / `daily_digest.py` as cron jobs
- `dashboard/dist` served by nginx as static files

`.github/workflows/*.yml` are left untouched — keep them as a fallback
until the VM setup below is confirmed working, then disable them
(Settings > Actions, or delete the files) in a separate change.

Assumes Ubuntu 22.04 LTS (see the note on `.env` quoting in step 4 for
why the version matters) and that you're running these commands yourself
over SSH as a sudo-capable user — nothing here provisions or connects to
the VM for you.

Paths used throughout (adjust if you clone somewhere else, keeping all
the file paths below consistent):

| What | Path |
|---|---|
| Repo clone | `/opt/kuberpack/inquiry` |
| Backend venv | `/opt/kuberpack/inquiry/backend/venv` |
| Shared env file | `/etc/kuberpack/.env` |
| Dashboard basic-auth password file | `/etc/kuberpack/dashboard.htpasswd` |
| Cron job logs | `/var/log/kuberpack/` |
| Service user | `kuberpack` (dedicated, no login shell) |

## 1. Firewall / networking

Oracle Cloud blocks inbound traffic at the **cloud network** level
(Security List / Network Security Group on the VCN) independently of the
VM's own firewall — the most common reason "it works locally but nginx
never receives traffic" on Oracle free tier. Before anything else:

1. In the OCI console, open the VM's subnet's Security List (or NSG) and
   add ingress rules for TCP 80 and 443 from `0.0.0.0/0`.
2. On the VM itself:
   ```bash
   sudo ufw allow OpenSSH
   sudo ufw allow 'Nginx Full'   # opens 80 + 443
   sudo ufw enable
   ```
3. Point DNS A records for `api.kuberpack.com` and `dashboard.kuberpack.com`
   at the VM's public IP (needed before the certbot step works).

## 2. System user, clone, venv

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin kuberpack

sudo mkdir -p /opt/kuberpack
sudo git clone <this-repo-url> /opt/kuberpack/inquiry
sudo chown -R kuberpack:kuberpack /opt/kuberpack/inquiry

sudo apt update
sudo apt install -y python3.12 python3.12-venv nginx

sudo -u kuberpack python3.12 -m venv /opt/kuberpack/inquiry/backend/venv
sudo -u kuberpack /opt/kuberpack/inquiry/backend/venv/bin/pip install \
  -r /opt/kuberpack/inquiry/backend/requirements.txt

# Vite 5 needs Node 18+; Ubuntu 22.04's own `apt` package is Node 12, too
# old to build the dashboard — use NodeSource instead:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## 3. Gmail OAuth files

`gmail_ingest.py` and `daily_digest.py` need `credentials.json` and one
`token_<account>.json` per Gmail account **in `backend/ingest/`** — these
are files, not env vars (`CREDENTIALS_PATH = "credentials.json"` and
`token_path_for()` in `gmail_ingest.py` are relative to the working
directory the script runs from, which is why every cron entry below
starts with `cd .../backend/ingest`). The `run_local_server()` OAuth flow
needs a real browser, which a headless VM doesn't have, so generate these
the same way the GitHub Actions secrets were originally created — on a
machine with a browser — then copy them over:

```bash
# on your local machine, from backend/ingest/, after `python gmail_ingest.py`
# has completed its one-time browser auth for every account in GMAIL_ACCOUNTS:
scp credentials.json token_*.json youruser@vm-ip:/tmp/

# on the VM:
sudo mv /tmp/credentials.json /tmp/token_*.json /opt/kuberpack/inquiry/backend/ingest/
sudo chown kuberpack:kuberpack /opt/kuberpack/inquiry/backend/ingest/credentials.json \
  /opt/kuberpack/inquiry/backend/ingest/token_*.json
sudo chmod 600 /opt/kuberpack/inquiry/backend/ingest/credentials.json \
  /opt/kuberpack/inquiry/backend/ingest/token_*.json
```

## 4. `/etc/kuberpack/.env`

One shared file read by the systemd unit (`EnvironmentFile=`) **and**
sourced directly by both cron jobs — so it has to be both systemd- and
POSIX-shell-parseable, and readable by the `kuberpack` user (not just
root, since cron's `. /etc/kuberpack/.env` runs as `kuberpack`).

```bash
sudo mkdir -p /etc/kuberpack
sudo -u kuberpack tee /etc/kuberpack/.env > /dev/null <<'EOF'
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
GMAIL_ACCOUNTS=
GMAIL_QUERY=is:unread
GMAIL_QUERY_OVERRIDES=
WHATSAPP_VERIFY_TOKEN=
DIGEST_FROM_ACCOUNT=
DIGEST_RECIPIENTS=
DASHBOARD_URL=
EOF
sudo chmod 600 /etc/kuberpack/.env
```

Fill in the blanks with the same values used in the GitHub Actions
secrets/variables (see `backend/README.md`'s "What's next" section for
what each one means). `GROQ_API_KEY` is required even though the webhook
and the digest job don't call Groq directly for every code path —
`daily_digest.py` imports `gmail_ingest.py`, which imports
`extraction.py`, which reads `GROQ_API_KEY` at **import time**; without
it `daily_digest.py` crashes with a `KeyError` before it does anything.

**Quoting note (why this needs Ubuntu 22.04+):** if you set
`GMAIL_QUERY_OVERRIDES` (only needed for a mixed personal/business
inbox), its value is a JSON object with spaces in it, e.g.
`{"rahul@personal-domain.com": "label:Business is:unread"}`. Wrap it in
single quotes:
```
GMAIL_QUERY_OVERRIDES='{"rahul@personal-domain.com": "label:Business is:unread"}'
```
This is the one quoting style both readers of this file agree on: POSIX
`sh` (used by `. /etc/kuberpack/.env` in the cron jobs) strips single
quotes as literal-string delimiters, and systemd's `EnvironmentFile=`
parser has followed the same POSIX shell quoting rules since systemd 246
(Ubuntu 22.04 ships 249; Ubuntu 20.04's 245 does not — either skip this
var on 20.04 or upgrade). Leave it blank if you don't need it.

## 5. systemd service (WhatsApp webhook)

```bash
sudo cp /opt/kuberpack/inquiry/deploy/whatsapp-webhook.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now whatsapp-webhook
sudo systemctl status whatsapp-webhook   # should be active (running)
curl -i "http://127.0.0.1:8000/webhook?hub.verify_token=<WHATSAPP_VERIFY_TOKEN>&hub.challenge=ping"
# should echo back "ping"
journalctl -u whatsapp-webhook -f        # tail logs
```

## 6. Cron jobs (Gmail poll + daily digest)

```bash
sudo mkdir -p /var/log/kuberpack
sudo chown kuberpack:kuberpack /var/log/kuberpack

sudo cp /opt/kuberpack/inquiry/deploy/gmail-ingest.cron /etc/cron.d/kuberpack-gmail-ingest
sudo cp /opt/kuberpack/inquiry/deploy/daily-digest.cron /etc/cron.d/kuberpack-daily-digest
sudo chown root:root /etc/cron.d/kuberpack-gmail-ingest /etc/cron.d/kuberpack-daily-digest
sudo chmod 644 /etc/cron.d/kuberpack-gmail-ingest /etc/cron.d/kuberpack-daily-digest
```

`/etc/cron.d` files are picked up automatically — no cron restart needed
(but cron silently ignores a file with the wrong owner/permissions, so if
nothing runs, re-check the `chown`/`chmod` above first). Test each script
manually once before waiting for the schedule:

```bash
sudo -u kuberpack bash -c 'cd /opt/kuberpack/inquiry/backend/ingest && set -a && . /etc/kuberpack/.env && set +a && /opt/kuberpack/inquiry/backend/venv/bin/python3 gmail_ingest.py'
tail -f /var/log/kuberpack/gmail-ingest.log
```

## 7. Dashboard build

```bash
cd /opt/kuberpack/inquiry/dashboard
sudo -u kuberpack cp .env.example .env
# edit .env: VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY (publishable key, never the secret key)
sudo -u kuberpack npm install
sudo -u kuberpack npm run build   # outputs dashboard/dist, served directly by nginx
```

Re-run `npm run build` after every dashboard change and deploy (`git pull`
then rebuild) — there's no CI doing this for you anymore.

## 8. nginx + basic auth

`dashboard/middleware.js` (the Vercel Edge Basic Auth gate) only runs on
Vercel's runtime — it does nothing once nginx is serving `dist/` directly.
`deploy/nginx.conf` adds an equivalent `auth_basic` gate on the
`dashboard.kuberpack.com` vhost so the dashboard doesn't end up
world-readable; create its password file before enabling the site:

```bash
sudo apt install -y apache2-utils   # provides htpasswd
sudo htpasswd -c /etc/kuberpack/dashboard.htpasswd <username>   # prompts for a password
```

Then install the vhost config:

```bash
sudo cp /opt/kuberpack/inquiry/deploy/nginx.conf /etc/nginx/sites-available/kuberpack-inquiry
sudo ln -s /etc/nginx/sites-available/kuberpack-inquiry /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

At this point `http://dashboard.kuberpack.com` should prompt for the
Basic Auth credentials and then serve the dashboard, and
`http://api.kuberpack.com/webhook?hub.verify_token=...&hub.challenge=ping`
should proxy through to the same response as the `curl` in step 5.

## 9. SSL (Let's Encrypt)

Only once DNS for both hostnames resolves to this VM (step 1):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.kuberpack.com -d dashboard.kuberpack.com
# follow the prompts (email, ToS, choose "redirect HTTP to HTTPS" when asked)
```

Certbot rewrites `/etc/nginx/sites-available/kuberpack-inquiry` in place
to add the HTTPS server blocks and the HTTP→HTTPS redirect, and installs
its own renewal timer:

```bash
systemctl list-timers | grep certbot   # confirm the renewal timer is active
```

## 10. Point WhatsApp at the webhook

In Meta's WhatsApp Business API webhook configuration, set the callback
URL to `https://api.kuberpack.com/webhook` and the verify token to the
same `WHATSAPP_VERIFY_TOKEN` set in `/etc/kuberpack/.env`.

## Updating the deployment later

```bash
cd /opt/kuberpack/inquiry
sudo -u kuberpack git pull
sudo -u kuberpack backend/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart whatsapp-webhook
cd dashboard && sudo -u kuberpack npm install && sudo -u kuberpack npm run build
```

Cron jobs and nginx pick up code/static-file changes on their next run —
no separate restart needed for those.
