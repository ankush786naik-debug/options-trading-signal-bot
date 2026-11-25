# Actual Options Premium Backtesting (Research Only)

This research harness is specifically for the NIFTY, BANKNIFTY and SENSEX options-buying bot. It compares variants of the live entry rules and evaluates entries/exits using historical option-contract premiums.

## Files added

- `backtest_actual_options.py` — compares strategy combinations using option-contract OHLC
- `download_options_history.py` — downloads 5-minute option candles from Upstox V3 for a supplied contract manifest

These files do not change `strategy.py`, do not send Telegram alerts, and do not place orders.

## Required historical data

Underlying 5-minute candles:

- `data/backtest/underlying/NIFTY_5m.csv`
- `data/backtest/underlying/BANKNIFTY_5m.csv`
- `data/backtest/underlying/SENSEX_5m.csv`

Each needs `timestamp,open,high,low,close,volume`.

Historical option 5-minute candles:

- `data/backtest/options/options_5m.csv`

Required columns:

`timestamp,underlying_symbol,instrument_key,option_type,strike,expiry,open,high,low,close,volume,lot_size`

The options file must include historical CE and PE contracts for the whole test period, including expired contracts. Do not use current option-chain LTP as historical premium data.

## Download historical option candles

Prepare `data/backtest/options/option_contracts.csv` with columns:

`underlying_symbol,instrument_key,option_type,strike,expiry,lot_size`

The manifest must include the option instrument keys that existed during the chosen historical period. Upstox's current option-contract list may not provide expired contracts; retain/archive instrument master files or obtain the historical contract manifest from a source that includes expired instruments.

Set your Upstox token locally as an environment variable (never hardcode or commit it):

```bash
export UPSTOX_ANALYTICS_TOKEN="YOUR_TOKEN"
python research/download_options_history.py --contracts data/backtest/options/option_contracts.csv --from-date 2026-01-01 --to-date 2026-11-24
```

The downloader requests V3 5-minute candles in one-month chunks, then writes `options_5m.csv`. Upstox documents 1–15 minute V3 history as limited to one month per request; see [Upstox V3 Historical Candle API](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/). Some expired contracts may not be retrievable; the script logs and skips those.

## Run the actual option backtest

```bash
python research/backtest_actual_options.py --data-dir data/backtest
```

Outputs:

- `research/backtest_results/options_summary.csv`
- `research/backtest_results/options_trades.csv`

## Strategies compared

- `live_strict` — live bot's strict entry filters
- `strict_no_volume` — removes volume confirmation
- `strict_no_adx` — removes ADX gate
- `strict_no_rsi_band` — broadens RSI condition
- `strict_no_15m` — removes 15-minute trend confirmation
- `strict_no_pullback` — removes pullback gate
- `trend_vwap` — simpler trend/VWAP setup
- `rsi_momentum` — RSI + EMA momentum
- `score_6of8` and `score_5of8` — flexible score-based combinations

The backtest uses next-candle option open as entry, applies configurable premium stop/target (defaults reflect live bot's 20% stop and 35% target 2), and applies slippage at entry/exit. If stop and target are both touched in one candle, it assumes stop first. Results include trade count, win rate, average premium return, profit factor, net premium points and drawdown.

## Important

I have committed the actual-options backtest code, but have not run it on your account's historical option data. The report cannot be produced until the historical contract manifest and option candles are available. A 70–80% win rate is not guaranteed; compare win rate with profit factor, average return, trade count and drawdown, and validate on dates not used to tune the strategy before changing the live bot.
