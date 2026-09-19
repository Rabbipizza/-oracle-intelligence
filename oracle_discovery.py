#!/usr/bin/env python3
"""ORACLE unsupervised discovery: lexical novelty/acceleration clusters from science snapshots.
No predefined investment themes. Output is candidate trends, never automatic PROVEN/GREEN.
"""
import json,re,math
from pathlib import Path
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta

SRC=Path("data/source_snapshots"); OUT=Path("data/discovery-candidates.json")
STOP=set("the a an and or of to in for on with by from is are as at using based via towards toward new we our this that these those be can".split())
def toks(s):
    return [w for w in re.findall(r"[a-z][a-z0-9-]{2,}",s.lower()) if w not in STOP]
docs=[]
for p in SRC.glob("arxiv_*.json"):
    try:
        x=json.loads(p.read_text())
        for d in x.get("data",[]): docs.append(d)
    except: pass
now=datetime.now(timezone.utc); recent=Counter(); prior=Counter(); examples=defaultdict(list)
for d in docs:
    try: dt=datetime.fromisoformat(d.get("published","").replace("Z","+00:00"))
    except: continue
    ts=toks((d.get("title") or "")+" "+(d.get("summary") or ""))
    grams=set(ts+[ts[i]+" "+ts[i+1] for i in range(len(ts)-1)])
    bucket=recent if dt>=now-timedelta(days=14) else prior
    for g in grams:
        bucket[g]+=1
        if len(examples[g])<3: examples[g].append(d.get("title",""))
cand=[]
for term,n in recent.items():
    if n<2: continue
    old=prior.get(term,0)
    accel=(n+1)/(old+1)
    novelty=1/(old+1)
    score=round(math.log1p(n)*accel*novelty,4)
    cand.append({"term":term,"recent_docs":n,"prior_docs":old,"acceleration":round(accel,2),"novelty":round(novelty,3),"discovery_score":score,"examples":examples[term]})
cand=sorted(cand,key=lambda x:x["discovery_score"],reverse=True)[:100]
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps({"generated_at":now.isoformat(),"method":"unsupervised lexical novelty+acceleration; candidate generation only","candidates":cand},indent=2))
print("candidates",len(cand))
