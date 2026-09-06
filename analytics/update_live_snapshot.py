#!/usr/bin/env python3
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API='https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-investor-api'
OUT=Path('data/v5_live_fallback.json')
ANALYTICS=Path('data/v5_analytics.json')


def load_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def merge_analytics(snapshot):
    analytics=load_json(ANALYTICS) or {}
    if analytics:
        snapshot['analytics_generated_at']=analytics.get('generated_at')
        snapshot['current_decision']=analytics.get('current_decision')
        snapshot['production_readiness']=analytics.get('production_readiness')
        snapshot['analytics_engine']=analytics.get('engine')
    return snapshot

existing=load_json(OUT) or {}
req=urllib.request.Request(API,headers={'User-Agent':'ORACLE-V5-Snapshot/1.1','Accept':'application/json','Cache-Control':'no-store'})
now=datetime.now(timezone.utc).isoformat()
try:
    with urllib.request.urlopen(req,timeout=8) as r:
        if r.status!=200: raise RuntimeError(f'HTTP {r.status}')
        data=json.loads(r.read().decode('utf-8'))
    if not data.get('ok'): raise RuntimeError(data.get('error','API not ok'))
    if not isinstance(data.get('trends'),list) or not isinstance(data.get('causal_nodes'),list):
        raise RuntimeError('incomplete live payload')
    data['fallback']=True
    data['fallback_source']='LAST_SUCCESSFUL_LIVE_API_EXPORT'
    data['snapshot_exported_at']=now
    data['live_api_reachable_at_export']=True
    data=merge_analytics(data)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(data,indent=2,sort_keys=True),encoding='utf-8')
    print(f"snapshot updated run={data.get('display_run',{}).get('id')}")
except Exception as e:
    # Preserve the last confirmed live trend/value-chain snapshot, but refresh
    # the independent analytics decision so degraded mode remains useful.
    if existing:
        existing['fallback']=True
        existing['fallback_source']='LAST_CONFIRMED_LIVE_PLUS_LATEST_EXTERNAL_ANALYTICS'
        existing['snapshot_checked_at']=now
        existing['live_api_reachable_at_export']=False
        existing['live_api_error']=str(e)[:180]
        existing=merge_analytics(existing)
        OUT.write_text(json.dumps(existing,indent=2,sort_keys=True),encoding='utf-8')
        print(f'live API unavailable; preserved live snapshot and refreshed analytics: {e}')
    else:
        print(f'live API unavailable and no fallback exists: {e}')
