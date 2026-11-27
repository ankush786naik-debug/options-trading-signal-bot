# Indian Options Trading Signal Bot

Python-based Indian index options paper-signal system using Upstox data.

## Strategy (paper signals only)

The index signal is evaluated on completed **15-minute candles** using:

1. **Dynamic Trend Pivots (BOSWaves)** bullish/bearish trend flip.
2. **EMA 20/EMA 50 alignment** as the trend filter.
   - BUY CE: DTP bullish flip and EMA20 > EMA50.
   - BUY PE: DTP bearish flip and EMA20 < EMA50.
3. ATR 14 is used only to calculate underlying invalidation (1.5 ATR) and target (3 ATR); it is not a directional signal filter.

The old RSI, ADX, VWAP, EMA9/21, MACD and Supertrend signal filters have been removed from the option-entry logic. Option contract liquidity/spread checks and option-premium risk levels remain.

### Important indicator accuracy note

The original BOSWaves Pine Script source was not available during this change. `indicators.py` contains a transparent **reconstruction** of the adaptive EMA/MAD bands and conviction-pulse idea using the chart settings (trend length 21, close zone 0.30, pulse decay 0.80, pulse cap 8, MAD length 17, band multipliers 1.4–2.2). This is not claimed to be an exact Pine-script port. Verify against the original Pine source before using signals for live trading.

## Supported indices
- NIFTY
- BANKNIFTY
- SENSEX

## Option selection and Telegram
- Selects closest liquid ATM/ITM contract; OTM contracts are rejected.
- Checks bid/ask spread and trading volume.
- Telegram signal includes EMA20/EMA50, DTP state, ATR risk levels, option premium, OI and volume.
- Duplicate signals are suppressed and a 15-minute same-direction cooldown is applied.

## Setup
```bash
pip install -r requirements.txt
python main.py
```

Environment variables:
- `UPSTOX_ANALYTICS_TOKEN`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ALERTS_ENABLED`

Run unit tests:
```bash
python -m unittest discover -s tests
python test_scanner.py
```

## Daily NSE Swing Stock Scanner

A separate project scans NSE cash equities and is not modified by the index-options strategy change.

- Project: [daily_stock_scanner](daily_stock_scanner/README.md)
- Workflow: [Daily NSE Stock Scanner](.github/workflows/daily-stock-scanner.yml)

## Safety
This is a signal and paper-analysis system only. It does not place live orders. Signals are not guaranteed to be profitable.
