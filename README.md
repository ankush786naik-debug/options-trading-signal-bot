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

## Daily NSE Swing Stock Scanner

A separate project scans NSE cash equities for daily swing-trading BUY setups (₹200–₹1,000 price range by default) and sends qualifying signals to Telegram after market close. It has its own scheduled workflow and does not modify the index-options scanner.

- Project: [daily_stock_scanner](daily_stock_scanner/README.md)
- Workflow: [Daily NSE Stock Scanner](.github/workflows/daily-stock-scanner.yml)
- Uses the existing Upstox and Telegram repository secrets
- Alerts only; no order execution

## Safety
This is a signal and paper-analysis system only. It does not place live orders. Signals are not guaranteed to be profitable.
