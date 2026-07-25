"""
Crypto 15m EMA55 Breakdown Scanner
------------------------------------
Scans every USDT pair on Binance. On the most recently CLOSED 15-minute
candle, checks whether EMA55 has just crossed BELOW all three of
EMA8, EMA13, and EMA21 (i.e. it was at/above at least one of them on
the prior candle, and is now below all three). Emails you the list of
coins where this just happened.

Runs once per 15-minute candle close via GitHub Actions (:01, :16, :31,
:46) -- no persistent memory needed, since a fresh cross only happens
once per transition and this schedule naturally prevents repeat alerts
for the same cross.
"""

import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "15m"
CANDLE_LIMIT = 100         # need enough history for EMA55 to be accurate
EMA_LENGTHS = [8, 13, 21, 55]
LONG_EMA = 55
SHORT_EMAS = [8, 13, 21]
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
    """Return True if EMA55 just crossed below EMA8, EMA13, and EMA21 on the last closed candle."""
    klines = get_klines(symbol)
    if len(klines) < CANDLE_LIMIT:
        return False

    # Drop the last kline -- it's the still-forming (unclosed) current candle
    closed = klines[:-1]
    closes = [float(k[4]) for k in closed]

    if len(closes) < LONG_EMA + 2:
        return False

    emas = {length: ema(closes, length) for length in EMA_LENGTHS}

    prev_long = emas[LONG_EMA][-2]
    curr_long = emas[LONG_EMA][-1]

    prev_shorts = [emas[length][-2] for length in SHORT_EMAS]
    curr_shorts = [emas[length][-1] for length in SHORT_EMAS]

    was_below_all = all(prev_long < s for s in prev_shorts)
    is_below_all = all(curr_long < s for s in curr_shorts)

    # Fresh cross: wasn't below all three before, but is below all three now
    return is_below_all and not was_below_all


def send_email(symbols):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    body = "EMA55 just crossed BELOW EMA8, EMA13, and EMA21 on the 15m candle for:\n\n" + "\n".join(symbols)

    msg = MIMEText(body)
    msg["Subject"] = f"15m EMA55 Breakdown Alert ({len(symbols)} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Scanning {len(symbols)} USDT pairs on {INTERVAL} candles for EMA55 breakdown...")

    hits = []
    for symbol in symbols:
        try:
            if check_signal(symbol):
                hits.append(symbol)
                print(f"  -> {symbol}: EMA55 crossed below EMA8/13/21")
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    print(f"Done. {len(hits)} coin(s) found.")

    if hits:
        send_email(hits)
        print("Email sent.")
    else:
        print("No email sent (no breakdowns this candle).")


if __name__ == "__main__":
    main()
