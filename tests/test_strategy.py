import unittest
import pandas as pd
from strategy import analyze_setup


class DTPWithEMATests(unittest.TestCase):
    def make_frame(self, **updates):
        row = {
            "timestamp": pd.Timestamp("2026-01-01 10:00", tz="UTC"),
            "close": 25000.0,
            "atr14": 100.0,
            "ema20": 25050.0,
            "ema50": 25000.0,
            "dtp_state": 1,
            "dtp_buy": True,
            "dtp_sell": False,
        }
        row.update(updates)
        return pd.DataFrame([row, row])

    def test_bullish_dtp_flip_with_ema_alignment_returns_call(self):
        result = analyze_setup(self.make_frame(), "TEST")
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "CALL")
        self.assertEqual(result["underlying_stop"], 24850.0)
        self.assertEqual(result["underlying_target"], 25300.0)
        self.assertEqual(result["ema20"], 25050.0)

    def test_bullish_signal_blocked_when_ema20_below_ema50(self):
        result = analyze_setup(self.make_frame(ema20=24900.0, ema50=25000.0), "TEST")
        self.assertIsNone(result)

    def test_bearish_dtp_flip_with_ema_alignment_returns_put(self):
        result = analyze_setup(self.make_frame(
            ema20=24900.0, ema50=25000.0, dtp_state=-1,
            dtp_buy=False, dtp_sell=True
        ), "TEST")
        self.assertIsNotNone(result)
        self.assertEqual(result["side"], "PUT")
        self.assertEqual(result["underlying_stop"], 25150.0)
        self.assertEqual(result["underlying_target"], 24700.0)

    def test_bearish_signal_blocked_when_ema20_above_ema50(self):
        result = analyze_setup(self.make_frame(
            dtp_buy=False, dtp_sell=True, dtp_state=-1,
            ema20=25100.0, ema50=25000.0
        ), "TEST")
        self.assertIsNone(result)

    def test_no_signal_without_dtp_flip(self):
        result = analyze_setup(self.make_frame(dtp_buy=False, dtp_sell=False), "TEST")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
