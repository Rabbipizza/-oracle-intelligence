"""Evidence-gated research queue for ORACLE stages 3–7.

The source Top5 merely nominates candidates. It MUST NOT create market
sizes, supplier links, security names or trading signals without evidence.
This module defines explicit stage gates and produces auditable pending work.
"""
from __future__ import annotations
from urllib.parse import urlparse

STAGES = (
    ("market", "3. Marché / demande adressable"),
    ("limits", "4. Capacités et goulots"),
    ("supply_chain", "5. Fournisseurs et matières premières"),
    ("companies", "6. Top 10 sociétés"),
    ("trading", "7. Analyse de trading"),
)
PORTFOLIO_BOOKS = ("ACTUAL", "TARGET", "PAPER")

def evidence_valid(proof):
    """Only reviewed, dated and attributable primary-source evidence passes."""
    if not isinstance(proof, dict):
        return False
    url = proof.get("url", "")
    return (
        isinstance(url, str)
        and urlparse(url).scheme == "https"
        and bool(urlparse(url).netloc)
        and bool(proof.get("publisher"))
        and bool(proof.get("published_at"))
        and proof.get("reviewed") is True
    )

def stage_ready(stage, evidence):
    if stage not in dict(STAGES):
        raise ValueError("Unknown stage")
    if not isinstance(evidence, list) or not evidence:
        return False
    return all(evidence_valid(e) for e in evidence)

def create_research_queue(source_billboards):
    queue = []
    for source_id, source in sorted(source_billboards.items()):
        for rank, trend in enumerate(source.get("top5", [])[:5], start=1):
            queue.append({
                "candidate_id": source_id + ":" + trend["term"],
                "trend_phrase": trend["term"],
                "source_id": source_id,
                "source_rank": rank,
                "acceleration_per_10k_week2": trend["acceleration_per_10k_week2"],
                "observational_evidence_urls": trend["evidence_urls"],
                "stage": "MARKET_RESEARCH_REQUIRED",
                "stages": {
                    key: {"state": "NOT_EVALUATED", "evidence": []}
                    for key, _ in STAGES
                },
                "companies_top10": [],
                "trading_signal": "GREY_NO_VALIDATED_DATA",
                "real_order_allowed": False,
            })
    return queue

def gate_company_candidate(company):
    """No unaudited company enters an investable Top10."""
    if not isinstance(company, dict):
        return False
    required = ("ticker", "exchange", "verified_revenue_exposure",
                "valuation_asof", "fundamentals_asof", "liquidity_asof")
    return all(company.get(name) is not None and company.get(name) != "" for name in required) and (
        stage_ready("companies", company.get("evidence", []))
    )

def gate_trading_signal(company, rule):
    """A green/orange/red can *only* be emitted after all evidence gates."""
    if not gate_company_candidate(company) or not isinstance(rule, dict):
        return "GREY_NO_VALIDATED_DATA"
    if not (rule.get("point_in_time_backtest_passed") is True
            and rule.get("price_verified") is True
            and rule.get("market_evidence_reviewed") is True
            and rule.get("risk_limits_configured") is True):
        return "GREY_NO_VALIDATED_DATA"
    if rule.get("hard_risk_breach") is True:
        return "RED"
    if rule.get("entry_conditions_met") is True:
        return "GREEN_REVIEW_ONLY"
    return "ORANGE_MONITOR"
