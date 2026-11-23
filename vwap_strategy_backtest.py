"""Compare VWAP-cross signals with and without an ADX strength filter.

Research-only underlying-index backtest; not option-premium P&L.
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
TRADE_COLUMNS = [
    "symbol", "strategy", "entry_time", "exit_time", "side",
    "entry_underlying", "exit_underlying", "gross_points",
    "cost_points", "net_points", "win", "exit_reason",
    "signal_vwap", "signal_adx14",
]


def parse_timestamp(value):
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("Asia/Kolkata") if stamp.tzinfo is None else stamp.tz_convert("Asia/Kolkata")


def date_range_one_year():
    end = datetime.now(IST).date() - timedelta(days=1)
    try:
        start = end.replace(year=end.year - 1)
    except ValueError:
        start = end.replace(year=end.year - 1, day=28)
    return start, end


def fetch_candles(client, instrument_key, start, end, interval=5):
    if interval != 5:
        raise ValueError("This strategy uses 5-minute candles only.")
    key = quote(instrument_key, safe="")
    candles, cursor = [], start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=27), end)
        endpoint = f"/v3/historical-candle/{key}/minutes/5/{chunk_end.isoformat()}/{cursor.isoformat()}"
        payload = client.get(endpoint)
        if not isinstance(payload, dict) or not isinstance(payload.get("candles"), list):
            raise RuntimeError(f"Invalid Upstox historical response for {instrument_key}")
        candles.extend(payload["candles"])
        print(f"  downloaded {cursor} to {chunk_end}: {len(payload['candles'])} candles")
        cursor = chunk_end + timedelta(days=1)
    return candles


def candles_frame(candles):
    rows = []
    for candle in candles or []:
        if not isinstance(candle, list) or len(candle) < 6:
            continue
        try:
            rows.append({
                "timestamp": parse_timestamp(candle[0]),
                "open": float(candle[1]), "high": float(candle[2]),
                "low": float(candle[3]), "close": float(candle[4]),
                "volume": max(float(candle[5] or 0), 0.0),
            })
        except (TypeError, ValueError, OverflowError):
            continue
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume", "session"])
    data = pd.DataFrame(rows).drop_duplicates("timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)
    data["session"] = data.timestamp.dt.date
    now = pd.Timestamp.now(tz=IST)
    return data[data.timestamp + pd.Timedelta(minutes=5) <= now].reset_index(drop=True)


def add_indicators(df, adx_period=14):
    data = df.copy()
    typical_price = (data.high + data.low + data.close) / 3.0
    volume = data.volume.clip(lower=0)
    cumulative_volume = volume.groupby(data.session, sort=False).cumsum()
    cumulative_value = (typical_price * volume).groupby(data.session, sort=False).cumsum()
    data["vwap"] = cumulative_value / cumulative_volume.where(cumulative_volume > 0)

    # VWAP direction-change signals; VWAP is reset for each trading session.
    previous_close = data.close.shift(1)
    previous_vwap = data.vwap.shift(1)
    same_session = data.session.eq(data.session.shift(1))
    data["bull_cross"] = ((data.close > data.vwap) & (previous_close <= previous_vwap) & same_session).fillna(False)
    data["bear_cross"] = ((data.close < data.vwap) & (previous_close >= previous_vwap) & same_session).fillna(False)

    prev_close = data.close.shift(1)
    true_range = pd.concat([
        data.high - data.low,
        (data.high - prev_close).abs(),
        (data.low - prev_close).abs(),
    ], axis=1).max(axis=1)
    up = data.high.diff()
    down = -data.low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    alpha = 1.0 / adx_period
    atr = true_range.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    plus_smoothed = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    minus_smoothed = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    plus_di = 100.0 * plus_smoothed / atr.replace(0, float("nan"))
    minus_di = 100.0 * minus_smoothed / atr.replace(0, float("nan"))
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    data["adx14"] = dx.ewm(alpha=alpha, adjust=False, min_periods=adx_period).mean()
    return data


def run_backtest(df, symbol, strategy, adx_threshold, cost_points):
    data = add_indicators(df)
    use_adx = strategy == "VWAP_ADX"
    signals = []
    trades = []
    candidate_count = passed_count = 0

    i = 1
    while i < len(data) - 1:
        direction = 1 if bool(data.bull_cross.iloc[i]) else (-1 if bool(data.bear_cross.iloc[i]) else 0)
        if not direction:
            i += 1
            continue
        candidate_count += 1
        adx = data.adx14.iloc[i]
        passed = not use_adx or (pd.notna(adx) and float(adx) >= adx_threshold)
        signals.append({
            "symbol": symbol, "strategy": strategy, "signal_time": data.timestamp.iloc[i],
            "direction": "LONG_BIAS" if direction == 1 else "SHORT_BIAS",
            "close": float(data.close.iloc[i]), "vwap": float(data.vwap.iloc[i]),
            "adx14": float(adx) if pd.notna(adx) else None, "adx_filter_passed": bool(passed),
        })
        if not passed:
            i += 1
            continue
        passed_count += 1
        entry_i = i + 1
        session = data.session.iloc[entry_i]
        if data.session.iloc[i] != session:
            i += 1
            continue
        entry = float(data.open.iloc[entry_i])
        exit_i, exit_price, exit_reason = None, None, "session_end"

        for j in range(entry_i + 1, len(data)):
            if data.session.iloc[j] != session:
                exit_i, exit_price = j - 1, float(data.close.iloc[j - 1])
                break
            opposite = bool(data.bear_cross.iloc[j]) if direction == 1 else bool(data.bull_cross.iloc[j])
            if opposite and j + 1 < len(data) and data.session.iloc[j + 1] == session:
                exit_i, exit_price, exit_reason = j + 1, float(data.open.iloc[j + 1]), "opposite_vwap_cross"
                break
        if exit_i is None:
            session_rows = data.index[data.session == session]
            if len(session_rows) == 0:
                i += 1
                continue
            exit_i = int(session_rows[-1])
            exit_price = float(data.close.iloc[exit_i])

        gross = (exit_price - entry) * direction
        net = gross - float(cost_points)
        trades.append({
            "symbol": symbol, "strategy": strategy, "entry_time": data.timestamp.iloc[entry_i],
            "exit_time": data.timestamp.iloc[exit_i],
            "side": "LONG_BIAS" if direction == 1 else "SHORT_BIAS",
            "entry_underlying": entry, "exit_underlying": exit_price,
            "gross_points": round(gross, 4), "cost_points": float(cost_points),
            "net_points": round(net, 4), "win": bool(net > 0), "exit_reason": exit_reason,
            "signal_vwap": round(float(data.vwap.iloc[i]), 4) if pd.notna(data.vwap.iloc[i]) else None,
            "signal_adx14": round(float(adx), 4) if pd.notna(adx) else None,
        })
        # One position at a time: resume after the exit candle to avoid overlapping trades.
        i = max(exit_i + 1, entry_i + 1)

    trade_frame = pd.DataFrame(trades, columns=TRADE_COLUMNS)
    signal_frame = pd.DataFrame(signals, columns=[
        "symbol", "strategy", "signal_time", "direction", "close", "vwap", "adx14", "adx_filter_passed"
    ])
    pnl = trade_frame.net_points.astype(float) if not trade_frame.empty else pd.Series(dtype=float)
    gains = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
    losses = float(abs(pnl[pnl < 0].sum())) if len(pnl) else 0.0
    equity = pnl.cumsum()
    drawdown = equity - equity.cummax() if len(equity) else pd.Series(dtype=float)
    summary = {
        "symbol": symbol, "strategy": strategy, "bars": len(data),
        "candidate_vwap_crosses": candidate_count, "signals_after_filter": passed_count,
        "trades": len(trade_frame),
        "win_rate_pct": round(100 * float((pnl > 0).mean()), 2) if len(pnl) else 0.0,
        "net_points": round(float(pnl.sum()), 2) if len(pnl) else 0.0,
        "avg_net_points": round(float(pnl.mean()), 2) if len(pnl) else 0.0,
        "profit_factor": round(gains / losses, 2) if losses else ("inf" if gains else 0.0),
        "max_drawdown_points": round(float(drawdown.min()), 2) if len(drawdown) else 0.0,
        "adx_threshold": adx_threshold if use_adx else "",
    }
    return summary, trade_frame, signal_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cost-points", type=float, default=0.0,
                        help="Estimated round-trip underlying index points (proxy only)")
    parser.add_argument("--adx-threshold", type=float, default=20.0,
                        help="Minimum ADX(14) for VWAP + ADX variant")
    parser.add_argument("--output-dir", default="vwap_backtest_results")
    args = parser.parse_args()
    if args.cost_points < 0 or args.adx_threshold < 0:
        parser.error("cost-points and adx-threshold must be non-negative")

    start, end = date_range_one_year()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    client, summaries, monthly_rows = UpstoxClient(), [], []
    print(f"Backtest date range: {start} to {end}; ADX threshold: {args.adx_threshold}")

    for symbol, instrument_key in UNDERLYINGS.items():
        print(f"\nFetching {symbol} 5-minute candles...")
        df = candles_frame(fetch_candles(client, instrument_key, start, end))
        if df.empty:
            raise RuntimeError(f"No completed candles received for {symbol}")
        for strategy in ("VWAP_ONLY", "VWAP_ADX"):
            summary, trades, signals = run_backtest(df, symbol, strategy, args.adx_threshold, args.cost_points)
            summaries.append(summary)
            trades.to_csv(output / f"{strategy.lower()}_{symbol.lower()}_trades.csv", index=False)
            signals.to_csv(output / f"{strategy.lower()}_{symbol.lower()}_signals.csv", index=False)
            if not trades.empty:
                work = trades.copy()
                work["month"] = pd.to_datetime(work.entry_time).dt.strftime("%Y-%m")
                for month, group in work.groupby("month", sort=True):
                    p = group.net_points.astype(float)
                    win_sum, loss_sum = float(p[p > 0].sum()), float(abs(p[p < 0].sum())))
                    monthly_rows.append({
                        "symbol": symbol, "strategy": strategy, "month": month, "trades": len(group),
                        "win_rate_pct": round(100 * float((p > 0).mean()), 2),
                        "net_points": round(float(p.sum()), 2),
                        "profit_factor": round(win_sum / loss_sum, 2) if loss_sum else ("inf" if win_sum else 0.0),
                    })
            print(f"{symbol} {strategy}: candidates={summary['candidate_vwap_crosses']}, "
                  f"passed={summary['signals_after_filter']}, trades={summary['trades']}")

    pd.DataFrame(summaries).to_csv(output / "summary.csv", index=False)
    pd.DataFrame(monthly_rows, columns=[
        "symbol", "strategy", "month", "trades", "win_rate_pct", "net_points", "profit_factor"
    ]).to_csv(output / "monthly_summary.csv", index=False)
    print("\nVWAP STRATEGY COMPARISON")
    print(pd.DataFrame(summaries)[[
        "symbol", "strategy", "candidate_vwap_crosses", "signals_after_filter",
        "trades", "win_rate_pct", "net_points", "profit_factor", "max_drawdown_points"
    ]].to_string(index=False))
    print("\nAll CSVs include headers even when no trades/signals qualify.")
    print("Underlying index points only; options premium, IV, theta, brokerage, taxes and slippage are not modelled.")


if __name__ == "__main__":
    main()
