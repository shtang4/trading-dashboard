# Trading Dashboard

A simple stock portfolio dashboard built with Python (Flask) and HTML.

Enter each stock you own — symbol, date bought, price paid, and number of
shares — and the dashboard fetches the current live price from Yahoo Finance
(via the `yfinance` library) to show each position's current value plus your
total portfolio value and total profit/loss.

A second table tracks leveraged trades: symbol, direction (Long/Short),
leverage ratio, entry price, stop loss, and shares. For each trade it
computes the amount borrowed (`Entry × Shares × (1 − 1/Leverage)`) and the
risk if the stop is hit (`(Current Price − Stop Loss) × Shares`, reversed
for shorts). Shares is the total share count of the leveraged position, so
leverage is already reflected in the risk number.

Each trade also shows ROI against your own capital:
`ROI = (Current Value − Invested Capital) ÷ Invested Capital × 100`, where
invested capital is `Entry × Shares ÷ Leverage`. ROI turns red with a ⚠
when it drops below −20%, and any row whose current price has crossed the
stop loss (below it for longs, above it for shorts) is highlighted with a
red warning.

The Liq. price column shows the theoretical liquidation price where your
equity hits zero: `Entry × (1 − 1/Leverage)` for longs and
`Entry × (1 + 1/Leverage)` for shorts. Brokers force-close positions at
their maintenance-margin level before this point. Unleveraged longs (1x)
show "—" since they can only reach zero equity at $0.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser. With no password set the
app runs open, which is fine on your own machine.

## Deploying to a server

See **[DEPLOY.md](DEPLOY.md)** for step-by-step instructions (written for a
Hostinger VPS, but the Docker / gunicorn+nginx setup applies to any Linux
server).

In production the app is served by **gunicorn** and protected by a password
login. Configure it with environment variables (see `.env.example`):

- `DASHBOARD_PASSWORD` — required to view/edit. **If unset, the app runs with
  no login** and prints a warning; always set it on a public server.
- `SECRET_KEY` — signs login cookies; set a fixed random value so logins
  survive restarts.
- `SESSION_COOKIE_SECURE=1` — enable once served over HTTPS.
- `DATABASE_URL` — optional Postgres connection string. **Set it on hosts
  with an ephemeral filesystem (e.g. Render's free tier)** so your data
  persists across restarts. When unset, data is kept in a local
  `portfolio.json` file — which is all you need locally or on a VPS.
- `DATA_DIR` — where `portfolio.json` is stored (when no `DATABASE_URL`).

Run in production with:

```bash
gunicorn -w 2 -b 127.0.0.1:8000 app:app
```

## Notes

- Holdings and trades are saved to `portfolio.json` (in `DATA_DIR`), written
  atomically so a crash can't corrupt it. Back this file up — it's your whole
  portfolio.
- Designed for a single user; the JSON store assumes edits don't truly
  overlap.
- Live prices are cached for 60 seconds (`PRICE_CACHE_SECONDS`); click
  **Refresh prices** to re-fetch.
- If Yahoo Finance is temporarily unreachable, the affected rows show "—"
  and totals wait until all prices load.
