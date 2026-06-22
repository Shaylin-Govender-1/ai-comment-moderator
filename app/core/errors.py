"""Domain exceptions and their HTTP representations.

Routes raise these intent-revealing exceptions; handlers registered in
``app.main`` translate them into clean JSON error responses. This keeps HTTP
concerns out of the business logic.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ModeratorError(Exception):
    """Base class for domain errors, carrying an HTTP status and message."""

    status_code: int = 400
    code: str = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class CommentNotFoundError(ModeratorError):
    status_code = 404
    code = "comment_not_found"


class NotAppealableError(ModeratorError):
    """Raised when appealing a comment that was not rejected."""

    status_code = 409
    code = "not_appealable"


class AlreadyAppealedError(ModeratorError):
    """Raised when a comment has already been through the appeal process."""

    status_code = 409
    code = "already_appealed"


class RateLimitExceededError(ModeratorError):
    status_code = 429
    code = "rate_limit_exceeded"


async def moderator_error_handler(_: Request, exc: ModeratorError) -> JSONResponse:
    """Render a `ModeratorError` as a JSON error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )
