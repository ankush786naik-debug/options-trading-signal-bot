import pandas as pd
import numpy as np


def prepare_dataframe(candles):

    if not candles:
        return None

    df = pd.DataFrame(
        candles,
        columns=[
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "oi"
        ]
    )

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(
        subset=["open", "high", "low", "close"]
    )

    return df.sort_values("timestamp").reset_index(drop=True)


def calculate_indicators(candles):

    df = prepare_dataframe(candles)

    if df is None or len(df) < 50:
        return None

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"].fillna(0)

    # EMA
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    df["ema50"] = close.ewm(span=50, adjust=False).mean()

    # RSI
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))
    df["rsi"] = df["rsi"].fillna(100)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(
        span=9, adjust=False
    ).mean()

    # ATR
    previous_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1/14, adjust=False
    ).mean()

    # ADX
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where(
        (up_move > down_move) & (up_move > 0), 0
    )

    minus_dm = down_move.where(
        (down_move > up_move) & (down_move > 0), 0
    )

    atr_safe = df["atr"].replace(0, np.nan)

    plus_di = 100 * plus_dm.ewm(
        alpha=1/14, adjust=False
    ).mean() / atr_safe

    minus_di = 100 * minus_dm.ewm(
        alpha=1/14, adjust=False
    ).mean() / atr_safe

    dx = 100 * (plus_di - minus_di).abs() / (
        plus_di + minus_di
    ).replace(0, np.nan)

    df["adx"] = dx.ewm(
        alpha=1/14, adjust=False
    ).mean().fillna(0)

    # VWAP: intraday cumulative
    typical = (high + low + close) / 3

    df["vwap"] = (
        (typical * volume).cumsum()
        / volume.cumsum().replace(0, np.nan)
    )

    # Volume confirmation
    df["volume_avg"] = volume.rolling(20).mean()

    # Supertrend
    midpoint = (high + low) / 2

    upper = midpoint + 3 * df["atr"]
    lower = midpoint - 3 * df["atr"]

    supertrend = [np.nan] * len(df)
    direction = [1] * len(df)

    for i in range(1, len(df)):

        if close.iloc[i] > upper.iloc[i - 1]:
            direction[i] = 1

        elif close.iloc[i] < lower.iloc[i - 1]:
            direction[i] = -1

        else:
            direction[i] = direction[i - 1]

        supertrend[i] = (
            lower.iloc[i]
            if direction[i] == 1
            else upper.iloc[i]
        )

    df["supertrend"] = supertrend
    df["supertrend_direction"] = direction

    return df
