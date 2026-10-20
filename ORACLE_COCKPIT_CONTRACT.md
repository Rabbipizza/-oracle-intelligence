# ORACLE-IA COCKPIT — LOCKED DECISION FORMAT

STATUS: LOCKED AFTER USER-REQUESTED REDESIGN (2026-09-21)

The main cockpit must answer five questions in one glance:

1. **What is moving?** Ranked Billboard of validated trends with rank delta, state, 1-month median stock performance and market breadth.
2. **Who composes each trend?** Exactly 20 researched companies per validated trend, with role, proof state, local-currency price, 1-month sparkline, J-1 / 1W / 1M performance and relative 1M performance versus QQQ.
3. **What is investable now?** A decision section that visually separates GREEN entry-admissible names from ORANGE watchlist names. Momentum alone must never create or reorder a recommendation.
4. **What is ACTUAL doing?** User-authoritative AAON baseline cost CHF 40 and CHF 960 cash, with no inferred GEV/QQQ executions. TARGET is a recommendation; the hypothetical fully invested ledger is shown separately.
5. **Is ACTUAL beating QQQ?** Full initial CHF 1,000, including cash, versus synthetic QQQ from 2026-09-04 with verified USD/CHF; show alpha CHF and percentage points. The model’s matched-tranche comparison remains simulation-only.

Research detail stays behind the decision layer. The cockpit may expose concise role/proof information, but raw source dumps and long causal-chain text do not belong in the main view.

Daily runs are data-only. They regenerate `data/cockpit.json`; they must not redesign the page. Structural cockpit changes require an explicit user request.

Traffic-light semantics are fixed:
- GREEN = ORACLE entry criteria currently validated.
- ORANGE = credible thesis / watchlist, at least one gate still open.
- RED = entry criteria not passed.

A portfolio holding never determines the traffic light.

Issue #3 correction: unavailable radar data is explicitly DATA_UNAVAILABLE, with no entry, sizing or target. Critical holdings, investable recommendations, QQQ and FX remain fail-closed independently of Top 20 membership. The page shows the market date, rejection reasons, invalidations and an explicit historical-data warning. Daily runs cannot alter either ledger.
