#!/usr/bin/env python3
"""ORACLE source ingestion — normalized snapshots for downstream analysis."""
import json, os, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("data/source_snapshots")
OUT.mkdir(parents=True, exist_ok=True)
UA=os.environ.get("ORACLE_USER_AGENT","ORACLE-research")

def request_json(url, data=None):
    headers={"User-Agent":UA,"Accept":"application/json"}
    if data is not None: headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,headers=headers)
    with urllib.request.urlopen(req,timeout=30) as res:
        return json.load(res)

def write_snapshot(name,family,source,url,payload,primary=True):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    obj={"meta":{"family":family,"source":source,"primary":primary,"url":url,"fetched_at":stamp},"data":payload}
    path=OUT/(name+"_"+stamp+".json")
    path.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    return str(path)

def sec_companyfacts(cik):
    cik=str(cik).zfill(10)
    url="https://data.sec.gov/api/xbrl/companyfacts/CIK"+cik+".json"
    return write_snapshot("sec_"+cik,"company","SEC EDGAR",url,request_json(url))

def usaspending(keyword,start_date="2026-01-01",end_date="2026-12-31"):
    url="https://api.usaspending.gov/api/v2/search/spending_by_award/"
    query={"filters":{"time_period":[{"start_date":start_date,"end_date":end_date}],"keywords":[keyword],"award_type_codes":["A","B","C","D"]},"fields":["Award ID","Recipient Name","Award Amount","Description"],"page":1,"limit":100}
    payload=request_json(url,json.dumps(query).encode("utf-8"))
    return write_snapshot("usaspending","industry_contracts","USAspending",url,payload)

def main():
    made=[]
    for cik in filter(None,(x.strip() for x in os.environ.get("ORACLE_SEC_CIKS","").split(","))):
        made.append(sec_companyfacts(cik))
    for kw in filter(None,(x.strip() for x in os.environ.get("ORACLE_USASPENDING_KEYWORDS","").split(","))):
        made.append(usaspending(kw))
    print(json.dumps({"created":made,"count":len(made)}))

if __name__=="__main__":
    main()
