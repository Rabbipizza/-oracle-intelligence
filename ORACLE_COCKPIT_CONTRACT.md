# ORACLE-IA Cockpit — LOCKED APPROVED FORMAT
STATUS: LOCKED
REFERENCE_COMMIT: 9287074b4f1bb47e8e1ce528241f7b2fc546b0d2
APPROVED_FORMAT_DATE: 2026-09-19

This exact cockpit layout is the daily UI reference.

Immutable presentation:
1. Top 5 trends.
2. Billboard 20.
   Columns: Rang | Δ rang | Société | Perf. cours J-1 | Trend | Feu | Leader | Gap.
   Δ rang and market performance J-1 are independent.
3. Performance indicative ORACLE vs QQQ.
   Base simulation: 1,000 CHF.
4. Scientific discipline: FACT / INFERENCE / HYPOTHESIS + invalidation.

Approved extension already defined in conversation:
- Trend Billboard Top 20 and company rankings per trend may be surfaced without replacing the core cockpit.
- ORACLE vs QQQ methodology compares actually invested ORACLE capital with matched QQQ tranches; cash is excluded from official alpha.
- Historical evolution is integrated into Billboard/history; no separate replay page.

DAILY RUN RULE: DATA ONLY. Update values, rankings, movements, prices, trends, evidence and history. Never redesign, reorder, rename core sections/columns, or change visual semantics during a daily run.
Any structural change requires an explicit user request.
