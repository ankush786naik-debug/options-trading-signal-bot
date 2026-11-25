# Strategy Lab

This directory is reserved for isolated index-signal experiments. Keep it separate from the live scanner and from the actual-options premium backtest.

## Data source

The manual workflow `Research - Download Historical Index Data` writes and uploads 1m, 5m and 15m candles for NIFTY, BANKNIFTY and SENSEX. The artifact contains the files under `data/backtest/underlying/`.

## Test protocol

1. Validate CSV timestamps, duplicates, gaps and date coverage.
2. Use 15m candles only after their close for trend confirmation.
3. Generate entry signals from completed 5m candles.
4. Execute at the next available 1m candle open (or next 5m open if 1m data is unavailable).
5. Compare individual strategies and combinations on identical dates.
6. Include transaction costs and conservative slippage.
7. Report train/validation/test or walk-forward results, monthly performance, trade count, win rate, profit factor and max drawdown.
8. Do not select a strategy on win rate alone; do not tune on the final holdout period.

No orders or Telegram messages are sent from this folder.
