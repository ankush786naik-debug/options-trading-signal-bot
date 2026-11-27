# NIFTY Intraday Bias Signal (Paper Only)

This is a separate, optional technical-bias report for NIFTY. It does not modify the production entry strategy, place orders, select option contracts, or turn Telegram alerts on.

## Run during NSE market hours

From the repository root:

```bash
python -m research.intraday_bias.nifty_intraday_signal
```

Prints UP / DOWN / FLAT heuristic weights and the indicator reasons. It uses completed 5-minute candles and completed 15-minute trend data from the existing Upstox client.

To send the report to Telegram:

```bash
python -m research.intraday_bias.nifty_intraday_signal --telegram
```

Telegram requires `ALERTS_ENABLED=true` and valid credentials. The default is print-only.

## Important limitations

- The percentages are transparent **heuristic weights**, not empirically calibrated probabilities or expected option returns.
- The module does not fetch headlines, RBI/macroeconomic news, FII/DII flow, India VIX, or option-chain Greeks. Do not interpret its output as a complete market forecast.
- VWAP is omitted when the feed has missing/zero volume.
- It reports only during the configured 09:20–14:45 IST window and rejects stale 5-minute candles.
- Use the existing entry rules and liquid ATM/ITM option checks for any separate paper setup. No live order is placed.
- Do not deploy these heuristic percentages as a profitability claim. Calibrate them using walk-forward backtests before relying on them.
