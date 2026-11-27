"""Dynamic Trend Pivots (reconstructed) and EMA20/EMA50 indicators.

IMPORTANT: BOSWaves' original Pine source is not included. This implementation
reconstructs the documented adaptive-band / conviction-pulse concept and the
visible settings; it is not an exact Pine-script port.
"""
import logging
import numpy as np
import pandas as pd

DTP_TREND_LENGTH = 21
DTP_CLOSE_ZONE = 0.30
DTP_PULSE_DECAY = 0.80
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


def calculate_indicators(candles):
    """Calculate DTP-like trend bands, DTP flips, EMA20/50 and ATR14.

    The DTP signal is only confirmed on candle close. The original Pine source
    was not verified, so the DTP section is a transparent reconstruction.
    ATR is retained only for underlying risk levels, not for signal filtering.
    """
    df = prepare_dataframe(candles)
    if df is None or len(df) < 50:
        return None
    try:
        close, high, low = df["close"], df["high"], df["low"]
        df["ema20"] = close.ewm(span=20, adjust=False).mean()
        df["ema50"] = close.ewm(span=50, adjust=False).mean()
        baseline = close.ewm(span=DTP_TREND_LENGTH, adjust=False).mean()
        df["dtp_baseline"] = baseline

        candle_range = (high - low).replace(0, np.nan)
        close_position = ((close - low) / candle_range).fillna(0.5)
        up_close = close > close.shift(1)
        down_close = close < close.shift(1)
        bull_condition = up_close & (close_position >= 1.0 - DTP_CLOSE_ZONE)
        bear_condition = down_close & (close_position <= DTP_CLOSE_ZONE)

        bull_pulse = np.zeros(len(df), dtype=float)
        bear_pulse = np.zeros(len(df), dtype=float)
        for i in range(len(df)):
            prev_bull = bull_pulse[i - 1] if i else 0.0
            prev_bear = bear_pulse[i - 1] if i else 0.0
            bull_pulse[i] = min(DTP_PULSE_CAP, prev_bull + 1.0) if bool(bull_condition.iloc[i]) else prev_bull * DTP_PULSE_DECAY
            bear_pulse[i] = min(DTP_PULSE_CAP, prev_bear + 1.0) if bool(bear_condition.iloc[i]) else prev_bear * DTP_PULSE_DECAY
        conviction = np.maximum(bull_pulse, bear_pulse) / DTP_PULSE_CAP
        band_multiplier = DTP_BAND_MIN + (DTP_BAND_MAX - DTP_BAND_MIN) * (1.0 - conviction)

        deviation = (close - baseline).abs().rolling(DTP_MAD_LENGTH, min_periods=DTP_MAD_LENGTH).mean()
        df["dtp_upper"] = baseline + deviation * band_multiplier
        df["dtp_lower"] = baseline - deviation * band_multiplier
        df["dtp_bull_pulse"] = bull_pulse
        df["dtp_bear_pulse"] = bear_pulse

        state = np.zeros(len(df), dtype=np.int8)
        buy = np.zeros(len(df), dtype=bool)
        sell = np.zeros(len(df), dtype=bool)
        for i in range(1, len(df)):
            state[i] = state[i - 1]
            upper, lower = df["dtp_upper"].iloc[i], df["dtp_lower"].iloc[i]
            prev_upper, prev_lower = df["dtp_upper"].iloc[i - 1], df["dtp_lower"].iloc[i - 1]
            if pd.notna(upper) and pd.notna(prev_upper) and close.iloc[i] > upper and close.iloc[i - 1] <= prev_upper:
                state[i] = 1
            elif pd.notna(lower) and pd.notna(prev_lower) and close.iloc[i] < lower and close.iloc[i - 1] >= prev_lower:
                state[i] = -1
            buy[i] = state[i] == 1 and state[i - 1] != 1
            sell[i] = state[i] == -1 and state[i - 1] != -1
        df["dtp_state"] = state
        df["dtp_buy"] = buy
        df["dtp_sell"] = sell

        previous_close = close.shift(1)
        true_range = pd.concat([
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ], axis=1).max(axis=1)
        df["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

        df = df.replace([np.inf, -np.inf], np.nan)
        return df
    except Exception as error:
        logging.exception("Indicator calculation failed: %s", error)
        return None
