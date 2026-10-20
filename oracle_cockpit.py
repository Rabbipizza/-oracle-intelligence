#!/usr/bin/env python3
"""Build the ORACLE cockpit data product from research, market and portfolio ledgers."""
import json, math, statistics
from datetime import datetime, timezone
from pathlib import Path
from oracle_data_quality import clean_rows, market_date, series_quality, dated_value, cost_weights, positive

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
    return clean_rows(market,ticker)

def close_on_or_before(rows,date):
    return dated_value(rows,date,"close")

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
    return dated_value(fx,date,"chf_per_usd")

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
    """Value ledgers independently. Any unpriced leg makes the total unavailable."""
    fx=market.get("fx_usd_chf",[])
    latest_date=market_date(market)
    qrows=series_rows(market,"QQQ")
    latest_fx=fx_on_or_before(fx,latest_date)
    q_ready=series_quality(market,"QQQ",latest_date)["status"]=="AVAILABLE"
    positions=[]
    invested=0.0
    for p in portfolio.get("positions",[]):
        if p.get("status")!="OPEN": continue
        ticker=p["ticker"]; allocated=float(p["allocated_chf"]); td=p["trade_date"]
        rs=series_rows(market,ticker)
        quality=series_quality(market,ticker,latest_date)
        entry_px=close_on_or_before(rs,td)
        current_px=close_on_or_before(rs,latest_date) if quality["status"]=="AVAILABLE" else None
        entry_fx=fx_on_or_before(fx,td)
        q_entry=close_on_or_before(qrows,td)
        q_current=close_on_or_before(qrows,latest_date) if q_ready else None
        current=allocated*current_px*latest_fx/(entry_px*entry_fx) if all(positive(v) for v in (entry_px,current_px,entry_fx,latest_fx)) else None
        qvalue=allocated*q_current*latest_fx/(q_entry*entry_fx) if all(positive(v) for v in (q_entry,q_current,entry_fx,latest_fx)) else None
        invested+=allocated
        positions.append({"ticker":ticker,"trade_date":td,"allocated_chf":allocated,
            "entry_price_usd":roundn(entry_px,4),"entry_fx_chf_per_usd":roundn(entry_fx,6),
            "current_price_usd":roundn(current_px,4),"current_value_chf":roundn(current),
            "pnl_chf":roundn(current-allocated) if current is not None else None,
            "pnl_pct":roundn(pct(current,allocated)),"matched_qqq_chf":roundn(qvalue),
            "data_status":quality["status"]})
    complete=all(p["current_value_chf"] is not None for p in positions)
    current_invested=sum(p["current_value_chf"] for p in positions) if complete else None
    cash=float(portfolio.get("cash_chf",0))
    total=current_invested+cash if complete else None
    capital=portfolio.get("initial_capital_chf")
    baseline=portfolio.get("baseline_date") or min((p["trade_date"] for p in positions),default=None)
    q0=close_on_or_before(qrows,baseline)
    fx0=fx_on_or_before(fx,baseline)
    q1=close_on_or_before(qrows,latest_date) if q_ready else None
    q_full=capital*q1*latest_fx/(q0*fx0) if all(positive(v) for v in (capital,q0,q1,fx0,latest_fx)) else None
    kind=portfolio.get("kind","ACTUAL")
    if kind=="ACTUAL":
        oracle_value=total; q_value=q_full; compared=capital
        mode="full_initial_capital_chf"
    else:
        oracle_value=current_invested
        q_value=sum(p["matched_qqq_chf"] for p in positions) if all(p["matched_qqq_chf"] is not None for p in positions) else None
        compared=invested; mode="matched_simulated_tranches"
    oracle_ret=pct(oracle_value,compared); qqq_ret=pct(q_value,compared)
    alpha=oracle_ret-qqq_ret if oracle_ret is not None and qqq_ret is not None else None
    return {"kind":kind,"as_of":latest_date,"baseline_date":baseline,"initial_capital_chf":capital,
        "valuation_method":"Verified baseline/entry close and FX convention; no inferred executions.",
        "cash_chf":roundn(cash),"invested_cost_chf":roundn(invested),
        "current_invested_value_chf":roundn(current_invested),"total_value_chf":roundn(total),
        "total_return_pct":roundn(pct(total,capital)),
        "official_comparison":{"mode":mode,"baseline_date":baseline,
            "oracle_return_pct":roundn(oracle_ret),"qqq_return_pct":roundn(qqq_ret),
            "alpha_pct_points":roundn(alpha),"alpha_chf":roundn(oracle_value-q_value) if oracle_value is not None and q_value is not None else None,
            "oracle_value_chf":roundn(oracle_value),"qqq_value_chf":roundn(q_value),
            "capital_compared_chf":roundn(compared),"initial_fx_chf_per_usd":roundn(fx0,6),"current_fx_chf_per_usd":roundn(latest_fx,6)},
        "positions":positions}

def main():
    research=load("research-universe.json")
    market=load("data/market.json")
    decisions=load("decision-state.json")
    portfolio=load("portfolio.json")
    simulated=load("portfolio-simulated.json")
    challengers=load("data/company-challengers.json")
    dossiers=load("data/evidence-dossiers.json")
    chains=load("data/economic-chains.json")
    funnel=load("data/funnel-audit.json")
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
            quality=series_quality(market,ticker,market_as_of)
            if quality["status"]!="AVAILABLE":
                metrics=latest_metrics([])
                sig="ORANGE"
                reason="DATA_UNAVAILABLE: entry prohibited; provider errors retained in the audit."
            if metrics["m1"] is not None:
                available+=1; m1s.append(metrics["m1"])
                if metrics["m1"]>0: positive+=1
            md=market.get("prices",{}).get(ticker) or {}
            sc=(decisions.get("scores",{}) or {}).get(ticker,{})
            structural_quality=sc.get("structural_quality")
            structural=sc.get("structural_early_bird")
            market_recognition=sc.get("market_recognition_score")
            unrecognized_market=sc.get("unrecognized_market_score")
            entry=sc.get("entry_score")
            proof_u=str(proof or "").upper()
            evidence_base=100.0 if sc.get("evidence_status")=="PROVEN" else 70.0 if proof_u=="PROVEN" or proof_u.startswith("PROVEN ") else 55.0 if "PARTIAL" in proof_u else 20.0
            quality_for_rank=float(structural_quality if structural_quality is not None else evidence_base)
            structural_for_rank=float(structural if structural is not None else max(0.0,evidence_base-20.0))
            entry_for_rank=float(entry if entry is not None else 50.0)
            rel=float(metrics.get("rel_m1_qqq") or 0.0)
            momentum=clamp(50.0+2.0*rel)
            discovery_boost=min(10.0,float(row.get("radar_discovery_score") or 0.0)*0.20)
            radar_score=roundn(
                0.25*quality_for_rank+
                0.25*structural_for_rank+
                0.25*entry_for_rank+
                0.15*momentum+
                0.10*evidence_base+
                discovery_boost,
                2
            )
            dossier=(dossiers.get("companies",{}) or {}).get(ticker,{})
            chain=(chains.get("companies",{}) or {}).get(ticker,{})
            c={"rank":None,"previous_rank":previous.get(ticker),
               "ticker":ticker,"company":row.get("company"),"role":row.get("role"),"proof":proof,
               "evidence_maturity":dossier.get("maturity"),
               "trend_evidence_score":dossier.get("trend_evidence_score"),
               "company_capture_score":dossier.get("company_capture_score"),
               "chain_state":chain.get("state"),
               "pre_green":chain.get("pre_green",False),
               "discovery_edge_score":chain.get("discovery_edge_score"),
               "economic_proof_score":chain.get("economic_proof_score"),
               "research_priority_score":chain.get("research_priority_score"),
               "chain_blockers":chain.get("blockers",[]),
               "economic_chain":chain.get("chain",[]),
               "research_rank":row.get("research_rank"),"radar_origin":row.get("radar_origin"),
               "radar_discovery_score":row.get("radar_discovery_score",0.0),
               "radar_rank_score":radar_score,
               "challenger_queries":row.get("challenger_queries",[]),
               "signal":sig,"signal_reason":reason,
               "data_status":quality["status"],"data_quality":quality,
               "structural_quality":structural_quality,
               "structural_early_bird":structural,
               "market_recognition_score":market_recognition,
               "unrecognized_market_score":unrecognized_market,
               "entry_score":entry,
               "indicative_entry_sizing":sc.get("indicative_entry_sizing") if quality["status"]=="AVAILABLE" else {"band":"0%","max_pct":0,"min_pct":0,"label":"NO ENTRY"},
               "hold_score":sc.get("hold_score"),
               "capital_competition_score":sc.get("capital_competition_score"),
               "actual_weight_pct":sc.get("actual_weight_pct"),
               "target_weight_pct":sc.get("target_weight_pct",0) if quality["status"]=="AVAILABLE" else 0,
               "portfolio_action":sc.get("portfolio_action","WAIT") if quality["status"]=="AVAILABLE" else "BLOCKED",
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
        all_rows=companies
        companies=companies[:20]
        for i,c in enumerate(companies,1):
            c["rank"]=i
            pr=c.get("previous_rank")
            c["rank_delta"]=None if pr is None else pr-i
        all_companies.extend({**c,"trend_key":key,"trend":tr.get("label"),"trend_rank":ds.get("rank")} for c in all_rows)

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
    # Eligibility and action visibility are independent of the displayed Top 20.
    action=[c for c in action if c["data_status"]=="AVAILABLE"]
    action=[c for c in action if c["signal"]=="GREEN"]+[c for c in action if c["signal"]=="ORANGE"][:12]

    discovery=load("data/discovery-candidates.json")
    gate=load("data/source-gate-status.json")
    scout=[]
    gates={g.get("term"):g for g in gate.get("candidate_gates",[])}
    for c in discovery.get("candidates",[])[:30]:
        g=gates.get(c.get("term"),{})
        if g.get("coverage_gate_pass"):
            scout.append({"term":c.get("term"),"score":c.get("discovery_score"),"acceleration":c.get("acceleration"),"families":g.get("families",[]),"status":g.get("trend_status")})

    portfolio_view=build_portfolio(market,portfolio)
    simulated_view=build_portfolio(market,simulated)
    data_as_of=portfolio_view.get("as_of")
    decision_as_of=decisions.get("as_of")
    decision_lag_days=None
    if data_as_of and decision_as_of:
        try:
            decision_lag_days=(datetime.fromisoformat(data_as_of)-datetime.fromisoformat(decision_as_of)).days
        except Exception:
            decision_lag_days=None
    decision_freshness={
        "status":"CURRENT" if data_as_of and decision_as_of==data_as_of else "STALE",
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
                     "concept_evidence":dossiers.get("concepts",{}),
                     "pre_green_watchlist":chains.get("pre_green_watchlist",[]),
                     "candidate_chain_diagnostics":chains.get("candidate_chains",[])[:20],
                     "chain_pipeline":chains.get("pipeline",[]),"funnel_audit":funnel},
        "trends":trends,
        "action_now":action,
        "target_allocation_pct":decisions.get("target_allocation_pct",{}),
        "actual_holdings_pct":cost_weights(portfolio),
        "actual_allocation_basis":"INITIAL_COST_PLUS_CONFIRMED_CASH",
        "decision_status":decisions.get("decision_status"),
        "data_warnings":[{"ticker":t,**series_quality(market,t,market_as_of)} for t in sorted({c["ticker"] for c in all_companies}) if series_quality(market,t,market_as_of)["status"]!="AVAILABLE"],
        "benchmark_competition":decisions.get("benchmark_competition",{}),
        "portfolio":portfolio_view,
        "actual_portfolio":portfolio_view,
        "simulated_portfolio":simulated_view,
        "market_errors":market.get("errors",[])
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"trends":len(trends),"companies":sum(len(t["companies"]) for t in trends),"action":len(action),"market_errors":len(out["market_errors"])}))

if __name__=="__main__":
    main()
