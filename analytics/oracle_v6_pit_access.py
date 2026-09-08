#!/usr/bin/env python3
"""Central point-in-time feature access for ORACLE V6 backtests.

Backtest code must use get_features_as_of() instead of querying source tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable


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


def get_features_as_of(connection, decision_time: datetime, source_type: str | None = None, entity_key: str | None = None) -> list[PITFeature]:
    """Return only features available no later than decision_time.

    The database function public.get_features_as_of is the single gateway for
    historical feature reads. This wrapper deliberately does not reference any
    source table directly.
    """
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")

    sql = """
        select source_type, source_id, entity_key, event_date, published_at,
               available_at, ingested_at, vintage_id, metadata
        from public.get_features_as_of(%s, %s, %s)
        order by available_at, id
    """
    with connection.cursor() as cur:
        cur.execute(sql, (decision_time, source_type, entity_key))
        rows = cur.fetchall()

    out: list[PITFeature] = []
    for row in rows:
        feature = PITFeature(*row)
        if feature.available_at > decision_time:
            raise RuntimeError(
                f"PIT violation: {feature.source_type}/{feature.source_id} "
                f"available_at={feature.available_at.isoformat()} > "
                f"decision_time={decision_time.isoformat()}"
            )
        out.append(feature)
    return out


def assert_no_lookahead(features: Iterable[PITFeature], decision_time: datetime) -> None:
    offenders = [f for f in features if f.available_at > decision_time]
    if offenders:
        sample = offenders[0]
        raise AssertionError(
            f"look-ahead detected: {sample.source_type}/{sample.source_id} "
            f"available_at={sample.available_at.isoformat()} > {decision_time.isoformat()}"
        )


__all__ = ["PITFeature", "get_features_as_of", "assert_no_lookahead"]
