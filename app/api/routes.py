"""HTTP routes: /moderate, /appeal, /log.

Endpoints are defined as ``def`` (not ``async def``) so FastAPI runs them in its
worker threadpool. That keeps the blocking Anthropic SDK call off the event loop
while still giving us dependency injection and background tasks.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.errors import CommentNotFoundError
from app.core.rate_limit import RateLimiter
from app.dependencies import (
    get_moderator,
    get_notifier,
    get_rate_limiter,
    get_store,
)
from app.models.schemas import (
    AppealRequest,
    AppealResponse,
    Decision,
    LogResponse,
    ModerationRequest,
    ModerationResponse,
)
from app.services.moderator import LLMModerator
from app.services.notifier import WebhookNotifier
from app.services.store import ModerationStore

router = APIRouter()


@router.post("/moderate", response_model=ModerationResponse, tags=["moderation"])
def moderate(
    body: ModerationRequest,
    background: BackgroundTasks,
    store: ModerationStore = Depends(get_store),
    moderator: LLMModerator = Depends(get_moderator),
    notifier: WebhookNotifier = Depends(get_notifier),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> ModerationResponse:
    """Submit a comment for AI moderation."""
    limiter.check(body.user_id)

    result = moderator.moderate(body.comment)
    entry = store.add_moderation(
        user_id=body.user_id, comment=body.comment, result=result
    )

    # Bonus: notify on flagged content (best-effort, off the request path).
    if entry.decision == Decision.FLAGGED_FOR_REVIEW:
        background.add_task(notifier.notify_flagged, entry)

    return ModerationResponse(
        comment_id=entry.id,
        decision=entry.decision,
        confidence=entry.confidence,
        reasoning=entry.reasoning,
        category=entry.category,
        timestamp=entry.timestamp,
        appealable=entry.decision == Decision.REJECTED,
    )


@router.post("/appeal", response_model=AppealResponse, tags=["moderation"])
def appeal(
    body: AppealRequest,
    store: ModerationStore = Depends(get_store),
    moderator: LLMModerator = Depends(get_moderator),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> AppealResponse:
    """Appeal a rejected comment with additional context for a final decision."""
    # We need the user_id for rate limiting, so peek first (cheap, friendly 404).
    entry = store.get(body.comment_id)
    if entry is None:
        raise CommentNotFoundError(f"No comment found with id '{body.comment_id}'.")

    limiter.check(entry.user_id)

    # Atomically validate (rejected, not yet appealed) and reserve the comment.
    # This is the single source of truth for appeal eligibility, and holding the
    # lock across check-and-mark means two appeals racing for the same comment
    # can't both proceed — exactly one wins and the other gets a 409.
    claimed = store.claim_for_appeal(body.comment_id)

    result = moderator.reconsider(
        comment=claimed.comment,
        original_reasoning=claimed.reasoning,
        appeal_context=body.appeal_context,
    )
    updated = store.add_appeal(
        comment_id=body.comment_id,
        appeal_context=body.appeal_context,
        result=result,
    )

    return AppealResponse(
        comment_id=updated.id,
        final_decision=updated.final_decision,
        confidence=updated.appeal_confidence,
        reasoning=updated.final_reasoning,
        category=updated.appeal_category,
        appeal_timestamp=updated.appeal_timestamp,
    )


@router.get("/log", response_model=LogResponse, tags=["moderation"])
def get_log(store: ModerationStore = Depends(get_store)) -> LogResponse:
    """Retrieve the full moderation log, newest first."""
    entries = store.all_entries()
    return LogResponse(count=len(entries), entries=entries)
