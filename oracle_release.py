#!/usr/bin/env python3
"""Package and verify the immutable validated Pages payload, never a moving branch."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from oracle_data_quality import iso_date, MAX_SNAPSHOT_AGE_DAYS

PUBLIC_FILES=("index.html","data/cockpit.json","data/validation.json","data/funnel-audit.json")


def package(source, destination, source_sha, replay=False):
    if destination.exists(): raise ValueError("output directory already exists")
    report=json.loads((source/"data/validation.json").read_text())
    if report.get("status")!="PASS": raise ValueError("validation did not pass")
    destination.mkdir(parents=True)
    hashes={}
    for name in PUBLIC_FILES:
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,target)
        hashes[name]=hashlib.sha256(target.read_bytes()).hexdigest()
    manifest={"source_sha":source_sha,"kind":"HISTORICAL_PREVIEW" if replay else "PRODUCTION",
              "files":hashes,"data_as_of":report["data_as_of"]}
    (destination/"release.json").write_text(json.dumps(manifest,indent=2)+"\n")
    if not replay: verify(destination)


def verify(directory):
    manifest=json.loads((directory/"release.json").read_text())
    report=json.loads((directory/"data/validation.json").read_text())
    cockpit=json.loads((directory/"data/cockpit.json").read_text())
    if manifest.get("kind")!="PRODUCTION" or report.get("validation_mode")!="PRODUCTION" or report.get("status")!="PASS" or report.get("errors"):
        raise ValueError("only a successful production validation can be deployed")
    if set(manifest.get("files",{}))!=set(PUBLIC_FILES): raise ValueError("unexpected release files")
    for name,digest in manifest["files"].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=digest: raise ValueError("release hash mismatch:"+name)
    day=iso_date(manifest.get("data_as_of"))
    if not day or not 0 <= (datetime.now(timezone.utc).date()-day).days <= MAX_SNAPSHOT_AGE_DAYS:
        raise ValueError("release data is stale or future dated")
    if cockpit.get("data_as_of")!=day.isoformat() or report.get("data_as_of")!=day.isoformat(): raise ValueError("release date mismatch")
    return manifest


if __name__=="__main__":
    import sys
    print(json.dumps(verify(Path(sys.argv[1]))))
