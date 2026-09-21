# ORACLE-IA COCKPIT — LOCKED DECISION FORMAT

STATUS: LOCKED AFTER USER-REQUESTED REDESIGN (2026-09-21)

The main cockpit must answer five questions in one glance:

1. **What is moving?** Ranked Billboard of validated trends with rank delta, state, 1-month median stock performance and market breadth.
2. **Who composes each trend?** Exactly 20 researched companies per validated trend, with role, proof state, local-currency price, 1-month sparkline, J-1 / 1W / 1M performance and relative 1M performance versus QQQ.
3. **What is investable now?** A decision section that visually separates GREEN entry-admissible names from ORANGE watchlist names. Momentum alone must never create or reorder a recommendation.
4. **What is the ORACLE simulated portfolio doing?** Position-level CHF value and P&L, plus total portfolio value and cash.
5. **Is ORACLE beating QQQ?** Matched-tranche ORACLE return, matched QQQ return and alpha in percentage points.

Research detail stays behind the decision layer. The cockpit may expose concise role/proof information, but raw source dumps and long causal-chain text do not belong in the main view.

Daily runs are data-only. They regenerate `data/cockpit.json`; they must not redesign the page. Structural cockpit changes require an explicit user request.

Traffic-light semantics are fixed:
- GREEN = ORACLE entry criteria currently validated.
- ORANGE = credible thesis / watchlist, at least one gate still open.
- RED = entry criteria not passed.

A portfolio holding never determines the traffic light.
