from __future__ import annotations

import copy
import json
from typing import Any, Iterable

from .evidence import latest_clause_from_text, normalize_text
from .facts import (
    CapabilitySnapshot,
    ObjectFactIndex,
    SessionSnapshot,
    TypedFactSnapshot,
    TypedObjectFact,
)
from .ontology import FactStatus, RecordType
from .records import (
    DurationValue,
    FocalResolutionTraceValue,
    MarkerRefsValue,
    MemoryRecallValue,
    MemoryWriteValue,
    RecordCode,
    RecordIndex,
    TargetChangeValue,
    TypedRecordFact,
)
from .property_policy import PropertyDescriptor, describe_object_properties


def stable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class TaskView:
    """Normalized, read-only access to one participant-visible task."""

    def __init__(self, task: dict[str, Any], session_state: dict[str, Any] | None = None):
        self.task = copy.deepcopy(task) if isinstance(task, dict) else {}
        self.session_state = (
            copy.deepcopy(session_state) if isinstance(session_state, dict) else {}
        )

        raw_state = self.task.get("device_state")
        state = raw_state if isinstance(raw_state, dict) else {}
        raw_objects = state.get("objects") if "objects" in state else None
        raw_records = state.get("records") if "records" in state else None
        object_items = raw_objects if isinstance(raw_objects, list) else []
        record_items = raw_records if isinstance(raw_records, list) else []
        self._objects = tuple(o for o in object_items if isinstance(o, dict))
        self._records = tuple(r for r in record_items if isinstance(r, dict))
        self._history = tuple(h for h in self.task.get("visible_history", []) if isinstance(h, dict))
        self._memory = tuple(m for m in self.task.get("personal_memory", []) if isinstance(m, dict))
        self.capability_snapshot = CapabilitySnapshot.parse(self.task)
        self.session_snapshot = SessionSnapshot.parse(session_state)
        self._available_actions = self.capability_snapshot.action_values
        session_id = str(self.task.get("session_id") or "")
        self.object_fact_index = ObjectFactIndex(object_items, session_id=session_id)
        self.record_index = RecordIndex(record_items, session_id=session_id)
        self._object_collection_status = self._collection_status(
            raw_state,
            raw_objects,
            self.object_fact_index.facts,
        )
        self._record_collection_status = self._collection_status(
            raw_state,
            raw_records,
            self.record_index.resolved_facts,
        )

        objects_by_id: dict[str, list[dict[str, Any]]] = {}
        for obj in self._objects:
            if obj.get("id") is not None:
                objects_by_id.setdefault(str(obj["id"]), []).append(obj)
        self._conflicting_object_ids = {
            object_id
            for object_id, objects in objects_by_id.items()
            if len({stable_text(obj) for obj in objects}) > 1
        }
        self._objects_by_id = {
            object_id: min(objects, key=stable_text)
            for object_id, objects in objects_by_id.items()
        }

        objects_by_ref: dict[str, list[dict[str, Any]]] = {}
        for obj in self._objects:
            ref_code = str((obj.get("attrs") or {}).get("ref_code") or "")
            if ref_code:
                objects_by_ref.setdefault(ref_code, []).append(obj)
        self._conflicting_ref_codes = {
            ref_code
            for ref_code, objects in objects_by_ref.items()
            if len({stable_text(obj) for obj in objects}) > 1
        }
        self._objects_by_ref_code = {
            ref_code: min(objects, key=stable_text)
            for ref_code, objects in objects_by_ref.items()
        }
        self._ambiguous_object_binding_ids = set(self._conflicting_object_ids)
        for ref_code in self._conflicting_ref_codes:
            self._ambiguous_object_binding_ids.update(
                str(obj.get("id") or "")
                for obj in objects_by_ref[ref_code]
                if obj.get("id") is not None
            )

    @property
    def task_id(self) -> str:
        return str(self.task.get("id") or "")

    @property
    def session_id(self) -> str:
        return str(self.task.get("session_id") or "")

    @property
    def turn_index(self) -> int:
        try:
            return int(self.task.get("turn_index", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def prompt(self) -> str:
        return normalize_text(stable_text(self.task.get("prompt")))

    @property
    def objects(self) -> tuple[dict[str, Any], ...]:
        return self._objects

    @property
    def records(self) -> tuple[dict[str, Any], ...]:
        return self._records

    @property
    def history(self) -> tuple[dict[str, Any], ...]:
        return self._history

    @property
    def available_actions(self) -> frozenset[str]:
        return self._available_actions

    @property
    def typed_objects(self) -> tuple[TypedObjectFact, ...]:
        return self.object_fact_index.facts

    @property
    def typed_records(self) -> tuple[TypedRecordFact, ...]:
        return self.record_index.resolved_facts

    @property
    def direct_record_facts(self) -> tuple[TypedRecordFact, ...]:
        return self.record_index.facts

    @property
    def typed_facts(self) -> TypedFactSnapshot:
        return TypedFactSnapshot(
            object_collection_status=self._object_collection_status,
            record_collection_status=self._record_collection_status,
            objects=self.typed_objects,
            records=self.typed_records,
            capabilities=self.capability_snapshot,
            session=self.session_snapshot,
        )

    def objects_by_id(self) -> dict[str, dict[str, Any]]:
        return self._objects_by_id

    def objects_by_ref_code(self) -> dict[str, dict[str, Any]]:
        return self._objects_by_ref_code

    def conflicting_object_ids(self) -> set[str]:
        return set(self._conflicting_object_ids)

    def conflicting_ref_codes(self) -> set[str]:
        return set(self._conflicting_ref_codes)

    def object_binding_is_ambiguous(self, object_id: str) -> bool:
        return object_id in self._ambiguous_object_binding_ids

    def record_fact(self, record_type: RecordType | str) -> TypedRecordFact:
        return self.record_index.fact(record_type)

    def record_facts(
        self,
        record_type: RecordType | str,
    ) -> tuple[TypedRecordFact, ...]:
        return self.record_index.facts_of_type(record_type)

    def record_status(self, record_type: RecordType | str) -> FactStatus:
        return self.record_fact(record_type).status

    def record_present(self, record_type: RecordType | str) -> bool:
        return self.record_status(record_type) == FactStatus.PRESENT

    def record_code(self, record_type: RecordType | str) -> RecordCode | None:
        return self.record_fact(record_type).code

    def record_reference(self, record_type: RecordType | str) -> str:
        return self.record_fact(record_type).reference

    def record_target_change(self) -> TargetChangeValue | None:
        value = self.record_fact(RecordType.TARGET_CHANGED_AFTER_TURN).semantic_value
        return value if isinstance(value, TargetChangeValue) else None

    def record_duration(self) -> DurationValue | None:
        value = self.record_fact(RecordType.TEMPORARY_OVERRIDE_ALLOWED).semantic_value
        return value if isinstance(value, DurationValue) else None

    def marker_refs(self) -> MarkerRefsValue | None:
        value = self.record_fact(RecordType.FOCAL_MARKER_REFS).semantic_value
        return value if isinstance(value, MarkerRefsValue) else None

    def focal_resolution_trace(self) -> FocalResolutionTraceValue | None:
        value = self.record_fact(RecordType.FOCAL_RESOLUTION_TRACE).semantic_value
        return value if isinstance(value, FocalResolutionTraceValue) else None

    def memory_recall_values(self) -> tuple[MemoryRecallValue, ...]:
        fact = self.record_fact(RecordType.PERSISTENT_MEMORY_RECALL)
        value = fact.semantic_value
        return (
            (value,)
            if fact.status == FactStatus.PRESENT
            and isinstance(value, MemoryRecallValue)
            else ()
        )

    def memory_write_values(self) -> tuple[MemoryWriteValue, ...]:
        fact = self.record_fact(RecordType.PERSISTENT_MEMORY_WRITE)
        value = fact.semantic_value
        return (
            (value,)
            if fact.status == FactStatus.PRESENT
            and isinstance(value, MemoryWriteValue)
            else ()
        )

    def record_source_ids(self, record_type: RecordType | str) -> tuple[str, ...]:
        return tuple(fact.fact_id for fact in self.record_facts(record_type))

    def record_is_ambiguous(self, record_type: RecordType | str) -> bool:
        return self.record_index.is_conflicting(record_type)

    def duplicate_record_types(self) -> set[str]:
        return self.record_index.conflicting_types()

    def contains_for_object(self, object_id: str) -> set[str]:
        obj = self._objects_by_id.get(object_id)
        if not obj:
            return set()
        attrs = obj.get("attrs") or {}
        declared: set[str] = set()
        for inventory_key in ("contains", "fields"):
            raw = attrs.get(inventory_key)
            if isinstance(raw, list):
                declared.update(str(item) for item in raw)
        return declared

    def properties_for_object(self, object_id: str) -> tuple[PropertyDescriptor, ...]:
        obj = self._objects_by_id.get(object_id)
        return describe_object_properties(obj) if obj else ()

    def object_type(self, object_id: str) -> str | None:
        obj = self._objects_by_id.get(object_id)
        return str(obj.get("type")) if obj else None

    def latest_clause(self) -> str:
        clause, _span = latest_clause_from_text(self.prompt)
        return clause

    def current_turn_history(self) -> tuple[dict[str, Any], ...]:
        return tuple(item for item in self._history if self._history_turn(item) == self.turn_index)

    def visible_history_text(self, *, current_turn_only: bool = False) -> str:
        items: Iterable[dict[str, Any]] = self.current_turn_history() if current_turn_only else self._history
        return " ".join(stable_text(item.get("summary", item)) for item in items)

    def personal_memory_entries(self) -> tuple[dict[str, Any], ...]:
        return self._memory

    @staticmethod
    def _history_turn(item: dict[str, Any]) -> int | None:
        try:
            return int(item.get("turn"))
        except (TypeError, ValueError):
            return None

        return None

    @staticmethod
    def _collection_status(
        raw_state: Any,
        raw_collection: Any,
        facts: tuple[Any, ...],
    ) -> FactStatus:
        if raw_state is None or (
            isinstance(raw_state, dict) and raw_collection is None
        ):
            return FactStatus.MISSING
        if not isinstance(raw_state, dict) or not isinstance(raw_collection, list):
            return FactStatus.INVALID
        if any(fact.status == FactStatus.INVALID for fact in facts):
            return FactStatus.INVALID
        if any(fact.status == FactStatus.CONFLICTED for fact in facts):
            return FactStatus.CONFLICTED
        if any(fact.status == FactStatus.UNKNOWN for fact in facts):
            return FactStatus.UNKNOWN
        return FactStatus.PRESENT
