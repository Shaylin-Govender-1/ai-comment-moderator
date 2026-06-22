"""Shared test fixtures.

The whole suite runs offline: the real `LLMModerator` is replaced via FastAPI's
dependency overrides with `FakeModerator`, whose responses each test programs
directly. No API key, no network, fully deterministic.
"""

from __future__ import annotations

import os

# Ensure the lifespan-created store never touches the filesystem and the real
# moderator is not built. Set before any Settings are instantiated. The HTTP
# tests use overridden dependencies regardless, so these only neutralise the
# unused app.state singletons created in the lifespan.
os.environ["LOG_FILE"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""

from dataclasses import dataclass, field  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import RateLimiter  # noqa: E402
from app.dependencies import (  # noqa: E402
    get_moderator,
    get_notifier,
    get_rate_limiter,
    get_store,
)
from app.main import create_app  # noqa: E402
from app.models.schemas import (  # noqa: E402
    AppealResult,
    Decision,
    FinalDecision,
    ModerationResult,
    RejectionCategory,
)
from app.services.notifier import WebhookNotifier  # noqa: E402
from app.services.store import ModerationStore  # noqa: E402


class FakeModerator:
    """Stand-in for `LLMModerator` with programmable, recorded responses."""

    def __init__(self) -> None:
        self.next_moderation = ModerationResult(
            decision=Decision.APPROVED,
            confidence=0.95,
            reasoning="Looks like genuine on-topic discussion.",
            category=RejectionCategory.NONE,
        )
        self.next_appeal = AppealResult(
            decision=FinalDecision.APPROVED,
            confidence=0.9,
            reasoning="The appeal context clarifies the intent; overturning.",
            category=RejectionCategory.NONE,
        )
        self.moderate_calls: list[str] = []
        self.reconsider_calls: list[dict] = []

    def moderate(self, comment: str) -> ModerationResult:
        self.moderate_calls.append(comment)
        return self.next_moderation

    def reconsider(
        self, comment: str, original_reasoning: str, appeal_context: str
    ) -> AppealResult:
        self.reconsider_calls.append(
            {
                "comment": comment,
                "original_reasoning": original_reasoning,
                "appeal_context": appeal_context,
            }
        )
        return self.next_appeal


class RecordingNotifier(WebhookNotifier):
    """Notifier that records flagged entries instead of making HTTP calls."""

    def __init__(self) -> None:
        super().__init__(webhook_url="")
        self.flagged: list = []

    def notify_flagged(self, entry) -> None:  # type: ignore[override]
        self.flagged.append(entry)


@dataclass
class Harness:
    """Bundle of a TestClient with the collaborators it was wired with."""

    client: TestClient
    moderator: FakeModerator
    store: ModerationStore
    notifier: RecordingNotifier
    rate_limiter: RateLimiter
    _exit_stack: list = field(default_factory=list)


@pytest.fixture
def make_api():
    """Factory that builds an API harness with optional custom collaborators."""
    harnesses: list[Harness] = []

    def _make(
        moderator: FakeModerator | None = None,
        store: ModerationStore | None = None,
        notifier: RecordingNotifier | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> Harness:
        moderator = moderator or FakeModerator()
        store = store or ModerationStore(log_file=None)
        notifier = notifier or RecordingNotifier()
        # Rate limiting off by default so unrelated tests aren't throttled.
        rate_limiter = rate_limiter or RateLimiter("1000/minute", enabled=False)

        app = create_app()
        app.dependency_overrides[get_moderator] = lambda: moderator
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_notifier] = lambda: notifier
        app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter

        client = TestClient(app)
        client.__enter__()
        harness = Harness(client, moderator, store, notifier, rate_limiter)
        harnesses.append(harness)
        return harness

    yield _make

    for h in harnesses:
        h.client.__exit__(None, None, None)


@pytest.fixture
def api(make_api) -> Harness:
    """A ready-to-use API harness with default (approve) behaviour."""
    return make_api()
