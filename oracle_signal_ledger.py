#!/usr/bin/env python3
"""Prospective ORACLE signal ledger.
Records first observation of every company/signal state BEFORE future returns are known.
Existing observations are immutable; later runs only add new state transitions.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

COCKPIT=Path("data/cockpit.json")
LEDGER=Path("data/signal-ledger.json")

def load(path, default):
    try: return json.loads(path.read_text())
    except Exception: return default

def main():
    cockpit=load(COCKPIT,{})
    ledger=load(LEDGER,{"version":1,"events":[]})
    events=ledger.setdefault("events",[])
    seen={(e.get("ticker"),e.get("signal")) for e in events}
    observed_at=cockpit.get("generated_at") or datetime.now(timezone.utc).isoformat()
    market_date=(cockpit.get("portfolio") or {}).get("as_of")
    added=0
    for trend in cockpit.get("trends",[]):
        for c in trend.get("companies",[]):
            key=(c.get("ticker"),c.get("signal"))
            if not c.get("ticker") or not c.get("signal") or key in seen:
                continue
            events.append({
                "event_id":f"{c['ticker']}:{c['signal']}:{market_date or observed_at[:10]}",
                "observed_at":observed_at,
                "market_date":market_date,
                "ticker":c.get("ticker"),
                "company":c.get("company"),
                "trend_key":trend.get("key"),
                "trend":trend.get("label"),
                "trend_rank":trend.get("rank"),
                "company_rank":c.get("rank"),
                "role":c.get("role"),
                "proof":c.get("proof"),
                "signal":c.get("signal"),
                "entry_price":c.get("price"),
                "currency":c.get("currency"),
                "exchange":c.get("exchange"),
                "entry_qqq_price":None,
                "forward_returns":{}
            })
            seen.add(key); added+=1
    ledger["last_updated_at"]=datetime.now(timezone.utc).isoformat()
    ledger["method"]="first-observed prospective state-transition ledger; immutable event dates"
    LEDGER.parent.mkdir(parents=True,exist_ok=True)
    LEDGER.write_text(json.dumps(ledger,indent=2),encoding="utf-8")
    print(json.dumps({"events":len(events),"added":added}))

if __name__=="__main__":
    main()
