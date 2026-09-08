from datetime import datetime, timezone, timedelta
from analytics.oracle_v6_pit_access import PITFeature, assert_no_lookahead


def feature(minutes: int) -> PITFeature:
    t = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return PITFeature('TEST', str(minutes), None, None, None, t, t, None, {})


def test_no_lookahead_passes_for_available_features():
    decision = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    assert_no_lookahead([feature(1), feature(30), feature(60)], decision)


def test_no_lookahead_rejects_future_feature():
    decision = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    try:
        assert_no_lookahead([feature(61)], decision)
    except AssertionError:
        return
    raise AssertionError('future feature was not rejected')
