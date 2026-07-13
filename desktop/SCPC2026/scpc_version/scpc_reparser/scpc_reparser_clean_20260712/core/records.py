from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .contracts import ContractStatus
from .ontology import FactStatus, RecordType, StrictSemanticEnum


class FactRole(str, Enum):
    HINT = "hint"
    RELATION = "relation"
    STATE = "state"
    CONSTRAINT = "constraint"
    MEMORY = "memory"
    CAPABILITY_MODIFIER = "capability_modifier"
    UNKNOWN = "unknown"


class UnknownValuePolicy(StrictSemanticEnum):
    MARK_UNKNOWN = "mark_unknown"
    ACCEPT_REFERENCE = "accept_reference"
    ACCEPT_PRESENCE = "accept_presence"
    REJECT_INVALID = "reject_invalid"


class ChronologyDomain(StrictSemanticEnum):
    TURN_INDEX = "turn_index"
    TURN = "turn"
    TIMESTAMP = "timestamp"
    UPDATED_AT = "updated_at"
    CREATED_AT = "created_at"


class ChronologyKind(StrictSemanticEnum):
    INTEGER = "integer"
    ISO_DATETIME_LOCAL = "iso_datetime_local"
    ISO_DATETIME_OFFSET = "iso_datetime_offset"


class RecordCode(StrictSemanticEnum):
    CONSENT_GRANTED = "granted"
    CONSENT_REVOKED = "revoked"

    AMBIGUOUS_APPROVED_OR_VISIBLE = "approved_channel_or_visible_recipient"
    AMBIGUOUS_RECENT_SURFACE_OR_RESOLVED = (
        "surface_recipient_and_resolved_target_both_recent"
    )
    AMBIGUOUS_STORED_OR_VISIBLE = "stored_channel_or_visible_recipient"

    AUTHORITY_INCOMPLETE = "authority_incomplete"
    AUTHORITY_INTERNAL_CONFIRMED = "internal_binding_confirmed"
    AUTHORITY_LOCAL_CONFIRMED = "local_authority_confirmed"
    AUTHORITY_USER_PENDING = "user_binding_pending"

    EXTERNAL_DOCTOR_NOTE_FORBIDDEN = "doctor_note_forbidden"
    EXTERNAL_RAW_QUOTE_FORBIDDEN = "raw_quote_forbidden"
    EXTERNAL_RAW_SENSITIVE_FORBIDDEN = "raw_sensitive_forbidden"
    EXTERNAL_SUMMARY_ONLY = "summary_only_allowed"

    ENTERPRISE_APPLY_STANDING_DEFAULT = "apply_standing_default_constraint"
    OPS_USE_PRIOR_RESULTS = "use_prior_success_and_failure_records"

    ROUTE_AUTHORITY_AFTER_CANDIDATES = "authority_after_candidates"
    ROUTE_AUTHORITY_AFTER_BOUNDARY = "authority_after_boundary"
    ROUTE_BOUNDARY_AFTER_AUTHORITY = "boundary_after_authority"
    ROUTE_CANDIDATES_AFTER_AUTHORITY = "candidates_after_authority"

    CANDIDATES_EXTERNAL_PRESENT = "external_candidates_present"
    CANDIDATES_LOCAL_ONLY = "local_candidate_only"
    CANDIDATES_MIXED = "mixed_local_external_candidates"
    CANDIDATES_SINGLE_INTERNAL = "single_internal_candidate"

    SHARE_BOUNDARY_BLOCKED = "dispatch_blocked_until_binding"
    SHARE_BOUNDARY_LOCAL = "local_update_boundary"
    SHARE_BOUNDARY_REDACTED_AFTER_SELECTION = "redacted_after_selection_boundary"
    SHARE_BOUNDARY_REDACTED_EXTERNAL = "redacted_external_boundary"

    SESSION_POLICY_NORMAL = "normal"
    SESSION_POLICY_STRICT = "strict"


class MemoryClass(StrictSemanticEnum):
    PRIOR_RESULT = "prior_result"
    STANDING_CONSTRAINT = "standing_constraint"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Provenance:
    source_kind: str
    source_id: str
    session_id: str = ""
    turn: int | None = None
    span: tuple[int, int] | None = None
    assertion_mode: str = "direct"


@dataclass(frozen=True)
class ChronologyKey:
    domain: ChronologyDomain
    kind: ChronologyKind
    value: int | datetime

    def compare(self, other: "ChronologyKey") -> int:
        if self.domain != other.domain or self.kind != other.kind:
            raise ValueError("chronology keys from different domains are incomparable")
        return (self.value > other.value) - (self.value < other.value)

    def to_trace(self) -> dict[str, Any]:
        return {
            "domain": self.domain.value,
            "kind": self.kind.value,
            "value": self.value.isoformat()
            if isinstance(self.value, datetime)
            else self.value,
        }


@dataclass(frozen=True)
class PresenceValue:
    record_type: RecordType

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class CategoricalValue:
    code: RecordCode

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class ReferenceValue:
    reference: str

    @property
    def object_references(self) -> tuple[str, ...]:
        return (self.reference,)


@dataclass(frozen=True)
class TargetChangeValue:
    replacement_target: str = ""
    prior_route_superseded: bool = False

    @property
    def object_references(self) -> tuple[str, ...]:
        return (self.replacement_target,) if self.replacement_target else ()


@dataclass(frozen=True)
class DurationValue:
    amount: int
    unit: str

    @property
    def canonical(self) -> str:
        return f"{self.amount}{self.unit}"

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class MarkerRefsValue:
    marker_to_ref: tuple[tuple[str, str], ...]

    def reference_for(self, marker: str) -> str:
        return dict(self.marker_to_ref).get(marker, "")

    @property
    def object_references(self) -> tuple[str, ...]:
        return tuple(ref for _marker, ref in self.marker_to_ref)


@dataclass(frozen=True)
class FocalResolutionTraceValue:
    latest_phase: str
    phase_source_is_route_binding_order: bool
    phase_to_marker: tuple[tuple[str, str], ...]
    latest_phase_rule: tuple[tuple[RecordCode, str], ...]

    def resolved_phase(self, binding_order: RecordCode | None) -> str:
        if self.latest_phase:
            return self.latest_phase
        if self.phase_source_is_route_binding_order and binding_order is not None:
            return dict(self.latest_phase_rule).get(binding_order, "")
        return ""

    def marker_for(self, phase: str) -> str:
        return dict(self.phase_to_marker).get(phase, "")

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class FrozenRecordMapping:
    items: tuple[tuple[str, Any], ...]


def _freeze_record_value(value: Any) -> Any:
    if isinstance(value, dict):
        return FrozenRecordMapping(
            tuple(
                (str(key), _freeze_record_value(child))
                for key, child in sorted(value.items(), key=lambda item: str(item[0]))
            )
        )
    if isinstance(value, list):
        return tuple(_freeze_record_value(child) for child in value)
    return value


def _thaw_record_value(value: Any) -> Any:
    if isinstance(value, FrozenRecordMapping):
        return {key: _thaw_record_value(child) for key, child in value.items}
    if isinstance(value, tuple):
        return [_thaw_record_value(child) for child in value]
    return value


@dataclass(frozen=True)
class MemoryRecallValue:
    memory_key: str
    person: str
    memory_class: MemoryClass
    fields: tuple[tuple[str, Any], ...]

    def field(self, key: str, default: Any = None) -> Any:
        value = dict(self.fields).get(key, default)
        return _thaw_record_value(value)

    def as_request(self) -> dict[str, Any]:
        return {key: _thaw_record_value(value) for key, value in self.fields}

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class MemoryWriteValue:
    fields: tuple[tuple[str, Any], ...] = ()
    alias: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {key: _thaw_record_value(value) for key, value in self.fields}

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


@dataclass(frozen=True)
class UnknownRecordValue:
    value_kind: str
    fingerprint: str

    @property
    def object_references(self) -> tuple[str, ...]:
        return ()


RecordSemanticValue = (
    PresenceValue
    | CategoricalValue
    | ReferenceValue
    | TargetChangeValue
    | DurationValue
    | MarkerRefsValue
    | FocalResolutionTraceValue
    | MemoryRecallValue
    | MemoryWriteValue
    | UnknownRecordValue
)


@dataclass(frozen=True)
class TypedRecordFact:
    fact_id: str
    record_type: RecordType
    source_type: str
    status: FactStatus
    semantic_value: RecordSemanticValue | None
    role: FactRole
    adapter_id: str
    conflict_key: str
    chronology: ChronologyKey | None
    provenance: Provenance | None
    issues: tuple[str, ...] = ()
    derived_from: tuple[str, ...] = ()

    @property
    def is_present(self) -> bool:
        return self.status == FactStatus.PRESENT

    @property
    def code(self) -> RecordCode | None:
        value = self.semantic_value
        return value.code if isinstance(value, CategoricalValue) else None

    @property
    def reference(self) -> str:
        value = self.semantic_value
        return value.reference if isinstance(value, ReferenceValue) else ""

    @property
    def object_references(self) -> tuple[str, ...]:
        value = self.semantic_value
        return value.object_references if value is not None else ()

    def to_trace(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "record_type": self.record_type.value,
            "source_type": self.source_type,
            "status": self.status.value,
            "semantic_kind": type(self.semantic_value).__name__
            if self.semantic_value is not None
            else "none",
            "role": self.role.value,
            "adapter_id": self.adapter_id,
            "chronology": self.chronology.to_trace()
            if self.chronology is not None
            else None,
            "issues": list(self.issues),
            "derived_from": list(self.derived_from),
        }


# Compatibility name retained as a type alias, not a second fact model.
RecordFact = TypedRecordFact


RECORD_ROLES = {
    RecordType.CURRENT_REQUEST_HINT: FactRole.HINT,
    RecordType.FOCAL_MARKER_REFS: FactRole.RELATION,
    RecordType.FOCAL_RESOLUTION_TRACE: FactRole.RELATION,
    RecordType.RESOLVED_TARGET: FactRole.RELATION,
    RecordType.TARGET_CHANGED_AFTER_TURN: FactRole.RELATION,
    RecordType.ROUTE_BINDING_ORDER: FactRole.RELATION,
    RecordType.ROUTE_CANDIDATE_SNAPSHOT: FactRole.RELATION,
    RecordType.DISPATCH_AUTHORITY_CHECK: FactRole.RELATION,
    RecordType.SHARE_BOUNDARY_UPDATE: FactRole.RELATION,
    RecordType.PERSISTENT_MEMORY_WRITE: FactRole.MEMORY,
    RecordType.PERSISTENT_MEMORY_RECALL: FactRole.MEMORY,
    RecordType.OPS_MEMORY_RECALL: FactRole.MEMORY,
    RecordType.ENTERPRISE_POLICY_RECALL: FactRole.MEMORY,
    RecordType.TRUSTED_SUBSCRIPTION: FactRole.CAPABILITY_MODIFIER,
    RecordType.GUEST_MODE: FactRole.CAPABILITY_MODIFIER,
    RecordType.VERIFIED_INTERNAL_TARGET: FactRole.CAPABILITY_MODIFIER,
}

for _record_type in (
    RecordType.AMBIGUOUS_FOCAL,
    RecordType.AMBIGUOUS_TARGET,
    RecordType.AMOUNT_CHANGED,
    RecordType.CALENDAR_CONFLICT,
    RecordType.CONSENT,
    RecordType.DURATION_AMBIGUOUS,
    RecordType.EXTERNAL_SHARE_POLICY,
    RecordType.GUARDRAIL_LADDER_SIGNAL,
    RecordType.HEALTH_SHARE_POLICY,
    RecordType.MEMORY_CONFLICT,
    RecordType.MERCHANT_VERIFICATION,
    RecordType.PAYMENT_POLICY,
    RecordType.PRIVACY_GUARD,
    RecordType.SAFETY_MODE,
    RecordType.SECURITY_ALERT,
    RecordType.SESSION_SHARE_POLICY,
    RecordType.ROUTINE_SCOPE,
    RecordType.TEMPORARY_OVERRIDE_ALLOWED,
):
    RECORD_ROLES.setdefault(_record_type, FactRole.CONSTRAINT)


def stable_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(value)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(stable_value(value).encode("utf-8")).hexdigest()


def _fact_id(raw_record: Any, source_type: str) -> str:
    if isinstance(raw_record, Mapping) and raw_record.get("id"):
        return f"record:{str(raw_record['id'])}"
    return f"record:{source_type or 'invalid'}:{_fingerprint(raw_record)[:16]}"


def _strict_json_fields(value: dict[str, Any]) -> tuple[tuple[str, Any], ...] | None:
    try:
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return None
    return tuple(
        (str(key), _freeze_record_value(child))
        for key, child in sorted(value.items(), key=lambda item: str(item[0]))
    )


class RecordAdapter(ABC):
    supported_record_type: RecordType
    validation_rules: tuple[str, ...]
    unknown_value_policy: UnknownValuePolicy
    contract_status = ContractStatus.SUPPORTED_INTERPRETATION
    basis_refs = ("TERMS_GUIDE.md#device-state-records",)
    assumption_refs: tuple[str, ...] = ()

    @property
    def adapter_id(self) -> str:
        return f"record_adapter:{self.supported_record_type.value}"

    @abstractmethod
    def parse(
        self,
        raw_record: Any,
        *,
        session_id: str = "",
    ) -> TypedRecordFact:
        raise NotImplementedError

    def conflict_key(self, raw_record: Mapping[str, Any]) -> str:
        return _fingerprint(raw_record.get("value"))

    def chronology_key(self, raw_record: Mapping[str, Any]) -> ChronologyKey | None:
        found: list[ChronologyKey] = []
        for domain in ChronologyDomain:
            if domain.value not in raw_record or raw_record.get(domain.value) is None:
                continue
            parsed = self._parse_chronology(domain, raw_record.get(domain.value))
            if parsed is None:
                return None
            found.append(parsed)
        return found[0] if len(found) == 1 else None

    @staticmethod
    def _parse_chronology(
        domain: ChronologyDomain,
        raw_value: Any,
    ) -> ChronologyKey | None:
        if domain in {ChronologyDomain.TURN_INDEX, ChronologyDomain.TURN}:
            if isinstance(raw_value, bool):
                return None
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                return None
            if str(raw_value).strip() != str(value) and not isinstance(raw_value, int):
                return None
            return ChronologyKey(domain, ChronologyKind.INTEGER, value)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        try:
            value = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        kind = (
            ChronologyKind.ISO_DATETIME_OFFSET
            if value.utcoffset() is not None
            else ChronologyKind.ISO_DATETIME_LOCAL
        )
        return ChronologyKey(domain, kind, value)

    def _base_fact(
        self,
        raw_record: Mapping[str, Any],
        *,
        session_id: str,
        status: FactStatus,
        semantic_value: RecordSemanticValue | None,
        issues: tuple[str, ...] = (),
    ) -> TypedRecordFact:
        source_type = str(raw_record.get("type") or "")
        fact_id = _fact_id(raw_record, source_type)
        chronology = self.chronology_key(raw_record)
        chronology_fields = [
            domain.value
            for domain in ChronologyDomain
            if domain.value in raw_record and raw_record.get(domain.value) is not None
        ]
        chronology_issues: tuple[str, ...] = ()
        if len(chronology_fields) > 1:
            chronology_issues = ("multiple_chronology_domains",)
        elif chronology_fields and chronology is None:
            chronology_issues = ("invalid_chronology_value",)
        if chronology_issues:
            status = FactStatus.INVALID
        turn = None
        if chronology is not None and chronology.domain in {
            ChronologyDomain.TURN_INDEX,
            ChronologyDomain.TURN,
        }:
            assert isinstance(chronology.value, int)
            turn = chronology.value
        return TypedRecordFact(
            fact_id=fact_id,
            record_type=self.supported_record_type,
            source_type=source_type,
            status=status,
            semantic_value=semantic_value,
            role=RECORD_ROLES.get(self.supported_record_type, FactRole.STATE),
            adapter_id=self.adapter_id,
            conflict_key=self.conflict_key(raw_record),
            chronology=chronology,
            provenance=Provenance(
                source_kind="record",
                source_id=fact_id.removeprefix("record:"),
                session_id=session_id,
                turn=turn,
            ),
            issues=tuple(dict.fromkeys(issues + chronology_issues)),
        )


class PresenceRecordAdapter(RecordAdapter):
    validation_rules = ("value must be non-empty JSON data",)
    unknown_value_policy = UnknownValuePolicy.ACCEPT_PRESENCE

    def __init__(self, record_type: RecordType) -> None:
        self.supported_record_type = record_type

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        try:
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            valid = value not in (None, "", [], {})
        except (TypeError, ValueError):
            valid = False
        if not valid:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("expected_nonempty_json_value",),
            )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=PresenceValue(self.supported_record_type),
        )


class CategoricalRecordAdapter(RecordAdapter):
    validation_rules = ("value must match the record-specific structured vocabulary",)
    unknown_value_policy = UnknownValuePolicy.MARK_UNKNOWN

    def __init__(
        self,
        record_type: RecordType,
        allowed_codes: Iterable[RecordCode],
    ) -> None:
        self.supported_record_type = record_type
        self._allowed = {code.value: code for code in allowed_codes}

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        code = self._allowed.get(value) if isinstance(value, str) else None
        if code is None:
            status = (
                FactStatus.UNKNOWN if isinstance(value, str) else FactStatus.INVALID
            )
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=status,
                semantic_value=UnknownRecordValue(
                    type(value).__name__, _fingerprint(value)
                ),
                issues=("unknown_categorical_value",)
                if status == FactStatus.UNKNOWN
                else ("categorical_value_not_string",),
            )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=CategoricalValue(code),
        )


class ReferenceRecordAdapter(RecordAdapter):
    validation_rules = ("value must be a non-empty reference string",)
    unknown_value_policy = UnknownValuePolicy.ACCEPT_REFERENCE

    def __init__(self, record_type: RecordType) -> None:
        self.supported_record_type = record_type

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        if not isinstance(value, str) or not value:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("reference_value_not_string",),
            )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=ReferenceValue(value),
        )


class ConsentRecordAdapter(CategoricalRecordAdapter):
    def __init__(self) -> None:
        super().__init__(
            RecordType.CONSENT,
            (RecordCode.CONSENT_GRANTED, RecordCode.CONSENT_REVOKED),
        )

    def conflict_key(self, raw_record: Mapping[str, Any]) -> str:
        value = raw_record.get("value")
        if isinstance(value, Mapping):
            value = value.get("status")
        return _fingerprint(value)

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if isinstance(raw_record, Mapping) and isinstance(
            raw_record.get("value"), Mapping
        ):
            copied = dict(raw_record)
            copied["value"] = raw_record["value"].get("status")
            fact = super().parse(copied, session_id=session_id)
            return replace(fact, conflict_key=self.conflict_key(raw_record))
        return super().parse(raw_record, session_id=session_id)


class TargetChangeRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.TARGET_CHANGED_AFTER_TURN
    validation_rules = (
        "value is a replacement target or an explicit supersession marker",
    )
    unknown_value_policy = UnknownValuePolicy.ACCEPT_REFERENCE
    _SUPERSEDED = "prior_success_route_superseded"

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        if not isinstance(value, str) or not value:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("target_change_value_not_string",),
            )
        semantic = (
            TargetChangeValue(prior_route_superseded=True)
            if value == self._SUPERSEDED
            else TargetChangeValue(replacement_target=value)
        )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=semantic,
        )


class DurationRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.TEMPORARY_OVERRIDE_ALLOWED
    validation_rules = ("value must be an integer duration with s, m, h, or d unit",)
    unknown_value_policy = UnknownValuePolicy.MARK_UNKNOWN
    _PATTERN = re.compile(r"^(0|[1-9][0-9]*)(s|m|h|d)$")

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        match = self._PATTERN.fullmatch(value) if isinstance(value, str) else None
        if match is None:
            status = (
                FactStatus.UNKNOWN if isinstance(value, str) else FactStatus.INVALID
            )
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=status,
                semantic_value=UnknownRecordValue(
                    type(value).__name__, _fingerprint(value)
                ),
                issues=("unknown_duration_format",),
            )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=DurationValue(int(match.group(1)), match.group(2)),
        )


class MarkerRefsRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.FOCAL_MARKER_REFS
    validation_rules = (
        "value.marker_to_ref must map non-empty marker IDs to reference IDs",
    )
    unknown_value_policy = UnknownValuePolicy.REJECT_INVALID

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        mapping = value.get("marker_to_ref") if isinstance(value, Mapping) else None
        if not isinstance(mapping, Mapping) or not all(
            isinstance(key, str) and key and isinstance(reference, str) and reference
            for key, reference in mapping.items()
        ):
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("invalid_marker_to_ref",),
            )
        semantic = MarkerRefsValue(tuple(sorted(mapping.items())))
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=semantic,
        )


class FocalResolutionTraceRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.FOCAL_RESOLUTION_TRACE
    validation_rules = (
        "phase_to_marker must be a string mapping",
        "latest_phase_rule keys must be known route-binding codes",
    )
    unknown_value_policy = UnknownValuePolicy.REJECT_INVALID

    _ROUTE_CODES = {
        code.value: code
        for code in (
            RecordCode.ROUTE_AUTHORITY_AFTER_CANDIDATES,
            RecordCode.ROUTE_AUTHORITY_AFTER_BOUNDARY,
            RecordCode.ROUTE_BOUNDARY_AFTER_AUTHORITY,
            RecordCode.ROUTE_CANDIDATES_AFTER_AUTHORITY,
        )
    }

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        if not isinstance(value, Mapping):
            return self._invalid(raw_record, session_id, "trace_value_not_mapping")
        phase_to_marker = value.get("phase_to_marker")
        rules = value.get("latest_phase_rule", {})
        if not isinstance(phase_to_marker, Mapping) or not all(
            isinstance(key, str) and key and isinstance(marker, str) and marker
            for key, marker in phase_to_marker.items()
        ):
            return self._invalid(raw_record, session_id, "invalid_phase_to_marker")
        if not isinstance(rules, Mapping):
            return self._invalid(raw_record, session_id, "invalid_latest_phase_rule")
        typed_rules: list[tuple[RecordCode, str]] = []
        for raw_code, phase in rules.items():
            code = self._ROUTE_CODES.get(raw_code)
            if code is None:
                if raw_code == "fallback":
                    continue
                return self._invalid(
                    raw_record, session_id, "unknown_route_binding_rule"
                )
            if not isinstance(phase, str) or not phase:
                return self._invalid(raw_record, session_id, "invalid_route_phase")
            typed_rules.append((code, phase))
        latest_phase = value.get("latest_phase", "")
        phase_source = value.get("phase_source", "")
        if not isinstance(latest_phase, str) or not isinstance(phase_source, str):
            return self._invalid(raw_record, session_id, "invalid_trace_scalar")
        semantic = FocalResolutionTraceValue(
            latest_phase=latest_phase,
            phase_source_is_route_binding_order=phase_source == "route_binding_order",
            phase_to_marker=tuple(sorted(phase_to_marker.items())),
            latest_phase_rule=tuple(
                sorted(typed_rules, key=lambda item: item[0].value)
            ),
        )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=semantic,
        )

    def _invalid(
        self,
        raw_record: Mapping[str, Any],
        session_id: str,
        issue: str,
    ) -> TypedRecordFact:
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.INVALID,
            semantic_value=None,
            issues=(issue,),
        )


class MemoryRecallRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.PERSISTENT_MEMORY_RECALL
    validation_rules = ("value must be a mapping with a non-empty memory_key",)
    unknown_value_policy = UnknownValuePolicy.REJECT_INVALID

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        if not isinstance(value, dict):
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("memory_recall_not_mapping",),
            )
        memory_key = value.get("memory_key")
        if not isinstance(memory_key, str) or not memory_key:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("memory_key_missing",),
            )
        raw_class = value.get("memory_class")
        if raw_class in {None, ""}:
            memory_class = MemoryClass.UNSPECIFIED
        else:
            try:
                memory_class = MemoryClass.parse(str(raw_class))
            except ValueError:
                return self._base_fact(
                    raw_record,
                    session_id=session_id,
                    status=FactStatus.UNKNOWN,
                    semantic_value=UnknownRecordValue(
                        type(value).__name__, _fingerprint(value)
                    ),
                    issues=("unknown_memory_class",),
                )
        fields = _strict_json_fields(value)
        if fields is None:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("memory_recall_not_json",),
            )
        semantic = MemoryRecallValue(
            memory_key=memory_key,
            person=str(value.get("person") or ""),
            memory_class=memory_class,
            fields=fields,
        )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=semantic,
        )


class MemoryWriteRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.PERSISTENT_MEMORY_WRITE
    validation_rules = ("value must be a JSON mapping or a non-empty memory alias",)
    unknown_value_policy = UnknownValuePolicy.REJECT_INVALID

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        value = raw_record.get("value")
        semantic: MemoryWriteValue | None = None
        if isinstance(value, dict):
            fields = _strict_json_fields(value)
            if fields is not None:
                semantic = MemoryWriteValue(fields=fields)
        elif isinstance(value, str) and value:
            semantic = MemoryWriteValue(alias=value)
        if semantic is None:
            return self._base_fact(
                raw_record,
                session_id=session_id,
                status=FactStatus.INVALID,
                semantic_value=None,
                issues=("invalid_memory_write",),
            )
        return self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.PRESENT,
            semantic_value=semantic,
        )


class UnknownRecordAdapter(RecordAdapter):
    supported_record_type = RecordType.UNKNOWN
    validation_rules = ("unknown record types are preserved without interpretation",)
    unknown_value_policy = UnknownValuePolicy.MARK_UNKNOWN

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        if not isinstance(raw_record, Mapping):
            return _invalid_record(raw_record, session_id=session_id)
        source_type = str(raw_record.get("type") or "")
        value = raw_record.get("value")
        fact = self._base_fact(
            raw_record,
            session_id=session_id,
            status=FactStatus.UNKNOWN if source_type else FactStatus.INVALID,
            semantic_value=UnknownRecordValue(
                type(value).__name__, _fingerprint(value)
            ),
            issues=("unknown_record_type",)
            if source_type
            else ("missing_record_type",),
        )
        return replace(fact, source_type=source_type)


def _invalid_record(raw_record: Any, *, session_id: str) -> TypedRecordFact:
    fact_id = _fact_id(raw_record, "")
    return TypedRecordFact(
        fact_id=fact_id,
        record_type=RecordType.UNKNOWN,
        source_type="",
        status=FactStatus.INVALID,
        semantic_value=UnknownRecordValue(
            type(raw_record).__name__, _fingerprint(raw_record)
        ),
        role=FactRole.UNKNOWN,
        adapter_id="record_adapter:invalid",
        conflict_key=_fingerprint(raw_record),
        chronology=None,
        provenance=Provenance(
            "record",
            fact_id.removeprefix("record:"),
            session_id,
        ),
        issues=("record_not_mapping",),
    )


class RecordAdapterRegistry:
    def __init__(self, adapters: Iterable[RecordAdapter]) -> None:
        self._adapters: dict[RecordType, RecordAdapter] = {}
        for adapter in adapters:
            if adapter.supported_record_type in self._adapters:
                raise ValueError(
                    f"duplicate RecordAdapter: {adapter.supported_record_type.value}"
                )
            self._adapters[adapter.supported_record_type] = adapter
        self._unknown = UnknownRecordAdapter()

    def adapter_for(self, source_type: str) -> RecordAdapter:
        try:
            record_type = RecordType.parse(source_type)
        except ValueError:
            return self._unknown
        return self._adapters.get(record_type, self._unknown)

    def parse(self, raw_record: Any, *, session_id: str = "") -> TypedRecordFact:
        source_type = (
            str(raw_record.get("type") or "") if isinstance(raw_record, Mapping) else ""
        )
        return self.adapter_for(source_type).parse(
            raw_record,
            session_id=session_id,
        )

    @property
    def adapters(self) -> tuple[RecordAdapter, ...]:
        return tuple(
            self._adapters[key]
            for key in sorted(self._adapters, key=lambda item: item.value)
        )

    def validate(self) -> None:
        expected = set(RecordType) - {RecordType.UNKNOWN}
        actual = set(self._adapters)
        if actual != expected:
            missing = sorted(item.value for item in expected - actual)
            extra = sorted(item.value for item in actual - expected)
            raise ValueError(
                f"RecordAdapter coverage mismatch: missing={missing}, extra={extra}"
            )
        for adapter in self.adapters:
            if not adapter.validation_rules:
                raise ValueError(
                    f"adapter has no validation rules: {adapter.adapter_id}"
                )
            if not isinstance(adapter.contract_status, ContractStatus):
                raise ValueError(
                    f"adapter has invalid contract status: {adapter.adapter_id}"
                )
            if not adapter.basis_refs:
                raise ValueError(
                    f"adapter has no basis reference: {adapter.adapter_id}"
                )


def _categorical(
    record_type: RecordType,
    *codes: RecordCode,
) -> CategoricalRecordAdapter:
    return CategoricalRecordAdapter(record_type, codes)


RECORD_ADAPTER_REGISTRY = RecordAdapterRegistry(
    (
        PresenceRecordAdapter(RecordType.AMBIGUOUS_FOCAL),
        _categorical(
            RecordType.AMBIGUOUS_TARGET,
            RecordCode.AMBIGUOUS_APPROVED_OR_VISIBLE,
            RecordCode.AMBIGUOUS_RECENT_SURFACE_OR_RESOLVED,
            RecordCode.AMBIGUOUS_STORED_OR_VISIBLE,
        ),
        PresenceRecordAdapter(RecordType.AMOUNT_CHANGED),
        PresenceRecordAdapter(RecordType.CALENDAR_CONFLICT),
        ConsentRecordAdapter(),
        PresenceRecordAdapter(RecordType.CURRENT_REQUEST_HINT),
        _categorical(
            RecordType.DISPATCH_AUTHORITY_CHECK,
            RecordCode.AUTHORITY_INCOMPLETE,
            RecordCode.AUTHORITY_INTERNAL_CONFIRMED,
            RecordCode.AUTHORITY_LOCAL_CONFIRMED,
            RecordCode.AUTHORITY_USER_PENDING,
        ),
        PresenceRecordAdapter(RecordType.DURATION_AMBIGUOUS),
        _categorical(
            RecordType.ENTERPRISE_POLICY_RECALL,
            RecordCode.ENTERPRISE_APPLY_STANDING_DEFAULT,
        ),
        _categorical(
            RecordType.EXTERNAL_SHARE_POLICY,
            RecordCode.EXTERNAL_DOCTOR_NOTE_FORBIDDEN,
            RecordCode.EXTERNAL_RAW_QUOTE_FORBIDDEN,
            RecordCode.EXTERNAL_RAW_SENSITIVE_FORBIDDEN,
            RecordCode.EXTERNAL_SUMMARY_ONLY,
        ),
        MarkerRefsRecordAdapter(),
        FocalResolutionTraceRecordAdapter(),
        PresenceRecordAdapter(RecordType.GUARDRAIL_LADDER_SIGNAL),
        PresenceRecordAdapter(RecordType.GUEST_MODE),
        PresenceRecordAdapter(RecordType.HEALTH_SHARE_POLICY),
        PresenceRecordAdapter(RecordType.MEMORY_CONFLICT),
        PresenceRecordAdapter(RecordType.MERCHANT_VERIFICATION),
        _categorical(
            RecordType.OPS_MEMORY_RECALL,
            RecordCode.OPS_USE_PRIOR_RESULTS,
        ),
        PresenceRecordAdapter(RecordType.PAYMENT_POLICY),
        MemoryRecallRecordAdapter(),
        MemoryWriteRecordAdapter(),
        PresenceRecordAdapter(RecordType.PRIVACY_GUARD),
        ReferenceRecordAdapter(RecordType.RESOLVED_TARGET),
        _categorical(
            RecordType.ROUTE_BINDING_ORDER,
            RecordCode.ROUTE_AUTHORITY_AFTER_CANDIDATES,
            RecordCode.ROUTE_AUTHORITY_AFTER_BOUNDARY,
            RecordCode.ROUTE_BOUNDARY_AFTER_AUTHORITY,
            RecordCode.ROUTE_CANDIDATES_AFTER_AUTHORITY,
        ),
        _categorical(
            RecordType.ROUTE_CANDIDATE_SNAPSHOT,
            RecordCode.CANDIDATES_EXTERNAL_PRESENT,
            RecordCode.CANDIDATES_LOCAL_ONLY,
            RecordCode.CANDIDATES_MIXED,
            RecordCode.CANDIDATES_SINGLE_INTERNAL,
        ),
        PresenceRecordAdapter(RecordType.ROUTINE_SCOPE),
        PresenceRecordAdapter(RecordType.SAFETY_MODE),
        PresenceRecordAdapter(RecordType.SECURITY_ALERT),
        _categorical(
            RecordType.SESSION_SHARE_POLICY,
            RecordCode.SESSION_POLICY_NORMAL,
            RecordCode.SESSION_POLICY_STRICT,
        ),
        _categorical(
            RecordType.SHARE_BOUNDARY_UPDATE,
            RecordCode.SHARE_BOUNDARY_BLOCKED,
            RecordCode.SHARE_BOUNDARY_LOCAL,
            RecordCode.SHARE_BOUNDARY_REDACTED_AFTER_SELECTION,
            RecordCode.SHARE_BOUNDARY_REDACTED_EXTERNAL,
        ),
        TargetChangeRecordAdapter(),
        DurationRecordAdapter(),
        ReferenceRecordAdapter(RecordType.TRUSTED_SUBSCRIPTION),
        PresenceRecordAdapter(RecordType.VERIFIED_INTERNAL_TARGET),
    )
)


class RecordIndex:
    """Order-independent typed record access with explicit fact states."""

    def __init__(
        self,
        records: Iterable[Any],
        *,
        session_id: str = "",
        registry: RecordAdapterRegistry = RECORD_ADAPTER_REGISTRY,
    ) -> None:
        registry.validate()
        parsed = [registry.parse(record, session_id=session_id) for record in records]
        self._facts = tuple(sorted(parsed, key=self._fact_sort_key))
        by_type: dict[str, list[TypedRecordFact]] = defaultdict(list)
        for fact in self._facts:
            by_type[fact.source_type].append(fact)
        self._by_type = {
            record_type: tuple(facts) for record_type, facts in by_type.items()
        }
        self._resolved = {
            record_type: self._resolve(record_type, facts)
            for record_type, facts in self._by_type.items()
        }

    @property
    def facts(self) -> tuple[TypedRecordFact, ...]:
        return self._facts

    @property
    def resolved_facts(self) -> tuple[TypedRecordFact, ...]:
        return tuple(self._resolved[key] for key in sorted(self._resolved))

    def facts_of_type(
        self,
        record_type: RecordType | str,
    ) -> tuple[TypedRecordFact, ...]:
        key = (
            record_type.value
            if isinstance(record_type, RecordType)
            else str(record_type)
        )
        return self._by_type.get(key, ())

    def fact(self, record_type: RecordType | str) -> TypedRecordFact:
        key = (
            record_type.value
            if isinstance(record_type, RecordType)
            else str(record_type)
        )
        if key in self._resolved:
            return self._resolved[key]
        try:
            typed = RecordType.parse(key)
        except ValueError:
            typed = RecordType.UNKNOWN
        return TypedRecordFact(
            fact_id=f"record:missing:{key}",
            record_type=typed,
            source_type=key,
            status=FactStatus.MISSING,
            semantic_value=None,
            role=RECORD_ROLES.get(typed, FactRole.UNKNOWN),
            adapter_id=f"record_adapter:{key}",
            conflict_key="",
            chronology=None,
            provenance=None,
            issues=("record_missing",),
        )

    def is_conflicting(self, record_type: RecordType | str) -> bool:
        return self.fact(record_type).status == FactStatus.CONFLICTED

    def conflicting_types(self) -> set[str]:
        return {
            record_type
            for record_type, fact in self._resolved.items()
            if fact.status == FactStatus.CONFLICTED
        }

    def unknown_facts(self) -> tuple[TypedRecordFact, ...]:
        return tuple(
            fact
            for fact in self._facts
            if fact.status in {FactStatus.UNKNOWN, FactStatus.INVALID}
        )

    def to_trace(self) -> dict[str, Any]:
        statuses: dict[str, int] = defaultdict(int)
        for fact in self.resolved_facts:
            statuses[fact.status.value] += 1
        return {
            "fact_count": len(self._facts),
            "resolved_fact_count": len(self._resolved),
            "status_counts": dict(sorted(statuses.items())),
            "conflicting_types": sorted(self.conflicting_types()),
            "unknown_or_invalid": [fact.to_trace() for fact in self.unknown_facts()],
        }

    @classmethod
    def _resolve(
        cls,
        source_type: str,
        facts: tuple[TypedRecordFact, ...],
    ) -> TypedRecordFact:
        if len(facts) == 1:
            return facts[0]
        derived_from = tuple(sorted(fact.fact_id for fact in facts))
        statuses = {fact.status for fact in facts}
        if FactStatus.INVALID in statuses:
            return cls._aggregate_status(
                source_type,
                facts,
                FactStatus.INVALID,
                "invalid_duplicate_record",
            )
        keys = {fact.conflict_key for fact in facts}
        if len(keys) == 1:
            selected = min(facts, key=cls._fact_sort_key)
            status = (
                FactStatus.UNKNOWN
                if FactStatus.UNKNOWN in statuses
                else selected.status
            )
            return replace(
                selected,
                status=status,
                provenance=None,
                derived_from=derived_from,
            )
        if FactStatus.UNKNOWN in statuses:
            return cls._aggregate_status(
                source_type,
                facts,
                FactStatus.CONFLICTED,
                "unknown_duplicate_values_disagree",
            )

        chronology = [fact.chronology for fact in facts]
        if any(key is None for key in chronology):
            return cls._aggregate_status(
                source_type,
                facts,
                FactStatus.CONFLICTED,
                "duplicate_values_without_common_chronology",
            )
        assert all(key is not None for key in chronology)
        typed_chronology = [key for key in chronology if key is not None]
        domains = {(key.domain, key.kind) for key in typed_chronology}
        if len(domains) != 1:
            return cls._aggregate_status(
                source_type,
                facts,
                FactStatus.CONFLICTED,
                "incomparable_chronology_domains",
            )
        top_key = typed_chronology[0]
        for candidate in typed_chronology[1:]:
            if candidate.compare(top_key) > 0:
                top_key = candidate
        top = [fact for fact in facts if fact.chronology == top_key]
        if len({fact.conflict_key for fact in top}) != 1:
            return cls._aggregate_status(
                source_type,
                facts,
                FactStatus.CONFLICTED,
                "latest_chronology_tie_conflict",
            )
        selected = min(top, key=cls._fact_sort_key)
        return replace(selected, provenance=None, derived_from=derived_from)

    @staticmethod
    def _aggregate_status(
        source_type: str,
        facts: tuple[TypedRecordFact, ...],
        status: FactStatus,
        issue: str,
    ) -> TypedRecordFact:
        selected = min(facts, key=RecordIndex._fact_sort_key)
        return TypedRecordFact(
            fact_id=f"record:{status.value}:{source_type}",
            record_type=selected.record_type,
            source_type=source_type,
            status=status,
            semantic_value=None,
            role=selected.role,
            adapter_id=selected.adapter_id,
            conflict_key="",
            chronology=None,
            provenance=None,
            issues=(issue,),
            derived_from=tuple(sorted(fact.fact_id for fact in facts)),
        )

    @staticmethod
    def _fact_sort_key(fact: TypedRecordFact) -> tuple[str, str, str, str]:
        return (
            fact.source_type,
            fact.fact_id,
            fact.conflict_key,
            fact.status.value,
        )


def validate_record_adapter_registry() -> None:
    RECORD_ADAPTER_REGISTRY.validate()
