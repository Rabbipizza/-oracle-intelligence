"""ORACLE market monitor (experimental reference instruments, NOT recommendations).

Price source is the Yahoo chart public endpoint. This is an undocumented
endpoint: availability, use rights, freshness and redistribution require
independent verification. The collector never manufactures unavailable prices,
never computes investable signals and never silently changes provider.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "market.json"
# Observational reference universe only, not a screened top 10 for any trend.
SYMBOLS = ("QQQ", "SPY", "NVDA", "MSFT", "GOOGL", "AMZN",
           "AVGO", "AMD", "TSM", "ASML", "META", "AAPL")
UA = "ORACLE research market-data checker/0.1"
MAX_AGE_DAYS = 5

def classify_age(date_string, now):
    try:
        price_date = dt.date.fromisoformat(date_string)
    except (ValueError, TypeError):
        return "INVALID"
    age = (now.date() - price_date).days
    if age < 0:
        return "INVALID"
    return "CURRENT_DAILY" if age <= MAX_AGE_DAYS else "STALE"

def indicators(prices):
    if not prices:
        return {"sma20": None, "sma50": None, "return_20d_pct": None,
                "volatility_20d_annualized_pct": None, "max_drawdown_90d_pct": None}
    prices = list(prices)
    sma20 = statistics.mean(prices[-20:]) if len(prices) >= 20 else None
    sma50 = statistics.mean(prices[-50:]) if len(prices) >= 50 else None
    ret20 = (prices[-1] / prices[-21] - 1) * 100 if len(prices) >= 21 and prices[-21] > 0 else None
    returns = [prices[i] / prices[i-1] - 1 for i in range(max(1, len(prices)-19), len(prices)) if prices[i-1] > 0]
    volatility = statistics.stdev(returns) * (252 ** 0.5) * 100 if len(returns) >= 10 else None
    peak = 0.0
    drawdown = 0.0
    for price in prices[-90:]:
        peak = max(peak, price)
        if peak:
            drawdown = min(drawdown, (price / peak - 1) * 100)
    return {"sma20": round(sma20, 4) if sma20 is not None else None,
            "sma50": round(sma50, 4) if sma50 is not None else None,
            "return_20d_pct": round(ret20, 3) if ret20 is not None else None,
            "volatility_20d_annualized_pct": round(volatility, 3) if volatility is not None else None,
            "max_drawdown_90d_pct": round(drawdown, 3) if prices else None}

def read_chart(symbol, now):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + symbol +
           "?range=1y&interval=1d&events=history")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; ORACLE-research/0.1)", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = response.read(1_500_001)
        if len(payload) > 1_500_000:
            raise ValueError("PAYLOAD_LIMIT")
    root = json.loads(payload)["chart"]
    if root.get("error") or not root.get("result"):
        raise ValueError("PROVIDER_ERROR")
    obj = root["result"][0]
    stamps = obj.get("timestamp") or []
    quote = (obj.get("indicators", {}).get("quote") or [{}])[0]
    close = quote.get("close") or []
    points = []
    for stamp, value in zip(stamps, close):
        if value is None or not isinstance(value, (int, float)) or value <= 0:
            continue
        date = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).date().isoformat()
        if points and points[-1]["date"] == date:
            points[-1]["close"] = round(value, 4)
        else:
            points.append({"date": date, "close": round(value, 4)})
    if not points:
        raise ValueError("NO_VALID_CLOSES")
    values = [x["close"] for x in points]
    quality = classify_age(points[-1]["date"], now)
    currency = obj.get("meta", {}).get("currency")
    return {"symbol": symbol, "state": quality, "currency": currency,
            "date": points[-1]["date"], "close": values[-1],
            "provider": "YAHOO_CHART_UNOFFICIAL", "frequency": "EOD",
            "series": points[-180:], "indicators": indicators(values),
            "signal": "GREY_NOT_VALIDATED",
            "trend_mapping": "NOT_REVIEWED",
            "license_status": "PENDING_REVIEW"}

def snapshot(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    results = []
    for symbol in SYMBOLS:
        try:
            results.append(read_chart(symbol, now))
        except Exception as err:
            results.append({"symbol": symbol, "state": "UNAVAILABLE",
                            "reason": type(err).__name__,
                            "signal": "GREY_NOT_VALIDATED",
                            "trend_mapping": "NOT_REVIEWED"})
    return {
        "schema_version": 1,
        "collected_at_utc": now.isoformat(),
        "data_kind": "EXPERIMENTAL_DAILY_QUOTES",
        "not_investment_advice": True,
        "benchmark_symbol": "QQQ",
        "securities": results,
        "portfolio": {"actual": None, "target": None, "paper": None},
        "strategy_backtest": {"status": "NOT_AVAILABLE"},
        "notes": "Reference watchlist only; not trend-linked top 10. No trading recommendation. Source licensing not verified."
    }

def main():
    data = snapshot()
    output = OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, output)
    count = sum(x["state"] == "CURRENT_DAILY" for x in data["securities"])
    print(json.dumps({"market_coverage": count, "market_total": len(data["securities"]),
                      "states": {x["symbol"]: x["state"] for x in data["securities"]}}))
    # A complete provider outage is NOT a CI failure: an explicit grey market
    # snapshot is published so the dashboard cannot display stale green data.
    return data

if __name__ == "__main__":
    main()
