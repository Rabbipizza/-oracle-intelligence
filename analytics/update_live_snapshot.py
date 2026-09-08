#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API=os.environ.get('ORACLE_V5_API','https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-investor-build')
OUT=Path('data/v5_live_fallback.json')
ANALYTICS=Path('data/v5_analytics.json')

def load_json(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception:return None

def safe_num(v):
    try:return float(v)
    except Exception:return None

def structural_score(e):
    pre=safe_num(e.get('pre_market_score'))
    if pre is not None:return round(max(0,min(100,pre)),2)
    role=safe_num(e.get('role_specificity_score')) or 0;evidence=safe_num(e.get('evidence_score')) or 0;attention=safe_num(e.get('attention_penalty')) or 0
    return round(max(0,min(100,.55*role+.30*evidence+.15*(100-attention))),2)

def sanitize_value_chains(snapshot):
    out=[]
    for ch in snapshot.get('value_chains',[]) or []:
        x=dict(ch);nodes=x.get('nodes') or []
        structural=[n for n in nodes if ('BOTTLENECK' in str(n.get('node_type','')).upper() or 'PICKS_SHOVELS' in str(n.get('node_type','')).upper() or 'SHOVEL' in str(n.get('node_type','')).upper())]
        proven=any((n.get('evidence_summary') or {}).get('causality_proven') is True or (n.get('evidence_summary') or {}).get('economic_bottleneck_proven') is True or str(n.get('status','')).upper() in {'ECONOMIC_BOTTLENECK','PROVEN','PROVEN_DIRECT'} for n in structural)
        plausible=any(str(n.get('status','')).upper() in {'PLAUSIBLE','REQUIRED_INPUT','MULTI_BUYER_INPUT','COVERAGE_CANDIDATE'} for n in structural)
        if proven:maturity='PROVEN'
        elif plausible:maturity='PLAUSIBLE'
        elif nodes:maturity='ANALYZED_UNPROVEN'
        else:maturity='NOT_ANALYZED'
        x['maturity']=maturity
        x['causal_gate_passed']=maturity in {'PROVEN','PLAUSIBLE'} and bool(structural)
        if not x['causal_gate_passed']:
            x['leaders']=[];x['companies']=[];x['early_birds']=[]
            x['company_gate_reason']='NO_CAUSAL_BOTTLENECK_OR_PICKS_SHOVELS'
        out.append(x)
    snapshot['value_chains']=out
    return snapshot

def enrich_methodology(snapshot, analytics):
    early_by_ticker={str(e.get('ticker') or '').upper():e for e in snapshot.get('early_birds',[]) if e.get('ticker')}
    enriched=[]
    for e in snapshot.get('early_birds',[]):
        x=dict(e);structural=structural_score(e);x['structural_early_bird_score']=structural;x['structural_status']='STRUCTURAL_EARLY_BIRD' if structural>=75 else ('STRUCTURAL_WATCH' if structural>=60 else 'LOW_STRUCTURAL_SCORE');x['legacy_market_adjusted_early_bird_score']=e.get('early_bird_score');enriched.append(x)
    snapshot['early_birds']=enriched
    current=((analytics or {}).get('current_decision') or {}).get('candidates') or [];rebuilt=[]
    for c in current:
        x=dict(c);t=str(c.get('ticker') or '').upper();e=early_by_ticker.get(t,{});structural=structural_score(e) if e else safe_num(c.get('structural_early_bird_score'));fs=safe_num((c.get('fundamental') or {}).get('score'));gs=safe_num((c.get('expectation_gap') or {}).get('score'));entry=round(.45*structural+.30*fs+.25*gs,2) if structural is not None and fs is not None and gs is not None else None;x['structural_early_bird_score']=structural;x['entry_score']=entry;x['legacy_composite_score']=c.get('composite_score');quality=safe_num((c.get('fundamental') or {}).get('quality')) or 0
        if entry is not None and quality>=70 and fs is not None and fs>=60 and gs is not None and gs>=45:x['decision']='PILOT_BUY' if not ((analytics or {}).get('production_readiness') or {}).get('real_money_alpha_validated') else 'BUY_CANDIDATE';x['max_paper_weight_pct']=15 if x['decision']=='PILOT_BUY' else (35 if entry>=75 else 20)
        elif quality>=70:x['decision']='WATCH';x['max_paper_weight_pct']=0
        else:x['decision']='WAIT_FOR_FUNDAMENTALS';x['max_paper_weight_pct']=0
        rebuilt.append(x)
    rebuilt.sort(key=lambda x:(x.get('entry_score') is not None,x.get('entry_score') or -1),reverse=True)
    snapshot['current_decision']={'global':rebuilt[0].get('decision','WATCH') if rebuilt else 'NO_ACTION','candidates':rebuilt[:10],'method':'STRUCTURAL_EARLY_BIRD_THEN_ENTRY_V1'}
    snapshot['scoring_methodology']={'structural_early_bird':'pre_market_score = causal role specificity + evidence + low attention; excludes price, rerating and market cap','entry_score':'45% structural Early Bird + 30% fundamentals + 25% expectation-gap/rerating proxy','principle':'being underpriced is an entry-timing question, not an Early Bird definition'}
    return sanitize_value_chains(snapshot)

def merge_analytics(snapshot):
    analytics=load_json(ANALYTICS) or {}
    if analytics:snapshot['analytics_generated_at']=analytics.get('generated_at');snapshot['production_readiness']=analytics.get('production_readiness');snapshot['analytics_engine']=analytics.get('engine')
    return enrich_methodology(snapshot,analytics)

existing=load_json(OUT) or {};req=urllib.request.Request(API,headers={'User-Agent':'ORACLE-V5-Snapshot/1.6','Accept':'application/json','Cache-Control':'no-store'});now=datetime.now(timezone.utc).isoformat()
try:
    with urllib.request.urlopen(req,timeout=75) as r:
        if r.status!=200:raise RuntimeError(f'HTTP {r.status}')
        data=json.loads(r.read().decode('utf-8'))
    if not data.get('ok'):raise RuntimeError(data.get('error','API not ok'))
    if not isinstance(data.get('trends'),list) or not isinstance(data.get('causal_nodes'),list):raise RuntimeError('incomplete live payload')
    data['fallback']=False;data['snapshot_source']='PRECOMPUTED_INVESTOR_BUILD';data['snapshot_exported_at']=now;data['live_api_reachable_at_export']=True;data=merge_analytics(data);OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(data,indent=2,sort_keys=True),encoding='utf-8');print(f"snapshot updated run={data.get('display_run',{}).get('id')}")
except Exception as e:
    if existing:
        existing['fallback']=True;existing['fallback_source']='LAST_CONFIRMED_SNAPSHOT';existing['snapshot_checked_at']=now;existing['live_api_reachable_at_export']=False;existing['live_api_error']=str(e)[:180];existing=merge_analytics(existing);OUT.write_text(json.dumps(existing,indent=2,sort_keys=True),encoding='utf-8');print(f'builder unavailable; preserved last snapshot: {e}')
    else:raise
