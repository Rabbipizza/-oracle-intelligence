#!/usr/bin/env python3
"""ORACLE market data: free EOD prices from Stooq + official ECB USD/CHF cross."""
import csv, io, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT=Path("data/market.json")
UA="ORACLE-Research/3.0 (+https://github.com/Rabbipizza/-oracle-intelligence)"

def request_text(url, timeout=25):
    req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"text/csv,text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8","replace")

def stooq_symbol(ticker):
    t=ticker.strip()
    suffixes={".L":".uk",".AX":".au",".TO":".ca",".PA":".fr",".MI":".it"}
    for src,dst in suffixes.items():
        if t.endswith(src):
            return t[:-len(src)].lower()+dst
    return t.lower()+".us"

def stooq_prices(ticker, start, end):
    params=urllib.parse.urlencode({
        "s":stooq_symbol(ticker),
        "d1":start.strftime("%Y%m%d"),
        "d2":end.strftime("%Y%m%d"),
        "i":"d"
    })
    url="https://stooq.com/q/d/l/?"+params
    text=request_text(url)
    rows=[]
    for r in csv.DictReader(io.StringIO(text)):
        try:
            rows.append({"date":r["Date"],"close":float(r["Close"])})
        except Exception:
            continue
    if not rows:
        raise RuntimeError("no_price_rows")
    return rows,url

def ecb_series(currency, start):
    # EXR D.<currency>.EUR.SP00.A is currency units per EUR.
    key=f"D.{currency}.EUR.SP00.A"
    url="https://data-api.ecb.europa.eu/service/data/EXR/"+key+"?"+urllib.parse.urlencode({
        "format":"csvdata","startPeriod":start.isoformat()
    })
    text=request_text(url)
    out={}
    for r in csv.DictReader(io.StringIO(text)):
        try:
            out[r["TIME_PERIOD"]]=float(r["OBS_VALUE"])
        except Exception:
            continue
    if not out:
        raise RuntimeError("no_ecb_fx_rows")
    return out,url

def usd_chf(start):
    usd,u1=ecb_series("USD",start)
    chf,u2=ecb_series("CHF",start)
    rows=[]
    for d in sorted(set(usd)&set(chf)):
        if usd[d]:
            rows.append({"date":d,"chf_per_usd":chf[d]/usd[d]})
    if not rows:
        raise RuntimeError("no_usd_chf_cross")
    return rows,[u1,u2]

def universe_tickers():
    tickers={"QQQ","AAON","GEV"}
    try:
        x=json.loads(Path("research-universe.json").read_text())
        for tr in x.get("trends",{}).values():
            for row in tr.get("companies",[]):
                if row: tickers.add(str(row[0]))
    except Exception:
        pass
    return sorted(tickers)

def main():
    now=datetime.now(timezone.utc)
    start=(now-timedelta(days=75)).date()
    end=now.date()
    out={"generated_at":now.isoformat(),"source":{"prices":"Stooq EOD","fx":"ECB Data Portal"},"prices":{},"fx_usd_chf":[],"errors":[]}
    try:
        out["fx_usd_chf"],out["fx_urls"]=usd_chf(start)
    except Exception as e:
        out["errors"].append({"kind":"fx","error":repr(e)})
    for ticker in universe_tickers():
        try:
            rows,url=stooq_prices(ticker,start,end)
            out["prices"][ticker]={"url":url,"rows":rows}
        except Exception as e:
            out["errors"].append({"ticker":ticker,"error":repr(e)})
        time.sleep(0.12)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"tickers_ok":len(out["prices"]),"errors":len(out["errors"]),"fx_rows":len(out["fx_usd_chf"])}))

if __name__=="__main__":
    main()
