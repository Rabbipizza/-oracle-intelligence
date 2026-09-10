#!/usr/bin/env python3
"""Central point-in-time feature access for ORACLE V6.

P0-9 dual-clock contract:
- mode='live' uses the time the datum was actually available to ORACLE.
- mode='simulated_historical' uses source-world availability for rolling backtests.

Derived historical signals are never relabelled: the database gateway rejects
STRUCTURAL_SIGNAL reads in simulated mode so they must be reconstructed at T.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

VALID_MODES = {"live", "simulated_historical"}


@dataclass(frozen=True)
class PITFeature:
    source_type: str
    source_id: str
    entity_key: str | None
    event_date: datetime | None
    published_at: datetime | None
    available_at: datetime
    ingested_at: datetime
    vintage_id: str | None
    metadata: dict[str, Any]


def get_features_as_of(
    connection,
    decision_time: datetime,
    source_type: str,
    entity_key: str | None = None,
    after_available_at: datetime | None = None,
    after_source_id: str | None = None,
    limit: int = 1000,
    mode: str = "live",
) -> list[PITFeature]:
    """Return a PIT page under one explicit clock.

    Rolling historical backtests MUST pass mode='simulated_historical'. The
    default remains live to preserve production behavior.
    """
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    if mode not in VALID_MODES:
        raise ValueError("mode must be 'live' or 'simulated_historical'")
    if not source_type or not source_type.strip():
        raise ValueError("source_type is required")
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if after_available_at is not None and after_available_at.tzinfo is None:
        raise ValueError("after_available_at must be timezone-aware")

    sql = """
        select source_type, source_id, entity_key, event_date, published_at,
               available_at, ingested_at, vintage_id, metadata
        from public.get_features_as_of_v3(%s, %s, %s, %s, %s, %s, %s)
        order by available_at, source_id
    """
    with connection.cursor() as cur:
        cur.execute(sql, (decision_time, mode, source_type, entity_key,
                          after_available_at, after_source_id, limit))
        rows = cur.fetchall()

    out: list[PITFeature] = []
    for row in rows:
        feature = PITFeature(*row)
        if feature.available_at > decision_time:
            raise RuntimeError(
                f"PIT violation[{mode}]: {feature.source_type}/{feature.source_id} "
                f"available_at={feature.available_at.isoformat()} > "
                f"decision_time={decision_time.isoformat()}"
            )
        out.append(feature)
    return out


def iter_features_as_of(
    connection,
    decision_time: datetime,
    source_type: str,
    entity_key: str | None = None,
    page_size: int = 1000,
    mode: str = "live",
) -> Iterable[PITFeature]:
    """Stream PIT features using keyset pagination under the selected clock."""
    after_time = None
    after_id = None
    while True:
        page = get_features_as_of(
            connection, decision_time, source_type, entity_key,
            after_time, after_id, page_size, mode,
        )
        if not page:
            return
        yield from page
        last = page[-1]
        after_time, after_id = last.available_at, last.source_id
        if len(page) < page_size:
            return


def assert_no_lookahead(features: Iterable[PITFeature], decision_time: datetime) -> None:
    offenders = [f for f in features if f.available_at > decision_time]
    if offenders:
        sample = offenders[0]
        raise AssertionError(
            f"look-ahead detected: {sample.source_type}/{sample.source_id} "
            f"available_at={sample.available_at.isoformat()} > {decision_time.isoformat()}"
        )


__all__ = ["PITFeature", "get_features_as_of", "iter_features_as_of", "assert_no_lookahead"]
