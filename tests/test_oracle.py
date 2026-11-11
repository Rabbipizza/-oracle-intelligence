import datetime as dt
import unittest
from oracle import aggregate, compute_rank, terms, DOMAINS

class TestOracle(unittest.TestCase):
    def test_stopword_unigram(self):
        result = terms("The quantum chips for data centers")
        self.assertIn("quantum chips", result)
        self.assertNotIn("the", result)
        self.assertNotIn("for data", result)

    def test_deduplicate_by_source_and_link(self):
        doc = {"title": "Quantum chips accelerate", "url": "https://example.org/a",
               "source": "s1", "family": "f1", "domain": "science"}
        data = aggregate([doc, doc])["science"]
        self.assertEqual(data["documents"], 1)
        self.assertEqual(data["terms"]["quantum"]["count"], 1)

    def test_no_claim_without_history(self):
        current = {"documents": 10, "terms": {"photonics": {"count": 5, "families": ["one", "two"], "links": []}}}
        top = compute_rank(current, [])
        self.assertEqual(top[0]["quality"], "EXPLORATORY")
        self.assertIsNone(top[0]["growth_vs_28d"])

    def test_measurable_only_if_two_families_and_history(self):
        current = {"documents": 10, "terms": {"photonics": {"count": 5, "families": ["one", "two"], "links": []}}}
        prior = [{"documents": 10, "terms": {"photonics": {"count": 1}}}] * 14
        top = compute_rank(current, prior)
        self.assertEqual(top[0]["quality"], "MEASURABLE")
        self.assertGreater(top[0]["growth_vs_28d"], 0)

    def test_missing_coverage_is_not_zero_ranked_as_trend(self):
        current = {"documents": 0, "terms": {}}
        self.assertEqual(compute_rank(current, []), [])

    def test_domain_coverage(self):
        self.assertEqual(len(DOMAINS), 14)

if __name__ == "__main__":
    unittest.main()
