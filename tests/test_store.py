"""Unit tests for the file-backed moderation store."""

from __future__ import annotations

from app.models.schemas import (
    AppealResult,
    Decision,
    FinalDecision,
    ModerationResult,
    RejectionCategory,
)
from app.services.store import ModerationStore


def _moderation(decision=Decision.REJECTED):
    return ModerationResult(
        decision=decision,
        confidence=0.8,
        reasoning="reason",
        category=RejectionCategory.SPAM if decision == Decision.REJECTED else RejectionCategory.NONE,
    )


def test_add_and_get(tmp_path):
    store = ModerationStore(log_file=str(tmp_path / "log.json"))
    entry = store.add_moderation(user_id="u1", comment="hi", result=_moderation())
    assert store.get(entry.id) is entry
    assert store.get("missing") is None


def test_appeal_updates_entry(tmp_path):
    store = ModerationStore(log_file=str(tmp_path / "log.json"))
    entry = store.add_moderation(user_id="u1", comment="hi", result=_moderation())
    updated = store.add_appeal(
        comment_id=entry.id,
        appeal_context="please",
        result=AppealResult(
            decision=FinalDecision.APPROVED,
            confidence=0.9,
            reasoning="ok",
            category=RejectionCategory.NONE,
        ),
    )
    assert updated.appealed is True
    assert updated.final_decision == FinalDecision.APPROVED
    assert updated.appeal_timestamp is not None


def test_persistence_survives_reload(tmp_path):
    path = str(tmp_path / "log.json")
    store = ModerationStore(log_file=path)
    entry = store.add_moderation(user_id="u1", comment="persist me", result=_moderation())

    # A brand-new store pointed at the same file should load the entry.
    reloaded = ModerationStore(log_file=path)
    loaded = reloaded.get(entry.id)
    assert loaded is not None
    assert loaded.comment == "persist me"
    assert loaded.decision == Decision.REJECTED


def test_corrupt_log_file_does_not_crash(tmp_path):
    path = tmp_path / "log.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    # Should load gracefully (empty) rather than raising.
    store = ModerationStore(log_file=str(path))
    assert store.all_entries() == []


def test_in_memory_only_mode(tmp_path):
    store = ModerationStore(log_file=None)
    store.add_moderation(user_id="u1", comment="hi", result=_moderation())
    assert len(store.all_entries()) == 1
    # No file should be created.
    assert list(tmp_path.iterdir()) == []
