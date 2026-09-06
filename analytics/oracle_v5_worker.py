#!/usr/bin/env python3
"""ORACLE V5 external analytics worker.

Supabase supplies only the compact PIT feature store. Heavy price retrieval and
walk-forward calculations happen outside Supabase. Results are committed as a
static JSON artifact for the investor cockpit.

Model weights in this file are predefined; they are not tuned after observing
worker results.
"""
from __future__ import annotations

import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

EXPORT_URL = "https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-analytics-export"
OUT = Path("data/v5_analytics.json")


def fetch_json(url: str, attempts: int = 5, timeout: int = 45) -> dict:
    last = None
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 ORACLE-V5-Analytics/1.2",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            if i + 1 < attempts:
                time.sleep(2 + i * 3)
    raise RuntimeError(f"GET failed after {attempts} attempts: {url}: {last}")


def get_features(limit: int = 100) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        p = fetch_json(f"{EXPORT_URL}?kind=features&offset={offset}&limit={limit}")
        if not p.get("ok"):
            raise RuntimeError(p.get("error", "feature export failed"))
        batch = p.get("rows", [])
        rows.extend(batch)
        nxt = p.get("next_offset")
        if nxt is None:
            break
        offset = int(nxt)
    return rows


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


def pct_rank(values, v):
    xs = sorted(x for x in values if x is not None and math.isfinite(x))
    if not xs or v is None or not math.isfinite(v):
        return 0.0
    return 100.0 * sum(x <= v for x in xs) / len(xs)


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


def model_scores(rows):
    accel = [safe_float(r.get("accel_ratio")) for r in rows]
    src = [safe_float(r.get("source_diversity")) for r in rows]
    sig = [safe_float(r.get("signal_diversity")) for r in rows]
    anc = [safe_float(r.get("anchored_docs")) for r in rows]
    qual = [safe_float(r.get("feature_quality")) for r in rows]

    out = {k: [] for k in [
        "ACCEL_ONLY",
        "ACCEL_EVIDENCE",
        "EARLY_ACCEL",
        "EARLY_QUALITY_MOMENTUM",
    ]}

    for r in rows:
        a = pct_rank(accel, safe_float(r.get("accel_ratio")))
        s = pct_rank(src, safe_float(r.get("source_diversity")))
        g = pct_rank(sig, safe_float(r.get("signal_diversity")))
        h = pct_rank(anc, safe_float(r.get("anchored_docs")))
        q = pct_rank(qual, safe_float(r.get("feature_quality")))
        r6 = safe_float(r.get("prior_return_6m"))
        r12 = safe_float(r.get("prior_return_12m"))

        accel_only = a
        evidence = 0.55*a + 0.15*s + 0.15*g + 0.15*h

        penalty = 0.0
        if r12 is not None and r12 > 60:
            penalty += min(35.0, (r12 - 60) * 0.35)
        if r6 is not None and r6 > 40:
            penalty += min(20.0, (r6 - 40) * 0.30)

        momentum = 50.0
        if r6 is not None:
            if 0 <= r6 <= 40:
                momentum = 80.0
            elif -20 <= r6 < 0:
                momentum = 60.0
            elif 40 < r6 <= 70:
                momentum = 55.0
            elif r6 > 70:
                momentum = 20.0
            else:
                momentum = 30.0

        early_quality = (
            0.45*a + 0.20*s + 0.10*g + 0.10*h + 0.10*q
            + 0.05*momentum - penalty
        )

        out["ACCEL_ONLY"].append((accel_only, r))
        out["ACCEL_EVIDENCE"].append((evidence, r))
        out["EARLY_ACCEL"].append((evidence - penalty, r))
        out["EARLY_QUALITY_MOMENTUM"].append((early_quality, r))

    return out


def yahoo_symbol(ticker: str) -> str:
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
    payload = fetch_json(url, attempts=4, timeout=30)
    result = (((payload.get("chart") or {}).get("result") or [None])[0])
    if not result:
        return {}
    stamps = result.get("timestamp") or []
    adj = (((result.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose") or [])
    close = (((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or [])
    out: dict[date, float] = {}
    for i, ts in enumerate(stamps):
        px = safe_float(adj[i] if i < len(adj) else None)
        if px is None:
            px = safe_float(close[i] if i < len(close) else None)
        if px is not None and px > 0:
            out[datetime.fromtimestamp(ts, timezone.utc).date()] = px
    return out


def latest_before(history: dict[date, float], d: date):
    candidates = [(k, v) for k, v in history.items() if k < d]
    return max(candidates, default=(None, None), key=lambda x: x[0])


def latest_on_or_before(history: dict[date, float], d: date):
    candidates = [(k, v) for k, v in history.items() if k <= d]
    return max(candidates, default=(None, None), key=lambda x: x[0])


def outcome(histories, ticker: str, as_of: date):
    h = histories.get(ticker.upper(), {})
    entry_date, entry = latest_before(h, as_of)
    exit_date, exit_px = latest_on_or_before(h, month_add(as_of, 6))
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
    features = get_features(limit=100)
    strict = [r for r in features if (r.get("metadata") or {}).get("strict_price_pit") is True]
    if len(strict) != len(features):
        raise RuntimeError(f"strict PIT gate failed: {len(strict)}/{len(features)}")

    by_date = defaultdict(list)
    for r in strict:
        by_date[r["as_of_date"]].append(r)

    ranked_by_model_date = {}
    needed = {"QQQ"}
    for ds, rows in sorted(by_date.items()):
        scores = model_scores(rows)
        for model, ranked in scores.items():
            ranked.sort(key=lambda z: (-z[0], str(z[1].get("ticker"))))
            top = ranked[:5]
            ranked_by_model_date[(model, ds)] = top
            for _, r in top:
                t = str(r.get("ticker") or "").upper()
                if t:
                    needed.add(t)

    histories = {}
    failures = []
    for i, ticker in enumerate(sorted(needed)):
        try:
            h = yahoo_history(ticker)
            if h:
                histories[ticker] = h
            else:
                failures.append({"ticker": ticker, "error": "NO_PRICE_HISTORY"})
        except Exception as e:
            failures.append({"ticker": ticker, "error": str(e)[:180]})
        if i and i % 20 == 0:
            time.sleep(1.0)

    picks_by_model = defaultdict(list)
    for (model, ds), ranked in ranked_by_model_date.items():
        as_of = date.fromisoformat(ds[:10])
        qqq = outcome(histories, "QQQ", as_of)
        if not qqq:
            continue
        for rank, (score, r) in enumerate(ranked, 1):
            ticker = str(r.get("ticker") or "").upper()
            ret = outcome(histories, ticker, as_of)
            if not ret:
                continue
            alpha = ret["return_6m"] - qqq["return_6m"]
            picks_by_model[model].append({
                "as_of_date": ds,
                "ticker": ticker,
                "rank": rank,
                "score": round(score, 4),
                "return_6m": ret["return_6m"],
                "qqq_return_6m": qqq["return_6m"],
                "alpha_6m": alpha,
                "entry_date": ret["entry_date"],
                "exit_date": ret["exit_date"],
                "regime": regime(as_of),
            })

    models = {}
    for model, picks in picks_by_model.items():
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
                picks,
                key=lambda p: (p["as_of_date"], -p["rank"]),
                reverse=True,
            )[:10],
        }

    result = {
        "ok": True,
        "engine": "ORACLE_V5_EXTERNAL_WORKER_2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strict_pit": True,
        "counts": {
            "features": len(features),
            "feature_quarters": len(by_date),
            "price_tickers_requested": len(needed),
            "price_tickers_loaded": len(histories),
            "price_failures": len(failures),
        },
        "market_data": {
            "provider": "YAHOO_CHART",
            "frequency": "DAILY_ADJUSTED",
            "selection_prices_live_db_dependency": False,
        },
        "methodology": {
            "top_n_per_quarter": 5,
            "horizon_months": 6,
            "entry": "last trading close strictly before decision date",
            "exit": "last trading close on or before decision date + 6 calendar months",
            "benchmark": "QQQ",
            "promotion_gate": "N>=100; median alpha>0; win-rate>55%; trimmed alpha>0; regime stability",
            "weights_predefined": True,
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
