"""Compare four EMA 9/15 crossover strategies on 12 months of 5-minute index candles.

Strategies:
1. EMA 9/15 crossover alone (baseline)
2. EMA 9/15 + session VWAP direction
3. EMA 9/15 + ADX(14) strength filter (default threshold 20)
4. EMA 9/15 + VWAP direction + ADX(14)

Results are underlying-index points, not option-premium P&L.
"""
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
from config import UNDERLYINGS
from upstox_client import UpstoxClient

IST = ZoneInfo("Asia/Kolkata")
STRATEGIES = {
    "ema_9_15_baseline": {"vwap": False, "adx": False},
    "ema_9_15_vwap": {"vwap": True, "adx": False},
    "ema_9_15_adx": {"vwap": False, "adx": True},
    "ema_9_15_vwap_adx": {"vwap": True, "adx": True},
}


def parse_timestamp(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("Asia/Kolkata") if stamp.tzinfo is None else stamp.tz_convert("Asia/Kolkata")


def one_year_range():
    end_date = datetime.now(IST).date() - timedelta(days=1)
    try:
        start_date = end_date.replace(year=end_date.year - 1)
    except ValueError:
        start_date = end_date.replace(year=end_date.year - 1, day=28)
    return start_date, end_date


def fetch_historical_candles(client, instrument_key, start_date, end_date, interval=5):
    """Use <=28-day requests to respect the Upstox V3 one-month limit."""
    if interval not in (5, 15):
        raise ValueError("Only 5 and 15 minute candles are supported.")
    key = quote(instrument_key, safe="")
    all_candles, cursor = [], start_date
    while cursor <= end_date:
        chunk_end = min(cursor + timedelta(days=27), end_date)
        path = f"/v3/historical-candle/{key}/minutes/{interval}/{chunk_end.isoformat()}/{cursor.isoformat()}"
        payload = client.get(path)
        if not isinstance(payload, dict) or not isinstance(payload.get("candles"), list):
            raise RuntimeError(f"Invalid historical response for {instrument_key}: {cursor} to {chunk_end}")
        all_candles.extend(payload["candles"])
        print(f"  fetched {cursor} to {chunk_end}: {len(payload['candles'])} candles")
        cursor = chunk_end + timedelta(days=1)
    return all_candles


def candles_to_frame(candles):
    rows = []
    for candle in candles or []:
        if not isinstance(candle, list) or len(candle) < 6:
            continue
        try:
            rows.append({
                "timestamp": parse_timestamp(candle[0]), "open": float(candle[1]),
                "high": float(candle[2]), "low": float(candle[3]),
                "close": float(candle[4]), "volume": float(candle[5] or 0),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    columns = ["timestamp", "open", "high", "low", "close", "volume", "session"]
    if not rows:
        return pd.DataFrame(columns=columns)
    df = (pd.DataFrame(rows).drop_duplicates("timestamp", keep="last")
          .sort_values("timestamp").reset_index(drop=True))
    df["session"] = df.timestamp.dt.date
    now = pd.Timestamp.now(tz=IST)
    return df[df.timestamp + pd.Timedelta(minutes=5) <= now].reset_index(drop=True)


def add_indicators(df, adx_period=14):
    data = df.copy()
    data["ema9"] = data.close.ewm(span=9, adjust=False).mean()
    data["ema15"] = data.close.ewm(span=15, adjust=False).mean()
    data["bull_cross"] = ((data.ema9 > data.ema15) & (data.ema9.shift(1) <= data.ema15.shift(1))).fillna(False)
    data["bear_cross"] = ((data.ema9 < data.ema15) & (data.ema9.shift(1) >= data.ema15.shift(1))).fillna(False)

    # Session VWAP resets at the start of each trading day.
    typical = (data.high + data.low + data.close) / 3.0
    pv = typical * data.volume.clip(lower=0)
    cumulative_volume = data.groupby("session", sort=False).volume.transform(lambda s: s.clip(lower=0).cumsum())
    cumulative_pv = pv.groupby(data.session, sort=False).cumsum()
    data["vwap"] = cumulative_pv / cumulative_volume.replace(0, float("nan"))

    # Wilder-style smoothed directional movement / ADX(14).
    previous_close = data.close.shift(1)
    tr = pd.concat([
        data.high - data.low,
        (data.high - previous_close).abs(),
        (data.low - previous_close).abs(),
    ], axis=1).max(axis=1)
    up_move = data.high.diff()
    down_move = -data.low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    alpha = 1.0 / adx_period
    atr = tr.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    plus_di = 100.0 * plus_dm.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean() / atr.replace(0, float("nan"))
    minus_di = 100.0 * minus_dm.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean() / atr.replace(0, float("nan"))
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    data["adx14"] = dx.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    return data


def signal_passes(data, signal_i, direction, filters, adx_threshold):
    if filters["vwap"]:
        vwap = data.vwap.iloc[signal_i]
        close = data.close.iloc[signal_i]
        if pd.isna(vwap) or (direction == 1 and close <= vwap) or (direction == -1 and close >= vwap):
            return False
    if filters["adx"]:
        adx = data.adx14.iloc[signal_i]
        if pd.isna(adx) or adx < adx_threshold:
            return False
    return True


def backtest(df, strategy, cost_points=0.0, adx_threshold=20.0):
    if df.empty or len(df) < 20:
        return pd.DataFrame()
    filters = STRATEGIES[strategy]
    data, trades, i = add_indicators(df), [], 1
    while i < len(data) - 1:
        direction = 1 if data.bull_cross.iloc[i] else (-1 if data.bear_cross.iloc[i] else 0)
        if not direction or not signal_passes(data, i, direction, filters, adx_threshold):
            i += 1
            continue
        entry_i, session = i + 1, data.session.iloc[i + 1]
        if data.session.iloc[i] != session:
            i += 1
            continue
        entry, exit_i, exit_price, exit_reason = float(data.open.iloc[entry_i]), None, None, "session_end"
        for j in range(entry_i + 1, len(data)):
            if data.session.iloc[j] != session:
                exit_i, exit_price = j - 1, float(data.close.iloc[j - 1])
                break
            opposite = bool(data.bear_cross.iloc[j]) if direction == 1 else bool(data.bull_cross.iloc[j])
            if opposite and j + 1 < len(data) and data.session.iloc[j + 1] == session:
                exit_i, exit_price, exit_reason = j + 1, float(data.open.iloc[j + 1]), "opposite_ema_cross"
                break
        if exit_i is None:
            exit_i = int(data.index[data.session == session][-1])
            exit_price = float(data.close.iloc[exit_i])
        gross = (exit_price - entry) * direction
        net = gross - float(cost_points)
        trades.append({
            "strategy": strategy, "entry_time": data.timestamp.iloc[entry_i],
            "exit_time": data.timestamp.iloc[exit_i],
            "side": "CE_BIAS" if direction == 1 else "PE_BIAS",
            "entry_underlying": entry, "exit_underlying": exit_price,
            "gross_points": round(gross, 4), "cost_points": float(cost_points),
            "net_points": round(net, 4), "win": net > 0, "exit_reason": exit_reason,
            "signal_vwap": round(float(data.vwap.iloc[i]), 4) if pd.notna(data.vwap.iloc[i]) else None,
            "signal_adx14": round(float(data.adx14.iloc[i]), 4) if pd.notna(data.adx14.iloc[i]) else None,
        })
        i = max(exit_i + 1, entry_i + 1)
    return pd.DataFrame(trades)


def summarize(symbol, strategy, df, trades, adx_threshold):
    base = {
        "symbol": symbol, "strategy": strategy, "bars": len(df),
        "from": str(df.timestamp.min()) if len(df) else "",
        "to": str(df.timestamp.max()) if len(df) else "",
        "trades": len(trades), "adx_threshold": adx_threshold if STRATEGIES[strategy]["adx"] else "",
    }
    if trades.empty:
        return {**base, "win_rate_pct": 0.0, "net_points": 0.0, "avg_net_points": 0.0,
                "profit_factor": 0.0, "max_drawdown_points": 0.0}
    pnl = trades.net_points.astype(float)
    winners, losers = pnl[pnl > 0], pnl[pnl < 0]
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax()
    loss_sum = abs(losers.sum())
    return {
        **base, "win_rate_pct": round(100 * (pnl > 0).mean(), 2),
        "net_points": round(pnl.sum(), 2), "avg_net_points": round(pnl.mean(), 2),
        "profit_factor": round(winners.sum() / loss_sum, 2) if loss_sum else "inf",
        "max_drawdown_points": round(float(drawdown.min()), 2),
    }


def monthly_summary(symbol, strategy, trades):
    columns = ["symbol", "strategy", "month", "trades", "wins", "win_rate_pct", "net_points", "profit_factor"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    work = trades.copy()
    work["month"] = pd.to_datetime(work.entry_time).dt.strftime("%Y-%m")
    rows = []
    for month, group in work.groupby("month", sort=True):
        pnl = group.net_points.astype(float)
        gains, losses = pnl[pnl > 0].sum(), abs(pnl[pnl < 0].sum())
        rows.append({
            "symbol": symbol, "strategy": strategy, "month": month, "trades": len(group),
            "wins": int((pnl > 0).sum()), "win_rate_pct": round(100 * (pnl > 0).mean(), 2),
            "net_points": round(pnl.sum(), 2),
            "profit_factor": round(gains / losses, 2) if losses else ("inf" if gains else 0.0),
        })
    return pd.DataFrame(rows, columns=columns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-points", type=float, default=0.0,
                        help="Round-trip underlying-points cost proxy (not actual option costs)")
    parser.add_argument("--adx-threshold", type=float, default=20.0,
                        help="Minimum ADX(14) for ADX-filtered strategies (default: 20)")
    parser.add_argument("--output-dir", default="ema_9_15_backtest_results")
    args = parser.parse_args()
    start_date, end_date = one_year_range()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    client, summaries, monthly = UpstoxClient(), [], []
    print(f"Date range: {start_date} to {end_date}")
    print(f"ADX(14) threshold: {args.adx_threshold}")
    for symbol, instrument_key in UNDERLYINGS.items():
        print(f"\\nDownloading {symbol} 5-minute history...")
        candles = fetch_historical_candles(client, instrument_key, start_date, end_date, 5)
        df = candles_to_frame(candles)
        if df.empty:
            raise RuntimeError(f"No candles received for {symbol}")
        for strategy in STRATEGIES:
            trades = backtest(df, strategy, args.cost_points, args.adx_threshold)
            trades.to_csv(output / f"{strategy}_{symbol.lower()}_trades.csv", index=False)
            summaries.append(summarize(symbol, strategy, df, trades, args.adx_threshold))
            monthly.append(monthly_summary(symbol, strategy, trades))
    report = pd.DataFrame(summaries)
    report.to_csv(output / "summary.csv", index=False)
    pd.concat(monthly, ignore_index=True).to_csv(output / "monthly_summary.csv", index=False)
    print("\\nEMA 9/15 FILTER COMPARISON")
    print(report[["symbol", "strategy", "trades", "win_rate_pct", "net_points",
                  "profit_factor", "max_drawdown_points"]].to_string(index=False))
    print("\\nMonthly results saved to monthly_summary.csv")
    print("Underlying points only; option premium, IV, theta, brokerage and slippage are not modelled.")


if __name__ == "__main__":
    main()
