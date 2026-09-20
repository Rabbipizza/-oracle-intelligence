#!/usr/bin/env python3
"""ORACLE free/open macro + public-demand collectors. No paid data."""
import json,urllib.request,urllib.parse
from datetime import datetime,timezone
from pathlib import Path
OUT=Path("data/source_snapshots"); OUT.mkdir(parents=True,exist_ok=True)
UA="ORACLE-Research/2.0 (+https://github.com/Rabbipizza/-oracle-intelligence)"
def save(name,family,source,url,data,primary=True):
 s=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"); p=OUT/f"{name}_{s}.json"
 p.write_text(json.dumps({"meta":{"family":family,"source":source,"primary":primary,"url":url,"fetched_at":s},"data":data},indent=2),encoding="utf-8"); return str(p)
def req(url,data=None,headers=None):
 h={"User-Agent":UA,"Accept":"application/json"}; h.update(headers or {})
 if data is not None:h["Content-Type"]="application/json"
 with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h),timeout=45) as r:return json.load(r)
def bls():
 url="https://api.bls.gov/publicAPI/v2/timeseries/data/"
 series=["LNS14000000","CES0000000001","CUUR0000SA0"]
 return save("bls","macro","BLS",url,req(url,json.dumps({"seriesid":series}).encode()))
def ecb():
 url="https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?format=csvdata&lastNObservations=120"
 with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":UA}),timeout=45) as r: data=r.read().decode("utf-8","replace")
 return save("ecb","macro","ECB Data Portal",url,{"csv":data})
def ted():
 url="https://api.ted.europa.eu/v3/notices/search"
 body={"query":"publication-date >= 20260901","page":1,"limit":100}
 return save("ted","industry_contracts","TED EU procurement",url,req(url,json.dumps(body).encode()),True)
def main():
 made=[]; errors=[]
 for n,fn in [("BLS",bls),("ECB",ecb),("TED",ted)]:
  try:made.append(fn())
  except Exception as e:errors.append({"source":n,"error":repr(e)})
 print(json.dumps({"created":made,"errors":errors}))
if __name__=="__main__":main()
