#!/usr/bin/env python3
"""Build ORACLE semantic evidence dossiers.

This module replaces exact-phrase gating with concept-level evidence expansion.
It does NOT auto-promote a company to PROVEN. Explicit primary economic evidence
remains required in economic-evidence.json.
"""
import hashlib, json, re
from pathlib import Path
from datetime import datetime, timezone

SNAP=Path("data/source_snapshots")
OUT=Path("data/evidence-dossiers.json")

def load(path,default=None):
    try: return json.loads(Path(path).read_text())
    except Exception: return {} if default is None else default

def norm(s):
    return " ".join(re.findall(r"[a-z0-9-]{2,}",(s or "").lower()))

def strings(x,depth=0):
    if depth>5: return []
    if isinstance(x,str): return [x]
    if isinstance(x,list):
        out=[]
        for v in x[:200]: out.extend(strings(v,depth+1))
        return out
    if isinstance(x,dict):
        out=[]
        for k,v in list(x.items())[:200]:
            if str(k).lower() in {"url","html_url","api_url"}: continue
            out.extend(strings(v,depth+1))
        return out
    return []

def records(data):
    if isinstance(data,list): return data
    if isinstance(data,dict):
        for k in ("results","items","awards","data","notices"):
            if isinstance(data.get(k),list): return data[k]
        return [data]
    return []

def origin(source,r,text):
    if isinstance(r,dict):
        for k in ("DOI","doi","id","Award ID","award_id","accessionNumber","filingDate","title","publication-number"):
            if r.get(k): return f"{source}:{r.get(k)}"
    return f"{source}:{hashlib.sha1(text.encode('utf-8','ignore')).hexdigest()[:16]}"

def load_snapshot_rows():
    out=[]
    for p in SNAP.glob("*.json"):
        try:
            x=json.loads(p.read_text())
            m=x.get("meta",{})
            for r in records(x.get("data")):
                text=norm(" ".join(strings(r)))
                if not text: continue
                out.append({
                    "family":m.get("family"),
                    "source":m.get("source"),
                    "primary":bool(m.get("primary")),
                    "origin":origin(m.get("source"),r,text),
                    "text":text,
                    "file":str(p)
                })
        except Exception:
            pass
    return out

def any_phrase(text,phrases):
    return [p for p in phrases if norm(p) and norm(p) in text]

def company_catalog():
    research=load("research-universe.json")
    challengers=load("data/company-challengers.json")
    explicit=load("economic-evidence.json")
    out={}
    for trend,tr in research.get("trends",{}).items():
        for row in tr.get("companies",[]):
            if not row: continue
            t,name,role,proof=(row+[None,None,None,None])[:4]
            out[t]={"ticker":t,"name":name,"trend":trend,"role":role,"legacy_proof":proof,"origin":"RESEARCH_UNIVERSE"}
    for trend,rows in (challengers.get("trends",{}) or {}).items():
        for r in rows or []:
            t=r.get("ticker")
            if not t or t in out: continue
            out[t]={"ticker":t,"name":r.get("name") or t,"trend":trend,"role":"Dynamic challenger","legacy_proof":"UNPROVEN","origin":"DYNAMIC_CHALLENGER"}
    for t,e in (explicit.get("companies",{}) or {}).items():
        if t not in out:
            out[t]={"ticker":t,"name":t,"trend":e.get("trend"),"role":e.get("role"),"legacy_proof":"UNPROVEN","origin":"EXPLICIT_EVIDENCE"}
    return out

rows=load_snapshot_rows()
ontology=load("evidence-ontology.json")
discovery=load("data/discovery-candidates.json")
explicit=load("economic-evidence.json")
companies=company_catalog()

concepts={}
concept_record_cache={}
for key,cfg in (ontology.get("concepts",{}) or {}).items():
    aliases=[norm(x) for x in cfg.get("aliases",[]) if norm(x)]
    econ=[norm(x) for x in cfg.get("economic_terms",[]) if norm(x)]
    matched=[]
    for r in rows:
        ah=any_phrase(r["text"],aliases)
        if ah:
            matched.append((r,ah,any_phrase(r["text"],econ)))
    uniq={r["origin"]:(r,ah,eh) for r,ah,eh in matched}
    vals=list(uniq.values())
    concept_record_cache[key]=vals
    fam=sorted({r["family"] for r,_,_ in vals if r.get("family")})
    src=sorted({r["source"] for r,_,_ in vals if r.get("source")})
    primary=[r for r,_,_ in vals if r.get("primary")]
    economic=[r for r,_,eh in vals if eh and r.get("family")!="science"]
    science=[r for r,_,_ in vals if r.get("family")=="science"]
    score=min(100.0,
        20.0*min(len(fam),4) +
        8.0*min(len(src),4) +
        12.0*(1 if primary else 0) +
        12.0*(1 if economic else 0)
    )
    if len(vals)==0: maturity="DISCOVERED"
    elif len(fam)>=2: maturity="CORROBORATED"
    else: maturity="DISCOVERED"
    if economic: maturity="ECONOMIC_LINK"
    concepts[key]={
        "label":cfg.get("label"),"aliases":aliases,
        "evidence_score":round(score,1),
        "maturity":maturity,
        "family_count":len(fam),"families":fam,
        "source_count":len(src),"sources":src,
        "matched_origin_count":len(vals),
        "primary_origin_count":len({r["origin"] for r in primary}),
        "economic_origin_count":len({r["origin"] for r in economic}),
        "science_origin_count":len({r["origin"] for r in science})
    }

company_dossiers={}
for ticker,meta in companies.items():
    trend=meta.get("trend")
    cc=(ontology.get("concepts",{}) or {}).get(trend,{})
    aliases=[norm(x) for x in cc.get("aliases",[]) if norm(x)]
    econ=[norm(x) for x in cc.get("economic_terms",[]) if norm(x)]
    company_name=norm(meta.get("name") or "")
    ticker_norm=norm(ticker)
    # Avoid false positives from short ticker symbols that are ordinary words
    # (BE, BA, CAT, ON, etc.). Prefer the full issuer name; only use ticker
    # matching when it is at least 4 characters long.
    names=[]
    if company_name and len(company_name)>=4:
        names.append(company_name)
    if ticker_norm and len(ticker_norm)>=4:
        names.append(ticker_norm)

    matches=[]
    # Only inspect records already semantically linked to this concept.
    # This changes complexity from companies × all records to
    # companies × concept-relevant records.
    for r,ah,eh in concept_record_cache.get(trend,[]):
        name_hit=any(re.search(r"(?<![a-z0-9])"+re.escape(n)+r"(?![a-z0-9])",r["text"]) for n in names)
        if not name_hit: continue
        matches.append((r,ah,eh))
    uniq={r["origin"]:(r,ah,eh) for r,ah,eh in matches}
    vals=list(uniq.values())
    fam=sorted({r["family"] for r,_,_ in vals if r.get("family")})
    prim=[r for r,_,_ in vals if r.get("primary")]
    # A company-capture record must link issuer + trend concept + economic
    # activity in a non-science primary source. Science-only co-mentions do not
    # constitute economic capture.
    econprim=[
        r for r,ah,eh in vals
        if r.get("primary")
        and r.get("family") in {"company","industry_contracts"}
        and ah and eh
    ]
    explicit_ev=(explicit.get("companies",{}) or {}).get(ticker)
    trend_score=(concepts.get(trend) or {}).get("evidence_score",0)
    non_science_fam={r["family"] for r,_,_ in vals if r.get("family") in {"company","industry_contracts"}}
    capture_score=min(100.0,
        15.0*min(len(fam),3) +
        15.0*min(len(non_science_fam),2) +
        30.0*(1 if econprim else 0) +
        40.0*(1 if explicit_ev and explicit_ev.get("status")=="PROVEN" else 0)
    )
    if explicit_ev and explicit_ev.get("status")=="PROVEN":
        maturity="PROVEN"
    elif econprim:
        maturity="COMPANY_CAPTURE"
    elif vals:
        maturity="ECONOMIC_LINK"
    else:
        maturity="CORROBORATED" if trend_score>=45 else "DISCOVERED"
    company_dossiers[ticker]={
        **meta,
        "maturity":maturity,
        "trend_evidence_score":trend_score,
        "company_capture_score":round(capture_score,1),
        "family_count":len(fam),"families":fam,
        "matched_origin_count":len(vals),
        "primary_origin_count":len({r["origin"] for r in prim}),
        "economic_primary_origin_count":len({r["origin"] for r in econprim}),
        "explicit_proven":bool(explicit_ev and explicit_ev.get("status")=="PROVEN"),
        "eligible_for_auto_promotion":False,
        "proof_requirement":"Explicit primary economic capture evidence remains required before PROVEN/GREEN."
    }

# Map discovery phrases to concepts by semantic vocabulary overlap.
mapped=[]
for c in discovery.get("candidates",[]) or []:
    term=norm(c.get("term",""))
    toks=set(term.split())
    best=None; best_score=0
    for key,cfg in (ontology.get("concepts",{}) or {}).items():
        for alias in cfg.get("aliases",[]):
            a=set(norm(alias).split())
            if not a: continue
            score=len(toks&a)/max(1,min(len(toks),len(a)))
            if term in norm(alias) or norm(alias) in term: score=max(score,0.9)
            if score>best_score:
                best_score=score; best=key
    if best and best_score>=0.5:
        mapped.append({
            "term":c.get("term"),"concept":best,
            "mapping_confidence":round(best_score,2),
            "discovery_score":c.get("discovery_score"),
            "acceleration":c.get("acceleration")
        })

OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "method":"semantic concept expansion + record-level origin dedupe + company-capture dossier",
    "maturity_scale":["DISCOVERED","CORROBORATED","ECONOMIC_LINK","COMPANY_CAPTURE","PROVEN"],
    "rule":"Semantic expansion can advance investigation maturity, but only explicit primary economic capture evidence can make a company PROVEN.",
    "concepts":concepts,
    "discovery_to_concepts":mapped,
    "companies":company_dossiers
},indent=2),encoding="utf-8")
print(json.dumps({
    "concepts":{k:v["maturity"] for k,v in concepts.items()},
    "mapped_discovery_terms":len(mapped),
    "companies":len(company_dossiers),
    "company_capture_candidates":sum(1 for v in company_dossiers.values() if v["maturity"]=="COMPANY_CAPTURE"),
    "proven":sum(1 for v in company_dossiers.values() if v["maturity"]=="PROVEN")
}))
