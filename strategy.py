"""DTP + EMA20/EMA50 index-options signal strategy."""
import logging
import pandas as pd
from indicators import calculate_indicators

logger = logging.getLogger(__name__)


def analyze_setup(indicator_df, name="INDEX"):
    """Return a signal only on a confirmed DTP flip with EMA20/50 alignment."""
    if indicator_df is None or len(indicator_df) < 2:
        return None
    row = indicator_df.iloc[-1]
    required = ["timestamp", "close", "atr14", "ema20", "ema50", "dtp_state", "dtp_buy", "dtp_sell"]
    for field in required:
        try:
            if pd.isna(row[field]):
                return None
        except (KeyError, TypeError):
            return None

    bullish = bool(row["dtp_buy"]) and float(row["ema20"]) > float(row["ema50"])
    bearish = bool(row["dtp_sell"]) and float(row["ema20"]) < float(row["ema50"])
    if not bullish and not bearish:
        return None

    side = "CALL" if bullish else "PUT"
    spot = float(row["close"])
    atr = float(row["atr14"])
    if not pd.notna(atr) or atr <= 0:
        return None
    stop = spot - 1.5 * atr if bullish else spot + 1.5 * atr
    target = spot + 3.0 * atr if bullish else spot - 3.0 * atr
    trend = "Bullish" if bullish else "Bearish"
    reasons = [
        f"Dynamic Trend Pivots confirmed {trend.lower()} flip on completed 15m candle",
        f"EMA20 ({float(row['ema20']):.2f}) {'>' if bullish else '<'} EMA50 ({float(row['ema50']):.2f})",
        "ATR14 used for underlying risk levels only; no RSI/ADX/VWAP/Supertrend filters",
    ]
    return {
        "symbol": name,
        "side": side,
        "score": 100,
        "reasons": reasons,
        "spot": spot,
        "atr": atr,
        "ema20": float(row["ema20"]),
        "ema50": float(row["ema50"]),
        "dtp_state": int(row["dtp_state"]),
        "underlying_stop": round(stop, 2),
        "underlying_target": round(target, 2),
        "higher_timeframe_trend": trend,
        "timestamp": str(row["timestamp"]),
    }


def generate_signal(name, candles15):
    """Evaluate the latest completed 15-minute candle only."""
    indicator_df = calculate_indicators(candles15)
    signal = analyze_setup(indicator_df, name)
    if signal:
        logger.info("%s DTP %s signal | EMA20=%.2f EMA50=%.2f", name, signal["side"], signal["ema20"], signal["ema50"])
    else:
        logger.info("%s: no DTP + EMA20/50 signal", name)
    return signal
