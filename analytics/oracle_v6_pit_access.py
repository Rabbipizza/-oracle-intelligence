#!/usr/bin/env python3
"""Central point-in-time feature access for ORACLE V6 backtests.

All V6 historical feature reads go through the database PIT gateway. Source type
is mandatory so a request cannot accidentally scan every historical source.
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


def get_features_as_of(
    connection,
    decision_time: datetime,
    source_type: str,
    entity_key: str | None = None,
    after_available_at: datetime | None = None,
    after_source_id: str | None = None,
    limit: int = 1000,
) -> list[PITFeature]:
    """Return one keyset-paginated PIT page available by ``decision_time``.

    ``source_type`` is mandatory by design. The database gateway routes heavy
    sources such as RAW_DOCUMENT and STRUCTURAL_SIGNAL directly to their indexed
    tables, while smaller/vintage sources come from oracle_v6_pit_observations.
    """
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    if not source_type or not source_type.strip():
        raise ValueError("source_type is required")
    if not 1 <= limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if after_available_at is not None and after_available_at.tzinfo is None:
        raise ValueError("after_available_at must be timezone-aware")

    sql = """
        select source_type, source_id, entity_key, event_date, published_at,
               available_at, ingested_at, vintage_id, metadata
        from public.get_features_as_of_v2(%s, %s, %s, %s, %s, %s)
        order by available_at, source_id
    """
    with connection.cursor() as cur:
        cur.execute(
            sql,
            (
                decision_time,
                source_type,
                entity_key,
                after_available_at,
                after_source_id,
                limit,
            ),
        )
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


def iter_features_as_of(
    connection,
    decision_time: datetime,
    source_type: str,
    entity_key: str | None = None,
    page_size: int = 1000,
) -> Iterable[PITFeature]:
    """Stream all PIT features using keyset pagination, never OFFSET scans."""
    after_time = None
    after_id = None
    while True:
        page = get_features_as_of(
            connection,
            decision_time,
            source_type,
            entity_key,
            after_time,
            after_id,
            page_size,
        )
        if not page:
            return
        for feature in page:
            yield feature
        last = page[-1]
        after_time = last.available_at
        after_id = last.source_id
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


__all__ = [
    "PITFeature",
    "get_features_as_of",
    "iter_features_as_of",
    "assert_no_lookahead",
]
