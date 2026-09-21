# ORACLE-IA Cockpit — VALIDATED UI CONTRACT

STATUS: LOCKED
REFERENCE_COMMIT: 76073899b08719d1d80b867fb9ed17f0c8622ead
RESTORED: 2026-09-21

The validated longitudinal cockpit presentation is the immutable UI reference.

Daily runs are DATA-ONLY updates. They may update rankings, trends, company rows, movements, performance, Fit/Timing values, causal-chain evidence, history and sources. They MUST NOT redesign the cockpit.

Core validated presentation:
- Investment Intelligence Cockpit header.
- Longitudinal company Billboard/ranking with rank movement arrows.
- Company trend, Fit, Timing/Entry, leader-relative progress and decision.
- J-1 movements integrated into the ranking/history.
- Top trends cards.
- Long-term trend and company history.
- Causal chains: Trend → economic need/bottleneck → picks & shovels → materials → companies.
- Early Compounders.
- Entry/timing logic separate from Fit.
- Scientific walk-forward evaluation versus QQQ (and SPY where retained by methodology).
- No hindsight reconstruction; missing data remain NULL/empty.
- Historical snapshots are append-only.

Additional already-approved daily fields may be populated inside the existing logical sections without redesigning the page, including stock performance vs J-1 and ORACLE-vs-QQQ 1,000 CHF simulation.

STRUCTURAL CHANGE RULE:
Any layout, navigation, section-order, visual-system or methodology-presentation change requires an explicit user-requested UI migration. A daily ORACLE run never changes presentation.
