import unittest
import numpy as np
import pandas as pd

from scanner import add_indicators, evaluate_setup, format_signal


class DailyScannerTests(unittest.TestCase):
    def make_candles(self, price=350.0):
        n = 260
        trend = np.linspace(price * 0.82, price * 1.04, n)
        # Last sessions pull back toward the 20-day average/support.
        trend[-8:] = np.linspace(trend[-9], trend[-9] * 0.985, 8)
        dates = pd.date_range("2025-01-01", periods=n, freq="B", tz="Asia/Kolkata")
        return pd.DataFrame({
            "timestamp": dates,
            "open": trend * 0.998,
            "high": trend * 1.012,
            "low": trend * 0.988,
            "close": trend,
            "volume": np.full(n, 150000.0),
        })

    def test_indicator_columns_are_created(self):
        result = add_indicators(self.make_candles())
        for column in ("ema20", "ema50", "ema200", "rsi", "macd_hist", "atr", "value_avg20"):
            self.assertIn(column, result.columns)
        self.assertTrue(np.isfinite(result.iloc[-1]["atr"]))

    def test_price_outside_configured_range_is_not_signal(self):
        instrument = {"symbol": "TEST", "name": "Test Ltd"}
        self.assertIsNone(evaluate_setup(instrument, self.make_candles(price=150), 150))
        self.assertIsNone(evaluate_setup(instrument, self.make_candles(price=1200), 1200))

    def test_telegram_signal_has_entry_stop_and_targets(self):
        signal = {
            "symbol": "TEST", "name": "Test Ltd", "score": 80,
            "price": 350.0, "rsi": 52.0, "volume_ratio": 1.4,
            "stop": 338.0, "risk_pct": 3.4, "target1": 367.5,
            "target2": 385.0, "stretch": 402.5,
            "reasons": ["near EMA/support", "RSI recovery"], "asof": "2026-11-20",
        }
        text = format_signal(signal)
        for required in ("Entry zone", "Stop-loss", "Target 1", "Target 2", "TEST"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
