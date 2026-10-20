#!/usr/bin/env python3
"""ORACLE Economic Chain Builder.

Builds an explicit, inspectable chain from early discovery to investability:
Discovery -> corroboration -> economic transmission -> company capture ->
market recognition -> entry readiness.

PRE_GREEN is a research-priority state only. It NEVER promotes a company to
GREEN and NEVER changes portfolio allocation by itself.
"""
import json
from pathlib import Path
from datetime import datetime, timezone
from oracle_data_quality import explicit_evidence

OUT=Path("data/economic-chains.json")

def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default

def clamp(x,a=0,b=100):
    return max(a,min(b,float(x)))

discovery=load("data/discovery-candidates.json",{"candidates":[]})
dossiers=load("data/evidence-dossiers.json")
gate=load("data/source-gate-status.json")
decision=load("decision-state.json")
research=load("research-universe.json")
registry=load("economic-evidence.json").get("companies",{})

# Discovery term lookup and concept mapping.
disc_by_term={x.get("term"):x for x in discovery.get("candidates",[]) if x.get("term")}
mapping={x.get("term"):x for x in dossiers.get("discovery_to_concepts",[]) or [] if x.get("term")}
concept_terms={}
for term,mp in mapping.items():
    concept=mp.get("concept")
    if concept:
        concept_terms.setdefault(concept,[]).append((term,mp))

# Candidate-level diagnostic: keep novelty separate from economic proof.
candidate_chains=[]
for g in gate.get("candidate_gates",[]) or []:
    term=g.get("term")
    d=disc_by_term.get(term,{})
    score=float(d.get("discovery_score") or 0)
    accel=float(d.get("acceleration") or 1)
    discovery_edge=round(clamp(30 + min(45,score*0.7) + min(25,max(0,accel-1)*12)),1)
    economic_proof=round(clamp(
        20*min(int(g.get("family_count") or 0),3) +
        20*(1 if int(g.get("primary_origin_count") or 0)>0 else 0) +
        20*(1 if int(g.get("economic_origin_count") or 0)>0 else 0)
    ),1)
    blockers=[]
    if int(g.get("family_count") or 0)<3: blockers.append("independent_source_families")
    if int(g.get("primary_origin_count") or 0)<1: blockers.append("primary_source")
    if int(g.get("economic_origin_count") or 0)<1: blockers.append("economic_transmission")
    if not g.get("concept"): blockers.append("concept_mapping")
    candidate_chains.append({
        "term":term,
        "concept":g.get("concept"),
        "discovery_edge_score":discovery_edge,
        "economic_proof_score":economic_proof,
        "coverage_gate_pass":bool(g.get("coverage_gate_pass")),
        "stage":g.get("trend_status"),
        "blockers":blockers,
        "research_priority":round(clamp(.60*discovery_edge+.40*(100-economic_proof)),1),
        "acceleration":d.get("acceleration"),
        "discovery_score":d.get("discovery_score")
    })

# Best upstream discovery signal linked to each concept.
best_discovery={}
for concept,vals in concept_terms.items():
    enriched=[]
    for term,mp in vals:
        d=disc_by_term.get(term,{})
        score=float(d.get("discovery_score") or 0)
        accel=float(d.get("acceleration") or 1)
        edge=clamp(30+min(45,score*.7)+min(25,max(0,accel-1)*12))
        enriched.append((edge,term,d,mp))
    if enriched:
        enriched.sort(reverse=True,key=lambda x:x[0])
        edge,term,d,mp=enriched[0]
        best_discovery[concept]={
            "term":term,"score":round(edge,1),
            "acceleration":d.get("acceleration"),
            "mapping_confidence":mp.get("mapping_confidence")
        }

company_chains={}
for ticker,cd in (dossiers.get("companies",{}) or {}).items():
    trend=cd.get("trend")
    concept=(dossiers.get("concepts",{}) or {}).get(trend,{})
    sc=(decision.get("scores",{}) or {}).get(ticker,{})
    sig=(decision.get("signals",{}) or {}).get(ticker,{})
    explicit=explicit_evidence(registry.get(ticker),decision.get("as_of"))
    investable=sig.get("signal")=="GREEN" and explicit and sc.get("data_status")=="AVAILABLE"
    capture=float(cd.get("company_capture_score") or 0)
    trend_ev=float(cd.get("trend_evidence_score") or concept.get("evidence_score") or 0)
    early=sc.get("structural_early_bird")
    recognition=sc.get("market_recognition_score")
    entry=sc.get("entry_score")
    quality=sc.get("structural_quality")

    discovery_link=best_discovery.get(trend)
    discovery_edge=float((discovery_link or {}).get("score") or 0)
    econ_orig=int(concept.get("economic_origin_count") or 0)
    econ_proof=clamp(.55*trend_ev + 25*(1 if econ_orig>0 else 0) + 20*min(1,int(concept.get("family_count") or 0)/3))
    economic_status="PROVEN" if econ_orig>0 and trend_ev>=80 else "PARTIAL" if econ_orig>0 else "UNPROVEN"
    if explicit:
        capture_status="PROVEN"
    elif capture>=60:
        capture_status="PARTIAL"
    else:
        capture_status="UNPROVEN"

    blockers=[]
    if trend_ev<80: blockers.append("trend_corroboration")
    if economic_status!="PROVEN": blockers.append("economic_transmission")
    if capture_status!="PROVEN": blockers.append("explicit_company_capture")
    if early is None: blockers.append("early_bird_not_scored")
    if entry is None: blockers.append("entry_not_scored")
    if sc.get("data_status")!="AVAILABLE": blockers.append("market_data_unavailable")

    # PRE_GREEN means "almost investable, investigate now". It cannot be GREEN
    # without explicit primary company-capture proof.
    pre_green=(
        not explicit and
        trend_ev>=80 and
        economic_status=="PROVEN" and
        capture>=60 and
        early is not None and float(early)>=50 and
        entry is not None and float(entry)>=55
    )

    missing_proof_penalty=0 if explicit else max(0,100-capture)
    priority=clamp(
        .18*discovery_edge +
        .22*trend_ev +
        .20*capture +
        .18*float(early or 0) +
        .12*float(entry or 0) +
        .10*missing_proof_penalty
    )

    chain=[
        {"step":"DISCOVERY","status":"PROVEN" if discovery_link else "UNPROVEN","score":round(discovery_edge,1),"evidence":discovery_link},
        {"step":"TREND_CORROBORATION","status":"PROVEN" if trend_ev>=80 else "PARTIAL","score":round(trend_ev,1)},
        {"step":"ECONOMIC_TRANSMISSION","status":economic_status,"score":round(econ_proof,1),"economic_origins":econ_orig},
        {"step":"COMPANY_CAPTURE","status":capture_status,"score":round(capture,1),"explicit_primary_proof":explicit},
        {"step":"MARKET_RECOGNITION","status":"MEASURED" if recognition is not None else "UNKNOWN","score":recognition},
        {"step":"EARLY_BIRD","status":"MEASURED" if early is not None else "UNKNOWN","score":early},
        {"step":"ENTRY_READINESS","status":"READY" if entry is not None and float(entry)>=60 else "WAIT","score":entry}
    ]

    company_chains[ticker]={
        "ticker":ticker,
        "company":cd.get("name"),
        "trend":trend,
        "role":cd.get("role"),
        "state":"GREEN" if investable else "PRE_GREEN" if pre_green else "ORANGE" if sig.get("signal")=="GREEN" else sig.get("signal","RED"),
        "pre_green":pre_green,
        "investable":investable,
        "research_priority_score":round(priority,1),
        "discovery_edge_score":round(discovery_edge,1),
        "economic_proof_score":round(econ_proof,1),
        "company_capture_score":round(capture,1),
        "structural_quality":quality,
        "early_bird_score":early,
        "market_recognition_score":recognition,
        "entry_score":entry,
        "blockers":blockers,
        "chain":chain,
        "rule":"PRE_GREEN is research priority only; GREEN still requires explicit primary economic company-capture proof."
    }

pre_green_watchlist=sorted(
    [v for v in company_chains.values() if v.get("pre_green")],
    key=lambda x:x.get("research_priority_score",0),
    reverse=True
)

OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "method":"ORACLE V5 explicit economic chain diagnostics",
    "pipeline":["DISCOVERY","TREND_CORROBORATION","ECONOMIC_TRANSMISSION","COMPANY_CAPTURE","MARKET_RECOGNITION","EARLY_BIRD","ENTRY_READINESS","PORTFOLIO_DECISION"],
    "candidate_chains":candidate_chains,
    "companies":company_chains,
    "pre_green_watchlist":pre_green_watchlist[:20],
    "rules":{
        "pre_green_non_investable":True,
        "green_requires_explicit_primary_capture":True,
        "causal_chains_are_never_inherited":True
    }
},indent=2),encoding="utf-8")
print(json.dumps({
    "candidate_chains":len(candidate_chains),
    "company_chains":len(company_chains),
    "pre_green":[x["ticker"] for x in pre_green_watchlist[:10]]
},indent=2))
