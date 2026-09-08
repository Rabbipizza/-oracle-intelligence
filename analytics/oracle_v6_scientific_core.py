#!/usr/bin/env python3
"""Scientific primitives for ORACLE V6.

This module is intentionally deterministic and side-effect free. It does not
replace legacy V5 workers yet; it provides the statistically testable building
blocks used to run V6 in parallel.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, log, sqrt
from typing import Iterable, Sequence


EPS = 1e-12


@dataclass(frozen=True)
class CountSurprise:
    observed: int
    expected: float
    z_score: float
    upper_tail_approx: float
    model: str = "POISSON_BASELINE"


@dataclass(frozen=True)
class BottleneckInputs:
    demand_growth: float
    utilization: float
    inverse_inventory: float
    lead_time: float
    concentration: float
    geo_risk: float
    substitution: float
    capacity_pipeline: float


@dataclass(frozen=True)
class ReverseDCFInputs:
    market_cap: float
    net_debt: float
    current_revenue: float
    current_fcf_margin: float
    terminal_growth: float
    discount_rate: float
    forecast_years: int = 5


def _normal_upper_tail(z: float) -> float:
    """Fast normal-tail approximation, sufficient for ranking diagnostics."""
    # Abramowitz-Stegun style logistic approximation. For formal p-values use scipy.
    return 1.0 / (1.0 + exp(1.702 * z))


def poisson_count_surprise(observed: int, expected: float) -> CountSurprise:
    """Explicit null-model surprise for event counts.

    Poisson variance equals lambda. If over-dispersion is empirically present,
    production code should switch the registered null family to a negative-
    binomial model and estimate dispersion on the training window only.
    """
    if observed < 0:
        raise ValueError("observed must be non-negative")
    if expected <= 0:
        raise ValueError("expected must be > 0")
    z = (observed - expected) / sqrt(expected)
    return CountSurprise(
        observed=observed,
        expected=expected,
        z_score=z,
        upper_tail_approx=_normal_upper_tail(z),
    )


def sigmoid(x: float) -> float:
    if x >= 0:
        e = exp(-x)
        return 1.0 / (1.0 + e)
    e = exp(x)
    return e / (1.0 + e)


def bottleneck_probability(
    x: BottleneckInputs,
    intercept: float,
    coefficients: Sequence[float],
) -> float:
    """Calibratable bottleneck probability.

    Coefficients MUST come from a training procedure; they are never meant to be
    hard-coded expert weights. The function exists to make that constraint
    explicit in the architecture.
    """
    features = (
        x.demand_growth,
        x.utilization,
        x.inverse_inventory,
        x.lead_time,
        x.concentration,
        x.geo_risk,
        x.substitution,
        x.capacity_pipeline,
    )
    if len(coefficients) != len(features):
        raise ValueError("expected 8 fitted coefficients")
    eta = intercept + sum(b * v for b, v in zip(coefficients, features))
    return sigmoid(eta)


def brier_score(probabilities: Iterable[float], outcomes: Iterable[int]) -> float:
    ps = list(probabilities)
    ys = list(outcomes)
    if len(ps) != len(ys) or not ps:
        raise ValueError("probabilities and outcomes must be non-empty and aligned")
    err = 0.0
    for p, y in zip(ps, ys):
        if not 0.0 <= p <= 1.0:
            raise ValueError("probabilities must be in [0,1]")
        if y not in (0, 1):
            raise ValueError("outcomes must be binary")
        err += (p - y) ** 2
    return err / len(ps)


def log_loss(probabilities: Iterable[float], outcomes: Iterable[int]) -> float:
    ps = list(probabilities)
    ys = list(outcomes)
    if len(ps) != len(ys) or not ps:
        raise ValueError("probabilities and outcomes must be non-empty and aligned")
    total = 0.0
    for p, y in zip(ps, ys):
        p = min(1.0 - EPS, max(EPS, p))
        total += -(y * log(p) + (1 - y) * log(1 - p))
    return total / len(ps)


def factor_adjusted_return(realized_return: float, expected_factor_return: float) -> float:
    """Primary market target Y(i,t,h). Returns are in decimal units."""
    return realized_return - expected_factor_return


def incremental_model_value(
    baseline_losses: Sequence[float],
    oracle_losses: Sequence[float],
) -> float:
    """Positive means BASELINE+ORACLE improves average loss vs BASELINE."""
    if len(baseline_losses) != len(oracle_losses) or not baseline_losses:
        raise ValueError("loss arrays must be non-empty and aligned")
    return sum(b - o for b, o in zip(baseline_losses, oracle_losses)) / len(baseline_losses)


def reverse_dcf_implied_revenue_growth(
    inputs: ReverseDCFInputs,
    lower: float = -0.50,
    upper: float = 1.50,
    iterations: int = 100,
) -> float:
    """Solve a deliberately simple reverse DCF for constant implied revenue growth.

    Assumptions are explicit: constant FCF margin over the forecast period,
    constant revenue growth, terminal Gordon growth. Production use should run
    a distribution over margins, WACC and terminal growth rather than pretend
    this point estimate is precise.
    """
    if inputs.market_cap <= 0 or inputs.current_revenue <= 0:
        raise ValueError("market_cap and current_revenue must be > 0")
    if inputs.discount_rate <= inputs.terminal_growth:
        raise ValueError("discount_rate must exceed terminal_growth")
    enterprise_value = inputs.market_cap + inputs.net_debt

    def pv_for_growth(g: float) -> float:
        revenue = inputs.current_revenue
        pv = 0.0
        for year in range(1, inputs.forecast_years + 1):
            revenue *= (1.0 + g)
            fcf = revenue * inputs.current_fcf_margin
            pv += fcf / ((1.0 + inputs.discount_rate) ** year)
        terminal_fcf = revenue * (1.0 + inputs.terminal_growth) * inputs.current_fcf_margin
        terminal_value = terminal_fcf / (inputs.discount_rate - inputs.terminal_growth)
        pv += terminal_value / ((1.0 + inputs.discount_rate) ** inputs.forecast_years)
        return pv

    lo, hi = lower, upper
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        if pv_for_growth(mid) < enterprise_value:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def expectation_gap_probability(
    fundamental_draws: Sequence[float],
    market_implied_draws: Sequence[float],
) -> float:
    """Empirical P(Fundamental > Market Implied) from paired or cross draws."""
    if not fundamental_draws or not market_implied_draws:
        raise ValueError("draw arrays must be non-empty")
    wins = 0
    total = 0
    for f in fundamental_draws:
        for m in market_implied_draws:
            total += 1
            wins += int(f > m)
    return wins / total


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> list[bool]:
    """FDR control for the many hypotheses ORACLE evaluates continuously."""
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    cutoff_rank = 0
    for rank, (_, p) in enumerate(indexed, start=1):
        if not 0 <= p <= 1:
            raise ValueError("p-values must be in [0,1]")
        if p <= alpha * rank / n:
            cutoff_rank = rank
    keep = [False] * n
    if cutoff_rank:
        cutoff = indexed[cutoff_rank - 1][1]
        for idx, p in enumerate(p_values):
            keep[idx] = p <= cutoff
    return keep


__all__ = [
    "CountSurprise",
    "BottleneckInputs",
    "ReverseDCFInputs",
    "poisson_count_surprise",
    "bottleneck_probability",
    "brier_score",
    "log_loss",
    "factor_adjusted_return",
    "incremental_model_value",
    "reverse_dcf_implied_revenue_growth",
    "expectation_gap_probability",
    "benjamini_hochberg",
]
