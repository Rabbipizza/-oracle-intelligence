import datetime as dt
import unittest
from oracle_market_monitor import indicators, classify_age, snapshot

class MarketMonitorTests(unittest.TestCase):
    def test_missing_data_has_no_indicators(self):
        self.assertIsNone(indicators([])["sma20"])
    def test_baseline_computes_without_trading_signal(self):
        p = [100 + x for x in range(80)]
        i = indicators(p)
        self.assertGreater(i["return_20d_pct"], 0)
        self.assertIsNotNone(i["sma50"])
    def test_no_future_or_stale_quotes(self):
        now = dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc)
        self.assertEqual(classify_age("2026-11-11", now), "CURRENT_DAILY")
        self.assertEqual(classify_age("2026-10-31", now), "STALE")
        self.assertEqual(classify_age("2026-11-15", now), "INVALID")
    def test_provider_failure_fails_closed(self):
        import unittest.mock
        with unittest.mock.patch("oracle_market_monitor.read_chart", side_effect=OSError("offline")):
            data = snapshot(dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc))
        self.assertTrue(all(r["state"] == "UNAVAILABLE" and r["signal"] == "GREY_NOT_VALIDATED" for r in data["securities"]))
        self.assertIsNone(data["portfolio"]["paper"])

if __name__=="__main__":
    unittest.main()
