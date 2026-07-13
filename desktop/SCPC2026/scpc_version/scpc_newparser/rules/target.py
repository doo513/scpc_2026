from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.evidence import EvidenceKind
from core.evidence_graph import EvidenceGraph
from core.ontology import RecordType
from core.records import MemoryClass
from core.session_state import MemoryEntry, MemoryStore
from core.task_view import TaskView


@dataclass(frozen=True)
class TargetCandidate:
    target: str
    source: str
    confidence: str
    requirements: tuple[str, ...] = ()


class TargetResolver:
    """Produces target candidates; it never finalizes an output target."""

    @staticmethod
    def resolve_candidates(
        view: TaskView,
        evidence: EvidenceGraph,
        focal_id: str,
        memory_store: MemoryStore | dict[str, Any] | None = None,
        *,
        focal_override: dict[str, Any] | None = None,
    ) -> tuple[TargetCandidate, ...]:
        candidates: list[TargetCandidate] = []
        focal = (
            focal_override
            if focal_override is not None
            else view.objects_by_id().get(focal_id) if focal_id else {}
        )

        if "prompt_local_intent" in evidence.local_update:
            candidates.append(
                TargetCandidate(
                    "memory_store", "latest_local_intent", "high"
                )
            )
        if view.record_present(RecordType.PERSISTENT_MEMORY_WRITE):
            candidates.append(
                TargetCandidate(
                    "memory_store", "persistent_memory_write", "high"
                )
            )

        changed = view.record_target_change()
        if changed is not None and changed.replacement_target:
            candidates.append(
                TargetCandidate(
                    changed.replacement_target,
                    "target_changed_after_turn",
                    "decisive",
                )
            )

        recalled, recall_reason = TargetResolver._target_from_memory_recall(
            view, evidence, memory_store
        )
        if recalled:
            candidates.append(TargetCandidate(recalled, recall_reason, "high"))
        elif recall_reason == "required_memory_unavailable":
            candidates.append(
                TargetCandidate(
                    "",
                    recall_reason,
                    "none",
                    ("requirement:memory_value:missing",),
                )
            )

        resolved = view.record_reference(RecordType.RESOLVED_TARGET)
        if resolved:
            candidates.append(
                TargetCandidate(resolved, "resolved_target", "high")
            )

        attrs = focal.get("attrs") or {} if focal else {}
        for key in (
            "recipient",
            "target",
            "channel",
            "app",
            "merchant",
            "name",
            "attendee",
        ):
            if attrs.get(key):
                candidates.append(
                    TargetCandidate(
                        str(attrs[key]), f"focal_attr:{key}", "medium"
                    )
                )
                break

        last_target = str(view.session_state.get("last_target") or "")
        if last_target and TargetResolver._allows_session_target(evidence):
            candidates.append(
                TargetCandidate(last_target, "same_session", "low")
            )
        deduped: list[TargetCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate.target, candidate.source)
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return tuple(deduped)

    @staticmethod
    def _target_from_memory_recall(
        view: TaskView,
        evidence: EvidenceGraph,
        memory_store: MemoryStore | dict[str, Any] | None,
    ) -> tuple[str, str]:
        if evidence.intent_evidence.prompt_evidence(
            EvidenceKind.MEMORY_REJECTION
        ):
            return "", "memory_rejected_by_latest_prompt"

        saw_recall = False
        for recall in view.memory_recall_values():
            saw_recall = True
            request = recall.as_request()
            memory = TargetResolver._recall_value(request, memory_store)
            if memory:
                memory_contexts = {
                    item.payload
                    for item in evidence.intent_evidence.prompt_evidence(
                        EvidenceKind.MEMORY_CONTEXT_REFERENCE
                    )
                }
                if recall.memory_class == MemoryClass.PRIOR_RESULT:
                    keys = (
                        "last_success_target",
                        "approval_channel",
                        "preferred_channel",
                        "health_channel",
                    )
                elif recall.memory_class == MemoryClass.STANDING_CONSTRAINT:
                    keys = (
                        "last_success_target",
                        "approval_channel",
                        "preferred_channel",
                    )
                elif "lighting_routine" in memory_contexts:
                    keys = ("dusk_room",)
                elif "health_schedule" in memory_contexts:
                    keys = (
                        "health_channel",
                        "preferred_channel",
                        "approval_channel",
                    )
                else:
                    keys = (
                        "preferred_channel",
                        "health_channel",
                        "approval_channel",
                        "last_success_target",
                    )
                for key in keys:
                    if memory.get(key):
                        return str(memory[key]), f"persistent_memory:{key}"

            for key in (
                "preferred_channel",
                "health_channel",
                "approval_channel",
                "last_success_target",
            ):
                if request.get(key):
                    return str(request[key]), f"recall_record:{key}"
        return (
            ("", "required_memory_unavailable")
            if saw_recall
            else ("", "no_memory_target")
        )

    @staticmethod
    def _recall_value(
        request: dict[str, Any],
        memory_store: MemoryStore | dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(memory_store, MemoryStore):
            entry = memory_store.recall(request)
            return entry.value if isinstance(entry, MemoryEntry) else {}
        if isinstance(memory_store, dict):
            value = memory_store.get(str(request.get("memory_key") or ""), {})
            if isinstance(value, dict) and isinstance(value.get("value"), dict):
                value = value["value"]
            return value if isinstance(value, dict) else {}
        return {}

    @staticmethod
    def _allows_session_target(evidence: EvidenceGraph) -> bool:
        return bool(
            evidence.intent_evidence.prompt_evidence(
                EvidenceKind.SESSION_TARGET_REFERENCE
            )
        )
