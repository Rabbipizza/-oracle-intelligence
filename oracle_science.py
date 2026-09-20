#!/usr/bin/env python3
"""ORACLE arXiv collector with explicit date-window backfill."""
import json,os,time,re,urllib.parse,urllib.request,xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from pathlib import Path
OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="Mozilla/5.0 (compatible; ORACLE-Research/1.0; +https://github.com/Rabbipizza/-oracle-intelligence)"
NS={"a":"http://www.w3.org/2005/Atom"}
CATS=[q.strip() for q in os.environ.get("ORACLE_ARXIV_QUERIES","cat:cs.AI,cat:cs.RO,cat:cs.LG,cat:cs.CV").split(",") if q.strip()]
WINDOW_DAYS=int(os.environ.get("ORACLE_ARXIV_WINDOW_DAYS","7"))
LOOKBACK_DAYS=int(os.environ.get("ORACLE_ARXIV_LOOKBACK_DAYS","110"))
MAX_PER_WINDOW=int(os.environ.get("ORACLE_ARXIV_MAX_PER_WINDOW","200"))

def atom_fetch(search_query,max_results):
    params=urllib.parse.urlencode({"search_query":search_query,"start":0,"max_results":max_results,"sortBy":"submittedDate","sortOrder":"descending"})
    url="https://export.arxiv.org/api/query?"+params
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"application/atom+xml,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req,timeout=60) as r: root=ET.fromstring(r.read())
    except Exception as e:
        print("WARN",search_query,repr(e)); return [],url,str(e)
    rows=[]
    for e in root.findall("a:entry",NS):
        rows.append({"id":e.findtext("a:id",default="",namespaces=NS),"title":" ".join(e.findtext("a:title",default="",namespaces=NS).split()),"published":e.findtext("a:published",default="",namespaces=NS),"updated":e.findtext("a:updated",default="",namespaces=NS),"summary":" ".join(e.findtext("a:summary",default="",namespaces=NS).split()),"authors":[x.findtext("a:name",default="",namespaces=NS) for x in e.findall("a:author",NS)],"categories":[x.attrib.get("term") for x in e.findall("a:category",NS)]})
    return rows,url,None

def main():
    now=datetime.now(timezone.utc); all_rows={}; windows=[]; failures=0
    for cat in CATS:
        end=now
        while end>now-timedelta(days=LOOKBACK_DAYS):
            start=max(now-timedelta(days=LOOKBACK_DAYS),end-timedelta(days=WINDOW_DAYS))
            # arXiv submittedDate is UTC YYYYMMDDHHMMSS.
            q=f"{cat} AND submittedDate:[{start.strftime('%Y%m%d%H%M')} TO {end.strftime('%Y%m%d%H%M')}]"
            rows,url,err=atom_fetch(q,MAX_PER_WINDOW)
            windows.append({"category":cat,"start":start.isoformat(),"end":end.isoformat(),"count":len(rows),"error":err})
            failures+=bool(err)
            for d in rows:
                raw=d.get("id") or ""
                m=re.search(r"(\\d{4}\\.\\d{4,5})(?:v\\d+)?",raw)
                key=m.group(1) if m else raw
                if key: all_rows[key]=d
            end=start-timedelta(seconds=1); time.sleep(3)
    stamp=now.strftime("%Y%m%dT%H%M%SZ")
    obj={"meta":{"family":"science","source":"arXiv","primary":True,"peer_reviewed":"unknown","fetched_at":stamp,"lookback_days":LOOKBACK_DAYS,"window_days":WINDOW_DAYS,"categories":CATS,"failed_windows":failures},"windows":windows,"data":list(all_rows.values())}
    p=OUT/f"arxiv_backfill_{stamp}.json"; p.write_text(json.dumps(obj,indent=2),encoding="utf-8")
    print(json.dumps({"path":str(p),"unique_papers":len(all_rows),"windows":len(windows),"failed_windows":failures}))
    if failures == len(windows) or not all_rows:
        raise SystemExit("FATAL: arXiv historical backfill returned no usable papers")
if __name__=="__main__": main()
