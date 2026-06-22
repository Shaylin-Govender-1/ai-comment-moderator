"""Unit tests for LLMModerator, focusing on robustness to bad/odd AI responses.

A tiny fake Anthropic client lets us exercise the parsing, normalisation and
fallback logic without any network calls.
"""

from __future__ import annotations

from app.models.schemas import Decision, FinalDecision, RejectionCategory
from app.services import prompts
from app.services.moderator import LLMModerator


class _Block:
    def __init__(self, type_, name=None, input_=None):
        self.type = type_
        self.name = name
        self.input = input_


class _Response:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, behavior):
        self._behavior = behavior
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._behavior(kwargs)


class _FakeClient:
    def __init__(self, behavior):
        self.messages = _FakeMessages(behavior)


def _moderator(behavior) -> LLMModerator:
    return LLMModerator(client=_FakeClient(behavior), model="test-model", max_retries=0)


def _tool_response(name, payload):
    return _Response([_Block("tool_use", name=name, input_=payload)])


# --- happy path ---------------------------------------------------------- #
def test_moderate_parses_tool_output():
    mod = _moderator(
        lambda _: _tool_response(
            "submit_moderation_decision",
            {"decision": "rejected", "confidence": 0.9, "category": "spam", "reasoning": "ad"},
        )
    )
    result = mod.moderate("buy my course")
    assert result.decision == Decision.REJECTED
    assert result.category == RejectionCategory.SPAM
    assert result.confidence == 0.9


def test_moderate_sends_system_prompt_and_forced_tool():
    client_holder = {}

    def behavior(kwargs):
        client_holder["kwargs"] = kwargs
        return _tool_response(
            "submit_moderation_decision",
            {"decision": "approved", "confidence": 0.9, "category": "none", "reasoning": "ok"},
        )

    mod = _moderator(behavior)
    mod.moderate("hello")
    kwargs = client_holder["kwargs"]
    assert kwargs["system"] == prompts.SYSTEM_PROMPT
    assert kwargs["tool_choice"]["name"] == "submit_moderation_decision"


# --- robustness / fallbacks --------------------------------------------- #
def test_moderate_falls_back_when_no_tool_use():
    mod = _moderator(lambda _: _Response([_Block("text")]))
    result = mod.moderate("anything")
    assert result.decision == Decision.FLAGGED_FOR_REVIEW
    assert result.confidence == 0.0


def test_moderate_falls_back_on_api_error():
    def boom(_):
        raise RuntimeError("network down")

    result = _moderator(boom).moderate("anything")
    assert result.decision == Decision.FLAGGED_FOR_REVIEW


def test_moderate_falls_back_on_malformed_payload():
    mod = _moderator(
        lambda _: _tool_response(
            "submit_moderation_decision",
            {"decision": "approved", "confidence": 5.0, "category": "none", "reasoning": "x"},
        )
    )
    # confidence 5.0 violates the 0..1 bound -> validation fails -> fallback.
    assert mod.moderate("x").decision == Decision.FLAGGED_FOR_REVIEW


def test_approved_decision_is_normalised_to_no_category():
    mod = _moderator(
        lambda _: _tool_response(
            "submit_moderation_decision",
            {"decision": "approved", "confidence": 0.9, "category": "spam", "reasoning": "x"},
        )
    )
    assert mod.moderate("x").category == RejectionCategory.NONE


def test_rejected_without_category_defaults_to_other():
    mod = _moderator(
        lambda _: _tool_response(
            "submit_moderation_decision",
            {"decision": "rejected", "confidence": 0.9, "category": "none", "reasoning": "x"},
        )
    )
    assert mod.moderate("x").category == RejectionCategory.OTHER


# --- appeals ------------------------------------------------------------- #
def test_reconsider_parses_appeal_tool():
    mod = _moderator(
        lambda _: _tool_response(
            "submit_appeal_decision",
            {"decision": "approved", "confidence": 0.8, "category": "none", "reasoning": "ctx helps"},
        )
    )
    result = mod.reconsider("comment", "was spam", "actually genuine")
    assert result.decision == FinalDecision.APPROVED


def test_reconsider_upholds_rejection_on_error():
    def boom(_):
        raise RuntimeError("down")

    result = _moderator(boom).reconsider("c", "r", "ctx")
    # On failure we never auto-approve an appeal.
    assert result.decision == FinalDecision.REJECTED


# --- few-shot ------------------------------------------------------------ #
def test_few_shot_history_shape():
    messages = LLMModerator._build_few_shot_messages()
    # Each example contributes user + assistant + tool_result = 3 messages.
    assert len(messages) == 3 * len(prompts.FEW_SHOT_EXAMPLES)
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
