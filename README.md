
# Options Trading Signal Bot

An Indian index options signal scanner powered by Upstox.

## Supported indices

- NIFTY
- BANKNIFTY
- SENSEX

## Features

- Upstox market data
- 5-minute analysis
- 15-minute trend confirmation
- EMA 9 and EMA 21
- RSI 14
- CALL and PUT signals
- Option strike selection
- Entry, stop loss and targets
- Telegram alerts
- GitHub Actions automation

## Required GitHub Secrets

UPSTOX_ANALYTICS_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
OPTION_EXPIRY

OPTION_EXPIRY must contain an actual valid expiry date.

## Installation

pip install -r requirements.txt

## Run

python main.py

## Safety

This application generates signals only.

It does not place live trades.

Backtest and paper trade before using any
signal for actual trading.
