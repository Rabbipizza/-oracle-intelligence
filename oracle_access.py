"""Explicit, conservative source-specific access policies for ORACLE.

Each active source must be registered. OPEN only permits a public request;
content reuse and redistribution remain subject to separate rights review.
No scraping, paywall bypass, hidden key, or silent source substitution.
"""
from __future__ import annotations
import json
import os
import socket
from functools import lru_cache
from pathlib import Path
from threading import Lock
from urllib import error as urlerror
from xml.etree import ElementTree as ET

CONFIG_PATH = Path(__file__).resolve().parent / "sources" / "access_profiles.json"
ACCESS_TYPES = frozenset(("OPEN", "FREE_KEY", "LIMITED", "LICENSED", "MANUAL"))
HEALTHY_STATUSES = frozenset(("OK", "EMPTY"))

class AccessBlocked(Exception):
    def __init__(self, status):
        self.status = status
        super().__init__(status)

class RequestBudgetExceeded(Exception):
    pass

class OversizedPayload(Exception):
    pass

@lru_cache(maxsize=1)
def load_profiles():
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported access profile version")
    return data

def policy_for(source, config=None):
    """Fail closed for any source not explicitly registered."""
    source_id, _name, _domain, family, kind, _url = source
    config = config if config is not None else load_profiles()
    explicit = config["sources"].get(source_id)
    if explicit is None:
        raise AccessBlocked("NOT_CONFIGURED")
    policy = dict(config["default_policy"])
    policy.update(config.get("families", {}).get(family, {}))
    policy.update(explicit)
    if policy.get("access") not in ACCESS_TYPES:
        raise AccessBlocked("NOT_CONFIGURED")
    if policy.get("access") == "FREE_KEY" and not policy.get("required_env"):
        raise AccessBlocked("NOT_CONFIGURED")
    for field in ("max_items", "timeout_seconds", "max_payload_bytes", "max_requests_per_run"):
        if not isinstance(policy.get(field), int) or not 1 <= policy[field] <= (5_000_000 if field=="max_payload_bytes" else 1000):
            raise AccessBlocked("NOT_CONFIGURED")
    policy["source_id"] = source_id
    policy["family"] = family
    policy["format"] = kind
    return policy

def access_decision(policy, env=None):
    """Return None only when collection is explicitly permitted."""
    env = os.environ if env is None else env
    if not policy.get("approved", False):
        return "NOT_APPROVED"
    access = policy["access"]
    if access == "LICENSED":
        return "LICENSE_REQUIRED" if not policy.get("license_granted") else None
    if access == "MANUAL":
        return "MANUAL_ONLY"
    if access == "LIMITED" and not policy.get("rights_approved"):
        return "POLICY_REVIEW_REQUIRED"
    secret = policy.get("required_env")
    if access == "FREE_KEY" and not env.get(secret, ""):
        return "AUTH_REQUIRED"
    return None

def classify_error(exc):
    if isinstance(exc, AccessBlocked):
        return exc.status
    if isinstance(exc, RequestBudgetExceeded):
        return "REQUEST_BUDGET_EXCEEDED"
    if isinstance(exc, OversizedPayload):
        return "PAYLOAD_LIMIT"
    if isinstance(exc, urlerror.HTTPError):
        if exc.code == 429:
            return "RATE_LIMITED"
        if exc.code == 401:
            return "AUTH_REQUIRED"
        if exc.code == 403:
            return "FORBIDDEN"
        if exc.code == 404:
            return "SOURCE_NOT_FOUND"
        if exc.code >= 500:
            return "TEMPORARY_ERROR"
        return "HTTP_ERROR"
    if isinstance(exc, (ET.ParseError, json.JSONDecodeError)):
        return "FORMAT_ERROR"
    if isinstance(exc, (urlerror.URLError, TimeoutError, socket.timeout)):
        return "NETWORK_ERROR"
    return "ERROR"

class BoundedFetcher:
    """Per-source HTTP-request budget, thread-safe even for HN item workers."""
    def __init__(self, policy, reader):
        self.policy, self.reader = policy, reader
        self.requests = 0
        self.lock = Lock()

    def __call__(self, url):
        with self.lock:
            if self.requests >= self.policy["max_requests_per_run"]:
                raise RequestBudgetExceeded("Source request budget exceeded")
            self.requests += 1
        return self.reader(
            url,
            timeout=self.policy["timeout_seconds"],
            max_bytes=self.policy["max_payload_bytes"],
        )

def source_health_meta(policy):
    return {"access": policy["access"],
            "poll_cadence": policy["poll_cadence"],
            "publication_cadence": policy["publication_cadence"],
            "sampling": policy["sampling"],
            "rights_review_status": policy["rights_review_status"]}
