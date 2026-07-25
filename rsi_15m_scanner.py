"""
Crypto 15m RSI Extreme Scanner
--------------------------------
Every 5 minutes (the fastest GitHub Actions allows), checks the LIVE
(still-forming) 15-minute candle's RSI for every USDT pair on Binance.
Emails you coins where RSI has crossed:
  - above 95 (overbought), or
  - below 5 (oversold)

Remembers what it already alerted on (separately for each direction)
so you get ONE email per fresh cross, not a repeat every 5 minutes
while a coin sits at the extreme. Resets automatically once RSI moves
back into the normal range, so a fresh cross will alert again.
"""

import json
import os
import smtplib
import time
from email.mime.text import MIMEText

import requests

# ---------- Settings you can tweak ----------
INTERVAL = "15m"
CANDLE_LIMIT = 50
RSI_LEN = 14
OVERBOUGHT = 95
OVERSOLD = 5
QUOTE_ASSET = "USDT"
EXCLUDE_KEYWORDS = ("UP", "DOWN", "BULL", "BEAR")
REQUEST_PAUSE = 0.08
STATE_FILE = "rsi_15m_state.json"
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


def send_email(overbought_list, oversold_list):
    sender = os.environ["EMAIL_FROM"]
    password = os.environ["EMAIL_APP_PASSWORD"]
    recipient = os.environ["EMAIL_TO"]

    parts = []
    if overbought_list:
        parts.append(f"OVERBOUGHT (RSI > {OVERBOUGHT}):")
        parts += [f"  {sym}: RSI {value:.1f}" for sym, value in overbought_list]
    if oversold_list:
        parts.append(f"OVERSOLD (RSI < {OVERSOLD}):")
        parts += [f"  {sym}: RSI {value:.1f}" for sym, value in oversold_list]

    body = "15m RSI Extreme Scanner:\n\n" + "\n".join(parts)
    total = len(overbought_list) + len(oversold_list)

    msg = MIMEText(body)
    msg["Subject"] = f"15m RSI Extreme Alert ({total} coins)"
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient], msg.as_string())


def main():
    symbols = get_usdt_symbols()
    print(f"Checking live 15m RSI on {len(symbols)} USDT pairs...")

    state = load_state()
    new_overbought = []
    new_oversold = []

    for symbol in symbols:
        try:
            value = get_live_rsi(symbol)
            if value is None:
                continue

            sym_state = state.get(symbol, {"overbought": False, "oversold": False})

            # Overbought side
            if value > OVERBOUGHT and not sym_state["overbought"]:
                new_overbought.append((symbol, value))
                sym_state["overbought"] = True
                print(f"  -> {symbol}: RSI {value:.1f} (NEW overbought)")
            elif value <= OVERBOUGHT and sym_state["overbought"]:
                sym_state["overbought"] = False

            # Oversold side
            if value < OVERSOLD and not sym_state["oversold"]:
                new_oversold.append((symbol, value))
                sym_state["oversold"] = True
                print(f"  -> {symbol}: RSI {value:.1f} (NEW oversold)")
            elif value >= OVERSOLD and sym_state["oversold"]:
                sym_state["oversold"] = False

            state[symbol] = sym_state
        except Exception as e:
            print(f"  ! {symbol} skipped ({e})")
        time.sleep(REQUEST_PAUSE)

    save_state(state)
    total = len(new_overbought) + len(new_oversold)
    print(f"Done. {total} new extreme alert(s).")

    if total:
        send_email(new_overbought, new_oversold)
        print("Email sent.")
    else:
        print("No email sent (no new extremes this run).")


if __name__ == "__main__":
    main()
