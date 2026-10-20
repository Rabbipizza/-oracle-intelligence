#!/usr/bin/env python3
"""Reconcile discovery/capture outcomes without inheriting company proof from a trend."""
import json
from collections import Counter
from pathlib import Path
from oracle_data_quality import explicit_evidence, market_date


def build_audit(dossiers, review, evidence, as_of):
    companies=dossiers.get("companies",{})
    outcomes=[]
    for row in review.get("results",[]):
        rule=row.get("promotion_rule",{})
        blockers=[]
        if not row.get("trend_gate_pass"): blockers.append("trend_gate_failed")
        if row.get("company_capture_score",0)<rule.get("min_capture_score",75): blockers.append("capture_score_below_minimum")
        if row.get("recent_primary_filing_hits",0)<rule.get("min_filings",2): blockers.append("insufficient_primary_filings")
        if len(row.get("distinct_economic_terms",[]))<rule.get("min_economic_terms",2): blockers.append("insufficient_economic_terms")
        outcomes.append({"ticker":row.get("ticker"),"status":row.get("status"),"blockers":blockers})
    registry=evidence.get("companies",{})
    proven=sorted(t for t,e in registry.items() if explicit_evidence(e,as_of))
    promoted=sorted(review.get("promoted",[]))
    violations=sorted(t for t,d in companies.items() if (d.get("explicit_proven") or d.get("maturity")=="PROVEN") and t not in proven)
    violations+=sorted(r["ticker"] for r in outcomes if r["status"]=="PROVEN" and (r["blockers"] or r["ticker"] not in proven))
    eligible_promotions={r["ticker"] for r in outcomes if r["status"]=="PROVEN" and not r["blockers"]}
    violations+=sorted(set(promoted)-(set(proven)&eligible_promotions))
    return {"as_of":as_of,"company_count":len(companies),
        "maturity_counts":dict(Counter(d.get("maturity","UNKNOWN") for d in companies.values())),
        "capture_review_count":len(outcomes),"review_status_counts":dict(Counter(r["status"] for r in outcomes)),
        "rejection_counts":dict(Counter(reason for r in outcomes for reason in r["blockers"])),
        "explicit_proven":proven,"newly_promoted":promoted,
        "preexisting_explicit_proven":sorted(set(proven)-set(promoted)),
        "unproven_inheritance_violations":sorted(set(violations)),"reviews":outcomes,
        "rule":"Rejection reasons overlap. Trend proof alone never establishes company capture; existing explicit primary proofs are distinct from new promotions."}


def main():
    def load(name): return json.loads(Path(name).read_text())
    out=build_audit(load("data/evidence-dossiers.json"),load("data/company-revalidation.json"),load("economic-evidence.json"),market_date(load("data/market.json")))
    Path("data/funnel-audit.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="reviews"}))


if __name__=="__main__": main()
