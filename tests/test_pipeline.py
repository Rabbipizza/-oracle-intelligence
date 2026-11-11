import unittest
from oracle_pipeline import (
    create_research_queue, evidence_valid, stage_ready,
    gate_company_candidate, gate_trading_signal, PORTFOLIO_BOOKS
)

VALID = {
    "url": "https://www.sec.gov/Archives/example", "publisher": "SEC",
    "published_at": "2026-11-11", "reviewed": True,
}

class PipelineTests(unittest.TestCase):
    def test_empty_top5_means_empty_research_queue(self):
        self.assertEqual(create_research_queue({
            "arxiv_ai": {"top5": []}
        }), [])

    def test_candidate_is_not_investment(self):
        x = create_research_queue({"arxiv_ai": {"top5": [{
            "term": "quantum chips",
            "acceleration_per_10k_week2": 100,
            "evidence_urls": ["https://example.org/1"]
        }]}})[0]
        self.assertEqual(x["trading_signal"], "GREY_NO_VALIDATED_DATA")
        self.assertEqual(x["companies_top10"], [])
        self.assertFalse(x["real_order_allowed"])

    def test_unreviewed_evidence_rejected(self):
        self.assertFalse(evidence_valid(dict(VALID, reviewed=False)))
        self.assertFalse(stage_ready("market", [dict(VALID, reviewed=False)]))
        self.assertTrue(stage_ready("market", [VALID]))

    def test_no_market_data_fails_closed(self):
        company = {"ticker": "ACME", "exchange": "NASDAQ", "verified_revenue_exposure": 0.4,
                   "valuation_asof": "2026-11-11", "fundamentals_asof": "2026-11-11",
                   "liquidity_asof": "2026-11-11", "evidence": [VALID]}
        self.assertTrue(gate_company_candidate(company))
        self.assertEqual(gate_trading_signal(company, {}), "GREY_NO_VALIDATED_DATA")

    def test_risk_breach_overrides_entry(self):
        company = {"ticker": "ACME", "exchange": "NASDAQ", "verified_revenue_exposure": 0.4,
                   "valuation_asof": "2026-11-11", "fundamentals_asof": "2026-11-11",
                   "liquidity_asof": "2026-11-11", "evidence": [VALID]}
        rules = {"point_in_time_backtest_passed": True, "price_verified": True,
                 "market_evidence_reviewed": True, "risk_limits_configured": True,
                 "hard_risk_breach": True, "entry_conditions_met": True}
        self.assertEqual(gate_trading_signal(company, rules), "RED")

    def test_separate_portfolio_books(self):
        self.assertEqual(PORTFOLIO_BOOKS, ("ACTUAL", "TARGET", "PAPER"))

if __name__ == "__main__":
    unittest.main()
