#!/usr/bin/env python3
"""ORACLE open scholarly sources. Independent metadata families; failures are explicit."""
import json,os,urllib.parse,urllib.request
from datetime import datetime,timezone,timedelta
from pathlib import Path
OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="ORACLE-Research/2.0 (+https://github.com/Rabbipizza/-oracle-intelligence)"

def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/json"})
    with urllib.request.urlopen(req,timeout=45) as r:return json.load(r)
def save(name,source,data,url):
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p=OUT/f"{name}_{stamp}.json"; p.write_text(json.dumps({"meta":{"family":"science","source":source,"primary":False,"url":url,"fetched_at":stamp},"data":data},indent=2),encoding="utf-8"); return str(p)

def crossref(days=110,rows=1000):
    end=datetime.now(timezone.utc).date(); start=end-timedelta(days=days)
    params={"filter":f"from-created-date:{start},until-created-date:{end}","rows":rows,"select":"DOI,title,created,published,subject,type,URL"}
    url="https://api.crossref.org/works?"+urllib.parse.urlencode(params)
    x=get(url); return save("crossref","Crossref",x.get("message",{}).get("items",[]),url)

def openalex(days=110,per_page=200):
    end=datetime.now(timezone.utc).date(); start=end-timedelta(days=days)
    params={"filter":f"from_publication_date:{start},to_publication_date:{end}","per-page":per_page,"sort":"publication_date:desc"}
    key=os.environ.get("OPENALEX_API_KEY"); 
    if key: params["api_key"]=key
    url="https://api.openalex.org/works?"+urllib.parse.urlencode(params)
    x=get(url); return save("openalex","OpenAlex",x.get("results",[]),url)

if __name__=="__main__":
    made=[]; errors=[]
    for name,fn in [("Crossref",crossref),("OpenAlex",openalex)]:
        try: made.append(fn())
        except Exception as e: errors.append({"source":name,"error":repr(e)})
    print(json.dumps({"created":made,"errors":errors}))
