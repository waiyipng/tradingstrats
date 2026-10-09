import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from bullcallspread.consensus import fetch_consensus, fetch_nasdaq_eps_forecast


class FetchConsensusTests(unittest.TestCase):
    @patch("bullcallspread.consensus.fetch_nasdaq_eps_forecast", return_value=None)
    @patch("bullcallspread.consensus.yf.Ticker")
    def test_shapes_yfinance_fields_into_snapshot(self, mock_ticker_cls, _mock_nasdaq):
        mock_ticker = MagicMock()
        mock_ticker.get_info.return_value = {"currentPrice": 190.31, "sharesOutstanding": 1_570_566_292}
        mock_ticker.calendar = {
            "Earnings Date": [date(2026, 10, 14)],
            "Earnings Average": 3.03, "Earnings Low": 2.86, "Earnings High": 3.20,
            "Revenue Average": 20_468_094_700, "Revenue Low": 19_846_711_430, "Revenue High": 21_485_000_000,
        }
        mock_ticker.analyst_price_targets = {"mean": 233.43, "median": 243.0, "low": 184.0, "high": 262.0}
        mock_ticker.earnings_dates = pd.DataFrame(
            {"EPS Estimate": [2.93, float("nan")], "Reported EPS": [3.46, float("nan")], "Surprise(%)": [17.94, float("nan")]},
            index=pd.to_datetime(["2026-07-15", "2026-10-14"]),
        )
        mock_ticker_cls.return_value = mock_ticker

        snapshot = fetch_consensus("MS")

        self.assertEqual(snapshot.symbol, "MS")
        self.assertEqual(snapshot.next_earnings_date, "2026-10-14")
        self.assertEqual(snapshot.consensus_eps, 3.03)
        self.assertEqual(snapshot.shares_outstanding, 1_570_566_292)
        self.assertEqual(len(snapshot.history), 1)
        self.assertEqual(snapshot.history[0].eps_actual, 3.46)

    @patch("bullcallspread.consensus.fetch_nasdaq_eps_forecast", return_value=None)
    @patch("bullcallspread.consensus.yf.Ticker")
    def test_handles_no_upcoming_earnings_date(self, mock_ticker_cls, _mock_nasdaq):
        mock_ticker = MagicMock()
        mock_ticker.get_info.return_value = {}
        mock_ticker.calendar = {}
        mock_ticker.analyst_price_targets = {}
        mock_ticker.earnings_dates = None
        mock_ticker_cls.return_value = mock_ticker

        snapshot = fetch_consensus("MS")
        self.assertIsNone(snapshot.next_earnings_date)
        self.assertEqual(snapshot.history, [])
        self.assertIsNone(snapshot.nasdaq_forecast)


class FetchNasdaqEpsForecastTests(unittest.TestCase):
    @patch("bullcallspread.consensus.requests.get")
    def test_parses_nearest_quarter_row(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "quarterlyForecast": {
                        "rows": [
                            {"fiscalEnd": "Sep 2026", "consensusEPSForecast": 3.01, "highEPSForecast": 3.2, "lowEPSForecast": 2.88, "noOfEstimates": 5, "up": 0, "down": 1},
                            {"fiscalEnd": "Dec 2026", "consensusEPSForecast": 2.85, "highEPSForecast": 3.05, "lowEPSForecast": 2.71, "noOfEstimates": 5, "up": 0, "down": 1},
                        ]
                    }
                }
            },
        )
        forecast = fetch_nasdaq_eps_forecast("MS")
        self.assertEqual(forecast.fiscal_quarter_end, "Sep 2026")
        self.assertEqual(forecast.consensus_eps, 3.01)
        self.assertEqual(forecast.num_estimates, 5)

    @patch("bullcallspread.consensus.requests.get", side_effect=RuntimeError("network down"))
    def test_returns_none_on_any_failure(self, _mock_get):
        self.assertIsNone(fetch_nasdaq_eps_forecast("MS"))

    @patch("bullcallspread.consensus.requests.get")
    def test_returns_none_on_empty_rows(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"data": {"quarterlyForecast": {"rows": []}}})
        self.assertIsNone(fetch_nasdaq_eps_forecast("MS"))


if __name__ == "__main__":
    unittest.main()
