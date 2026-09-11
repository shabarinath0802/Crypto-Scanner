"""
Crypto 5m EMA5 No-Touch Scanner
-----------------------------------
Scans every USDT pair on Binance. On the most recently CLOSED 5-minute
candle, checks whether the candle stayed entirely ABOVE the EMA5 line
-- i.e. its low never touched or dipped down to EMA5. This flags clean,
strong bullish candles with no pullback to the average.

Runs once per 5-minute candle close via GitHub Actions (:01, :06, :11,
etc.) -- no persistent memory needed, since each run checks a fresh
closed candle and naturally won't repeat.
"""

import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "5m"
CANDLE_LIMIT = 50
EMA_LEN = 5
QUOTE_ASSET = "USDT"
EXCLUDE_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")
REQUEST_PAUSE = 0.08
# ----------------------------------------------

BINANCE_BASE = "https://data-api.binance.vision"


def get_usdt_symbols():
    url = f"{BINANCE_BASE}/api/v3/exchangeInfo"
    data = requests.get(url, timeout=15).json()
    if "symbols" not in data:
        raise RuntimeError(f"Binance did not return coin data. Response was: {data}")
    symbols = []
    for s in data["symbols"]:
        if (
            s["quoteAsset"] == QUOTE_ASSET
            and s["status"] == "TRADING"
            and s["isSpotTradingAllowed"]
            and not any(kw in s["baseAsset"] for kw in EXCLUDE_KEYWORDS)
        ):
            symbols.append(s["symbol"])
    return symbols


def get_klines(symbol):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": INTERVAL, "limit": CANDLE_LIMIT}
    r = requests.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def ema(values, length):
    k = 2 / (length + 1)
    ema_vals = [values[0]]
    for price in values[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals


def check_signal(symbol):
    """Return True if the last closed candle stayed entirely above EMA5 (no touch)."""
    klines = get_klines(symbol)
    if len(klines) < CANDLE_LIMIT:
        return False

    closed = klines[:-1]  # drop the still-forming current candle
    if len(closed) < EMA_LEN + 2:
        return False

    closes = [float(k[4]) for k in closed]
    ema5_series = ema(closes, EMA_LEN)

    last_candle_low = float(closed[-1][3])
    last_ema5 = ema5_series[-1]

    return last_candle_low > last_ema5


def send_email(symbols):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO_EMA5"]

    body = "Candle stayed above EMA5 (no touch) on the 5m candle for:\n\n" + "\n".join(symbols)

    msg = MIMEText(body)
    msg["Subject"] = f"5m EMA5 No-Touch Alert ({len(symbols)} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Scanning {len(symbols)} USDT pairs on {INTERVAL} candles for EMA5 no-touch...")

    hits = []
    for symbol in symbols:
        try:
            if check_signal(symbol):
                hits.append(symbol)
                print(f"  -> {symbol}: candle stayed above EMA5")
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    print(f"Done. {len(hits)} coin(s) found.")

    if hits:
        send_email(hits)
        print("Email sent.")
    else:
        print("No email sent (no matches this candle).")


if __name__ == "__main__":
    main()
