#!/usr/bin/env python3
"""
ORACLE Macro Stress Gap research module.

Purpose
-------
Test whether a bond/equity-volatility divergence similar to the current
"high MOVE / calm VIX / rising yields / rising oil" regime has historically
contained exploitable information.

This module is RESEARCH ONLY. It does not alter portfolio weights or GREEN/
ORANGE/RED entry states. Any future allocation use must be gated on out-of-
sample evidence.

Methodology
-----------
* Free public EOD data from Yahoo Finance chart endpoint.
* Signal computed at day t close; forward returns enter at t+1 close.
* Rolling z-scores use only observations strictly prior to t.
* Events are de-clustered with a 20-trading-day cooldown.
* Event returns are compared with random calm-VIX dates using an empirical
  randomization test. Random dates are also de-clustered.
* Multiple asset/horizon p-values are adjusted by Benjamini-Hochberg.
* Results are written to data/macro-stress-backtest.json.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT = Path("data/macro-stress-backtest.json")
UA = "Mozilla/5.0 ORACLE-Research/4.0"

START_DATE = datetime(2007, 1, 1, tzinfo=timezone.utc).date()
LOOKBACK = 252
MIN_HISTORY = 126
COOLDOWN = 20
RANDOM_DRAWS = 2000
HORIZONS = (5, 20, 60)

MARKET = {
    "MOVE": "^MOVE",
    "VIX": "^VIX",
    "TNX": "^TNX",
    "OIL": "CL=F",
    "SPY": "SPY",
    "QQQ": "QQQ",
    "TLT": "TLT",
    "GLD": "GLD",
    "XLE": "XLE",
}
ASSETS = ("SPY", "QQQ", "TLT", "GLD", "XLE")


def request_json(url: str, timeout: int = 25, retries: int = 2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "application/json,*/*"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:
            last = exc
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise last


def yahoo_series(ticker: str, start, end):
    p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    p2 = int(
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )
    symbol = urllib.parse.quote(ticker, safe="")
    params = urllib.parse.urlencode(
        {
            "period1": p1,
            "period2": p2,
            "interval": "1d",
            "events": "history",
            "includeAdjustedClose": "true",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{params}"
    obj = request_json(url)
    result = ((obj.get("chart") or {}).get("result") or [])
    if not result:
        raise RuntimeError(f"no_yahoo_result:{ticker}:{(obj.get('chart') or {}).get('error')}")
    r = result[0]
    ts = r.get("timestamp") or []
    q = (((r.get("indicators") or {}).get("quote") or [{}])[0])
    closes = q.get("close") or []
    rows = {}
    for t, c in zip(ts, closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(t, timezone.utc).date().isoformat()
        try:
            v = float(c)
        except Exception:
            continue
        if math.isfinite(v) and v > 0:
            rows[d] = v
    if len(rows) < 100:
        raise RuntimeError(f"insufficient_rows:{ticker}:{len(rows)}")
    return rows, url


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def percentile(xs, p):
    if not xs:
        return None
    ys = sorted(xs)
    if len(ys) == 1:
        return ys[0]
    k = (len(ys) - 1) * p
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    if lo == hi:
        return ys[lo]
    return ys[lo] + (ys[hi] - ys[lo]) * (k - lo)


def sample_sd(xs):
    if len(xs) < 2:
        return None
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def z_prior(values, i, lookback=LOOKBACK):
    lo = max(0, i - lookback)
    hist = [x for x in values[lo:i] if x is not None and math.isfinite(x)]
    if len(hist) < MIN_HISTORY:
        return None
    m = mean(hist)
    sd = sample_sd(hist)
    if not sd or sd <= 1e-12:
        return None
    return (values[i] - m) / sd


def change(values, i, lag, scale=1.0):
    if i < lag or values[i] is None or values[i - lag] is None:
        return None
    return (values[i] - values[i - lag]) * scale


def ret(values, i, lag):
    if i < lag or values[i] is None or values[i - lag] in (None, 0):
        return None
    return values[i] / values[i - lag] - 1.0


def forward_return(values, i, horizon):
    # signal at close t; enter at next close, exit at t+horizon close
    if i + horizon >= len(values) or i + 1 >= len(values):
        return None
    p0, p1 = values[i + 1], values[i + horizon]
    if p0 in (None, 0) or p1 is None:
        return None
    return p1 / p0 - 1.0


def decluster(indices, cooldown=COOLDOWN):
    out = []
    last = -10**9
    for i in sorted(indices):
        if i - last >= cooldown:
            out.append(i)
            last = i
    return out


def bh_adjust(rows):
    """Benjamini-Hochberg q-values in-place for rows containing p_value."""
    valid = [(idx, r["p_value"]) for idx, r in enumerate(rows) if r.get("p_value") is not None]
    if not valid:
        return
    valid.sort(key=lambda x: x[1])
    m = len(valid)
    q = [None] * m
    running = 1.0
    for rank_rev in range(m - 1, -1, -1):
        idx, p = valid[rank_rev]
        rank = rank_rev + 1
        running = min(running, p * m / rank)
        q[rank_rev] = min(1.0, running)
    for (pair, qq) in zip(valid, q):
        rows[pair[0]]["q_value_bh"] = qq


def ci_mean(xs):
    if len(xs) < 2:
        return [None, None]
    m = mean(xs)
    sd = sample_sd(xs)
    se = sd / math.sqrt(len(xs))
    return [m - 1.96 * se, m + 1.96 * se]


def summarize_returns(xs):
    if not xs:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "positive_rate": None,
            "mean_ci95": [None, None],
        }
    return {
        "n": len(xs),
        "mean": mean(xs),
        "median": statistics.median(xs),
        "positive_rate": sum(x > 0 for x in xs) / len(xs),
        "mean_ci95": ci_mean(xs),
    }


def empirical_test(event_returns, candidate_returns, n_draws=RANDOM_DRAWS, seed=74017):
    """
    Test mean event return against same-size random calm-regime samples.
    Two-sided empirical p-value and excess versus null mean.
    """
    if len(event_returns) < 5 or len(candidate_returns) < max(20, len(event_returns)):
        return {
            "p_value": None,
            "null_mean": None,
            "excess_mean": None,
            "null_ci95": [None, None],
            "draws": 0,
        }
    rng = random.Random(seed)
    n = len(event_returns)
    obs = mean(event_returns)
    sims = []
    for _ in range(n_draws):
        samp = rng.sample(candidate_returns, n)
        sims.append(mean(samp))
    null_mean = mean(sims)
    delta = obs - null_mean
    tail = sum(abs(x - null_mean) >= abs(delta) for x in sims)
    p = (tail + 1) / (len(sims) + 1)
    return {
        "p_value": p,
        "null_mean": null_mean,
        "excess_mean": delta,
        "null_ci95": [percentile(sims, 0.025), percentile(sims, 0.975)],
        "draws": len(sims),
    }


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    now = datetime.now(timezone.utc)
    end = now.date()
    raw, urls, errors = {}, {}, []

    for name, ticker in MARKET.items():
        try:
            raw[name], urls[name] = yahoo_series(ticker, START_DATE, end)
        except Exception as exc:
            errors.append({"series": name, "ticker": ticker, "error": repr(exc)})
        time.sleep(0.08)

    required = ("MOVE", "VIX", "TNX", "OIL", "SPY", "QQQ")
    missing = [x for x in required if x not in raw]
    if missing:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": iso_now(),
            "status": "INSUFFICIENT_DATA",
            "research_only": True,
            "missing_required": missing,
            "errors": errors,
            "sources": urls,
        }
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(json.dumps({"status": payload["status"], "missing": missing, "errors": len(errors)}))
        return

    # SPY defines the trading calendar. Other series are forward-filled up to
    # 3 sessions to bridge isolated holidays/data gaps, never future-filled.
    dates = sorted(raw["SPY"])

    def aligned(name, max_ffill=3):
        series = raw.get(name, {})
        out = []
        last_v, last_i = None, None
        for i, d in enumerate(dates):
            if d in series:
                last_v, last_i = series[d], i
                out.append(last_v)
            elif last_i is not None and i - last_i <= max_ffill:
                out.append(last_v)
            else:
                out.append(None)
        return out

    a = {name: aligned(name, 3 if name in ("MOVE", "VIX", "TNX", "OIL") else 1) for name in raw}

    move, vix, tnx, oil = a["MOVE"], a["VIX"], a["TNX"], a["OIL"]
    # Yahoo ^TNX is typically 10x yield percentage (e.g. 52.4 == 5.24%).
    # Scaling does not affect z-scores; /10 makes changes interpretable in pp.
    tnx_yield = [x / 10.0 if x is not None else None for x in tnx]

    scores = [None] * len(dates)
    strict = [False] * len(dates)
    components = [None] * len(dates)

    # build transformations first; z-scores are then based only on prior values
    tnx20 = [change(tnx_yield, i, 20) for i in range(len(dates))]
    oil20 = [ret(oil, i, 20) for i in range(len(dates))]

    for i in range(len(dates)):
        if any(x is None for x in (move[i], vix[i], tnx20[i], oil20[i])):
            continue
        zm = z_prior(move, i)
        zv = z_prior(vix, i)
        zt = z_prior(tnx20, i)
        zo = z_prior(oil20, i)
        if any(x is None for x in (zm, zv, zt, zo)):
            continue
        score = zm - zv + zt + zo
        scores[i] = score
        components[i] = {"z_move": zm, "z_vix": zv, "z_tnx_20d": zt, "z_oil_20d": zo}

        # Human-readable regime mirroring the hypothesis, not optimized on returns.
        move_hist = [x for x in move[max(0, i - LOOKBACK):i] if x is not None]
        move_p80 = percentile(move_hist, 0.80) if len(move_hist) >= MIN_HISTORY else None
        strict[i] = bool(
            move_p80 is not None
            and move[i] >= move_p80
            and vix[i] <= 20.0
            and tnx20[i] >= 0.15
            and oil20[i] > 0.0
        )

    # Main score event: score above the 90th percentile of its own *prior* 3y
    # distribution + calm VIX. This avoids a full-sample threshold.
    score_event = [False] * len(dates)
    for i, s in enumerate(scores):
        if s is None or vix[i] is None:
            continue
        hist = [x for x in scores[max(0, i - 756):i] if x is not None]
        if len(hist) < MIN_HISTORY:
            continue
        q90 = percentile(hist, 0.90)
        score_event[i] = bool(s >= q90 and vix[i] <= 20.0)

    # Require enough future data for all horizons when selecting events.
    last_valid = len(dates) - max(HORIZONS) - 1
    score_idx = decluster([i for i in range(last_valid + 1) if score_event[i]])
    strict_idx = decluster([i for i in range(last_valid + 1) if strict[i]])

    # Null candidates: calm-equity-volatility regime, not current signal events.
    calm_idx = decluster(
        [
            i
            for i in range(MIN_HISTORY, last_valid + 1)
            if vix[i] is not None and vix[i] <= 20.0 and not score_event[i]
        ],
        cooldown=COOLDOWN,
    )

    tests = []
    event_sets = {"score_q90_vix20": score_idx, "strict_pattern": strict_idx}
    for event_name, idxs in event_sets.items():
        for asset in ASSETS:
            if asset not in a:
                continue
            vals = a[asset]
            for h in HORIZONS:
                ev = [forward_return(vals, i, h) for i in idxs]
                ev = [x for x in ev if x is not None and math.isfinite(x)]
                null = [forward_return(vals, i, h) for i in calm_idx]
                null = [x for x in null if x is not None and math.isfinite(x)]
                base = summarize_returns(ev)
                rnd = empirical_test(ev, null, seed=74017 + h + sum(ord(c) for c in asset + event_name))
                tests.append(
                    {
                        "event": event_name,
                        "asset": asset,
                        "horizon_sessions": h,
                        **base,
                        **rnd,
                    }
                )

    bh_adjust(tests)

    def event_rows(idxs):
        rows = []
        for i in idxs:
            rows.append(
                {
                    "date": dates[i],
                    "score": scores[i],
                    "move": move[i],
                    "vix": vix[i],
                    "tnx_yield_pct": tnx_yield[i],
                    "tnx_20d_change_pp": tnx20[i],
                    "oil_20d_return": oil20[i],
                    "components": components[i],
                }
            )
        return rows

    # Latest live reading: no forward-return requirement.
    latest_i = max(
        (i for i, s in enumerate(scores) if s is not None and vix[i] is not None),
        default=None,
    )
    latest = None
    if latest_i is not None:
        hist = [x for x in scores[max(0, latest_i - 756):latest_i] if x is not None]
        q90 = percentile(hist, 0.90) if len(hist) >= MIN_HISTORY else None
        latest = {
            "date": dates[latest_i],
            "score": scores[latest_i],
            "score_prior_3y_q90": q90,
            "score_event_now": bool(q90 is not None and scores[latest_i] >= q90 and vix[latest_i] <= 20.0),
            "strict_pattern_now": strict[latest_i],
            "move": move[latest_i],
            "vix": vix[latest_i],
            "tnx_yield_pct": tnx_yield[latest_i],
            "tnx_20d_change_pp": tnx20[latest_i],
            "oil_20d_return": oil20[latest_i],
            "components": components[latest_i],
        }

    # Conservative "edge" flag: at least one main event test with n>=10,
    # q<=0.05 and economically meaningful |excess| >= 1% at 20/60d.
    qualifying = [
        t
        for t in tests
        if t["event"] == "score_q90_vix20"
        and t["horizon_sessions"] in (20, 60)
        and t["n"] >= 10
        and t.get("q_value_bh") is not None
        and t["q_value_bh"] <= 0.05
        and t.get("excess_mean") is not None
        and abs(t["excess_mean"]) >= 0.01
    ]

    payload = {
        "generated_at": iso_now(),
        "status": "EDGE_CANDIDATE" if qualifying else "NO_VALIDATED_EDGE",
        "research_only": True,
        "do_not_trade_from_this_file": True,
        "method": {
            "signal_timing": "signal at close t; forward return enters at close t+1",
            "lookback_sessions": LOOKBACK,
            "score": "z(MOVE) - z(VIX) + z(20d change in 10Y yield) + z(20d oil return)",
            "main_event": "score >= rolling prior-3y 90th percentile AND VIX <= 20",
            "strict_event": "MOVE >= prior-1y p80, VIX<=20, 20d 10Y change>=+0.15pp, oil 20d return>0",
            "decluster_sessions": COOLDOWN,
            "null": "same-size random samples from de-clustered VIX<=20 non-event dates",
            "random_draws": RANDOM_DRAWS,
            "multiple_testing": "Benjamini-Hochberg across reported asset/horizon tests",
            "edge_candidate_gate": "main event, horizon 20/60, n>=10, BH q<=0.05, abs excess mean>=1%",
        },
        "coverage": {
            "start": dates[0],
            "end": dates[-1],
            "trading_days": len(dates),
            "main_events": len(score_idx),
            "strict_events": len(strict_idx),
            "calm_null_dates": len(calm_idx),
        },
        "latest": latest,
        "qualifying_tests": qualifying,
        "tests": tests,
        "events": {
            "score_q90_vix20": event_rows(score_idx),
            "strict_pattern": event_rows(strict_idx),
        },
        "sources": urls,
        "errors": errors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": payload["status"],
                "main_events": len(score_idx),
                "strict_events": len(strict_idx),
                "tests": len(tests),
                "qualifying": len(qualifying),
                "latest": latest,
                "errors": len(errors),
            }
        )
    )


if __name__ == "__main__":
    main()
