from datetime import datetime
from zoneinfo import ZoneInfo

from config import MIN_SIGNAL_SCORE, MAX_SPREAD_PCT


def ema(values, period):

    if len(values) < period:
        return None

    alpha = 2 / (period + 1)

    result = sum(values[:period]) / period

    for value in values[period:]:
        result = (
            value * alpha +
            result * (1 - alpha)
        )

    return result


def calculate_rsi(values, period=14):

    if len(values) <= period:
        return None

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes[-period:]]
    losses = [max(-x, 0) for x in changes[-period:]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss

    return 100 - (100 / (1 + rs))


def analyze_candles(candles):

    candles = sorted(candles, key=lambda x: x[0])

    closes = [
        float(candle[4])
        for candle in candles
        if len(candle) >= 5
    ]

    if len(closes) < 30:
        return None

    return {
        "close": closes[-1],
        "ema9": ema(closes, 9),
        "ema21": ema(closes, 21),
        "rsi": calculate_rsi(closes)
    }


def select_option(chain, side):

    field = (
        "call_options"
        if side == "CALL"
        else "put_options"
    )

    valid_options = []

    for row in chain:

        option = row.get(field) or {}
        market = option.get("market_data") or {}

        ltp = float(market.get("ltp") or 0)
        bid = float(market.get("bid_price") or 0)
        ask = float(market.get("ask_price") or 0)

        spot = float(
            row.get("underlying_spot_price") or 0
        )

        strike = float(row.get("strike_price") or 0)

        if ltp <= 0 or strike <= 0 or spot <= 0:
            continue

        if bid <= 0 or ask <= 0:
            continue

        if ask < bid:
            continue

        spread = ((ask - bid) / ltp) * 100

        if spread > MAX_SPREAD_PCT:
            continue

        valid_options.append({
            "distance": abs(strike - spot),
            "strike": strike,
            "expiry": row.get("expiry", ""),
            "instrument_key": option.get("instrument_key"),
            "ltp": ltp,
            "entry": ask,
            "spread": spread
        })

    if not valid_options:
        return None

    selected = min(
        valid_options,
        key=lambda x: x["distance"]
    )

    entry = selected["entry"]

    return {
        **selected,
        "stop_loss": round(entry * 0.80, 2),
        "target_1": round(entry * 1.20, 2),
        "target_2": round(entry * 1.35, 2)
    }


def generate_signal(name, candles5, candles15, chain):

    fast = analyze_candles(candles5)
    slow = analyze_candles(candles15)

    if not fast or not slow:
        return None

    score = 0
    side = None

    if fast["ema9"] > fast["ema21"]:
        score += 1

    if slow["ema9"] > slow["ema21"]:
        score += 2

    if 52 <= fast["rsi"] <= 70:
        score += 1

    if fast["close"] > fast["ema9"]:
        score += 1

    if score >= MIN_SIGNAL_SCORE:
        side = "CALL"

    else:

        score = 0

        if fast["ema9"] < fast["ema21"]:
            score += 1

        if slow["ema9"] < slow["ema21"]:
            score += 2

        if 30 <= fast["rsi"] <= 48:
            score += 1

        if fast["close"] < fast["ema9"]:
            score += 1

        if score >= MIN_SIGNAL_SCORE:
            side = "PUT"

    if not side:
        return None

    option = select_option(chain, side)

    if not option:
        return None

    return {
        "symbol": name,
        "side": side,
        "score": score,
        "spot": fast["close"],
        "rsi": fast["rsi"],
        "timestamp": datetime.now(
            ZoneInfo("Asia/Kolkata")
        ).isoformat(timespec="seconds"),
        **option
    }
  
