from __future__ import annotations

from dataclasses import dataclass
import copy
from typing import Any


@dataclass(frozen=True)
class MemoryEntry:
    key: str
    person: str
    value: dict[str, Any]
    source_task_id: str
    source_session_id: str
    source_turn_index: int


class MemoryStore:
    """Process-local persistent memory with provenance and explicit recall."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], list[MemoryEntry]] = {}

    def clear(self) -> None:
        self._entries.clear()

    def clone(self) -> "MemoryStore":
        cloned = MemoryStore()
        cloned._entries = copy.deepcopy(self._entries)
        return cloned

    def replace_from(self, other: "MemoryStore") -> None:
        self._entries = copy.deepcopy(other._entries)

    def write(
        self,
        value: dict[str, Any],
        *,
        task_id: str,
        session_id: str,
        turn_index: int,
    ) -> MemoryEntry | None:
        key = str(value.get("memory_key") or value.get("person") or "")
        if not key:
            return None
        person = str(value.get("person") or "")
        entry = MemoryEntry(key, person, dict(value), task_id, session_id, turn_index)
        bucket = self._entries.setdefault((key, person), [])
        if entry not in bucket:
            bucket.append(entry)
        return entry

    def recall(self, request: dict[str, Any]) -> MemoryEntry | None:
        key = str(request.get("memory_key") or "")
        person = str(request.get("person") or "")
        if not key:
            return None
        candidates = self._entries.get((key, person), [])
        if not candidates and not person:
            candidates = [entry for (entry_key, _), entries in self._entries.items() if entry_key == key for entry in entries]
        return max(
            candidates,
            key=lambda entry: (entry.source_turn_index, entry.source_session_id, entry.source_task_id),
            default=None,
        )

    def snapshot(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for (key, _person), entries in self._entries.items():
            if entries:
                result[key] = max(
                    entries,
                    key=lambda entry: (entry.source_turn_index, entry.source_session_id, entry.source_task_id),
                ).value
        return result


def update_session_state(session: dict[str, Any], answer: dict[str, Any]) -> None:
    control = str(answer.get("control") or "")
    session["last_observed_control"] = control
    if control not in {"proceed", "amend"}:
        return
    session["last_target"] = answer["target"]
    session["last_control"] = control
    session["last_scope_mode"] = answer["content_scope"]["mode"]


class AtomicSessionCommitter:
    """Single owner for an all-or-nothing in-process session/memory commit."""

    production_active = True

    @staticmethod
    def commit(
        session: dict[str, Any],
        memory_store: MemoryStore,
        *,
        staged_session: dict[str, Any],
        staged_memory: MemoryStore,
    ) -> None:
        original_session = copy.deepcopy(session)
        original_memory = memory_store.clone()
        try:
            session.clear()
            session.update(copy.deepcopy(staged_session))
            memory_store.replace_from(staged_memory)
        except Exception:
            session.clear()
            session.update(original_session)
            memory_store.replace_from(original_memory)
            raise
