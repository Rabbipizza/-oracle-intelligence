#!/usr/bin/env python3
"""ORACLE upstream science collector: arXiv Atom API -> normalized snapshots.
Fetches enough history for discovery baselines and deduplicates downstream by arXiv ID.
"""
import json,os,time,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone
from pathlib import Path
OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA=os.environ.get("ORACLE_USER_AGENT","Mozilla/5.0 ORACLE-Research/1.0")
NS={"a":"http://www.w3.org/2005/Atom"}

def collect(query,max_results=300):
    papers=[]
    page=100
    for start in range(0,max_results,page):
        n=min(page,max_results-start)
        params=urllib.parse.urlencode({"search_query":query,"start":start,"max_results":n,"sortBy":"submittedDate","sortOrder":"descending"})
        url="https://export.arxiv.org/api/query?"+params
        req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
        try:\n            with urllib.request.urlopen(req,timeout=45) as r: root=ET.fromstring(r.read())\n        except Exception as e:\n            print("WARN arXiv page failed",query,start,repr(e))\n            break
        entries=root.findall("a:entry",NS)
        for e in entries:
            papers.append({"id":e.findtext("a:id",default="",namespaces=NS),"title":" ".join(e.findtext("a:title",default="",namespaces=NS).split()),"published":e.findtext("a:published",default="",namespaces=NS),"updated":e.findtext("a:updated",default="",namespaces=NS),"summary":" ".join(e.findtext("a:summary",default="",namespaces=NS).split()),"authors":[x.findtext("a:name",default="",namespaces=NS) for x in e.findall("a:author",NS)],"categories":[x.attrib.get("term") for x in e.findall("a:category",NS)]})
        if len(entries)<n: break
        time.sleep(3)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    obj={"meta":{"family":"science","source":"arXiv","primary":True,"peer_reviewed":"unknown","query":query,"fetched_at":stamp},"data":papers}
    safe="".join(x if x.isalnum() else "_" for x in query)[:60]
    p=OUT/f"arxiv_{safe}_{stamp}.json"; p.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    return str(p),len(papers)

if __name__=="__main__":
    queries=[q.strip() for q in os.environ.get("ORACLE_ARXIV_QUERIES","cat:cs.AI,cat:cs.RO,cat:cs.LG,cat:cs.CV").split(",") if q.strip()]
    created=[]
    for q in queries:
        p,n=collect(q,int(os.environ.get("ORACLE_ARXIV_MAX_RESULTS","300"))); created.append({"path":p,"papers":n})
    print(json.dumps({"created":created}))
