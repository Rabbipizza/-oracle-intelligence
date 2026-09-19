#!/usr/bin/env python3
"""Evaluate ORACLE Source Coverage Gate from normalized snapshots."""
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

CFG=json.loads(Path("source-gate.json").read_text())
SNAP=Path("data/source_snapshots")
OUT=Path("data/source-gate-status.json")

def load():
    rows=[]
    if SNAP.exists():
        for p in SNAP.glob("*.json"):
            try:
                x=json.loads(p.read_text())
                m=x.get("meta",{})
                rows.append({"file":str(p),"family":m.get("family"),"source":m.get("source"),"primary":bool(m.get("primary")),"fetched_at":m.get("fetched_at")})
            except Exception:
                pass
    return rows

rows=load()
families=sorted({r["family"] for r in rows if r["family"]})
primary=sum(1 for r in rows if r["primary"])
g=CFG["gate"]
coverage=len(families)>=g["min_independent_families"] and primary>=g["min_primary_sources"]
status={
 "generated_at":datetime.now(timezone.utc).isoformat(),
 "independent_families":families,
 "family_count":len(families),
 "primary_snapshot_count":primary,
 "coverage_gate_pass":coverage,
 "economic_transmission":"REQUIRES_ANALYST_PROOF",
 "company_capture":"REQUIRES_ANALYST_PROOF",
 "trend_status":"PARTIAL" if coverage else "UNPROVEN",
 "rule":"Coverage alone never makes a trend PROVEN or a company GREEN."
}
OUT.parent.mkdir(parents=True,exist_ok=True)
OUT.write_text(json.dumps(status,indent=2))
print(json.dumps(status))
