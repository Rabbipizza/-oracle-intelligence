#!/usr/bin/env python3
"""ORACLE V6 SEC Companyfacts cash-flow PIT ingestion.

Scope is deliberately narrow: only tickers already admitted by the V6 company-
capture evidence gate. Raw XBRL cash-flow facts are preserved with accession,
period, filed date, and a conservative availability timestamp. Annual FCF is
materialized only when operating cash flow and capex refer to the same period
end and are both present in 10-K/10-K/A data.

Because SEC Companyfacts exposes `filed` as a date rather than an acceptance
timestamp, availability is conservatively set to 00:00 UTC on the following
day. This avoids pretending the fact was available before we can prove it.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text

MODEL_VERSION = "SEC_FCF_ANNUAL_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
SEC_BASE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
USER_AGENT = os.environ.get(
    "ORACLE_SEC_USER_AGENT",
    "ORACLE-V6 research https://github.com/Rabbipizza/-oracle-intelligence",
)

CFO_TAGS = (
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
)
CAPEX_TAGS = (
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsForAdditionsToPropertyPlantAndEquipment",
)
WANTED_TAGS = CFO_TAGS + CAPEX_TAGS


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _availability_from_filed(filed: date) -> datetime:
    # Companyfacts lacks filing acceptance time. Next-day midnight UTC is a
    # transparent conservative approximation and is tagged as estimated.
    return datetime.combine(filed + timedelta(days=1), dtime.min, tzinfo=timezone.utc)


def _fetch_companyfacts(cik: str) -> dict[str, Any]:
    url = SEC_BASE.format(cik=str(cik).zfill(10))
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _iter_fact_rows(ticker: str, cik: str, payload: dict[str, Any]):
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    source_url = SEC_BASE.format(cik=str(cik).zfill(10))
    for concept in WANTED_TAGS:
        node = us_gaap.get(concept)
        if not node:
            continue
        units = node.get("units", {})
        # Cash-flow statement values should be USD. We intentionally do not
        # convert other units or infer missing currencies.
        for item in units.get("USD", []):
            filed = _parse_date(item.get("filed"))
            end = _parse_date(item.get("end"))
            start = _parse_date(item.get("start"))
            val = item.get("val")
            if filed is None or end is None or val is None:
                continue
            form = str(item.get("form") or "")
            if form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                continue
            yield {
                "ticker": ticker,
                "cik": str(cik).zfill(10),
                "concept": concept,
                "unit": "USD",
                "period_start": start,
                "period_end": end,
                "filed_date": filed,
                "available_at": _availability_from_filed(filed),
                "accession": item.get("accn"),
                "form": form,
                "fiscal_year": item.get("fy"),
                "fiscal_period": item.get("fp"),
                "frame": item.get("frame"),
                "value": Decimal(str(val)),
                "source_url": source_url,
                "availability_quality": "ESTIMATED_CONSERVATIVE_FROM_FILED_DATE",
                "metadata": json.dumps({
                    "taxonomy": "us-gaap",
                    "sec_entity_name": payload.get("entityName"),
                    "raw_tag": concept,
                    "availability_rule": "filed_date_plus_one_day_00_00_utc",
                }, sort_keys=True),
            }


def _materialize_annual_fcf(conn, tickers: list[str]) -> int:
    if not tickers:
        return 0
    rows = conn.execute(text("""
        with eligible as (
          select f.*,
                 case when f.concept = any(:cfo_tags) then 'CFO'
                      when f.concept = any(:capex_tags) then 'CAPEX' end kind,
                 row_number() over (
                   partition by f.ticker,f.period_end,
                     case when f.concept = any(:cfo_tags) then 'CFO' else 'CAPEX' end
                   order by
                     case when f.form='10-K' then 0 else 1 end,
                     f.available_at asc,
                     f.id asc
                 ) rn
          from public.oracle_v6_sec_cashflow_facts f
          where f.ticker=any(:tickers)
            and f.form in ('10-K','10-K/A')
            and f.period_start is not null
            and (f.period_end - f.period_start) between 300 and 430
            and (f.concept=any(:cfo_tags) or f.concept=any(:capex_tags))
        ), picked as (
          select * from eligible where rn=1
        )
        select c.ticker,c.period_end,
               c.value operating_cash_flow,
               x.value capex,
               c.value-x.value free_cash_flow,
               greatest(c.available_at,x.available_at) as_of,
               jsonb_build_array(
                 jsonb_build_object('concept',c.concept,'accession',c.accession,'available_at',c.available_at),
                 jsonb_build_object('concept',x.concept,'accession',x.accession,'available_at',x.available_at)
               ) source_accessions
        from picked c
        join picked x on x.ticker=c.ticker and x.period_end=c.period_end
        where c.kind='CFO' and x.kind='CAPEX'
          and x.value>=0
        order by c.ticker,c.period_end
    """), {"tickers": tickers, "cfo_tags": list(CFO_TAGS), "capex_tags": list(CAPEX_TAGS)}).mappings().all()

    conn.execute(text("delete from public.oracle_v6_fcf_snapshots where model_version=:model and ticker=any(:tickers)"), {
        "model": MODEL_VERSION, "tickers": tickers,
    })
    if rows:
        conn.execute(text("""
            insert into public.oracle_v6_fcf_snapshots
              (ticker,as_of,fiscal_period_end,operating_cash_flow,capex,free_cash_flow,
               source_accessions,source_quality,model_version,metadata)
            values
              (:ticker,:as_of,:period_end,:operating_cash_flow,:capex,:free_cash_flow,
               :source_accessions,'SEC_COMPANYFACTS_PIT_CONSERVATIVE',:model_version,
               jsonb_build_object('fcf_definition','operating_cash_flow_minus_capex',
                                  'annual_period_required',true,
                                  'availability_quality','ESTIMATED_CONSERVATIVE_FROM_FILED_DATE'))
        """), [dict(r, model_version=MODEL_VERSION) for r in rows])
    return len(rows)


def run(db_url: str) -> dict[str, Any]:
    engine = _engine(db_url)
    fetched = 0
    failed: list[dict[str, str]] = []
    inserted_facts = 0

    with engine.begin() as conn:
        targets = conn.execute(text("""
            select distinct c.ticker,u.cik
            from public.oracle_v6_company_capture c
            join public.oracle_v5_universe u on u.ticker=c.ticker
            where c.model_version=:capture_model
              and u.cik is not null and btrim(u.cik)<>''
            order by c.ticker
        """), {"capture_model": CAPTURE_MODEL}).mappings().all()

    for target in targets:
        ticker = str(target["ticker"])
        cik = str(target["cik"])
        try:
            payload = _fetch_companyfacts(cik)
            facts = list(_iter_fact_rows(ticker, cik, payload))
            with engine.begin() as conn:
                if facts:
                    result = conn.execute(text("""
                        insert into public.oracle_v6_sec_cashflow_facts
                          (ticker,cik,concept,unit,period_start,period_end,filed_date,available_at,
                           accession,form,fiscal_year,fiscal_period,frame,value,source_url,
                           availability_quality,metadata)
                        values
                          (:ticker,:cik,:concept,:unit,:period_start,:period_end,:filed_date,:available_at,
                           :accession,:form,:fiscal_year,:fiscal_period,:frame,:value,:source_url,
                           :availability_quality,cast(:metadata as jsonb))
                        on conflict do nothing
                    """), facts)
                    inserted_facts += max(result.rowcount or 0, 0)
            fetched += 1
        except Exception as exc:  # keep one issuer failure from destroying the whole family
            failed.append({"ticker": ticker, "error": type(exc).__name__})
        time.sleep(0.12)

    tickers = [str(t["ticker"]) for t in targets]
    with engine.begin() as conn:
        fcf_rows = _materialize_annual_fcf(conn, tickers)
        coverage = conn.execute(text("""
            select count(distinct ticker) tickers,
                   count(*) snapshots,
                   min(as_of) min_as_of,
                   max(as_of) max_as_of
            from public.oracle_v6_fcf_snapshots
            where model_version=:model and ticker=any(:tickers)
        """), {"model": MODEL_VERSION, "tickers": tickers}).mappings().one()

        exp = conn.execute(text("""
            select id from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
            order by created_at desc,id desc limit 1
        """)).scalar_one_or_none()
        summary = {
            "model_version": MODEL_VERSION,
            "target_tickers": len(targets),
            "issuers_fetched": fetched,
            "issuer_failures": failed,
            "raw_facts_inserted_this_run": inserted_facts,
            "annual_fcf_snapshots": int(coverage["snapshots"] or 0),
            "tickers_with_annual_fcf": int(coverage["tickers"] or 0),
            "availability_quality": "ESTIMATED_CONSERVATIVE_FROM_FILED_DATE",
            "fcf_definition": "CFO minus capex, same annual SEC period",
        }
        if exp is not None:
            conn.execute(text("""
                update public.oracle_v6_experiments
                set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_cashflow_pit}',cast(:summary as jsonb),true)
                where id=:experiment_id
            """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": int(exp)})

    return {"ok": True, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
