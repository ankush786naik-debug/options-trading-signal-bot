import logging
import pandas as pd

from indicators import calculate_indicators

logger = logging.getLogger(__name__)

# Strategy defaults requested for the option-buying signal setup.
ADX_MIN = 22.0
CALL_RSI_MIN = 60.0
CALL_RSI_MAX = 75.0
PUT_RSI_MIN = 25.0
PUT_RSI_MAX = 40.0
PULLBACK_LOOKBACK = 3
PULLBACK_ATR_TOLERANCE = 0.25


def _finite(row, fields):
    for field in fields:
        try:
            value = float(row[field])
            if not pd.notna(value):
                return False
        except (KeyError, TypeError, ValueError):
            return False
    return True


def _near_level(candles, level, tolerance):
    """True if any candle in the window traded within tolerance of level."""
    if not pd.notna(level):
        return False
    lows = pd.to_numeric(candles["low"], errors="coerce")
    highs = pd.to_numeric(candles["high"], errors="coerce")
    return bool(((lows <= level + tolerance) & (highs >= level - tolerance)).any())


def analyze_setup(fast_df, slow_df, name="INDEX"):
    """Evaluate completed 5m candles with 15m EMA trend confirmation."""
    required_fast = [
        "open", "high", "low", "close", "volume", "volume_avg",
        "ema9", "ema21", "rsi", "adx", "atr", "vwap"
    ]
    required_slow = ["ema9", "ema21", "close"]

    if fast_df is None or slow_df is None:
        return None
    if len(fast_df) < 4 or len(slow_df) < 1:
        return None

    fast = fast_df.iloc[-1]
    slow = slow_df.iloc[-1]
    if not _finite(fast, required_fast) or not _finite(slow, required_slow):
        logger.info("%s: invalid or incomplete indicator data", name)
        return None

    # The three candles before the trigger candle must show a pullback
    # near one of the dynamic levels.
    pullback = fast_df.iloc[-(PULLBACK_LOOKBACK + 1):-1]
    if len(pullback) != PULLBACK_LOOKBACK:
        return None

    tolerance = max(float(fast["atr"]) * PULLBACK_ATR_TOLERANCE, 0.01)
    levels = {
        "EMA 9": float(fast["ema9"]),
        "EMA 21": float(fast["ema21"]),
        "VWAP": float(fast["vwap"]),
    }
    touched = [
        label for label, level in levels.items()
        if _near_level(pullback, level, tolerance)
    ]
    if not touched:
        return None

    bullish = (
        float(fast["close"]) > float(fast["vwap"])
        and float(fast["ema9"]) > float(fast["ema21"])
        and float(fast["adx"]) > ADX_MIN
        and CALL_RSI_MIN < float(fast["rsi"]) < CALL_RSI_MAX
        and float(slow["ema9"]) > float(slow["ema21"])
        and float(fast["close"]) > float(fast["open"])
    )
    bearish = (
        float(fast["close"]) < float(fast["vwap"])
        and float(fast["ema9"]) < float(fast["ema21"])
        and float(fast["adx"]) > ADX_MIN
        and PUT_RSI_MIN < float(fast["rsi"]) < PUT_RSI_MAX
        and float(slow["ema9"]) < float(slow["ema21"])
        and float(fast["close"]) < float(fast["open"])
    )

    if not bullish and not bearish:
        return None

    side = "CALL" if bullish else "PUT"
    reasons = [
        "Price " + ("above" if bullish else "below") + " session VWAP",
        "5m EMA 9/21 " + ("bullish" if bullish else "bearish"),
        "15m EMA 9/21 confirms " + ("bullish" if bullish else "bearish"),
        f"ADX {float(fast['adx']):.2f} > {ADX_MIN:g}",
        f"RSI {float(fast['rsi']):.2f} in entry range",
        "Prior pullback near " + ", ".join(touched),
        "Completed candle " + ("bullish" if bullish else "bearish"),
    ]

    return {
        "symbol": name,
        "side": side,
        "score": 100,
        "reasons": reasons,
        "spot": float(fast["close"]),
        "rsi": float(fast["rsi"]),
        "adx": float(fast["adx"]),
        "vwap": float(fast["vwap"]),
        "atr": float(fast["atr"]),
        "ema9": float(fast["ema9"]),
        "ema21": float(fast["ema21"]),
        "higher_timeframe_trend": "Bullish" if bullish else "Bearish",
        "pullback_levels": touched,
        "timestamp": str(fast["timestamp"]),
    }


def generate_signal(name, candles5, candles15):
    fast_df = calculate_indicators(candles5)
    slow_df = calculate_indicators(candles15)
    signal = analyze_setup(fast_df, slow_df, name)

    if signal:
        logger.info(
            "%s VALID %s SETUP | RSI=%.2f ADX=%.2f VWAP=%.2f | %s",
            name, signal["side"], signal["rsi"], signal["adx"],
            signal["vwap"], ", ".join(signal["pullback_levels"])
        )
    else:
        logger.info("%s: no signal; strategy conditions not all satisfied", name)

    return signal
