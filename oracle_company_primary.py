#!/usr/bin/env python3
"""ORACLE primary-company evidence collector.

Fetches recent SEC submissions and selected filing documents for the most
relevant US-listed incumbents/challengers. Output is primary company evidence
for the evidence-expansion layer. No investment status is assigned here.
"""
import html, json, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="ORACLE-Research/4.1 guillaume.edition@gmail.com"

FORMS={"10-K","10-Q","8-K","20-F","6-K"}
MAX_COMPANIES=35
MAX_FILINGS_PER_COMPANY=4
MAX_DOC_CHARS=180000

def get_bytes(url,accept="application/json,text/html,*/*",timeout=35,retries=2):
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":accept})
            with urllib.request.urlopen(req,timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last=e
            if i<retries: time.sleep(1.5*(i+1))
    raise last

def get_json(url):
    return json.loads(get_bytes(url,"application/json,*/*").decode("utf-8","replace"))

def clean_html(raw):
    s=raw.decode("utf-8","replace")
    s=re.sub(r"(?is)<script.*?</script>"," ",s)
    s=re.sub(r"(?is)<style.*?</style>"," ",s)
    s=re.sub(r"(?is)<[^>]+>"," ",s)
    s=html.unescape(s)
    s=re.sub(r"\s+"," ",s).strip()
    return s[:MAX_DOC_CHARS]

def save(name,data,extra=None):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta={
        "family":"company",
        "source":"SEC EDGAR filings",
        "primary":True,
        "fetched_at":stamp
    }
    if extra: meta.update(extra)
    p=OUT/f"{name}_{stamp}.json"
    p.write_text(json.dumps({"meta":meta,"data":data},indent=2),encoding="utf-8")
    return str(p)

def relevant_tickers():
    scores={}
    def add(ticker,score,name=None):
        if not ticker: return
        t=str(ticker).upper()
        # SEC mapping is US-symbol oriented; skip obvious non-US suffixed symbols/ETFs.
        if any(x in t for x in [".","=","^"]): return
        scores[t]=max(scores.get(t,0),score)

    try:
        r=json.loads(Path("research-universe.json").read_text())
        for tr in r.get("trends",{}).values():
            for i,row in enumerate(tr.get("companies",[])[:20],1):
                if row: add(row[0],100-i)
    except Exception: pass

    try:
        c=json.loads(Path("data/company-challengers.json").read_text())
        for rows in (c.get("trends",{}) or {}).values():
            for i,row in enumerate(rows[:10],1):
                add(row.get("ticker"),85-i)
    except Exception: pass

    try:
        d=json.loads(Path("decision-state.json").read_text())
        for t,sc in (d.get("scores",{}) or {}).items():
            bonus=0
            if sc.get("evidence_status")=="PROVEN": bonus+=80
            bonus+=float(sc.get("structural_early_bird") or 0)*0.25
            bonus+=float(sc.get("entry_score") or 0)*0.15
            add(t,bonus)
    except Exception: pass

    return [t for t,_ in sorted(scores.items(),key=lambda kv:kv[1],reverse=True)[:MAX_COMPANIES]]

def ticker_map():
    url="https://www.sec.gov/files/company_tickers.json"
    obj=get_json(url)
    out={}
    for x in obj.values():
        t=str(x.get("ticker") or "").upper()
        if t:
            out[t]={"cik":str(x.get("cik_str")).zfill(10),"title":x.get("title")}
    return out,url

def recent_filings(cik):
    url=f"https://data.sec.gov/submissions/CIK{cik}.json"
    x=get_json(url)
    rec=((x.get("filings") or {}).get("recent") or {})
    rows=[]
    forms=rec.get("form") or []
    n=len(forms)
    for i in range(n):
        form=forms[i]
        if form not in FORMS: continue
        row={}
        for k,v in rec.items():
            if isinstance(v,list) and i<len(v): row[k]=v[i]
        rows.append(row)
        if len(rows)>=MAX_FILINGS_PER_COMPANY: break
    return rows,url,x.get("name")

def filing_doc(cik,row):
    acc=str(row.get("accessionNumber") or "")
    primary=row.get("primaryDocument")
    if not acc or not primary: return None
    acc_no=acc.replace("-","")
    cik_int=str(int(cik))
    url=f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_no}/{primary}"
    raw=get_bytes(url,"text/html,text/plain,*/*",timeout=40,retries=1)
    return {
        "accessionNumber":acc,
        "filingDate":row.get("filingDate"),
        "reportDate":row.get("reportDate"),
        "form":row.get("form"),
        "primaryDocument":primary,
        "url":url,
        "text":clean_html(raw)
    }

def main():
    tickers=relevant_tickers()
    tmap,map_url=ticker_map()
    made=[]; errors=[]; records=[]; covered=[]
    cutoff=(datetime.now(timezone.utc)-timedelta(days=550)).date().isoformat()

    for ticker in tickers:
        info=tmap.get(ticker)
        if not info: continue
        cik=info["cik"]
        try:
            filings,sub_url,issuer=recent_filings(cik)
            docs=[]
            for row in filings:
                if row.get("filingDate") and row.get("filingDate")<cutoff:
                    continue
                try:
                    d=filing_doc(cik,row)
                    if d: docs.append(d)
                except Exception as e:
                    errors.append({"ticker":ticker,"accession":row.get("accessionNumber"),"error":repr(e)})
                time.sleep(0.15)
            if docs:
                for d in docs:
                    records.append({
                        "ticker":ticker,
                        "company":issuer or info.get("title"),
                        "cik":cik,
                        "submissions_url":sub_url,
                        **d
                    })
                covered.append(ticker)
        except Exception as e:
            errors.append({"ticker":ticker,"cik":cik,"error":repr(e)})
        time.sleep(0.15)

    if records:
        made.append(save("sec_primary_filings",records,{"ticker_map_url":map_url,"tickers":covered}))
    print(json.dumps({
        "requested":len(tickers),"covered":len(covered),"tickers":covered,
        "filing_documents":len(records),
        "created":made,"errors":errors[:12]
    }))

if __name__=="__main__":
    main()
