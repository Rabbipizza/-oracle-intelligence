#!/usr/bin/env python3
import json, os, time
from sqlalchemy import create_engine, text


def engine_for(url: str):
    if url.startswith('postgres://'):
        url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url='postgresql+psycopg://'+url[len('postgresql://'):]
    else:
        raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)


def main():
    eng=engine_for(os.environ['ORACLE_SUPABASE_DB_URL'])
    with eng.begin() as c:
        request_id=c.execute(text('select public.oracle_v6_trigger_sec_financials()')).scalar_one()
    deadline=time.time()+40
    row=None
    while time.time()<deadline:
        with eng.begin() as c:
            row=c.execute(text('select status_code,error_msg,content from net._http_response where id=:id'),{'id':request_id}).mappings().one_or_none()
        if row and (row['status_code'] is not None or row['error_msg'] is not None):
            break
        time.sleep(1)
    if not row:
        raise RuntimeError('SEC edge response missing')
    if row['error_msg']:
        raise RuntimeError(f"SEC edge transport failure: {row['error_msg']}")
    if int(row['status_code'] or 0)!=200:
        raise RuntimeError(f"SEC edge HTTP {row['status_code']}: {row['content']}")
    payload=json.loads(row['content'] or '{}')
    if not payload.get('ok'):
        raise RuntimeError(f"SEC edge application failure: {payload}")
    if int(payload.get('issuers_fetched') or 0)<1:
        raise RuntimeError(f"SEC edge returned no issuers: {payload}")
    print(json.dumps(payload,sort_keys=True))

if __name__=='__main__':
    main()
