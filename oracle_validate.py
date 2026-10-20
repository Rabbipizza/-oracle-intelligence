#!/usr/bin/env python3
"""Fail-closed admission of the exact deployable cockpit; negative alpha is allowed."""
import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from oracle_data_quality import (CASH_TICKERS, MAX_SNAPSHOT_AGE_DAYS, cost_weights,
    explicit_evidence, finite, fx_errors, holdings, iso_date, positive, series_quality)
from oracle_cockpit import build_portfolio
from oracle_funnel_audit import build_audit


def validate(root=Path("."), reference_date=None):
    errors=[]; warnings=[]
    def load(name):
        try:
            result=json.loads((root/name).read_text())
            if not isinstance(result,dict): raise ValueError("expected object")
            return result
        except (OSError,ValueError) as exc:
            errors.append(f"invalid_or_missing:{name}:{exc}")
            return {}
    disc=load("data/discovery-candidates.json")
    market=load("data/market.json")
    cockpit=load("data/cockpit.json")
    decision=load("decision-state.json")
    actual=load("portfolio.json")
    simulated=load("portfolio-simulated.json")
    evidence=load("economic-evidence.json")
    gate=load("data/source-gate-status.json")
    protocol=load("scientific-protocol.json")
    signal_perf=load("data/signal-performance.json")
    dossiers=load("data/evidence-dossiers.json")
    review=load("data/company-revalidation.json")
    funnel=load("data/funnel-audit.json")
    as_of=cockpit.get("data_as_of")
    reference=reference_date or datetime.now(timezone.utc).date()
    day=iso_date(as_of)
    if not day:
        errors.append("missing_or_invalid_valuation_date")
    elif not 0 <= (reference-day).days <= MAX_SNAPSHOT_AGE_DAYS:
        errors.append("market_snapshot_stale_or_future:"+str(as_of))
    if not day or cockpit.get("decision_as_of")!=as_of or decision.get("as_of")!=as_of:
        errors.append("decision_market_date_mismatch")
    if cockpit.get("decision_freshness",{}).get("status")!="CURRENT":
        errors.append("decision_state_stale_or_unknown")
    if decision.get("decision_status")!="READY" or cockpit.get("decision_status")!="READY":
        errors.append("decision_blocked_or_unknown")
    if not protocol.get("objective") or protocol.get("overfitting_controls",{}).get("deflated_sharpe_ratio") is not True:
        errors.append("scientific_protocol_missing")
    if disc.get("quality")!="OK" or gate.get("discovery_quality")!="OK":
        errors.append("discovery_quality_not_OK")
    for cohort in ("ALL_DETECTED","TOP20","ORANGE","GREEN"):
        if cohort not in signal_perf.get("cohorts",{}): errors.append("signal_cohort_missing:"+cohort)

    critical={"QQQ"}|holdings(actual)|holdings(simulated)
    targets=cockpit.get("target_allocation_pct")
    if not isinstance(targets,dict):
        errors.append("target_allocation_missing"); targets={}
    if targets!=decision.get("target_allocation_pct"):
        errors.append("target_decision_mismatch")
    if not targets or any(not finite(w) or not 0<=w<=100 for w in targets.values()) or abs(sum(w for w in targets.values() if finite(w))-100)>0.05:
        errors.append("invalid_target_weights")
    critical.update(t for t,w in targets.items() if positive(w))
    for t,s in decision.get("signals",{}).items():
        if s.get("signal")=="GREEN" or s.get("portfolio_action") in {"BUY","INCREASE"}: critical.add(t)
    for t,s in decision.get("scores",{}).items():
        if positive((s.get("indicative_entry_sizing") or {}).get("max_pct")): critical.add(t)

    companies=[c for tr in cockpit.get("trends",[]) for c in tr.get("companies",[])]
    companies+=cockpit.get("action_now",[])
    for c in companies:
        t=c.get("ticker")
        invests=c.get("signal")=="GREEN" or positive(c.get("target_weight_pct")) or positive((c.get("indicative_entry_sizing") or {}).get("max_pct")) or c.get("portfolio_action") in {"BUY","INCREASE"}
        if invests: critical.add(t)
        quality=series_quality(market,t,as_of)
        if quality["status"]!="AVAILABLE":
            if c.get("data_status")!="DATA_UNAVAILABLE": errors.append("missing_data_status:"+str(t))
            if invests: errors.append("unpriced_investable_recommendation:"+str(t))
            if c.get("price") is not None or c.get("spark"): errors.append("unavailable_candidate_has_prices:"+str(t))
            warnings.append("research_market_history_missing:"+str(t))
    critical-=CASH_TICKERS
    for t in sorted(critical,key=str):
        quality=series_quality(market,t,as_of)
        if quality["status"]!="AVAILABLE": errors.append("critical_market_series_invalid:"+str(t)+":"+",".join(quality["reasons"]))
    errors.extend("critical_fx_invalid:"+r for r in fx_errors(market,as_of))
    if cockpit.get("market_errors")!=market.get("errors",[]): errors.append("market_error_audit_not_preserved")

    registry=evidence.get("companies",{})
    for t,s in decision.get("signals",{}).items():
        if s.get("signal")=="GREEN" and not explicit_evidence(registry.get(t),as_of): errors.append("green_without_primary_proof:"+t)
    for t,w in targets.items():
        if positive(w) and t not in CASH_TICKERS|{"QQQ"} and not explicit_evidence(registry.get(t),as_of): errors.append("target_without_primary_proof:"+t)
    for c in companies:
        if c.get("signal")=="GREEN" and not explicit_evidence(registry.get(c.get("ticker")),as_of): errors.append("cockpit_green_without_primary_proof:"+str(c.get("ticker")))

    for name,ledger,kind in (("portfolio",actual,"ACTUAL"),("simulated_portfolio",simulated,"SIMULATED")):
        if ledger.get("kind")!=kind: errors.append("ledger_kind_mismatch:"+name)
        if not positive(ledger.get("initial_capital_chf")) or not finite(ledger.get("cash_chf")) or ledger.get("cash_chf",-1)<0:
            errors.append("invalid_ledger_capital:"+name); continue
        positions=[p for p in ledger.get("positions",[]) if p.get("status")=="OPEN"]
        if any(not positive(p.get("allocated_chf")) or not iso_date(p.get("trade_date")) or p.get("ticker") in CASH_TICKERS for p in positions):
            errors.append("invalid_ledger_position:"+name); continue
        if abs(sum(p["allocated_chf"] for p in positions)+ledger["cash_chf"]-ledger["initial_capital_chf"])>0.01: errors.append("ledger_does_not_reconcile:"+name)
        for t in holdings(ledger)|{"QQQ"}:
            if (market.get("prices",{}).get(t) or {}).get("currency")!="USD": errors.append("unsupported_ledger_currency:"+str(t))
        expected=build_portfolio(market,ledger)
        value=cockpit.get(name,{})
        if value!=expected: errors.append("ledger_valuation_mismatch:"+name)
        if not finite(expected.get("total_value_chf")): errors.append("portfolio_unpriced:"+name)
        comp=expected["official_comparison"]
        for metric in ("oracle_return_pct","qqq_return_pct","alpha_pct_points","alpha_chf"):
            if not finite(comp.get(metric)): errors.append("benchmark_metric_missing:"+name+":"+metric)
    if cockpit.get("actual_portfolio")!=cockpit.get("portfolio"): errors.append("actual_portfolio_mismatch")
    if actual and (cockpit.get("actual_holdings_pct")!=cost_weights(actual) or decision.get("actual_holdings_pct")!=cost_weights(actual)):
        errors.append("actual_ledger_allocation_mismatch")
    expected_funnel=build_audit(dossiers,review,evidence,as_of)
    if funnel!=expected_funnel or cockpit.get("discovery",{}).get("funnel_audit")!=expected_funnel:
        errors.append("funnel_audit_mismatch")
    if expected_funnel["unproven_inheritance_violations"]: errors.append("unproven_company_capture_inherited")
    trends=cockpit.get("trends",[])
    if len(trends)<5: errors.append("cockpit_has_fewer_than_5_trends")
    for tr in trends:
        if len(tr.get("companies",[]))!=20: errors.append("trend_not_top20:"+str(tr.get("key")))
    alpha=cockpit.get("portfolio",{}).get("official_comparison",{}).get("alpha_pct_points")
    if finite(alpha) and alpha<0: warnings.append("prospective_alpha_negative:"+str(alpha))
    return {"status":"FAIL" if errors else "PASS","errors":sorted(set(errors)),"warnings":sorted(set(warnings)),
            "data_as_of":as_of,"reference_date":reference.isoformat(),
            "validation_mode":"HISTORICAL_REPLAY" if reference_date else "PRODUCTION", "prospective_alpha_pct_points":alpha}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-date",type=date.fromisoformat,help="Offline historical replay only; never accepted by the publisher.")
    args=parser.parse_args()
    result=validate(reference_date=args.replay_date)
    Path("data/validation.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
    return 1 if result["errors"] else 0


if __name__=="__main__": sys.exit(main())
