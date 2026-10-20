# ORACLE-IA — research cockpit

ORACLE discovers emerging signals, separates issuer-level primary evidence from market timing, and produces a fail-closed research cockpit. It never sends orders.

## Three separate states

- `portfolio.json`: user-authoritative ACTUAL baseline: AAON CHF 40 initial cost on 2026-09-04, CHF 960 cash. No GEV/QQQ execution is confirmed. A decision or rebuild never writes this file.
- `decision-state.json`: current TARGET recommendations and their reasons/invalidations. ACTUAL cost allocations are read from the ledger, never from previous targets.
- `portfolio-simulated.json`: the previous AAON/GEV/QQQ hypothetical tranches, explicitly SIMULATED. Rebuilding its valuation never changes ACTUAL.

ACTUAL valuation uses the verified baseline close and USD/CHF to derive baseline units from the confirmed cost. This convention is visible in the cockpit and is not a broker fill confirmation. ACTUAL allocation labels use initial costs, not current market weights.

## Data admission

`oracle_data_quality.py` is shared by decision generation and final validation. Entry requires at least 22 valid dated positive finite closes, including the common QQQ valuation date. Critical ACTUAL/model holdings, positive targets and every investable signal/sizing are checked independently of the displayed Top 20. The collector includes ledger holdings and targets outside the radar and retains history covering the earliest entry and baseline.

Missing radar data is `DATA_UNAVAILABLE`: no GREEN, entry, target, or positive sizing. Provider errors and their HTTP status are retained; valid radar constituents can still be published. Critical failures block publication, preserve ACTUAL, and make incomplete portfolio totals unavailable. FX must be positive, finite and observed at/before each valuation, with a maximum four-calendar-day carry for weekends/holidays. The production snapshot must be at most four calendar days old and cannot be future dated. This conservative policy can block a valid illiquid or non-US constituent; no stale fallback is silently admitted.

## Benchmark and funnel

ACTUAL compares the complete initial CHF 1,000 (cash included) to CHF 1,000 hypothetically invested in QQQ from 2026-09-04. Both entry and current USD/CHF are applied. Alpha is shown in CHF and percentage points; negative alpha is an audit warning and never a deployment failure. The separate model retains its explicitly simulated matched-tranche comparison.

`data/funnel-audit.json` reconciles all dossier maturity counts, capture reviews, new promotions and pre-existing explicit primary proofs. Each rejected capture review lists its blockers; blocker counts overlap. Trend proof alone cannot create company capture. Previously automatic PROVEN records are rechecked and demoted if their original requirements no longer pass.

## Tests and historical review

No dependency installation or network calls are needed for the regression suite:

```sh
python -m unittest discover -v -p 'test_oracle_*.py'
python oracle_logic_tests.py
node test_oracle_ui.cjs
```

The unit suite exercises the real collector/allocator/cockpit/validator with synthetic offline inputs. It includes HTTP 404, missing holdings outside the radar, invalid/short/stale prices, missing entry/current FX, ledger isolation, cash-inclusive benchmark, proof inheritance, and publication integrity.

Rebuild only the checked-in historical snapshot (no source ingestion, git push, deployment or orders):

```sh
python oracle_build.py --replay-date 2026-10-13 --output .preview-site
```

`--replay-date` is explicit historical validation. Its report is marked HISTORICAL_REPLAY and its payload HISTORICAL_PREVIEW. `oracle_release.py` refuses to deploy it. The currently checked-in market date remains 2026-10-13; a successful replay does not claim fresh market data or production approval.

## Publication

`oracle-ci.yml` runs the tests and historical rebuild on pull requests with read-only permissions. The former unconditional `pages.yml` path is removed.

The production workflow is gated by the repository variable `ORACLE_PRODUCTION_ENABLED == 'true'`. Keep that variable unset/false until the exact correction commit has passed CI and its cockpit has been reviewed. No production run is necessary to review this PR.

An enabled production run tests its exact source SHA, ingests sources/market data, and calls `python oracle_build.py --output .verified-site` without a replay override. Validation precedes audit/persistence. The workflow refuses a concurrent main change instead of rebasing validated data onto different code. A SHA-256 manifest seals the public files; deploy downloads and verifies that immutable artifact instead of checking out a newer main. Failure diagnostics are retained privately as Actions artifacts, without publishing a site.

## TMRC investigation

Run [38560418700](https://github.com/Rabbipizza/-oracle-intelligence/actions/runs/38560418700) recorded a Yahoo chart HTTP 404 for `TMRC`. Historical issuer releases identify Texas Mineral Resources as OTCQB: TMRC ([2024 primary release](https://www.tmrcorp.com/news/press_releases/2024/index.php?content_id=266)); they do not prove current provider coverage. At the correction review, the issuer's newsroom redirected to a “Website is currently unavailable” page. Current listing/provider equivalence therefore remains unverified.

No alternate ticker, successor security, provider, or synthetic history is substituted. HTTP 404 is recorded as DATA_UNAVAILABLE without retrying it as a transient error. Re-admission requires verified provider identity, currency/exchange metadata and dated positive price history. Transient failures retain bounded retries.
