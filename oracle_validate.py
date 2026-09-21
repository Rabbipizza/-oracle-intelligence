#!/usr/bin/env python3
"""Fail-closed validation for the deployable ORACLE cockpit."""
import json, sys
from pathlib import Path

errors=[]; warnings=[]

def load(path):
    p=Path(path)
    if not p.exists():
        errors.append(f"missing:{path}"); return {}
    try: return json.loads(p.read_text())
    except Exception as e:
        errors.append(f"invalid_json:{path}:{e}"); return {}

disc=load("data/discovery-candidates.json")
market=load("data/market.json")
cockpit=load("data/cockpit.json")
gate=load("data/source-gate-status.json")

if disc.get("quality")!="OK":
    errors.append("discovery_quality_not_OK")
if len(disc.get("candidates",[]))<10:
    warnings.append("few_discovery_candidates")

prices=market.get("prices",{})
for t in ("QQQ","AAON","GEV"):
    if not (prices.get(t) or {}).get("rows"):
        errors.append(f"critical_market_series_missing:{t}")
if len(market.get("fx_usd_chf",[]))<2:
    errors.append("critical_fx_series_missing:USDCHF")

trends=cockpit.get("trends",[])
if len(trends)<5:
    errors.append("cockpit_has_fewer_than_5_trends")
for tr in trends[:5]:
    companies=tr.get("companies",[])
    if len(companies)!=20:
        errors.append(f"trend_not_top20:{tr.get('key')}:{len(companies)}")
    missing=[x.get("ticker") for x in companies if x.get("price") is None or not x.get("spark")]
    if missing:
        errors.append(f"trend_market_history_missing:{tr.get('key')}:{','.join(str(x) for x in missing)}")

pf=cockpit.get("portfolio",{})
if len(pf.get("positions",[]))<2:
    errors.append("portfolio_positions_missing")
for p in pf.get("positions",[]):
    if p.get("current_value_chf") is None:
        errors.append(f"portfolio_unpriced:{p.get('ticker')}")
comp=pf.get("official_comparison",{})
for k in ("oracle_return_pct","qqq_return_pct","alpha_pct_points"):
    if comp.get(k) is None:
        errors.append(f"benchmark_metric_missing:{k}")

if gate.get("discovery_quality")!="OK":
    errors.append("source_gate_discovery_not_OK")
if len(market.get("errors",[]))>20:
    warnings.append(f"many_market_series_errors:{len(market.get('errors',[]))}")

result={"status":"PASS" if not errors else "FAIL","errors":errors,"warnings":warnings}
print(json.dumps(result))
if errors:
    sys.exit(1)
