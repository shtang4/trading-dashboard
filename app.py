"""Simple stock portfolio dashboard.

Holdings are stored in portfolio.json next to this file. Live prices come
from Yahoo Finance via the yfinance library.

Run with:  python app.py   then open http://127.0.0.1:5000
"""

import json
import time
import uuid
from pathlib import Path
from threading import Lock

import yfinance as yf
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"
_file_lock = Lock()

# Cache prices for a minute so refreshing the page doesn't hammer Yahoo.
PRICE_CACHE_SECONDS = 60
_price_cache = {}  # symbol -> (timestamp, price or None)


def load_data():
    with _file_lock:
        if PORTFOLIO_FILE.exists():
            data = json.loads(PORTFOLIO_FILE.read_text())
            # Older versions stored a bare list of holdings.
            if isinstance(data, list):
                data = {"holdings": data, "trades": []}
            data.setdefault("holdings", [])
            data.setdefault("trades", [])
            return data
        return {"holdings": [], "trades": []}


def save_data(data):
    with _file_lock:
        PORTFOLIO_FILE.write_text(json.dumps(data, indent=2))


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
def index():
    return render_template("index.html")


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
    """
    rows = []
    for t in trades:
        position = t["entry_price"] * t["shares"]
        borrowed = position * (1 - 1 / t["leverage"])
        price = get_live_price(t["symbol"])
        risk = None
        if price is not None:
            if t["direction"] == "Long":
                diff = price - t["stop_loss"]
            else:
                diff = t["stop_loss"] - price
            risk = diff * t["shares"]
        rows.append(
            {
                **t,
                "position": position,
                "borrowed": borrowed,
                "current_price": price,
                "risk": risk,
            }
        )
    return rows


@app.route("/api/portfolio")
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
def delete_holding(holding_id):
    data = load_data()
    remaining = [h for h in data["holdings"] if h["id"] != holding_id]
    if len(remaining) == len(data["holdings"]):
        return jsonify({"error": "Holding not found."}), 404
    data["holdings"] = remaining
    save_data(data)
    return jsonify({"ok": True})


@app.route("/api/trades", methods=["POST"])
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
def delete_trade(trade_id):
    data = load_data()
    remaining = [t for t in data["trades"] if t["id"] != trade_id]
    if len(remaining) == len(data["trades"]):
        return jsonify({"error": "Trade not found."}), 404
    data["trades"] = remaining
    save_data(data)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
