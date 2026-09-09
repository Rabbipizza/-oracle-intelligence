#!/usr/bin/env python3
"""P0-8 benchmark for Evidence-Backed Tension extraction.

Requires two independent human annotations per sampled excerpt. Cohen's kappa is
computed BEFORE adjudication. Disagreements require an explicit adjudication row.
The current rule-based extractor is evaluated as a 4-class classifier that emits
REAL_TENSION when the current detector fires, otherwise NO_TENSION.

A benchmark passes only when:
  * >= configured minimum sample size are double-annotated,
  * Cohen's kappa >= configured minimum,
  * every disagreement used in the benchmark is adjudicated,
  * precision(REAL_TENSION) >= configured threshold.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from math import isfinite
from sqlalchemy import create_engine, text

CONFIG_VERSION = "TENSION_VALIDATION_V1"
BENCHMARK_VERSION = "TENSION_BENCHMARK_V1"
SAMPLE_VERSION = "TENSION_SAMPLE_V1"
LABELS = ["REAL_TENSION","RESOLVED_TENSION","NO_TENSION","AMBIGUOUS"]


def _engine(url: str):
    if url.startswith('postgres://'):
        url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url='postgresql+psycopg://'+url[len('postgresql://'):]
    else:
        raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)


def cohen_kappa(a: list[str], b: list[str]) -> float:
    if len(a)!=len(b) or not a:
        raise ValueError('kappa requires equal non-empty label vectors')
    n=len(a); po=sum(x==y for x,y in zip(a,b))/n
    ca=Counter(a); cb=Counter(b)
    pe=sum((ca[l]/n)*(cb[l]/n) for l in LABELS)
    if pe>=1.0:
        return 1.0 if po>=1.0 else 0.0
    return (po-pe)/(1.0-pe)


def metrics(y_true: list[str], y_pred: list[str]) -> dict:
    out={}
    for label in LABELS:
        tp=sum(t==label and p==label for t,p in zip(y_true,y_pred))
        fp=sum(t!=label and p==label for t,p in zip(y_true,y_pred))
        fn=sum(t==label and p!=label for t,p in zip(y_true,y_pred))
        precision=tp/(tp+fp) if tp+fp else 0.0
        recall=tp/(tp+fn) if tp+fn else 0.0
        f1=2*precision*recall/(precision+recall) if precision+recall else 0.0
        out[label]={"tp":tp,"fp":fp,"fn":fn,"precision":precision,"recall":recall,"f1":f1,"support":sum(t==label for t in y_true)}
    return out


def run(db_url: str) -> dict:
    with _engine(db_url).begin() as conn:
        cfg=conn.execute(text("select * from public.oracle_v6_tension_validation_config where config_version=:v and active=true"),{'v':CONFIG_VERSION}).mappings().one()
        rows=conn.execute(text("""
          with a as (
            select s.id sample_id,s.current_classifier_positive,
                   array_agg(x.label order by x.annotator_id) labels,
                   array_agg(x.annotator_id order by x.annotator_id) annotators,
                   j.label adjudicated_label
            from public.oracle_v6_tension_annotation_sample s
            join public.oracle_v6_tension_annotations x on x.sample_id=s.id
            left join public.oracle_v6_tension_adjudications j on j.sample_id=s.id
            where s.sample_version=:sv
            group by s.id,s.current_classifier_positive,j.label
            having count(distinct x.annotator_id)=2 and count(*)=2
          ) select * from a order by sample_id
        """),{'sv':SAMPLE_VERSION}).mappings().all()

        double_n=len(rows)
        min_n=int(cfg['minimum_sample_size'])
        failure=[]
        if double_n < min_n:
            failure.append(f"DOUBLE_ANNOTATED_SAMPLE_TOO_SMALL:{double_n}<{min_n}")
            kappa=None; per_class={}; rp=rr=rf=None
        else:
            a=[r['labels'][0] for r in rows]; b=[r['labels'][1] for r in rows]
            kappa=cohen_kappa(a,b)
            if kappa < float(cfg['minimum_kappa']):
                failure.append(f"KAPPA_TOO_LOW:{kappa:.6f}<{float(cfg['minimum_kappa']):.6f}")
            y_true=[]; y_pred=[]; unresolved=0
            for r in rows:
                l1,l2=r['labels']
                if l1==l2: truth=l1
                elif r['adjudicated_label'] is not None: truth=str(r['adjudicated_label'])
                else:
                    unresolved+=1
                    continue
                y_true.append(truth)
                y_pred.append('REAL_TENSION' if r['current_classifier_positive'] else 'NO_TENSION')
            if unresolved:
                failure.append(f"UNADJUDICATED_DISAGREEMENTS:{unresolved}")
            if len(y_true)<min_n:
                failure.append(f"FINAL_LABEL_SAMPLE_TOO_SMALL:{len(y_true)}<{min_n}")
            per_class=metrics(y_true,y_pred) if y_true else {}
            real=per_class.get('REAL_TENSION',{})
            rp=float(real.get('precision',0.0)); rr=float(real.get('recall',0.0)); rf=float(real.get('f1',0.0))
            if rp < float(cfg['required_real_tension_precision']):
                failure.append(f"REAL_TENSION_PRECISION_TOO_LOW:{rp:.6f}<{float(cfg['required_real_tension_precision']):.6f}")

        passed=(not failure and kappa is not None and isfinite(kappa))
        result={"benchmark_version":BENCHMARK_VERSION,"sample_version":SAMPLE_VERSION,"sample_size":double_n,"double_annotated_size":double_n,"cohen_kappa":kappa,"per_class_metrics":per_class,"real_tension_precision":rp,"real_tension_recall":rr,"real_tension_f1":rf,"required_precision":float(cfg['required_real_tension_precision']),"minimum_kappa":float(cfg['minimum_kappa']),"benchmark_pass":passed,"failure_reason":";".join(failure) if failure else None}
        conn.execute(text("""
          insert into public.oracle_v6_tension_benchmark_runs
            (benchmark_version,sample_version,sample_size,double_annotated_size,cohen_kappa,per_class_metrics,
             real_tension_precision,real_tension_recall,real_tension_f1,required_precision,minimum_kappa,benchmark_pass,failure_reason)
          values(:benchmark_version,:sample_version,:sample_size,:double_annotated_size,:cohen_kappa,cast(:per_class_metrics as jsonb),
             :real_tension_precision,:real_tension_recall,:real_tension_f1,:required_precision,:minimum_kappa,:benchmark_pass,:failure_reason)
        """),{**result,'per_class_metrics':json.dumps(per_class,sort_keys=True)})
    return {"ok":passed,**result}


if __name__=='__main__':
    r=run(os.environ.get('ORACLE_SUPABASE_DB_URL',''))
    print(json.dumps(r,sort_keys=True))
    raise SystemExit(0 if r['ok'] else 2)
