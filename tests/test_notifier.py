"""Tests for the webhook notifier (bonus feature)."""

from __future__ import annotations

import httpx

from app.models.schemas import Decision, LogEntry, RejectionCategory
from app.services.notifier import WebhookNotifier


def _flagged_entry() -> LogEntry:
    return LogEntry(
        user_id="u1",
        comment="borderline comment",
        decision=Decision.FLAGGED_FOR_REVIEW,
        confidence=0.5,
        reasoning="needs a human",
        category=RejectionCategory.HARASSMENT,
    )


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


def test_disabled_notifier_is_noop():
    notifier = WebhookNotifier(webhook_url="")
    assert notifier.enabled is False
    # Should be safe to call and must not raise or attempt any HTTP.
    notifier.notify_flagged(_flagged_entry())


def test_notifier_posts_expected_payload(monkeypatch):
    captured: dict = {}

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("app.services.notifier.httpx.post", fake_post)

    notifier = WebhookNotifier(webhook_url="https://hooks.example.com/x")
    notifier.notify_flagged(_flagged_entry())

    assert captured["url"] == "https://hooks.example.com/x"
    assert captured["json"]["event"] == "comment.flagged_for_review"
    assert captured["json"]["category"] == "harassment"
    assert captured["json"]["comment"] == "borderline comment"


def test_notifier_swallows_http_errors(monkeypatch):
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.services.notifier.httpx.post", fake_post)

    notifier = WebhookNotifier(webhook_url="https://hooks.example.com/x")
    # Delivery is best-effort: a failing webhook must not raise.
    notifier.notify_flagged(_flagged_entry())
