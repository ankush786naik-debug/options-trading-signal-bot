"""Rule-based NIFTY intraday bias report (research/paper signal only).

This module is deliberately separate from the production options entry strategy.
Its up/down/flat figures are heuristic scores, NOT calibrated probabilities.
"""
import argparse
import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config import UNDERLYINGS, ALERTS_ENABLED
from indicators import calculate_indicators
from upstox_client import UpstoxClient
from telegram_bot import send_message

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "NIFTY"
MARKET_START = time(9, 20)
MARKET_END = time(14, 45)


def _parse_time(value):
    ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def _completed(candles, interval):
    now = datetime.now(IST)
    valid = {}
    for candle in candles or []:
        if not isinstance(candle, list) or len(candle) < 6:
            continue
        try:
            start = _parse_time(candle[0])
            if start + timedelta(minutes=interval) <= now:
                valid[start] = candle
        except (TypeError, ValueError, IndexError):
            continue
    return [valid[k] for k in sorted(valid)]


def _safe(row, key):
    try:
        value = float(row[key])
        return value if math.isfinite(value) else None
    except (KeyError, TypeError, ValueError):
        return None


def _score(fast, slow):
    """Return weighted bullish/bearish points and readable reasons."""
    bull = 0.0
    bear = 0.0
    reasons = []

    def add(condition, points, label):
        nonlocal bull, bear
        if condition is True:
            bull += points
            reasons.append("Bullish: " + label)
        elif condition is False:
            bear += points
            reasons.append("Bearish: " + label)

    close = _safe(fast, "close")
    ema9 = _safe(fast, "ema9")
    ema21 = _safe(fast, "ema21")
    rsi = _safe(fast, "rsi")
    adx = _safe(fast, "adx")
    macd = _safe(fast, "macd")
    macd_signal = _safe(fast, "macd_signal")
    vwap = _safe(fast, "vwap")
    slow_close = _safe(slow, "close")
    slow_ema9 = _safe(slow, "ema9")
    slow_ema21 = _safe(slow, "ema21")

    if None in (close, ema9, ema21, rsi, macd, macd_signal, slow_close, slow_ema9, slow_ema21):
        raise ValueError("Required indicators are missing; no bias report generated.")

    add(ema9 > ema21, 2.0, "5m EMA 9/21 alignment")
    add(close > ema21, 1.0, "5m close vs EMA 21")
    add(slow_ema9 > slow_ema21, 2.5, "15m EMA 9/21 trend")
    add(macd > macd_signal, 1.5, "MACD vs signal")
    if rsi >= 55:
        bull += 1.2
        reasons.append(f"Bullish: RSI {rsi:.1f} above 55")
    elif rsi <= 45:
        bear += 1.2
        reasons.append(f"Bearish: RSI {rsi:.1f} below 45")
    if vwap is not None:
        add(close > vwap, 1.0, "price vs session VWAP")
    else:
        reasons.append("VWAP unavailable (volume may be missing/zero); excluded")
    if adx is not None and adx >= 22:
        if bull > bear:
            bull += 0.6
        elif bear > bull:
            bear += 0.6
        reasons.append(f"Trend strength: ADX {adx:.1f}")
    # Recent price impulse; no future candles are used.
    if len(fast) >= 4:
        prev_close = _safe(fast.iloc[-4], "close")
        if prev_close and close > prev_close:
            bull += 0.8
            reasons.append("Bullish: 3-candle momentum")
        elif prev_close and close < prev_close:
            bear += 0.8
            reasons.append("Bearish: 3-candle momentum")

    last_open = _safe(fast, "open")
    if last_open is not None:
        if close > last_open:
            bull += 0.4
            reasons.append("Last completed 5m candle bullish")
        elif close < last_open:
            bear += 0.4
            reasons.append("Last completed 5m candle bearish")

    return bull, bear, reasons, close, rsi, adx, vwap


def _heuristic_probabilities(bull, bear, adx):
    """Produce transparent heuristic weights; not statistically calibrated."""
    net = bull - bear
    strength = math.tanh(abs(net) / 5.0)
    flat = 0.22 + 0.36 * (1.0 - strength)
    if adx is None or adx < 18:
        flat += 0.08
    flat = min(0.62, max(0.18, flat))
    directional = 1.0 - flat
    directional_split = 0.5 + 0.45 * math.tanh(net / 5.0)
    up = directional * directional_split
    down = directional - up
    values = [round(up * 100), round(down * 100), round(flat * 100)]
    # Keep rounded totals exactly 100.
    values[2] += 100 - sum(values)
    return values[0], values[1], values[2]


def build_message(fast_df, slow_df):
    fast = fast_df.iloc[-1]
    slow = slow_df.iloc[-1]
    bull, bear, reasons, spot, rsi, adx, vwap = _score(fast_df, slow)
    up, down, flat = _heuristic_probabilities(bull, bear, adx)

    if max(up, down) >= 55 and abs(bull - bear) >= 2.0:
        bias = "CALL BIAS" if up > down else "PUT BIAS"
    else:
        bias = "WAIT / NO EDGE"

    return (
        f"📊 NIFTY INTRADAY BIAS (PAPER)\n"
        f"Time: {datetime.now(IST):%d-%b-%Y %H:%M IST}\n"
        f"Spot (last completed 5m): {spot:.2f}\n"
        f"Heuristic estimate — NOT calibrated: UP {up}% | DOWN {down}% | FLAT {flat}%\n"
        f"Bias: {bias}\n"
        f"5m RSI: {rsi:.1f} | ADX: {adx if adx is not None else 'N/A'}\n"
        f"VWAP: {vwap if vwap is not None else 'unavailable'}\n"
        f"15m trend: {'Bullish' if _safe(slow, 'ema9') > _safe(slow, 'ema21') else 'Bearish'}\n"
        f"Key rule: use the existing completed-candle setup + liquid ATM/ITM option filter; "
        f"do not buy solely from this bias.\n\n"
        f"Reasons:\n- " + "\n- ".join(reasons) +
        "\n\nMODE: SIGNAL/PAPER ONLY — no live order."
    )


def run(send_telegram=False):
    now = datetime.now(IST)
    if now.weekday() >= 5 or not (MARKET_START <= now.time() <= MARKET_END):
        return (
            f"NO LIVE INTRADAY SIGNAL — outside scan window "
            f"(09:20–14:45 IST). Current time: {now:%d-%b %H:%M IST}"
        )

    client = UpstoxClient()
    instrument = UNDERLYINGS[SYMBOL]
    candles5 = _completed(client.intraday_candles(instrument, 5), 5)
    candles15 = _completed(client.intraday_candles(instrument, 15), 15)

    if len(candles5) < 50 or len(candles15) < 50:
        return f"DATA WAIT — insufficient completed candles (5m={len(candles5)}, 15m={len(candles15)})"

    # Reject stale data so a delayed API response cannot create a fresh-looking signal.
    if now - (_parse_time(candles5[-1][0]) + timedelta(minutes=5)) > timedelta(minutes=10):
        return "DATA WAIT — latest completed 5m candle is stale."

    fast_df = calculate_indicators(candles5)
    slow_df = calculate_indicators(candles15)
    if fast_df is None or slow_df is None:
        return "DATA WAIT — indicators could not be calculated."

    message = build_message(fast_df, slow_df)
    if send_telegram:
        if not ALERTS_ENABLED:
            raise RuntimeError("Telegram alerts are disabled in config; enable explicitly before using --telegram.")
        send_message(message)
    return message


def main():
    parser = argparse.ArgumentParser(description="NIFTY intraday technical bias report (paper only).")
    parser.add_argument("--telegram", action="store_true", help="Send report to Telegram; requires ALERTS_ENABLED=true.")
    args = parser.parse_args()
    print(run(send_telegram=args.telegram))


if __name__ == "__main__":
    main()
