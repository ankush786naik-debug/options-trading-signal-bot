
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

    df["timestamp"] = pd.to_datetime(
        df["timestamp"],
        errors="coerce"
    )

    df = df.dropna(
        subset=["timestamp", "open", "high", "low", "close"]
    )

    df = df.sort_values("timestamp")
    df = df.drop_duplicates(subset=["timestamp"], keep="last")

    return df.reset_index(drop=True)


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

    # RSI 14
    delta = close.diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)

    df["rsi"] = 100 - (100 / (1 + rs))

    df.loc[
        (avg_loss == 0) & (avg_gain > 0),
        "rsi"
    ] = 100

    df.loc[
        (avg_gain == 0) & (avg_loss > 0),
        "rsi"
    ] = 0

    df.loc[
        (avg_gain == 0) & (avg_loss == 0),
        "rsi"
    ] = 50

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26

    df["macd_signal"] = df["macd"].ewm(
        span=9,
        adjust=False
    ).mean()

    # ATR 14
    previous_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs()
        ],
        axis=1
    ).max(axis=1)

    df["atr"] = tr.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    # ADX 14
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = up_move.where(
        (up_move > down_move) & (up_move > 0),
        0.0
    )

    minus_dm = down_move.where(
        (down_move > up_move) & (down_move > 0),
        0.0
    )

    atr_safe = df["atr"].replace(0, np.nan)

    plus_di = 100 * plus_dm.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean() / atr_safe

    minus_di = 100 * minus_dm.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean() / atr_safe

    di_sum = (plus_di + minus_di).replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / di_sum

    df["adx"] = dx.ewm(
        alpha=1 / 14,
        adjust=False,
        min_periods=14
    ).mean()

    # Session-based VWAP
    typical = (high + low + close) / 3

    df["_session"] = df["timestamp"].dt.date

    price_volume = typical * volume

    cumulative_pv = price_volume.groupby(
        df["_session"]
    ).cumsum()

    cumulative_volume = volume.groupby(
        df["_session"]
    ).cumsum()

    df["vwap"] = (
        cumulative_pv /
        cumulative_volume.replace(0, np.nan)
    )

    df.drop(columns=["_session"], inplace=True)

    # Volume average
    df["volume_avg"] = volume.rolling(
        window=20,
        min_periods=20
    ).mean()

    # Supertrend 10, multiplier 3
    multiplier = 3.0

    basic_upper = (
        (high + low) / 2
    ) + multiplier * df["atr"]

    basic_lower = (
        (high + low) / 2
    ) - multiplier * df["atr"]

    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()

    direction = pd.Series(
        1,
        index=df.index,
        dtype="int64"
    )

    supertrend = pd.Series(
        np.nan,
        index=df.index,
        dtype="float64"
    )

    for i in range(1, len(df)):

        if pd.isna(df["atr"].iloc[i]):
            continue

        previous_upper = final_upper.iloc[i - 1]
        previous_lower = final_lower.iloc[i - 1]

        if (
            basic_upper.iloc[i] < previous_upper
            or close.iloc[i - 1] > previous_upper
        ):
            final_upper.iloc[i] = basic_upper.iloc[i]
        else:
            final_upper.iloc[i] = previous_upper

        if (
            basic_lower.iloc[i] > previous_lower
            or close.iloc[i - 1] < previous_lower
        ):
            final_lower.iloc[i] = basic_lower.iloc[i]
        else:
            final_lower.iloc[i] = previous_lower

        previous_direction = direction.iloc[i - 1]

        if previous_direction == -1:
            if close.iloc[i] > final_upper.iloc[i]:
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1
        else:
            if close.iloc[i] < final_lower.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = 1

        if direction.iloc[i] == 1:
            supertrend.iloc[i] = final_lower.iloc[i]
        else:
            supertrend.iloc[i] = final_upper.iloc[i]

    df["supertrend"] = supertrend
    df["supertrend_direction"] = direction

    return df
    
