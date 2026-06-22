"""Tests for POST /appeal."""

from __future__ import annotations

from app.models.schemas import (
    AppealResult,
    Decision,
    FinalDecision,
    ModerationResult,
    RejectionCategory,
)


def _submit_rejected(api, comment="borderline comment", user_id="u1") -> str:
    """Submit a comment that gets rejected and return its id."""
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.REJECTED,
        confidence=0.8,
        reasoning="Looked like spam.",
        category=RejectionCategory.SPAM,
    )
    resp = api.client.post("/moderate", json={"comment": comment, "user_id": user_id})
    return resp.json()["comment_id"]


def test_appeal_can_overturn_rejection(api):
    comment_id = _submit_rejected(api)
    api.moderator.next_appeal = AppealResult(
        decision=FinalDecision.APPROVED,
        confidence=0.86,
        reasoning="The appeal shows this was a genuine question, not spam; overturning.",
        category=RejectionCategory.NONE,
    )
    resp = api.client.post(
        "/appeal",
        json={"comment_id": comment_id, "appeal_context": "I was genuinely asking, not selling."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_decision"] == "approved"
    assert body["reasoning"]


def test_appeal_passes_original_comment_and_context_to_model(api):
    comment_id = _submit_rejected(api, comment="my original comment text")
    api.client.post(
        "/appeal",
        json={"comment_id": comment_id, "appeal_context": "here is my extra context"},
    )
    assert len(api.moderator.reconsider_calls) == 1
    call = api.moderator.reconsider_calls[0]
    # The appeal genuinely feeds both the original comment and the new context.
    assert call["comment"] == "my original comment text"
    assert call["appeal_context"] == "here is my extra context"
    assert call["original_reasoning"] == "Looked like spam."


def test_appeal_outcome_recorded_in_log(api):
    comment_id = _submit_rejected(api)
    api.client.post(
        "/appeal", json={"comment_id": comment_id, "appeal_context": "please reconsider"}
    )
    entry = api.store.get(comment_id)
    assert entry.appealed is True
    assert entry.appeal_context == "please reconsider"
    assert entry.final_decision == FinalDecision.APPROVED
    assert entry.appeal_timestamp is not None


def test_appeal_unknown_comment_returns_404(api):
    resp = api.client.post(
        "/appeal", json={"comment_id": "does-not-exist", "appeal_context": "context"}
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "comment_not_found"


def test_cannot_appeal_approved_comment(api):
    # Default behaviour approves.
    resp = api.client.post("/moderate", json={"comment": "totally fine", "user_id": "u1"})
    comment_id = resp.json()["comment_id"]
    resp = api.client.post(
        "/appeal", json={"comment_id": comment_id, "appeal_context": "context"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_appealable"


def test_no_second_appeal_allowed(api):
    comment_id = _submit_rejected(api)
    first = api.client.post(
        "/appeal", json={"comment_id": comment_id, "appeal_context": "first appeal"}
    )
    assert first.status_code == 200
    second = api.client.post(
        "/appeal", json={"comment_id": comment_id, "appeal_context": "second appeal"}
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "already_appealed"


def test_appeal_can_uphold_rejection(api):
    comment_id = _submit_rejected(api)
    api.moderator.next_appeal = AppealResult(
        decision=FinalDecision.REJECTED,
        confidence=0.9,
        reasoning="The appeal does not address why this was spam; rejection stands.",
        category=RejectionCategory.SPAM,
    )
    resp = api.client.post(
        "/appeal", json={"comment_id": comment_id, "appeal_context": "but I really want it up"}
    )
    assert resp.status_code == 200
    assert resp.json()["final_decision"] == "rejected"
    assert resp.json()["category"] == "spam"


def test_cannot_appeal_flagged_comment(api):
    api.moderator.next_moderation = ModerationResult(
        decision=Decision.FLAGGED_FOR_REVIEW,
        confidence=0.5,
        reasoning="Borderline.",
        category=RejectionCategory.HARASSMENT,
    )
    cid = api.client.post("/moderate", json={"comment": "hmm", "user_id": "u1"}).json()["comment_id"]
    resp = api.client.post("/appeal", json={"comment_id": cid, "appeal_context": "please"})
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "not_appealable"


def test_appeal_context_is_trimmed(api):
    cid = _submit_rejected(api)
    api.client.post(
        "/appeal", json={"comment_id": cid, "appeal_context": "   padded context   "}
    )
    # Trimmed both where it's sent to the model and where it's stored.
    assert api.moderator.reconsider_calls[0]["appeal_context"] == "padded context"
    assert api.store.get(cid).appeal_context == "padded context"
