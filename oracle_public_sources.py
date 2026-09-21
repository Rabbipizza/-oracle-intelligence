#!/usr/bin/env python3
"""ORACLE free/open macro + procurement collectors. No paid data."""
import json, time, urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="ORACLE-Research/3.0 (+https://github.com/Rabbipizza/-oracle-intelligence)"

def save(name,family,source,url,data,primary=True):
    s=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p=OUT/f"{name}_{s}.json"
    p.write_text(json.dumps({"meta":{"family":family,"source":source,"primary":primary,"url":url,"fetched_at":s},"data":data},indent=2),encoding="utf-8")
    return str(p)

def req(url,data=None,headers=None,timeout=45,retries=2):
    h={"User-Agent":UA,"Accept":"application/json"}; h.update(headers or {})
    if data is not None: h["Content-Type"]="application/json"
    last=None
    for i in range(retries+1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h),timeout=timeout) as r:
                return json.load(r)
        except Exception as e:
            last=e
            if i<retries: time.sleep(2*(i+1))
    raise last

def bls():
    url="https://api.bls.gov/publicAPI/v2/timeseries/data/"
    year=datetime.now(timezone.utc).year
    body={"seriesid":["LNS14000000","CES0000000001","CUUR0000SA0"],"startyear":str(year-1),"endyear":str(year)}
    return save("bls","macro","BLS",url,req(url,json.dumps(body).encode(),timeout=25,retries=1))

def ecb():
    url="https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata&lastNObservations=120"
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=35) as r:
        data=r.read().decode("utf-8","replace")
    return save("ecb","macro","ECB Data Portal",url,{"csv":data})

def ted():
    url="https://api.ted.europa.eu/v3/notices/search"
    since=(datetime.now(timezone.utc)-timedelta(days=30)).strftime("%Y%m%d")
    body={
        "query":f"publication-date >= {since} SORT BY publication-date DESC",
        "fields":["publication-number","publication-date","notice-title","buyer-name","notice-type","classification-cpv"],
        "page":1,"limit":100,"scope":"ALL","checkQuerySyntax":False,"paginationMode":"PAGE_NUMBER","onlyLatestVersions":True
    }
    data=req(url,json.dumps(body).encode(),timeout=45,retries=1)
    notices=data.get("notices",[]) if isinstance(data,dict) else data
    return save("ted","industry_contracts","TED EU procurement",url,notices,True)

def main():
    made=[]; errors=[]
    for n,fn in [("BLS",bls),("ECB",ecb),("TED",ted)]:
        try: made.append(fn())
        except Exception as e: errors.append({"source":n,"error":repr(e)})
    print(json.dumps({"created":made,"errors":errors}))

if __name__=="__main__":
    main()
