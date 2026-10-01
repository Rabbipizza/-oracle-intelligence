#!/usr/bin/env python3
"""ORACLE strict primary-company revalidation.

Promotes a COMPANY_CAPTURE dossier to PROVEN only when:
1) its canonical trend has at least one discovery candidate that passed the
   concept-level Source Coverage Gate;
2) company capture score >= 75;
3) at least two distinct recent SEC primary filings contain a trend alias and
   an economic-capture term in close textual proximity;
4) at least two distinct economic terms are observed across those filings.

Otherwise the company is only marked VALIDATION_READY / NEEDS_MORE_EVIDENCE.
Simulation/research only; this module never places orders.
"""
import json, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

SNAP=Path("data/source_snapshots")
OUT=Path("data/company-revalidation.json")
ECON=Path("economic-evidence.json")

MAX_AGE_DAYS=450
MIN_CAPTURE_SCORE=75
MIN_FILINGS=2
MIN_ECON_TERMS=2
WINDOW=420

def load(path,default=None):
    try: return json.loads(Path(path).read_text())
    except Exception: return {} if default is None else default

def norm(s):
    return " ".join(re.findall(r"[a-z0-9-]{2,}",(s or "").lower()))

def latest_sec_records():
    rows=[]
    for p in sorted(SNAP.glob("sec_primary_filings_*.json")):
        try:
            x=json.loads(p.read_text())
            for r in x.get("data",[]) or []:
                if isinstance(r,dict):
                    rows.append(r)
        except Exception:
            pass
    # Deduplicate filing accession across repeated snapshots.
    uniq={}
    for r in rows:
        key=(str(r.get("ticker") or "").upper(),str(r.get("accessionNumber") or r.get("url") or ""))
        if key[0] and key[1]:
            uniq[key]=r
    return list(uniq.values())

def strong_hits(text,aliases,econ_terms):
    t=norm(text)
    hits=[]
    for alias in aliases:
        a=norm(alias)
        if len(a)<4: continue
        for m in re.finditer(re.escape(a),t):
            lo=max(0,m.start()-WINDOW); hi=min(len(t),m.end()+WINDOW)
            w=t[lo:hi]
            es=sorted({e for e in econ_terms if norm(e) and norm(e) in w})
            if es:
                hits.append({"alias":a,"economic_terms":es})
    return hits

dossiers=load("data/evidence-dossiers.json")
gate=load("data/source-gate-status.json")
ontology=load("evidence-ontology.json")
economic=load(ECON,{"version":1,"companies":{}})
if "companies" not in economic: economic["companies"]={}

passed_concepts={
    x.get("concept") for x in gate.get("candidate_gates",[]) or []
    if x.get("coverage_gate_pass") and x.get("concept")
}

sec=latest_sec_records()
by_ticker={}
for r in sec:
    by_ticker.setdefault(str(r.get("ticker") or "").upper(),[]).append(r)

cutoff=(datetime.now(timezone.utc)-timedelta(days=MAX_AGE_DAYS)).date().isoformat()
results=[]
promoted=[]

for ticker,d in (dossiers.get("companies",{}) or {}).items():
    if d.get("maturity")!="COMPANY_CAPTURE":
        continue
    trend=d.get("trend")
    score=float(d.get("company_capture_score") or 0)
    cfg=(ontology.get("concepts",{}) or {}).get(trend,{})
    aliases=cfg.get("aliases",[]) or []
    econ_terms=cfg.get("economic_terms",[]) or []

    filing_hits=[]
    all_terms=set()
    for r in by_ticker.get(str(ticker).upper(),[]):
        fd=str(r.get("filingDate") or "")
        if fd and fd<cutoff: continue
        hits=strong_hits(r.get("text") or "",aliases,econ_terms)
        if not hits: continue
        terms=sorted({e for h in hits for e in h["economic_terms"]})
        all_terms.update(terms)
        filing_hits.append({
            "accessionNumber":r.get("accessionNumber"),
            "filingDate":r.get("filingDate"),
            "form":r.get("form"),
            "url":r.get("url"),
            "matched_aliases":sorted({h["alias"] for h in hits})[:8],
            "economic_terms":terms[:12]
        })

    distinct={x.get("accessionNumber") or x.get("url"):x for x in filing_hits}
    filing_hits=list(distinct.values())
    trend_pass=trend in passed_concepts
    strict_pass=(
        trend_pass and
        score>=MIN_CAPTURE_SCORE and
        len(filing_hits)>=MIN_FILINGS and
        len(all_terms)>=MIN_ECON_TERMS
    )

    if strict_pass:
        status="PROVEN"
        promoted.append(ticker)
        prev=economic["companies"].get(ticker,{})
        economic["companies"][ticker]={
            **prev,
            "status":"PROVEN",
            "trend":trend,
            "role":d.get("role") or prev.get("role"),
            "evidence_date":max((x.get("filingDate") or "" for x in filing_hits),default=datetime.now(timezone.utc).date().isoformat()),
            "primary_source":"SEC EDGAR multi-filing automatic revalidation",
            "source_url":filing_hits[0].get("url") if filing_hits else prev.get("source_url"),
            "validation_method":"ORACLE_STRICT_PRIMARY_REVALIDATION_V1",
            "validation_filing_count":len(filing_hits),
            "validation_economic_terms":sorted(all_terms),
            "validation_trend_gate_pass":True,
            "invalidation":prev.get("invalidation") or [
                "loss of explicit trend-linked primary evidence",
                "material deterioration in orders/backlog/revenue/capacity linked to the thesis",
                "trend Source Coverage Gate no longer passes"
            ]
        }
    elif score>=MIN_CAPTURE_SCORE and len(filing_hits)>=1:
        status="VALIDATION_READY"
    else:
        status="NEEDS_MORE_EVIDENCE"

    results.append({
        "ticker":ticker,
        "trend":trend,
        "company_capture_score":score,
        "trend_gate_pass":trend_pass,
        "recent_primary_filing_hits":len(filing_hits),
        "distinct_economic_terms":sorted(all_terms),
        "status":status,
        "promotion_rule":{
            "min_capture_score":MIN_CAPTURE_SCORE,
            "min_filings":MIN_FILINGS,
            "min_economic_terms":MIN_ECON_TERMS,
            "max_age_days":MAX_AGE_DAYS
        },
        "filings":filing_hits[:6]
    })

economic["as_of"]=datetime.now(timezone.utc).date().isoformat()
economic["rule"]="Fresh GREEN requires explicit economic evidence. Automatic PROVEN status is allowed only through ORACLE_STRICT_PRIMARY_REVALIDATION_V1 or pre-existing explicit primary evidence."
ECON.write_text(json.dumps(economic,indent=2),encoding="utf-8")

OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "method":"ORACLE_STRICT_PRIMARY_REVALIDATION_V1",
    "passed_concepts":sorted(passed_concepts),
    "promoted":promoted,
    "results":sorted(results,key=lambda x:(x["status"]=="PROVEN",x["company_capture_score"],x["recent_primary_filing_hits"]),reverse=True)
},indent=2),encoding="utf-8")

print(json.dumps({
    "passed_concepts":sorted(passed_concepts),
    "company_capture_reviewed":len(results),
    "validation_ready":sum(1 for x in results if x["status"]=="VALIDATION_READY"),
    "promoted":promoted
},indent=2))
