#!/usr/bin/env python3
"""ORACLE V6 final decision prerequisite gate.

Decisions are evaluated at the current evaluation-run timestamp. Deterministic
reverse DCF rows alone do not satisfy the expectation-gap prerequisite; a
calibrated probability that fundamentals exceed expectations is required.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text
MODEL_VERSION="DECISION_PREREQUISITE_GATE_V1"; CAPTURE_MODEL="COMPANY_CAPTURE_EVIDENCE_GATE_V1"
def _engine(db_url):
    if db_url.startswith("postgres://"): db_url="postgresql+psycopg://"+db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"): db_url="postgresql+psycopg://"+db_url[len("postgresql://"):]
    else: raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url,pool_pre_ping=True)
def run(db_url):
    engine=_engine(db_url); run_id=os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp=conn.execute(text("select id,(metrics->>'decision_as_of')::timestamptz signal_available_at from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).mappings().one_or_none()
        if not exp: raise RuntimeError("latest PIT experiment unavailable")
        experiment_id=int(exp["id"])
        cutoff=None
        if run_id: cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:experiment_id and external_run_id=:run_id"),{"experiment_id":experiment_id,"run_id":run_id}).scalar_one_or_none()
        if cutoff is None: cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:experiment_id order by evaluation_as_of desc,id desc limit 1"),{"experiment_id":experiment_id}).scalar_one_or_none()
        if cutoff is None: raise RuntimeError("no evaluation clock for decision gate")
        tickers=[str(x) for x in conn.execute(text("select distinct ticker from public.oracle_v6_company_capture where model_version=:m and as_of=:c order by ticker"),{"m":CAPTURE_MODEL,"c":cutoff}).scalars().all()]
        gaps=[]
        if conn.execute(text("select count(*) from public.oracle_v6_company_capture where model_version=:m and as_of=:c and capture_probability is not null"),{"m":CAPTURE_MODEL,"c":cutoff}).scalar_one()==0: gaps.append("UNCALIBRATED_ECONOMIC_CAPTURE")
        if conn.execute(text("select count(*) from public.oracle_v6_market_expectations where as_of=:c and p_fundamentals_exceed_expectations is not null"),{"c":cutoff}).scalar_one()==0: gaps.append("MISSING_CALIBRATED_EXPECTATION_GAP")
        if conn.execute(text("select count(*) from public.oracle_v6_bottleneck_forecasts where as_of<=:c"),{"c":cutoff}).scalar_one()==0: gaps.append("NO_VALIDATED_BOTTLENECK_FORECAST")
        gaps.append("NO_OOS_INCREMENTAL_RETURN_MODEL"); gaps=sorted(set(gaps))
        conn.execute(text("delete from public.oracle_v6_decisions where model_version=:m and as_of=:c"),{"m":MODEL_VERSION,"c":cutoff})
        payload=[{"ticker":t,"as_of":cutoff,"decision":"NO_ACTION","uncertainty":json.dumps({"probabilities_calibrated":False,"expected_residual_return_calibrated":False,"signal_available_at":exp["signal_available_at"].isoformat() if exp["signal_available_at"] else None},sort_keys=True),"data_gaps":json.dumps(gaps),"invalidation_conditions":json.dumps([]),"model_version":MODEL_VERSION} for t in tickers]
        if payload: conn.execute(text("insert into public.oracle_v6_decisions (ticker,as_of,decision,p_structural,p_bottleneck,p_economic_capture,p_fundamentals_exceed_expectations,expected_residual_return,uncertainty,invalidation_conditions,data_gaps,model_version) values (:ticker,:as_of,:decision,null,null,null,null,null,cast(:uncertainty as jsonb),cast(:invalidation_conditions as jsonb),cast(:data_gaps as jsonb),:model_version)"),payload)
        summary={"model_version":MODEL_VERSION,"signal_available_at":exp["signal_available_at"].isoformat() if exp["signal_available_at"] else None,"evaluation_as_of":cutoff.isoformat(),"candidate_tickers":len(tickers),"decision_rows_written":len(payload),"decision":"NO_ACTION","data_gaps":gaps,"numeric_probabilities_written":0,"expected_returns_written":0,"state":"NO_ACTION_PREREQUISITES_INCOMPLETE"}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{decision_gate}',cast(:s as jsonb),true) where id=:i"),{"s":json.dumps(summary,sort_keys=True),"i":experiment_id})
    return {"ok":True,"experiment_id":experiment_id,**summary}
def main(): print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL","")),sort_keys=True))
if __name__=="__main__": main()
