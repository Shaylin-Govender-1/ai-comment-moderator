"""Tests for app wiring in app.main (the lifespan state initialiser)."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings
from app.main import _init_state
from app.services.moderator import LLMModerator


def test_init_state_builds_moderator_when_key_present():
    app = FastAPI()
    _init_state(app, Settings(anthropic_api_key="test-key", log_file=""))
    assert isinstance(app.state.moderator, LLMModerator)
    assert app.state.store is not None
    assert app.state.notifier is not None
    assert app.state.rate_limiter is not None


def test_init_state_leaves_moderator_none_without_key():
    app = FastAPI()
    _init_state(app, Settings(anthropic_api_key="", log_file=""))
    assert app.state.moderator is None
