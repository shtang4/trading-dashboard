"""Simple stock portfolio dashboard.

Holdings and leveraged trades are stored in portfolio.json. Live prices
come from Yahoo Finance via the yfinance library.

Configuration (environment variables):
  DASHBOARD_PASSWORD  Password required to view/edit. If unset, the app runs
                      OPEN (no login) and prints a warning — never leave this
                      unset on a public server.
  SECRET_KEY          Secret used to sign session cookies. Set a fixed random
                      value in production so logins survive restarts.
  DATABASE_URL        Postgres connection string. If set, holdings/trades are
                      stored in the database (needed on hosts with an
                      ephemeral filesystem, e.g. Render's free tier). If
                      unset, data is stored in a local portfolio.json file.
  DATA_DIR            Directory for portfolio.json when no DATABASE_URL is set
                      (default: this folder).
  SESSION_COOKIE_SECURE  Set to 1/true when served over HTTPS.
  PRICE_CACHE_SECONDS    Seconds to cache prices (default 60).
  PORT / FLASK_DEBUG     Dev server port / debug toggle (dev only).

Local dev:   python app.py                       (uses portfolio.json)
Production:  gunicorn -w 2 -b 0.0.0.0:$PORT app:app   (set DATABASE_URL)
"""

import hmac
import json
import os
import secrets
import sys
import time
import uuid
from functools import wraps
from pathlib import Path
from threading import Lock

import yfinance as yf
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

app = Flask(__name__)

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")

app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower()
    in ("1", "true", "yes"),
)

if not DASHBOARD_PASSWORD:
    print(
        "WARNING: DASHBOARD_PASSWORD is not set — the dashboard is OPEN to "
        "anyone who can reach it. Set it before exposing this on a public "
        "server.",
        file=sys.stderr,
    )
elif not os.environ.get("SECRET_KEY"):
    print(
        "WARNING: SECRET_KEY is not set — a random one was generated, so "
        "everyone will be logged out whenever the app restarts. Set a fixed "
        "SECRET_KEY in production.",
        file=sys.stderr,
    )

DATA_DIR = Path(os.environ.get("DATA_DIR") or Path(__file__).parent)
DATA_DIR.mkdir(parents=True, exist_ok=True)
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
_file_lock = Lock()

# Cache prices so refreshing the page doesn't hammer Yahoo.
PRICE_CACHE_SECONDS = int(os.environ.get("PRICE_CACHE_SECONDS", "60"))
_price_cache = {}  # symbol -> (timestamp, price or None)


def login_required(view):
    """Gate a view behind the dashboard password (no-op if none is set)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not DASHBOARD_PASSWORD or session.get("authed"):
            return view(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required."}), 401
        return redirect(url_for("login", next=request.path))

    return wrapped


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if not DASHBOARD_PASSWORD:
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if hmac.compare_digest(supplied, DASHBOARD_PASSWORD):
            session["authed"] = True
            session.permanent = True
            nxt = request.args.get("next", "")
            # Only allow local redirects, never protocol-relative (//host).
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = url_for("index")
            return redirect(nxt)
        error = "Incorrect password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


def _normalize(data):
    """Coerce loaded data into {"holdings": [...], "trades": [...]}."""
    # Older versions stored a bare list of holdings.
    if isinstance(data, list):
        data = {"holdings": data, "trades": []}
    data.setdefault("holdings", [])
    data.setdefault("trades", [])
    return data


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

if DATABASE_URL:
    # Persistent storage for hosts with an ephemeral filesystem (e.g. Render
    # free tier). The whole portfolio is kept as one JSON document in a
    # single-row table — simple and a good fit for a single-user dashboard.
    import psycopg
    from psycopg.types.json import Json

    # Some providers hand out the legacy "postgres://" scheme.
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

    with psycopg.connect(DATABASE_URL, autocommit=True) as _conn:
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS portfolio_kv "
            "(k TEXT PRIMARY KEY, v JSONB NOT NULL)"
        )

    def load_data():
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            row = conn.execute(
                "SELECT v FROM portfolio_kv WHERE k = 'portfolio'"
            ).fetchone()
        return _normalize(row[0]) if row else {"holdings": [], "trades": []}

    def save_data(data):
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO portfolio_kv (k, v) VALUES ('portfolio', %s) "
                "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
                (Json(data),),
            )

else:
    # Local / single-server storage: a plain JSON file.
    def load_data():
        with _file_lock:
            if PORTFOLIO_FILE.exists():
                return _normalize(json.loads(PORTFOLIO_FILE.read_text()))
            return {"holdings": [], "trades": []}

    def save_data(data):
        # Write to a temp file and atomically replace, so a crash mid-write
        # can never leave a truncated portfolio.json behind.
        with _file_lock:
            tmp = PORTFOLIO_FILE.parent / (PORTFOLIO_FILE.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2))
            os.replace(tmp, PORTFOLIO_FILE)


def get_live_price(symbol):
    """Return the latest price for symbol, or None if Yahoo is unreachable."""
    now = time.time()
    cached = _price_cache.get(symbol)
    if cached and now - cached[0] < PRICE_CACHE_SECONDS:
        return cached[1]
    price = None
    try:
        ticker = yf.Ticker(symbol)
        price = ticker.fast_info["last_price"]
        if price is not None:
            price = float(price)
    except Exception:
        try:
            history = yf.Ticker(symbol).history(period="1d")
            if not history.empty:
                price = float(history["Close"].iloc[-1])
        except Exception:
            price = None
    _price_cache[symbol] = (now, price)
    return price


@app.route("/")
@login_required
def index():
    return render_template("index.html", auth_enabled=bool(DASHBOARD_PASSWORD))


def build_trade_rows(trades):
    """Enrich leveraged trades with borrowed amount and stop-loss risk.

    Shares is the TOTAL share count of the leveraged position, so the
    price move times shares already captures the full loss — no extra
    leverage multiplier.
    Borrowed: with leverage L you put up 1/L of the position yourself, so
    borrowed = entry_price * shares * (1 - 1/L).
    Risk, sign-adjusted for shorts:
    Long:  (Current Price - Stop Loss) * Shares
    Short: (Stop Loss - Current Price) * Shares
    ROI is measured against invested capital (position / leverage):
    ROI = (Current Value - Invested Capital) / Invested Capital * 100
    A trade is flagged stop_breached when the current price is past the
    stop (below it for longs, above it for shorts).
    Liquidation price is where equity (invested + P/L) reaches zero:
    Long:  entry * (1 - 1/L)      Short: entry * (1 + 1/L)
    A real broker force-closes earlier, at its maintenance-margin level,
    so treat this as the theoretical wipe-out point. An unleveraged long
    (L = 1) has no liquidation price - equity only hits zero at $0.
    """
    rows = []
    for t in trades:
        position = t["entry_price"] * t["shares"]
        borrowed = position * (1 - 1 / t["leverage"])
        invested = position - borrowed  # your own capital
        is_long = t["direction"] == "Long"
        if is_long:
            liq_price = None if t["leverage"] == 1 else t["entry_price"] * (1 - 1 / t["leverage"])
        else:
            liq_price = t["entry_price"] * (1 + 1 / t["leverage"])
        price = get_live_price(t["symbol"])
        risk = None
        roi = None
        stop_breached = False
        if price is not None:
            risk = (price - t["stop_loss"] if is_long else t["stop_loss"] - price) * t["shares"]
            pl = (price - t["entry_price"] if is_long else t["entry_price"] - price) * t["shares"]
            # ROI = (Current Value - Invested Capital) / Invested Capital * 100,
            # where current value is your equity: invested capital plus P/L.
            roi = pl / invested * 100
            stop_breached = price < t["stop_loss"] if is_long else price > t["stop_loss"]
        rows.append(
            {
                **t,
                "position": position,
                "borrowed": borrowed,
                "invested": invested,
                "liq_price": liq_price,
                "current_price": price,
                "risk": risk,
                "roi": roi,
                "stop_breached": stop_breached,
            }
        )
    return rows


@app.route("/api/portfolio")
@login_required
def api_portfolio():
    data = load_data()
    holdings = data["holdings"]
    rows = []
    total_cost = 0.0
    total_value = 0.0
    any_price_missing = False

    for h in holdings:
        cost = h["buy_price"] * h["shares"]
        price = get_live_price(h["symbol"])
        row = {
            **h,
            "cost": cost,
            "current_price": price,
            "current_value": None,
            "gain": None,
            "gain_pct": None,
        }
        total_cost += cost
        if price is not None:
            value = price * h["shares"]
            row["current_value"] = value
            row["gain"] = value - cost
            row["gain_pct"] = (value - cost) / cost * 100 if cost else None
            total_value += value
        else:
            any_price_missing = True
        rows.append(row)

    totals = {
        "cost": total_cost,
        "value": total_value if not any_price_missing else None,
        "gain": total_value - total_cost if not any_price_missing else None,
        "gain_pct": (
            (total_value - total_cost) / total_cost * 100
            if not any_price_missing and total_cost
            else None
        ),
        "prices_incomplete": any_price_missing,
    }
    return jsonify(
        {
            "holdings": rows,
            "totals": totals,
            "trades": build_trade_rows(data["trades"]),
        }
    )


@app.route("/api/holdings", methods=["POST"])
@login_required
def add_holding():
    data = request.get_json(silent=True) or {}
    symbol = str(data.get("symbol", "")).strip().upper()
    buy_date = str(data.get("buy_date", "")).strip()
    try:
        buy_price = float(data.get("buy_price"))
        shares = float(data.get("shares"))
    except (TypeError, ValueError):
        return jsonify({"error": "Price and shares must be numbers."}), 400
    if not symbol or not buy_date:
        return jsonify({"error": "Symbol and buy date are required."}), 400
    if buy_price <= 0 or shares <= 0:
        return jsonify({"error": "Price and shares must be positive."}), 400

    data = load_data()
    data["holdings"].append(
        {
            "id": uuid.uuid4().hex,
            "symbol": symbol,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "shares": shares,
        }
    )
    save_data(data)
    return jsonify({"ok": True}), 201


@app.route("/api/holdings/<holding_id>", methods=["DELETE"])
@login_required
def delete_holding(holding_id):
    data = load_data()
    remaining = [h for h in data["holdings"] if h["id"] != holding_id]
    if len(remaining) == len(data["holdings"]):
        return jsonify({"error": "Holding not found."}), 404
    data["holdings"] = remaining
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/trades", methods=["POST"])
@login_required
def add_trade():
    payload = request.get_json(silent=True) or {}
    symbol = str(payload.get("symbol", "")).strip().upper()
    direction = str(payload.get("direction", "")).strip().capitalize()
    try:
        leverage = float(payload.get("leverage"))
        entry_price = float(payload.get("entry_price"))
        stop_loss = float(payload.get("stop_loss"))
        shares = float(payload.get("shares"))
    except (TypeError, ValueError):
        return jsonify({"error": "Leverage, prices, and shares must be numbers."}), 400
    if not symbol:
        return jsonify({"error": "Symbol is required."}), 400
    if direction not in ("Long", "Short"):
        return jsonify({"error": "Direction must be Long or Short."}), 400
    if leverage < 1:
        return jsonify({"error": "Leverage must be at least 1."}), 400
    if entry_price <= 0 or stop_loss <= 0 or shares <= 0:
        return jsonify({"error": "Prices and shares must be positive."}), 400

    data = load_data()
    data["trades"].append(
        {
            "id": uuid.uuid4().hex,
            "symbol": symbol,
            "direction": direction,
            "leverage": leverage,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "shares": shares,
        }
    )
    save_data(data)
    return jsonify({"ok": True}), 201


@app.route("/api/trades/<trade_id>", methods=["DELETE"])
@login_required
def delete_trade(trade_id):
    data = load_data()
    remaining = [t for t in data["trades"] if t["id"] != trade_id]
    if len(remaining) == len(data["trades"]):
        return jsonify({"error": "Trade not found."}), 404
    data["trades"] = remaining
    save_data(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=debug)
