#!/usr/bin/env python3
"""Collect forward-only PIT analyst EPS revision snapshots.

Scientific contract:
- This collector NEVER backfills synthetic historical analyst revisions.
- available_at is the actual collection timestamp.
- The source is Yahoo Finance via yfinance and is treated as an external current snapshot,
  not as a historical PIT vendor feed.
- Until enough daily snapshots accumulate, the factor baseline remains NOT historically validated.
"""
from __future__ import annotations
import json, os, time
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
import yfinance as yf

SOURCE='YAHOO_FINANCE_YFINANCE'
SOURCE_VERSION='EPS_REVISIONS_SNAPSHOT_V1'
MAX_TICKERS=int(os.environ.get('ORACLE_V6_REVISION_MAX_TICKERS','40'))
SLEEP=float(os.environ.get('ORACLE_V6_REVISION_SLEEP','0.15'))


def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)


def _num(v):
    try:
        if v is None: return None
        if hasattr(v,'item'): v=v.item()
        if isinstance(v,float) and v!=v: return None
        return float(v)
    except Exception:
        return None


def _int(v):
    x=_num(v)
    return int(x) if x is not None else None


def _get(df,row,col):
    try: return df.loc[row,col]
    except Exception: return None


def collect_one(ticker:str,available_at:datetime):
    t=yf.Ticker(ticker)
    rev=t.get_eps_revisions()
    trend=t.get_eps_trend()
    if rev is None or getattr(rev,'empty',True): return []
    horizons=[str(c) for c in rev.columns]
    out=[]
    for h in horizons:
        up7=_int(_get(rev,'upLast7days',h))
        up30=_int(_get(rev,'upLast30days',h))
        down7=_int(_get(rev,'downLast7days',h))
        down30=_int(_get(rev,'downLast30days',h))
        cur=_num(_get(trend,'current',h)) if trend is not None else None
        d7=_num(_get(trend,'7daysAgo',h)) if trend is not None else None
        d30=_num(_get(trend,'30daysAgo',h)) if trend is not None else None
        pos=(up30 or 0)-(down30 or 0)
        den=(up30 or 0)+(down30 or 0)
        score=(pos/den) if den else None
        raw={
          'up_7d':up7,'up_30d':up30,'down_7d':down7,'down_30d':down30,
          'current_estimate':cur,'seven_days_ago':d7,'thirty_days_ago':d30,
        }
        out.append(dict(ticker=ticker,available_at=available_at,source=SOURCE,source_version=SOURCE_VERSION,
                        horizon=h,up_7d=up7,up_30d=up30,down_7d=down7,down_30d=down30,
                        current_estimate=cur,seven_days_ago=d7,thirty_days_ago=d30,
                        revision_score=score,raw_payload=json.dumps(raw,sort_keys=True)))
    return out


def run(db_url:str):
    e=eng(db_url); now=datetime.now(timezone.utc)
    with e.begin() as c:
        tickers=[str(x) for x in c.execute(text("""
          with x as (
            select ticker,0 pri from public.oracle_v6_decisions where as_of=(select max(as_of) from public.oracle_v6_decisions)
            union
            select ticker,1 pri from public.oracle_v6_structural_company_exposure where exposure_role='SUPPLIER_CANDIDATE'
          ) select ticker from x where ticker ~ '^[A-Z.-]{1,10}$' order by pri,ticker limit :n
        """),{'n':MAX_TICKERS}).scalars().all()]
    rows=[]; failures=[]
    for ticker in tickers:
        try: rows.extend(collect_one(ticker,now))
        except Exception as ex: failures.append({'ticker':ticker,'error':str(ex)[:240]})
        time.sleep(SLEEP)
    if rows:
        with e.begin() as c:
            c.execute(text("""
              insert into public.oracle_v6_earnings_revision_snapshots
                (ticker,available_at,source,source_version,horizon,up_7d,up_30d,down_7d,down_30d,current_estimate,seven_days_ago,thirty_days_ago,revision_score,raw_payload)
              values(:ticker,:available_at,:source,:source_version,:horizon,:up_7d,:up_30d,:down_7d,:down_30d,:current_estimate,:seven_days_ago,:thirty_days_ago,:revision_score,cast(:raw_payload as jsonb))
              on conflict(ticker,available_at,source,horizon) do nothing
            """),rows)
    result={'ok':True,'source':SOURCE,'source_version':SOURCE_VERSION,'available_at':now.isoformat(),
            'tickers_requested':len(tickers),'rows_written':len(rows),'failures':failures,
            'historical_backtest_ready':False,'state':'FORWARD_PIT_REVISION_SNAPSHOTS_COLLECTING' if rows else 'NO_REVISION_SNAPSHOTS_COLLECTED'}
    print(json.dumps(result,sort_keys=True))
    return result

if __name__=='__main__': run(os.environ.get('ORACLE_SUPABASE_DB_URL',''))
