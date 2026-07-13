from __future__ import annotations

from dataclasses import dataclass
import re
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


def extract_memory_payload(prompt: str, alias: str) -> dict[str, Any]:
    """Parse only explicitly labelled memory fields; never infer missing values."""
    payload: dict[str, Any] = {"memory_key": alias}
    patterns = {
        "person_birthday": re.compile(r"([A-Za-z가-힣_]+)의 생일은\s*(\d{2}-\d{2})"),
        "preferred_channel": re.compile(r"연락 채널은\s*([A-Za-z0-9_]+)"),
        "tone": re.compile(r"말투는\s*([A-Za-z0-9_]+)"),
        "gift_hint": re.compile(r"선호 선물은\s*([A-Za-z0-9_]+)"),
        "avoid": re.compile(r"([A-Za-z0-9_]+)(?:는|은) 피하고"),
        "privacy_rule": re.compile(r"privacy 규칙은\s*([A-Za-z0-9_]+)"),
        "medication_time": re.compile(r"복약 시간은\s*(\d{2}:\d{2})"),
        "checkup": re.compile(r"검진/점검 일정은\s*(\d{2}-\d{2}\s+\d{2}:\d{2})\s+([A-Za-z0-9_]+)"),
        "dusk": re.compile(r"날이 어두워지면\s*([A-Za-z0-9_]+)\s*조명\s*(\d+)개"),
        "prior_result": re.compile(r"지난 성공 작업은\s*([A-Za-z0-9_]+)에\s*([A-Za-z0-9_]+)\s*범위"),
        "prior_excluded": re.compile(r"([A-Za-z0-9_]+)(?:는|은) 제외"),
        "failure": re.compile(r"실패 기록은\s*([A-Za-z0-9_]+)"),
        "enterprise": re.compile(r"기업 기본 규정은\s*([A-Za-z0-9_]+)이고 승인 채널은\s*([A-Za-z0-9_]+)"),
    }
    match = patterns["person_birthday"].search(prompt)
    if match:
        payload.update(person=match.group(1), birthday=match.group(2))
    for key in ("preferred_channel", "tone", "gift_hint", "avoid", "privacy_rule", "medication_time"):
        match = patterns[key].search(prompt)
        if match:
            payload[key] = match.group(1)
    match = patterns["checkup"].search(prompt)
    if match:
        payload.update(checkup_time=match.group(1), checkup_place=match.group(2))
    match = patterns["dusk"].search(prompt)
    if match:
        payload.update(dusk_room=match.group(1), dusk_light_count=match.group(2))
    match = patterns["prior_result"].search(prompt)
    if match:
        payload.update(last_success_target=match.group(1), last_success_scope=match.group(2))
    match = patterns["prior_excluded"].search(prompt)
    if match:
        payload["last_success_excluded"] = match.group(1)
    match = patterns["failure"].search(prompt)
    if match:
        payload["last_failure_reason"] = match.group(1)
    match = patterns["enterprise"].search(prompt)
    if match:
        payload.update(enterprise_rule=match.group(1), approval_channel=match.group(2))
    return payload
