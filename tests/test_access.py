import io
import unittest
import os
from datetime import date
from unittest.mock import patch
import urllib.error
from oracle_access import (
    AccessBlocked, BoundedFetcher, OversizedPayload,
    access_decision, classify_error, policy_for, source_health_meta, should_poll
)

BASE = {
    "default_policy": {
        "access": "OPEN", "poll_cadence": "DAILY",
        "publication_cadence": "EVENT_DRIVEN", "sampling": "PUBLIC_FEED",
        "max_items": 50, "timeout_seconds": 8,
        "max_payload_bytes": 250000, "max_requests_per_run": 3,
        "required_env": "", "approved": False,
        "rights_review_status": "PENDING_REVIEW",
    },
    "families": {"rss": {"max_items": 10}},
    "sources": {
        "open": {"approved": True},
        "key": {"access": "FREE_KEY", "approved": True, "required_env": "SECRET_TOKEN",
                "auth_header": "X-Api-Key"},
        "limited": {"access": "LIMITED", "approved": True},
        "paid": {"access": "LICENSED", "approved": True},
        "manual": {"access": "MANUAL", "approved": True},
    },
}

def source(key):
    return (key, "Test", "science", "rss", "rss", "https://example.org/rss")

class SourceAccessTests(unittest.TestCase):
    def test_all_active_sources_must_be_registered(self):
        with self.assertRaises(AccessBlocked) as ctx:
            policy_for(source("unknown"), BASE)
        self.assertEqual(ctx.exception.status, "NOT_CONFIGURED")

    def test_open_source_direct_access(self):
        p = policy_for(source("open"), BASE)
        self.assertIsNone(access_decision(p, {}))
        self.assertEqual(p["max_items"], 10)
        self.assertEqual(source_health_meta(p)["sampling"], "PUBLIC_FEED")

    def test_free_key_does_not_leak_or_fake_access(self):
        p = policy_for(source("key"), BASE)
        self.assertEqual(access_decision(p, {}), "AUTH_REQUIRED")
        self.assertIsNone(access_decision(p, {"SECRET_TOKEN": "provided"}))

    def test_free_key_is_passed_only_to_configured_header(self):
        p = policy_for(source("key"), BASE)
        calls = []
        def reader(url, **kwargs):
            calls.append(kwargs)
            return b"ok"
        with patch.dict(os.environ, {"SECRET_TOKEN": "sample-secret"}, clear=False):
            self.assertEqual(BoundedFetcher(p, reader)("https://example.org"), b"ok")
        self.assertEqual(calls[0]["headers"]["X-Api-Key"], "sample-secret")

    def test_weekly_and_monthly_polls_not_misreported(self):
        p = policy_for(source("open"), BASE)
        p["poll_cadence"] = "WEEKLY"
        self.assertTrue(should_poll(p, date(2026, 11, 9)))
        self.assertFalse(should_poll(p, date(2026, 11, 10)))
        p["poll_cadence"] = "MONTHLY"
        self.assertTrue(should_poll(p, date(2026, 12, 1)))
        self.assertFalse(should_poll(p, date(2026, 12, 2)))
        p["poll_cadence"] = "QUARTERLY"
        self.assertTrue(should_poll(p, date(2027, 1, 1)))
        self.assertFalse(should_poll(p, date(2027, 2, 1)))
        p["poll_cadence"] = "ANNUAL"
        self.assertTrue(should_poll(p, date(2027, 1, 1)))
        self.assertFalse(should_poll(p, date(2027, 4, 1)))

    def test_limited_requires_explicit_review(self):
        p = policy_for(source("limited"), BASE)
        self.assertEqual(access_decision(p, {}), "POLICY_REVIEW_REQUIRED")
        p["rights_approved"] = True
        self.assertIsNone(access_decision(p, {}))

    def test_licensed_and_manual_are_blocked(self):
        self.assertEqual(access_decision(policy_for(source("paid"), BASE), {}), "LICENSE_REQUIRED")
        self.assertEqual(access_decision(policy_for(source("manual"), BASE), {}), "MANUAL_ONLY")

    def test_http_error_categorization(self):
        def err(status):
            return urllib.error.HTTPError("https://example.org", status, "denied", {}, io.BytesIO(b""))
        self.assertEqual(classify_error(err(429)), "RATE_LIMITED")
        self.assertEqual(classify_error(err(403)), "FORBIDDEN")
        self.assertEqual(classify_error(err(503)), "TEMPORARY_ERROR")
        self.assertEqual(classify_error(OversizedPayload()), "PAYLOAD_LIMIT")

    def test_per_source_budget(self):
        calls = []
        def reader(url, **kwargs):
            calls.append((url, kwargs))
            return b"data"
        fetch = BoundedFetcher(policy_for(source("open"), BASE), reader)
        for _ in range(3):
            self.assertEqual(fetch("https://example.org"), b"data")
        with self.assertRaises(Exception) as ctx:
            fetch("https://example.org")
        self.assertIn("RequestBudgetExceeded", type(ctx.exception).__name__)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][1]["max_bytes"], 250000)

    def test_unapproved_open_source_is_blocked(self):
        p = policy_for(source("open"), BASE)
        p["approved"] = False
        self.assertEqual(access_decision(p), "NOT_APPROVED")

if __name__ == "__main__":
    unittest.main()
