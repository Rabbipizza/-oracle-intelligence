#!/usr/bin/env python3
"""ORACLE v0.1: daily public-source sampling and *exploratory* trend charts.
No trading signals; no claims that counts represent the entire internet.
Standard library only. Rights and source coverage must be monitored.
"""
from __future__ import annotations
import collections
import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from oracle_billboard import source_snapshots, source_billboards
from oracle_pipeline import create_research_queue

UTC = dt.timezone.utc
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
USER_AGENT = "ORACLE-research/0.1 (public-data sampler; Github Rabbipizza/-oracle-intelligence)"
STOP = set("""
a an and are as at be by for from has have in into is it its of on or the their this that
to with without will was were how what when where who why about after before over under
versus vs amid new latest first more using use can may could should beyond through
de de la le les des du au aux en un une est sont et pour dans avec sur par dans pas
que qui ce cette ces plus moins comme entre dont il elle ils elles mais alors
""".split())
TOKEN = re.compile(r"[^\W\d_][\w-]{2,39}", re.UNICODE)
ATOM = "{http://www.w3.org/2005/Atom}"

SOURCES = [
    ("google_us", "Google Trends US", "culture", "google_trends", "rss", "https://trends.google.com/trending/rss?geo=US"),
    ("google_fr", "Google Trends FR", "culture", "google_trends", "rss", "https://trends.google.com/trending/rss?geo=FR"),
    ("google_ch", "Google Trends CH", "culture", "google_trends", "rss", "https://trends.google.com/trending/rss?geo=CH"),
    ("google_gb", "Google Trends GB", "culture", "google_trends", "rss", "https://trends.google.com/trending/rss?geo=GB"),
    ("arxiv_ai", "arXiv AI", "technology", "arxiv", "rss", "https://rss.arxiv.org/rss/cs.AI"),
    ("arxiv_robotics", "arXiv Robotics", "technology", "arxiv", "rss", "https://rss.arxiv.org/rss/cs.RO"),
    ("arxiv_quantum", "arXiv Quantum", "science", "arxiv", "rss", "https://rss.arxiv.org/rss/quant-ph"),
    ("arxiv_biology", "arXiv Biology", "science", "arxiv", "rss", "https://rss.arxiv.org/rss/q-bio"),
    ("arxiv_economics", "arXiv Economics", "science", "arxiv", "rss", "https://rss.arxiv.org/rss/econ"),
    ("hackernews", "Hacker News", "social", "hackernews", "hn", "https://hacker-news.firebaseio.com/v0/topstories.json"),
    ("wikipedia_en", "Wikipedia Top Pages EN", "culture", "wikipedia", "wiki", "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia.org/all-access"),
    ("wikipedia_fr", "Wikipedia Top Pages FR", "culture", "wikipedia", "wiki", "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/fr.wikipedia.org/all-access"),
    ("google_news_us", "Google News US", "news", "google_news", "rss", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
    ("google_news_fr", "Google News France", "news", "google_news", "rss", "https://news.google.com/rss?hl=fr&gl=FR&ceid=FR:fr"),
    ("google_news_health", "Google News Santé", "health", "google_news", "rss", "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en"),
    ("mit_environment", "MIT Environment", "geography", "mit_environment", "rss", "https://news.mit.edu/rss/topic/environment"),
    ("fed_press", "Federal Reserve Press", "macroeconomics", "fed_press", "rss", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("eurlex_law", "EUR-Lex Acts", "geopolitics", "eurlex", "rss", "https://eur-lex.europa.eu/EN/display-feed.rss?rssId=165"),
    ("federal_register", "US Federal Register", "geopolitics", "federal_register", "federal", "https://www.federalregister.gov/api/v1/documents.json?per_page=100&order=newest"),
]
DOMAINS = [
    "culture", "social", "news", "technology", "science", "patents",
    "macroeconomics", "geopolitics", "geography", "demography",
    "commodities", "supply_chain", "health", "markets",
]

def get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json, application/rss+xml, application/xml",
    })
    with urllib.request.urlopen(req, timeout=16) as response:
        return response.read(3_000_001)[:3_000_000]

def parse_published(raw: str | None):
    if not raw:
        return None
    try:
        return email.utils.parsedate_to_datetime(raw).astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
        except (TypeError, ValueError):
            return None

def rss_items(url: str):
    root = ET.fromstring(get_bytes(url))
    items = []
    for item in root.findall(".//item"):
        title = html.unescape("".join(item.find("title").itertext()) if item.find("title") is not None else "")
        link = item.findtext("link", "")
        published = parse_published(item.findtext("pubDate", ""))
        if title and link.startswith("http"):
            items.append({"title": title, "url": link, "published": published})
    if not items:
        for entry in root.findall(".//" + ATOM + "entry"):
            title = entry.findtext(ATOM + "title", "")
            link_node = entry.find(ATOM + "link")
            link = link_node.get("href", "") if link_node is not None else ""
            published = parse_published(entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated"))
            if title and link.startswith("http"):
                items.append({"title": title, "url": link, "published": published})
    return items

def hn_items():
    ids = json.loads(get_bytes("https://hacker-news.firebaseio.com/v0/topstories.json"))[:60]
    def fetch_one(item_id):
        return json.loads(get_bytes("https://hacker-news.firebaseio.com/v0/item/%s.json" % item_id))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        raw = list(ex.map(fetch_one, ids))
    result = []
    for obj in raw:
        if not isinstance(obj, dict) or obj.get("dead") or obj.get("deleted"):
            continue
        if obj.get("title"):
            result.append({"title": html.unescape(obj["title"]), "url": obj.get("url") or "https://news.ycombinator.com/item?id=%s" % obj["id"],
                           "published": dt.datetime.fromtimestamp(obj["time"], tz=UTC) if obj.get("time") else None})
    return result

def wiki_items(url: str, now: dt.datetime):
    day = (now - dt.timedelta(days=2)).date()
    endpoint = "%s/%04d/%02d/%02d" % (url, day.year, day.month, day.day)
    data = json.loads(get_bytes(endpoint))
    items = data["items"][0]["articles"]
    result = []
    for item in items[:500]:
        title = item.get("article", "")
        if not title or title.startswith(("Special:", "Wikipedia:", "Main_Page", "Accueil_principal")):
            continue
        host = "fr.wikipedia.org" if "fr.wikipedia" in url else "en.wikipedia.org"
        from urllib.parse import quote
        result.append({"title": title.replace("_", " "), "url": "https://%s/wiki/%s" % (host, quote(title)), "published": None})
    return result

def federal_items():
    data = json.loads(get_bytes("https://www.federalregister.gov/api/v1/documents.json?per_page=100&order=newest"))
    result = []
    for row in data.get("results", []):
        if row.get("title") and row.get("html_url"):
            result.append({"title": row["title"], "url": row["html_url"], "published": parse_published(row.get("publication_date"))})
    return result

def collect(source, now):
    key, name, domain, family, kind, url = source
    if kind == "rss":
        docs = rss_items(url)
    elif kind == "hn":
        docs = hn_items()
    elif kind == "wiki":
        docs = wiki_items(url, now)
    elif kind == "federal":
        docs = federal_items()
    else:
        raise ValueError("Unsupported connector")
    # Google Trends trending RSS is itself a current ranked snapshot. Its item
    # pubDate may describe the original story rather than trending-list entry;
    # discarding it makes sample volume unpredictably shrink to 0–1 items.
    if family != "google_trends":
        cutoff = now - dt.timedelta(days=3)
        docs = [x for x in docs if x["published"] is None or x["published"] >= cutoff]
    # Google News appends " - Publisher" to each title. Counting publisher
    # names as trending terms is a structural measurement error.
    if family == "google_news":
        for item in docs:
            if " - " in item["title"]:
                item["title"] = item["title"].rsplit(" - ", 1)[0].strip()
    for item in docs:
        item.update({"source": key, "family": family, "domain": domain})
    return docs

def terms(title: str):
    tokens = [x.casefold() for x in TOKEN.findall(title)]
    tokens = [x for x in tokens if not x.isnumeric()]
    phrases = set()
    # Single words inflate boilerplate ("notice", "show", "model").
    # Multiword phrases are a cautious bootstrap, not semantic clustering.
    for n in (2, 3):
        for i in range(len(tokens) - n + 1):
            seq = tokens[i:i+n]
            if any(word in STOP for word in seq):
                continue
            if any(any(ch.isdigit() for ch in word) for word in seq):
                continue
            phrases.add(" ".join(seq))
    return phrases

def aggregate(documents):
    counters = {domain: {"documents": 0, "terms": {}} for domain in DOMAINS}
    seen = set()
    for doc in documents:
        if not doc["url"].startswith(("https://", "http://")):
            continue
        identifier = (doc["source"], doc["url"])
        if identifier in seen:
            continue
        seen.add(identifier)
        area = counters[doc["domain"]]
        area["documents"] += 1
        for term in terms(doc["title"]):
            item = area["terms"].setdefault(term, {"count": 0, "families": [], "links": []})
            item["count"] += 1
            if doc["family"] not in item["families"]:
                item["families"].append(doc["family"])
            if doc["url"] not in item["links"] and len(item["links"]) < 3:
                item["links"].append(doc["url"])
    return counters

def compute_rank(current: dict, previous: list[dict], minimum_history_days=14):
    docs = current["documents"]
    available = [x for x in previous if x.get("documents", 0) > 0]
    enough_history = len(available) >= minimum_history_days and docs > 0
    result = []
    for term, data in current["terms"].items():
        if data["count"] < 2:
            continue
        rate = 10000.0 * data["count"] / max(1, docs)
        historic = [10000.0 * day["terms"].get(term, {}).get("count", 0) / day["documents"] for day in available[-28:]]
        baseline = sum(historic) / len(historic) if historic else None
        growth = (rate - baseline) / max(1.0, baseline) if baseline is not None else None
        breadth = len(data["families"])
        # The score is *exploratory*, not predictive or scientific proof.
        score = (math.log1p(rate) + (max(-2, min(5, growth)) if growth is not None else 0) +
                 0.25 * breadth)
        quality = "MEASURABLE" if enough_history and breadth >= 2 and data["count"] >= 3 else "EXPLORATORY"
        result.append({"term": term, "score": round(score, 3), "mentions": data["count"],
                       "rate_per_10k": round(rate, 2),
                       "growth_vs_28d": round(growth, 3) if growth is not None else None,
                       "independent_source_families": breadth, "quality": quality,
                       "evidence_urls": data["links"]})
    result.sort(key=lambda x: (-x["score"], -x["mentions"], x["term"]))
    return result[:20]

def load_history(directory, today):
    prior = []
    if not directory.exists():
        return prior
    for path in sorted(directory.glob("????-??-??.json")):
        if path.stem >= today:
            continue
        try:
            prior.append(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return prior[-90:]

def run(now=None):
    now = now or dt.datetime.now(UTC)
    today = now.date().isoformat()
    data_dir = DATA / "history"
    good, health = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(collect, source, now): source for source in SOURCES}
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                docs = future.result()
                good.extend(docs)
                health.append({"source": source[0], "status": "OK" if docs else "EMPTY", "documents": len(docs)})
            except Exception as exc:
                health.append({"source": source[0], "status": "ERROR", "documents": 0,
                               "error": type(exc).__name__})
    health.sort(key=lambda x: x["source"])
    if not good:
        raise RuntimeError("FAIL_CLOSED: no successfully collected observations; output not updated")
    daily = {"date": today, "collected_at_utc": now.isoformat(), "domains": aggregate(good),
             "sources": source_snapshots(good, SOURCES, terms),
             "source_health": health, "schema_version": 2}
    data_dir.mkdir(parents=True, exist_ok=True)
    past = load_history(data_dir, today)
    rank = {}
    for domain in DOMAINS:
        previous_domains = [day.get("domains", {}).get(domain, {"documents": 0, "terms": {}}) for day in past]
        day_now = daily["domains"][domain]
        rank[domain] = {"documents": day_now["documents"],
                        "historical_days": sum(p["documents"] > 0 for p in previous_domains),
                        "state": "EXPLORATORY" if day_now["documents"] else "NO_DATA",
                        "top20": compute_rank(day_now, previous_domains)}
    per_source = source_billboards(today, daily, past, SOURCES)
    latest = {"date": today, "collected_at_utc": now.isoformat(), "schema_version": 2,
              "status": "PARTIAL" if any(h["status"] == "ERROR" for h in health) else "OK",
              "source_health": health, "source_billboard": per_source, "billboard": rank,
              "research_queue": create_research_queue(per_source),
              "investment": {"state": "NOT_EVALUATED", "reason": "No verified security pricing, fundamentals or backtest; no trading signals."}}
    # Snapshot retains statistics, term counts, provenance URLs only — no raw post text.
    day_path = data_dir / (today + ".json")
    day_path.write_text(json.dumps(daily, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    out_path = DATA / "latest.json"
    temp = DATA / "latest.tmp"
    temp.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, out_path)
    print(json.dumps({"date": today, "observations": len(good), "successful_sources": sum(h["status"] == "OK" for h in health),
                      "errors": sum(h["status"] == "ERROR" for h in health), "source_billboards": sum(bool(x["top5"]) for x in per_source.values())}))
    return latest

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
