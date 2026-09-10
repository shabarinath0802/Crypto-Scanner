"""
Crypto 4H EMA55 Support Touch Scanner
----------------------------------------
Every 5 minutes, checks every USDT pair on Binance for this setup on
the 4-hour timeframe:

  1. UPTREND STRUCTURE: EMA55 sits BELOW all three of EMA8, EMA13,
     EMA21 (based on the last fully closed 4H candle -- stable values).
  2. PRICE TOUCH: the current, still-forming 4H candle's price range
     (low to high) touches the EMA55 level -- i.e. price has pulled
     back down to the EMA55 "support" line.
  3. VOLUME: 24h trading volume must be above $50M (liquidity filter).

Emails you the list of coins where this is happening right now.

Remembers which coins it already alerted on (so you get ONE email
per touch, not a repeat every 5 minutes while price sits on the
line). Resets automatically once price moves away from EMA55, so a
fresh pullback/touch later will alert again.
"""

import json
import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "4h"
CANDLE_LIMIT = 100        # need enough closed history for EMA55 to be accurate
EMA_LENGTHS = [8, 13, 21, 55]
LONG_EMA = 55
SHORT_EMAS = [8, 13, 21]
QUOTE_ASSET = "USDT"
EXCLUDE_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")
REQUEST_PAUSE = 0.08
STATE_FILE = "ema_touch_4h_state.json"
MIN_VOLUME_USD = 50_000_000   # only scan coins with at least this much 24h trading volume
# ----------------------------------------------

BINANCE_BASE = "https://data-api.binance.vision"


def get_24h_volumes():
    """Return {symbol: 24h quote volume in USD} for every symbol, in one call."""
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    data = requests.get(url, timeout=20).json()
    return {item["symbol"]: float(item["quoteVolume"]) for item in data if "symbol" in item and "quoteVolume" in item}


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
    """Return (True, ema55_value) if price is touching EMA55 during a bullish alignment."""
    klines = get_klines(symbol)
    if len(klines) < CANDLE_LIMIT:
        return False, None

    closed = klines[:-1]           # fully closed candles, used for stable EMA values
    forming = klines[-1]           # the current, still-in-progress candle

    closes = [float(k[4]) for k in closed]
    if len(closes) < LONG_EMA + 2:
        return False, None

    emas = {length: ema(closes, length)[-1] for length in EMA_LENGTHS}
    ema55 = emas[LONG_EMA]
    shorts = [emas[length] for length in SHORT_EMAS]

    is_bullish_alignment = all(ema55 < s for s in shorts)
    if not is_bullish_alignment:
        return False, None

    forming_low = float(forming[3])
    forming_high = float(forming[2])
    is_touching = forming_low <= ema55 <= forming_high

    return is_touching, ema55


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def send_email(hits):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    lines = [f"{sym}: EMA55 @ {value:.6g}" for sym, value in hits]
    body = "Price touched EMA55 support (bullish alignment) on the 4H candle for:\n\n" + "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"4H EMA55 Support Touch ({len(hits)} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    volumes = get_24h_volumes()
    symbols = [s for s in symbols if volumes.get(s, 0) > MIN_VOLUME_USD]
    print(f"Checking {len(symbols)} USDT pairs (24h volume > ${MIN_VOLUME_USD:,.0f}) on {INTERVAL} candles for EMA55 support touch...")

    state = load_state()
    new_hits = []

    for symbol in symbols:
        try:
            touching, ema55_value = check_signal(symbol)
            was_alerted = state.get(symbol, False)

            if touching and not was_alerted:
                new_hits.append((symbol, ema55_value))
                state[symbol] = True
                print(f"  -> {symbol}: touching EMA55 @ {ema55_value:.6g} (NEW)")
            elif not touching and was_alerted:
                state[symbol] = False  # price moved away -- allow a fresh alert next touch
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    save_state(state)
    print(f"Done. {len(new_hits)} new touch(es) found.")

    if new_hits:
        send_email(new_hits)
        print("Email sent.")
    else:
        print("No email sent (no new touches this run).")


if __name__ == "__main__":
    main()
