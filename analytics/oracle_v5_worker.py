#!/usr/bin/env python3
"""ORACLE V5 external walk-forward analytics.

This worker is intentionally independent from the live Supabase database.
Selections are frozen as strict point-in-time snapshots under
``data/v5_ranked_picks/*.json``. Market prices are fetched outside Supabase and
only the compact result is committed for the investor cockpit.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

PICKS_DIR = Path("data/v5_ranked_picks")
OUT = Path("data/v5_analytics.json")


def fetch_json(url: str, attempts: int = 4, timeout: int = 30) -> dict:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 ORACLE-V5-Analytics/2.0",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            if i + 1 < attempts:
                time.sleep(1.5 + i * 2)
    raise RuntimeError(f"GET failed: {url}: {last}")


def month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def safe_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def avg(xs):
    return statistics.fmean(xs) if xs else None


def med(xs):
    return statistics.median(xs) if xs else None


def trimmed90(xs):
    if not xs:
        return None
    ys = sorted(xs)
    k = max(0, int(len(ys) * 0.05))
    zs = ys[k:len(ys)-k] if len(ys) - 2*k > 0 else ys
    return avg(zs)


def load_frozen_picks():
    rows = []
    files = sorted(PICKS_DIR.glob("*.json"))
    if not files:
        raise RuntimeError("No frozen V5 ranked-pick snapshots found")
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("strict_pit") is not True or payload.get("models_predefined") is not True:
            raise RuntimeError(f"Snapshot integrity gate failed: {path}")
        for row in payload.get("picks", []):
            if len(row) < 4:
                raise RuntimeError(f"Malformed pick in {path}: {row}")
            rows.append({
                "as_of_date": str(row[0]),
                "model": str(row[1]),
                "ticker": str(row[2]).upper(),
                "rank": int(row[3]),
            })
    return files, rows


def yahoo_symbol(ticker: str) -> str:
    # Yahoo convention for class shares, e.g. BRK-B.
    return ticker.upper().replace(".", "-")


def yahoo_history(ticker: str) -> dict[date, float]:
    symbol = urllib.parse.quote(yahoo_symbol(ticker), safe="-")
    start = int(datetime(2016, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int(datetime.now(timezone.utc).timestamp()) + 86400
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={start}&period2={end}&interval=1d&events=history"
        "&includeAdjustedClose=true"
    )
    payload = fetch_json(url)
    result = (((payload.get("chart") or {}).get("result") or [None])[0])
    if not result:
        return {}
    stamps = result.get("timestamp") or []
    adj = (((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [])
    close = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    out = {}
    for i, ts in enumerate(stamps):
        px = safe_float(adj[i] if i < len(adj) else None)
        if px is None:
            px = safe_float(close[i] if i < len(close) else None)
        if px is not None and px > 0:
            out[datetime.fromtimestamp(ts, timezone.utc).date()] = px
    return out


def latest_before(history, d):
    candidates = [(k, v) for k, v in history.items() if k < d]
    return max(candidates, default=(None, None), key=lambda x: x[0])


def latest_on_or_before(history, d):
    candidates = [(k, v) for k, v in history.items() if k <= d]
    return max(candidates, default=(None, None), key=lambda x: x[0])


def outcome(histories, ticker: str, as_of: date):
    h = histories.get(ticker.upper(), {})
    entry_date, entry = latest_before(h, as_of)
    target = month_add(as_of, 6)
    exit_date, exit_px = latest_on_or_before(h, target)
    # Refuse an incomplete future horizon. This prevents current prices being
    # silently substituted for an outcome that has not matured yet.
    if target > datetime.now(timezone.utc).date():
        return None
    if not entry or not exit_px:
        return None
    return {
        "return_6m": 100.0 * (exit_px / entry - 1.0),
        "entry_date": entry_date.isoformat(),
        "exit_date": exit_date.isoformat(),
    }


def stats(picks):
    alphas = [p["alpha_6m"] for p in picks if p.get("alpha_6m") is not None]
    return {
        "n": len(alphas),
        "avg_alpha_6m": avg(alphas),
        "median_alpha_6m": med(alphas),
        "win_rate_vs_qqq": 100.0 * sum(a > 0 for a in alphas) / len(alphas) if alphas else None,
        "trimmed_alpha_90pct": trimmed90(alphas),
        "best_alpha": max(alphas) if alphas else None,
        "worst_alpha": min(alphas) if alphas else None,
    }


def regime(d):
    if d.year <= 2021:
        return "2017_2021"
    if d.year <= 2025:
        return "2022_2025"
    return "2026_FORWARD"


def main():
    files, frozen = load_frozen_picks()
    needed = {"QQQ"} | {p["ticker"] for p in frozen}

    histories = {}
    failures = []
    for i, ticker in enumerate(sorted(needed)):
        try:
            hist = yahoo_history(ticker)
            if hist:
                histories[ticker] = hist
            else:
                failures.append({"ticker": ticker, "error": "NO_PRICE_HISTORY"})
        except Exception as e:
            failures.append({"ticker": ticker, "error": str(e)[:180]})
        if i and i % 15 == 0:
            time.sleep(1.0)

    qqq_cache = {}
    picks_by_model = defaultdict(list)
    for p in frozen:
        as_of = date.fromisoformat(p["as_of_date"][:10])
        if as_of not in qqq_cache:
            qqq_cache[as_of] = outcome(histories, "QQQ", as_of)
        qqq = qqq_cache[as_of]
        ret = outcome(histories, p["ticker"], as_of)
        if not qqq or not ret:
            continue
        picks_by_model[p["model"]].append({
            **p,
            "return_6m": ret["return_6m"],
            "qqq_return_6m": qqq["return_6m"],
            "alpha_6m": ret["return_6m"] - qqq["return_6m"],
            "entry_date": ret["entry_date"],
            "exit_date": ret["exit_date"],
            "regime": regime(as_of),
        })

    models = {}
    for model, picks in sorted(picks_by_model.items()):
        overall = stats(picks)
        regimes = {
            rg: stats([p for p in picks if p["regime"] == rg])
            for rg in ["2017_2021", "2022_2025", "2026_FORWARD"]
        }
        validated = (
            overall["n"] >= 100
            and (overall["median_alpha_6m"] or -999) > 0
            and (overall["win_rate_vs_qqq"] or 0) > 55
            and (overall["trimmed_alpha_90pct"] or -999) > 0
            and all(
                regimes[rg]["n"] < 25 or (regimes[rg]["median_alpha_6m"] or -999) > 0
                for rg in ["2017_2021", "2022_2025"]
            )
        )
        models[model] = {
            "status": "VALIDATED" if validated else "RESEARCH_ONLY",
            "overall": overall,
            "regimes": regimes,
            "latest_picks": sorted(
                picks, key=lambda x: (x["as_of_date"], -x["rank"]), reverse=True
            )[:10],
        }

    result = {
        "ok": True,
        "engine": "ORACLE_V5_EXTERNAL_WORKER_3_STATIC_PIT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strict_pit": True,
        "supabase_dependency_for_backtest": False,
        "counts": {
            "snapshot_files": len(files),
            "frozen_picks": len(frozen),
            "price_tickers_requested": len(needed),
            "price_tickers_loaded": len(histories),
            "price_failures": len(failures),
        },
        "market_data": {
            "provider": "YAHOO_CHART",
            "frequency": "DAILY_ADJUSTED",
        },
        "methodology": {
            "top_n_per_quarter": 5,
            "horizon_months": 6,
            "entry": "last trading close strictly before decision date",
            "exit": "last trading close on or before decision date + 6 calendar months",
            "benchmark": "QQQ",
            "promotion_gate": "N>=100; median alpha>0; win-rate>55%; trimmed alpha>0; regime stability",
            "selection_formula_frozen_before_outcomes": True,
            "fundamentals_in_model": False,
            "note": "SEC PIT fundamentals remain a separate gate until historical coverage is sufficient.",
        },
        "models": models,
        "price_failures": failures[:50],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({m: models[m]["overall"] for m in models}, indent=2))
    print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    main()
