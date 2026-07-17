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


def load_holdings():
    with _file_lock:
        if PORTFOLIO_FILE.exists():
            return json.loads(PORTFOLIO_FILE.read_text())
        return []


def save_holdings(holdings):
    with _file_lock:
        PORTFOLIO_FILE.write_text(json.dumps(holdings, indent=2))


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


@app.route("/api/portfolio")
def api_portfolio():
    holdings = load_holdings()
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
    return jsonify({"holdings": rows, "totals": totals})


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

    holdings = load_holdings()
    holdings.append(
        {
            "id": uuid.uuid4().hex,
            "symbol": symbol,
            "buy_date": buy_date,
            "buy_price": buy_price,
            "shares": shares,
        }
    )
    save_holdings(holdings)
    return jsonify({"ok": True}), 201


@app.route("/api/holdings/<holding_id>", methods=["DELETE"])
def delete_holding(holding_id):
    holdings = load_holdings()
    remaining = [h for h in holdings if h["id"] != holding_id]
    if len(remaining) == len(holdings):
        return jsonify({"error": "Holding not found."}), 404
    save_holdings(remaining)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
