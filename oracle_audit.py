#!/usr/bin/env python3
"""ORACLE immutable daily evidence audit manifest."""
import json,hashlib
from pathlib import Path
from datetime import datetime,timezone
root=Path("data"); files=sorted([p for p in root.rglob("*.json") if "audit" not in p.parts])
rows=[]
for p in files:
    b=p.read_bytes(); rows.append({"path":str(p),"sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b)})
stamp=datetime.now(timezone.utc).strftime("%Y-%m-%d")
out=Path("data/audit")/(stamp+".json"); out.parent.mkdir(parents=True,exist_ok=True)
if not out.exists(): out.write_text(json.dumps({"date":stamp,"created_at":datetime.now(timezone.utc).isoformat(),"files":rows},indent=2))
print(out)
