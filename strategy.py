from indicators import calculate_indicators
from config import MIN_SIGNAL_SCORE


def analyze_direction(fast, slow):

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
    elif fast["close"] < fast["ema50"]:
        score -= 10

    # VWAP
    if fast["close"] > fast["vwap"]:
        score += 10
    elif fast["close"] < fast["vwap"]:
        score -= 10

    # RSI
    if 52 <= fast["rsi"] <= 70:
        score += 10
    elif 30 <= fast["rsi"] <= 48:
        score -= 10

    # MACD
    if fast["macd"] > fast["macd_signal"]:
        score += 10
    elif fast["macd"] < fast["macd_signal"]:
        score -= 10

    # ADX
    if fast["adx"] >= 20:
        if fast["ema9"] > fast["ema21"]:
            score += 5
        elif fast["ema9"] < fast["ema21"]:
            score -= 5

    # Supertrend
    if fast["supertrend_direction"] == 1:
        score += 10
    else:
        score -= 10

    # Volume
    if (
        fast["volume"] > fast["volume_avg"]
        and fast["volume_avg"] > 0
    ):
        if fast["close"] > fast["open"]:
            score += 5
        elif fast["close"] < fast["open"]:
            score -= 5

    return score, reasons


def generate_signal(name, candles5, candles15):

    fast_df = calculate_indicators(candles5)
    slow_df = calculate_indicators(candles15)

    if fast_df is None or slow_df is None:
        return None

    fast = fast_df.iloc[-1].to_dict()
    slow = slow_df.iloc[-1].to_dict()

    score, reasons = analyze_direction(fast, slow)

    if score >= MIN_SIGNAL_SCORE:
        side = "CALL"

    elif score <= -MIN_SIGNAL_SCORE:
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
