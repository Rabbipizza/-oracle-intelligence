#!/usr/bin/env python3
"""Build the ORACLE cockpit data product from research, market and portfolio ledgers."""
import json, math, statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(".")
OUT=ROOT/"data/cockpit.json"

def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default

def pct(a,b):
    if a is None or b in (None,0): return None
    return (a/b-1.0)*100.0

def roundn(x,n=2):
    return None if x is None or not math.isfinite(x) else round(x,n)

def clamp(x,a=0,b=100):
    return max(a,min(b,x))

def series_rows(market,ticker):
    p=(market.get("prices",{}).get(ticker) or {}).get("rows",[])
    return sorted([r for r in p if isinstance(r,dict) and r.get("date") and isinstance(r.get("close"),(int,float))],key=lambda r:r["date"])

def close_on_or_before(rows,date):
    vals=[r for r in rows if r["date"]<=date]
    return vals[-1]["close"] if vals else None

def latest_metrics(rows, benchmark_rows=None, as_of=None):
    if as_of:
        rows=[r for r in rows if r.get("date","")<=as_of]
        if benchmark_rows:
            benchmark_rows=[r for r in benchmark_rows if r.get("date","")<=as_of]
    if not rows:
        return {"date":None,"price":None,"d1":None,"w1":None,"m1":None,"rel_m1_qqq":None,"spark":[]}
    latest=rows[-1]
    price=latest["close"]
    d1=pct(price,rows[-2]["close"]) if len(rows)>=2 else None
    w1=pct(price,rows[-6]["close"]) if len(rows)>=6 else None
    m1=pct(price,rows[-22]["close"]) if len(rows)>=22 else None
    rel=None
    if benchmark_rows and len(benchmark_rows)>=22 and m1 is not None:
        q=pct(benchmark_rows[-1]["close"],benchmark_rows[-22]["close"])
        if q is not None: rel=m1-q
    tail=[r["close"] for r in rows[-22:]]
    base=tail[0] if tail else None
    spark=[roundn(v/base*100,2) for v in tail] if base else []
    return {"date":latest["date"],"price":roundn(price,4),"d1":roundn(d1),"w1":roundn(w1),"m1":roundn(m1),"rel_m1_qqq":roundn(rel),"spark":spark}

def fx_on_or_before(fx,date):
    vals=[r for r in fx if r.get("date","")<=date and isinstance(r.get("chf_per_usd"),(int,float))]
    return vals[-1]["chf_per_usd"] if vals else None

def signal_for(ticker,proof,decisions):
    explicit=(decisions.get("signals",{}).get(ticker) or {})
    if explicit:
        return explicit.get("signal","ORANGE"), explicit.get("reason","")
    p=(proof or "").upper()
    # IMPORTANT: UNPROVEN contains the substring "PROVEN"; test it first.
    if p=="UNPROVEN" or not p:
        return "RED","Evidence is insufficient for an ORACLE entry."
    if p=="PROVEN":
        return "ORANGE","Economic exposure is proven; full entry gate has not been validated."
    if p.startswith("PROVEN ") or "PARTIAL" in p:
        return "ORANGE","Exposure is credible but at least one evidence or entry gate remains open."
    return "RED","Evidence is insufficient for an ORACLE entry."

def rank_delta(cur,prev):
    if not cur or not prev: return None
    return prev-cur

def build_portfolio(market, portfolio):
    fx=sorted(market.get("fx_usd_chf",[]),key=lambda r:r.get("date",""))
    benchmark=portfolio.get("benchmark_ticker","QQQ")
    qrows=series_rows(market,benchmark)
    latest_date=qrows[-1]["date"] if qrows else None
    latest_fx=fx_on_or_before(fx,latest_date) if latest_date else None
    positions=[]
    invested=0.0; current_invested=0.0; matched_qqq=0.0
    for p in portfolio.get("positions",[]):
        if p.get("status")!="OPEN": continue
        ticker=p["ticker"]; allocated=float(p["allocated_chf"]); td=p["trade_date"]
        rows=series_rows(market,ticker)
        entry_px=close_on_or_before(rows,td); current_px=close_on_or_before(rows,latest_date) if latest_date else None
        entry_fx=fx_on_or_before(fx,td)
        q_entry=close_on_or_before(qrows,td); q_current=close_on_or_before(qrows,latest_date) if latest_date else None
        current=None; qvalue=None; units=None
        if entry_px and current_px and entry_fx and latest_fx:
            units=allocated/(entry_px*entry_fx)
            current=units*current_px*latest_fx
        if q_entry and q_current and entry_fx and latest_fx:
            qunits=allocated/(q_entry*entry_fx)
            qvalue=qunits*q_current*latest_fx
        invested+=allocated
        if current is not None: current_invested+=current
        if qvalue is not None: matched_qqq+=qvalue
        positions.append({
            "ticker":ticker,"trade_date":td,"allocated_chf":allocated,
            "entry_price_usd":roundn(entry_px,4),"entry_fx_chf_per_usd":roundn(entry_fx,6),
            "current_price_usd":roundn(current_px,4),"current_value_chf":roundn(current),
            "pnl_chf":roundn(current-allocated) if current is not None else None,
            "pnl_pct":roundn(pct(current,allocated)) if current is not None else None,
            "matched_qqq_chf":roundn(qvalue)
        })
    cash=float(portfolio.get("cash_chf",0))
    total=(current_invested+cash) if current_invested or cash else None
    official_oracle_ret=pct(current_invested,invested) if invested and current_invested else None
    official_qqq_ret=pct(matched_qqq,invested) if invested and matched_qqq else None
    alpha=(official_oracle_ret-official_qqq_ret) if official_oracle_ret is not None and official_qqq_ret is not None else None
    return {
        "as_of":latest_date,"initial_capital_chf":portfolio.get("initial_capital_chf"),
        "cash_chf":roundn(cash),"invested_cost_chf":roundn(invested),
        "current_invested_value_chf":roundn(current_invested) if current_invested else None,
        "total_value_chf":roundn(total),"total_return_pct":roundn(pct(total,float(portfolio.get("initial_capital_chf",1000)))) if total else None,
        "official_comparison":{
            "mode":portfolio.get("official_benchmark_mode"),
            "oracle_return_pct":roundn(official_oracle_ret),
            "qqq_return_pct":roundn(official_qqq_ret),
            "alpha_pct_points":roundn(alpha),
            "oracle_value_chf":roundn(current_invested) if current_invested else None,
            "qqq_matched_value_chf":roundn(matched_qqq) if matched_qqq else None,
            "capital_compared_chf":roundn(invested)
        },
        "positions":positions
    }

def main():
    research=load("research-universe.json")
    market=load("data/market.json")
    decisions=load("decision-state.json")
    portfolio=load("portfolio.json")
    challengers=load("data/company-challengers.json")
    dossiers=load("data/evidence-dossiers.json")
    prior_cockpit=load("data/cockpit.json")
    qrows=series_rows(market,"QQQ")
    market_as_of=qrows[-1]["date"] if qrows else None

    trends=[]
    all_companies=[]
    for key,tr in research.get("trends",{}).items():
        ds=decisions.get("trends",{}).get(key,{})
        companies=[]
        m1s=[]; positive=0; available=0

        # Static research universe = validated/incumbent layer.
        base_rows=[]
        for i,row in enumerate(tr.get("companies",[]),1):
            ticker,name,role,proof=(row+[None,None,None,None])[:4]
            base_rows.append({
                "ticker":ticker,"company":name,"role":role,"proof":proof,
                "research_rank":i,"radar_origin":"RESEARCH_UNIVERSE",
                "radar_discovery_score":0.0
            })

        # Dynamic challengers = radar-only until explicit economic proof exists.
        known={x["ticker"] for x in base_rows}
        for ch in (challengers.get("trends",{}) or {}).get(key,[]) or []:
            ticker=ch.get("ticker")
            if not ticker or ticker in known:
                continue
            base_rows.append({
                "ticker":ticker,
                "company":ch.get("name") or ticker,
                "role":"Dynamic challenger — economic capture unproven",
                "proof":"UNPROVEN",
                "research_rank":None,
                "radar_origin":"DYNAMIC_CHALLENGER",
                "radar_discovery_score":float(ch.get("radar_discovery_score") or 0),
                "challenger_queries":ch.get("queries",[])
            })

        previous={}
        for pt in prior_cockpit.get("trends",[]) or []:
            if pt.get("key")==key:
                previous={x.get("ticker"):x.get("rank") for x in pt.get("companies",[]) or []}
                break

        for row in base_rows:
            ticker=row["ticker"]; proof=row.get("proof")
            metrics=latest_metrics(series_rows(market,ticker),qrows,as_of=market_as_of)
            sig,reason=signal_for(ticker,proof,decisions)
            if metrics["m1"] is not None:
                available+=1; m1s.append(metrics["m1"])
                if metrics["m1"]>0: positive+=1
            md=market.get("prices",{}).get(ticker) or {}
            sc=(decisions.get("scores",{}) or {}).get(ticker,{})
            structural=sc.get("structural_early_bird")
            entry=sc.get("entry_score")
            proof_u=str(proof or "").upper()
            evidence_base=100.0 if sc.get("evidence_status")=="PROVEN" else 70.0 if "PROVEN" in proof_u else 55.0 if "PARTIAL" in proof_u else 20.0
            structural_for_rank=float(structural if structural is not None else evidence_base)
            entry_for_rank=float(entry if entry is not None else 50.0)
            rel=float(metrics.get("rel_m1_qqq") or 0.0)
            momentum=clamp(50.0+2.0*rel)
            discovery_boost=min(10.0,float(row.get("radar_discovery_score") or 0.0)*0.20)
            radar_score=roundn(
                0.45*structural_for_rank+
                0.30*entry_for_rank+
                0.15*momentum+
                0.10*evidence_base+
                discovery_boost,
                2
            )
            dossier=(dossiers.get("companies",{}) or {}).get(ticker,{})
            c={"rank":None,"previous_rank":previous.get(ticker),
               "ticker":ticker,"company":row.get("company"),"role":row.get("role"),"proof":proof,
               "evidence_maturity":dossier.get("maturity"),
               "trend_evidence_score":dossier.get("trend_evidence_score"),
               "company_capture_score":dossier.get("company_capture_score"),
               "research_rank":row.get("research_rank"),"radar_origin":row.get("radar_origin"),
               "radar_discovery_score":row.get("radar_discovery_score",0.0),
               "radar_rank_score":radar_score,
               "challenger_queries":row.get("challenger_queries",[]),
               "signal":sig,"signal_reason":reason,
               "structural_early_bird":structural,
               "entry_score":entry,
               "indicative_entry_sizing":sc.get("indicative_entry_sizing"),
               "hold_score":sc.get("hold_score"),
               "capital_competition_score":sc.get("capital_competition_score"),
               "actual_weight_pct":sc.get("actual_weight_pct"),
               "target_weight_pct":sc.get("target_weight_pct"),
               "portfolio_action":sc.get("portfolio_action"),
               "evidence_status":sc.get("evidence_status") or ("UNPROVEN" if row.get("radar_origin")=="DYNAMIC_CHALLENGER" else None),
               "invalidation":sc.get("invalidation",[]),
               "currency":md.get("currency"),"exchange":md.get("exchange"),**metrics}
            companies.append(c)

        # Dynamic Top 20: proof/structure dominates, then entry + QQQ-relative acceleration.
        # Unproven challengers can enter the radar but never become GREEN here.
        companies.sort(key=lambda x:(
            x.get("radar_rank_score") is None,
            -(x.get("radar_rank_score") or -1e9),
            x.get("research_rank") or 999
        ))
        companies=companies[:20]
        for i,c in enumerate(companies,1):
            c["rank"]=i
            pr=c.get("previous_rank")
            c["rank_delta"]=None if pr is None else pr-i
            all_companies.append({**c,"trend_key":key,"trend":tr.get("label"),"trend_rank":ds.get("rank")})

        trends.append({
            "key":key,"label":tr.get("label"),"rank":ds.get("rank"),
            "previous_rank":ds.get("previous_rank"),"rank_delta":rank_delta(ds.get("rank"),ds.get("previous_rank")),
            "state":ds.get("state","UNRANKED"),"summary":ds.get("summary",""),
            "market":{"median_1m_pct":roundn(statistics.median(m1s)) if m1s else None,
                      "breadth_positive_1m_pct":roundn(positive/available*100) if available else None,
                      "priced_companies":available},
            "companies":companies
        })
    trends.sort(key=lambda t:(t["rank"] is None,t["rank"] or 999))

    action=[]
    for c in all_companies:
        if c["signal"] in ("GREEN","ORANGE"):
            action.append(c)
    order={"GREEN":0,"ORANGE":1,"RED":2}
    # Never turn short-term momentum into an implicit recommendation.
    # GREEN comes first; ORANGE is a watchlist ordered by validated trend/company rank.
    action.sort(key=lambda c:(order.get(c["signal"],9),c.get("trend_rank") or 999,c.get("rank") or 999))
    # Keep every GREEN visible. Limit only the ORANGE watchlist so a GREEN\n    # cannot disappear merely because its research-universe row is ranked after 12 ORANGEs.\n    greens=[c for c in action if c["signal"]=="GREEN"]\n    oranges=[c for c in action if c["signal"]=="ORANGE"][:12]\n    action=greens+oranges

    discovery=load("data/discovery-candidates.json")
    gate=load("data/source-gate-status.json")
    scout=[]
    gates={g.get("term"):g for g in gate.get("candidate_gates",[])}
    for c in discovery.get("candidates",[])[:30]:
        g=gates.get(c.get("term"),{})
        if g.get("coverage_gate_pass"):
            scout.append({"term":c.get("term"),"score":c.get("discovery_score"),"acceleration":c.get("acceleration"),"families":g.get("families",[]),"status":g.get("trend_status")})

    portfolio_view=build_portfolio(market,portfolio)
    data_as_of=portfolio_view.get("as_of")
    decision_as_of=decisions.get("as_of")
    decision_lag_days=None
    if data_as_of and decision_as_of:
        try:
            decision_lag_days=(datetime.fromisoformat(data_as_of)-datetime.fromisoformat(decision_as_of)).days
        except Exception:
            decision_lag_days=None
    decision_freshness={
        "status":"STALE" if decision_lag_days is not None and decision_lag_days>1 else "CURRENT",
        "lag_days":decision_lag_days,
        "message":(
            f"Decision state is {decision_lag_days} day(s) behind market data."
            if decision_lag_days is not None and decision_lag_days>1
            else "Decision state is aligned with the latest market snapshot."
        )
    }

    out={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "market_generated_at":market.get("generated_at"),
        "market_source":market.get("source"),
        "data_as_of":data_as_of,
        "decision_as_of":decision_as_of,
        "decision_freshness":decision_freshness,
        "discovery":{"quality":discovery.get("quality"),"unique_papers":discovery.get("unique_papers"),
                     "recent_docs":discovery.get("recent_docs"),"baseline_docs":discovery.get("baseline_docs"),
                     "scout_candidates_passing_coverage":scout[:10],
                     "evidence_maturity_scale":dossiers.get("maturity_scale",[]),
                     "concept_evidence":dossiers.get("concepts",{})},
        "trends":trends,
        "action_now":action,
        "target_allocation_pct":decisions.get("target_allocation_pct",{}),
        "actual_holdings_pct":decisions.get("actual_holdings_pct",{}),
        "benchmark_competition":decisions.get("benchmark_competition",{}),
        "portfolio":portfolio_view,
        "market_errors":market.get("errors",[])
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"trends":len(trends),"companies":sum(len(t["companies"]) for t in trends),"action":len(action),"market_errors":len(out["market_errors"])}))

if __name__=="__main__":
    main()
