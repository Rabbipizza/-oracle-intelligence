#!/usr/bin/env python3
"""Shared, deterministic market and evidence admission rules. No network or orders."""
import math
from datetime import date

CASH_TICKERS = {"CASH", "CASH_CHF"}
MIN_PRICE_ROWS = 22  # 1M relative return and 21-session volatility.
MAX_FX_LAG_DAYS = 4  # ECB weekends and public holidays; never an unlimited carry.
MAX_SNAPSHOT_AGE_DAYS = 4


def iso_date(value):
    try:
        parsed=date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
        return parsed if parsed and parsed.isoformat()==value else None
    except ValueError:
        return None


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def clean_rows(market, ticker):
    rows = (market.get("prices", {}).get(ticker) or {}).get("rows") or []
    return sorted((r for r in rows if isinstance(r, dict) and iso_date(r.get("date")) and positive(r.get("close"))), key=lambda r: r["date"])


def market_date(market):
    rows = clean_rows(market, "QQQ")
    return rows[-1]["date"] if rows else None


def series_quality(market, ticker, as_of, min_rows=MIN_PRICE_ROWS):
    entry = market.get("prices", {}).get(ticker) or {}
    raw = entry.get("rows") or []
    reasons = []
    if str(entry.get("symbol", "")).upper()!=str(ticker).upper() or not entry.get("currency") or not entry.get("exchange"):
        reasons.append("provider_identity_unverified")
    if not raw:
        reasons.append("missing_history")
    if any(not isinstance(r, dict) or not iso_date(r.get("date")) or not positive(r.get("close")) for r in raw):
        reasons.append("invalid_price_row")
    valid = [r for r in clean_rows(market, ticker) if iso_date(as_of) and r["date"] <= as_of]
    dates = [r["date"] for r in valid]
    if len(dates) != len(set(dates)):
        reasons.append("duplicate_price_date")
    if len(valid) < min_rows:
        reasons.append("insufficient_history")
    if not iso_date(as_of):
        reasons.append("missing_valuation_date")
    elif not valid or valid[-1]["date"] != as_of:
        reasons.append("price_date_mismatch")
    errors = [e for e in market.get("errors", []) if e.get("ticker") == ticker]
    if errors:
        reasons.append("provider_error")
    return {"status": "DATA_UNAVAILABLE" if reasons else "AVAILABLE", "reasons": reasons,
            "price_date": valid[-1]["date"] if valid else None, "history_rows": len(valid), "provider_errors": errors}


def dated_value(rows, on_date, key, max_lag=MAX_FX_LAG_DAYS):
    """Use an observed value at/before a date, with an explicit carry limit."""
    day = iso_date(on_date)
    valid = sorted((r for r in rows if isinstance(r, dict) and iso_date(r.get("date")) and positive(r.get(key)) and day and r["date"] <= on_date), key=lambda r: r["date"])
    if not valid or (day - iso_date(valid[-1]["date"])).days > max_lag:
        return None
    return valid[-1][key]


def fx_errors(market, as_of):
    rows = market.get("fx_usd_chf") or []
    reasons = []
    if len(rows) < 2:
        reasons.append("missing_fx_history")
    if any(not isinstance(r, dict) or not iso_date(r.get("date")) or not positive(r.get("chf_per_usd")) for r in rows):
        reasons.append("invalid_fx_row")
    dates = [r.get("date") for r in rows if isinstance(r, dict)]
    if len(dates) != len(set(dates)):
        reasons.append("duplicate_fx_date")
    if dated_value(rows, as_of, "chf_per_usd") is None:
        reasons.append("missing_or_stale_fx")
    if any(e.get("kind") == "fx" for e in market.get("errors", [])):
        reasons.append("fx_provider_error")
    return reasons


def explicit_evidence(evidence, as_of):
    ev_date = iso_date((evidence or {}).get("evidence_date"))
    day = iso_date(as_of)
    automatic_ok = not evidence or evidence.get("validation_method")!="ORACLE_STRICT_PRIMARY_REVALIDATION_V1" or (
        evidence.get("validation_trend_gate_pass") is True and evidence.get("validation_filing_count",0)>=2 and
        len(evidence.get("validation_economic_terms",[]))>=2)
    return bool(automatic_ok and evidence and evidence.get("status") == "PROVEN" and ev_date and day and
                0 <= (day - ev_date).days <= 450 and evidence.get("primary_source") and
                str(evidence.get("source_url", "")).startswith("https://") and evidence.get("invalidation"))


def holdings(ledger):
    return {p.get("ticker") for p in ledger.get("positions", []) if p.get("status") == "OPEN" and p.get("ticker") not in CASH_TICKERS}


def cost_weights(ledger):
    capital = ledger.get("initial_capital_chf")
    if not positive(capital):
        return {}
    out = {}
    for p in ledger.get("positions", []):
        if p.get("status") == "OPEN":
            t = p.get("ticker")
            out[t] = round(out.get(t, 0) + 100 * p.get("allocated_chf", 0) / capital, 6)
    out["CASH_CHF"] = round(100 * ledger.get("cash_chf", 0) / capital, 6)
    return out
