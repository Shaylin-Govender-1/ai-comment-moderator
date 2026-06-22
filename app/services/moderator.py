"""LLM moderation service.

`LLMModerator` wraps the Anthropic client and turns a raw comment (or an appeal)
into a normalised, schema-validated result. It is deliberately defensive: the
public methods never raise because of a misbehaving model or a transient API
error — they fall back to a safe decision instead.

Design choices that matter:
- **Forced tool use** guarantees structured output, removing fragile text parsing.
- **Few-shot history** (for first-pass moderation) anchors the model's behaviour.
- **Retries with backoff** handle transient API errors; a final failure degrades
  gracefully to ``flagged_for_review`` (for moderation) or to upholding the
  original rejection (for appeals) — we never auto-approve on error.
"""

from __future__ import annotations

import logging
import time

from anthropic import Anthropic, APIError, APITimeoutError

from app.models.schemas import (
    AppealResult,
    Decision,
    FinalDecision,
    ModerationResult,
    RejectionCategory,
)
from app.services import prompts

logger = logging.getLogger(__name__)

_MAX_TOKENS = 600


class LLMModerator:
    """Moderates comments and re-evaluates appeals using an LLM."""

    def __init__(
        self,
        client: Anthropic,
        model: str,
        max_retries: int = 2,
    ) -> None:
        self._client = client
        self._model = model
        self._max_retries = max_retries

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def moderate(self, comment: str) -> ModerationResult:
        """Make a first-pass moderation decision for ``comment``."""
        messages = self._build_few_shot_messages()
        messages.append(
            {"role": "user", "content": prompts.format_comment_for_moderation(comment)}
        )

        tool_input = self._call_tool(
            messages=messages,
            tool=prompts.MODERATION_TOOL,
        )
        if tool_input is None:
            return self._moderation_fallback()

        try:
            result = ModerationResult.model_validate(tool_input)
        except Exception as exc:  # malformed payload despite the schema
            logger.warning("Moderation tool payload failed validation: %s", exc)
            return self._moderation_fallback()

        return self._normalise_moderation(result)

    def reconsider(
        self, comment: str, original_reasoning: str, appeal_context: str
    ) -> AppealResult:
        """Re-evaluate a rejected ``comment`` in light of an appeal."""
        user_message = prompts.build_appeal_user_message(
            comment=comment,
            original_reasoning=original_reasoning,
            appeal_context=appeal_context,
        )
        messages = [{"role": "user", "content": user_message}]

        tool_input = self._call_tool(
            messages=messages,
            tool=prompts.APPEAL_TOOL,
        )
        if tool_input is None:
            return self._appeal_fallback()

        try:
            result = AppealResult.model_validate(tool_input)
        except Exception as exc:
            logger.warning("Appeal tool payload failed validation: %s", exc)
            return self._appeal_fallback()

        return self._normalise_appeal(result)

    # ------------------------------------------------------------------ #
    # LLM plumbing
    # ------------------------------------------------------------------ #
    def _call_tool(self, messages: list[dict], tool: dict) -> dict | None:
        """Call the model forcing ``tool`` and return the tool input dict.

        Returns ``None`` if the call fails after retries or the model does not
        produce a tool call. Callers convert ``None`` into a safe fallback.
        """
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=_MAX_TOKENS,
                    system=prompts.SYSTEM_PROMPT,
                    messages=messages,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": tool["name"]},
                )
                return self._extract_tool_input(response, tool["name"])
            except (APITimeoutError, APIError) as exc:
                last_error = exc
                wait = 0.5 * (2**attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                )
                if attempt < self._max_retries:
                    time.sleep(wait)
            except Exception as exc:  # unexpected client/library error
                last_error = exc
                logger.error("Unexpected LLM error: %s", exc)
                break

        logger.error("LLM call ultimately failed: %s", last_error)
        return None

    @staticmethod
    def _extract_tool_input(response, tool_name: str) -> dict | None:
        """Pull the forced tool-call input out of an Anthropic response."""
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                if isinstance(block.input, dict):
                    return block.input
        logger.warning("No '%s' tool_use block found in LLM response.", tool_name)
        return None

    # ------------------------------------------------------------------ #
    # Normalisation & fallbacks
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalise_moderation(result: ModerationResult) -> ModerationResult:
        """Keep category consistent with the decision."""
        if result.decision == Decision.APPROVED:
            result.category = RejectionCategory.NONE
        elif result.category == RejectionCategory.NONE:
            # Rejected/flagged should carry a category; default to 'other'.
            result.category = RejectionCategory.OTHER
        return result

    @staticmethod
    def _normalise_appeal(result: AppealResult) -> AppealResult:
        if result.decision == FinalDecision.APPROVED:
            result.category = RejectionCategory.NONE
        elif result.category == RejectionCategory.NONE:
            result.category = RejectionCategory.OTHER
        return result

    @staticmethod
    def _moderation_fallback() -> ModerationResult:
        """Safe default when moderation cannot be completed automatically."""
        return ModerationResult(
            decision=Decision.FLAGGED_FOR_REVIEW,
            confidence=0.0,
            reasoning=(
                "Automated moderation could not be completed reliably, so this "
                "comment has been flagged for a human moderator to review."
            ),
            category=RejectionCategory.OTHER,
        )

    @staticmethod
    def _appeal_fallback() -> AppealResult:
        """Safe default when an appeal cannot be re-evaluated automatically.

        We uphold the original rejection rather than auto-approving on error.
        """
        return AppealResult(
            decision=FinalDecision.REJECTED,
            confidence=0.0,
            reasoning=(
                "Automated re-evaluation of the appeal could not be completed, so "
                "the original rejection stands. Please escalate to a human moderator."
            ),
            category=RejectionCategory.OTHER,
        )

    # ------------------------------------------------------------------ #
    # Few-shot construction
    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_few_shot_messages() -> list[dict]:
        """Turn the example pairs into tool-use conversation history."""
        messages: list[dict] = []
        for i, (comment, tool_input) in enumerate(prompts.FEW_SHOT_EXAMPLES):
            call_id = f"example_{i}"
            messages.append(
                {"role": "user", "content": prompts.format_comment_for_moderation(comment)}
            )
            messages.append(
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": prompts.MODERATION_TOOL["name"],
                            "input": tool_input,
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call_id,
                            "content": "Decision recorded.",
                        }
                    ],
                }
            )
        return messages


def build_moderator(api_key: str, model: str, timeout: float, max_retries: int) -> LLMModerator:
    """Construct an `LLMModerator` backed by a real Anthropic client."""
    client = Anthropic(api_key=api_key, timeout=timeout)
    return LLMModerator(client=client, model=model, max_retries=max_retries)
