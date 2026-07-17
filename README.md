# Trading Dashboard

A simple stock portfolio dashboard built with Python (Flask) and HTML.

Enter each stock you own — symbol, date bought, price paid, and number of
shares — and the dashboard fetches the current live price from Yahoo Finance
(via the `yfinance` library) to show each position's current value plus your
total portfolio value and total profit/loss.

A second table tracks leveraged trades: symbol, direction (Long/Short),
leverage ratio, entry price, stop loss, and shares. For each trade it
computes the amount borrowed (`Entry × Shares × (1 − 1/Leverage)`) and the
risk if the stop is hit (`(Current Price − Stop Loss) × Shares × Leverage`,
reversed for shorts).

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Then open http://127.0.0.1:5000 in your browser.

## Notes

- Holdings are saved to `portfolio.json` in the project folder, so your
  portfolio persists between restarts.
- Live prices are cached for 60 seconds; click **Refresh prices** to re-fetch.
- If Yahoo Finance is temporarily unreachable, the affected rows show "—"
  and totals wait until all prices load.
