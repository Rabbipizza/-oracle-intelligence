#!/usr/bin/env python3
"""ORACLE V6 SEC inline-XBRL fallback.

`data.sec.gov` may reject cloud CI runners. This fallback uses SEC filing URLs
already present in ORACLE's PIT raw-document corpus, fetches the primary filing
from www.sec.gov/Archives, parses inline XBRL with the Python standard library,
and stores only exact primary-source facts needed by V6.

Scientific availability is the ORACLE raw-document `available_at`, not the
historical filing date, so this fallback never backdates knowledge.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser

from sqlalchemy import create_engine, text

MODEL_VERSION = "SEC_INLINE_XBRL_FALLBACK_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
USER_AGENT = os.environ.get(
    "ORACLE_SEC_USER_AGENT",
    "ORACLE-V6 research contact https://github.com/Rabbipizza/-oracle-intelligence",
)

CFO = {
    "netcashprovidedbyusedinoperatingactivities",
    "netcashprovidedbyusedinoperatingactivitiescontinuingoperations",
}
CAPEX = {
    "paymentstoacquirepropertyplantandequipment",
    "paymentsforadditionstopropertyplantandequipment",
}
CASH = {
    "cashandcashequivalentsatcarryingvalue",
    "cashcashequivalentsrestrictedcashandrestrictedcashequivalents",
}
SHARES = {"entitycommonstocksharesoutstanding"}
DEBT_CURRENT = {
    "longtermdebtcurrent",
    "longtermdebtandfinanceleaseobligationscurrent",
    "shorttermdebtcurrent",
}
DEBT_NONCURRENT = {
    "longtermdebtnoncurrent",
    "longtermdebtandfinanceleaseobligationsnoncurrent",
}
SHORT_BORROW = {"shorttermborrowings"}
WANTED = CFO | CAPEX | CASH | SHARES | DEBT_CURRENT | DEBT_NONCURRENT | SHORT_BORROW


class InlineXBRLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.contexts: dict[str, dict] = {}
        self._ctx: dict | None = None
        self._ctx_tag_depth = 0
        self._ctx_text_tag: str | None = None
        self._ctx_text: list[str] = []
        self._fact: dict | None = None
        self._fact_depth = 0
        self.facts: list[dict] = []

    @staticmethod
    def _attrs(attrs):
        return {str(k).lower(): v for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        a = self._attrs(attrs)
        if t.endswith(":context") or t == "context":
            self._ctx = {"id": a.get("id"), "start": None, "end": None, "instant": None, "dimensional": False}
            self._ctx_tag_depth = 1
            return
        if self._ctx is not None:
            self._ctx_tag_depth += 1
            if t.endswith(":explicitmember") or t.endswith(":typedmember"):
                self._ctx["dimensional"] = True
            if t.endswith(":startdate") or t.endswith(":enddate") or t.endswith(":instant"):
                self._ctx_text_tag = t.split(":")[-1]
                self._ctx_text = []
            return

        if t in {"ix:nonfraction", "ix:fraction"}:
            name = str(a.get("name") or "")
            local = name.split(":")[-1].lower()
            if local in WANTED:
                self._fact = {
                    "name": name,
                    "local": local,
                    "contextref": a.get("contextref"),
                    "unitref": a.get("unitref"),
                    "scale": a.get("scale"),
                    "sign": a.get("sign"),
                    "text": [],
                    "excluded": 0,
                }
                self._fact_depth = 1
                return
        if self._fact is not None:
            self._fact_depth += 1
            if t == "ix:exclude":
                self._fact["excluded"] += 1

    def handle_endtag(self, tag):
        t = tag.lower()
        if self._ctx is not None:
            if self._ctx_text_tag and t.endswith(":" + self._ctx_text_tag):
                raw = "".join(self._ctx_text).strip()
                try:
                    val = date.fromisoformat(raw)
                except Exception:
                    val = None
                self._ctx[self._ctx_text_tag] = val
                self._ctx_text_tag = None
                self._ctx_text = []
            self._ctx_tag_depth -= 1
            if self._ctx_tag_depth == 0:
                if self._ctx.get("id"):
                    self.contexts[str(self._ctx["id"])] = self._ctx
                self._ctx = None
            return
        if self._fact is not None:
            if t == "ix:exclude" and self._fact["excluded"] > 0:
                self._fact["excluded"] -= 1
            self._fact_depth -= 1
            if self._fact_depth == 0:
                self.facts.append(self._fact)
                self._fact = None

    def handle_data(self, data):
        if self._ctx is not None and self._ctx_text_tag:
            self._ctx_text.append(data)
        if self._fact is not None and self._fact.get("excluded", 0) == 0:
            self._fact["text"].append(data)


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def _numeric(fact: dict) -> Decimal | None:
    raw = html.unescape("".join(fact.get("text") or [])).strip()
    if not raw or raw in {"—", "–", "-", "N/A"}:
        return None
    neg_paren = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw.replace(",", ""))
    if cleaned in {"", "-", "."}:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if neg_paren and value > 0:
        value = -value
    if fact.get("sign") == "-":
        value = -abs(value)
    try:
        scale = int(fact.get("scale") or 0)
    except Exception:
        scale = 0
    return value * (Decimal(10) ** scale)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
    })
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _accession_from_url(url: str) -> str | None:
    m = re.search(r"/data/\d+/(\d+)/", url)
    return m.group(1) if m else None


def _taxonomy_and_concept(name: str) -> tuple[str, str]:
    if ":" in name:
        tax, concept = name.split(":", 1)
        return tax.lower(), concept
    return "unknown", name


def _extract_rows(ticker: str, filing: dict, page: str):
    parser = InlineXBRLParser()
    parser.feed(page)
    filed_date = filing["published_at"].date()
    available_at = filing["available_at"]
    accession = _accession_from_url(filing["url"])
    cashflow_rows, position_rows = [], []
    for fact in parser.facts:
        context = parser.contexts.get(str(fact.get("contextref")))
        if not context or context.get("dimensional"):
            continue
        value = _numeric(fact)
        if value is None:
            continue
        local = fact["local"]
        taxonomy, concept_case = _taxonomy_and_concept(fact["name"])
        if context.get("instant") is not None:
            start = None
            end = context["instant"]
        else:
            start = context.get("start")
            end = context.get("end")
        if end is None:
            continue
        if local in CFO | CAPEX:
            if start is None:
                continue
            cashflow_rows.append({
                "ticker": ticker,
                "cik": filing["cik"],
                "concept": concept_case,
                "unit": "USD",
                "period_start": start,
                "period_end": end,
                "filed_date": filed_date,
                "available_at": available_at,
                "accession": accession,
                "form": "10-K",
                "fiscal_year": end.year,
                "fiscal_period": "FY",
                "frame": None,
                "value": value,
                "source_url": filing["url"],
                "availability_quality": "KNOWN_ORACLE_INGESTION_TIME",
                "metadata": json.dumps({"source":"SEC_INLINE_XBRL","contextref":fact.get("contextref"),"raw_name":fact["name"]}, sort_keys=True),
            })
        elif local in CASH | SHARES | DEBT_CURRENT | DEBT_NONCURRENT | SHORT_BORROW:
            unit = "shares" if local in SHARES else "USD"
            position_rows.append({
                "ticker": ticker,
                "cik": filing["cik"],
                "taxonomy": taxonomy,
                "concept": concept_case,
                "unit": unit,
                "period_end": end,
                "filed_date": filed_date,
                "available_at": available_at,
                "accession": accession,
                "form": "10-K",
                "fiscal_year": end.year,
                "fiscal_period": "FY",
                "value": value,
                "source_url": filing["url"],
                "availability_quality": "KNOWN_ORACLE_INGESTION_TIME",
                "metadata": json.dumps({"source":"SEC_INLINE_XBRL","contextref":fact.get("contextref"),"raw_name":fact["name"]}, sort_keys=True),
            })
    return cashflow_rows, position_rows


def run(db_url: str) -> dict:
    engine = _engine(db_url)
    run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null order by created_at desc,id desc limit 1
        """)).scalar_one()
        if run_id:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:e and external_run_id=cast(:r as text)
                order by evaluation_as_of desc limit 1
            """), {"e": int(exp), "r": run_id}).scalar_one_or_none()
        else:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:e order by evaluation_as_of desc limit 1
            """), {"e": int(exp)}).scalar_one_or_none()
        if cutoff is None:
            raise RuntimeError("no evaluation clock")
        tickers = [str(x) for x in conn.execute(text("""
            select distinct ticker from public.oracle_v6_company_capture
            where model_version=:m and as_of=:c order by ticker
        """), {"m": CAPTURE_MODEL, "c": cutoff}).scalars().all()]
        filings = conn.execute(text("""
            with docs as (
              select substring(d.title from '^([A-Z.\\-]+) ') ticker,
                     d.url,d.published_at,d.available_at,u.cik,
                     row_number() over (
                       partition by substring(d.title from '^([A-Z.\\-]+) ')
                       order by d.published_at desc,d.available_at desc
                     ) rn
              from public.oracle_raw_documents d
              join public.oracle_sources s on s.id=d.source_id
              join public.oracle_v5_universe u
                on u.ticker=substring(d.title from '^([A-Z.\\-]+) ')
              where s.source_type='CORPORATE_SEC'
                and d.title like '% 10-K filed %'
                and substring(d.title from '^([A-Z.\\-]+) ')=any(:tickers)
                and d.available_at<=:cutoff
                and d.url like 'https://www.sec.gov/Archives/edgar/%'
            )
            select ticker,url,published_at,available_at,cik from docs where rn<=3
            order by ticker,rn
        """), {"tickers": tickers, "cutoff": cutoff}).mappings().all()

    cf_inserted = pos_inserted = fetched = 0
    failures = []
    covered = set()
    for filing in filings:
        ticker = str(filing["ticker"])
        try:
            page = _fetch(str(filing["url"]))
            cf, pos = _extract_rows(ticker, dict(filing), page)
            with engine.begin() as conn:
                if cf:
                    rs = conn.execute(text("""
                        insert into public.oracle_v6_sec_cashflow_facts
                          (ticker,cik,concept,unit,period_start,period_end,filed_date,available_at,
                           accession,form,fiscal_year,fiscal_period,frame,value,source_url,
                           availability_quality,metadata)
                        values
                          (:ticker,:cik,:concept,:unit,:period_start,:period_end,:filed_date,:available_at,
                           :accession,:form,:fiscal_year,:fiscal_period,:frame,:value,:source_url,
                           :availability_quality,cast(:metadata as jsonb))
                        on conflict do nothing
                    """), cf)
                    cf_inserted += max(rs.rowcount or 0, 0)
                if pos:
                    rs = conn.execute(text("""
                        insert into public.oracle_v6_sec_position_facts
                          (ticker,cik,taxonomy,concept,unit,period_end,filed_date,available_at,
                           accession,form,fiscal_year,fiscal_period,value,source_url,
                           availability_quality,metadata)
                        values
                          (:ticker,:cik,:taxonomy,:concept,:unit,:period_end,:filed_date,:available_at,
                           :accession,:form,:fiscal_year,:fiscal_period,:value,:source_url,
                           :availability_quality,cast(:metadata as jsonb))
                        on conflict do nothing
                    """), pos)
                    pos_inserted += max(rs.rowcount or 0, 0)
            fetched += 1
            if cf or pos:
                covered.add(ticker)
        except urllib.error.HTTPError as exc:
            failures.append({"ticker":ticker,"url":str(filing["url"]),"status":exc.code})
        except Exception as exc:
            failures.append({"ticker":ticker,"url":str(filing["url"]),"error":type(exc).__name__})
        time.sleep(0.15)

    summary = {
        "model_version": MODEL_VERSION,
        "evaluation_as_of": cutoff.isoformat(),
        "candidate_tickers": len(tickers),
        "filings_attempted": len(filings),
        "filings_fetched": fetched,
        "tickers_with_extracted_facts": len(covered),
        "cashflow_facts_inserted": cf_inserted,
        "position_facts_inserted": pos_inserted,
        "failures": failures,
    }
    with engine.begin() as conn:
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_inline_xbrl_fallback}',cast(:s as jsonb),true)
            where id=:e
        """), {"s": json.dumps(summary,sort_keys=True), "e": int(exp)})
    return {"ok": True, **summary}


def main():
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))

if __name__ == "__main__":
    main()
