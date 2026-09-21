# ORACLE-IA Cockpit — LOCKED APPROVED FORMAT

STATUS: LOCKED
REFERENCE_COMMIT: 9287074b4f1bb47e8e1ce528241f7b2fc546b0d2
APPROVED_FORMAT_DATE: 2026-09-19

Daily UI reference:
1. Top 5 trends.
2. Billboard 20.
   Columns: Rang | Delta rang | Société | Perf. cours J-1 | Trend | Feu | Leader | Gap.
   Rank movement and market performance J-1 are independent.
3. Performance indicative ORACLE vs QQQ — base 1,000 CHF.
4. Scientific discipline — FACT / INFERENCE / HYPOTHESIS + invalidation.

Approved additions do not replace the core cockpit:
- Trend Billboard Top 20 and company rankings per trend.
- ORACLE vs QQQ compares actually invested ORACLE capital with matched QQQ tranches; cash excluded from official alpha.
- History stays integrated into Billboard/history; no separate replay.

DAILY RUN = DATA ONLY.
Never redesign, reorder, rename core sections/columns, or change visual semantics during a daily run.
Structural changes require an explicit user request.
