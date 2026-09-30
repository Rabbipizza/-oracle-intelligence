#!/usr/bin/env python3
"""ORACLE dynamic listed-company challenger discovery.

Purpose:
- Expand each trend beyond the static research-universe.
- Discover listed-company challengers from public search endpoints.
- NEVER mark a challenger PROVEN or investable here.
- Output is radar-only; economic transmission/company capture still require explicit proof.
"""
import json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("data/company-challengers.json")
UA="Mozilla/5.0 (compatible; ORACLE-Research/4.0; +https://github.com/Rabbipizza/-oracle-intelligence)"

TREND_QUERIES={
    "power":[
        "data center cooling company stock",
        "electrical grid equipment company stock",
        "power generation data center stock",
        "switchgear electrical equipment stock",
        "nuclear power equipment stock"
    ],
    "cuas":[
        "counter drone defense stock",
        "drone defense company stock",
        "directed energy defense stock",
        "autonomous drone systems stock"
    ],
    "photonics":[
        "optical interconnect stock",
        "photonics semiconductor stock",
        "optical networking stock",
        "silicon photonics stock",
        "AI data center optics stock"
    ],
    "minerals":[
        "rare earth mining stock",
        "critical minerals stock",
        "copper mining stock",
        "magnet materials stock",
        "uranium mining stock"
    ],
    "physical":[
        "robotics stock",
        "industrial automation stock",
        "lidar stock",
        "edge AI semiconductor stock",
        "warehouse automation stock"
    ]
}

def get_json(url,timeout=25,retries=2):
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json,*/*"})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last=e
            if i<retries: time.sleep(1.5*(i+1))
    raise last

def yahoo_search(query,count=12):
    params=urllib.parse.urlencode({
        "q":query,
        "quotesCount":count,
        "newsCount":0,
        "listsCount":0,
        "enableFuzzyQuery":"false",
        "quotesQueryId":"tss_match_phrase_query"
    })
    url="https://query1.finance.yahoo.com/v1/finance/search?"+params
    obj=get_json(url)
    rows=[]
    for q in obj.get("quotes",[]) or []:
        if str(q.get("quoteType") or "").upper() not in {"EQUITY","ETF"}:
            continue
        symbol=str(q.get("symbol") or "").strip()
        if not symbol or "^" in symbol or "=" in symbol:
            continue
        rows.append({
            "ticker":symbol,
            "name":q.get("shortname") or q.get("longname") or symbol,
            "exchange":q.get("exchange"),
            "quote_type":q.get("quoteType"),
            "search_score":q.get("score"),
            "query":query,
            "source":"Yahoo Finance search"
        })
    return rows,url

def incumbents():
    out=set()
    try:
        r=json.loads(Path("research-universe.json").read_text())
        for tr in r.get("trends",{}).values():
            for row in tr.get("companies",[]):
                if row: out.add(str(row[0]))
    except Exception:
        pass
    return out

def main():
    now=datetime.now(timezone.utc)
    known=incumbents()
    by_trend={}
    errors=[]
    urls=[]
    for trend,queries in TREND_QUERIES.items():
        seen={}
        for query in queries:
            try:
                rows,url=yahoo_search(query)
                urls.append(url)
                for rank,row in enumerate(rows,1):
                    t=row["ticker"]
                    if t in known:
                        continue
                    # consensus across multiple economically-related searches is preferred
                    x=seen.setdefault(t,{
                        "ticker":t,
                        "name":row["name"],
                        "trend":trend,
                        "status":"UNPROVEN",
                        "economic_transmission":"REQUIRES_ANALYST_PROOF",
                        "company_capture":"REQUIRES_ANALYST_PROOF",
                        "queries":[],
                        "search_hits":0,
                        "search_rank_points":0.0,
                        "source":"Yahoo Finance search"
                    })
                    x["queries"].append(query)
                    x["search_hits"]+=1
                    x["search_rank_points"]+=max(0.0,13-rank)
            except Exception as e:
                errors.append({"trend":trend,"query":query,"error":repr(e)})
            time.sleep(0.25)
        rows=list(seen.values())
        for x in rows:
            # Discovery relevance only. This is NOT evidence of economic capture.
            x["radar_discovery_score"]=round(
                10.0*x["search_hits"] + 0.5*x["search_rank_points"],2
            )
        rows.sort(key=lambda x:(x["search_hits"],x["radar_discovery_score"]),reverse=True)
        by_trend[trend]=rows[:20]

    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at":now.isoformat(),
        "method":"public listed-company search challengers; radar-only; never auto-PROVEN",
        "rule":"A discovered company may enter the radar ranking as UNPROVEN but cannot become GREEN or receive capital until economic transmission and company capture are explicitly proven.",
        "trends":by_trend,
        "errors":errors,
        "query_urls":urls
    },indent=2),encoding="utf-8")
    print(json.dumps({
        "generated_at":now.isoformat(),
        "trends":{k:len(v) for k,v in by_trend.items()},
        "errors":len(errors)
    }))

if __name__=="__main__":
    main()
