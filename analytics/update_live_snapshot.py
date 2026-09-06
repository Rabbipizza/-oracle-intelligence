#!/usr/bin/env python3
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API='https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-investor-api'
OUT=Path('data/v5_live_fallback.json')
req=urllib.request.Request(API,headers={'User-Agent':'ORACLE-V5-Snapshot/1.0','Accept':'application/json','Cache-Control':'no-store'})
try:
    with urllib.request.urlopen(req,timeout=10) as r:
        if r.status!=200: raise RuntimeError(f'HTTP {r.status}')
        data=json.loads(r.read().decode('utf-8'))
    if not data.get('ok'): raise RuntimeError(data.get('error','API not ok'))
    if not isinstance(data.get('trends'),list) or not isinstance(data.get('causal_nodes'),list):
        raise RuntimeError('incomplete live payload')
    data['fallback']=True
    data['fallback_source']='LAST_SUCCESSFUL_LIVE_API_EXPORT'
    data['snapshot_exported_at']=datetime.now(timezone.utc).isoformat()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(data,indent=2,sort_keys=True),encoding='utf-8')
    print(f"snapshot updated run={data.get('display_run',{}).get('id')}")
except Exception as e:
    print(f'live API unavailable, preserving existing snapshot: {e}')
