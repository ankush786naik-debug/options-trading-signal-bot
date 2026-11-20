
import logging

import numpy as np
import pandas as pd


def prepare_dataframe(candles):
    """Convert Upstox candles into a clean OHLCV DataFrame."""

    if not candles:
        return None

    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "oi",
    ]

    try:
        df = pd.DataFrame(candles, columns=columns)

        numeric_columns = [
            "open", "high", "low", "close", "volume", "oi"
        ]

        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["timestamp"] = pd.to_datetime(
            df["timestamp"],
            errors="coerce",
            utc=True
        )

        df = df.dropna(
            subset=["timestamp", "open", "high", "low", "close"]
        ).copy()

        df = df.sort_values("timestamp")

        df = df.drop_duplicates(
            subset=["timestamp"],
            keep="last"
        )

        df = df.reset_index(drop=True)

        if df.empty:
            return None

        return df

    except (ValueError, TypeError, KeyError) as error:
        logging.exception("DataFrame preparation failed: %s", error)
        return None


def calculate_indicators(candles):
    """Calculate technical indicators for the trading strategy."""

    df = prepare_dataframe(candles)

    if df is None or len(df) < 50:
        return None

    try:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"].fillna(0)

        # EMA
        df["ema9"] = close.ewm(
            span=9, adjust=False
        ).mean()

        df["ema21"] = close.ewm(
            span=21, adjust=False
        ).mean()

        df["ema50"] = close.ewm(
            span=50, adjust=False
        ).mean()

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
            (avg_gain > 0) & (avg_loss == 0), "rsi"
        ] = 100

        df.loc[
            (avg_gain == 0) & (avg_loss > 0), "rsi"
        ] = 0

        df.loc[
            (avg_gain == 0) & (avg_loss == 0), "rsi"
        ] = 50

        # MACD 12, 26, 9
        ema12 = close.ewm(
            span=12, adjust=False
        ).mean()

        ema26 = close.ewm(
            span=26, adjust=False
        ).mean()

        df["macd"] = ema12 - ema26

        df["macd_signal"] = df["macd"].ewm(
            span=9, adjust=False
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

        plus_di = (
            100 * plus_dm.ewm(
                alpha=1 / 14,
                adjust=False,
                min_periods=14
            ).mean() / atr_safe
        )

        minus_di = (
            100 * minus_dm.ewm(
                alpha=1 / 14,
                adjust=False,
                min_periods=14
            ).mean() / atr_safe
        )

        di_sum = (plus_di + minus_di).replace(0, np.nan)

        dx = (
            100 * (plus_di - minus_di).abs() / di_sum
        )

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

        df = df.drop(columns=["_session"])

        # Volume average
        df["volume_avg"] = volume.rolling(
            window=20,
            min_periods=20
        ).mean()

        # Supertrend 10, multiplier 3
        multiplier = 3.0

        atr = df["atr"]

        midpoint = (high + low) / 2

        basic_upper = midpoint + multiplier * atr
        basic_lower = midpoint - multiplier * atr

        upper = basic_upper.to_numpy(dtype=float)
        lower = basic_lower.to_numpy(dtype=float)

        prices = close.to_numpy(dtype=float)
        atr_values = atr.to_numpy(dtype=float)

        final_upper = np.full(len(df), np.nan)
        final_lower = np.full(len(df), np.nan)

        direction = np.ones(len(df), dtype=np.int64)
        supertrend = np.full(len(df), np.nan)

        valid_positions = np.flatnonzero(
            np.isfinite(atr_values)
        )

        if len(valid_positions) > 0:

            first = valid_positions[0]

            final_upper[first] = upper[first]
            final_lower[first] = lower[first]

            direction[first] = -1
            supertrend[first] = final_upper[first]

            for i in range(first + 1, len(df)):

                if not np.isfinite(atr_values[i]):
                    continue

                previous_upper = final_upper[i - 1]
                previous_lower = final_lower[i - 1]
                previous_close = prices[i - 1]

                if (
                    upper[i] < previous_upper
                    or previous_close > previous_upper
                ):
                    final_upper[i] = upper[i]
                else:
                    final_upper[i] = previous_upper

                if (
                    lower[i] > previous_lower
                    or previous_close < previous_lower
                ):
                    final_lower[i] = lower[i]
                else:
                    final_lower[i] = previous_lower

                if direction[i - 1] == -1:

                    if prices[i] > final_upper[i]:
                        direction[i] = 1
                    else:
                        direction[i] = -1

                else:

                    if prices[i] < final_lower[i]:
                        direction[i] = -1
                    else:
                        direction[i] = 1

                if direction[i] == 1:
                    supertrend[i] = final_lower[i]
                else:
                    supertrend[i] = final_upper[i]

        df["supertrend"] = supertrend
        df["supertrend_direction"] = direction

        # Final validation
        df = df.replace(
            [np.inf, -np.inf],
            np.nan
        )

        return df

    except Exception as error:
        logging.exception(
            "Indicator calculation failed: %s",
            error
        )
        return None
        
