#!/usr/bin/env python3
"""ORACLE V6 SEC Companyfacts PIT position ingestion.

Fetches only currently investable company-capture candidates. It preserves raw
SEC facts for shares, cash and debt, then materializes a position snapshot only
when all required components can be supported at a common fiscal period end.
No proxy from narrative evidence is allowed.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, text

MODEL_VERSION = "SEC_POSITION_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
SEC_BASE = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
USER_AGENT = os.environ.get(
    "ORACLE_SEC_USER_AGENT",
    "ORACLE-V6 research https://github.com/Rabbipizza/-oracle-intelligence",
)

# Ordered by preference within each economic component.
CASH_TAGS = (
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
    ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
)
SHARES_TAGS = (
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStocksIncludingAdditionalPaidInCapitalMember"),
)
CURRENT_DEBT_TAGS = (
    ("us-gaap", "LongTermDebtCurrent"),
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsCurrent"),
    ("us-gaap", "ShortTermDebtCurrent"),
)
NONCURRENT_DEBT_TAGS = (
    ("us-gaap", "LongTermDebtNoncurrent"),
    ("us-gaap", "LongTermDebtAndFinanceLeaseObligationsNoncurrent"),
)
SHORT_BORROWING_TAGS = (
    ("us-gaap", "ShortTermBorrowings"),
)
ALL_TAGS = CASH_TAGS + SHARES_TAGS + CURRENT_DEBT_TAGS + NONCURRENT_DEBT_TAGS + SHORT_BORROWING_TAGS


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
    return datetime.combine(filed + timedelta(days=1), dtime.min, tzinfo=timezone.utc)


def _fetch_companyfacts(cik: str) -> dict[str, Any]:
    url = SEC_BASE.format(cik=str(cik).zfill(10))
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "identity",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _expected_unit(taxonomy: str, concept: str) -> str:
    return "shares" if (taxonomy, concept) in SHARES_TAGS else "USD"


def _iter_rows(ticker: str, cik: str, payload: dict[str, Any]):
    source_url = SEC_BASE.format(cik=str(cik).zfill(10))
    for taxonomy, concept in ALL_TAGS:
        node = payload.get("facts", {}).get(taxonomy, {}).get(concept)
        if not node:
            continue
        unit = _expected_unit(taxonomy, concept)
        for item in node.get("units", {}).get(unit, []):
            filed = _parse_date(item.get("filed"))
            end = _parse_date(item.get("end"))
            val = item.get("val")
            form = str(item.get("form") or "")
            if filed is None or end is None or val is None:
                continue
            if form not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                continue
            yield {
                "ticker": ticker,
                "cik": str(cik).zfill(10),
                "taxonomy": taxonomy,
                "concept": concept,
                "unit": unit,
                "period_end": end,
                "filed_date": filed,
                "available_at": _availability_from_filed(filed),
                "accession": item.get("accn"),
                "form": form,
                "fiscal_year": item.get("fy"),
                "fiscal_period": item.get("fp"),
                "value": Decimal(str(val)),
                "source_url": source_url,
                "availability_quality": "ESTIMATED_CONSERVATIVE_FROM_FILED_DATE",
                "metadata": json.dumps({
                    "sec_entity_name": payload.get("entityName"),
                    "availability_rule": "filed_date_plus_one_day_00_00_utc",
                }, sort_keys=True),
            }


def _component(tags: tuple[tuple[str,str], ...], facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    for taxonomy, concept in tags:
        eligible = [f for f in facts if f["taxonomy"] == taxonomy and f["concept"] == concept]
        if eligible:
            return sorted(eligible, key=lambda r: (r["available_at"], r["filed_date"]))[0]
    return None


def _materialize(conn, tickers: list[str], cutoff: datetime) -> int:
    if not tickers:
        return 0
    rows = conn.execute(text("""
        select ticker,taxonomy,concept,unit,period_end,filed_date,available_at,
               accession,form,fiscal_year,fiscal_period,value,source_url
        from public.oracle_v6_sec_position_facts
        where ticker=any(:tickers) and available_at<=:cutoff
        order by ticker,period_end,available_at,id
    """), {"tickers": tickers, "cutoff": cutoff}).mappings().all()

    by_period: dict[tuple[str,date], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_period[(str(r["ticker"]), r["period_end"])].append(dict(r))

    snapshots = []
    for (ticker, period_end), facts in by_period.items():
        cash = _component(CASH_TAGS, facts)
        shares = _component(SHARES_TAGS, facts)
        debt_current = _component(CURRENT_DEBT_TAGS, facts)
        debt_noncurrent = _component(NONCURRENT_DEBT_TAGS, facts)
        short_borrow = _component(SHORT_BORROWING_TAGS, facts)
        if cash is None or shares is None:
            continue
        debt_parts = [x for x in (debt_current, debt_noncurrent, short_borrow) if x is not None]
        if not debt_parts:
            continue
        debt = sum((Decimal(str(x["value"])) for x in debt_parts), Decimal("0"))
        components = [cash, shares] + debt_parts
        as_of = max(x["available_at"] for x in components)
        snapshots.append({
            "ticker": ticker,
            "as_of": as_of,
            "period_end": period_end,
            "shares": Decimal(str(shares["value"])),
            "cash": Decimal(str(cash["value"])),
            "debt": debt,
            "source_components": json.dumps([
                {
                    "taxonomy": x["taxonomy"], "concept": x["concept"],
                    "accession": x["accession"], "available_at": x["available_at"].isoformat(),
                } for x in components
            ], sort_keys=True),
        })

    # Keep only one snapshot per ticker/period and all historical periods for PIT.
    conn.execute(text("delete from public.oracle_v6_position_snapshots where model_version=:model and ticker=any(:tickers)"), {
        "model": MODEL_VERSION, "tickers": tickers,
    })
    if snapshots:
        conn.execute(text("""
            insert into public.oracle_v6_position_snapshots
              (ticker,as_of,fiscal_period_end,shares_outstanding,cash,debt,
               source_components,source_quality,model_version,metadata)
            values
              (:ticker,:as_of,:period_end,:shares,:cash,:debt,cast(:source_components as jsonb),
               'SEC_COMPANYFACTS_PIT_CONSERVATIVE',:model,
               jsonb_build_object('availability_quality','ESTIMATED_CONSERVATIVE_FROM_FILED_DATE',
                                  'debt_definition','preferred current + noncurrent + short borrowing tags'))
        """), [dict(s, model=MODEL_VERSION) for s in snapshots])
    return len(snapshots)


def run(db_url: str) -> dict[str, Any]:
    engine = _engine(db_url)
    run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
            order by created_at desc,id desc limit 1
        """)).scalar_one()
        cutoff = conn.execute(text("""
            select evaluation_as_of from public.oracle_v6_evaluation_runs
            where experiment_id=:exp and (:run_id is null or external_run_id=:run_id)
            order by evaluation_as_of desc,id desc limit 1
        """), {"exp": int(exp), "run_id": run_id}).scalar_one_or_none()
        if cutoff is None:
            raise RuntimeError("no evaluation clock")
        targets = conn.execute(text("""
            select distinct c.ticker,u.cik
            from public.oracle_v6_company_capture c
            join public.oracle_v5_universe u on u.ticker=c.ticker
            where c.model_version=:capture_model and c.as_of=:cutoff
              and u.cik is not null and btrim(u.cik)<>''
            order by c.ticker
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).mappings().all()

    fetched = 0
    failed: list[dict[str,str]] = []
    inserted = 0
    for t in targets:
        ticker,cik = str(t["ticker"]),str(t["cik"])
        try:
            payload = _fetch_companyfacts(cik)
            facts = list(_iter_rows(ticker,cik,payload))
            with engine.begin() as conn:
                if facts:
                    result = conn.execute(text("""
                        insert into public.oracle_v6_sec_position_facts
                          (ticker,cik,taxonomy,concept,unit,period_end,filed_date,available_at,
                           accession,form,fiscal_year,fiscal_period,value,source_url,
                           availability_quality,metadata)
                        values
                          (:ticker,:cik,:taxonomy,:concept,:unit,:period_end,:filed_date,:available_at,
                           :accession,:form,:fiscal_year,:fiscal_period,:value,:source_url,
                           :availability_quality,cast(:metadata as jsonb))
                        on conflict do nothing
                    """), facts)
                    inserted += max(result.rowcount or 0,0)
            fetched += 1
        except Exception as exc:
            failed.append({"ticker":ticker,"error":type(exc).__name__})
        time.sleep(0.12)

    tickers = [str(t["ticker"]) for t in targets]
    with engine.begin() as conn:
        _materialize(conn,tickers,cutoff)
        cov = conn.execute(text("""
            select count(*) snapshots,count(distinct ticker) tickers
            from public.oracle_v6_position_snapshots
            where model_version=:model and as_of<=:cutoff and ticker=any(:tickers)
        """), {"model":MODEL_VERSION,"cutoff":cutoff,"tickers":tickers}).mappings().one()
        summary = {
            "model_version": MODEL_VERSION,
            "evaluation_as_of": cutoff.isoformat(),
            "target_tickers": len(targets),
            "issuers_fetched": fetched,
            "issuer_failures": failed,
            "raw_position_facts_inserted_this_run": inserted,
            "position_snapshots": int(cov["snapshots"] or 0),
            "tickers_with_position": int(cov["tickers"] or 0),
            "availability_quality": "ESTIMATED_CONSERVATIVE_FROM_FILED_DATE",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_position_pit}',cast(:summary as jsonb),true)
            where id=:exp
        """), {"summary":json.dumps(summary,sort_keys=True),"exp":int(exp)})
    return {"ok":True,**summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL","")),sort_keys=True))


if __name__ == "__main__":
    main()
