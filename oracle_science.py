#!/usr/bin/env python3
"""ORACLE upstream science collector: arXiv Atom API -> normalized snapshots."""
import json, os, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA=os.environ.get("ORACLE_USER_AGENT","ORACLE-research")
NS={"a":"http://www.w3.org/2005/Atom"}

def collect(query,max_results=50):
    params=urllib.parse.urlencode({"search_query":query,"start":0,"max_results":max_results,"sortBy":"submittedDate","sortOrder":"descending"})
    url="https://export.arxiv.org/api/query?"+params
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    with urllib.request.urlopen(req,timeout=30) as r: root=ET.fromstring(r.read())
    papers=[]
    for e in root.findall("a:entry",NS):
        papers.append({"id":e.findtext("a:id",default="",namespaces=NS),"title":" ".join(e.findtext("a:title",default="",namespaces=NS).split()),"published":e.findtext("a:published",default="",namespaces=NS),"updated":e.findtext("a:updated",default="",namespaces=NS),"summary":" ".join(e.findtext("a:summary",default="",namespaces=NS).split()),"authors":[x.findtext("a:name",default="",namespaces=NS) for x in e.findall("a:author",NS)],"categories":[x.attrib.get("term") for x in e.findall("a:category",NS)]})
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    obj={"meta":{"family":"science","source":"arXiv","primary":True,"query":query,"url":url,"fetched_at":stamp},"data":papers}
    safe="".join(x if x.isalnum() else "_" for x in query)[:60]
    p=OUT/f"arxiv_{safe}_{stamp}.json"; p.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    return str(p)

if __name__=="__main__":
    queries=[q.strip() for q in os.environ.get("ORACLE_ARXIV_QUERIES","cat:cs.AI,cat:cs.RO,cat:cs.LG,cat:cs.CV").split(",") if q.strip()]
    print(json.dumps({"created":[collect(q) for q in queries]}))
