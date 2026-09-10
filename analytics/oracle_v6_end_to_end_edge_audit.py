#!/usr/bin/env python3
"""ORACLE V6 end-to-end scientific edge audit.

This is an audit, not an investment engine. It asks whether the full chain
signal -> economic transmission -> fundamentals -> expectations -> residual
returns is presently testable out-of-sample under the project's declared
baseline contract.

States:
  EDGE_UNTESTABLE: at least one prerequisite for an OOS edge test is missing.
  NO_EDGE: prerequisites exist and OOS test does not beat the baseline.
  EDGE_CANDIDATE: preliminary OOS excess exists but validation sample/gates are
                  not yet sufficient for a validated claim.
  EDGE_VALIDATED: reserved for a pre-registered OOS test that clears all gates.

Important: zero observations never means NO_EDGE. It means EDGE_UNTESTABLE.
"""
from __future__ import annotations

import json
import os
from sqlalchemy import create_engine, text

MODEL_VERSION = "END_TO_END_EDGE_AUDIT_V1"
BASELINE_CONTRACT = "MOMENTUM+EARNINGS_REVISIONS+VALUATION+QUALITY"
MIN_MATURED_OUTCOMES = 100
MIN_DISTINCT_TICKERS = 20


def _engine(url: str):
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    else:
        raise ValueError("PostgreSQL URL required")
    return create_engine(url, pool_pre_ping=True)


def scalar(conn, sql: str, params=None):
    return conn.execute(text(sql), params or {}).scalar_one()


def run(db_url: str) -> dict:
    with _engine(db_url).begin() as conn:
        exp = conn.execute(text("""
          select id from public.oracle_v6_experiments
          where model_family='COUNT_NULL_MODEL'
            and model_version='FORMAL_COUNT_NULL_V1'
            and invalidated_at is null
          order by created_at desc,id desc limit 1
        """)).scalar_one_or_none()
        experiment_id = int(exp) if exp is not None else None

        evaluation_as_of = conn.execute(text("""
          select max(evaluation_as_of) from public.oracle_v6_evaluation_runs
          where (:e is null or experiment_id=:e)
        """), {"e": experiment_id}).scalar_one_or_none()

        replicated = scalar(conn, """
          select count(*) from public.oracle_v6_signal_lifecycle
          where lifecycle_state in ('REPLICATED_SIGNAL','CANDIDATE_FOR_SEMANTIC_BRIDGE')
            and (:e is null or experiment_id=:e)
        """, {"e": experiment_id})

        semantic_edges = scalar(conn, """
          select count(*) from public.oracle_v6_graph_edges
          where generated_by_model='SEMANTIC_BRIDGE_V1'
            and status in ('HYPOTHESIS','DESCRIPTIVE_EVIDENCE','PREDICTIVE_EVIDENCE','CAUSAL_VALIDATED')
        """)
        predictive_transmission = scalar(conn, """
          select count(*) from public.oracle_v6_graph_edges
          where status in ('PREDICTIVE_EVIDENCE','CAUSAL_VALIDATED')
        """)

        calibrated_fundamentals = scalar(conn, """
          select count(*) from public.oracle_v6_fundamental_forecasts
          where calibration_status not in ('NO_EXPECTATION_GAP_CALIBRATION_FAILED_OR_INSUFFICIENT')
            and p_exceed_implied is not null
        """)
        calibrated_gap = scalar(conn, """
          select count(*) from public.oracle_v6_market_expectations
          where p_fundamentals_exceed_expectations is not null
        """)
        forward_signals = scalar(conn, "select count(*) from public.oracle_v6_forward_signals")
        matured = scalar(conn, """
          select count(*) from public.oracle_v6_forward_outcomes
          where matured_at is not null and residual_return_net is not null
        """)
        matured_tickers = scalar(conn, """
          select count(distinct s.ticker)
          from public.oracle_v6_forward_outcomes o
          join public.oracle_v6_forward_signals s on s.id=o.signal_id
          where o.matured_at is not null and o.residual_return_net is not null
        """)

        # Baseline contract requires all four factor families and, specifically,
        # PIT analyst revisions. At present no V6 PIT revisions table exists.
        revisions_table_exists = scalar(conn, """
          select count(*) from information_schema.tables
          where table_schema='public' and table_name ilike '%revision%'
        """) > 0
        baseline_ready = bool(revisions_table_exists)

        blockers = []
        if replicated == 0:
            blockers.append("NO_REPLICATED_DISCOVERY_SIGNALS")
        if semantic_edges == 0:
            blockers.append("NO_SEMANTIC_BRIDGE_OUTPUT")
        if predictive_transmission == 0:
            blockers.append("NO_PREDICTIVE_ECONOMIC_TRANSMISSION")
        if calibrated_fundamentals == 0:
            blockers.append("NO_CALIBRATED_FUNDAMENTAL_EXPECTATION_MODEL")
        if calibrated_gap == 0:
            blockers.append("NO_CALIBRATED_EXPECTATION_GAP")
        if forward_signals == 0:
            blockers.append("NO_FORWARD_SIGNALS")
        if matured < MIN_MATURED_OUTCOMES:
            blockers.append(f"INSUFFICIENT_MATURED_FORWARD_OUTCOMES:{matured}<{MIN_MATURED_OUTCOMES}")
        if matured_tickers < MIN_DISTINCT_TICKERS:
            blockers.append(f"INSUFFICIENT_FORWARD_TICKERS:{matured_tickers}<{MIN_DISTINCT_TICKERS}")
        if not baseline_ready:
            blockers.append("BASELINE_INCOMPLETE_MISSING_PIT_EARNINGS_REVISIONS")

        edge_testable = len(blockers) == 0
        # We intentionally refuse to manufacture an edge estimate before the
        # prerequisites are satisfied. When testable, a later pre-registered
        # statistical comparison must determine NO_EDGE/EDGE_CANDIDATE/VALIDATED.
        edge_state = "EDGE_UNTESTABLE" if not edge_testable else "EDGE_CANDIDATE"

        diagnostics = {
            "model_version": MODEL_VERSION,
            "baseline_contract": BASELINE_CONTRACT,
            "minimum_matured_outcomes": MIN_MATURED_OUTCOMES,
            "minimum_distinct_tickers": MIN_DISTINCT_TICKERS,
            "note": "No alpha claim is permitted while edge_state=EDGE_UNTESTABLE. Zero observations are not evidence of NO_EDGE.",
        }

        conn.execute(text("""
          insert into public.oracle_v6_edge_audit_runs
            (experiment_id,evaluation_as_of,replicated_signal_count,semantic_edge_count,
             predictive_transmission_count,calibrated_fundamental_forecast_count,
             calibrated_expectation_gap_count,forward_signal_count,matured_forward_outcome_count,
             baseline_ready,edge_testable,edge_state,blockers,diagnostics)
          values(:e,:a,:r,:s,:p,:f,:g,:fs,:mo,:b,:t,:state,cast(:blockers as jsonb),cast(:diag as jsonb))
        """), {
            "e": experiment_id,
            "a": evaluation_as_of,
            "r": int(replicated),
            "s": int(semantic_edges),
            "p": int(predictive_transmission),
            "f": int(calibrated_fundamentals),
            "g": int(calibrated_gap),
            "fs": int(forward_signals),
            "mo": int(matured),
            "b": baseline_ready,
            "t": edge_testable,
            "state": edge_state,
            "blockers": json.dumps(blockers),
            "diag": json.dumps(diagnostics, sort_keys=True),
        })

    result = {
        "ok": True,
        "model_version": MODEL_VERSION,
        "experiment_id": experiment_id,
        "evaluation_as_of": evaluation_as_of.isoformat() if evaluation_as_of else None,
        "replicated_signal_count": int(replicated),
        "semantic_edge_count": int(semantic_edges),
        "predictive_transmission_count": int(predictive_transmission),
        "calibrated_fundamental_forecast_count": int(calibrated_fundamentals),
        "calibrated_expectation_gap_count": int(calibrated_gap),
        "forward_signal_count": int(forward_signals),
        "matured_forward_outcome_count": int(matured),
        "matured_forward_tickers": int(matured_tickers),
        "baseline_ready": baseline_ready,
        "edge_testable": edge_testable,
        "edge_state": edge_state,
        "blockers": blockers,
    }
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    run(os.environ.get("ORACLE_SUPABASE_DB_URL", ""))
