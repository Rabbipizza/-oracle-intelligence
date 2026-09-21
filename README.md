# ORACLE-IA — Autonomous Investment Intelligence

ORACLE is a fail-closed research and simulation pipeline. It discovers emerging signals, keeps evidence separate from investment timing, maps validated trends to listed companies, prices the universe, updates a CHF 1,000 simulated portfolio and publishes a decision cockpit.

## Live architecture

The repository is the operational source of truth for the current implementation. Every verified run writes dated source snapshots plus immutable audit manifests under `data/`. A run is persisted only after `oracle_validate.py` passes.

Pipeline:
1. Collect scholarly and public upstream evidence (arXiv when available, OpenAlex, Crossref, BLS, ECB, TED).
2. Detect accelerating phrases without promoting them automatically to validated trends.
3. Enrich candidate signals with public procurement evidence.
4. Apply a record-level, origin-deduplicated Source Coverage Gate.
5. Fetch EOD market data for QQQ and the full company universe and official ECB FX data.
6. Build the cockpit data product: trend pulse, Top 20 companies per trend, J-1 / 1W / 1M / relative-to-QQQ performance, entry state, portfolio simulation and benchmark.
7. Validate critical market, portfolio and discovery fields.
8. Commit only a verified snapshot and let GitHub Pages deploy the cockpit.

## Decision doctrine

Discovery, Selection, Entry and Sizing are separate layers. A company does not become GREEN because it is already in the simulated portfolio. GREEN means the current ORACLE entry gate is validated; ORANGE is a watchlist state with at least one open gate; RED means entry criteria are not passed.

A new trend is not promoted merely because a phrase accelerates. The Source Coverage Gate requires candidate-specific evidence across at least three independent source families and at least one primary origin; economic transmission and company capture remain separate proof requirements.

## Benchmark

The portfolio starts at CHF 1,000. The official ORACLE-vs-QQQ comparison is matched-tranche: every simulated ORACLE purchase is compared with the same CHF amount hypothetically invested in QQQ on the same date. Uninvested cash is shown in total portfolio value but excluded from official alpha.

## Automation

GitHub Actions runs ORACLE three times on weekdays and on relevant code/config pushes. Concurrency cancels superseded runs. The workflow fails closed if critical price/FX/portfolio/benchmark fields are missing.
