#!/usr/bin/env python3
"""ORACLE V6 deterministic PIT reverse DCF.

This stage estimates what constant five-year FCF growth rate is implied by the
current enterprise value. It is a market-expectations measurement, not a price
target and not an investment recommendation. It writes no probability of
outperformance and no forward fundamental forecast claim.

Required PIT inputs at evaluation_as_of:
- latest raw monthly close known by evaluation time;
- latest annual SEC FCF snapshot;
- latest complete SEC position snapshot (shares, cash, debt).

Default assumptions are explicit and versioned: 10% discount rate, 2.5%
terminal growth, 5-year explicit horizon. The implied FCF CAGR is solved by
bisection only when a root exists in [-50%, +200%].
"""
from __future__ import annotations

import json
import math
import os
from decimal import Decimal
from sqlalchemy import create_engine, text

MODEL_VERSION = "REVERSE_DCF_IMPLIED_FCF_GROWTH_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
FCF_MODEL = "SEC_FCF_ANNUAL_V1"
POSITION_MODEL = "SEC_POSITION_V1"
WACC = 0.10
TERMINAL_GROWTH = 0.025
HORIZON_YEARS = 5
LOW_G = -0.50
HIGH_G = 2.00


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def _enterprise_value_from_growth(fcf0: float, g: float) -> float:
    if fcf0 <= 0 or WACC <= TERMINAL_GROWTH:
        return math.nan
    pv = 0.0
    fcf = fcf0
    for year in range(1, HORIZON_YEARS + 1):
        fcf *= 1.0 + g
        pv += fcf / ((1.0 + WACC) ** year)
    terminal = fcf * (1.0 + TERMINAL_GROWTH) / (WACC - TERMINAL_GROWTH)
    pv += terminal / ((1.0 + WACC) ** HORIZON_YEARS)
    return pv


def _solve_implied_growth(fcf0: float, target_ev: float) -> float | None:
    if fcf0 <= 0 or target_ev <= 0:
        return None
    lo, hi = LOW_G, HIGH_G
    f_lo = _enterprise_value_from_growth(fcf0, lo) - target_ev
    f_hi = _enterprise_value_from_growth(fcf0, hi) - target_ev
    if not math.isfinite(f_lo) or not math.isfinite(f_hi) or f_lo * f_hi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        f_mid = _enterprise_value_from_growth(fcf0, mid) - target_ev
        if abs(f_mid) <= max(1.0, target_ev * 1e-9):
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2.0


def run(db_url: str) -> dict:
    engine = _engine(db_url)
    run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id,(metrics->>'decision_as_of')::timestamptz signal_available_at
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp:
            raise RuntimeError("latest formal experiment unavailable")
        experiment_id = int(exp["id"])

        cutoff = None
        if run_id:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:experiment_id and external_run_id=:run_id
            """), {"experiment_id": experiment_id, "run_id": run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:experiment_id
                order by evaluation_as_of desc,id desc limit 1
            """), {"experiment_id": experiment_id}).scalar_one_or_none()
        if cutoff is None:
            raise RuntimeError("no evaluation clock")

        tickers = [str(x) for x in conn.execute(text("""
            select distinct ticker from public.oracle_v6_company_capture
            where model_version=:capture_model and as_of=:cutoff
            order by ticker
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).scalars().all()]

        rows = conn.execute(text("""
            with candidates as (
              select unnest(cast(:tickers as text[])) ticker
            ), price as (
              select distinct on (p.ticker)
                     p.ticker,p.close::double precision close,p.known_at,p.price_month,p.source_code
              from public.oracle_v5_monthly_prices p
              join candidates c on c.ticker=p.ticker
              where p.known_at<=:cutoff and p.close is not null and p.close>0
              order by p.ticker,p.known_at desc,p.price_month desc
            ), fcf as (
              select distinct on (f.ticker)
                     f.ticker,f.free_cash_flow::double precision free_cash_flow,
                     f.as_of fcf_as_of,f.fiscal_period_end fcf_period_end,f.source_accessions
              from public.oracle_v6_fcf_snapshots f
              join candidates c on c.ticker=f.ticker
              where f.model_version=:fcf_model and f.as_of<=:cutoff
              order by f.ticker,f.fiscal_period_end desc,f.as_of desc
            ), pos as (
              select distinct on (p.ticker)
                     p.ticker,p.shares_outstanding::double precision shares_outstanding,
                     p.cash::double precision cash,p.debt::double precision debt,
                     p.as_of position_as_of,p.fiscal_period_end position_period_end,p.source_components
              from public.oracle_v6_position_snapshots p
              join candidates c on c.ticker=p.ticker
              where p.model_version=:position_model and p.as_of<=:cutoff
              order by p.ticker,p.fiscal_period_end desc,p.as_of desc
            )
            select c.ticker,price.close,price.known_at price_known_at,price.price_month,price.source_code,
                   fcf.free_cash_flow,fcf.fcf_as_of,fcf.fcf_period_end,fcf.source_accessions,
                   pos.shares_outstanding,pos.cash,pos.debt,pos.position_as_of,pos.position_period_end,pos.source_components
            from candidates c
            join price using(ticker)
            join fcf using(ticker)
            join pos using(ticker)
            order by c.ticker
        """), {
            "tickers": tickers,
            "cutoff": cutoff,
            "fcf_model": FCF_MODEL,
            "position_model": POSITION_MODEL,
        }).mappings().all()

        payload = []
        out_of_range = []
        for r in rows:
            price = float(r["close"])
            shares = float(r["shares_outstanding"])
            cash = float(r["cash"])
            debt = float(r["debt"])
            fcf0 = float(r["free_cash_flow"])
            market_cap = price * shares
            enterprise_value = market_cap + debt - cash
            implied_g = _solve_implied_growth(fcf0, enterprise_value)
            if implied_g is None:
                out_of_range.append(str(r["ticker"]))
                continue
            assumptions = {
                "discount_rate": WACC,
                "terminal_growth": TERMINAL_GROWTH,
                "explicit_horizon_years": HORIZON_YEARS,
                "growth_solve_bounds": [LOW_G, HIGH_G],
                "valuation_target": "enterprise_value",
                "price_input": "latest raw monthly close known by evaluation_as_of",
                "fcf_definition": "annual SEC CFO minus capex",
            }
            implied = {
                "implied_constant_fcf_cagr_5y": implied_g,
                "enterprise_value": enterprise_value,
                "market_cap": market_cap,
                "price": price,
                "shares_outstanding": shares,
                "cash": cash,
                "debt": debt,
                "base_free_cash_flow": fcf0,
            }
            historical_context = {
                "state": "NO_CALIBRATED_FORWARD_FUNDAMENTAL_FORECAST",
                "claim": "reverse DCF expectation measurement only",
                "signal_available_at": exp["signal_available_at"].isoformat() if exp["signal_available_at"] else None,
                "evaluation_as_of": cutoff.isoformat(),
                "price_known_at": r["price_known_at"].isoformat(),
                "fcf_as_of": r["fcf_as_of"].isoformat(),
                "position_as_of": r["position_as_of"].isoformat(),
                "fcf_period_end": r["fcf_period_end"].isoformat(),
                "position_period_end": r["position_period_end"].isoformat(),
                "source_code": r["source_code"],
            }
            payload.append({
                "ticker": str(r["ticker"]),
                "as_of": cutoff,
                "assumptions": json.dumps(assumptions, sort_keys=True),
                "implied": json.dumps(implied, sort_keys=True),
                "forecast": json.dumps(historical_context, sort_keys=True),
                "gap": json.dumps({"state":"NO_GAP_UNTIL_FORWARD_FORECAST_CALIBRATED"}, sort_keys=True),
                "model": MODEL_VERSION,
            })

        conn.execute(text("delete from public.oracle_v6_market_expectations where model_version=:model and as_of=:cutoff"), {
            "model": MODEL_VERSION, "cutoff": cutoff,
        })
        if payload:
            conn.execute(text("""
                insert into public.oracle_v6_market_expectations
                  (ticker,as_of,reverse_dcf_assumptions,implied_fundamentals,fundamental_forecast,
                   p_fundamentals_exceed_expectations,gap_magnitude,model_version)
                values
                  (:ticker,:as_of,cast(:assumptions as jsonb),cast(:implied as jsonb),cast(:forecast as jsonb),
                   null,cast(:gap as jsonb),:model)
            """), payload)

        summary = {
            "model_version": MODEL_VERSION,
            "evaluation_as_of": cutoff.isoformat(),
            "candidate_tickers": len(tickers),
            "complete_pit_input_tickers": len(rows),
            "reverse_dcf_rows_written": len(payload),
            "out_of_growth_solve_range": out_of_range,
            "probabilities_written": 0,
            "forward_forecasts_written": 0,
            "state": "REVERSE_DCF_EXPECTATIONS_ONLY_NO_FORWARD_GAP_MODEL" if payload else "NO_REVERSE_DCF_COMPLETE_PIT_INPUTS",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{reverse_dcf}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
