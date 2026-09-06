#!/usr/bin/env python3
"""ORACLE V5 final external validation worker.

The live Supabase database is deliberately NOT used for heavy historical work.
Inputs are frozen point-in-time ranked snapshots committed in GitHub. Market
prices and SEC Companyfacts are fetched by this worker. Every historical
fundamental fact must have filed <= decision date. A market-rerating proxy is
used for expectation gap; it is never labelled analyst consensus.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

PICKS_DIR = Path("data/v5_ranked_picks")
RESERVE_DIR = Path("data/v5_ranked_reserve")
FALLBACK = Path("data/v5_live_fallback.json")
OUT = Path("data/v5_analytics.json")

ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
PERIODIC_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A", "6-K"}
REV_TAGS = [
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet",
]
NI_TAGS = ["NetIncomeLoss", "ProfitLoss"]
CASH_TAGS = ["CashAndCashEquivalentsAtCarryingValue"]
DEBT_CUR_TAGS = ["LongTermDebtCurrent", "LongTermDebtAndFinanceLeaseObligationsCurrent"]
DEBT_NONCUR_TAGS = ["LongTermDebtNoncurrent", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"]


def fetch_json(url: str, attempts: int = 4, timeout: int = 30, sec: bool = False):
    last = None
    ua = "ORACLE-Intelligence research client contact: research@example.com" if sec else "Mozilla/5.0 ORACLE-V5-Final/1.0"
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            if i + 1 < attempts:
                time.sleep(1.5 + i * 2.0)
    raise RuntimeError(f"GET failed: {url}: {last}")


def safe_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def avg(xs): return statistics.fmean(xs) if xs else None

def med(xs): return statistics.median(xs) if xs else None


def trimmed90(xs):
    if not xs: return None
    ys = sorted(xs); k = max(0, int(len(ys) * 0.05))
    zs = ys[k:len(ys)-k] if len(ys)-2*k > 0 else ys
    return avg(zs)


def load_ranked_candidates():
    grouped = defaultdict(dict)
    primary_files = sorted(PICKS_DIR.glob("*.json"))
    if not primary_files:
        raise RuntimeError("No frozen V5 ranked snapshots")
    all_files = primary_files + sorted(RESERVE_DIR.glob("*.json"))
    for path in all_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("strict_pit") is not True:
            raise RuntimeError(f"Strict-PIT gate failed: {path}")
        for row in payload.get("picks", []):
            if len(row) < 4: continue
            ds, model, ticker, rank = str(row[0]), str(row[1]), str(row[2]).upper(), int(row[3])
            key = (ds, model)
            prev = grouped[key].get(ticker)
            if prev is None or rank < prev:
                grouped[key][ticker] = rank
    out = {}
    for key, mp in grouped.items():
        out[key] = [{"as_of_date": key[0], "model": key[1], "ticker": t, "rank": r}
                    for t, r in sorted(mp.items(), key=lambda z: (z[1], z[0]))]
    return all_files, out


def yahoo_symbol(ticker: str) -> str:
    return ticker.upper().replace(".", "-")


def yahoo_history(ticker: str):
    symbol = urllib.parse.quote(yahoo_symbol(ticker), safe="-")
    start = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime.now(timezone.utc).timestamp()) + 86400
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={start}&period2={end}&interval=1d&events=history&includeAdjustedClose=true"
    p = fetch_json(url)
    result = (((p.get("chart") or {}).get("result") or [None])[0])
    if not result: return {}
    stamps = result.get("timestamp") or []
    adj = (((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [])
    close = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    out = {}
    for i, ts in enumerate(stamps):
        px = safe_float(adj[i] if i < len(adj) else None)
        if px is None: px = safe_float(close[i] if i < len(close) else None)
        if px and px > 0: out[datetime.fromtimestamp(ts, timezone.utc).date()] = px
    return out


def latest_before(hist, d):
    xs = [(k,v) for k,v in hist.items() if k < d]
    return max(xs, default=(None,None), key=lambda z:z[0])


def latest_on_or_before(hist, d):
    xs = [(k,v) for k,v in hist.items() if k <= d]
    return max(xs, default=(None,None), key=lambda z:z[0])


def is_listed_at(hist, as_of):
    if not hist: return False
    first = min(hist)
    _, px = latest_before(hist, as_of)
    return first < as_of and px is not None


def outcome(hist, as_of):
    target = month_add(as_of, 6)
    if target > datetime.now(timezone.utc).date(): return None
    ed, ep = latest_before(hist, as_of)
    xd, xp = latest_on_or_before(hist, target)
    if not ep or not xp: return None
    return {"return_6m":100*(xp/ep-1),"entry_date":ed.isoformat(),"exit_date":xd.isoformat()}


def prior_return(hist, as_of, months):
    _, nowpx = latest_before(hist, as_of)
    _, oldpx = latest_on_or_before(hist, month_add(as_of, -months))
    if not nowpx or not oldpx: return None
    return 100*(nowpx/oldpx-1)


def expectation_gap_proxy(hist, as_of):
    """Low-saturation proxy, not analyst consensus. Does not reward crashes."""
    r6 = prior_return(hist, as_of, 6)
    r12 = prior_return(hist, as_of, 12)
    score = 75.0
    if r12 is None: score -= 15
    elif r12 > 120: score -= 45
    elif r12 > 80: score -= 35
    elif r12 > 60: score -= 25
    elif r12 > 30: score -= 10
    if r6 is None: score -= 10
    elif r6 > 80: score -= 30
    elif r6 > 50: score -= 22
    elif r6 > 30: score -= 12
    # Near a 52-week high is only penalized when rerating is already strong.
    cur_d, cur = latest_before(hist, as_of)
    start = as_of - timedelta(days=365)
    window = [v for k,v in hist.items() if start <= k < as_of]
    dist_high = None
    if cur and window:
        dist_high = 100*(cur/max(window)-1)
        if dist_high > -5 and (r12 or 0) > 60: score -= 8
    return {"score":max(0,min(100,round(score,2))),"prior_return_6m":r6,"prior_return_12m":r12,"distance_52w_high_pct":dist_high,"kind":"MARKET_RERATING_PROXY_NOT_ANALYST_CONSENSUS"}


def sec_ticker_map():
    p = fetch_json("https://www.sec.gov/files/company_tickers.json", sec=True)
    out = {}
    for row in p.values():
        t = str(row.get("ticker") or "").upper()
        cik = row.get("cik_str")
        if t and cik is not None: out[t] = int(cik)
    return out


def sec_companyfacts(cik):
    return fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json", sec=True)


def fact_rows(usgaap, tags):
    rows=[]
    for tag in tags:
        node=usgaap.get(tag) or {}
        units=node.get("units") or {}
        for unit, vals in units.items():
            if unit not in ("USD", "USD/shares", "shares", "pure") and not unit.startswith("USD"):
                continue
            for x in vals or []:
                if safe_float(x.get("val")) is not None:
                    rows.append(x)
    return rows


def annual_latest_pair(usgaap, tags, as_of):
    by_end={}
    for x in fact_rows(usgaap,tags):
        try:
            filed=date.fromisoformat(str(x.get("filed"))[:10]); end=date.fromisoformat(str(x.get("end"))[:10]); start=date.fromisoformat(str(x.get("start"))[:10])
        except Exception: continue
        if filed>as_of or end>as_of or str(x.get("form")) not in ANNUAL_FORMS: continue
        dur=(end-start).days
        if dur<300 or dur>430: continue
        cur=by_end.get(end)
        if cur is None or filed>cur[0]: by_end[end]=(filed,safe_float(x.get("val")))
    ends=sorted(by_end, reverse=True)
    vals=[by_end[e][1] for e in ends if by_end[e][1] is not None]
    return (vals[0] if vals else None, vals[1] if len(vals)>1 else None)


def instant_latest(usgaap,tags,as_of):
    best=None
    for x in fact_rows(usgaap,tags):
        try:
            filed=date.fromisoformat(str(x.get("filed"))[:10]); end=date.fromisoformat(str(x.get("end"))[:10])
        except Exception: continue
        if filed>as_of or end>as_of or str(x.get("form")) not in PERIODIC_FORMS: continue
        val=safe_float(x.get("val"))
        key=(end,filed)
        if val is not None and (best is None or key>best[0]): best=(key,val)
    return best[1] if best else None


def fundamental_snapshot(companyfacts, as_of):
    us=(companyfacts or {}).get("facts",{}).get("us-gaap",{})
    if not us: return {"quality":0,"score":None,"source":"SEC_COMPANYFACTS_PIT"}
    rev,prev=annual_latest_pair(us,REV_TAGS,as_of)
    ni,_=annual_latest_pair(us,NI_TAGS,as_of)
    cash=instant_latest(us,CASH_TAGS,as_of)
    dc=instant_latest(us,DEBT_CUR_TAGS,as_of); dn=instant_latest(us,DEBT_NONCUR_TAGS,as_of)
    debt=None if dc is None and dn is None else (dc or 0)+(dn or 0)
    growth=None if rev is None or prev in (None,0) else 100*(rev-prev)/abs(prev)
    quality=(30 if rev is not None else 0)+(20 if prev is not None else 0)+(20 if ni is not None else 0)+(15 if cash is not None else 0)+(15 if debt is not None else 0)
    score=None
    if quality>=70 and rev is not None and prev is not None and ni is not None:
        score=50.0
        if growth is not None:
            if growth>=25: score+=20
            elif growth>=10: score+=12
            elif growth>0: score+=5
            elif growth<=-15: score-=18
            else: score-=7
        score += 10 if ni>0 else -12
        if cash is not None and debt is not None:
            if debt==0 or cash>=debt: score+=12
            elif cash>0 and debt>cash*3: score-=12
        score=max(0,min(100,round(score,2)))
    return {"quality":quality,"score":score,"revenue":rev,"revenue_previous":prev,"revenue_growth_pct":growth,"net_income":ni,"cash":cash,"debt":debt,"source":"SEC_COMPANYFACTS_PIT","filed_cutoff":as_of.isoformat()}


def statblock(picks):
    alphas=[p["alpha_6m"] for p in picks if p.get("alpha_6m") is not None]
    return {"n":len(alphas),"avg_alpha_6m":avg(alphas),"median_alpha_6m":med(alphas),"win_rate_vs_qqq":100*sum(a>0 for a in alphas)/len(alphas) if alphas else None,"trimmed_alpha_90pct":trimmed90(alphas),"best_alpha":max(alphas) if alphas else None,"worst_alpha":min(alphas) if alphas else None}


def regime(d): return "2017_2021" if d.year<=2021 else ("2022_2025" if d.year<=2025 else "2026_FORWARD")


def validated(stats, regimes):
    return stats["n"]>=100 and (stats["median_alpha_6m"] or -999)>0 and (stats["win_rate_vs_qqq"] or 0)>55 and (stats["trimmed_alpha_90pct"] or -999)>0 and all(regimes[r]["n"]<25 or (regimes[r]["median_alpha_6m"] or -999)>0 for r in ("2017_2021","2022_2025"))


def main():
    files, grouped=load_ranked_candidates()
    needed={"QQQ"}
    for rows in grouped.values(): needed.update(x["ticker"] for x in rows)
    fallback=json.loads(FALLBACK.read_text(encoding="utf-8")) if FALLBACK.exists() else {}
    needed.update(str(x.get("ticker") or "").upper() for x in fallback.get("early_birds",[]) if x.get("ticker"))

    histories={}; price_fail=[]
    for i,t in enumerate(sorted(needed)):
        try:
            h=yahoo_history(t)
            if h: histories[t]=h
            else: price_fail.append({"ticker":t,"error":"NO_HISTORY"})
        except Exception as e: price_fail.append({"ticker":t,"error":str(e)[:160]})
        if i and i%15==0: time.sleep(.7)

    # Listing-date gate. Select at most five eligible names from primary+reserve ranks.
    selected=[]; listing_rejections=[]
    for (ds,model), rows in sorted(grouped.items()):
        asof=date.fromisoformat(ds[:10]); n=0
        for x in rows:
            h=histories.get(x["ticker"],{})
            if not is_listed_at(h,asof):
                listing_rejections.append({**x,"reason":"NOT_LISTED_AT_DECISION_DATE"}); continue
            selected.append({**x,"selected_rank":n+1}); n+=1
            if n>=5: break

    # SEC CIK mapping and Companyfacts, only for tickers actually needed by selected/current names.
    sec_map={}; secfacts={}; sec_fail=[]
    try: sec_map=sec_ticker_map()
    except Exception as e: sec_fail.append({"ticker":"__CIK_MAP__","error":str(e)[:180]})
    sec_needed=sorted({x["ticker"] for x in selected}|{str(x.get("ticker") or "").upper() for x in fallback.get("early_birds",[]) if x.get("ticker")})
    for i,t in enumerate(sec_needed):
        cik=sec_map.get(t)
        if cik is None: continue
        try: secfacts[t]=sec_companyfacts(cik)
        except Exception as e: sec_fail.append({"ticker":t,"error":str(e)[:180]})
        time.sleep(.12)
        if i and i%20==0: time.sleep(.8)

    qqq_cache={}; base_by_model=defaultdict(list)
    for p in selected:
        asof=date.fromisoformat(p["as_of_date"][:10]); q=qqq_cache.get(asof)
        if asof not in qqq_cache:
            q=outcome(histories.get("QQQ",{}),asof); qqq_cache[asof]=q
        ret=outcome(histories.get(p["ticker"],{}),asof)
        if not q or not ret: continue
        f=fundamental_snapshot(secfacts.get(p["ticker"]),asof)
        gap=expectation_gap_proxy(histories.get(p["ticker"],{}),asof)
        row={**p,**ret,"qqq_return_6m":q["return_6m"],"alpha_6m":ret["return_6m"]-q["return_6m"],"regime":regime(asof),"fundamental":f,"expectation_gap":gap}
        base_by_model[p["model"]].append(row)

    # Predefined second-stage tests. These rules are frozen before reading their outcomes.
    derived={}
    src=base_by_model.get("ACCEL_EVIDENCE",[])
    derived["ACCEL_EVIDENCE_FUND_PIT"]=[p for p in src if p["fundamental"].get("quality",0)>=70 and (p["fundamental"].get("score") or 0)>=60 and (p["fundamental"].get("revenue_growth_pct") or -999)>0 and (p["fundamental"].get("net_income") or -1)>0]
    derived["ACCEL_EVIDENCE_FUND_GAP"]=[p for p in derived["ACCEL_EVIDENCE_FUND_PIT"] if (p["expectation_gap"].get("score") or 0)>=55]

    models={}
    for name,picks in sorted({**base_by_model,**derived}.items()):
        overall=statblock(picks)
        regs={r:statblock([p for p in picks if p["regime"]==r]) for r in ("2017_2021","2022_2025","2026_FORWARD")}
        models[name]={"status":"VALIDATED" if validated(overall,regs) else "RESEARCH_ONLY","overall":overall,"regimes":regs,"latest_picks":sorted(picks,key=lambda x:(x["as_of_date"],-x.get("selected_rank",x.get("rank",99))),reverse=True)[:10]}

    any_validated=any(v["status"]=="VALIDATED" for v in models.values())
    # Current paper decision from the latest confirmed snapshot. Real-money gate stays closed until alpha is validated.
    current=[]; today=datetime.now(timezone.utc).date()
    for e in fallback.get("early_birds",[]):
        t=str(e.get("ticker") or "").upper(); status=e.get("status")
        if not t or status not in ("EARLY_BIRD","WATCH_EARLY"): continue
        f=fundamental_snapshot(secfacts.get(t),today); gap=expectation_gap_proxy(histories.get(t,{}),today)
        early=safe_float(e.get("early_bird_score")) or 0
        composite=None if f.get("score") is None else round(.45*early+.30*f["score"]+.25*gap["score"],2)
        if composite is not None and f.get("quality",0)>=70 and f.get("score",0)>=60 and gap.get("score",0)>=45:
            decision="BUY_CANDIDATE" if any_validated else "PILOT_BUY"
            weight=35 if any_validated and composite>=75 else 15
        elif f.get("quality",0)>=70:
            decision="WATCH"; weight=0
        else:
            decision="WAIT_FOR_FUNDAMENTALS"; weight=0
        current.append({**e,"fundamental":f,"expectation_gap":gap,"composite_score":composite,"decision":decision,"max_paper_weight_pct":weight})
    current.sort(key=lambda x:(x.get("composite_score") is not None,x.get("composite_score") or -1),reverse=True)
    global_decision="NO_ACTION"
    if current and current[0]["decision"] in ("PILOT_BUY","BUY_CANDIDATE"): global_decision=current[0]["decision"]
    elif current: global_decision="WATCH"

    result={
      "ok":True,"engine":"ORACLE_V5_FINAL_EXTERNAL_PIT","generated_at":datetime.now(timezone.utc).isoformat(),"strict_pit":True,"supabase_dependency_for_backtest":False,
      "production_readiness":{"research_product_complete":True,"real_money_alpha_validated":any_validated,"real_money_autonomous_trading_enabled":False,"global_decision":global_decision,"remaining_non_blocking_limitations":["TRUE_ANALYST_CONSENSUS_UNAVAILABLE_EXPECTATION_GAP_USES_MARKET_RERATING_PROXY","DELISTED_COMPANY_UNIVERSE_NOT_YET_COMPLETE"]},
      "counts":{"snapshot_files":len(files),"candidate_groups":len(grouped),"listing_eligible_picks":len(selected),"listing_rejections":len(listing_rejections),"price_tickers_loaded":len(histories),"price_failures":len(price_fail),"sec_companyfacts_loaded":len(secfacts),"sec_failures":len(sec_fail)},
      "methodology":{"top_n_per_quarter":5,"listing_gate":"must have traded strictly before decision date","horizon_months":6,"benchmark":"QQQ","fundamentals":"SEC Companyfacts with filed <= decision date","expectation_gap":"MARKET_RERATING_PROXY_NOT_ANALYST_CONSENSUS","promotion_gate":"N>=100; median alpha>0; win-rate>55%; trimmed alpha>0; regime stability","derived_rules_frozen_before_outcomes":True},
      "models":models,"current_decision":{"global":global_decision,"candidates":current[:10]},"listing_rejections":listing_rejections[:100],"price_failures":price_fail[:50],"sec_failures":sec_fail[:50]
    }
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({k:v["overall"] for k,v in models.items()},indent=2))
    print(json.dumps(result["production_readiness"],indent=2))
    print(json.dumps(result["counts"],indent=2))

if __name__=="__main__": main()
