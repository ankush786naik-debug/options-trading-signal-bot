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

## Additional CSV backtest

Prepare historical underlying-index CSVs for 5-minute and 15-minute candles. Required headers:

`timestamp,open,high,low,close,volume`

Run:
```bash
python backtest.py --5m data_5m.csv --15m data_15m.csv --output backtest_results.csv
```

This separate general-purpose script compares indicators and higher-timeframe setups.

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
