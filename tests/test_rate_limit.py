"""Tests for the per-user rate limiter (bonus feature) — unit and HTTP level."""

from __future__ import annotations

import pytest

from app.core.errors import RateLimitExceededError
from app.core.rate_limit import RateLimiter, parse_rate


# --- unit ---------------------------------------------------------------- #
def test_parse_rate():
    assert parse_rate("10/minute") == (10, 60)
    assert parse_rate("5/second") == (5, 1)
    assert parse_rate("100/hour") == (100, 3600)


def test_parse_rate_invalid():
    with pytest.raises(ValueError):
        parse_rate("nonsense")
    with pytest.raises(ValueError):
        parse_rate("0/minute")


def test_limiter_allows_up_to_limit_then_blocks():
    limiter = RateLimiter("3/minute", enabled=True)
    for _ in range(3):
        limiter.check("user-a")
    with pytest.raises(RateLimitExceededError):
        limiter.check("user-a")


def test_limiter_is_per_key():
    limiter = RateLimiter("1/minute", enabled=True)
    limiter.check("user-a")
    # A different user has their own bucket.
    limiter.check("user-b")
    with pytest.raises(RateLimitExceededError):
        limiter.check("user-a")


def test_disabled_limiter_never_blocks():
    limiter = RateLimiter("1/minute", enabled=False)
    for _ in range(100):
        limiter.check("user-a")


# --- HTTP ---------------------------------------------------------------- #
def test_moderate_returns_429_when_rate_limited(make_api):
    api = make_api(rate_limiter=RateLimiter("2/minute", enabled=True))
    for _ in range(2):
        ok = api.client.post("/moderate", json={"comment": "hello", "user_id": "u1"})
        assert ok.status_code == 200
    blocked = api.client.post("/moderate", json={"comment": "hello again", "user_id": "u1"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limit_exceeded"


def test_rate_limit_is_per_user_over_http(make_api):
    api = make_api(rate_limiter=RateLimiter("1/minute", enabled=True))
    assert api.client.post("/moderate", json={"comment": "a", "user_id": "alice"}).status_code == 200
    # Bob is unaffected by Alice's usage.
    assert api.client.post("/moderate", json={"comment": "b", "user_id": "bob"}).status_code == 200
    # Alice is now over her limit.
    assert api.client.post("/moderate", json={"comment": "c", "user_id": "alice"}).status_code == 429
