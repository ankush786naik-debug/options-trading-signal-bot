"""
One-year 5-minute Upstox data downloader + signal-variant backtest.

IMPORTANT:
This is a directional underlying-index research test, not option-premium P&L.
It tests whether signal variants predict subsequent index movement using ATR
risk levels. Accurate option P&L requires historical CE/PE contract OHLC
(including expired contracts), bid/ask/spread and actual contract selection.

Usage:
  pip install requests pandas numpy
  export UPSTOX_ANALYTICS_TOKEN="..."  # keep private; do not commit
  python research/backtest_signal_variants_1y.py
  python research/backtest_signal_variants_1y.py --from-date 2025-11-25 --to-date 2026-11-24
  python research/backtest_signal_variants_1y.py --backtest-only

Downloads 5-minute candles in month-sized chunks (Upstox API limit) for
NIFTY, BANKNIFTY and SENSEX; saves CSVs under data/backtest/underlying.
"""

import argparse
import os
import time
from pathlib import Path
from urllib.parse import quote
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://api.upstox.com"
INSTRUMENTS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX": "BSE_INDEX|SENSEX",
}

VARIANTS = [
    "live_strict", "no_volume", "no_adx", "no_rsi_band", "no_15m",
    "no_pullback", "no_vwap", "no_candle", "no_volume_adx",
    "no_adx_rsi", "no_15m_pullback", "trend_vwap", "rsi_momentum",
    "score_6of8", "score_5of8", "score_4of8",
]


def month_chunks(start: date, end: date):
    cursor = start
    while cursor <= end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        chunk_end = min(end, next_month - timedelta(days=1))
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


def fetch_candles(session, instrument_key, start, end, interval=5):
    """Fetch candles oldest-to-newest in monthly chunks; API returns newest first."""
    key = quote(instrument_key, safe="")
    collected = []
    for chunk_start, chunk_end in month_chunks(start, end):
        url = (
            f"{BASE_URL}/v3/historical-candle/{key}/minutes/{interval}/"
            f"{chunk_end.isoformat()}/{chunk_start.isoformat()}"
        )
        response = session.get(url, timeout=(15, 60))
        if response.status_code == 429:
            time.sleep(2)
            response = session.get(url, timeout=(15, 60))
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(f"Upstox returned unsuccessful response for {instrument_key}: {payload}")
        candles = (payload.get("data") or {}).get("candles") or []
        collected.extend(candles)
        print(f"  {chunk_start} to {chunk_end}: {len(candles)} candles")
        time.sleep(0.25)

    if not collected:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(collected, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(IST)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df = df[(df["timestamp"].dt.date >= start) & (df["timestamp"].dt.date <= end)]
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def rsi_wilder(close, period=14):
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result[(avg_gain > 0) & (avg_loss == 0)] = 100
    result[(avg_gain == 0) & (avg_loss > 0)] = 0
    result[(avg_gain == 0) & (avg_loss == 0)] = 50
    return result


def calculate_research_indicators(df):
    """Match indicators.py calculations used by the live strategy."""
    x = df.copy()
    close, high, low = x["close"], x["high"], x["low"]
    volume = x["volume"].fillna(0)
    x["ema9"] = close.ewm(span=9, adjust=False).mean()
    x["ema21"] = close.ewm(span=21, adjust=False).mean()
    x["rsi"] = rsi_wilder(close)

    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr_safe = x["atr"].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    typical = (high + low + close) / 3
    session = x["timestamp"].dt.date
    x["vwap"] = (typical * volume).groupby(session).cumsum() / volume.groupby(session).cumsum().replace(0, np.nan)
    x["volume_avg"] = volume.rolling(20, min_periods=20).mean()

    slow = x.set_index("timestamp").resample(
        "15min", origin="start_day", offset="9h15min", label="right", closed="left"
    ).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    slow = slow.dropna(subset=["close"])
    slow["ema9_15"] = slow["close"].ewm(span=9, adjust=False, min_periods=9).mean()
    slow["ema21_15"] = slow["close"].ewm(span=21, adjust=False, min_periods=21).mean()
    slow = slow[["ema9_15", "ema21_15"]].reset_index().rename(columns={"timestamp": "slow_timestamp"})
    x["bar_end"] = x["timestamp"] + pd.Timedelta(minutes=5)
    x = pd.merge_asof(
        x.sort_values("bar_end"), slow.sort_values("slow_timestamp"),
        left_on="bar_end", right_on="slow_timestamp", direction="backward"
    )
    return x.sort_values("timestamp").reset_index(drop=True)


def touched_pullback(df, i):
    row = df.iloc[i]
    if not np.isfinite(row["atr"]) or row["atr"] <= 0:
        return False
    window = df.iloc[i - 3:i]
    if len(window) != 3:
        return False
    tol = max(float(row["atr"]) * 0.25, 0.01)
    for level in (row["ema9"], row["ema21"], row["vwap"]):
        if np.isfinite(level) and ((window["low"] <= level + tol) & (window["high"] >= level - tol)).any():
            return True
    return False


def signal_side(df, i, variant):
    row = df.iloc[i]
    if i < 60:
        return 0
    keys = ["ema9", "ema21", "rsi", "adx", "atr", "vwap", "ema9_15", "ema21_15"]
    if any(pd.isna(row[k]) for k in keys):
        return 0
    up_candle = row["close"] > row["open"]
    down_candle = row["close"] < row["open"]
    fast_up, fast_down = row["ema9"] > row["ema21"], row["ema9"] < row["ema21"]
    slow_up, slow_down = row["ema9_15"] > row["ema21_15"], row["ema9_15"] < row["ema21_15"]
    above, below = row["close"] > row["vwap"], row["close"] < row["vwap"]
    adx_ok = row["adx"] > 22
    call_rsi, put_rsi = 60 < row["rsi"] < 75, 25 < row["rsi"] < 40
    volume_ok = pd.notna(row["volume_avg"]) and row["volume"] > row["volume_avg"]
    pullback = touched_pullback(df, i)

    if variant == "live_strict":
        call = above and fast_up and slow_up and adx_ok and call_rsi and pullback and up_candle and volume_ok
        put = below and fast_down and slow_down and adx_ok and put_rsi and pullback and down_candle and volume_ok
    elif variant == "no_volume":
        call = above and fast_up and slow_up and adx_ok and call_rsi and pullback and up_candle
        put = below and fast_down and slow_down and adx_ok and put_rsi and pullback and down_candle
    elif variant == "no_adx":
        call = above and fast_up and slow_up and call_rsi and pullback and up_candle and volume_ok
        put = below and fast_down and slow_down and put_rsi and pullback and down_candle and volume_ok
    elif variant == "no_rsi_band":
        call = above and fast_up and slow_up and adx_ok and row["rsi"] > 50 and pullback and up_candle and volume_ok
        put = below and fast_down and slow_down and adx_ok and row["rsi"] < 50 and pullback and down_candle and volume_ok
    elif variant == "no_15m":
        call = above and fast_up and adx_ok and call_rsi and pullback and up_candle and volume_ok
        put = below and fast_down and adx_ok and put_rsi and pullback and down_candle and volume_ok
    elif variant == "no_pullback":
        call = above and fast_up and slow_up and adx_ok and call_rsi and up_candle and volume_ok
        put = below and fast_down and slow_down and adx_ok and put_rsi and down_candle and volume_ok
    elif variant == "no_vwap":
        call = fast_up and slow_up and adx_ok and call_rsi and pullback and up_candle and volume_ok
        put = fast_down and slow_down and adx_ok and put_rsi and pullback and down_candle and volume_ok
    elif variant == "no_candle":
        call = above and fast_up and slow_up and adx_ok and call_rsi and pullback and volume_ok
        put = below and fast_down and slow_down and adx_ok and put_rsi and pullback and volume_ok
    elif variant == "no_volume_adx":
        call = above and fast_up and slow_up and call_rsi and pullback and up_candle
        put = below and fast_down and slow_down and put_rsi and pullback and down_candle
    elif variant == "no_adx_rsi":
        call = above and fast_up and slow_up and pullback and up_candle and volume_ok
        put = below and fast_down and slow_down and pullback and down_candle and volume_ok
    elif variant == "no_15m_pullback":
        call = above and fast_up and adx_ok and call_rsi and up_candle and volume_ok
        put = below and fast_down and adx_ok and put_rsi and down_candle and volume_ok
    elif variant == "trend_vwap":
        call = above and fast_up and slow_up and up_candle
        put = below and fast_down and slow_down and down_candle
    elif variant == "rsi_momentum":
        call = fast_up and 55 < row["rsi"] < 72 and up_candle
        put = fast_down and 28 < row["rsi"] < 45 and down_candle
    else:
        call_pts = sum([above, fast_up, slow_up, 52 < row["rsi"] < 72, adx_ok, pullback, up_candle, volume_ok])
        put_pts = sum([below, fast_down, slow_down, 28 < row["rsi"] < 48, adx_ok, pullback, down_candle, volume_ok])
        threshold = {"score_6of8": 6, "score_5of8": 5, "score_4of8": 4}[variant]
        call, put = call_pts >= threshold and call_pts > put_pts, put_pts >= threshold and put_pts > call_pts

    return 1 if call and not put else (-1 if put and not call else 0)


def run_backtest(df, variant, stop_atr=1.5, target_atr=3.0, max_hold=12):
    """Index-points proxy; signal at completed close, entry next bar open."""
    trades = []
    i = 60
    while i < len(df) - 1:
        row = df.iloc[i]
        ts = row["timestamp"]
        local_ts = ts.tz_convert(IST) if ts.tzinfo else ts.replace(tzinfo=IST)
        if local_ts.hour < 9 or (local_ts.hour == 9 and local_ts.minute < 20) or local_ts.hour >= 15:
            i += 1
            continue
        side = signal_side(df, i, variant)
        if not side:
            i += 1
            continue
        entry_i = i + 1
        entry_row = df.iloc[entry_i]
        entry = float(entry_row["open"])
        atr = float(row["atr"])
        stop = entry - side * stop_atr * atr
        target = entry + side * target_atr * atr
        exit_price, exit_time, reason = float(entry_row["close"]), entry_row["timestamp"], "TIME"
        last_i = min(len(df) - 1, entry_i + max_hold - 1)
        for j in range(entry_i, last_i + 1):
            bar = df.iloc[j]
            bar_ts = bar["timestamp"]
            local = bar_ts.tz_convert(IST) if bar_ts.tzinfo else bar_ts.replace(tzinfo=IST)
            if local.date() != local_ts.date() or local.hour >= 15:
                exit_price, exit_time, reason = float(df.iloc[j - 1]["close"] if j > entry_i else bar["open"]), bar_ts, "EOD"
                break
            stop_hit = float(bar["low"]) <= stop if side == 1 else float(bar["high"]) >= stop
            target_hit = float(bar["high"]) >= target if side == 1 else float(bar["low"]) <= target
            if stop_hit:
                exit_price, exit_time, reason = stop, bar_ts, "STOP"
                break
            if target_hit:
                exit_price, exit_time, reason = target, bar_ts, "TARGET"
                break
            exit_price, exit_time = float(bar["close"]), bar_ts
        points = (exit_price - entry) * side
        trades.append({
            "variant": variant, "side": "CALL" if side == 1 else "PUT",
            "signal_time": ts, "entry_time": entry_row["timestamp"], "exit_time": exit_time,
            "entry_index": entry, "exit_index": exit_price, "exit_reason": reason,
            "pnl_index_points": points, "return_pct_underlying": points / entry * 100,
        })
        i = j + 1
    return pd.DataFrame(trades)


def trade_metrics(trades):
    if trades.empty:
        return {"trades": 0, "win_rate_pct": 0.0, "avg_points": 0.0, "net_points": 0.0,
                "profit_factor": 0.0, "max_drawdown_points": 0.0}
    p = trades["pnl_index_points"].astype(float)
    positive, negative = p[p > 0].sum(), -p[p < 0].sum()
    equity = p.cumsum()
    drawdown = equity - equity.cummax()
    return {
        "trades": int(len(p)),
        "win_rate_pct": round(float((p > 0).mean() * 100), 2),
        "avg_points": round(float(p.mean()), 2),
        "net_points": round(float(p.sum()), 2),
        "profit_factor": round(float(positive / negative), 3) if negative else (999.0 if positive else 0.0),
        "max_drawdown_points": round(float(drawdown.min()), 2),
    }


def run_symbol(symbol, raw, out_dir, stop_atr, target_atr, max_hold):
    df = calculate_research_indicators(raw)
    # Reserve the latest 20% of dates as chronological holdout.
    unique_dates = sorted(df["timestamp"].dt.date.unique())
    cut = unique_dates[max(1, int(len(unique_dates) * 0.8))] if len(unique_dates) > 5 else unique_dates[-1]
    results, all_trade_rows = [], []
    for variant in VARIANTS:
        full = run_backtest(df, variant, stop_atr, target_atr, max_hold)
        if full.empty:
            full = pd.DataFrame(columns=["variant", "signal_time", "pnl_index_points"])
        full["symbol"] = symbol
        full["period"] = "full"
        results.append({"symbol": symbol, "period": "full", "variant": variant, **trade_metrics(full)})
        holdout = full[pd.to_datetime(full["signal_time"]).dt.date >= cut].copy() if not full.empty else full
        results.append({"symbol": symbol, "period": "holdout_20pct", "variant": variant, **trade_metrics(holdout)})
        all_trade_rows.extend(full.to_dict("records"))
        print(f"{symbol:10s} {variant:20s} trades={len(full):4d} win={trade_metrics(full)['win_rate_pct']:5.1f}% "
              f"PF={trade_metrics(full)['profit_factor']:6.2f} net={trade_metrics(full)['net_points']:9.2f} pts")
    return results, all_trade_rows


def main():
    parser = argparse.ArgumentParser(description="Download one year of Upstox 5m index candles and test signal variants.")
    parser.add_argument("--from-date", default=(date.today() - timedelta(days=365)).isoformat())
    parser.add_argument("--to-date", default=(date.today() - timedelta(days=1)).isoformat())
    parser.add_argument("--data-dir", default="data/backtest/underlying")
    parser.add_argument("--out-dir", default="research/backtest_results")
    parser.add_argument("--backtest-only", action="store_true", help="Use existing CSVs; do not call Upstox")
    parser.add_argument("--stop-atr", type=float, default=1.5)
    parser.add_argument("--target-atr", type=float, default=3.0)
    parser.add_argument("--max-hold", type=int, default=12)
    args = parser.parse_args()
    start, end = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)
    if start > end:
        parser.error("--from-date must be before --to-date")
    data_dir, out_dir = Path(args.data_dir), Path(args.out_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if not args.backtest_only:
        token = os.getenv("UPSTOX_ANALYTICS_TOKEN", "").strip()
        if not token:
            parser.error("Set UPSTOX_ANALYTICS_TOKEN in your environment; do not put it in the script or commit it.")
        session = requests.Session()
        session.headers.update({"Accept": "application/json", "Authorization": f"Bearer {token}"})
        for symbol, instrument_key in INSTRUMENTS.items():
            print(f"Downloading {symbol} 5-minute candles from {start} to {end}...")
            df = fetch_candles(session, instrument_key, start, end)
            path = data_dir / f"{symbol}_5m.csv"
            df.to_csv(path, index=False)
            print(f"Saved {len(df):,} candles: {path}")
    summaries, trades = [], []
    for symbol in INSTRUMENTS:
        path = data_dir / f"{symbol}_5m.csv"
        if not path.exists():
            print(f"Missing {path}; skipping {symbol}")
            continue
        raw = pd.read_csv(path)
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
        if raw["timestamp"].dt.tz is None:
            raw["timestamp"] = raw["timestamp"].dt.tz_localize(IST)
        else:
            raw["timestamp"] = raw["timestamp"].dt.tz_convert(IST)
        raw = raw.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
        if raw.empty:
            print(f"No valid candles in {path}; skipping")
            continue
        print(f"Backtesting {symbol}: {len(raw):,} bars")
        result, trade_rows = run_symbol(symbol, raw, out_dir, args.stop_atr, args.target_atr, args.max_hold)
        summaries.extend(result)
        trades.extend(trade_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(out_dir / "signal_variants_1y_summary.csv", index=False)
    pd.DataFrame(trades).to_csv(out_dir / "signal_variants_1y_trades.csv", index=False)
    print(f"Saved {out_dir / 'signal_variants_1y_summary.csv'}")
    print(f"Saved {out_dir / 'signal_variants_1y_trades.csv'}")
    print("Reminder: this is an underlying index-points proxy, not option premium P&L.")
    print("Compare holdout results, trade count, profit factor and drawdown; don't select by win rate alone.")


if __name__ == "__main__":
    main()
