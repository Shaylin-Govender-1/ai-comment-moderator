"""Pydantic models: enums, request bodies, responses, and the log entry.

These models are the single source of truth for input validation. FastAPI uses
them to reject malformed requests with a 422 *before* any business logic or LLM
call runs, which is how most edge cases (empty / whitespace / over-long input)
are handled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.config import get_settings


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class Decision(str, Enum):
    """Possible moderation outcomes for a freshly submitted comment."""

    APPROVED = "approved"
    REJECTED = "rejected"
    FLAGGED_FOR_REVIEW = "flagged_for_review"


class FinalDecision(str, Enum):
    """Outcome of an appeal. Appeals can only ever approve or reject."""

    APPROVED = "approved"
    REJECTED = "rejected"


class RejectionCategory(str, Enum):
    """Reason category for a rejected/flagged comment (bonus feature).

    ``NONE`` is used for approved comments where no category applies.
    """

    SPAM = "spam"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    MISINFORMATION = "misinformation"
    ILLEGAL_ACTIVITY = "illegal_activity"
    ADULT_CONTENT = "adult_content"
    PERSONAL_INFORMATION = "personal_information"
    OFF_TOPIC = "off_topic"
    OTHER = "other"
    NONE = "none"


# --------------------------------------------------------------------------- #
# Shared validation
# --------------------------------------------------------------------------- #
def _validate_text(value: str, field_name: str) -> str:
    """Trim and ensure the text is non-empty and within the configured limit."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty or whitespace only.")
    max_len = get_settings().max_comment_length
    if len(cleaned) > max_len:
        raise ValueError(
            f"{field_name} exceeds the maximum length of {max_len} characters "
            f"(got {len(cleaned)})."
        )
    return cleaned


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class ModerationRequest(BaseModel):
    """Body for ``POST /moderate``."""

    comment: str = Field(..., description="The user-submitted comment to moderate.")
    user_id: str = Field(
        default="anonymous",
        max_length=200,
        description="Identifier for the submitting user (used for rate limiting).",
    )

    @field_validator("comment")
    @classmethod
    def _check_comment(cls, v: str) -> str:
        return _validate_text(v, "comment")

    @field_validator("user_id")
    @classmethod
    def _check_user_id(cls, v: str) -> str:
        return v.strip() or "anonymous"


class AppealRequest(BaseModel):
    """Body for ``POST /appeal``."""

    comment_id: str = Field(..., description="ID of the previously rejected comment.")
    appeal_context: str = Field(
        ...,
        description="Additional context explaining why the comment should be reconsidered.",
    )

    @field_validator("appeal_context")
    @classmethod
    def _check_context(cls, v: str) -> str:
        return _validate_text(v, "appeal_context")


# --------------------------------------------------------------------------- #
# LLM result (internal, returned by the moderator service)
# --------------------------------------------------------------------------- #
class ModerationResult(BaseModel):
    """Normalised result coming back from the LLM moderator."""

    decision: Decision
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    category: RejectionCategory = RejectionCategory.NONE


class AppealResult(BaseModel):
    """Normalised result of an appeal re-evaluation."""

    decision: FinalDecision
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str
    category: RejectionCategory = RejectionCategory.NONE


# --------------------------------------------------------------------------- #
# Log entry + responses
# --------------------------------------------------------------------------- #
class LogEntry(BaseModel):
    """A single moderation record, persisted to the log."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    comment: str

    decision: Decision
    confidence: float
    reasoning: str
    category: RejectionCategory = RejectionCategory.NONE
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    # Appeal-related fields (populated only if an appeal is made).
    appealed: bool = False
    appeal_context: str | None = None
    final_decision: FinalDecision | None = None
    final_reasoning: str | None = None
    appeal_confidence: float | None = None
    appeal_category: RejectionCategory | None = None
    appeal_timestamp: str | None = None


class ModerationResponse(BaseModel):
    """Response for ``POST /moderate``."""

    comment_id: str
    decision: Decision
    confidence: float
    reasoning: str
    category: RejectionCategory
    timestamp: str
    appealable: bool = Field(
        description="Whether this decision can be appealed (true only when rejected)."
    )


class AppealResponse(BaseModel):
    """Response for ``POST /appeal``."""

    comment_id: str
    final_decision: FinalDecision
    confidence: float
    reasoning: str
    category: RejectionCategory
    appeal_timestamp: str


class LogResponse(BaseModel):
    """Response for ``GET /log``."""

    count: int
    entries: list[LogEntry]
