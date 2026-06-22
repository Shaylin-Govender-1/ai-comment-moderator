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


def test_comment_at_max_length_is_accepted(api):
    text = "a" * get_settings().max_comment_length
    resp = api.client.post("/moderate", json={"comment": text, "user_id": "u1"})
    assert resp.status_code == 200


def test_non_string_comment_rejected(api):
    resp = api.client.post("/moderate", json={"comment": 12345, "user_id": "u1"})
    assert resp.status_code == 422
    assert api.moderator.moderate_calls == []


def test_user_id_too_long_rejected(api):
    resp = api.client.post("/moderate", json={"comment": "hi", "user_id": "u" * 201})
    assert resp.status_code == 422


def test_user_id_is_trimmed(api):
    api.client.post("/moderate", json={"comment": "hi", "user_id": "  bob  "})
    assert api.store.all_entries()[0].user_id == "bob"


def test_blank_user_id_defaults_to_anonymous(api):
    api.client.post("/moderate", json={"comment": "hi", "user_id": "   "})
    assert api.store.all_entries()[0].user_id == "anonymous"


def test_unknown_fields_are_ignored(api):
    resp = api.client.post(
        "/moderate", json={"comment": "hi", "user_id": "u1", "unexpected": "junk"}
    )
    assert resp.status_code == 200


def test_missing_comment_id_in_appeal_rejected(api):
    resp = api.client.post("/appeal", json={"appeal_context": "ctx"})
    assert resp.status_code == 422


def test_missing_appeal_context_rejected(api):
    resp = api.client.post("/appeal", json={"comment_id": "x"})
    assert resp.status_code == 422
