"""Unit tests for the FastAPI dependency providers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.dependencies import (
    get_moderator,
    get_notifier,
    get_rate_limiter,
    get_store,
)


class _State:
    pass


class _App:
    def __init__(self, **attrs) -> None:
        self.state = _State()
        for key, value in attrs.items():
            setattr(self.state, key, value)


class _Request:
    def __init__(self, app: _App) -> None:
        self.app = app


def test_providers_return_state_singletons():
    request = _Request(
        _App(store="STORE", notifier="NOTIFIER", rate_limiter="LIMITER", moderator="MOD")
    )
    assert get_store(request) == "STORE"
    assert get_notifier(request) == "NOTIFIER"
    assert get_rate_limiter(request) == "LIMITER"
    assert get_moderator(request) == "MOD"


def test_get_moderator_raises_503_when_unconfigured():
    request = _Request(_App(moderator=None))
    with pytest.raises(HTTPException) as exc_info:
        get_moderator(request)
    assert exc_info.value.status_code == 503
