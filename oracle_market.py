#!/usr/bin/env python3
"""ORACLE market data: free EOD prices from Yahoo chart endpoint + official ECB USD/CHF cross."""
import csv, io, json, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from oracle_data_quality import positive, iso_date, holdings, CASH_TICKERS

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
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                break  # A symbol 404 is not a transient rate-limit failure.
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
    meta=r.get("meta") or {}
    if str(meta.get("symbol", "")).upper() != ticker.upper():
        raise RuntimeError("provider_symbol_mismatch")
    if not meta.get("currency") or not meta.get("exchangeName"):
        raise RuntimeError("provider_identity_missing")
    if any(not positive(row["close"]) for row in rows):
        raise RuntimeError("invalid_provider_close")
    # A same-day chart candle can be intraday. Keep completed sessions only.
    now = datetime.now(timezone.utc)
    if now.hour < 22:
        rows = [row for row in rows if row["date"] < now.date().isoformat()]
    if not rows:
        raise RuntimeError("no_completed_price_rows")
    info={"currency":meta.get("currency"),"exchange":meta.get("exchangeName"),"symbol":meta.get("symbol")}
    return rows,url,info

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
    tickers={"QQQ"}
    for name in ("portfolio.json", "portfolio-simulated.json"):
        try:
            tickers.update(holdings(json.loads(Path(name).read_text())))
        except (OSError, ValueError): pass
    try:
        decision = json.loads(Path("decision-state.json").read_text())
        tickers.update(t for t, w in decision.get("target_allocation_pct", {}).items() if positive(w))
        tickers.update(t for t, s in decision.get("signals", {}).items() if s.get("signal") == "GREEN")
    except (OSError, ValueError): pass
    try:
        x=json.loads(Path("research-universe.json").read_text())
        for tr in x.get("trends",{}).values():
            for row in tr.get("companies",[]):
                if row: tickers.add(str(row[0]))
    except Exception: pass
    try:
        x=json.loads(Path("data/company-challengers.json").read_text())
        for rows in (x.get("trends",{}) or {}).values():
            for row in rows or []:
                t=row.get("ticker")
                if t: tickers.add(str(t))
    except Exception: pass
    return sorted(tickers - CASH_TICKERS)

def history_start(now):
    # Keep the baseline and every recorded entry after the rolling window moves on.
    starts=[(now-timedelta(days=110)).date()]
    for name in ("portfolio.json", "portfolio-simulated.json"):
        try:
            ledger=json.loads(Path(name).read_text())
            values=[ledger.get("baseline_date")]+[p.get("trade_date") for p in ledger.get("positions", [])]
            starts.extend(iso_date(v)-timedelta(days=7) for v in values if iso_date(v))
        except (OSError, ValueError): pass
    return min(starts)

def main():
    now=datetime.now(timezone.utc); start=history_start(now); end=now.date()
    out={"generated_at":now.isoformat(),"source":{"prices":"Yahoo Finance chart EOD","fx":"ECB Data Portal"},"prices":{},"fx_usd_chf":[],"errors":[],"data_quality":{}}
    try:
        out["fx_usd_chf"],out["fx_urls"]=usd_chf(start)
    except Exception as e:
        out["errors"].append({"kind":"fx","error":repr(e)})
    for ticker in universe_tickers():
        try:
            rows,url,info=yahoo_prices(ticker,start,end)
            out["prices"][ticker]={"url":url,**info,"rows":rows}
            out["data_quality"][ticker]={"status":"AVAILABLE","provider_symbol":info["symbol"],"price_date":rows[-1]["date"]}
        except Exception as e:
            error={"ticker":ticker,"provider":"Yahoo chart EOD","provider_symbol":ticker,"status":"DATA_UNAVAILABLE","observed_at":now.isoformat(),"error":repr(e)}
            if isinstance(e, urllib.error.HTTPError): error["http_status"]=e.code
            out["errors"].append(error)
            out["data_quality"][ticker]={"status":"DATA_UNAVAILABLE","price_date":None,"reason":repr(e)}
        time.sleep(0.08)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps({"tickers_ok":len(out["prices"]),"errors":len(out["errors"]),"fx_rows":len(out["fx_usd_chf"]),"sample_errors":out["errors"][:5]}))

if __name__=="__main__":
    main()
