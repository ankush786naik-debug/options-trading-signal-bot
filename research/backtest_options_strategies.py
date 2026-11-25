"""
Research-only backtest for the index options signal bot.

Does NOT import or alter strategy.py and does NOT place orders.
Input: 5-minute underlying OHLCV CSVs (NIFTY_5m.csv, BANKNIFTY_5m.csv,
SENSEX_5m.csv) under data/backtest/ or paths passed on the command line.

Required columns: timestamp (or datetime/date/time), open, high, low, close.
volume is optional but recommended.

Usage:
  python research/backtest_options_strategies.py --data-dir data/backtest
  python research/backtest_options_strategies.py NIFTY_5m.csv BANKNIFTY_5m.csv
  python research/backtest_options_strategies.py --data-dir data/backtest --stop-atr 1.5 --target-r 2 --max-hold 12

Outputs: research/backtest_results/summary.csv and trades.csv

Important: This tests directional movement in the UNDERLYING, not historical option premiums.
Before using a winner for options buying, replay signals against actual historical option
OHLC/premium, bid-ask spread, brokerage, slippage and expiry/contract selection.
"""

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd


STRATEGIES = [
    "ema_cross",
    "vwap_direction",
    "rsi_momentum",
    "ema_pullback",
    "ema_vwap_adx",
    "strict_current",
    "score_60",
    "score_70",
    "breakout",
]


def load_candles(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "timestamp" not in df.columns:
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "timestamp"})
        elif "date" in df.columns and "time" in df.columns:
            df["timestamp"] = df["date"].astype(str) + " " + df["time"].astype(str)
        elif "date" in df.columns:
            df = df.rename(columns={"date": "timestamp"})
        else:
            raise ValueError(f"{path}: need timestamp/datetime or date column")

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "volume" not in df:
        df["volume"] = 0.0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)

    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    if df.empty:
        raise ValueError(f"{path}: no valid candles")
    return df


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def add_indicators(df):
    x = df.copy()
    close = x["close"]
    prev_close = close.shift(1)

    x["ema9"] = close.ewm(span=9, adjust=False, min_periods=9).mean()
    x["ema21"] = close.ewm(span=21, adjust=False, min_periods=21).mean()
    x["ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    x["rsi"] = rsi(close, 14)

    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    up = x["high"].diff()
    down = -x["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr_safe = x["atr"].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["adx"] = dx.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()

    # Session VWAP resets every local trading date.
    typical = (x["high"] + x["low"] + x["close"]) / 3
    x["date"] = x["timestamp"].dt.date
    pv = typical * x["volume"]
    x["vwap"] = pv.groupby(x["date"]).cumsum() / x["volume"].groupby(x["date"]).cumsum().replace(0, np.nan)
    x["vol_avg20"] = x["volume"].rolling(20, min_periods=20).mean()
    x["prev_high20"] = x["high"].shift(1).rolling(20, min_periods=20).max()
    x["prev_low20"] = x["low"].shift(1).rolling(20, min_periods=20).min()

    # 15-minute trend: completed bars only. Label each aggregate at its end time.
    indexed = x.set_index("timestamp")
    slow = indexed.resample(
        "15min", origin="start_day", offset="9h15min", label="right", closed="left"
    ).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna(subset=["close"])
    slow["slow_ema9"] = slow["close"].ewm(span=9, adjust=False, min_periods=9).mean()
    slow["slow_ema21"] = slow["close"].ewm(span=21, adjust=False, min_periods=21).mean()
    slow = slow[["slow_ema9", "slow_ema21"]].reset_index()
    x = x.reset_index(drop=True)
    # A 5m candle is known at its timestamp + 5 minutes. Merge only completed 15m bars.
    x["bar_end"] = x["timestamp"] + pd.Timedelta(minutes=5)
    x = pd.merge_asof(
        x.sort_values("bar_end"),
        slow.sort_values("timestamp"),
        left_on="bar_end", right_on="timestamp", direction="backward",
        suffixes=("", "_slow")
    )
    # Avoid the duplicate timestamp from the right-hand frame.
    if "timestamp_slow" in x.columns:
        x = x.drop(columns=["timestamp_slow"])
    return x.sort_values("timestamp").reset_index(drop=True)


def signal_for(row, prev, strategy):
    """Return +1 CALL bias, -1 PUT bias, or 0. Signal is based on closed candle."""
    if not all(pd.notna(row.get(k)) for k in [
        "ema9", "ema21", "ema50", "rsi", "adx", "atr", "vwap",
        "slow_ema9", "slow_ema21"
    ]):
        return 0

    up = row["close"] > row["open"]
    down = row["close"] < row["open"]
    trend_up = row["ema9"] > row["ema21"]
    trend_down = row["ema9"] < row["ema21"]
    slow_up = row["slow_ema9"] > row["slow_ema21"]
    slow_down = row["slow_ema9"] < row["slow_ema21"]
    above_vwap = row["close"] > row["vwap"]
    below_vwap = row["close"] < row["vwap"]
    volume_ok = row["volume"] > row["vol_avg20"] if pd.notna(row["vol_avg20"]) else False
    adx_ok = row["adx"] > 18
    pullback = (
        abs(row["low"] - row["ema9"]) <= 0.35 * row["atr"]
        or abs(row["low"] - row["ema21"]) <= 0.35 * row["atr"]
        or abs(row["low"] - row["vwap"]) <= 0.35 * row["atr"]
    )
    pullback_down = (
        abs(row["high"] - row["ema9"]) <= 0.35 * row["atr"]
        or abs(row["high"] - row["ema21"]) <= 0.35 * row["atr"]
        or abs(row["high"] - row["vwap"]) <= 0.35 * row["atr"]
    )

    if strategy == "ema_cross":
        if trend_up and prev["ema9"] <= prev["ema21"]:
            return 1
        if trend_down and prev["ema9"] >= prev["ema21"]:
            return -1
    elif strategy == "vwap_direction":
        if above_vwap and row["close"] > row["open"] and prev["close"] <= prev["vwap"]:
            return 1
        if below_vwap and row["close"] < row["open"] and prev["close"] >= prev["vwap"]:
            return -1
    elif strategy == "rsi_momentum":
        if 52 < row["rsi"] < 70 and trend_up and up:
            return 1
        if 30 < row["rsi"] < 48 and trend_down and down:
            return -1
    elif strategy == "ema_pullback":
        if trend_up and slow_up and pullback and up:
            return 1
        if trend_down and slow_down and pullback_down and down:
            return -1
    elif strategy == "ema_vwap_adx":
        if trend_up and slow_up and above_vwap and adx_ok and up:
            return 1
        if trend_down and slow_down and below_vwap and adx_ok and down:
            return -1
    elif strategy == "strict_current":
        # Approximation of the live strategy's main gates, for research comparison.
        if (above_vwap and trend_up and slow_up and row["adx"] > 22
                and 60 < row["rsi"] < 75 and up and volume_ok):
            return 1
        if (below_vwap and trend_down and slow_down and row["adx"] > 22
                and 25 < row["rsi"] < 40 and down and volume_ok):
            return -1
    elif strategy in ("score_60", "score_70"):
        call = sum([
            2 if trend_up else 0,
            1 if slow_up else 0,
            1 if above_vwap else 0,
            1 if 52 < row["rsi"] < 72 else 0,
            1 if up else 0,
            1 if adx_ok else 0,
            1 if volume_ok else 0,
            1 if pullback else 0,
        ])
        put = sum([
            2 if trend_down else 0,
            1 if slow_down else 0,
            1 if below_vwap else 0,
            1 if 28 < row["rsi"] < 48 else 0,
            1 if down else 0,
            1 if adx_ok else 0,
            1 if volume_ok else 0,
            1 if pullback_down else 0,
        ])
        threshold = 6 if strategy == "score_60" else 7
        if call >= threshold and call > put:
            return 1
        if put >= threshold and put > call:
            return -1
    elif strategy == "breakout":
        if pd.notna(row["prev_high20"]) and row["close"] > row["prev_high20"] and up:
            return 1
        if pd.notna(row["prev_low20"]) and row["close"] < row["prev_low20"] and down:
            return -1
    return 0


def backtest(df, symbol, strategy, stop_atr=1.5, target_r=2.0, max_hold=12):
    trades = []
    warmup = 80
    i = warmup
    while i < len(df) - 1:
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        ts = row["timestamp"]
        # Restrict signal/entry to regular NSE session.
        if ts.hour < 9 or (ts.hour == 9 and ts.minute < 20) or ts.hour >= 15 or (ts.hour == 15 and ts.minute > 10):
            i += 1
            continue

        side = signal_for(row, prev, strategy)
        if side == 0 or not np.isfinite(row["atr"]) or row["atr"] <= 0:
            i += 1
            continue

        entry_i = i + 1
        entry = float(df.iloc[entry_i]["open"])
        risk = float(row["atr"]) * stop_atr
        stop = entry - side * risk
        target = entry + side * risk * target_r
        exit_price = float(df.iloc[min(entry_i + max_hold, len(df) - 1)]["close"])
        exit_i = min(entry_i + max_hold, len(df) - 1)
        exit_reason = "TIME"

        for j in range(entry_i, min(entry_i + max_hold + 1, len(df))):
            candle = df.iloc[j]
            # Conservative handling: if stop and target both hit in one candle, stop wins.
            stop_hit = candle["low"] <= stop if side == 1 else candle["high"] >= stop
            target_hit = candle["high"] >= target if side == 1 else candle["low"] <= target
            if stop_hit:
                exit_price, exit_i, exit_reason = stop, j, "STOP"
                break
            if target_hit:
                exit_price, exit_i, exit_reason = target, j, "TARGET"
                break
            # Avoid holding overnight; exit at last candle of session.
            if j + 1 < len(df):
                next_ts = df.iloc[j + 1]["timestamp"]
                if next_ts.date() != candle["timestamp"].date() or next_ts.hour >= 15:
                    exit_price, exit_i, exit_reason = float(candle["close"]), j, "EOD"
                    break

        pnl = (exit_price - entry) * side
        trades.append({
            "symbol": symbol, "strategy": strategy, "side": "CALL" if side == 1 else "PUT",
            "signal_time": ts, "entry_time": df.iloc[entry_i]["timestamp"],
            "entry": entry, "stop": stop, "target": target,
            "exit_time": df.iloc[exit_i]["timestamp"], "exit": exit_price,
            "exit_reason": exit_reason, "pnl_points": pnl,
            "risk_points": risk, "r_multiple": pnl / risk if risk else np.nan,
        })
        # One position at a time; skip to after exit.
        i = max(exit_i + 1, i + 1)
    return trades


def summarize(trades_df):
    if trades_df.empty:
        return {
            "trades": 0, "win_rate_pct": 0.0, "net_points": 0.0,
            "avg_r": 0.0, "profit_factor": 0.0, "max_drawdown_points": 0.0,
        }
    pnl = trades_df["pnl_points"].astype(float)
    wins = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax()
    return {
        "trades": int(len(pnl)),
        "win_rate_pct": round(float((pnl > 0).mean() * 100), 2),
        "net_points": round(float(pnl.sum()), 2),
        "avg_r": round(float(trades_df["r_multiple"].mean()), 3),
        "profit_factor": round(float(wins / losses), 3) if losses > 0 else (999.0 if wins > 0 else 0.0),
        "max_drawdown_points": round(float(drawdown.min()), 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare independent and combined options-bot signal strategies.")
    parser.add_argument("files", nargs="*", help="5-minute OHLCV CSV files")
    parser.add_argument("--data-dir", default="data/backtest", help="Directory containing *_5m.csv files")
    parser.add_argument("--stop-atr", type=float, default=1.5)
    parser.add_argument("--target-r", type=float, default=2.0)
    parser.add_argument("--max-hold", type=int, default=12)
    parser.add_argument("--out-dir", default="research/backtest_results")
    args = parser.parse_args()

    files = [Path(p) for p in args.files]
    if not files:
        files = sorted(Path(args.data_dir).glob("*_5m.csv"))
    if not files:
        print(f"No CSV files found. Put NIFTY_5m.csv/BANKNIFTY_5m.csv/SENSEX_5m.csv in {args.data_dir}.")
        print("Expected columns: timestamp,open,high,low,close,volume")
        return 2

    all_trades = []
    summaries = []
    for path in files:
        symbol = path.stem.replace("_5m", "").upper()
        try:
            raw = load_candles(path)
            candles = add_indicators(raw)
        except Exception as exc:
            print(f"Skipping {path}: {exc}", file=sys.stderr)
            continue

        print(f"{symbol}: {len(candles):,} 5m candles | {candles['timestamp'].min()} to {candles['timestamp'].max()}")
        for strategy in STRATEGIES:
            trades = backtest(
                candles, symbol, strategy,
                stop_atr=args.stop_atr, target_r=args.target_r, max_hold=args.max_hold
            )
            trade_df = pd.DataFrame(trades)
            all_trades.extend(trades)
            metrics = summarize(trade_df)
            summaries.append({"symbol": symbol, "strategy": strategy, **metrics})
            print(
                f"  {strategy:18s} trades={metrics['trades']:4d} "
                f"win={metrics['win_rate_pct']:5.1f}% PF={metrics['profit_factor']:6.2f} "
                f"net={metrics['net_points']:9.2f} maxDD={metrics['max_drawdown_points']:8.2f}"
            )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_df = pd.DataFrame(summaries)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["symbol", "profit_factor", "net_points"], ascending=[True, False, False])
        summary_df.to_csv(out / "summary.csv", index=False)
    pd.DataFrame(all_trades).to_csv(out / "trades.csv", index=False)
    print(f"\nSaved: {out / 'summary.csv'}")
    print(f"Saved: {out / 'trades.csv'}")
    print("Interpretation: compare profit factor, expectancy/net points, drawdown and trade count together.")
    print("This is underlying-point research, not option-premium P&L. Do not deploy based on win rate alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
