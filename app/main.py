"""Application factory and process entrypoint.

Builds the FastAPI app, wires singletons onto ``app.state`` in the lifespan,
registers exception handlers, and exposes ``/health`` plus the moderation routes.

Run with:  ``uvicorn app.main:app --reload``
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import Settings, get_settings
from app.core.errors import ModeratorError, moderator_error_handler
from app.core.rate_limit import RateLimiter
from app.services.moderator import build_moderator
from app.services.notifier import WebhookNotifier
from app.services.store import ModerationStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


def _init_state(app: FastAPI, settings: Settings) -> None:
    """Construct and attach the app's singleton collaborators."""
    app.state.settings = settings
    app.state.store = ModerationStore(log_file=settings.log_file)
    app.state.notifier = WebhookNotifier(webhook_url=settings.webhook_url)
    app.state.rate_limiter = RateLimiter(
        rate=settings.rate_limit, enabled=settings.rate_limit_enabled
    )

    if settings.llm_configured:
        app.state.moderator = build_moderator(
            api_key=settings.anthropic_api_key,
            model=settings.moderation_model,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        logger.info("Moderator ready using model '%s'.", settings.moderation_model)
    else:
        app.state.moderator = None
        logger.warning(
            "ANTHROPIC_API_KEY not set — /moderate and /appeal will return 503 "
            "until it is configured."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_state(app, get_settings())
    yield


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="AI Comment Moderator",
        version="1.0.0",
        description=(
            "Backend API that moderates forum comments with an LLM, with an "
            "appeal mechanism and a moderation log."
        ),
        lifespan=lifespan,
    )

    app.add_exception_handler(ModeratorError, moderator_error_handler)
    app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "model": settings.moderation_model,
            "llm_configured": settings.llm_configured,
            "rate_limit_enabled": settings.rate_limit_enabled,
        }

    return app


app = create_app()
