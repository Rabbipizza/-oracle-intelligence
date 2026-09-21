#!/usr/bin/env python3
"""ORACLE market data: free EOD prices from Yahoo chart endpoint + official ECB USD/CHF cross."""
import csv, io, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT=Path("data/market.json")
UA="Mozilla/5.0 ORACLE-Research/3.1"

def request_bytes(url, timeout=25, retries=2):
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url, headers={"User-Agent":UA,"Accept":"application/json,text/csv,*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last=e
            if i<retries: time.sleep(1.5*(i+1))
    raise last

def yahoo_prices(ticker, start, end):
    p1=int(datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc).timestamp())
    p2=int(datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc).timestamp())
    symbol=urllib.parse.quote(ticker,safe="")
    params=urllib.parse.urlencode({"period1":p1,"period2":p2,"interval":"1d","events":"history","includeAdjustedClose":"true"})
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}"
    obj=json.loads(request_bytes(url).decode("utf-8","replace"))
    result=((obj.get("chart") or {}).get("result") or [])
    if not result:
        err=(obj.get("chart") or {}).get("error")
        raise RuntimeError(f"no_yahoo_result:{err}")
    r=result[0]
    ts=r.get("timestamp") or []
    quote=(((r.get("indicators") or {}).get("quote") or [{}])[0])
    closes=quote.get("close") or []
    rows=[]
    for t,c in zip(ts,closes):
        if c is None: continue
        rows.append({"date":datetime.fromtimestamp(t,timezone.utc).date().isoformat(),"close":float(c)})
    if not rows: raise RuntimeError("no_price_rows")
    return rows,url

def ecb_series(currency, start):
    key=f"D.{currency}.EUR.SP00.A"
    url="https://data-api.ecb.europa.eu/service/data/EXR/"+key+"?"+urllib.parse.urlencode({"format":"csvdata","startPeriod":start.isoformat()})
    text=request_bytes(url).decode("utf-8","replace")
    out={}
    for r in csv.DictReader(io.StringIO(text)):
        try: out[r["TIME_PERIOD"]]=float(r["OBS_VALUE"])
        except Exception: continue
    if not out: raise RuntimeError("no_ecb_fx_rows")
    return out,url

def usd_chf(start):
    usd,u1=ecb_series("USD",start); chf,u2=ecb_series("CHF",start)
    rows=[]
    for d in sorted(set(usd)&set(chf)):
        if usd[d]: rows.append({"date":d,"chf_per_usd":chf[d]/usd[d]})
    if not rows: raise RuntimeError("no_usd_chf_cross")
    return rows,[u1,u2]

def universe_tickers():
    tickers={"QQQ","AAON","GEV"}
    try:
        x=json.loads(Path("research-universe.json").read_text())
        for tr in x.get("trends",{}).values():
            for row in tr.get("companies",[]):
                if row: tickers.add(str(row[0]))
    except Exception: pass
    return sorted(tickers)

def main():
    now=datetime.now(timezone.utc); start=(now-timedelta(days=75)).date(); end=now.date()
    out={"generated_at":now.isoformat(),"source":{"prices":"Yahoo Finance chart EOD","fx":"ECB Data Portal"},"prices":{},"fx_usd_chf":[],"errors":[]}
    try:
        out["fx_usd_chf"],out["fx_urls"]=usd_chf(start)
    except Exception as e:
        out["errors"].append({"kind":"fx","error":repr(e)})
    for ticker in universe_tickers():
        try:
            rows,url=yahoo_prices(ticker,start,end)
            out["prices"][ticker]={"url":url,"rows":rows}
        except Exception as e:
            out["errors"].append({"ticker":ticker,"error":repr(e)})
        time.sleep(0.08)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"tickers_ok":len(out["prices"]),"errors":len(out["errors"]),"fx_rows":len(out["fx_usd_chf"]),"sample_errors":out["errors"][:5]}))

if __name__=="__main__":
    main()
