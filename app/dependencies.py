"""FastAPI dependency providers.

Each provider reads a singleton off ``app.state`` (wired up in the lifespan in
``app.main``). Routing through dependencies means tests can swap any collaborator
— most importantly the LLM moderator — via ``app.dependency_overrides`` without
patching internals or making network calls.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.rate_limit import RateLimiter
from app.services.moderator import LLMModerator
from app.services.notifier import WebhookNotifier
from app.services.store import ModerationStore


def get_store(request: Request) -> ModerationStore:
    return request.app.state.store


def get_notifier(request: Request) -> WebhookNotifier:
    return request.app.state.notifier


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_moderator(request: Request) -> LLMModerator:
    moderator = request.app.state.moderator
    if moderator is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Moderation is unavailable because ANTHROPIC_API_KEY is not "
                "configured. Set it in your environment or .env file."
            ),
        )
    return moderator
