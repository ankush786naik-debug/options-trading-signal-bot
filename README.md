# Indian Options Trading Signal Bot

Python-based Indian index options buying analysis system using Upstox data.

## Supported indices
- NIFTY
- BANKNIFTY
- SENSEX

## Production signal setup
Signals are evaluated only on completed 5-minute candles and require completed 15-minute EMA confirmation.

### BUY CE
- Underlying close above session VWAP
- EMA 9 > EMA 21 on both 5-minute and 15-minute charts
- ADX 14 > 22
- RSI 14 > 60 and < 75
- A pullback in the prior 3 completed 5-minute candles near EMA 9, EMA 21, or VWAP (within 0.25 ATR)
- Current completed candle bullish
- Current volume above its 20-candle average

### BUY PE
- Underlying close below session VWAP
- EMA 9 < EMA 21 on both 5-minute and 15-minute charts
- ADX 14 > 22
- RSI 14 > 25 and < 40
- A pullback in the prior 3 completed 5-minute candles near EMA 9, EMA 21, or VWAP (within 0.25 ATR)
- Current completed candle bearish
- Current volume above its 20-candle average

The scanner is limited to 09:20–14:45 IST. The scheduled GitHub Actions workflow runs every five minutes on weekdays, refreshing the option chain/OI on each scan. It sends Telegram paper signals only and does not place live orders.

## Option selection and Telegram
- Selects the closest liquid ATM/ITM contract; OTM contracts are rejected.
- Checks bid/ask spread and trading volume.
- Telegram message includes option premium, premium-based risk levels, underlying ATR invalidation/2R target, indicators, OI and volume.
- Duplicate signals are suppressed and a 15-minute same-direction cooldown is applied.

## VWAP strategy comparison (backtest only)

The retired EMA 9/15 crossover experiment has been removed. The research backtest compares two strategies on approximately six months of 5-minute NIFTY, BANKNIFTY and SENSEX futures candles. Upstox Plus expired-futures endpoints supply expired contract metadata and candles; the official Upstox BOD instrument master supplies active futures.

1. **VWAP-only:** A bullish signal occurs when the completed candle crosses above session VWAP; a bearish signal occurs when it crosses below session VWAP.
2. **VWAP + ADX:** Uses the same VWAP-cross signal, but only accepts the signal when ADX(14) is at least the configured threshold (default 20).

Entry is at the next 5-minute candle open. A position exits at the next candle open after an opposite VWAP cross, or at the final completed candle of that session. VWAP resets each trading day. ADX is reset at futures contract rollovers. The backtest permits only one open position at a time per futures/strategy. Candidate and filtered signal counts are included for troubleshooting. It writes `futures_data_diagnostics.csv` and `contracts_used.csv`; it stops if futures volume is absent/mostly zero or VWAP is invalid.

Run from **Actions → VWAP Strategy Backtest → Run workflow**. The workflow uses the `UPSTOX_ANALYTICS_TOKEN` repository secret and creates the `vwap-futures-vwap-adx-6-months` artifact containing summary, monthly summary, data diagnostics, contracts used, signal diagnostics and per-index trade logs. Upstox documents expired expiry discovery as covering up to six months of historical expiries, so this workflow does not claim a 12-month sample.

Results are futures points, not actual option-premium P&L. Option strike selection, premium/IV changes, theta, brokerage, taxes and realistic slippage are not fully modelled. The cost input is only a futures-points proxy. This research workflow does not send alerts and does not modify the production scanner.

## Additional CSV backtest

Prepare historical underlying-index CSVs for 5-minute and 15-minute candles. Required headers:

`timestamp,open,high,low,close,volume`

Run:

```bash
python backtest.py --5m data_5m.csv --15m data_15m.csv --output backtest_results.csv
```

This separate general-purpose script compares indicators and higher-timeframe setups. It is not the retired EMA 9/15 experiment.

**Important limitation:** These are underlying-index-points proxies, not options-premium backtests. They do not model option premium, strike selection, IV, theta, brokerage, taxes or realistic slippage. Use them for research only; they do not establish live options profitability.

## Setup
```bash
pip install -r requirements.txt
```

Environment variables:
- `UPSTOX_ANALYTICS_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ALERTS_ENABLED`

Run scanner:
```bash
python main.py
```

Run unit tests:
```bash
python -m unittest discover -s tests
```

## Safety
This is a signal and paper-analysis system only. It does not place live orders. Signals are not guaranteed to be profitable.
