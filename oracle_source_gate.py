#!/usr/bin/env python3
"""ORACLE per-candidate Source Coverage Gate using record-level evidence."""
import hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone

CFG=json.loads(Path("source-gate.json").read_text())
SNAP=Path("data/source_snapshots")
DISC=Path("data/discovery-candidates.json")
OUT=Path("data/source-gate-status.json")

def norm(s):
    return " ".join(re.findall(r"[a-z0-9-]{2,}",(s or "").lower()))

def strings(x, depth=0):
    if depth>4:
        return []
    if isinstance(x,str):
        return [x]
    if isinstance(x,list):
        out=[]
        for v in x[:100]:
            out.extend(strings(v,depth+1))
        return out
    if isinstance(x,dict):
        out=[]
        for k,v in list(x.items())[:100]:
            if k.lower() in {"url","html_url","api_url"}:
                continue
            out.extend(strings(v,depth+1))
        return out
    return []

def record_list(data):
    if isinstance(data,list):
        return data
    if isinstance(data,dict):
        for key in ("results","items","awards","data"):
            v=data.get(key)
            if isinstance(v,list):
                return v
        return [data]
    return []

def origin_id(source,r,text):
    if isinstance(r,dict):
        for key in ("DOI","doi","id","Award ID","award_id","accessionNumber","accession_number","filingDate","title"):
            v=r.get(key)
            if v:
                return f"{source}:{v}"
    return f"{source}:{hashlib.sha1(text.encode('utf-8','ignore')).hexdigest()[:16]}"

def load_records():
    rows=[]
    for p in SNAP.glob("*.json"):
        try:
            x=json.loads(p.read_text())
            m=x.get("meta",{})
            family=m.get("family"); source=m.get("source"); primary=bool(m.get("primary"))
            for r in record_list(x.get("data")):
                text=norm(" ".join(strings(r)))
                if not text:
                    continue
                rows.append({
                    "family":family,"source":source,"primary":primary,
                    "origin":origin_id(source,r,text),"text":text,"file":str(p)
                })
        except Exception:
            continue
    return rows

rows=load_records()
g=CFG["gate"]
disc=json.loads(DISC.read_text()) if DISC.exists() else {"candidates":[]}
candidate_status=[]
for c in disc.get("candidates",[]):
    phrase=norm(c.get("term",""))
    if not phrase:
        continue
    matched=[r for r in rows if phrase in r["text"]]
    origins={}
    for r in matched:
        origins[r["origin"]]=r
    uniq=list(origins.values())
    fam=sorted({r["family"] for r in uniq if r["family"]})
    primary_origins=sorted({r["origin"] for r in uniq if r["primary"]})
    sources=sorted({r["source"] for r in uniq if r["source"]})
    coverage=len(fam)>=g["min_independent_families"] and len(primary_origins)>=g["min_primary_sources"]
    candidate_status.append({
        "term":c.get("term"),"families":fam,"family_count":len(fam),
        "sources":sources,"matched_origin_count":len(uniq),
        "primary_origin_count":len(primary_origins),
        "coverage_gate_pass":coverage,
        "economic_transmission":"REQUIRES_ANALYST_PROOF",
        "company_capture":"REQUIRES_ANALYST_PROOF",
        "trend_status":"PARTIAL" if coverage else "UNPROVEN"
    })

families=sorted({r["family"] for r in rows if r["family"]})
status={
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "discovery_quality":disc.get("quality"),
    "global_source_inventory":{
        "families":families,
        "family_count":len(families),
        "record_count":len(rows),
        "primary_origin_count":len({r["origin"] for r in rows if r["primary"]})
    },
    "candidate_gates":candidate_status,
    "rule":"Coverage is record-level and origin-deduplicated. A trend needs evidence in at least three independent families and one primary origin; economic transmission and company capture remain separate gates."
}
OUT.write_text(json.dumps(status,indent=2),encoding="utf-8")
print(json.dumps({"discovery_quality":status["discovery_quality"],"records":len(rows),"candidate_gates":len(candidate_status),"passing":sum(1 for x in candidate_status if x["coverage_gate_pass"])}))
