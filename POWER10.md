# ORACLE POWER 10 — V1 prospective experiment

Goal: test whether ORACLE's **pre-existing, timestamped structural discoveries** plus market ignition can improve forward returns and reach successive portfolio high-water marks.

## Capital experiment
- Synthetic initial capital: CHF 50,000.
- Portfolio milestone: +10% (first HWM CHF 55,000), then next +10% HWM compounds from the achieved capital.
- Simulation/research only; no brokerage/order execution.
- Maximum single simulated position: 15%.
- Maximum deployed capital in V1: 60%.
- No forced investment and no forced sale at +10%.

## Anti-leak protocol
1. Company must exist in the timestamped ORACLE ledger before its forward performance is evaluated.
2. No deleting losing observations.
3. V1 scoring/thresholds are frozen before forward evaluation.
4. Results must report QQQ matched-date benchmark, fees/slippage/FX when available.
5. Historical backcasts are diagnostics only and never count as prospective evidence.

## States
DISCOVERED → WATCH → ARMED → POWER → HOLD/RUN → EXIT.

## V1 scores
- Structural: economic proof + role (bottleneck/pick-and-shovel preferred).
- Early Bird: whether a timestamped first observation exists.
- Ignition: relative strength vs QQQ + trend breadth + trend momentum.
- POWER score combines all three; it is **not** a probability of profit.

The system must not publish P(+10%) until a statistically meaningful forward sample exists.

Run: `python power10.py`
Output: `data/power10.json`.
