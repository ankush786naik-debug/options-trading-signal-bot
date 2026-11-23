import unittest
import pandas as pd

from ema_9_15_reversal_backtest import add_ema_crosses, backtest


class EMA915BacktestTests(unittest.TestCase):
    def test_ema_cross_columns_created(self):
        prices = [100 + i * 0.2 for i in range(25)] + [105, 104, 103, 102, 101]
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01 09:15", periods=len(prices), freq="5min", tz="Asia/Kolkata"),
            "open": prices, "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices], "close": prices,
            "volume": [100] * len(prices),
            "session": [pd.Timestamp("2026-01-01").date()] * len(prices),
        })
        result = add_ema_crosses(frame)
        self.assertIn("bull_cross", result)
        self.assertIn("bear_cross", result)
        self.assertTrue(result.bull_cross.any())
        self.assertTrue(result.bear_cross.any())

    def test_backtest_returns_trade_schema(self):
        prices = [100 + i * 0.25 for i in range(30)] + [107, 106, 105, 104, 103, 102, 101, 100]
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01 09:15", periods=len(prices), freq="5min", tz="Asia/Kolkata"),
            "open": prices, "high": [p + 0.5 for p in prices],
            "low": [p - 0.5 for p in prices], "close": prices,
            "volume": [100] * len(prices),
            "session": [pd.Timestamp("2026-01-01").date()] * len(prices),
        })
        trades = backtest(frame, cost_points=1.0)
        self.assertFalse(trades.empty)
        self.assertIn("net_points", trades.columns)
        self.assertTrue((trades.cost_points == 1.0).all())


if __name__ == "__main__":
    unittest.main()
