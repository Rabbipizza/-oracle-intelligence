#!/usr/bin/env python3
"""ORACLE source enrichment — company primary data and procurement evidence."""
import json, os, re, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("data/source_snapshots")
OUT.mkdir(parents=True, exist_ok=True)
UA=os.environ.get("ORACLE_USER_AGENT","ORACLE-Research/3.0 (+https://github.com/Rabbipizza/-oracle-intelligence)")

def request_json(url, data=None, timeout=35, retries=2):
    headers={"User-Agent":UA,"Accept":"application/json"}
    if data is not None: headers["Content-Type"]="application/json"
    last=None
    for i in range(retries+1):
        try:
            req=urllib.request.Request(url,data=data,headers=headers)
            with urllib.request.urlopen(req,timeout=timeout) as res:
                return json.load(res)
        except Exception as e:
            last=e
            if i<retries: time.sleep(2*(i+1))
    raise last

def write_snapshot(name,family,source,url,payload,primary=True,extra=None):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta={"family":family,"source":source,"primary":primary,"url":url,"fetched_at":stamp}
    if extra: meta.update(extra)
    obj={"meta":meta,"data":payload}
    path=OUT/(name+"_"+stamp+".json")
    path.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    return str(path)

def sec_companyfacts(cik):
    cik=str(cik).zfill(10)
    url="https://data.sec.gov/api/xbrl/companyfacts/CIK"+cik+".json"
    return write_snapshot("sec_"+cik,"company","SEC EDGAR",url,request_json(url),True,{"cik":cik})

def usaspending(keyword,start_date=None,end_date=None):
    now=datetime.now(timezone.utc).date()
    if end_date is None: end_date=now.isoformat()
    if start_date is None: start_date=now.replace(month=1,day=1).isoformat()
    url="https://api.usaspending.gov/api/v2/search/spending_by_award/"
    query={"filters":{"time_period":[{"start_date":start_date,"end_date":end_date}],
                      "keywords":[keyword],"award_type_codes":["A","B","C","D"]},
           "fields":["Award ID","Recipient Name","Award Amount","Description"],
           "page":1,"limit":100}
    payload=request_json(url,json.dumps(query).encode("utf-8"))
    rows=payload.get("results",[]) if isinstance(payload,dict) else payload
    safe=re.sub(r"[^a-z0-9]+","_",keyword.lower()).strip("_")[:40] or "query"
    return write_snapshot("usaspending_"+safe,"industry_contracts","USAspending",url,rows,True,{"query":keyword})

def discovery_keywords(limit=8):
    env=[x.strip() for x in os.environ.get("ORACLE_USASPENDING_KEYWORDS","").split(",") if x.strip()]
    if env: return env[:limit]
    p=Path("data/discovery-candidates.json")
    if not p.exists(): return []
    try: data=json.loads(p.read_text())
    except Exception: return []
    bad={"large language","neural network","natural language","real world","same time","object detection","about god","reduces mean","mean absolute","upper bound","publicly available"}
    tech={"agent","agents","robot","robotics","llm","language","vision","action","autonomous","quantum","photonic","photonics","optical","energy","power","grid","battery","semiconductor","network","satellite","drone","uas","lidar","sensor","sensing","compute","chip","gpu","memory","cooling","nuclear","mineral","minerals","magnet","rare","copper","tungsten","laser","interconnect","wireless","cyber","manufacturing"}
    out=[]
    for row in data.get("candidates",[]):
        term=(row.get("term") or "").strip().lower()
        toks=set(re.findall(r"[a-z0-9-]+",term))
        if not term or term in bad: continue
        if row.get("recent_docs",0)<3: continue
        if any(x in term for x in ("github","https","chapter ","percentage points","psalms","cancer","education")): continue
        if not (toks & tech): continue
        out.append(term)
        if len(out)>=limit: break
    return out

def main():
    made=[]; errors=[]
    for cik in filter(None,(x.strip() for x in os.environ.get("ORACLE_SEC_CIKS","").split(","))):
        try: made.append(sec_companyfacts(cik))
        except Exception as e: errors.append({"source":"SEC","cik":cik,"error":repr(e)})
    kws=discovery_keywords()
    for kw in kws:
        try:
            made.append(usaspending(kw))
        except Exception as e:
            errors.append({"source":"USAspending","query":kw,"error":repr(e)})
        time.sleep(0.2)
    print(json.dumps({"created":made,"count":len(made),"dynamic_keywords":kws,"errors":errors}))

if __name__=="__main__":
    main()
