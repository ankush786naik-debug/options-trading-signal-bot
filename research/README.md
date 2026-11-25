# Strategy Backtesting (Research Only)

The isolated script `research/backtest_options_strategies.py` compares several entry-rule families without importing or changing the live `strategy.py`.

## Input data

Place 5-minute underlying OHLCV files in `data/backtest/`:

- `NIFTY_5m.csv`
- `BANKNIFTY_5m.csv`
- `SENSEX_5m.csv`

Required columns: `timestamp,open,high,low,close`; `volume` is recommended. Timestamps should be candle-start times in IST or timezone-aware timestamps.

Run locally or in a notebook:

```bash
python research/backtest_options_strategies.py --data-dir data/backtest
```

You can also pass file paths directly:

```bash
python research/backtest_options_strategies.py NIFTY_5m.csv BANKNIFTY_5m.csv
```

The script writes `research/backtest_results/summary.csv` and `trades.csv`.

## Strategy variants

- EMA cross
- VWAP direction/reclaim
- RSI momentum
- EMA pullback
- EMA + VWAP + ADX trend
- Strict-current-style filters
- Score threshold 6/9
- Score threshold 7/9
- 20-bar breakout

The report includes trade count, win rate, profit factor, net underlying points, average R and max drawdown. Entries occur at the next candle open; stop/target collisions are resolved conservatively (stop first).

## Important limitations

This is an underlying directional backtest, not option-contract P&L. It cannot validate the live option selection, premium movement, spread, liquidity, expiry or brokerage. Use out-of-sample dates and actual option historical data before changing the live bot. A target win rate is not guaranteed.
