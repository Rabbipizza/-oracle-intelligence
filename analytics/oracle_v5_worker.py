#!/usr/bin/env python3
"""ORACLE V5 external analytics worker.

Heavy walk-forward analytics run outside Supabase. The worker consumes the compact
public V5 analytics export, computes predefined factor models, and writes a static
JSON artifact for the investor cockpit.

No model weights are tuned after observing results in this script.
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

EXPORT_URL = "https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-analytics-export"
OUT = Path("data/v5_analytics.json")


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ORACLE-V5-Analytics/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def month_add(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def pct_rank(values: list[float | None], v: float | None) -> float:
    xs = sorted(x for x in values if x is not None and math.isfinite(x))
    if not xs or v is None or not math.isfinite(v):
        return 0.0
    return 100.0 * sum(x <= v for x in xs) / len(xs)


def safe_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def median(xs):
    return statistics.median(xs) if xs else None


def mean(xs):
    return statistics.fmean(xs) if xs else None


def trimmed_mean_90(xs):
    if not xs:
        return None
    ys = sorted(xs)
    k = max(0, int(len(ys) * 0.05))
    zs = ys[k:len(ys)-k] if len(ys) - 2 * k > 0 else ys
    return mean(zs)


def model_scores(rows: list[dict]) -> dict[str, list[tuple[float, dict]]]:
    accel = [safe_float(r.get("accel_ratio")) for r in rows]
    src = [safe_float(r.get("source_diversity")) for r in rows]
    sig = [safe_float(r.get("signal_diversity")) for r in rows]
    anchor = [safe_float(r.get("anchored_docs")) for r in rows]
    qual = [safe_float(r.get("feature_quality")) for r in rows]
    p6 = [safe_float(r.get("prior_return_6m")) for r in rows]
    p12 = [safe_float(r.get("prior_return_12m")) for r in rows]

    out = {k: [] for k in ["ACCEL_ONLY", "ACCEL_EVIDENCE", "EARLY_ACCEL", "EARLY_QUALITY_MOMENTUM"]}
    for r in rows:
        a = pct_rank(accel, safe_float(r.get("accel_ratio")))
        s = pct_rank(src, safe_float(r.get("source_diversity")))
        g = pct_rank(sig, safe_float(r.get("signal_diversity")))
        h = pct_rank(anchor, safe_float(r.get("anchored_docs")))
        q = pct_rank(qual, safe_float(r.get("feature_quality")))
        r6 = safe_float(r.get("prior_return_6m"))
        r12 = safe_float(r.get("prior_return_12m"))

        # Predefined before observing worker results.
        accel_only = a
        evidence = 0.55 * a + 0.15 * s + 0.15 * g + 0.15 * h

        too_late_pen = 0.0
        if r12 is not None and r12 > 60:
            too_late_pen += min(35.0, (r12 - 60) * 0.35)
        if r6 is not None and r6 > 40:
            too_late_pen += min(20.0, (r6 - 40) * 0.30)
        early_accel = evidence - too_late_pen

        # Moderate positive momentum is preferred; extreme rerating is penalized.
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
        early_quality = 0.45 * a + 0.20 * s + 0.10 * g + 0.10 * h + 0.10 * q + 0.05 * momentum - too_late_pen

        out["ACCEL_ONLY"].append((accel_only, r))
        out["ACCEL_EVIDENCE"].append((evidence, r))
        out["EARLY_ACCEL"].append((early_accel, r))
        out["EARLY_QUALITY_MOMENTUM"].append((early_quality, r))
    return out


def build_price_maps(prices: list[dict]):
    m = defaultdict(dict)
    for p in prices:
        ticker = str(p.get("ticker") or "").upper()
        pm = p.get("price_month")
        px = safe_float(p.get("adjusted_close")) or safe_float(p.get("close"))
        if ticker and pm and px and px > 0:
            m[ticker][pm[:10]] = px
    return m


def latest_before(pm: dict[str, float], d: date):
    target = d.isoformat()
    eligible = [(k, v) for k, v in pm.items() if k < target]
    return max(eligible, default=(None, None), key=lambda x: x[0])


def latest_on_or_before(pm: dict[str, float], d: date):
    target = d.isoformat()
    eligible = [(k, v) for k, v in pm.items() if k <= target]
    return max(eligible, default=(None, None), key=lambda x: x[0])


def outcome(price_map, ticker: str, as_of: date):
    pm = price_map.get(ticker.upper(), {})
    _, entry = latest_before(pm, as_of)
    _, exit6 = latest_on_or_before(pm, month_add(as_of, 6))
    if not entry or not exit6:
        return None
    return 100.0 * (exit6 / entry - 1.0)


def stats(xs: list[dict]):
    alphas = [x["alpha_6m"] for x in xs if x.get("alpha_6m") is not None]
    return {
        "n": len(alphas),
        "avg_alpha_6m": mean(alphas),
        "median_alpha_6m": median(alphas),
        "win_rate_vs_qqq": 100.0 * sum(a > 0 for a in alphas) / len(alphas) if alphas else None,
        "trimmed_alpha_90pct": trimmed_mean_90(alphas),
        "best_alpha": max(alphas) if alphas else None,
        "worst_alpha": min(alphas) if alphas else None,
    }


def regime(as_of: date) -> str:
    if as_of.year <= 2021:
        return "2017_2021"
    if as_of.year <= 2025:
        return "2022_2025"
    return "2026_FORWARD"


def main():
    payload = get_json(EXPORT_URL)
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "analytics export failed"))
    features = payload.get("features", [])
    prices = payload.get("prices", [])
    strict = [r for r in features if (r.get("metadata") or {}).get("strict_price_pit") is True]
    if len(strict) != len(features):
        raise RuntimeError(f"strict PIT gate failed: {len(strict)}/{len(features)} rows")

    by_date = defaultdict(list)
    for r in strict:
        by_date[r["as_of_date"]].append(r)
    price_map = build_price_maps(prices)

    picks_by_model = defaultdict(list)
    for ds, rows in sorted(by_date.items()):
        as_of = date.fromisoformat(ds[:10])
        qqq_ret = outcome(price_map, "QQQ", as_of)
        if qqq_ret is None:
            continue
        scores = model_scores(rows)
        for model, ranked in scores.items():
            ranked.sort(key=lambda z: (-z[0], str(z[1].get("ticker"))))
            for rank, (score, r) in enumerate(ranked[:5], start=1):
                ticker = str(r.get("ticker") or "").upper()
                ret = outcome(price_map, ticker, as_of)
                if ret is None:
                    continue
                picks_by_model[model].append({
                    "as_of_date": ds,
                    "ticker": ticker,
                    "rank": rank,
                    "score": round(score, 4),
                    "return_6m": ret,
                    "qqq_return_6m": qqq_ret,
                    "alpha_6m": ret - qqq_ret,
                    "regime": regime(as_of),
                })

    models = {}
    for model, picks in picks_by_model.items():
        overall = stats(picks)
        regimes = {}
        for rg in ["2017_2021", "2022_2025", "2026_FORWARD"]:
            regimes[rg] = stats([p for p in picks if p["regime"] == rg])
        validated = (
            overall["n"] >= 100
            and (overall["median_alpha_6m"] or -999) > 0
            and (overall["win_rate_vs_qqq"] or 0) > 55
            and (overall["trimmed_alpha_90pct"] or -999) > 0
            and all(
                (regimes[rg]["n"] < 25) or ((regimes[rg]["median_alpha_6m"] or -999) > 0)
                for rg in ["2017_2021", "2022_2025"]
            )
        )
        models[model] = {
            "status": "VALIDATED" if validated else "RESEARCH_ONLY",
            "overall": overall,
            "regimes": regimes,
            "latest_picks": sorted(picks, key=lambda p: (p["as_of_date"], -p["rank"]), reverse=True)[:10],
        }

    result = {
        "ok": True,
        "engine": "ORACLE_V5_EXTERNAL_WORKER_1",
        "source_dataset_version": payload.get("dataset_version"),
        "source_generated_at": payload.get("generated_at"),
        "strict_pit": True,
        "counts": payload.get("counts", {}),
        "methodology": {
            "top_n_per_quarter": 5,
            "horizon_months": 6,
            "benchmark": "QQQ",
            "promotion_gate": "N>=100; median alpha>0; win-rate>55%; trimmed alpha>0; regime stability",
            "weights_predefined": True,
            "fundamentals_in_model": False,
            "note": "SEC PIT fundamentals remain a separate gate until historical coverage is sufficient."
        },
        "models": models,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({m: models[m]["overall"] for m in models}, indent=2))


if __name__ == "__main__":
    main()
