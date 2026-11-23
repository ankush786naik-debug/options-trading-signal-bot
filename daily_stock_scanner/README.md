# Daily NSE Swing Stock Scanner

Independent daily swing scanner for NSE cash equities. It uses the Upstox BOD NSE instrument master and daily OHLCV candles, then sends qualifying BUY setup alerts to Telegram.

## Scope
- NSE listed cash equity instruments (NSE_EQ, equity instrument type)
- Price filter: ₹200–₹1,000 (configurable)
- Daily candles; scans after market close on weekdays
- Support/pullback/reversal and trend-confirmation scoring
- Telegram alerts only; no order placement

## GitHub Actions secrets
Reuse the existing repository secrets:
- UPSTOX_ANALYTICS_TOKEN
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID

The scanner reads these secrets independently of the options bot. Do not put tokens in source files.

## Schedule
Runs weekdays at 3:45 PM IST (10:15 UTC). GitHub Actions scheduling is best-effort and may be delayed.

## Signal method
The scanner scores a setup using:
- Price within configured range
- Near 20/50-day EMA or recent support zone
- Medium-term trend confirmation
- RSI recovery / bullish momentum
- MACD histogram improving or bullish crossover
- Volume confirmation and average traded value
- ATR-based stop and 5% / 10% target levels (with a 15% stretch reference)

A BUY alert is a technical watchlist signal, not a guaranteed profitable trade. Verify chart, liquidity, corporate news and risk before acting. Stocks with insufficient or stale candles are skipped.

## Run locally
    pip install -r daily_stock_scanner/requirements.txt
    python daily_stock_scanner/scanner.py

## Configuration
Environment variables:
- MIN_PRICE (default 200)
- MAX_PRICE (default 1000)
- MIN_AVG_VALUE (default ₹1 crore average daily traded value over 20 sessions)
- MIN_SCORE (default 70)
- MAX_WORKERS (default 4; rate-limit-conscious)
- ALERTS_ENABLED (default true when Telegram secrets exist)

The NSE instrument master is refreshed each run from Upstox's official BOD JSON file. Upstox historical candles are fetched one instrument at a time; the scanner throttles requests and reports failures rather than fabricating data.
