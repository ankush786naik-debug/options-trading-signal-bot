import unittest
import pandas as pd

from strategy import analyze_setup


def frame(rows):
    return pd.DataFrame(rows)


class BuyerStrategyTests(unittest.TestCase):
    def setUp(self):
        self.fast = []
        for i in range(60):
            self.fast.append({
                "timestamp": pd.Timestamp("2026-01-01 09:15") + pd.Timedelta(minutes=5 * i),
                "open": 100.0, "high": 102.0, "low": 99.8, "close": 101.0,
                "volume": 150.0, "volume_avg": 100.0,
                "ema9": 100.5, "ema21": 100.0, "rsi": 65.0,
                "adx": 28.0, "atr": 2.0, "vwap": 100.0,
            })
        self.fast[-1].update({"open": 101.0, "close": 102.0, "low": 100.4})
        self.slow = [{"close": 101.5, "ema9": 101.0, "ema21": 100.5}]

    def test_valid_bullish_setup_returns_call(self):
        result = analyze_setup(frame(self.fast), frame(self.slow), "TEST")
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "CALL")
        self.assertAlmostEqual(result["underlying_stop"], 99.0)
        self.assertAlmostEqual(result["underlying_target"], 108.0)

    def test_volume_confirmation_blocks_signal(self):
        self.fast[-1]["volume"] = 50.0
        result = analyze_setup(frame(self.fast), frame(self.slow), "TEST")
        self.assertIsNone(result)

    def test_15m_disagreement_blocks_signal(self):
        self.slow[0]["ema9"] = 100.0
        self.slow[0]["ema21"] = 100.5
        result = analyze_setup(frame(self.fast), frame(self.slow), "TEST")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
