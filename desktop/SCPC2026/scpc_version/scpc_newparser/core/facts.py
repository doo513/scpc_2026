from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Iterable, Iterator

from .ontology import CapabilityType, FactStatus, ObjectType
from .records import Provenance, TypedRecordFact


FrozenValue = Any


@dataclass(frozen=True)
class FrozenMapping:
    items: tuple[tuple[str, FrozenValue], ...] = ()

    def get(self, key: str, default: Any = None) -> Any:
        for item_key, value in self.items:
            if item_key == key:
                return thaw_value(value)
        return default

    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _value in self.items)

    def to_dict(self) -> dict[str, Any]:
        return {key: thaw_value(value) for key, value in self.items}


def freeze_value(value: Any) -> FrozenValue:
    if isinstance(value, dict):
        return FrozenMapping(
            tuple(
                (str(key), freeze_value(child))
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            )
        )
    if isinstance(value, list):
        return tuple(freeze_value(child) for child in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("non-finite JSON number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def thaw_value(value: FrozenValue) -> Any:
    if isinstance(value, FrozenMapping):
        return value.to_dict()
    if isinstance(value, tuple):
        return [thaw_value(child) for child in value]
    return value


def _stable_digest(value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        payload = repr(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class TypedObjectFact:
    fact_id: str
    object_id: str
    object_type: ObjectType
    source_type: str
    attributes: FrozenMapping
    status: FactStatus
    provenance: Provenance | None
    issues: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

    @classmethod
    def parse(cls, raw_object: Any, *, session_id: str = "") -> "TypedObjectFact":
        if not isinstance(raw_object, dict):
            digest = _stable_digest(raw_object)
            return cls(
                fact_id=f"object:invalid:{digest}",
                object_id="",
                object_type=ObjectType.UNKNOWN,
                source_type="",
                attributes=FrozenMapping(),
                status=FactStatus.INVALID,
                provenance=None,
                issues=("object_not_mapping",),
            )

        object_id = str(raw_object.get("id") or "")
        source_type = str(raw_object.get("type") or "")
        issues: list[str] = []
        if not object_id:
            issues.append("missing_object_id")
        try:
            object_type = ObjectType.parse(source_type)
            status = FactStatus.PRESENT
        except ValueError:
            object_type = ObjectType.UNKNOWN
            status = FactStatus.UNKNOWN if source_type else FactStatus.INVALID
            issues.append(
                "unknown_object_type" if source_type else "missing_object_type"
            )

        raw_attributes = raw_object.get("attrs", {})
        if not isinstance(raw_attributes, dict):
            attributes = FrozenMapping()
            status = FactStatus.INVALID
            issues.append("object_attrs_not_mapping")
        else:
            try:
                frozen = freeze_value(raw_attributes)
                assert isinstance(frozen, FrozenMapping)
                attributes = frozen
            except TypeError:
                attributes = FrozenMapping()
                status = FactStatus.INVALID
                issues.append("object_attrs_not_json")
        if not object_id:
            status = FactStatus.INVALID

        source_id = object_id or f"invalid:{_stable_digest(raw_object)}"
        return cls(
            fact_id=f"object:{source_id}",
            object_id=object_id,
            object_type=object_type,
            source_type=source_type,
            attributes=attributes,
            status=status,
            provenance=Provenance("object", source_id, session_id),
            issues=tuple(issues),
        )

    def attribute(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def to_trace(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "object_id": self.object_id,
            "object_type": self.object_type.value,
            "source_type": self.source_type,
            "status": self.status.value,
            "issues": list(self.issues),
            "derived_from": list(self.derived_from),
        }


class ObjectFactIndex:
    def __init__(self, raw_objects: Iterable[Any], *, session_id: str = "") -> None:
        parsed = [
            TypedObjectFact.parse(raw, session_id=session_id) for raw in raw_objects
        ]
        by_id: dict[str, list[TypedObjectFact]] = {}
        for fact in parsed:
            if fact.object_id:
                by_id.setdefault(fact.object_id, []).append(fact)

        normalized: list[TypedObjectFact] = []
        for fact in parsed:
            siblings = by_id.get(fact.object_id, ()) if fact.object_id else ()
            if len(siblings) > 1 and len(set(siblings)) > 1:
                normalized.append(
                    TypedObjectFact(
                        fact_id=fact.fact_id,
                        object_id=fact.object_id,
                        object_type=fact.object_type,
                        source_type=fact.source_type,
                        attributes=fact.attributes,
                        status=FactStatus.CONFLICTED,
                        provenance=fact.provenance,
                        issues=tuple(
                            dict.fromkeys(fact.issues + ("duplicate_object_conflict",))
                        ),
                        derived_from=tuple(sorted(item.fact_id for item in siblings)),
                    )
                )
            else:
                normalized.append(fact)
        self._facts = tuple(sorted(normalized, key=self._sort_key))

    @property
    def facts(self) -> tuple[TypedObjectFact, ...]:
        return self._facts

    @staticmethod
    def _sort_key(fact: TypedObjectFact) -> tuple[str, str, str]:
        return (
            fact.object_id,
            fact.source_type,
            json.dumps(fact.attributes.to_dict(), ensure_ascii=False, sort_keys=True),
        )


@dataclass(frozen=True)
class CapabilitySnapshot:
    status: FactStatus
    capabilities: frozenset[CapabilityType]
    unknown_actions: tuple[str, ...] = ()
    issues: tuple[str, ...] = ()

    @classmethod
    def parse(cls, task: dict[str, Any]) -> "CapabilitySnapshot":
        if "available_actions" not in task:
            return cls(
                FactStatus.MISSING, frozenset(), issues=("available_actions_missing",)
            )
        raw_actions = task.get("available_actions")
        if not isinstance(raw_actions, list):
            return cls(
                FactStatus.INVALID, frozenset(), issues=("available_actions_not_list",)
            )
        known: set[CapabilityType] = set()
        unknown: set[str] = set()
        for raw_action in raw_actions:
            if not isinstance(raw_action, str) or not raw_action:
                unknown.add(str(raw_action))
                continue
            try:
                known.add(CapabilityType.parse(raw_action))
            except ValueError:
                unknown.add(raw_action)
        return cls(
            FactStatus.UNKNOWN if unknown else FactStatus.PRESENT,
            frozenset(known),
            tuple(sorted(unknown)),
            ("unknown_available_action",) if unknown else (),
        )

    @property
    def action_values(self) -> frozenset[str]:
        return frozenset(capability.value for capability in self.capabilities)


@dataclass(frozen=True)
class SessionSnapshot:
    status: FactStatus
    values: FrozenMapping
    issues: tuple[str, ...] = ()

    @classmethod
    def parse(cls, session_state: Any) -> "SessionSnapshot":
        if session_state is None:
            return cls(FactStatus.MISSING, FrozenMapping(), ("session_state_missing",))
        if not isinstance(session_state, dict):
            return cls(
                FactStatus.INVALID, FrozenMapping(), ("session_state_not_mapping",)
            )
        try:
            values = freeze_value(session_state)
            assert isinstance(values, FrozenMapping)
        except TypeError:
            return cls(FactStatus.INVALID, FrozenMapping(), ("session_state_not_json",))
        return cls(FactStatus.PRESENT, values)

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


@dataclass(frozen=True)
class TypedFactSnapshot:
    object_collection_status: FactStatus
    record_collection_status: FactStatus
    objects: tuple[TypedObjectFact, ...]
    records: tuple[TypedRecordFact, ...]
    capabilities: CapabilitySnapshot
    session: SessionSnapshot

    def __iter__(self) -> Iterator[TypedObjectFact | TypedRecordFact]:
        yield from self.objects
        yield from self.records

    def to_trace(self) -> dict[str, Any]:
        return {
            "object_collection_status": self.object_collection_status.value,
            "record_collection_status": self.record_collection_status.value,
            "object_count": len(self.objects),
            "record_count": len(self.records),
            "capability_status": self.capabilities.status.value,
            "session_status": self.session.status.value,
        }
