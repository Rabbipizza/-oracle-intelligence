#!/usr/bin/env python3
"""Regression tests for missing research-only market quotes."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALIDATOR = ROOT / "oracle_validate.py"


def scenario(missing_ticker, target=False):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "data").mkdir()
        files = {
            "data/discovery-candidates.json": {"quality": "OK", "candidates": [{}] * 10},
            "data/market.json": {
                "prices": {t: {"rows": [{"date": "2026-10-13", "close": 100}]} for t in ("QQQ", "AAON", "GEV")},
                "fx_usd_chf": [{"date": "2026-10-12", "chf_per_usd": .8}, {"date": "2026-10-13", "chf_per_usd": .8}],
            },
            "data/source-gate-status.json": {"discovery_quality": "OK"},
            "data/signal-performance.json": {"cohorts": {t: {} for t in ("ALL_DETECTED", "TOP20", "ORANGE", "GREEN")}},
            "scientific-protocol.json": {"objective": "research", "overfitting_controls": {"deflated_sharpe_ratio": True}},
        }
        companies = [{"ticker": "TEST" + str(i), "price": 100, "spark": [100]} for i in range(20)]
        companies[0] = {"ticker": missing_ticker, "price": None, "spark": []}
        files["data/cockpit.json"] = {
            "trends": [{"key": "minerals", "companies": companies}] + [
                {"key": "trend" + str(i), "companies": [{"ticker": "TEST" + str(j), "price": 100, "spark": [100]} for j in range(20)]}
                for i in range(4)
            ],
            "decision_as_of": "2026-10-13", "data_as_of": "2026-10-13",
            "decision_freshness": {"status": "FRESH"},
            "target_allocation_pct": {missing_ticker: 5} if target else {},
            "portfolio": {
                "positions": [{"ticker": "AAON", "current_value_chf": 40}, {"ticker": "CASH", "current_value_chf": 960}],
                "official_comparison": {"oracle_return_pct": 0, "qqq_return_pct": 0, "alpha_pct_points": 0},
            },
        }
        for name, payload in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload))
        run = subprocess.run([sys.executable, str(VALIDATOR)], cwd=root, text=True, capture_output=True)
        result = json.loads(run.stdout)
        return run.returncode, result


def test_research_only_missing_quote_is_warning():
    code, result = scenario("TMRC")
    assert code == 0, result
    assert result["status"] == "PASS"
    assert any("research_market_history_missing:minerals:TMRC" in w for w in result["warnings"])


def test_target_missing_quote_is_fatal():
    code, result = scenario("TMRC", target=True)
    assert code != 0, result
    assert any("investable_market_history_missing:minerals:TMRC" in e for e in result["errors"])


if __name__ == "__main__":
    test_research_only_missing_quote_is_warning()
    test_target_missing_quote_is_fatal()
    print("ORACLE missing-quote regression tests: PASS")
