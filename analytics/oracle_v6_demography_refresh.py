#!/usr/bin/env python3
import json, os, time
from sqlalchemy import create_engine, text

BATCHES=['WLD,USA,CHN,IND,JPN','DEU,FRA,GBR,CHE,KOR','ITA,ESP,CAN,AUS,BRA','MEX,IDN,SAU,ARE,ZAF']

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def main():
    e=eng(os.environ['ORACLE_SUPABASE_DB_URL']); reqs=[]
    with e.begin() as c:
        for b in BATCHES: reqs.append(int(c.execute(text('select public.oracle_v6_trigger_demography_ingest_batch(:b)'),{'b':b}).scalar_one()))
    deadline=time.time()+150; pending=set(reqs); responses={}
    while pending and time.time()<deadline:
        with e.begin() as c:
            rows=c.execute(text('select id,status_code,error_msg,content from net._http_response where id=any(:ids)'),{'ids':list(pending)}).mappings().all()
        for r in rows:
            if r['status_code'] is not None or r['error_msg'] is not None:
                responses[int(r['id'])]=dict(r); pending.discard(int(r['id']))
        if pending: time.sleep(2)
    if pending: raise RuntimeError(f'demography refresh timed out: {sorted(pending)}')
    payloads=[]
    for rid in reqs:
        r=responses[rid]
        if r['error_msg'] or int(r['status_code'] or 0)!=200: raise RuntimeError(f'demography batch {rid} failed: {r}')
        p=json.loads(r['content'] or '{}')
        if not p.get('ok'): raise RuntimeError(f'demography batch {rid} application failure: {p}')
        payloads.append(p)
    print(json.dumps({'ok':True,'batches':payloads,'countries':sum(len(x.get('countries',[])) for x in payloads),'rows_upserted':sum(int(x.get('rows_upserted') or 0) for x in payloads)},sort_keys=True))

if __name__=='__main__': main()
