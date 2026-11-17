
import pandas as pd

from indicators import calculate_indicators
from config import MIN_SIGNAL_SCORE


def valid_number(value):

    try:
        return pd.notna(float(value))
    except (TypeError, ValueError):
        return False


def analyze_direction(fast, slow):

    required = [
        "ema9", "ema21", "ema50",
        "rsi", "macd", "macd_signal",
        "adx", "supertrend_direction",
        "close", "open", "volume",
        "volume_avg", "vwap"
    ]

    for field in required:
        if field not in fast or not valid_number(fast[field]):
            return 0, ["Invalid 5-minute indicator data"]

    slow_required = ["ema9", "ema21"]

    for field in slow_required:
        if field not in slow or not valid_number(slow[field]):
            return 0, ["Invalid 15-minute indicator data"]

    score = 0
    reasons = []

    # 5-minute trend
    if fast["ema9"] > fast["ema21"]:
        score += 10
        reasons.append("5m EMA bullish")

    elif fast["ema9"] < fast["ema21"]:
        score -= 10
        reasons.append("5m EMA bearish")

    # 15-minute trend
    if slow["ema9"] > slow["ema21"]:
        score += 20
        reasons.append("15m EMA bullish")

    elif slow["ema9"] < slow["ema21"]:
        score -= 20
        reasons.append("15m EMA bearish")

    # Major trend
    if fast["close"] > fast["ema50"]:
        score += 10
        reasons.append("Price above EMA50")

    elif fast["close"] < fast["ema50"]:
        score -= 10
        reasons.append("Price below EMA50")

    # VWAP
    if fast["close"] > fast["vwap"]:
        score += 10
        reasons.append("Price above VWAP")

    elif fast["close"] < fast["vwap"]:
        score -= 10
        reasons.append("Price below VWAP")

    # RSI
    if 52 <= fast["rsi"] <= 70:
        score += 10
        reasons.append("RSI bullish")

    elif 30 <= fast["rsi"] <= 48:
        score -= 10
        reasons.append("RSI bearish")

    # MACD
    if fast["macd"] > fast["macd_signal"]:
        score += 10
        reasons.append("MACD bullish")

    elif fast["macd"] < fast["macd_signal"]:
        score -= 10
        reasons.append("MACD bearish")

    # ADX trend strength
    if fast["adx"] >= 20:
        if fast["ema9"] > fast["ema21"]:
            score += 5
            reasons.append("ADX confirms bullish trend")

        elif fast["ema9"] < fast["ema21"]:
            score -= 5
            reasons.append("ADX confirms bearish trend")

    # Supertrend
    if fast["supertrend_direction"] == 1:
        score += 10
        reasons.append("Supertrend bullish")

    elif fast["supertrend_direction"] == -1:
        score -= 10
        reasons.append("Supertrend bearish")

    # Volume confirmation
    if (
        fast["volume_avg"] > 0
        and fast["volume"] > fast["volume_avg"]
    ):
        if fast["close"] > fast["open"]:
            score += 5
            reasons.append("Bullish volume confirmation")

        elif fast["close"] < fast["open"]:
            score -= 5
            reasons.append("Bearish volume confirmation")

    return score, reasons


def generate_signal(name, candles5, candles15):

    fast_df = calculate_indicators(candles5)
    slow_df = calculate_indicators(candles15)

    if fast_df is None or slow_df is None:
        return None

    fast = fast_df.iloc[-1].to_dict()
    slow = slow_df.iloc[-1].to_dict()

    score, reasons = analyze_direction(fast, slow)

    # Require both timeframes to agree.
    bullish_alignment = (
        fast["ema9"] > fast["ema21"]
        and slow["ema9"] > slow["ema21"]
    )

    bearish_alignment = (
        fast["ema9"] < fast["ema21"]
        and slow["ema9"] < slow["ema21"]
    )

    if score >= MIN_SIGNAL_SCORE and bullish_alignment:
        side = "CALL"

    elif score <= -MIN_SIGNAL_SCORE and bearish_alignment:
        side = "PUT"

    else:
        return None

    return {
        "symbol": name,
        "side": side,
        "score": abs(score),
        "reasons": reasons,
        "spot": float(fast["close"]),
        "rsi": float(fast["rsi"]),
        "adx": float(fast["adx"]),
        "vwap": float(fast["vwap"]),
        "atr": float(fast["atr"]),
        "timestamp": str(fast["timestamp"])
    }
