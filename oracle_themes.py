"""ORACLE theme Billboard: rankings belong to THEMES, not provider names.

The top 20 is built from comparable source-normalized phrases, and movement is
only computed after two complete 7-day observation windows. During warmup the
rank is labelled PREVIEW, changes and chart longevity are unknown (null).
"""
from __future__ import annotations
from collections import defaultdict
from datetime import date, timedelta
import re

THEMES = {
    "geek": {"name": "Geek & Gaming", "description": "Jeux vidéo, anime, manga, comics, cosplay, culture geek", "icon": "🎮"},
    "pop_culture": {"name": "Pop culture", "description": "Cinéma, séries, musique et phénomènes culturels", "icon": "🎬"},
    "technology": {"name": "Technologie & IA", "description": "IA, puces, logiciels et robotique", "icon": "🧠"},
    "science": {"name": "Science & innovation", "description": "Recherche, découvertes et quantique", "icon": "🔬"},
    "health": {"name": "Santé & biotech", "description": "Médecine, soins, biotechnologies", "icon": "🧬"},
    "economics": {"name": "Économie & finance", "description": "Taux, inflation, macroéconomie et entreprises", "icon": "📈"},
    "geopolitics": {"name": "Géopolitique", "description": "Élections, relations internationales, défense et lois", "icon": "🌍"},
    "climate": {"name": "Climat & géographie", "description": "Climat, écosystèmes, territoires", "icon": "🌱"},
    "energy": {"name": "Énergie & matières premières", "description": "Électricité, pétrole, minerais et ressources", "icon": "⚡"},
    "society": {"name": "Société & démographie", "description": "Population, éducation, migrations et emploi", "icon": "👥"},
    "industry": {"name": "Industrie & supply chain", "description": "Usines, logistique, capacité de production", "icon": "🏭"},
}
SOURCE_DEFAULTS = {
    "geek": "geek", "culture": "pop_culture", "social": "technology",
    "news": "pop_culture", "technology": "technology", "science": "science",
    "patents": "science", "macroeconomics": "economics", "markets": "economics",
    "geopolitics": "geopolitics", "geography": "climate", "demography": "society",
    "commodities": "energy", "supply_chain": "industry", "health": "health"
}
# Specific phrases can override default source category. This is a transparent
# *heuristic*, not a validated multilingual topic clustering model.
RULES = [
    ("geek", r"\b(?:gaming|gamer|gamers|video games?|jeux? vid[eé]o|pokemon|pokémon|nintendo|playstation|xbox|steam deck|cosplay|anime|manga|comic books?|comics|marvel|dc comics|star wars|star trek|esports?|e-sports?|minecraft|roblox|dungeons dragons)\b"),
    ("energy", r"\b(?:lithium|uranium|copper|cuivre|batter(?:y|ies)|batterie|electric grid|energy storage|solar power|nuclear power|renewable energy|oil prices?|rare earths)\b"),
    ("health", r"\b(?:cancer|oncology|vaccine|vaccin|clinical trial|clinical trials|drug discovery|biotech|alzheimer|diabetes|genomics|gene therapy)\b"),
    ("technology", r"\b(?:artificial intelligence|machine learning|large language models?|llm agents?|gpu clusters?|semiconductors?|robotics?|quantum computing|ai agents?|coding agents?)\b"),
    ("economics", r"\b(?:interest rates?|inflation|unemployment|central bank|bond yields?|economic growth|recession)\b"),
    ("geopolitics", r"\b(?:election|élection|sanctions?|tariffs?|trade war|geopolitic|political crisis)\b"),
    ("climate", r"\b(?:global warming|climate change|climate crisis|wildfires?|drought|flooding|biodiversity)\b"),
    ("society", r"\b(?:birth rate|population growth|migration|demographic|aging population|student debt)\b"),
    ("industry", r"\b(?:supply chain|manufacturing capacity|factory automation|industrial robots?|shipping costs?|semiconductor packaging)\b"),
]
COMPILED = [(name, re.compile(pattern, re.IGNORECASE)) for name, pattern in RULES]
# Avoid spurious chart entries from templated legal and research-document titles.
NOISE = frozenset({
    "notice inventory", "inventory completion", "notice inventory completion",
    "commission implementing", "commission implementing regulation",
    "european parliament", "states senate", "united states senate",
    "language models", "large language", "error correction",
    "quantum error", "notice intended", "study finds",
    "bbc news", "cbs news", "abc news", "new york times",
    "implementing regulation", "implementing regulation november",
    "regulation november", "announces approval",
    "announces approval two", "applications mutual",
    "notice intended repatriation"
})

def choose_theme(phrase, source_domain):
    phrase = phrase.strip().casefold()
    for theme_id, regex in COMPILED:
        if regex.search(phrase):
            return theme_id
    return SOURCE_DEFAULTS.get(source_domain, "pop_culture")

def _daily_theme_data(snapshot, source_domains):
    """Source-normalized observations. A source contributes equal weight to
    its category, not a misleading bulk dominance by 500 Wikipedia pages."""
    results = {key: defaultdict(dict) for key in THEMES}
    for source_id, sample in snapshot.get("sources", {}).items():
        if not isinstance(sample, dict) or sample.get("documents", 0) < 10:
            # Tiny RSS feeds (one press release / day) are not robust
            # wording-frequency denominators. Do not show 1/1 = 10000.
            continue
        source_domain = source_domains.get(source_id, "news")
        volume = sample["documents"]
        for phrase, info in sample.get("terms", {}).items():
            if phrase.casefold() in NOISE or info.get("count", 0) < 2:
                continue
            if re.search(r"\b(?:notice|implementing|repatriation|regulation november)\b", phrase, re.I):
                continue
            category = choose_theme(phrase, source_domain)
            results[category][phrase][source_id] = {
                # Shrink low-sample ranked-list sources to limit dominance.
                # This is a preliminary conservative heuristic, not a
                # statistical estimate of population prevalence.
                "rate": 10000.0 * info["count"] / (volume + 80),
                "count": info["count"],
                "links": info.get("links", [])[:3]
            }
    return results

def _rank_theme(daily_snapshots, source_domains, theme_id):
    records = {}
    for snapshot in daily_snapshots:
        for phrase, observations in _daily_theme_data(snapshot, source_domains)[theme_id].items():
            obj = records.setdefault(phrase, {"rates":defaultdict(list),"counts":0,"links":[]})
            for source_id, observation in observations.items():
                obj["rates"][source_id].append(observation["rate"])
                obj["counts"] += observation["count"]
                for link in observation["links"]:
                    if link not in obj["links"] and len(obj["links"]) < 4:
                        obj["links"].append(link)
    results=[]
    for phrase, obj in records.items():
        # Mean of each contributing source's observed daily rates, then mean
        # across sources. Never pool source denominators (incompatible lists).
        each_source = [sum(vals) / len(vals) for vals in obj["rates"].values() if vals]
        if not each_source:
            continue
        score = sum(each_source) / len(each_source)
        results.append({
            "term": phrase,
            "score": round(score, 3),
            "mentions": obj["counts"],
            "source_count": len(each_source),
            "source_ids": sorted(obj["rates"]),
            "evidence_urls": obj["links"],
        })
    results.sort(key=lambda x: (-x["score"], -x["source_count"], -x["mentions"], x["term"]))
    return results[:20]

def _complete_window(rows, dates, source_ids):
    """Require at least one source measured for all seven calendar days.
    The comparison later uses identical eligible sources across weeks."""
    bydate = {r.get("date"): r for r in rows}
    if any(day not in bydate for day in dates):
        return []
    eligible = []
    for source_id in source_ids:
        if all(
            any(h.get("source")==source_id and h.get("status") in ("OK", "EMPTY")
                for h in bydate[day].get("source_health", []))
            and source_id in bydate[day].get("sources", {})
            for day in dates
        ):
            eligible.append(source_id)
    return eligible

def make_billboard(day_string, today_snapshot, previous_snapshots, sources):
    source_domains = {row[0]: row[2] for row in sources}
    all_sources = set(source_domains)
    bydate = {s.get("date"):s for s in previous_snapshots if s.get("date", "") < day_string}
    bydate[day_string] = today_snapshot
    d = date.fromisoformat(day_string)
    recent_dates = [(d-timedelta(days=i)).isoformat() for i in range(6,-1,-1)]
    prior_dates = [(d-timedelta(days=i)).isoformat() for i in range(13,6,-1)]
    recent_eligible=set(_complete_window(list(bydate.values()),recent_dates,all_sources))
    prior_eligible=set(_complete_window(list(bydate.values()),prior_dates,all_sources))
    common=recent_eligible & prior_eligible
    # "Preview": only today's real observations, no fictitious prior ranking.
    def filter_sources(record,allowed):
        return {"sources": {k:v for k,v in record.get("sources", {}).items() if k in allowed}}
    weekly_ready=bool(common)
    if weekly_ready:
        recent=[filter_sources(bydate[x],common) for x in recent_dates]
        previous=[filter_sources(bydate[x],common) for x in prior_dates]
    else:
        recent=[filter_sources(today_snapshot,all_sources)]
        previous=[]
    charts={}
    for theme_id,meta in THEMES.items():
        current=_rank_theme(recent,source_domains,theme_id)
        prior=_rank_theme(previous,source_domains,theme_id) if weekly_ready else []
        old_positions={x["term"]:i+1 for i,x in enumerate(prior)}
        entries=[]
        for idx,row in enumerate(current,1):
            prev=old_positions.get(row["term"])
            if not weekly_ready:
                status="UNAVAILABLE"
                movement=None
            elif prev is None:
                status="NEW"
                movement=None
            else:
                movement=prev-idx
                status="UP" if movement>0 else "DOWN" if movement<0 else "SAME"
            entries.append({
                **row, "rank":idx, "previous_rank":prev if weekly_ready else None,
                "movement":movement, "movement_status":status,
                "weeks_on_chart":None,
            })
        charts[theme_id]={
            **meta,"theme_id":theme_id,
            "state":"WEEKLY_COMPARABLE" if weekly_ready else "PREVIEW",
            "comparison_available":weekly_ready,
            "week_end":day_string,
            "sources_compared":len(common) if weekly_ready else 0,
            "window": "7D_VS_PRIOR_7D" if weekly_ready else "TODAY_ONLY",
            "top20": entries
        }
    return charts
