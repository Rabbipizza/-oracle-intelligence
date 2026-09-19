#!/usr/bin/env python3
"""ORACLE per-candidate Source Coverage Gate. Global inventory is diagnostic only."""
import json,re
from pathlib import Path
from datetime import datetime,timezone
CFG=json.loads(Path("source-gate.json").read_text()); SNAP=Path("data/source_snapshots")
DISC=Path("data/discovery-candidates.json"); OUT=Path("data/source-gate-status.json")

def words(s): return {x for x in re.findall(r"[a-z0-9-]{3,}",(s or "").lower())}
def load_snaps():
    out=[]
    for p in SNAP.glob("*.json"):
        try:
            x=json.loads(p.read_text()); m=x.get("meta",{})
            text=json.dumps(x.get("data",[]),ensure_ascii=False).lower()
            out.append({"file":str(p),"family":m.get("family"),"source":m.get("source"),"primary":bool(m.get("primary")),"text":text})
        except Exception: pass
    return out
rows=load_snaps(); g=CFG["gate"]
disc=json.loads(DISC.read_text()) if DISC.exists() else {"candidates":[]}
candidate_status=[]
for c in disc.get("candidates",[]):
    tw=words(c.get("term",""))
    matched=[r for r in rows if tw and all(w in r["text"] for w in tw)]
    fam=sorted({r["family"] for r in matched if r["family"]}); prim=sum(1 for r in matched if r["primary"])
    coverage=len(fam)>=g["min_independent_families"] and prim>=g["min_primary_sources"]
    candidate_status.append({"term":c.get("term"),"families":fam,"family_count":len(fam),"primary_snapshots":prim,"coverage_gate_pass":coverage,"economic_transmission":"REQUIRES_ANALYST_PROOF","company_capture":"REQUIRES_ANALYST_PROOF","trend_status":"PARTIAL" if coverage else "UNPROVEN"})
families=sorted({r["family"] for r in rows if r["family"]})
status={"generated_at":datetime.now(timezone.utc).isoformat(),"discovery_quality":disc.get("quality"),"global_source_inventory":{"families":families,"family_count":len(families),"primary_snapshot_count":sum(1 for r in rows if r["primary"])},"candidate_gates":candidate_status,"rule":"A candidate passes coverage only on its own matched evidence. Global source diversity never proves a trend; economic transmission and company capture require separate proof."}
OUT.write_text(json.dumps(status,indent=2)); print(json.dumps({"discovery_quality":status["discovery_quality"],"candidate_gates":len(candidate_status)}))
