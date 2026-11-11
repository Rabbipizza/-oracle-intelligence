import unittest
from datetime import date, timedelta
from oracle import SOURCES, terms
from oracle_billboard import source_snapshots, source_top5

class BillboardPerSourceTests(unittest.TestCase):
    def setUp(self):
        self.source = next(s for s in SOURCES if s[0] == "arxiv_ai")
        self.key = self.source[0]
        self.today = date(2026, 11, 11)

    def days(self, hits):
        previous = []
        for offset in range(20, 0, -1):
            d = self.today - timedelta(days=offset)
            x = hits(offset)
            previous.append({"date": d.isoformat(), "sources": {
                self.key: {"documents": 100, "terms": {
                    "quantum chips": {"count": x, "links": ["https://example.org/x"]}
                }}
            }})
        return previous

    def current(self, count):
        return {"sources": {self.key: {
            "documents": 100, "terms": {
                "quantum chips": {"count": count, "links": ["https://example.org/y"]}
            }
        }}}

    def test_two_sources_not_mixed_and_url_dedup(self):
        docs = [
            {"source": self.key, "domain": "science", "title": "Quantum chips",
             "url": "https://example.org/a"},
            {"source": self.key, "domain": "science", "title": "Quantum chips",
             "url": "https://example.org/a"},
            {"source": "hackernews", "domain": "social", "title": "Quantum chips",
             "url": "https://example.org/a"},
        ]
        grouped = source_snapshots(docs, SOURCES, terms)
        self.assertEqual(grouped[self.key]["documents"], 1)
        self.assertEqual(grouped["hackernews"]["documents"], 1)
        self.assertEqual(grouped[self.key]["terms"]["quantum chips"]["count"], 1)

    def test_insufficient_history_is_never_ranked(self):
        old = self.days(lambda offset: 1)[:2]
        result = source_top5(self.source, self.today.isoformat(), self.current(10), old)
        self.assertEqual(result["top5"], [])
        self.assertTrue(result["preview_unranked"])
        self.assertEqual(result["state"], "INSUFFICIENT_HISTORY")

    def test_missing_day_not_assumed_zero(self):
        old = self.days(lambda offset: 1)
        old.pop(6)
        result = source_top5(self.source, self.today.isoformat(), self.current(10), old)
        self.assertEqual(result["observed_days"], 20)
        self.assertEqual(result["top5"], [])

    def test_positive_acceleration_is_ranked(self):
        previous = self.days(lambda offset: 1 if offset >= 14 else (2 if offset >= 7 else 8))
        result = source_top5(self.source, self.today.isoformat(), self.current(8), previous)
        self.assertEqual(result["state"], "RANKED_EXPLORATORY")
        self.assertEqual(result["top5"][0]["term"], "quantum chips")
        self.assertGreater(result["top5"][0]["acceleration_per_10k_week2"], 0)

    def test_steady_growth_not_accelerating(self):
        previous = self.days(lambda offset: 1 if offset >= 14 else (6 if offset >= 7 else 11))
        result = source_top5(self.source, self.today.isoformat(), self.current(11), previous)
        self.assertEqual(result["top5"], [])
        self.assertEqual(result["state"], "NO_POSITIVE_ACCELERATION")

    def test_no_data_fail_closed(self):
        result = source_top5(self.source, self.today.isoformat(),
            {"sources": {self.key: {"documents": 0, "terms": {}}}},
            self.days(lambda offset: 8))
        self.assertEqual(result["state"], "NO_DATA")
        self.assertEqual(result["top5"], [])

    def test_single_day_spike_not_ranked(self):
        previous = self.days(lambda offset: 1 if offset >= 7 else 0)
        result = source_top5(self.source, self.today.isoformat(),
                             self.current(20), previous)
        self.assertEqual(result["top5"], [])

    def test_not_enough_current_documents(self):
        previous = self.days(lambda offset: 8)
        cur = {"sources": {self.key: {
            "documents": 1, "terms": {"quantum chips": {"count": 1, "links": []}}
        }}}
        # Last 7d still sufficient from previous 6 days; confirms volume is
        # evaluated across the window, not single-day document count.
        result = source_top5(self.source, self.today.isoformat(), cur, previous)
        self.assertNotEqual(result["state"], "NO_DATA")

if __name__ == "__main__":
    unittest.main()
