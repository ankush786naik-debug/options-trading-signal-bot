"""
Actual OPTIONS PREMIUM backtest for this repository's options signal bot.

This research script:
- Reproduces the current strategy's indicators and strict entry rules.
- Tests individual filters and alternative combinations.
- Uses historical option-contract OHLC candles for entries/exits (not just index points).
- Selects historical CE/PE contracts nearest ATM/ITM using contract metadata.
- Simulates the bot's premium-based stop/targets.

No live orders, no Telegram, and does not import/change the live strategy.py.

Required input CSVs:
  data/backtest/underlying/NIFTY_5m.csv
  data/backtest/underlying/BANKNIFTY_5m.csv
  data/backtest/underlying/SENSEX_5m.csv
  data/backtest/options/options_5m.csv

Underlying columns:
  timestamp,open,high,low,close,volume

Options columns:
  timestamp,instrument_key,option_type,strike,expiry,open,high,low,close,volume
Optional options columns:
  bid,ask,lot_size

Timestamp must identify candle START time and be in IST or timezone-aware.
Option CSV must contain historical contracts for the test period, including expired contracts.
Historical option OHLC data is essential; live option-chain LTP cannot substitute for it.

Run:
  python research/backtest_actual_options.py --data-dir data/backtest

Output:
  research/backtest_results/options_summary.csv
  research/backtest_results/options_trades.csv
"""

import argparse
from pathlib import Path
import sys

import numpy as np
import pandas as pd


UNDERLYINGS = ["NIFTY", "BANKNIFTY", "SENSEX"]

# Strategy variants are deliberate filter ablations/combinations.
STRATEGIES = [
    "live_strict",
    "strict_no_volume",
    "strict_no_adx",
    "strict_no_rsi_band",
    "strict_no_15m",
    "strict_no_pullback",
    "trend_vwap",
    "rsi_momentum",
    "score_6of8",
    "score_5of8",
]


def timestamp_series(series):
    ts = pd.to_datetime(series, errors="coerce")
    if ts.dt.tz is not None:
        ts = ts.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    return ts


def load_underlying(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "timestamp" not in df.columns:
        for alternative in ("datetime", "date_time", "date"):
            if alternative in df.columns:
                df = df.rename(columns={alternative: "timestamp"})
                break
    needed = {"timestamp", "open", "high", "low", "close"}
    if not needed.issubset(df.columns):
        raise ValueError(f"{path}: required columns {sorted(needed)}")
    if "volume" not in df:
        df["volume"] = 0.0
    df["timestamp"] = timestamp_series(df["timestamp"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def load_options(path):
    df = pd.read_csv(path)
    df.columns = [str(c).strip().lower() for c in df.columns]
    needed = {
        "timestamp", "instrument_key", "option_type", "strike", "expiry",
        "open", "high", "low", "close", "volume"
    }
    if not needed.issubset(df.columns):
        raise ValueError(f"{path}: options CSV missing {sorted(needed - set(df.columns))}")
    df["timestamp"] = timestamp_series(df["timestamp"])
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    df["option_type"] = df["option_type"].astype(str).str.upper().str.strip()
    df["instrument_key"] = df["instrument_key"].astype(str)
    for col in ["strike", "open", "high", "low", "close", "volume", "bid", "ask", "lot_size"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "expiry", "strike", "open", "high", "low", "close"])
    return df.sort_values(["timestamp", "expiry", "strike"]).reset_index(drop=True)


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    result[(avg_gain > 0) & (avg_loss == 0)] = 100
    result[(avg_gain == 0) & (avg_loss > 0)] = 0
    result[(avg_gain == 0) & (avg_loss == 0)] = 50
    return result


def indicators(df):
    x = df.copy()
    c, h, l = x["close"], x["high"], x["low"]
    x["ema9"] = c.ewm(span=9, adjust=False).mean()
    x["ema21"] = c.ewm(span=21, adjust=False).mean()
    x["rsi"] = rsi(c)

    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    x["atr"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    up, down = h.diff(), -l.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr_safe = x["atr"].replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / atr_safe
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    x["adx"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    typical = (h + l + c) / 3
    session = x["timestamp"].dt.date
    cum_pv = (typical * x["volume"]).groupby(session).cumsum()
    cum_vol = x["volume"].groupby(session).cumsum()
    x["vwap"] = cum_pv / cum_vol.replace(0, np.nan)
    x["volume_avg"] = x["volume"].rolling(20, min_periods=20).mean()

    # 15m EMA trend; the bar is timestamped at its close and only merged after close.
    indexed = x.set_index("timestamp")
    slow = indexed.resample(
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


def near_pullback(df, i, side, tolerance_atr=0.25):
    row = df.iloc[i]
    if not np.isfinite(row["atr"]) or row["atr"] <= 0:
        return False
    window = df.iloc[max(0, i - 3):i]
    if len(window) < 3:
        return False
    levels = [row["ema9"], row["ema21"], row["vwap"]]
    for level in levels:
        if not np.isfinite(level):
            continue
        tol = max(row["atr"] * tolerance_atr, 0.01)
        if ((window["low"] <= level + tol) & (window["high"] >= level - tol)).any():
            return True
    return False


def score_setup(df, i, strategy):
    row = df.iloc[i]
    if i < 50:
        return 0
    fields = ["ema9", "ema21", "rsi", "adx", "atr", "vwap", "ema9_15", "ema21_15"]
    if any(pd.isna(row.get(k)) for k in fields):
        return 0

    prev = df.iloc[i - 1]
    up = row["close"] > row["open"]
    down = row["close"] < row["open"]
    fast_up, fast_down = row["ema9"] > row["ema21"], row["ema9"] < row["ema21"]
    slow_up, slow_down = row["ema9_15"] > row["ema21_15"], row["ema9_15"] < row["ema21_15"]
    above, below = row["close"] > row["vwap"], row["close"] < row["vwap"]
    volume_ok = pd.notna(row["volume_avg"]) and row["volume"] > row["volume_avg"]
    adx_ok = row["adx"] > 22
    call_rsi = 60 < row["rsi"] < 75
    put_rsi = 25 < row["rsi"] < 40
    pull_call = near_pullback(df, i, "CALL")
    pull_put = near_pullback(df, i, "PUT")

    if strategy == "live_strict":
        call = above and fast_up and slow_up and adx_ok and call_rsi and pull_call and up and volume_ok
        put = below and fast_down and slow_down and adx_ok and put_rsi and pull_put and down and volume_ok
    elif strategy == "strict_no_volume":
        call = above and fast_up and slow_up and adx_ok and call_rsi and pull_call and up
        put = below and fast_down and slow_down and adx_ok and put_rsi and pull_put and down
    elif strategy == "strict_no_adx":
        call = above and fast_up and slow_up and call_rsi and pull_call and up and volume_ok
        put = below and fast_down and slow_down and put_rsi and pull_put and down and volume_ok
    elif strategy == "strict_no_rsi_band":
        call = above and fast_up and slow_up and adx_ok and row["rsi"] > 50 and pull_call and up and volume_ok
        put = below and fast_down and slow_down and adx_ok and row["rsi"] < 50 and pull_put and down and volume_ok
    elif strategy == "strict_no_15m":
        call = above and fast_up and adx_ok and call_rsi and pull_call and up and volume_ok
        put = below and fast_down and adx_ok and put_rsi and pull_put and down and volume_ok
    elif strategy == "strict_no_pullback":
        call = above and fast_up and slow_up and adx_ok and call_rsi and up and volume_ok
        put = below and fast_down and slow_down and adx_ok and put_rsi and down and volume_ok
    elif strategy == "trend_vwap":
        call = above and fast_up and slow_up and up
        put = below and fast_down and slow_down and down
    elif strategy == "rsi_momentum":
        call = fast_up and row["rsi"] > 55 and row["rsi"] < 72 and up
        put = fast_down and row["rsi"] < 45 and row["rsi"] > 28 and down
    else:
        call_points = sum([
            1 if above else 0, 1 if fast_up else 0, 1 if slow_up else 0,
            1 if row["rsi"] > 52 and row["rsi"] < 72 else 0,
            1 if adx_ok else 0, 1 if pull_call else 0,
            1 if up else 0, 1 if volume_ok else 0,
        ])
        put_points = sum([
            1 if below else 0, 1 if fast_down else 0, 1 if slow_down else 0,
            1 if row["rsi"] < 48 and row["rsi"] > 28 else 0,
            1 if adx_ok else 0, 1 if pull_put else 0,
            1 if down else 0, 1 if volume_ok else 0,
        ])
        threshold = 6 if strategy == "score_6of8" else 5
        call, put = call_points >= threshold and call_points > put_points, put_points >= threshold and put_points > call_points

    if call and not put:
        return 1
    if put and not call:
        return -1
    return 0


def select_contract(options_at_entry, side, spot, signal_date):
    """Historical analogue of live selector: nearest eligible ATM/ITM contract."""
    if options_at_entry.empty:
        return None
    typ = "CE" if side == 1 else "PE"
    x = options_at_entry[
        (options_at_entry["option_type"] == typ)
        & (options_at_entry["expiry"] >= signal_date)
        & (options_at_entry["volume"] > 0)
    ].copy()
    if x.empty:
        return None

    # Live bot rejects OTM contracts: CE strike <= spot, PE strike >= spot.
    if side == 1:
        x = x[x["strike"] <= spot]
    else:
        x = x[x["strike"] >= spot]
    if x.empty:
        return None

    # Select nearest expiry first, then nearest strike, then volume.
    x["days_to_expiry"] = x["expiry"].apply(lambda d: (d - signal_date).days)
    x["strike_distance"] = (x["strike"] - spot).abs()
    x = x.sort_values(["days_to_expiry", "strike_distance", "volume"], ascending=[True, True, False])
    return x.iloc[0]


def backtest_symbol(df, options, symbol, strategy, sl_pct=20.0, target_pct=35.0,
                    max_hold=12, slippage_pct=0.15):
    trades = []
    opt_groups = {ts: grp for ts, grp in options.groupby("timestamp", sort=False)}
    i = 60
    while i < len(df) - 1:
        row = df.iloc[i]
        ts = row["timestamp"]
        if ts.hour < 9 or (ts.hour == 9 and ts.minute < 20) or ts.hour >= 15:
            i += 1
            continue

        side = score_setup(df, i, strategy)
        if not side:
            i += 1
            continue

        entry_i = i + 1
        entry_ts = df.iloc[entry_i]["timestamp"]
        option_rows = opt_groups.get(entry_ts)
        if option_rows is None:
            i += 1
            continue

        contract = select_contract(option_rows, side, float(row["close"]), ts.date())
        if contract is None or not np.isfinite(contract["open"]) or contract["open"] <= 0:
            i += 1
            continue

        entry = float(contract["open"]) * (1 + slippage_pct / 100)
        stop = entry * (1 - sl_pct / 100)
        target = entry * (1 + target_pct / 100)
        key = contract["instrument_key"]
        opt = options[options["instrument_key"] == key].set_index("timestamp").sort_index()

        exit_price, exit_ts, exit_reason = None, None, "TIME"
        future = opt.loc[opt.index >= entry_ts].head(max_hold + 1)
        for opt_ts, candle in future.iterrows():
            if opt_ts.date() != entry_ts.date() or opt_ts.hour >= 15:
                exit_price, exit_ts, exit_reason = float(candle["close"]), opt_ts, "EOD"
                break
            stop_hit = float(candle["low"]) <= stop
            target_hit = float(candle["high"]) >= target
            if stop_hit:  # conservative if both stop and target touched in same candle
                exit_price, exit_ts, exit_reason = stop, opt_ts, "STOP"
                break
            if target_hit:
                exit_price, exit_ts, exit_reason = target, opt_ts, "TARGET"
                break
            exit_price, exit_ts = float(candle["close"]), opt_ts

        if exit_price is None:
            i += 1
            continue

        exit_price *= (1 - slippage_pct / 100)
        pnl_pct = (exit_price - entry) / entry * 100
        lot_size = float(contract.get("lot_size", 1) or 1)
        pnl_points = exit_price - entry
        trades.append({
            "symbol": symbol, "strategy": strategy, "side": "CALL" if side == 1 else "PUT",
            "signal_time": ts, "entry_time": entry_ts, "expiry": contract["expiry"],
            "instrument_key": key, "strike": float(contract["strike"]),
            "entry_premium": round(entry, 2), "exit_premium": round(exit_price, 2),
            "stop_premium": round(stop, 2), "target_premium": round(target, 2),
            "exit_time": exit_ts, "exit_reason": exit_reason,
            "pnl_premium_points": round(pnl_points, 2),
            "pnl_per_lot": round(pnl_points * lot_size, 2),
            "return_pct": round(pnl_pct, 2), "lot_size": lot_size,
        })
        # one open position per index/strategy; skip to after exit candle
        exit_positions = df.index[df["timestamp"] == exit_ts]
        i = int(exit_positions[0]) + 1 if len(exit_positions) else entry_i + 1
    return trades


def metrics(trades):
    if trades.empty:
        return {"trades": 0, "win_rate_pct": 0.0, "avg_return_pct": 0.0,
                "net_premium_points": 0.0, "profit_factor": 0.0, "max_drawdown_pct": 0.0}
    ret = trades["return_pct"].astype(float)
    wins = ret[ret > 0].sum()
    losses = -ret[ret < 0].sum()
    equity = ret.cumsum()
    dd = equity - equity.cummax()
    return {
        "trades": int(len(ret)),
        "win_rate_pct": round(float((ret > 0).mean() * 100), 2),
        "avg_return_pct": round(float(ret.mean()), 3),
        "net_premium_points": round(float(trades["pnl_premium_points"].sum()), 2),
        "profit_factor": round(float(wins / losses), 3) if losses else (999.0 if wins else 0.0),
        "max_drawdown_pct": round(float(dd.min()), 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest the real options premium strategy variants.")
    parser.add_argument("--data-dir", default="data/backtest")
    parser.add_argument("--stop-loss", type=float, default=20.0, help="Option premium stop-loss percent (live bot: 20)")
    parser.add_argument("--target", type=float, default=35.0, help="Option premium target percent (live bot T2: 35)")
    parser.add_argument("--max-hold", type=int, default=12, help="Maximum 5m option candles to hold")
    parser.add_argument("--slippage", type=float, default=0.15, help="Percent slippage applied at entry and exit")
    parser.add_argument("--out-dir", default="research/backtest_results")
    args = parser.parse_args()

    root = Path(args.data_dir)
    option_path = root / "options" / "options_5m.csv"
    if not option_path.exists():
        print(f"Missing {option_path}. Historical option-contract candles are required for actual options P&L.")
        print("See research/README.md for the CSV schema; live option-chain LTP is not historical premium data.")
        return 2

    try:
        options = load_options(option_path)
    except Exception as exc:
        print(f"Cannot load options data: {exc}", file=sys.stderr)
        return 2

    all_trades, summaries = [], []
    for symbol in UNDERLYINGS:
        path = root / "underlying" / f"{symbol}_5m.csv"
        if not path.exists():
            print(f"Missing underlying file: {path}", file=sys.stderr)
            continue
        try:
            df = indicators(load_underlying(path))
        except Exception as exc:
            print(f"Skipping {symbol}: {exc}", file=sys.stderr)
            continue

        symbol_options = options.copy()
        # Index options in the combined file can be labelled by underlying_symbol if supplied.
        if "underlying_symbol" in symbol_options.columns:
            symbol_options = symbol_options[
                symbol_options["underlying_symbol"].astype(str).str.upper() == symbol
            ]
        print(f"{symbol}: {len(df):,} underlying bars; {len(symbol_options):,} option bars")

        for strategy in STRATEGIES:
            trades = backtest_symbol(
                df, symbol_options, symbol, strategy,
                sl_pct=args.stop_loss, target_pct=args.target,
                max_hold=args.max_hold, slippage_pct=args.slippage
            )
            trade_df = pd.DataFrame(trades)
            all_trades.extend(trades)
            summaries.append({"symbol": symbol, "strategy": strategy, **metrics(trade_df)})
            m = metrics(trade_df)
            print(f"  {strategy:22s} n={m['trades']:4d} win={m['win_rate_pct']:5.1f}% "
                  f"PF={m['profit_factor']:6.2f} avg={m['avg_return_pct']:7.2f}% "
                  f"net premium pts={m['net_premium_points']:8.2f}")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(summaries).to_csv(out / "options_summary.csv", index=False)
    pd.DataFrame(all_trades).to_csv(out / "options_trades.csv", index=False)
    print(f"Saved {out / 'options_summary.csv'}")
    print(f"Saved {out / 'options_trades.csv'}")
    print("Compare win rate with profit factor, avg return, trade count and drawdown.")
    print("No strategy is guaranteed to win 70-80%; use out-of-sample validation before live use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
