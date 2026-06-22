"""Tests for POST /moderate."""

from __future__ import annotations

from app.models.schemas import Decision, ModerationResult, RejectionCategory


def test_approved_comment(api):
    resp = api.client.post(
        "/moderate",
        json={"comment": "Any advice on switching to a limited company structure?", "user_id": "u1"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "approved"
    assert body["category"] == "none"
    assert body["appealable"] is False
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["comment_id"]
    assert body["reasoning"]


def test_rejected_comment_is_appealable_with_category(api):
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.REJECTED,
        confidence=0.97,
        reasoning="Get-rich-quick self promotion.",
        category=RejectionCategory.SPAM,
    )
    resp = api.client.post(
        "/moderate", json={"comment": "DM me to make £10k/month!", "user_id": "u1"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "rejected"
    assert body["category"] == "spam"
    assert body["appealable"] is True


def test_flagged_comment_triggers_notification(api):
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.FLAGGED_FOR_REVIEW,
        confidence=0.5,
        reasoning="Borderline insult toward another member.",
        category=RejectionCategory.HARASSMENT,
    )
    resp = api.client.post(
        "/moderate", json={"comment": "you clearly know nothing", "user_id": "u1"}
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "flagged_for_review"
    # Background task should have fired the webhook notifier exactly once.
    assert len(api.notifier.flagged) == 1
    assert api.notifier.flagged[0].decision == Decision.FLAGGED_FOR_REVIEW


def test_approved_comment_does_not_notify(api):
    api.client.post("/moderate", json={"comment": "Great thread, thanks!", "user_id": "u1"})
    assert api.notifier.flagged == []


def test_moderation_is_logged(api):
    api.client.post("/moderate", json={"comment": "Hello forum", "user_id": "u42"})
    entries = api.store.all_entries()
    assert len(entries) == 1
    assert entries[0].user_id == "u42"
    assert entries[0].comment == "Hello forum"


def test_user_id_defaults_to_anonymous(api):
    resp = api.client.post("/moderate", json={"comment": "No user id provided"})
    assert resp.status_code == 200
    assert api.store.all_entries()[0].user_id == "anonymous"
