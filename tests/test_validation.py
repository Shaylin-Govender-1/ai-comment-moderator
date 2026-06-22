"""Edge-case input validation for /moderate and /appeal (handled by Pydantic)."""

from __future__ import annotations

from app.config import get_settings


def test_empty_comment_rejected(api):
    resp = api.client.post("/moderate", json={"comment": "", "user_id": "u1"})
    assert resp.status_code == 422


def test_whitespace_only_comment_rejected(api):
    resp = api.client.post("/moderate", json={"comment": "    \n\t  ", "user_id": "u1"})
    assert resp.status_code == 422


def test_missing_comment_field_rejected(api):
    resp = api.client.post("/moderate", json={"user_id": "u1"})
    assert resp.status_code == 422


def test_over_long_comment_rejected(api):
    too_long = "a" * (get_settings().max_comment_length + 1)
    resp = api.client.post("/moderate", json={"comment": too_long, "user_id": "u1"})
    assert resp.status_code == 422
    # The LLM should never be called for invalid input.
    assert api.moderator.moderate_calls == []


def test_comment_is_trimmed_before_moderation(api):
    api.client.post("/moderate", json={"comment": "   padded comment   ", "user_id": "u1"})
    assert api.moderator.moderate_calls == ["padded comment"]


def test_empty_appeal_context_rejected(api):
    resp = api.client.post(
        "/appeal", json={"comment_id": "whatever", "appeal_context": "   "}
    )
    assert resp.status_code == 422
