"""HTTP routes: /moderate, /appeal, /log.

Endpoints are defined as ``def`` (not ``async def``) so FastAPI runs them in its
worker threadpool. That keeps the blocking Anthropic SDK call off the event loop
while still giving us dependency injection and background tasks.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from app.core.errors import (
    AlreadyAppealedError,
    CommentNotFoundError,
    NotAppealableError,
)
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
    entry = store.get(body.comment_id)
    if entry is None:
        raise CommentNotFoundError(f"No comment found with id '{body.comment_id}'.")
    if entry.decision != Decision.REJECTED:
        raise NotAppealableError(
            f"Only rejected comments can be appealed; this comment was "
            f"'{entry.decision.value}'."
        )
    if entry.appealed:
        raise AlreadyAppealedError(
            "This comment has already been appealed; no further appeals are allowed."
        )

    limiter.check(entry.user_id)

    result = moderator.reconsider(
        comment=entry.comment,
        original_reasoning=entry.reasoning,
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
