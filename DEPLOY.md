# Deploying the dashboard

Two supported ways to put this online:

- **Option 1 — Free on Render, at your own subdomain (recommended).** Works
  even though your Hostinger plan is shared hosting: Render runs the Python
  app, a free database keeps your data, and a subdomain of *your* Hostinger
  domain points at it. Your existing Hostinger website is untouched.
- **Option 2 — A Hostinger VPS** (paid, ~$5–7/mo) — runs everything on
  Hostinger itself.

Running it on your own computer never needs any of this — see
[README.md](README.md).

---

## Option 1 — Free on Render + your subdomain (recommended)

You'll use three free things: this GitHub repo (code), a free **Neon**
Postgres database (your data), and a free **Render** web service (runs the
app). Total cost: $0.

> **Why a database?** Render's free tier erases the app's local files every
> time it restarts (which happens whenever it goes idle). The app is built to
> store your holdings in the database instead, so nothing is ever lost. On
> your own machine it still just uses a file — no database needed there.

### Step 1 — Create a free database (Neon)

1. Go to <https://neon.tech> and sign up (free, no card).
2. Create a project (any name, any region near you).
3. Copy the **connection string**. It looks like:
   `postgresql://user:password@ep-xxxx.neon.tech/dbname?sslmode=require`
   Keep it handy for Step 2.

*(Any Postgres works — Supabase, Render's own free Postgres, etc. Neon is
just an easy, persistent free choice.)*

### Step 2 — Deploy to Render

1. Go to <https://render.com> and sign up (free), connecting your GitHub.
2. Click **New + → Blueprint** and pick the `trading-dashboard` repo.
   Render reads `render.yaml` automatically.
3. **Branch:** if you haven't merged, set the branch to
   `claude/stock-portfolio-dashboard-qxkn5x` (Render lets you choose).
4. Render will ask you to fill in the two secret values:
   - `DASHBOARD_PASSWORD` → the password you'll type to open the dashboard.
   - `DATABASE_URL` → the Neon connection string from Step 1.
   (`SECRET_KEY` is auto-generated and `SESSION_COOKIE_SECURE` is preset — you
   don't touch those.)
5. Click **Apply / Deploy** and wait for the build to finish. Render gives you
   a URL like `https://trading-dashboard-xxxx.onrender.com`.
6. Open it — you'll get the password screen, then your dashboard.

> **Free-tier note:** after ~15 minutes of no visits the app "sleeps," so the
> next visit takes ~30–60 seconds to wake up. Your data is always safe in the
> database regardless. (Upgrading to Render's cheapest paid tier removes the
> sleep, if the wait ever bothers you.)

### Step 3 — Point your Hostinger subdomain at it

This gives you `portfolio.yourdomain.com` instead of the `onrender.com` URL,
without moving your main site.

1. In **Render** → your service → **Settings → Custom Domains** → add
   `portfolio.yourdomain.com`. Render shows a DNS target to point at (a value
   ending in `.onrender.com`).
2. In **Hostinger** → hPanel → **Domains → DNS / Nameservers → DNS Zone**,
   add a record:
   | Type  | Name      | Points to (Target)                     |
   |-------|-----------|----------------------------------------|
   | CNAME | portfolio | the value Render gave you (…onrender.com) |
3. Wait a few minutes. Render issues an HTTPS certificate automatically, and
   `https://portfolio.yourdomain.com` starts working.

### Updating later

Push new commits to the branch on GitHub — Render redeploys automatically.
Your data stays put in the database across deploys.

---

## Option 2 — Hostinger VPS (paid)

Needs a **VPS plan** (Ubuntu/Debian with SSH). Hostinger shared/hPanel
hosting can't run this. On a VPS you don't need Render or an external
database — the app can use its local file (or a database if you prefer).

### 1. Point a subdomain at the VPS

In Hostinger DNS, add an **A record**: `portfolio` → your VPS IP address.

### 2. Get the code and set secrets

```bash
ssh root@YOUR_VPS_IP
apt update && apt install -y git
git clone -b claude/stock-portfolio-dashboard-qxkn5x \
  https://github.com/shtang4/trading-dashboard.git /opt/trading-dashboard
cd /opt/trading-dashboard
cp .env.example .env
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
nano .env      # paste SECRET_KEY, set DASHBOARD_PASSWORD, keep SESSION_COOKIE_SECURE=1
```

### 3. Run it — Docker (simplest)

```bash
curl -fsSL https://get.docker.com | sh
docker compose up -d --build
```

The app runs on `127.0.0.1:8000` with data in a Docker volume that survives
rebuilds. Update later with `git pull && docker compose up -d --build`.

### 3 (alt). Run it — gunicorn + systemd (no Docker)

```bash
apt install -y python3-venv
python3 -m venv venv
venv/bin/pip install -r requirements.txt
mkdir -p data
cp deploy/portfolio.service.example /etc/systemd/system/portfolio.service
nano /etc/systemd/system/portfolio.service   # adjust User/paths if needed
systemctl daemon-reload
systemctl enable --now portfolio
```

### 4. nginx + HTTPS in front

```bash
apt install -y nginx certbot python3-certbot-nginx
cp deploy/nginx.conf.example /etc/nginx/sites-available/portfolio
nano /etc/nginx/sites-available/portfolio    # set server_name to your subdomain
ln -s /etc/nginx/sites-available/portfolio /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d portfolio.yourdomain.com
```

Open `https://portfolio.yourdomain.com`.

---

## Notes

- **Backups:** on the free/Render path your data lives in the database — Neon
  keeps its own backups. On a VPS with the file store, back up
  `portfolio.json` (or `data/portfolio.json`) occasionally.
- **Single user:** the storage assumes one person editing at a time, which is
  the intended use.
- **Changing your password:** update `DASHBOARD_PASSWORD` (in Render's
  dashboard, or `.env` on a VPS) and redeploy/restart.
