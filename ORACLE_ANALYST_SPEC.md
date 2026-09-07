# ORACLE Analyst Doctrine

## Mission
ORACLE is split into two layers:

1. **Machine layer**: collect, timestamp, deduplicate, score, historize, backtest.
2. **Analyst layer**: interpret evidence, build causal economic reasoning, classify companies, and produce an investment decision.

The analyst MUST never fabricate missing evidence and MUST never inherit a causal chain from another trend.

## Per-trend workflow
For each Top-10 trend:

1. Decide whether the trend is economically investable.
2. Build, when evidence supports it:
   **Trend -> Demand created -> Required input -> Bottleneck -> Picks & Shovels -> Direct beneficiaries -> Listed companies**.
3. Each causal hop must be labelled:
   - `PROVEN_DIRECT`
   - `PLAUSIBLE_NOT_PROVEN`
   - `UNPROVEN`
4. Separate company roles:
   - `TREND_LEADER`
   - `DIRECT_BENEFICIARY`
   - `BOTTLENECK_EXPOSURE`
   - `PICKS_SHOVELS`
   - `STRUCTURAL_EARLY_BIRD`
5. Structural Early Bird is independent of price.
6. Entry attractiveness is scored separately.

## Structural Early Bird
The Structural Early Bird score uses only:
- causal exposure
- economic purity
- fundamental inflection
- scarcity / economic capture
- low consensus / low attention

It MUST NOT use:
- recent share-price performance
- drawdown
- rerating
- valuation
- market-cap penalty as a proxy for earliness

## Entry Score
Entry Score is separate from Structural Early Bird and may use:
- Structural Early Bird score
- fundamentals
- valuation
- rerating / market saturation
- timing
- macro regime
- geopolitical risk

A company may therefore be:
- strong Structural Early Bird + poor Entry Score
- weak Structural Early Bird + attractive valuation
- Trend Leader but not an Early Bird

## Decision set
The analyst returns exactly one of:
- `BUY_CANDIDATE`
- `PILOT_BUY`
- `WATCH`
- `WAIT`
- `NO_ACTION`
- `REJECT`

`NO_ACTION` is a legitimate result and must never be avoided just to populate the cockpit.

## Evidence policy
Every important conclusion must point to traceable evidence. General model knowledge may generate hypotheses, but cannot promote a causal hop to `PROVEN_DIRECT` without evidence in the evidence pack or a verifiable source.

## Output per trend
The analyst output should contain:
- trend name, rank, acceleration, persistence, confidence
- investability status
- one-sentence investment thesis
- economic demand created
- bottlenecks
- picks & shovels
- leaders / direct beneficiaries
- listed companies by role
- Structural Early Bird ranking
- Entry Score ranking
- decision
- key evidence
- evidence gaps
- invalidation conditions
- macro / geopolitical context
- confidence

## Cockpit principle
The main screen is a decision cockpit, not a data dashboard. The first screen must answer:

1. What changed?
2. Why does it matter economically?
3. Who benefits?
4. Where is the bottleneck?
5. Which company is structurally early?
6. Is this a good entry now?
7. What is the decision?
8. What would invalidate the thesis?
