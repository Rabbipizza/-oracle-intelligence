#!/usr/bin/env python3
"""P0-9 strict simulated-historical Discovery reconstruction.

Re-applies the frozen ORACLE_V4_RETRO_OPEN_WORLD_2 document-local title
extractor directly to source documents observable at T. It never reads the
2026 materialization timestamps of oracle_v4_retro_term_occurrences, never
reuses an all-history count baseline, and never touches LIVE alpha/FDR tables.

Critical anti-selection rule: the tested family is frozen from the 104-week
PRE-TEST history. A term is eligible iff it appeared at least once during that
training window. Test-week N(t) is never used to decide family membership, so
zero observations remain in-family and brand-new test-week terms are not
silently conditioned into the family.
"""
from __future__ import annotations
import hashlib, json, math, os, re, unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from sqlalchemy import create_engine, text
from oracle_v6_formal_nulls import _fit_count_null, WINDOW_WEEKS

TARGET_ALPHA=0.05
MODEL_VERSION='FORMAL_COUNT_NULL_V1_SIMULATED_P0_9'
EXTRACTION_VERSION='ORACLE_V4_RETRO_OPEN_WORLD_2'
FAMILY_RULE='TERM_SEEN_IN_104W_PRETEST_TRAINING'
DEFAULT_DATES=['2018-12-31','2019-06-30','2019-12-31','2020-06-30','2020-12-31','2021-12-31','2022-06-30','2022-12-31','2023-06-30','2023-12-31']
STOP=set(('a an and are as at be been being by can could did do does for from had has have how if in into is it its may more most new no not of on or our out over said says than that the their them there these they this those to under up use used using via was were what when where which while who will with would you your after before about amid among across also first one two three report reports study studies research researchers latest today year years company companies market markets tax themes theme record records title implied fncact soc crisislex uspec http https www com org net html amp source sources unknown article story official monitoring bbc website form filed filing press release against').split())
GENERIC=set(('global world industry business technology science health news update analysis future growth change changes impact system systems service services product products group team people time way work case launch operation conduct successful checking north south').split())
VERBS={'launched':'launch','launches':'launch','launching':'launch','attacked':'attack','attacks':'attack','attacking':'attack','killed':'kill','kills':'kill','killing':'kill','announced':'announce','announces':'announce','announcing':'announce','released':'release','releases':'release','releasing':'release','analyses':'analysis','defence':'defense','defences':'defense','centres':'center','centre':'center','programmes':'program','organisations':'organization'}

def engine(url):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def normalized(v):
    v=unicodedata.normalize('NFKD',v or '').encode('ascii','ignore').decode()
    v=re.sub(r'https?://\S+',' ',v); v=re.sub(r'\s+-\s+[^-]{2,45}$','',v); v=re.sub(r"[^A-Za-z0-9+#.' -]+",' ',v)
    return re.sub(r'\s+',' ',v).strip()

def lemma(v):
    x=v.lower().strip("+.#'-")
    if x in VERBS:return VERBS[x]
    if len(x)>5 and x.endswith('ies'):return x[:-3]+'y'
    if len(x)>5 and re.search(r'(ches|shes|xes|zes)$',x):return x[:-2]
    if len(x)>5 and x.endswith('ses') and not x.endswith('sses'):return x[:-1]
    if len(x)>4 and x.endswith('s') and not x.endswith('ss'):return x[:-1]
    return x

def terms(title):
    ts=[lemma(x) for x in normalized(title).split()]
    ts=[x for x in ts if len(x)>2 and x not in STOP and not re.match(r'^(\d+|[a-f0-9]{8,})$',x)]
    out=set()
    def label(v): return ' '.join(x.upper() if re.match(r'^[a-z]{1,4}\d|\d',x) else x[:1].upper()+x[1:] for x in v.split())
    for token in ts:
        if len(token)>=5 and token not in GENERIC: out.add(label(token))
    for n in (2,3):
        for i in range(0,len(ts)-n+1):
            a=ts[i:i+n]
            if all(x in GENERIC for x in a): continue
            v=' '.join(a)
            if 8<=len(v)<=72: out.add(label(v))
            if len(out)>=36: break
    return list(out)[:36]

def bh_adjusted(pvals):
    n=len(pvals); out=[1.0]*n; running=1.0
    order=sorted(range(n),key=lambda i:pvals[i])
    for rank in range(n,0,-1):
        i=order[rank-1]; running=min(running,pvals[i]*n/rank); out[i]=min(1.0,running)
    return out

def cutoff(d): return datetime.combine(d,time(23,59,59),tzinfo=timezone.utc)
def week_start(d): return d-timedelta(days=d.weekday())
def parse_dates():
    raw=os.environ.get('ORACLE_V6_SIMULATED_DATES',','.join(DEFAULT_DATES))
    xs=sorted({date.fromisoformat(x.strip()) for x in raw.split(',') if x.strip()})
    if not xs: raise ValueError('at least one simulated date required')
    return xs

def load_documents(conn,max_cutoff,min_event):
    return conn.execute(text("""
      select d.id,d.title,d.published_at,d.available_at_simulated
      from public.oracle_raw_documents d join public.oracle_sources s on s.id=d.source_id
      where s.source_type='RESEARCH_RSS' and s.name ilike 'arXiv%'
        and d.available_at_simulated is not null and d.available_at_simulated<=:mx
        and d.published_at>=:mn
      order by d.available_at_simulated,d.id
    """),{'mx':max_cutoff,'mn':min_event}).mappings().all()

def build_occurrences(docs):
    out=[]
    for d in docs:
        event=d['published_at'].date()
        for term in terms(str(d['title'] or '')):
            out.append((event,term,str(d['id']),d['available_at_simulated']))
    return out

def z_stats(family):
    zs=sorted(float(x['surprise_z']) for x in family)
    n=len(zs)
    if not n:
        return {'median':None,'max':None,'pct_z_ge_3':None,'pct_z_ge_5':None}
    mid=n//2
    median=zs[mid] if n%2 else (zs[mid-1]+zs[mid])/2.0
    return {
        'median':median,
        'max':zs[-1],
        'pct_z_ge_3':100.0*sum(1 for z in zs if z>=3.0)/n,
        'pct_z_ge_5':100.0*sum(1 for z in zs if z>=5.0)/n,
    }

def family_at(occ,cutoff_dt,test_week):
    train_start=test_week-timedelta(weeks=WINDOW_WEEKS); test_end=min(test_week+timedelta(days=6),cutoff_dt.date())
    by=defaultdict(lambda:defaultdict(set))
    for event,term,doc_id,avail in occ:
        if avail>cutoff_dt or event<train_start or event>test_end: continue
        w=event-timedelta(days=event.weekday()); by[term][w].add(doc_id)
    weeks=[train_start+timedelta(weeks=i) for i in range(WINDOW_WEEKS)]
    payload=[]
    for key,h in sorted(by.items()):
        train=[len(h.get(w,set())) for w in weeks]
        # Family membership is determined ONLY from pre-test information.
        # Terms absent from the entire 104-week training window are not tested
        # in this family; terms that were seen in training remain in the family
        # even when the test-week observation is zero.
        if sum(train)<=0: continue
        observed=len(h.get(test_week,set()))
        fit=_fit_count_null(train,observed)
        payload.append({'signal_key':key,'null_family':fit.family,'observed_value':observed,'expected_value':fit.expected,'dispersion':fit.dispersion,'surprise_z':fit.z_score,'p_value':fit.p_value,'training_window':{'weeks':WINDOW_WEEKS,'train_start':train_start.isoformat(),'train_end':(test_week-timedelta(weeks=1)).isoformat(),'test_week':test_week.isoformat(),'test_end':test_end.isoformat(),'cutoff':cutoff_dt.isoformat(),'clock_mode':'simulated_historical','source_filter':'arXiv available_at_simulated<=T','family_rule':FAMILY_RULE},'diagnostics':{**fit.diagnostics,'point_in_time':True,'clock_mode':'simulated_historical','recomputed_at_cutoff':True,'all_history_baseline_reused':False,'extraction_version':EXTRACTION_VERSION,'family_rule':FAMILY_RULE,'family_membership_depends_on_test_observation':False}})
    return payload

def run(db_url):
    dates=parse_dates(); run_material=','.join(d.isoformat() for d in dates)
    recon=os.environ.get('ORACLE_V6_RECONSTRUCTION_RUN') or 'P0_9_'+hashlib.sha256((run_material+'|'+FAMILY_RULE).encode()).hexdigest()[:16]
    summaries=[]; cumulative=0.0
    with engine(db_url).begin() as conn:
        min_event=week_start(dates[0])-timedelta(weeks=WINDOW_WEEKS)
        docs=load_documents(conn,cutoff(dates[-1]),min_event); occ=build_occurrences(docs)
        conn.execute(text('delete from public.oracle_v6_simulated_null_models where reconstruction_run=:r'),{'r':recon}); conn.execute(text('delete from public.oracle_v6_simulated_alpha_budget where reconstruction_run=:r'),{'r':recon})
        for t,d in enumerate(dates,1):
            c=cutoff(d); w=week_start(d); family=family_at(occ,c,w); gamma=6.0/(math.pi*math.pi*t*t); alpha_t=TARGET_ALPHA*gamma; cumulative+=alpha_t
            pvals=[float(x['p_value']) for x in family]; adj=bh_adjusted(pvals); selected=[a<=alpha_t for a in adj]
            rows=[]
            for i,x in enumerate(family): rows.append({**{k:v for k,v in x.items() if k not in ('training_window','diagnostics')},'r':recon,'d':d,'c':c,'tw':json.dumps(x['training_window'],sort_keys=True),'dg':json.dumps(x['diagnostics'],sort_keys=True),'ap':adj[i],'sel':selected[i],'alpha':alpha_t})
            if rows: conn.execute(text("""insert into public.oracle_v6_simulated_null_models(reconstruction_run,evaluation_date,decision_as_of,signal_key,null_family,observed_value,expected_value,dispersion,surprise_z,p_value,training_window,diagnostics,bh_adjusted_p,bh_selected,alpha_t) values(:r,:d,:c,:signal_key,:null_family,:observed_value,:expected_value,:dispersion,:surprise_z,:p_value,cast(:tw as jsonb),cast(:dg as jsonb),:ap,:sel,:alpha)"""),rows)
            disc=sum(selected); conn.execute(text("""insert into public.oracle_v6_simulated_alpha_budget(reconstruction_run,sequence_t,evaluation_date,gamma_t,alpha_t,cumulative_alpha_spend,family_size,discoveries) values(:r,:t,:d,:g,:a,:cum,:n,:k)"""),{'r':recon,'t':t,'d':d,'g':gamma,'a':alpha_t,'cum':cumulative,'n':len(family),'k':disc})
            summaries.append({'date':d.isoformat(),'test_week':w.isoformat(),'family_size':len(family),'discoveries':disc,'gamma_t':gamma,'alpha_t':alpha_t,'z_distribution':z_stats(family)})
    return {'ok':True,'clock_mode':'simulated_historical','family_rule':FAMILY_RULE,'conditional_selection_guard':True,'reconstruction_run':recon,'source_documents':len(docs),'reconstructed_occurrences':len(occ),'dates':summaries,'target_alpha':TARGET_ALPHA,'cumulative_alpha_spend':cumulative,'live_budget_touched':False}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
