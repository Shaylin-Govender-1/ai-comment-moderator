"""Tests for GET /log."""

from __future__ import annotations

from app.models.schemas import Decision, ModerationResult, RejectionCategory


def test_empty_log(api):
    resp = api.client.get("/log")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["entries"] == []


def test_log_contains_required_fields(api):
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.REJECTED,
        confidence=0.91,
        reasoning="Spam.",
        category=RejectionCategory.SPAM,
    )
    api.client.post("/moderate", json={"comment": "buy my course", "user_id": "u9"})

    entry = api.client.get("/log").json()["entries"][0]
    for field in ("comment", "decision", "confidence", "reasoning", "timestamp", "appealed"):
        assert field in entry
    assert entry["decision"] == "rejected"
    assert entry["appealed"] is False


def test_log_reflects_appeal(api):
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.REJECTED, confidence=0.8, reasoning="Spam.", category=RejectionCategory.SPAM
    )
    cid = api.client.post("/moderate", json={"comment": "x", "user_id": "u1"}).json()["comment_id"]
    api.client.post("/appeal", json={"comment_id": cid, "appeal_context": "reconsider please"})

    entry = api.client.get("/log").json()["entries"][0]
    assert entry["appealed"] is True
    assert entry["final_decision"] == "approved"


def test_log_is_newest_first(api):
    for i in range(3):
        api.client.post("/moderate", json={"comment": f"comment {i}", "user_id": "u1"})
    entries = api.client.get("/log").json()["entries"]
    timestamps = [e["timestamp"] for e in entries]
    assert timestamps == sorted(timestamps, reverse=True)
