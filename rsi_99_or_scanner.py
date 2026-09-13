"""
Crypto 1H OR 4H RSI 99 Scanner
----------------------------------
Every 5 minutes, checks the LIVE (still-forming) candle's RSI on the
1-hour and 4-hour timeframes for every USDT pair on Binance. Emails
you the list of coins where RSI is above 99 on EITHER timeframe
(doesn't need to be both at once).

NOTE: no duplicate prevention -- it will email you again every single
run (every 5 minutes) for as long as a coin keeps meeting the
condition, as requested.
"""

import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
CANDLE_LIMIT = 50
RSI_LEN = 14
RSI_THRESHOLD = 99
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


def get_klines(symbol, interval):
    url = f"{BINANCE_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": CANDLE_LIMIT}
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


def get_live_rsi(symbol, interval):
    """RSI using the current still-forming candle's live price as the last value."""
    klines = get_klines(symbol, interval)
    if len(klines) < RSI_LEN + 2:
        return None
    closes = [float(k[4]) for k in klines]  # last entry = live/forming candle
    return rsi(closes, RSI_LEN)


def send_email(hits):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    lines = []
    for sym, rsi1h, rsi4h in hits:
        parts = []
        if rsi1h is not None and rsi1h > RSI_THRESHOLD:
            parts.append(f"1H RSI {rsi1h:.1f}")
        if rsi4h is not None and rsi4h > RSI_THRESHOLD:
            parts.append(f"4H RSI {rsi4h:.1f}")
        lines.append(f"{sym}: " + " | ".join(parts))

    body = f"Coins with RSI above {RSI_THRESHOLD} on 1H or 4H:\n\n" + "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = f"1H/4H RSI 99 Alert ({len(hits)} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Checking live 1H + 4H RSI on {len(symbols)} USDT pairs...")

    hits = []
    for symbol in symbols:
        try:
            rsi_1h = get_live_rsi(symbol, "1h")
            rsi_4h = get_live_rsi(symbol, "4h")

            hit_1h = rsi_1h is not None and rsi_1h > RSI_THRESHOLD
            hit_4h = rsi_4h is not None and rsi_4h > RSI_THRESHOLD

            if hit_1h or hit_4h:
                hits.append((symbol, rsi_1h, rsi_4h))
                print(f"  -> {symbol}: 1H RSI {rsi_1h} | 4H RSI {rsi_4h}")
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    print(f"Done. {len(hits)} coin(s) meeting the condition.")

    if hits:
        send_email(hits)
        print("Email sent.")
    else:
        print("No email sent (no coins meeting the condition this run).")


if __name__ == "__main__":
    main()
