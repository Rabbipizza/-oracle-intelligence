#!/usr/bin/env python3
"""ORACLE arXiv collector. Fetch recent category streams, filter dates locally, dedupe versions."""
import json, os, re, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="Mozilla/5.0 (compatible; ORACLE-Research/3.1; +https://github.com/Rabbipizza/-oracle-intelligence)"
NS={"a":"http://www.w3.org/2005/Atom"}
CATS=[q.strip() for q in os.environ.get("ORACLE_ARXIV_QUERIES","cat:cs.AI,cat:cs.RO,cat:cs.LG,cat:cs.CV").split(",") if q.strip()]
LOOKBACK_DAYS=int(os.environ.get("ORACLE_ARXIV_LOOKBACK_DAYS","110"))
MAX_PER_CATEGORY=int(os.environ.get("ORACLE_ARXIV_MAX_PER_CATEGORY","1000"))

def atom_fetch(search_query,max_results):
    params=urllib.parse.urlencode({"search_query":search_query,"start":0,"max_results":max_results,"sortBy":"submittedDate","sortOrder":"descending"})
    url="https://export.arxiv.org/api/query?"+params
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
    with urllib.request.urlopen(req,timeout=75) as r:
        root=ET.fromstring(r.read())
    rows=[]
    for e in root.findall("a:entry",NS):
        rows.append({
            "id":e.findtext("a:id",default="",namespaces=NS),
            "title":" ".join(e.findtext("a:title",default="",namespaces=NS).split()),
            "published":e.findtext("a:published",default="",namespaces=NS),
            "updated":e.findtext("a:updated",default="",namespaces=NS),
            "summary":" ".join(e.findtext("a:summary",default="",namespaces=NS).split()),
            "authors":[x.findtext("a:name",default="",namespaces=NS) for x in e.findall("a:author",NS)],
            "categories":[x.attrib.get("term") for x in e.findall("a:category",NS)]
        })
    return rows,url

def main():
    now=datetime.now(timezone.utc); cutoff=now-timedelta(days=LOOKBACK_DAYS)
    all_rows={}; queries=[]; errors=[]
    for cat in CATS:
        try:
            rows,url=atom_fetch(cat,MAX_PER_CATEGORY)
            kept=0
            for d in rows:
                try: dt=datetime.fromisoformat((d.get("published") or "").replace("Z","+00:00"))
                except Exception: continue
                if dt<cutoff: continue
                raw=d.get("id") or ""
                m=re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?",raw)
                key=m.group(1) if m else raw
                if key:
                    all_rows[key]=d; kept+=1
            queries.append({"category":cat,"fetched":len(rows),"kept":kept,"url":url})
        except Exception as e:
            errors.append({"category":cat,"error":repr(e)})
        time.sleep(3)
    stamp=now.strftime("%Y%m%dT%H%M%SZ")
    obj={"meta":{"family":"science","source":"arXiv","primary":True,"peer_reviewed":"unknown","fetched_at":stamp,"lookback_days":LOOKBACK_DAYS,"categories":CATS,"errors":errors},"queries":queries,"data":list(all_rows.values())}
    p=OUT/f"arxiv_backfill_{stamp}.json"; p.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    print(json.dumps({"path":str(p),"unique_papers":len(all_rows),"categories_ok":len(queries),"errors":errors[:3]}))
    if not all_rows:
        print("WARN: arXiv unavailable or empty; continuing with redundant scholarly sources")

if __name__=="__main__": main()
