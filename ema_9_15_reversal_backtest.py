"""Preliminary pure EMA 9/15 reversal backtest on underlying index candles.

No VWAP, RSI, ADX, volume, higher timeframe, option-chain or other filters.
Entry: next 5-minute candle open after EMA9 crosses EMA15.
Exit: next candle open after opposite EMA cross, or session's final close.
This measures underlying points, not option premium returns.
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from config import UNDERLYINGS
from upstox_client import UpstoxClient

IST = ZoneInfo("Asia/Kolkata")


def parse_timestamp(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("Asia/Kolkata")
    return stamp.tz_convert("Asia/Kolkata")


def candles_to_frame(candles):
    rows = []
    for candle in candles or []:
        if not isinstance(candle, list) or len(candle) < 6:
            continue
        try:
            rows.append({
                "timestamp": parse_timestamp(candle[0]),
                "open": float(candle[1]),
                "high": float(candle[2]),
                "low": float(candle[3]),
                "close": float(candle[4]),
                "volume": float(candle[5] or 0),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "session"])
    df = pd.DataFrame(rows).drop_duplicates("timestamp", keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["session"] = df.timestamp.dt.date
    # Exclude bars that have not completed yet.
    now = pd.Timestamp.now(tz=IST)
    df = df[df.timestamp + pd.Timedelta(minutes=5) <= now].reset_index(drop=True)
    return df


def add_ema_crosses(df):
    df = df.copy()
    df["ema9"] = df.close.ewm(span=9, adjust=False).mean()
    df["ema15"] = df.close.ewm(span=15, adjust=False).mean()
    bullish = (df.ema9 > df.ema15) & (df.ema9.shift(1) <= df.ema15.shift(1))
    bearish = (df.ema9 < df.ema15) & (df.ema9.shift(1) >= df.ema15.shift(1))
    df["bull_cross"] = bullish.fillna(False)
    df["bear_cross"] = bearish.fillna(False)
    return df


def backtest(df, cost_points=0.0):
    """Single-position, intraday-only EMA 9/15 crossover simulation."""
    if df.empty or len(df) < 20:
        return pd.DataFrame()
    data = add_ema_crosses(df)
    trades = []
    i = 1

    while i < len(data) - 1:
        direction = 1 if data.bull_cross.iloc[i] else (-1 if data.bear_cross.iloc[i] else 0)
        if not direction:
            i += 1
            continue

        entry_i = i + 1
        session = data.session.iloc[entry_i]
        if data.session.iloc[i] != session:
            i += 1
            continue
        entry = float(data.open.iloc[entry_i])
        exit_i = None
        exit_price = None
        exit_reason = "session_end"

        for j in range(entry_i + 1, len(data)):
            if data.session.iloc[j] != session:
                # Exit on the previous session's final completed candle close.
                exit_i = j - 1
                exit_price = float(data.close.iloc[exit_i])
                break
            opposite = bool(data.bear_cross.iloc[j]) if direction == 1 else bool(data.bull_cross.iloc[j])
            if opposite and j + 1 < len(data) and data.session.iloc[j + 1] == session:
                exit_i = j + 1
                exit_price = float(data.open.iloc[exit_i])
                exit_reason = "opposite_ema_cross"
                break

        if exit_i is None:
            same_session = data.index[data.session == session]
            exit_i = int(same_session[-1])
            exit_price = float(data.close.iloc[exit_i])

        gross = (exit_price - entry) * direction
        net = gross - float(cost_points)
        trades.append({
            "entry_time": data.timestamp.iloc[entry_i],
            "exit_time": data.timestamp.iloc[exit_i],
            "side": "CE_BIAS" if direction == 1 else "PE_BIAS",
            "entry_underlying": entry,
            "exit_underlying": exit_price,
            "gross_points": round(gross, 4),
            "cost_points": float(cost_points),
            "net_points": round(net, 4),
            "win": net > 0,
            "exit_reason": exit_reason,
        })
        i = max(exit_i + 1, entry_i + 1)

    return pd.DataFrame(trades)


def summary(symbol, df, trades):
    if trades.empty:
        return {
            "symbol": symbol, "bars": len(df), "from": str(df.timestamp.min()) if len(df) else "",
            "to": str(df.timestamp.max()) if len(df) else "", "trades": 0,
            "win_rate_pct": 0.0, "net_points": 0.0, "avg_net_points": 0.0,
            "profit_factor": 0.0, "max_drawdown_points": 0.0,
        }
    pnl = trades.net_points.astype(float)
    winners = pnl[pnl > 0]
    losers = pnl[pnl < 0]
    equity = pnl.cumsum()
    dd = equity - equity.cummax()
    loss_sum = abs(losers.sum())
    return {
        "symbol": symbol, "bars": len(df),
        "from": str(df.timestamp.min()), "to": str(df.timestamp.max()),
        "trades": len(trades), "win_rate_pct": round(100 * (pnl > 0).mean(), 2),
        "net_points": round(pnl.sum(), 2), "avg_net_points": round(pnl.mean(), 2),
        "profit_factor": round(winners.sum() / loss_sum, 2) if loss_sum else "inf",
        "max_drawdown_points": round(float(dd.min()), 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-points", type=float, default=0.0,
                        help="Estimated round-trip cost in underlying index points (proxy only)")
    parser.add_argument("--output-dir", default="ema_9_15_backtest_results")
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    client = UpstoxClient()
    summaries = []

    for symbol, instrument_key in UNDERLYINGS.items():
        print(f"Fetching recent 5-minute candles for {symbol}...")
        candles = client.intraday_candles(instrument_key, 5)
        df = candles_to_frame(candles)
        trades = backtest(df, args.cost_points)
        trades.to_csv(output / f"{symbol.lower()}_trades.csv", index=False)
        summaries.append(summary(symbol, df, trades))

    report = pd.DataFrame(summaries)
    report.to_csv(output / "summary.csv", index=False)
    print("\nPRELIMINARY EMA 9/15 REVERSAL RESULTS")
    print(report.to_string(index=False))
    print("\nThis is a recent-data preliminary test (Upstox client currently retrieves about 7 calendar days plus today's intraday data).")
    print("Win rate is based on underlying index points, not actual option premium P&L.")
    print("No additional indicators or filters are used. Extend the historical sample before judging reliability.")


if __name__ == "__main__":
    main()
