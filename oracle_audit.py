#!/usr/bin/env python3
"""ORACLE immutable run-level evidence audit manifest."""
import json,hashlib
from pathlib import Path
from datetime import datetime,timezone
root=Path("data"); files=sorted([p for p in root.rglob("*.json") if "audit" not in p.parts])
rows=[]
for p in files:
    b=p.read_bytes(); rows.append({"path":str(p),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
now=datetime.now(timezone.utc); stamp=now.strftime("%Y%m%dT%H%M%SZ")
adir=Path("data/audit"); adir.mkdir(parents=True,exist_ok=True)
manifest={"run_id":stamp,"created_at":now.isoformat(),"files":rows}
out=adir/(stamp+".json"); out.write_text(json.dumps(manifest,indent=2))
(adir/"latest.json").write_text(json.dumps(manifest,indent=2))
print(out)
