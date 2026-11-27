import unittest
import pandas as pd
from indicators import calculate_indicators
from option_selector import select_option
from risk_manager import calculate_trade, entry_activated
from strategy import generate_signal


def make_candles(count=100, interval=15):
    candles = []
    start = pd.Timestamp("2026-11-17 09:15:00", tz="Asia/Kolkata")
    for i in range(count):
        price = 25000 + i * 5
        timestamp = (start + pd.Timedelta(minutes=i * interval)).isoformat()
        candles.append([timestamp, price - 2, price + 5, price - 5, price, 1000 + i * 10, 0])
    return candles


class TestScanner(unittest.TestCase):
    def test_indicator_calculation(self):
        result = calculate_indicators(make_candles())
        self.assertIsNotNone(result)
        for column in ["ema20", "ema50", "dtp_baseline", "dtp_upper", "dtp_lower", "dtp_state", "dtp_buy", "dtp_sell", "atr14"]:
            self.assertIn(column, result.columns)
        self.assertTrue(pd.notna(result.iloc[-1]["ema50"]))
        self.assertTrue(pd.notna(result.iloc[-1]["dtp_upper"]))
        for obsolete in ["rsi", "adx", "vwap", "macd", "supertrend"]:
            self.assertNotIn(obsolete, result.columns)

    def test_option_selection(self):
        chain = [{
            "call_options": {"instrument_key": "TEST_CALL", "market_data": {"ltp": 100, "bid_price": 99, "ask_price": 100, "volume": 1000, "oi": 5000}},
            "put_options": {}, "underlying_spot_price": 25000, "strike_price": 25000, "expiry": "2026-11-26"
        }]
        result = select_option(chain, "CALL")
        self.assertIsNotNone(result)
        self.assertEqual(result["instrument_key"], "TEST_CALL")

    def test_option_rejects_wide_spread(self):
        chain = [{
            "call_options": {"instrument_key": "TEST_CALL", "market_data": {"ltp": 100, "bid_price": 90, "ask_price": 110, "volume": 1000, "oi": 5000}},
            "underlying_spot_price": 25000, "strike_price": 25000
        }]
        self.assertIsNone(select_option(chain, "CALL"))

    def test_risk_calculation(self):
        trade = calculate_trade({"ask": 100, "instrument_key": "TEST_CALL"})
        self.assertEqual(trade["entry"], 100)
        self.assertEqual(trade["stop_loss"], 80)
        self.assertEqual(trade["target_1"], 120)
        self.assertEqual(trade["target_2"], 135)

    def test_entry_activation(self):
        option = {"entry": 100}
        self.assertTrue(entry_activated(option, 101))
        self.assertTrue(entry_activated(option, 100))
        self.assertFalse(entry_activated(option, 99))

    def test_strategy_handles_valid_candles(self):
        result = generate_signal("NIFTY", make_candles())
        self.assertTrue(result is None or result["side"] in ("CALL", "PUT"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
