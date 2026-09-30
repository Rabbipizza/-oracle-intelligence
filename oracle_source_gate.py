#!/usr/bin/env python3
"""ORACLE per-candidate Source Coverage Gate using record-level evidence."""
import hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone

CFG=json.loads(Path("source-gate.json").read_text())
SNAP=Path("data/source_snapshots")
DISC=Path("data/discovery-candidates.json")
DOSSIERS=Path("data/evidence-dossiers.json")
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
dossiers=json.loads(DOSSIERS.read_text()) if DOSSIERS.exists() else {}
mapping={x.get("term"):x for x in dossiers.get("discovery_to_concepts",[]) or []}
concepts=dossiers.get("concepts",{}) or {}
candidate_status=[]
for c in disc.get("candidates",[]):
    phrase=norm(c.get("term",""))
    if not phrase:
        continue

    # Exact phrase evidence remains useful, but mapped canonical concepts may
    # aggregate semantically-equivalent vocabulary across independent sources.
    matched=[r for r in rows if phrase in r["text"]]
    origins={r["origin"]:r for r in matched}
    exact=list(origins.values())
    exact_fam={r["family"] for r in exact if r["family"]}
    exact_primary={r["origin"] for r in exact if r["primary"]}
    exact_sources={r["source"] for r in exact if r["source"]}

    mp=mapping.get(c.get("term")) or {}
    concept_key=mp.get("concept")
    cd=concepts.get(concept_key,{}) if concept_key else {}

    fam=sorted(set(exact_fam)|set(cd.get("families",[]) or []))
    sources=sorted(set(exact_sources)|set(cd.get("sources",[]) or []))
    primary_count=max(len(exact_primary),int(cd.get("primary_origin_count") or 0))
    economic_count=int(cd.get("economic_origin_count") or 0)
    matched_count=max(len(exact),int(cd.get("matched_origin_count") or 0))

    coverage=(
        len(fam)>=g["min_independent_families"] and
        primary_count>=g["min_primary_sources"] and
        economic_count>=1
    )

    maturity=cd.get("maturity") if concept_key else None
    if coverage:
        trend_status="ECONOMIC_LINK"
    elif maturity in {"ECONOMIC_LINK","CORROBORATED","DISCOVERED"}:
        trend_status=maturity
    else:
        trend_status="DISCOVERED" if matched_count else "UNPROVEN"

    candidate_status.append({
        "term":c.get("term"),
        "concept":concept_key,
        "concept_mapping_confidence":mp.get("mapping_confidence"),
        "families":fam,"family_count":len(fam),
        "sources":sources,"matched_origin_count":matched_count,
        "primary_origin_count":primary_count,
        "economic_origin_count":economic_count,
        "coverage_gate_pass":coverage,
        "economic_transmission":"EVIDENCE_PRESENT" if economic_count else "REQUIRES_EVIDENCE_EXPANSION",
        "company_capture":"REQUIRES_COMPANY_DOSSIER",
        "trend_status":trend_status
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
    "rule":"Coverage is concept-level and origin-deduplicated. Semantic aliases may combine equivalent vocabulary across sources. Full coverage still requires at least three independent families, one primary origin, and non-science economic evidence; company capture is a separate gate."
}
OUT.write_text(json.dumps(status,indent=2),encoding="utf-8")
print(json.dumps({"discovery_quality":status["discovery_quality"],"records":len(rows),"candidate_gates":len(candidate_status),"passing":sum(1 for x in candidate_status if x["coverage_gate_pass"])}))
