"""
Crypto 1H Signal Scanner
-------------------------
Scans every USDT trading pair on Binance, checks the most recently
CLOSED 1-hour candle for a Buy/Sell style signal (EMA9/EMA21 crossover
confirmed by RSI), and emails you a summary if anything fired.

This does NOT reproduce any specific paid TradingView indicator's
proprietary formula. It uses a well-known, publicly documented
trend + momentum signal that behaves similarly to common
"sniper entry/exit" style scripts.

Runs for free on a schedule via GitHub Actions (see
.github/workflows/scan.yml) -- no server, no subscription needed.
"""

import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "1h"          # candle timeframe
CANDLE_LIMIT = 50         # how many candles to pull per coin (need ~30+ for EMA21/RSI14)
EMA_FAST = 9
EMA_SLOW = 21
RSI_LEN = 14
QUOTE_ASSET = "USDT"      # only scan pairs quoted in USDT
EXCLUDE_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")  # skip leveraged tokens
REQUEST_PAUSE = 0.08       # seconds between API calls, keeps us under Binance rate limits
# ----------------------------------------------

BINANCE_BASE = "https://data-api.binance.vision"


def get_usdt_symbols():
    """Return all actively trading spot pairs quoted in USDT, excluding leveraged tokens."""
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
    return r.json()  # list of [open_time, open, high, low, close, volume, close_time, ...]


def ema(values, length):
    k = 2 / (length + 1)
    ema_vals = [values[0]]
    for price in values[1:]:
        ema_vals.append(price * k + ema_vals[-1] * (1 - k))
    return ema_vals


def rsi(values, length):
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    if len(gains) < length:
        return [None] * len(values)

    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length
    rsi_vals = [None] * length  # pad to align index with `values`

    for i in range(length, len(gains)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length
        rs = avg_gain / avg_loss if avg_loss != 0 else float("inf")
        rsi_vals.append(100 - (100 / (1 + rs)))

    rsi_vals = [None] + rsi_vals  # align to `values` length (values has len(gains)+1 items)
    return rsi_vals


def check_signal(symbol):
    """Return 'BUY', 'SELL', or None for the most recently CLOSED candle."""
    klines = get_klines(symbol)
    if len(klines) < CANDLE_LIMIT:
        return None

    # Drop the last kline -- it's the still-forming (unclosed) current candle
    closed = klines[:-1]
    closes = [float(k[4]) for k in closed]

    if len(closes) < EMA_SLOW + 2:
        return None

    fast = ema(closes, EMA_FAST)
    slow = ema(closes, EMA_SLOW)
    rsi_vals = rsi(closes, RSI_LEN)

    # Compare the last two CLOSED candles to detect a fresh crossover
    prev_fast, curr_fast = fast[-2], fast[-1]
    prev_slow, curr_slow = slow[-2], slow[-1]
    curr_rsi = rsi_vals[-1]

    if curr_rsi is None:
        return None

    crossed_up = prev_fast <= prev_slow and curr_fast > curr_slow
    crossed_down = prev_fast >= prev_slow and curr_fast < curr_slow

    if crossed_up and curr_rsi > 50:
        return "BUY"
    if crossed_down and curr_rsi < 50:
        return "SELL"
    return None


def send_email(signals):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    lines = [f"{sym}: {sig}" for sym, sig in signals]
    body = "1H Crypto Signal Scanner found:\n\n" + "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"Crypto 1H Signals ({len(signals)} found)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Scanning {len(symbols)} USDT pairs on {INTERVAL} candles...")

    signals = []
    for symbol in symbols:
        try:
            result = check_signal(symbol)
            if result:
                signals.append((symbol, result))
                print(f"  -> {symbol}: {result}")
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    print(f"Done. {len(signals)} signal(s) found.")

    if signals:
        send_email(signals)
        print("Email sent.")
    else:
        print("No email sent (no signals this hour).")


if __name__ == "__main__":
    main()
