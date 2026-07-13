from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Self


class StrictSemanticEnum(str, Enum):
    @classmethod
    def parse(cls, value: str) -> Self:
        try:
            return cls(value)
        except ValueError as exc:
            raise ValueError(f"unknown {cls.__name__}: {value!r}") from exc


class Domain(StrictSemanticEnum):
    PAYMENT = "payment"
    DEVICE = "device_control"
    CALENDAR = "calendar"
    MEMORY = "memory"
    CONTENT = "content"
    GENERAL = "general"
    UNKNOWN = "none"


class Operation(StrictSemanticEnum):
    EXECUTE = "execute"
    CREATE = "create"
    MODIFY = "modify"
    CANCEL = "cancel"
    VERIFY = "verify"
    SHARE = "share"
    STORE = "store"
    DELETE = "delete"
    CLARIFY = "clarify"
    STOP = "stop"
    LOCAL_UPDATE = "local_update"
    UNRESOLVED = "unresolved"


class TargetRole(StrictSemanticEnum):
    DISPATCH_DESTINATION = "dispatch_destination"
    LOCAL_RESOURCE = "local_resource"
    MERCHANT = "merchant"
    DEVICE_TARGET = "device_target"
    CALENDAR_TARGET = "calendar_target"
    CLARIFICATION_TARGET = "clarification_target"
    OPERATION_TARGET = "operation_target"
    MEMORY_OWNER = "memory_owner"
    CONFIRMATION_AUTHORITY = "confirmation_authority"
    UNRESOLVED = "unresolved"


class TargetLocality(StrictSemanticEnum):
    LOCAL = "local"
    EXTERNAL = "external"
    DOMAIN = "domain"
    INTERACTION = "interaction"
    UNKNOWN = "unknown"


class ObjectType(StrictSemanticEnum):
    FILE = "file"
    GALLERY_ITEM = "gallery_item"
    MESSAGE = "message"
    PERSONAL_NOTE = "personal_note"
    HEALTH_RECORD = "health_record"
    PAYMENT_REQUEST = "payment_request"
    DEVICE_SETTING = "device_setting"
    IOT_ROUTINE = "iot_routine"
    CALENDAR_EVENT = "calendar_event"
    UNKNOWN = "unknown"


class RecordType(StrictSemanticEnum):
    AMBIGUOUS_FOCAL = "ambiguous_focal"
    AMBIGUOUS_TARGET = "ambiguous_target"
    AMOUNT_CHANGED = "amount_changed"
    CALENDAR_CONFLICT = "calendar_conflict"
    CONSENT = "consent"
    CURRENT_REQUEST_HINT = "current_request_hint"
    DISPATCH_AUTHORITY_CHECK = "dispatch_authority_check"
    DURATION_AMBIGUOUS = "duration_ambiguous"
    ENTERPRISE_POLICY_RECALL = "enterprise_policy_recall"
    EXTERNAL_SHARE_POLICY = "external_share_policy"
    FOCAL_MARKER_REFS = "focal_marker_refs"
    FOCAL_RESOLUTION_TRACE = "focal_resolution_trace"
    GUARDRAIL_LADDER_SIGNAL = "guardrail_ladder_signal"
    GUEST_MODE = "guest_mode"
    HEALTH_SHARE_POLICY = "health_share_policy"
    MEMORY_CONFLICT = "memory_conflict"
    MERCHANT_VERIFICATION = "merchant_verification"
    OPS_MEMORY_RECALL = "ops_memory_recall"
    PAYMENT_POLICY = "payment_policy"
    PERSISTENT_MEMORY_RECALL = "persistent_memory_recall"
    PERSISTENT_MEMORY_WRITE = "persistent_memory_write"
    PRIVACY_GUARD = "privacy_guard"
    RESOLVED_TARGET = "resolved_target"
    ROUTE_BINDING_ORDER = "route_binding_order"
    ROUTE_CANDIDATE_SNAPSHOT = "route_candidate_snapshot"
    ROUTINE_SCOPE = "routine_scope"
    SAFETY_MODE = "safety_mode"
    SECURITY_ALERT = "security_alert"
    SESSION_SHARE_POLICY = "session_share_policy"
    SHARE_BOUNDARY_UPDATE = "share_boundary_update"
    TARGET_CHANGED_AFTER_TURN = "target_changed_after_turn"
    TEMPORARY_OVERRIDE_ALLOWED = "temporary_override_allowed"
    TRUSTED_SUBSCRIPTION = "trusted_subscription"
    VERIFIED_INTERNAL_TARGET = "verified_internal_target"
    UNKNOWN = "unknown"


class FactStatus(StrictSemanticEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"
    CONFLICTED = "conflicted"
    INVALID = "invalid"
    NOT_APPLICABLE = "not_applicable"


class InformationSlot(StrictSemanticEnum):
    OPERATION = "operation"
    OPERATION_REFERENCE = "operation_reference"
    MERCHANT = "merchant"
    AMOUNT = "amount"
    METHOD = "method"
    DEVICE_TARGET = "device_target"
    DESIRED_STATE = "desired_state"
    EVENT = "event"
    TIME = "time"
    DURATION = "duration"
    RECIPIENT = "recipient"
    LOCAL_RESOURCE = "local_resource"
    CLARIFICATION_TARGET = "clarification_target"
    DESTINATION = "destination"
    CONTENT_SCOPE = "content_scope"
    MEMORY_VALUE = "memory_value"


class InformationStatus(StrictSemanticEnum):
    COMPLETE = "complete"
    MISSING = "missing"
    CONFLICT = "conflict"


class CandidateState(StrictSemanticEnum):
    VIABLE = "executable"
    EXECUTABLE = "executable"  # compatibility alias
    NEEDS_INFORMATION = "needs_information"
    NEEDS_CONFIRMATION = "needs_clarification"
    NEEDS_CLARIFICATION = "needs_clarification"  # compatibility alias
    AMENDABLE = "amendable"
    BLOCKED = "blocked"
    CONFLICTED = "conflicted"
    REJECTED = "rejected"
    UNSUPPORTED_RULEPACK = "unsupported_rulepack"


class ConstraintType(StrictSemanticEnum):
    CONSENT = "consent"
    SECURITY = "security"
    SAFETY = "safety"
    PAYMENT_POLICY = "payment_policy"
    CALENDAR_CONFLICT = "calendar_conflict"
    LOCAL_BOUNDARY = "local_boundary"
    TEMPORARY_OVERRIDE = "temporary_override"
    TARGET_BINDING = "target_binding"
    INFORMATION_CONFLICT = "information_conflict"
    USER_STOP = "user_stop"
    UNKNOWN = "unknown"


class ConstraintEffect(StrictSemanticEnum):
    BLOCK_EXECUTION = "block_execution"
    RESTRICT_TARGET = "restrict_target"
    ADD_CONFIRMATION = "add_confirmation"
    ADD_REDACTION = "add_redaction"
    FORCE_SUMMARY = "force_summary"
    LIMIT_DURATION = "limit_duration"
    ALLOW_RAW = "allow_raw"


CONSTRAINT_EFFECT_CANONICAL_ORDER = (
    ConstraintEffect.ADD_REDACTION,
    ConstraintEffect.FORCE_SUMMARY,
    ConstraintEffect.ADD_CONFIRMATION,
    ConstraintEffect.LIMIT_DURATION,
    ConstraintEffect.RESTRICT_TARGET,
    ConstraintEffect.BLOCK_EXECUTION,
)


def constraint_effect_rank(effect: ConstraintEffect) -> int:
    try:
        return CONSTRAINT_EFFECT_CANONICAL_ORDER.index(effect)
    except ValueError as exc:
        raise ValueError(f"unsupported constraint effect: {effect.value}") from exc


class CapabilityType(StrictSemanticEnum):
    READ = "read"
    VERIFY = "verify"
    REDACT = "redact"
    SUMMARIZE = "summarize"
    DISPATCH = "dispatch"
    GUARD = "guard"
    CLARIFY = "clarify"
    UPDATE = "update"
    SCHEDULE = "schedule"
    TOGGLE = "toggle"
    PAY = "pay"
    CANCEL = "cancel"


class CapabilitySource(StrictSemanticEnum):
    AVAILABLE_ACTIONS = "available_actions"
    INTERNAL_TRANSFORM = "internal_transform"
    FIXED_RUNTIME = "fixed_runtime"
    UNKNOWN = "unknown"


class ExecutionDisposition(StrictSemanticEnum):
    PROCEED = "proceed"
    AMEND = "amend"
    ASK = "ask"
    HOLD = "hold"


class DisclosureMode(StrictSemanticEnum):
    RAW = "raw"
    SUMMARY = "summary"
    REDACTED = "redacted"
    STATUS_ONLY = "status_only"
    NONE = "none"


class ReasonCode(StrictSemanticEnum):
    EXECUTABLE = "EXECUTABLE"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    REQUIRED_INFORMATION_MISSING = "REQUIRED_INFORMATION_MISSING"
    REQUIRED_INFORMATION_CONFLICT = "REQUIRED_INFORMATION_CONFLICT"
    UNSUPPORTED_OPERATION_BLUEPRINT = "UNSUPPORTED_OPERATION_BLUEPRINT"
    TARGET_BINDING_FAILED = "TARGET_BINDING_FAILED"
    CONFLICTING_INSTRUCTIONS = "CONFLICTING_INSTRUCTIONS"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    SAFETY_BLOCK = "SAFETY_BLOCK"
    PAYMENT_POLICY_REVIEW = "PAYMENT_POLICY_REVIEW"
    CALENDAR_CONFLICT = "CALENDAR_CONFLICT"
    EXTERNAL_DISCLOSURE_RESTRICTED = "EXTERNAL_DISCLOSURE_RESTRICTED"
    EXTERNAL_DISCLOSURE_BLOCKED = "EXTERNAL_DISCLOSURE_BLOCKED"
    TEMPORARY_OVERRIDE_LIMIT = "TEMPORARY_OVERRIDE_LIMIT"
    DURATION_REQUIRES_CLARIFICATION = "DURATION_REQUIRES_CLARIFICATION"
    CONSTRAINT_FACT_CONFLICT = "CONSTRAINT_FACT_CONFLICT"
    ROLE_INCOMPATIBLE = "ROLE_INCOMPATIBLE"
    ROLE_UNRESOLVED = "ROLE_UNRESOLVED"
    CAPABILITY_STATUS_UNRESOLVED = "CAPABILITY_STATUS_UNRESOLVED"
    CONSTRAINT_STATUS_UNRESOLVED = "CONSTRAINT_STATUS_UNRESOLVED"
    AVOIDED_BY_AUTHORIZED_FALLBACK = "AVOIDED_BY_AUTHORIZED_FALLBACK"
    FALLBACK_USER_CHOICE_REQUIRED = "FALLBACK_USER_CHOICE_REQUIRED"
    UNKNOWN = "UNKNOWN"


class PlanStepType(StrictSemanticEnum):
    READ = "read"
    VERIFY = "verify"
    REDACT = "redact"
    SUMMARIZE = "summarize"
    DISPATCH = "dispatch"
    GUARD = "guard"
    CLARIFY = "clarify"
    UPDATE = "update"
    SCHEDULE = "schedule"
    TOGGLE = "toggle"
    PAY = "pay"


@dataclass(frozen=True)
class DispositionDecision:
    candidate_state: CandidateState
    execution_disposition: ExecutionDisposition
    assumption_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        expected = CandidateDispositionPolicy.execution_disposition(
            self.candidate_state
        )
        if self.execution_disposition != expected:
            raise ValueError(
                "candidate state and execution disposition are incompatible: "
                f"{self.candidate_state.value} -> "
                f"{self.execution_disposition.value}"
            )


class CandidateDispositionPolicy:
    """Single owner for candidate-state and execution-disposition mapping."""

    UNRESOLVED_PRECEDENCE_ASSUMPTION = "ASSUMPTION-DISPOSITION-001"

    @staticmethod
    def candidate_state(
        *,
        rulepack_supported: bool,
        execution_blocked: bool,
        information_status: InformationStatus,
        requires_confirmation: bool,
        amended: bool,
    ) -> CandidateState:
        if not rulepack_supported:
            return CandidateState.UNSUPPORTED_RULEPACK
        if execution_blocked:
            return CandidateState.BLOCKED
        if information_status == InformationStatus.CONFLICT:
            return CandidateState.CONFLICTED
        if information_status == InformationStatus.MISSING:
            return CandidateState.NEEDS_INFORMATION
        if requires_confirmation:
            return CandidateState.NEEDS_CONFIRMATION
        if amended:
            return CandidateState.AMENDABLE
        return CandidateState.VIABLE

    @staticmethod
    def apply_capability(
        state: CandidateState,
        *,
        capability_available: bool,
    ) -> CandidateState:
        if not capability_available:
            return CandidateState.BLOCKED
        return state

    @staticmethod
    def execution_disposition(
        state: CandidateState,
    ) -> ExecutionDisposition:
        if state == CandidateState.VIABLE:
            return ExecutionDisposition.PROCEED
        if state == CandidateState.AMENDABLE:
            return ExecutionDisposition.AMEND
        if state in {
            CandidateState.NEEDS_INFORMATION,
            CandidateState.NEEDS_CONFIRMATION,
            CandidateState.CONFLICTED,
        }:
            return ExecutionDisposition.ASK
        return ExecutionDisposition.HOLD


@dataclass(frozen=True)
class TargetBindingContract:
    target_id: str
    role: TargetRole
    locality: TargetLocality

    def __post_init__(self) -> None:
        if self.role == TargetRole.UNRESOLVED:
            if self.target_id or self.locality != TargetLocality.UNKNOWN:
                raise ValueError(
                    "unresolved target must have empty identity and unknown locality"
                )
            return
        if not self.target_id:
            raise ValueError("resolved target role requires a target identity")
        required_locality = {
            TargetRole.LOCAL_RESOURCE: TargetLocality.LOCAL,
            TargetRole.MEMORY_OWNER: TargetLocality.LOCAL,
            TargetRole.CLARIFICATION_TARGET: TargetLocality.INTERACTION,
            TargetRole.CONFIRMATION_AUTHORITY: TargetLocality.INTERACTION,
            TargetRole.MERCHANT: TargetLocality.DOMAIN,
            TargetRole.DEVICE_TARGET: TargetLocality.DOMAIN,
            TargetRole.CALENDAR_TARGET: TargetLocality.DOMAIN,
            TargetRole.OPERATION_TARGET: TargetLocality.DOMAIN,
        }.get(self.role)
        if required_locality is not None and self.locality != required_locality:
            raise ValueError(
                f"target role {self.role.value} requires locality "
                f"{required_locality.value}"
            )


ONTOLOGY_TYPES = (
    Domain,
    Operation,
    TargetRole,
    TargetLocality,
    ObjectType,
    RecordType,
    FactStatus,
    InformationSlot,
    InformationStatus,
    CandidateState,
    ConstraintType,
    ConstraintEffect,
    CapabilityType,
    CapabilitySource,
    ExecutionDisposition,
    DisclosureMode,
    ReasonCode,
    PlanStepType,
)


def validate_ontology() -> None:
    for enum_type in ONTOLOGY_TYPES:
        values = [member.value for member in enum_type]
        if not values or any(not value for value in values):
            raise ValueError(f"{enum_type.__name__} has an empty value")
        if len(values) != len(set(values)):
            raise ValueError(f"{enum_type.__name__} has duplicate canonical values")
