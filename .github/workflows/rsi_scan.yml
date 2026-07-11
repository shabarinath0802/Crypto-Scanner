"""
Crypto 1H RSI Overbought Scanner
----------------------------------
Every 5 minutes, checks the LIVE (still-forming) 1H candle's RSI for every
USDT pair on Binance. Emails you the list of coins currently above the
RSI threshold (default 95).

Remembers which coins it already alerted on (in state.json) so you get
ONE email when a coin first crosses above the threshold, not a repeat
every 5 minutes while it stays there. It resets automatically once RSI
drops back below the threshold, so a fresh cross-up will alert again.
"""

import json
import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "1h"
CANDLE_LIMIT = 50
RSI_LEN = 14
RSI_THRESHOLD = 95
QUOTE_ASSET = "USDT"
EXCLUDE_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")
REQUEST_PAUSE = 0.08
STATE_FILE = "rsi_state.json"
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


def rsi(values, length):
    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    if len(gains) < length:
        return None

    avg_gain = sum(gains[:length]) / length
    avg_loss = sum(losses[:length]) / length

    for i in range(length, len(gains)):
        avg_gain = (avg_gain * (length - 1) + gains[i]) / length
        avg_loss = (avg_loss * (length - 1) + losses[i]) / length

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_live_rsi(symbol):
    """RSI using the current still-forming candle's live price as the last value."""
    klines = get_klines(symbol)
    if len(klines) < RSI_LEN + 2:
        return None
    closes = [float(k[4]) for k in klines]  # last entry = live/forming candle
    return rsi(closes, RSI_LEN)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_email(overbought):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    lines = [f"{sym}: RSI {value:.1f}" for sym, value in overbought]
    body = f"Coins with 1H RSI above {RSI_THRESHOLD}:\n\n" + "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"RSI Overbought Alert ({len(overbought)} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Checking live RSI on {len(symbols)} USDT pairs...")

    state = load_state()
    new_alerts = []

    for symbol in symbols:
        try:
            value = get_live_rsi(symbol)
            if value is None:
                continue

            was_alerted = state.get(symbol, False)

            if value > RSI_THRESHOLD and not was_alerted:
                new_alerts.append((symbol, value))
                state[symbol] = True
                print(f"  -> {symbol}: RSI {value:.1f} (NEW alert)")
            elif value <= RSI_THRESHOLD and was_alerted:
                state[symbol] = False  # reset so it can alert again next time
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    save_state(state)
    print(f"Done. {len(new_alerts)} new overbought alert(s).")

    if new_alerts:
        send_email(new_alerts)
        print("Email sent.")
    else:
        print("No email sent (no new overbought coins this run).")


if __name__ == "__main__":
    main()
