"""Tests for /health and the no-API-key behaviour of the moderation endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint(api):
    resp = api.client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["model"]
    assert "llm_configured" in body
    assert "rate_limit_enabled" in body


def test_moderate_returns_503_when_llm_not_configured():
    # No dependency overrides: with no ANTHROPIC_API_KEY in the test environment
    # (set in conftest), app.state.moderator is None and the endpoint should 503.
    with TestClient(create_app()) as client:
        resp = client.post("/moderate", json={"comment": "hello", "user_id": "u1"})
    assert resp.status_code == 503


def test_appeal_returns_503_when_llm_not_configured():
    with TestClient(create_app()) as client:
        resp = client.post(
            "/appeal", json={"comment_id": "x", "appeal_context": "context"}
        )
    assert resp.status_code == 503
