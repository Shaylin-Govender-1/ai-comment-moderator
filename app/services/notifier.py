"""Webhook notifications for flagged content (bonus feature).

When a comment is ``flagged_for_review`` and ``WEBHOOK_URL`` is configured, we
POST the log entry to that URL so a downstream system (Slack relay, moderation
dashboard, etc.) can alert a human. Delivery is best-effort and never blocks or
breaks the moderation request: it runs as a FastAPI background task and all
errors are swallowed and logged.
"""

from __future__ import annotations

import logging

import httpx

from app.models.schemas import LogEntry

logger = logging.getLogger(__name__)


class WebhookNotifier:
    """Posts flagged-content notifications to a configured webhook URL."""

    def __init__(self, webhook_url: str = "", timeout: float = 5.0) -> None:
        self._url = webhook_url.strip()
        self._timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self._url)

    def notify_flagged(self, entry: LogEntry) -> None:
        """Send a notification for a flagged entry. Safe to call unconditionally."""
        if not self.enabled:
            logger.info(
                "Comment %s flagged for review (no webhook configured).", entry.id
            )
            return

        payload = {
            "event": "comment.flagged_for_review",
            "comment_id": entry.id,
            "user_id": entry.user_id,
            "comment": entry.comment,
            "confidence": entry.confidence,
            "category": entry.category.value,
            "reasoning": entry.reasoning,
            "timestamp": entry.timestamp,
        }
        try:
            response = httpx.post(self._url, json=payload, timeout=self._timeout)
            response.raise_for_status()
            logger.info("Webhook notification sent for comment %s.", entry.id)
        except httpx.HTTPError as exc:
            logger.error("Webhook notification failed for comment %s: %s", entry.id, exc)
