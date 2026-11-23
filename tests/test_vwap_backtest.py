import unittest

import pandas as pd

from vwap_strategy_backtest import add_indicators, run_backtest
from vwap_futures_data import fetch_continuous_futures


class VwapBacktestTests(unittest.TestCase):
    def setUp(self):
        timestamps = pd.date_range("2026-01-05 09:15", periods=4, freq="5min", tz="Asia/Kolkata")
        next_day = pd.date_range("2026-01-06 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
        closes = [10.0, 9.0, 11.0, 10.0, 20.0, 19.0, 21.0]
        times = list(timestamps) + list(next_day)
        self.data = pd.DataFrame({
            "timestamp": times,
            "open": closes,
            "high": [x + 1 for x in closes],
            "low": [x - 1 for x in closes],
            "close": closes,
            "volume": [100.0] * len(closes),
            "session": [t.date() for t in times],
        })

    def test_vwap_resets_each_session(self):
        result = add_indicators(self.data)
        self.assertAlmostEqual(result.vwap.iloc[0], 10.0)
        self.assertAlmostEqual(result.vwap.iloc[4], 20.0)
        self.assertFalse(bool(result.bull_cross.iloc[4]))
        self.assertFalse(bool(result.bear_cross.iloc[4]))

    def test_vwap_crosses_are_detected(self):
        result = add_indicators(self.data)
        self.assertTrue(bool(result.bull_cross.iloc[2]))

    def test_adx_filter_does_not_accept_missing_adx(self):
        summary, trades, signals = run_backtest(
            self.data, "TEST", "VWAP_ADX", adx_threshold=20.0, cost_points=0.0
        )
        self.assertGreater(summary["candidate_vwap_crosses"], 0)
        self.assertEqual(summary["signals_after_filter"], 0)
        self.assertTrue(trades.empty)
        self.assertFalse(signals.empty)
        self.assertTrue(signals.adx_filter_passed.eq(False).all())

    def test_zero_futures_volume_stops_backtest_data(self):
        class FakeClient:
            def get(self, path, params=None):
                return {"candles": [
                    ["2025-01-06T09:15:00+05:30", 100, 101, 99, 100, 0, 0],
                ]}

        contracts = [{
            "symbol": "TEST", "instrument_key": "NSE_FO|test",
            "expired_instrument_key": "NSE_FO|test|30-01-2025",
            "expiry": "2025-01-30", "expired": True, "trading_symbol": "TEST FUT",
        }]
        with self.assertRaisesRegex(RuntimeError, "futures volume invalid"):
            fetch_continuous_futures(
                FakeClient(), contracts, "TEST",
                pd.Timestamp("2025-01-01").date(), pd.Timestamp("2025-01-10").date()
            )


if __name__ == "__main__":
    unittest.main()
