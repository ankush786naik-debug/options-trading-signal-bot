"""Exact Python port of the core signal calculations in BOSWaves DTP Pine v6.

The main trend-flip labels reproduce Pine's crossover/crossunder + lastSignal
state logic. Display smoothing, plots, labels and drawing objects are omitted.
"""
import logging
import numpy as np
import pandas as pd

DTP_TREND_LENGTH = 21
DTP_CLOSE_ZONE = 0.30
DTP_PULSE_DECAY = 0.85
DTP_PULSE_CAP = 8.0
DTP_MAD_LENGTH = 17
DTP_BAND_MIN = 1.4
DTP_BAND_MAX = 2.2


def prepare_dataframe(candles):
    """Convert Upstox candle rows into clean, chronological OHLCV data."""
    if not candles:
        return None
    columns = ["timestamp", "open", "high", "low", "close", "volume", "oi"]
    try:
        df = pd.DataFrame(candles, columns=columns)
        for col in ["open", "high", "low", "close", "volume", "oi"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        df = df.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
        df = df.reset_index(drop=True)
        return df if not df.empty else None
    except (ValueError, TypeError, KeyError):
        logging.exception("DataFrame preparation failed")
        return None


def _wilder_rma(series, length):
    """Pine ta.rma equivalent: SMA seed, then Wilder recursive smoothing."""
    values = series.astype(float).to_numpy()
    out = np.full(len(values), np.nan, dtype=float)
    if len(values) < length:
        return pd.Series(out, index=series.index)
    seed_idx = length - 1
    seed = np.nanmean(values[:length])
    if not np.isfinite(seed):
        return pd.Series(out, index=series.index)
    out[seed_idx] = seed
    alpha = 1.0 / length
    for i in range(length, len(values)):
        if np.isfinite(values[i]) and np.isfinite(out[i - 1]):
            out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return pd.Series(out, index=series.index)


def calculate_indicators(candles):
    """Calculate DTP core signals, EMA20/50 and ATR14.

    Pine source: Dynamic Trend Pivots [BOSWaves], supplied by user.
    Main signals are the Pine switchUp/switchDown events, not raw band
    crossings. Evaluate only completed candles in the caller.
    """
    df = prepare_dataframe(candles)
    if df is None or len(df) < 50:
        return None
    try:
        close, high, low, open_ = df["close"], df["high"], df["low"], df["open"]
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()

        # Pine: basis = ta.ema(close, 21)
        basis = close.ewm(span=DTP_TREND_LENGTH, adjust=False).mean()
        df["dtp_baseline"] = basis

        # Pine conviction candles use close location and candle direction (close vs open).
        bar_range = (high - low).clip(lower=1e-8)
        close_loc = (close - low) / bar_range
        bull_conv = (close_loc >= (1.0 - DTP_CLOSE_ZONE)) & (close > open_)
        bear_conv = (close_loc <= DTP_CLOSE_ZONE) & (close < open_)

        bull_pulse = np.zeros(len(df), dtype=float)
        bear_pulse = np.zeros(len(df), dtype=float)
        for i in range(len(df)):
            bp = bull_pulse[i - 1] if i else 0.0
            sp = bear_pulse[i - 1] if i else 0.0
            bull_pulse[i] = min(bp + 1.0, DTP_PULSE_CAP) if bool(bull_conv.iloc[i]) else bp * DTP_PULSE_DECAY
            bear_pulse[i] = min(sp + 1.0, DTP_PULSE_CAP) if bool(bear_conv.iloc[i]) else sp * DTP_PULSE_DECAY

        saturation = np.maximum(bull_pulse, bear_pulse) / DTP_PULSE_CAP
        df["dtp_bull_pulse"] = bull_pulse
        df["dtp_bear_pulse"] = bear_pulse
        df["dtp_saturation"] = saturation

        # Pine: mean = sma(close, 17); mad = sma(abs(close - mean), 17)
        mean = close.rolling(DTP_MAD_LENGTH, min_periods=DTP_MAD_LENGTH).mean()
        mad = (close - mean).abs().rolling(DTP_MAD_LENGTH, min_periods=DTP_MAD_LENGTH).mean()
        band_mult = DTP_BAND_MAX - (DTP_BAND_MAX - DTP_BAND_MIN) * saturation
        upper = basis + mad * band_mult
        lower = basis - mad * band_mult
        df["dtp_mad"] = mad
        df["dtp_band_multiplier"] = band_mult
        df["dtp_upper"] = upper
        df["dtp_lower"] = lower

        # Pine ta.crossover(close, upper) / ta.crossunder(close, lower).
        long_cond = (close > upper) & (close.shift(1) <= upper.shift(1))
        short_cond = (close < lower) & (close.shift(1) >= lower.shift(1))
        state = np.zeros(len(df), dtype=np.int8)
        buy = np.zeros(len(df), dtype=bool)   # Pine switchUp: previous state -1 -> 1
        sell = np.zeros(len(df), dtype=bool)  # Pine switchDown: previous state 1 -> -1
        for i in range(1, len(df)):
            previous_state = state[i - 1]
            state[i] = previous_state
            if bool(long_cond.iloc[i]):
                state[i] = 1
            elif bool(short_cond.iloc[i]):
                state[i] = -1
            buy[i] = state[i] == 1 and previous_state == -1
            sell[i] = state[i] == -1 and previous_state == 1

        df["dtp_long_condition"] = long_cond.fillna(False)
        df["dtp_short_condition"] = short_cond.fillna(False)
        df["dtp_state"] = state
        df["dtp_buy"] = buy
        df["dtp_sell"] = sell

        # Pine ta.atr(14) = Wilder RMA of true range.
        prev_close = close.shift(1)
        true_range = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        df["atr14"] = _wilder_rma(true_range, 14)

        df = df.replace([np.inf, -np.inf], np.nan)
        return df
    except Exception as error:
        logging.exception("Indicator calculation failed: %s", error)
        return None
