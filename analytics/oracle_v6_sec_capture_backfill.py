#!/usr/bin/env python3
"""Backfill PIT SEC capture evidence from full-text filings already fetched via Supabase Edge.

This stage never backdates evidence: it uses oracle_raw_documents.fetched_at as the
availability timestamp of the full text. It only extracts evidence when a bottleneck
alias and a capture keyword co-occur in a local context window.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION='SEC_CAPTURE_FULLTEXT_V1'
WINDOW=750
KEYWORDS={
 'DEMAND':['demand'],
 'ORDERS':['orders','order growth','bookings'],
 'BACKLOG':['backlog'],
 'CAPACITY':['capacity','production capacity','manufacturing capacity'],
 'SUPPLY':['supply','supplier','suppliers'],
 'CONSTRAINT':['constraint','constraints','constrained','shortage','shortages'],
 'LEAD_TIME':['lead time','lead times'],
 'PRICE':['pricing','price increases','higher prices','pricing actions','price realization'],
}
ALIASES={
 'COMPONENT:Semiconductors':['semiconductor','semiconductors','wafer','foundry','chip','chips'],
 'INFRASTRUCTURE:Grid Power Capacity':['grid','power capacity','electrical power','power distribution','utility','utilities','data center','data centers'],
 'COMPONENT:High Bandwidth Memory':['high bandwidth memory','hbm'],
 'PROCESS:Advanced Semiconductor Packaging':['advanced packaging','wafer-level packaging','3d stacking'],
 'COMPONENT:AI Accelerators':['ai accelerator','accelerators','gpu','gpus'],
 'INFRASTRUCTURE:Data Center Cooling':['cooling','thermal management','liquid cooling'],
 'INFRASTRUCTURE:High-Speed Networking':['networking','network interface','switches','interconnect'],
}

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def contexts(content:str, aliases:list[str]):
    low=content.lower(); seen=set()
    for alias in aliases:
        a=alias.lower(); pos=0
        while True:
            pos=low.find(a,pos)
            if pos<0: break
            start=max(0,pos-WINDOW); end=min(len(content),pos+len(a)+WINDOW)
            key=(start,end)
            if key not in seen:
                seen.add(key); yield content[start:end]
            pos+=max(1,len(a))

def run(db_url:str)->dict:
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as c:
        exp=int(c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        q="select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e "+("and external_run_id=:r " if run_id else "")+"order by evaluation_as_of desc,id desc limit 1"
        p={'e':exp}; p.update({'r':run_id} if run_id else {})
        cutoff=c.execute(text(q),p).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock')
        pairs=c.execute(text("""
          select distinct x.ticker,s.bottleneck_node
          from public.oracle_v6_structural_bottlenecks s
          join public.oracle_v6_structural_company_exposure x
            on x.experiment_id=s.experiment_id and x.evaluation_as_of=s.evaluation_as_of
           and x.bottleneck_node=s.bottleneck_node and x.exposure_role='SUPPLIER_CANDIDATE'
          where s.experiment_id=:e and s.evaluation_as_of=:a
            and s.structural_status='EVIDENCE_BACKED_TENSION'
          order by x.ticker,s.bottleneck_node
        """),{'e':exp,'a':cutoff}).mappings().all()
        inserted=0; docs_seen=0; pair_stats=[]
        for pair in pairs:
            ticker=str(pair['ticker']); node=str(pair['bottleneck_node']); aliases=ALIASES.get(node,[node.split(':')[-1].lower()])
            docs=c.execute(text("""
              select d.id,d.url,d.published_at,d.fetched_at,d.content
              from public.oracle_raw_documents d
              join public.oracle_sources s on s.id=d.source_id
              where s.source_type='CORPORATE_SEC' and s.name=:src
                and d.fetched_at<=:cutoff and length(coalesce(d.content,''))>1000
                and (d.title ilike '%10-K%' or d.title ilike '%10-Q%' or d.title ilike '%8-K%')
              order by d.published_at desc limit 18
            """),{'src':f'SEC {ticker}','cutoff':cutoff}).mappings().all()
            matched_docs=set(); pair_keys=set()
            for d in docs:
                docs_seen+=1
                content=str(d['content'] or '')
                for ctx in contexts(content,aliases):
                    lctx=ctx.lower()
                    for ek,terms in KEYWORDS.items():
                        if not any(t.lower() in lctx for t in terms): continue
                        if not any(a.lower() in lctx for a in aliases): continue
                        res=c.execute(text("""
                          insert into public.oracle_v4_sec_economic_evidence
                            (document_id,ticker,filing_date,evidence_key,excerpt,source_url,known_at,source_quality)
                          values (:doc,:ticker,cast(:filing as date),:key,:excerpt,:url,:known,1.0)
                          on conflict (document_id,evidence_key) do nothing
                          returning id
                        """),{'doc':d['id'],'ticker':ticker,'filing':d['published_at'].date().isoformat() if d['published_at'] else None,'key':ek,'excerpt':ctx[:1400],'url':d['url'],'known':d['fetched_at']}).scalar_one_or_none()
                        if res is not None: inserted+=1
                        matched_docs.add(str(d['id'])); pair_keys.add(ek)
                        break
            pair_stats.append({'ticker':ticker,'bottleneck_node':node,'fulltext_docs':len(docs),'matched_docs':len(matched_docs),'evidence_types':sorted(pair_keys)})
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'supplier_pairs':len(pairs),'docs_scanned':docs_seen,'evidence_inserted':inserted,'pairs':pair_stats,'state':'SEC_CAPTURE_EVIDENCE_BACKFILLED' if pairs else 'NO_TENSION_SUPPLIERS'}
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_capture_backfill}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
