# Deploying to Hostinger

This is a Python/Flask app, so it needs a host that can run a long-running
Python process. On Hostinger that means a **VPS plan** (Ubuntu/Debian with
root/SSH access).

> **Hostinger shared/web hosting (hPanel) will not work.** Those plans run
> PHP/WordPress and can't keep a Python server running. If you only have a
> shared plan, upgrade to a Hostinger VPS (KVM) plan — the cheapest tier is
> plenty for this — or host it on a managed platform (Render/Railway/Fly)
> instead. Everything below assumes a VPS.

Before you start you'll want a subdomain like `portfolio.yourdomain.com`
(you can also use the bare VPS IP, but a subdomain + HTTPS is nicer).

---

## 1. Point a subdomain at the VPS

In your DNS (Hostinger hPanel → Domains → DNS/Nameservers), add an **A
record**:

| Type | Name        | Points to        |
|------|-------------|------------------|
| A    | portfolio   | your VPS IP addr |

Give DNS a few minutes to propagate.

## 2. SSH into the VPS

```bash
ssh root@YOUR_VPS_IP
```

## 3. Get the code onto the server

```bash
apt update && apt install -y git
git clone https://github.com/shtang4/trading-dashboard.git /opt/trading-dashboard
cd /opt/trading-dashboard
```

(Or, if you keep the repo private, use SSH or upload the folder with `scp`.)

## 4. Create your `.env` with a password and secret

```bash
cp .env.example .env
# generate a strong secret key:
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
nano .env      # paste the SECRET_KEY line, set DASHBOARD_PASSWORD, keep SESSION_COOKIE_SECURE=1
```

`.env` is gitignored — it never gets committed.

---

Now pick **one** of the two run options.

## Option A — Docker (simplest)

Hostinger has a one-click Docker template, or install it yourself:

```bash
curl -fsSL https://get.docker.com | sh
```

Then from `/opt/trading-dashboard`:

```bash
docker compose up -d --build
```

The app is now running on `127.0.0.1:8000`, and your data lives in a Docker
volume (`portfolio-data`) so it survives rebuilds. To update later:

```bash
git pull && docker compose up -d --build
```

## Option B — gunicorn + systemd (no Docker)

```bash
apt install -y python3-venv
cd /opt/trading-dashboard
python3 -m venv venv
venv/bin/pip install -r requirements.txt
mkdir -p data

cp deploy/portfolio.service.example /etc/systemd/system/portfolio.service
# edit the User/paths inside if yours differ:
nano /etc/systemd/system/portfolio.service

systemctl daemon-reload
systemctl enable --now portfolio
systemctl status portfolio        # should say "active (running)"
```

---

## 5. Put nginx + HTTPS in front (both options)

The app listens only on localhost; nginx faces the internet and adds HTTPS.

```bash
apt install -y nginx certbot python3-certbot-nginx

cp deploy/nginx.conf.example /etc/nginx/sites-available/portfolio
nano /etc/nginx/sites-available/portfolio   # set server_name to your subdomain
ln -s /etc/nginx/sites-available/portfolio /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# free HTTPS certificate (auto-renews):
certbot --nginx -d portfolio.yourdomain.com
```

Open `https://portfolio.yourdomain.com` — you'll get the password screen,
and after signing in, your dashboard.

---

## Notes

- **Data:** holdings/trades are stored in `portfolio.json` (in the Docker
  volume, or in `/opt/trading-dashboard/data` for Option B). Back it up
  occasionally — that one file is your whole portfolio.
- **Single user:** the JSON store assumes one person editing at a time,
  which is the intended use. It's not built for many simultaneous editors.
- **Firewall:** make sure only ports 80/443 (and your SSH port) are open to
  the world; the app's 8000 stays bound to localhost.
- **Changing your password:** edit `DASHBOARD_PASSWORD` in `.env`, then
  `docker compose up -d` (Option A) or `systemctl restart portfolio`
  (Option B).
