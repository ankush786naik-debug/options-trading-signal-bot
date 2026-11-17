# Indian Options Trading Signal Bot

Python-based Indian index options buying analysis system.

## Supported Indices

- NIFTY
- BANKNIFTY
- SENSEX

## Data Provider

Upstox Analytics API.

## Analysis Timeframes

- 5-minute candles
- 15-minute candles

## Indicators

- EMA 9, 21, 50
- RSI 14
- MACD
- VWAP
- ADX
- ATR
- Supertrend
- Volume

## Features

- CALL and PUT candidate signals
- Automatic ATM strike selection
- Option-chain analysis
- Entry, stop-loss and targets
- Telegram integration
- Duplicate signal protection
- Signal history

## Installation

pip install -r requirements.txt

## Environment Variables

UPSTOX_ANALYTICS_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
ALERTS_ENABLED

## Run API Test

python test_upstox.py

## Run Scanner

python main.py

## Safety

The application is for analysis and paper trading.

It does not place live orders.

Signals are not guaranteed to be profitable.
