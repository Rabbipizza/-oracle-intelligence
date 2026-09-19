#!/usr/bin/env python3
"""ORACLE discovery v2: deduplicated phrase acceleration from science snapshots.
Candidate generation only: never automatic PROVEN/GREEN.
"""
import json,re,math
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta

SRC=Path("data/source_snapshots"); OUT=Path("data/discovery-candidates.json")
RECENT_DAYS=14; BASELINE_DAYS=90
STOP=set("""the a an and or of to in for on with by from is are as at using based via towards toward new we our this that these those be can
while which without but into over only across present show introduce than then also such have has had their its it they them were was been being
model models method methods framework approach approaches results result study studies paper work task tasks data system systems learning
training performance proposed propose demonstrate shows use used through between under where when how what who why more most less each both
all any some many may might could would should do does did done not no yes
""".split())

def tokens(s):
    return [w for w in re.findall(r"[a-z][a-z0-9-]{2,}",(s or "").lower()) if w not in STOP]

def canonical_id(d):
    raw=str(d.get("id") or d.get("url") or "")
    m=re.search(r"(?:abs/)?(\d{4}\.\d{4,5})(?:v\d+)?",raw)
    if m: return m.group(1)
    return re.sub(r"v\d+$","",raw) or (d.get("title") or "").strip().lower()

# Deduplicate papers across repeated snapshots/versions.
unique={}
for p in SRC.glob("arxiv_*.json"):
    try:
        x=json.loads(p.read_text())
        for d in x.get("data",[]):
            k=canonical_id(d)
            if k and k not in unique: unique[k]=d
    except Exception:
        continue

now=datetime.now(timezone.utc)
recent=Counter(); baseline=Counter(); examples=defaultdict(list)
recent_docs=baseline_docs=0
for d in unique.values():
    try: dt=datetime.fromisoformat((d.get("published") or "").replace("Z","+00:00"))
    except Exception: continue
    age=(now-dt).total_seconds()/86400
    if age < 0: continue
    if age <= RECENT_DAYS: bucket=recent; recent_docs+=1
    elif age <= RECENT_DAYS+BASELINE_DAYS: bucket=baseline; baseline_docs+=1
    else: continue
    ts=tokens((d.get("title") or "")+" "+(d.get("summary") or ""))
    # Phrases carry more semantic signal than generic unigrams.
    grams=set()
    for n in (2,3):
        grams.update(" ".join(ts[i:i+n]) for i in range(len(ts)-n+1))
    for g in grams:
        bucket[g]+=1
        if len(examples[g])<3: examples[g].append(d.get("title",""))

cand=[]
for term,n in recent.items():
    if n < 2: continue
    old=baseline.get(term,0)
    # Compare document rates, not raw counts; Bayesian smoothing prevents division explosions.
    rr=(n+0.5)/(max(recent_docs,1)+1)
    br=(old+0.5)/(max(baseline_docs,1)+1)
    accel=rr/br
    support=n/max(recent_docs,1)
    score=math.log1p(n)*math.log1p(max(accel,0))*math.sqrt(support*1000)
    cand.append({
      "term":term,"recent_docs":n,"baseline_docs":old,
      "recent_corpus_docs":recent_docs,"baseline_corpus_docs":baseline_docs,
      "acceleration":round(accel,3),"discovery_score":round(score,4),
      "examples":examples[term]
    })
cand=sorted(cand,key=lambda x:(x["discovery_score"],x["recent_docs"]),reverse=True)[:100]
quality="OK" if baseline_docs>=50 and recent_docs>=20 else "INSUFFICIENT_BASELINE"
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({
 "generated_at":now.isoformat(),
 "method":"v2 deduplicated 2-3gram document-frequency acceleration; 14d recent vs preceding 90d baseline",
 "quality":quality,
 "unique_papers":len(unique),"recent_docs":recent_docs,"baseline_docs":baseline_docs,
 "candidates":cand if quality=="OK" else []
},indent=2))
print("quality",quality,"unique",len(unique),"recent",recent_docs,"baseline",baseline_docs,"candidates",len(cand if quality=="OK" else []))
