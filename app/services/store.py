"""Moderation log storage.

The store keeps every decision in memory for fast reads and mirrors it to a JSON
file so the log survives restarts. All access goes through a lock, so it is safe
to use from FastAPI's threadpool. Swap this class out for a database-backed
implementation without touching the rest of the app.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.models.schemas import (
    AppealResult,
    LogEntry,
    ModerationResult,
)

logger = logging.getLogger(__name__)


class ModerationStore:
    """Thread-safe, file-backed store of moderation log entries."""

    def __init__(self, log_file: str | None = None) -> None:
        self._lock = threading.RLock()
        self._entries: dict[str, LogEntry] = {}
        self._log_path: Path | None = Path(log_file) if log_file else None
        self._load()

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, comment_id: str) -> LogEntry | None:
        with self._lock:
            return self._entries.get(comment_id)

    def all_entries(self) -> list[LogEntry]:
        """Return all entries, newest first."""
        with self._lock:
            return sorted(
                self._entries.values(), key=lambda e: e.timestamp, reverse=True
            )

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def add_moderation(
        self, *, user_id: str, comment: str, result: ModerationResult
    ) -> LogEntry:
        """Persist a first-pass moderation decision and return the new entry."""
        entry = LogEntry(
            user_id=user_id,
            comment=comment,
            decision=result.decision,
            confidence=result.confidence,
            reasoning=result.reasoning,
            category=result.category,
        )
        with self._lock:
            self._entries[entry.id] = entry
            self._persist()
        return entry

    def add_appeal(self, *, comment_id: str, appeal_context: str, result: AppealResult) -> LogEntry:
        """Attach an appeal outcome to an existing entry and return it."""
        with self._lock:
            entry = self._entries[comment_id]
            entry.appealed = True
            entry.appeal_context = appeal_context
            entry.final_decision = result.decision
            entry.final_reasoning = result.reasoning
            entry.appeal_confidence = result.confidence
            entry.appeal_category = result.category
            entry.appeal_timestamp = datetime.now(UTC).isoformat()
            self._persist()
            return entry

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _persist(self) -> None:
        """Write the whole log to disk (called while holding the lock)."""
        if self._log_path is None:
            return
        try:
            payload = [e.model_dump() for e in self._entries.values()]
            tmp = self._log_path.with_suffix(self._log_path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._log_path)  # atomic on POSIX & Windows
        except OSError as exc:
            # Persistence is best-effort; never fail a request because of disk I/O.
            logger.error("Failed to persist moderation log: %s", exc)

    def _load(self) -> None:
        """Load any existing log file into memory on startup."""
        if self._log_path is None or not self._log_path.exists():
            return
        try:
            raw = json.loads(self._log_path.read_text(encoding="utf-8"))
            for item in raw:
                entry = LogEntry.model_validate(item)
                self._entries[entry.id] = entry
            logger.info("Loaded %d moderation entries from %s", len(self._entries), self._log_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error("Could not load existing log file (%s): %s", self._log_path, exc)
