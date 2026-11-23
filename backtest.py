"""Compare option-buying signal filters on historical underlying candles.

This is an underlying-points proxy backtest, not an options-premium backtest.
CSV columns required: timestamp, open, high, low, close, volume.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def load_candles(path, interval):
    df = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("Asia/Kolkata")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata")
    df = df.drop_duplicates("timestamp").reset_index(drop=True)
    df["session"] = df["timestamp"].dt.date
    return df


def add_indicators(df):
    df = df.copy()
    close, high, low = df.close, df.high, df.low
    df["ema9"] = close.ewm(span=9, adjust=False).mean()
    df["ema21"] = close.ewm(span=21, adjust=False).mean()
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df.loc[(avg_gain > 0) & (avg_loss == 0), "rsi"] = 100
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    up, down = high.diff(), -low.diff()
    plus = up.where((up > down) & (up > 0), 0.0)
    minus = down.where((down > up) & (down > 0), 0.0)
    safe_atr = df["atr"].replace(0, np.nan)
    pdi = 100 * plus.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / safe_atr
    mdi = 100 * minus.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / safe_atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    typical = (high + low + close) / 3
    pv = typical * df.volume.fillna(0)
    df["vwap"] = pv.groupby(df.session).cumsum() / df.volume.fillna(0).groupby(df.session).cumsum().replace(0, np.nan)
    df["volume_avg"] = df.volume.rolling(20, min_periods=20).mean()
    return df


def merge_15m(five, fifteen):
    slow = fifteen[["timestamp", "ema9", "ema21"]].rename(
        columns={"ema9": "ema9_15m", "ema21": "ema21_15m"})
    # Shift 15m timestamps to candle close time to prevent lookahead.
    slow["timestamp"] = slow["timestamp"] + pd.Timedelta(minutes=15)
    return pd.merge_asof(
        five.sort_values("timestamp"),
        slow.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )


def make_variants(df):
    trend_up = df.ema9 > df.ema21
    trend_down = df.ema9 < df.ema21
    cross_up = trend_up & ~trend_up.shift(1, fill_value=False)
    cross_down = trend_down & ~trend_down.shift(1, fill_value=False)
    rsi_up = (df.rsi > 60) & (df.rsi.shift(1) <= 60)
    rsi_down = (df.rsi < 40) & (df.rsi.shift(1) >= 40)
    vwap_up, vwap_down = df.close > df.vwap, df.close < df.vwap
    adx_ok = df.adx > 22
    vol_ok = df.volume > df.volume_avg
    higher_up = df.ema9_15m > df.ema21_15m
    higher_down = df.ema9_15m < df.ema21_15m
    bullish_candle, bearish_candle = df.close > df.open, df.close < df.open

    pullback_up = pd.Series(False, index=df.index)
    pullback_down = pd.Series(False, index=df.index)
    for lag in (1, 2, 3):
        tolerance = 0.25 * df.atr.shift(lag)
        for level in ("ema9", "ema21", "vwap"):
            level_value = df[level].shift(lag)
            candle_low = df.low.shift(lag)
            candle_high = df.high.shift(lag)
            touched = (
                (candle_low <= level_value + tolerance)
                & (candle_high >= level_value - tolerance)
            )
            pullback_up |= touched
            pullback_down |= touched

    variants = {
        "EMA9/21 crossover": (cross_up, cross_down),
        "RSI threshold cross": (rsi_up, rsi_down),
        "ADX trend filter": (cross_up & adx_ok, cross_down & adx_ok),
        "VWAP filter": (cross_up & vwap_up, cross_down & vwap_down),
        "EMA + RSI": (cross_up & rsi_up, cross_down & rsi_down),
        "EMA + VWAP + RSI": (cross_up & vwap_up & rsi_up, cross_down & vwap_down & rsi_down),
        "EMA + VWAP + RSI + ADX": (cross_up & vwap_up & rsi_up & adx_ok & vol_ok,
                                    cross_down & vwap_down & rsi_down & adx_ok & vol_ok),
        "Full 15m + pullback setup": (
            trend_up & vwap_up & df.rsi.between(60, 75) & adx_ok & vol_ok
            & higher_up & pullback_up & bullish_candle,
            trend_down & vwap_down & df.rsi.between(25, 40) & adx_ok & vol_ok
            & higher_down & pullback_down & bearish_candle,
        ),
    }
    return variants


def simulate(df, long_signal, short_signal, stop_atr=1.5, target_r=2.0, max_bars=6):
    trades = []
    i = 1
    while i < len(df) - 1:
        direction = 1 if bool(long_signal.iloc[i]) else (-1 if bool(short_signal.iloc[i]) else 0)
        if direction == 0 or not np.isfinite(df.atr.iloc[i]) or df.atr.iloc[i] <= 0:
            i += 1
            continue
        entry_i = i + 1
        entry = float(df.open.iloc[entry_i])
        risk = float(df.atr.iloc[i]) * stop_atr
        stop = entry - direction * risk
        target = entry + direction * risk * target_r
        exit_price, exit_i, reason = float(df.close.iloc[min(entry_i + max_bars, len(df)-1)]), min(entry_i + max_bars, len(df)-1), "time"
        for j in range(entry_i, min(entry_i + max_bars + 1, len(df))):
            hi, lo = float(df.high.iloc[j]), float(df.low.iloc[j])
            stop_hit = lo <= stop if direction == 1 else hi >= stop
            target_hit = hi >= target if direction == 1 else lo <= target
            # Conservative assumption: if both hit in same candle, stop is first.
            if stop_hit:
                exit_price, exit_i, reason = stop, j, "stop"
                break
            if target_hit:
                exit_price, exit_i, reason = target, j, "target"
                break
        pnl = (exit_price - entry) * direction
        trades.append({"entry_time": df.timestamp.iloc[entry_i], "side": "LONG" if direction == 1 else "SHORT",
                       "entry": entry, "exit": exit_price, "pnl_points": pnl, "exit_reason": reason})
        i = exit_i + 1
    return pd.DataFrame(trades)


def summarize(name, trades):
    if trades.empty:
        return {"Strategy": name, "Trades": 0, "Win rate %": 0.0, "Net points": 0.0,
                "Avg points/trade": 0.0, "Profit factor": 0.0, "Max drawdown points": 0.0}
    pnl = trades.pnl_points.astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax()
    gross_loss = abs(losses.sum())
    return {"Strategy": name, "Trades": len(trades), "Win rate %": round(100 * (pnl > 0).mean(), 2),
            "Net points": round(pnl.sum(), 2), "Avg points/trade": round(pnl.mean(), 2),
            "Profit factor": round(wins.sum() / gross_loss, 2) if gross_loss else float("inf"),
            "Max drawdown points": round(drawdown.min(), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--5m", dest="five", required=True, help="CSV of historical 5-minute underlying candles")
    parser.add_argument("--15m", dest="fifteen", required=True, help="CSV of historical 15-minute underlying candles")
    parser.add_argument("--output", default="backtest_results.csv")
    args = parser.parse_args()
    five = add_indicators(load_candles(args.five, 5))
    fifteen = add_indicators(load_candles(args.fifteen, 15))
    data = merge_15m(five, fifteen).dropna(subset=["ema9_15m", "ema21_15m"]).reset_index(drop=True)
    rows = []
    for name, (longs, shorts) in make_variants(data).items():
        trades = simulate(data, longs.fillna(False), shorts.fillna(False))
        rows.append(summarize(name, trades))
        if not trades.empty:
            trades.to_csv(Path(args.output).with_name(name.lower().replace(" ", "_").replace("+", "plus") + "_trades.csv"), index=False)
    result = pd.DataFrame(rows).sort_values(["Win rate %", "Net points"], ascending=False)
    result.to_csv(args.output, index=False)
    print(result.to_string(index=False))
    print("\nNote: results are underlying index points, not option premium P&L; costs, slippage, strike selection, IV and theta are not modelled.")


if __name__ == "__main__":
    main()
