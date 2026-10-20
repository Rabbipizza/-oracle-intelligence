#!/usr/bin/env python3
"""Rebuild derived products with no ingestion, git writes, publication, or orders."""
import argparse
import subprocess
import sys
from pathlib import Path
from oracle_release import package

ROOT=Path(__file__).resolve().parent
STAGES=("oracle_decision.py","oracle_chain_builder.py","oracle_funnel_audit.py","oracle_cockpit.py",
        "oracle_signal_ledger.py","oracle_signal_performance.py")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-date",help="Explicit historical validation; payload is ineligible for deployment.")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    protected={p:p.read_bytes() for p in (Path("portfolio.json"),Path("portfolio-simulated.json"))}
    try:
        for name in STAGES:
            subprocess.run([sys.executable,str(ROOT/name)],check=True)
        command=[sys.executable,str(ROOT/"oracle_validate.py")]
        if args.replay_date: command += ["--replay-date",args.replay_date]
        subprocess.run(command,check=True)
        subprocess.run([sys.executable,str(ROOT/"oracle_audit.py")],check=True)
    finally:
        if any(p.read_bytes()!=data for p,data in protected.items()): raise RuntimeError("a derived-data build changed a portfolio ledger")
    if args.output:
        sha=subprocess.check_output(["git","-C",str(ROOT),"rev-parse","HEAD"],text=True).strip()
        package(Path("."),args.output,sha,replay=bool(args.replay_date))


if __name__=="__main__": main()
