# Daily NSE Swing Stock Scanner

Independent daily swing scanner for NSE cash equities. It uses the Upstox BOD NSE instrument master and daily OHLCV candles, then sends qualifying BUY setup alerts to Telegram.

## Scope
- NSE listed cash equity instruments (NSE_EQ, equity instrument type)
- No stock price boundary; scans all NSE EQ stocks with valid LTP
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

## Fundamental + technical Top 5 ranking

The scanner uses Upstox Company Fundamentals endpoints (ISIN-based) for key ratios, yearly income statement, cash flow and balance sheet data. It scores ROCE, ROE, revenue/profit growth, valuation versus sector, operating cash-flow consistency and liabilities/assets. Candidates with insufficient fundamental coverage are excluded rather than treated as high quality.

The daily alert ranks at most five stocks from the strongest technical candidates. Combined score = 55% fundamental score + 45% technical score. Default fundamental minimum is 50/100; the scanner evaluates fundamentals for up to 60 leading technical setups to control API usage.

## Signal method
The scanner scores a setup using:
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
- MIN_AVG_VALUE (default ₹1 crore average daily traded value over 20 sessions)
- MIN_SCORE (default 70)
- MAX_WORKERS (default 4; rate-limit-conscious)
- ALERTS_ENABLED (default true when Telegram secrets exist)

The NSE instrument master is refreshed each run from Upstox's official BOD JSON file, including ISINs required for fundamentals. There is no price boundary. The scanner fetches historical candles for the full universe and throttles requests to respect API limits; the full scan can take around an hour, depending on valid instruments and API response times.
