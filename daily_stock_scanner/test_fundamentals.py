import unittest
from unittest.mock import patch

import fundamentals


class FundamentalsTests(unittest.TestCase):
    def test_growth_uses_latest_and_three_year_oldest(self):
        growth = fundamentals._growth([140, 125, 110, 100])
        self.assertAlmostEqual(growth, (1.4 ** (1 / 3) - 1) * 100, places=5)

    def test_fundamental_score_returns_quality_metrics(self):
        def fake_get(url, headers, params=None):
            if url.endswith("/key-ratios"):
                return [
                    {"name": "ROCE", "company_value": "20%", "sector_value": "15%"},
                    {"name": "ROE", "company_value": "18%", "sector_value": "15%"},
                    {"name": "P/E", "company_value": "20", "sector_value": "25"},
                    {"name": "EV/EBITDA", "company_value": "12", "sector_value": "14"},
                ]
            if url.endswith("/income-statement"):
                return {"income_statement": [
                    {"category": "revenue", "history": [{"value": 1400}, {"value": 1200}, {"value": 1100}, {"value": 1000}]},
                    {"category": "net_profit", "history": [{"value": 200}, {"value": 170}, {"value": 150}, {"value": 120}]},
                ]}
            if url.endswith("/cash-flow"):
                return {"cash_flow": [
                    {"category": "operating", "history": [{"value": 300}, {"value": 250}, {"value": 200}, {"value": 100}]}
                ]}
            if url.endswith("/balance-sheet"):
                return {"history": [{"total_asset": 1000, "total_liability": 400}]}
            raise AssertionError(url)

        with patch.object(fundamentals, "_get", side_effect=fake_get):
            result = fundamentals.score_fundamentals("INE000000000", {"Authorization": "Bearer test"})

        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["fundamental_score"], 70)
        self.assertIn("ROCE 20.0%", result["fundamental_reasons"])
        self.assertAlmostEqual(result["fundamental_metrics"]["liabilities_assets"], 0.4)

    def test_missing_coverage_is_not_scored_as_good(self):
        with patch.object(fundamentals, "_get", side_effect=[
            [{"name": "P/E", "company_value": "15", "sector_value": "20"}],
            {}, {}, {},
        ]):
            result = fundamentals.score_fundamentals("INE000000000", {"Authorization": "Bearer test"})
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
