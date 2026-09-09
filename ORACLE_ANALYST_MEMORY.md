# ORACLE Analyst Memory

## Purpose

ORACLE detects and measures structural trends from data. The analyst layer then interprets those detected trends and stores a persistent, versioned dossier that grows over time instead of restarting from zero at each run.

## Operating loop

1. ORACLE ingests and detects signals / trends.
2. The analyst reads only the data available at the evaluation timestamp.
3. The analyst interprets the trend through first-, second- and third-order economic consequences.
4. The interpretation is stored in `oracle_v6_analyst_memory` as an immutable versioned dossier.
5. Later runs retrieve the latest dossier, compare new evidence with prior hypotheses, enrich or invalidate parts of the thesis, and create a new version linked to the prior one.
6. The cockpit reads the current dossier and displays the whole chain:
   `TREND -> NEEDS -> BOTTLENECKS -> SOLUTIONS -> PICKS & SHOVELS -> COMPANIES / RAW MATERIALS -> ECONOMIC CAPTURE -> VALUATION / EARLY BIRD`.

## Scientific rule

Analyst reasoning creates hypotheses, not facts. Every downstream statement keeps an explicit state such as `ANALYST_HYPOTHESIS`, `EVIDENCE_BACKED`, `PARTIALLY_VALIDATED`, `VALIDATED`, or `INVALIDATED`. A company cannot become a validated BUY simply because it appears in an analyst dossier.

## Memory schema

Canonical storage is Supabase table `oracle_v6_analyst_memory`. Each record contains:

- `evaluation_as_of`: frozen data cutoff;
- `trend_key`: detected ORACLE trend;
- `executive_summary` and `body_md`: human-readable living dossier;
- `structured_analysis`: needs, bottleneck hypotheses, solution hypotheses, picks & shovels and investment implications;
- `evidence_refs`: data sources used for that version;
- `confidence_status`: evidence state;
- `supersedes_id`: prior dossier version when applicable;
- `model_version`: analyst version.

The view `oracle_v6_analyst_memory_current` exposes the latest non-invalidated dossier per trend and analysis type.

## Update policy

Never overwrite historical interpretation. New evidence creates a new version. New evidence may:

- reinforce a prior hypothesis;
- add a new need, bottleneck, solution or company;
- downgrade or invalidate an old hypothesis;
- change which picks & shovels are most economically attractive;
- change valuation / timing without changing the structural thesis.

This gives ORACLE a cumulative research memory and makes the system progressively more useful as data accumulates.
