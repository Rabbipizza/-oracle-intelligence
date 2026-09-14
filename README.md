# ORACLE-IA — Daily Research Library

Supabase is the append-only source of truth. Every daily run is a new dated snapshot; prior trend conclusions, evidence, company candidates and leader-relative comparisons must never be overwritten.

The cockpit must always render two layers: the current decision view and the full longitudinal history. Trend keys may become more precise over time; semantic normalization is allowed only in the presentation layer and must not alter stored snapshots.

Alternative signals use two layers in parallel:
- Semrush when quota is available, as a confirmation/enrichment source.
- Free/public frontier signals including Common Crawl, GDELT, GitHub, OpenAlex/Crossref, arXiv/bioRxiv/medRxiv, USPTO/EPO, SAM.gov/USAspending/TED, NIH/NSF/ARPA-E/DARPA, standards bodies, hiring and capacity announcements.

Semrush is not a critical dependency. A depleted quota must not block a daily run.

Daily workflow:
1. Detect the Top 5 accelerating trends without imposing themes.
2. Build causal chains and bottlenecks.
3. Map picks & shovels and raw materials.
4. Rank emerging listed companies and benchmark each against the relevant segment leader.
5. Separate company Fit from investment Timing.
6. Save a new dated Supabase snapshot.
7. Compare J vs J-1 and maintain multi-day / multi-week trajectories.
8. Regenerate the cockpit from the complete stored history.
9. Verify both Supabase persistence and the GitHub cockpit update.