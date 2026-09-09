#!/usr/bin/env python3
"""ORACLE V6 bottleneck forecast gate.

Evidence-backed tension is descriptive evidence, not a forecast. This worker
recognizes those PIT candidates, but still refuses to write a bottleneck
probability until a historical outcome model is explicitly calibrated.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION="BOTTLENECK_GATE_V2"
MIN_INDEPENDENT_GROUPS=2
MIN_CALIBRATION_OUTCOMES=20

def _engine(db_url:str):
    if db_url.startswith('postgres://'): db_url='postgresql+psycopg://'+db_url[len('postgres://'):]
    elif db_url.startswith('postgresql://'): db_url='postgresql+psycopg://'+db_url[len('postgresql://'):]
    else: raise ValueError('db_url must be PostgreSQL')
    return create_engine(db_url,pool_pre_ping=True)

def run(db_url:str)->dict:
    run_id=os.environ.get('GITHUB_RUN_ID')
    with _engine(db_url).begin() as conn:
        exp=conn.execute(text("select id,(metrics->>'decision_as_of')::timestamptz signal_available_at,(metrics->>'test_week')::date test_week from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).mappings().one_or_none()
        if not exp: raise RuntimeError('latest scientific experiment unavailable')
        experiment_id=int(exp['id'])
        cutoff=None
        if run_id:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by evaluation_as_of desc limit 1"),{'e':experiment_id,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':experiment_id}).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock')
        candidates=conn.execute(text("select bottleneck_node,max(independent_source_count) independent_source_count from public.oracle_v6_structural_bottlenecks where experiment_id=:e and evaluation_as_of=:a and structural_status='EVIDENCE_BACKED_TENSION' and independent_source_count>=:n group by bottleneck_node order by bottleneck_node"),{'e':experiment_id,'a':cutoff,'n':MIN_INDEPENDENT_GROUPS}).mappings().all()
        calibration_outcomes=int(conn.execute(text("select count(*) from public.oracle_v6_bottleneck_forecasts where realized_outcome is not null and realized_at is not null and model_version is not null")).scalar_one())
        calibrated=calibration_outcomes>=MIN_CALIBRATION_OUTCOMES
        if not candidates: state='NO_FORECAST_INSUFFICIENT_INDEPENDENT_EVIDENCE'
        elif not calibrated: state='NO_FORECAST_UNCALIBRATED'
        else: state='NO_FORECAST_MODEL_NOT_YET_VALIDATED'
        summary={
            'model_version':MODEL_VERSION,'state':state,'candidate_count':len(candidates),
            'candidate_bottlenecks':[str(x['bottleneck_node']) for x in candidates],
            'calibration_outcomes':calibration_outcomes,'minimum_calibration_outcomes':MIN_CALIBRATION_OUTCOMES,
            'minimum_independent_groups':MIN_INDEPENDENT_GROUPS,'forecast_rows_written':0,
            'test_week':exp['test_week'].isoformat() if exp['test_week'] else None,
            'signal_available_at':exp['signal_available_at'].isoformat() if exp['signal_available_at'] else None,
            'evaluation_as_of':cutoff.isoformat(),'probability_synthesized':False,
        }
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{bottleneck_gate}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':experiment_id})
    return {'ok':True,'experiment_id':experiment_id,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
