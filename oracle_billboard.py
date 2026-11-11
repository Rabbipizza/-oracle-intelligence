"""Source-isolated ORACLE Top 5: acceleration, not popularity.

Only a *complete* 21-calendar-day observation window is rankable.
No inference from missing days. The initial signal is exploratory.
"""
from __future__ import annotations
from datetime import date, timedelta
from urllib.parse import urlparse

MIN_DAYS = 21
MIN_RECENT_DOCS = 35
MIN_RECENT_MENTIONS = 4
MIN_RECENT_ACTIVE_DAYS = 2


def source_snapshots(documents, source_definitions, term_extractor):
    """Deduplicate observations by URL per source, count distinct documents."""
    counters = {source[0]: {"documents": 0, "terms": {}} for source in source_definitions}
    seen = set()
    for doc in documents:
        key = doc.get("source")
        url = doc.get("url", "")
        if key not in counters or not isinstance(url, str):
            continue
        if urlparse(url).scheme not in ("https", "http"):
            continue
        marker = (key, url)
        if marker in seen:
            continue
        seen.add(marker)
        result = counters[key]
        result["documents"] += 1
        for phrase in set(term_extractor(doc.get("title", ""))):
            mention = result["terms"].setdefault(phrase, {"count": 0, "links": []})
            mention["count"] += 1
            if len(mention["links"]) < 3:
                mention["links"].append(url)
    return counters


def _window_rate(days, phrase):
    denominator = sum(d["documents"] for d in days)
    numerator = sum(d["terms"].get(phrase, {}).get("count", 0) for d in days)
    return (numerator * 10000.0 / denominator) if denominator else None


def source_top5(source, day_string, current_snapshot, previous_snapshots):
    """Rank changes in slopes of consecutive weekly normalized frequencies.

    Returns no Top 5 unless 21 *consecutive calendar days* of non-empty
    samples exist. A missing source on a given day is not a zero count.
    """
    source_id, source_name, domain, family, kind, url = source
    day = date.fromisoformat(day_string)
    past = {
        row.get("date"): row.get("sources", {}).get(source_id)
        for row in previous_snapshots
        if row.get("date", "") < day_string
    }
    past[day_string] = current_snapshot.get("sources", {}).get(source_id)
    samples = [
        past.get((day - timedelta(days=offset)).isoformat())
        for offset in range(20, -1, -1)
    ]
    observed = sum(bool(s and s.get("documents", 0) > 0) for s in samples)
    today = past.get(day_string) or {"documents": 0, "terms": {}}
    state = {
        "source_id": source_id,
        "source_name": source_name,
        "domain": domain,
        "state": "INSUFFICIENT_HISTORY",
        "observed_days": observed,
        "required_days": MIN_DAYS,
        "documents_today": today.get("documents", 0),
        "top5": [],
        "preview_unranked": [],
    }
    if not today.get("documents"):
        state["state"] = "NO_DATA"
        return state
    if observed != MIN_DAYS:
        return state

    early, middle, recent = samples[:7], samples[7:14], samples[14:21]
    if sum(x["documents"] for x in recent) < MIN_RECENT_DOCS:
        state["state"] = "INSUFFICIENT_VOLUME"
        return state
    candidates = set().union(*(set(x["terms"]) for x in recent))
    results = []
    for term in candidates:
        counts = [x["terms"].get(term, {}).get("count", 0) for x in recent]
        if sum(counts) < MIN_RECENT_MENTIONS:
            continue
        if sum(x > 0 for x in counts) < MIN_RECENT_ACTIVE_DAYS:
            continue
        r_early, r_middle, r_recent = (
            _window_rate(window, term) for window in (early, middle, recent)
        )
        if r_early is None or r_middle is None or r_recent is None:
            continue
        velocity = r_recent - r_middle
        acceleration = r_recent - 2 * r_middle + r_early
        if acceleration <= 0 or velocity <= 0:
            continue
        links = []
        for snapshot in reversed(recent):
            for evidence in snapshot["terms"].get(term, {}).get("links", []):
                if evidence not in links and len(links) < 3:
                    links.append(evidence)
        results.append({
            "term": term,
            "acceleration_per_10k_week2": round(acceleration, 3),
            "velocity_per_10k_week": round(velocity, 3),
            "rate_earlier": round(r_early, 3),
            "rate_previous": round(r_middle, 3),
            "rate_recent": round(r_recent, 3),
            "mentions_last_7d": sum(counts),
            "active_days_last_7d": sum(x > 0 for x in counts),
            "evidence_urls": links,
            "quality": "EXPLORATORY",
        })
    results.sort(key=lambda x: (
        -x["acceleration_per_10k_week2"], -x["mentions_last_7d"], x["term"]
    ))
    state["state"] = "RANKED_EXPLORATORY" if results else "NO_POSITIVE_ACCELERATION"
    state["top5"] = results[:5]
    return state


def source_billboards(day_string, current_snapshot, previous_snapshots, sources):
    return {
        source[0]: source_top5(source, day_string, current_snapshot, previous_snapshots)
        for source in sources
    }
