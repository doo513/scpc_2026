from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from .evidence import (
    EvidenceKind,
    EvidenceStrength,
    IntentEvidenceExtractor,
    IntentEvidenceSet,
    is_strong_local,
)
from .ontology import RecordType
from .records import RecordCode
from .task_view import TaskView


class IntentOverride(str, Enum):
    NONE = "none"
    STOP = "stop"
    CLARIFY = "clarify"
    LOCAL_ONLY = "local_only"
    REDACT_ONLY = "redact_only"


def has_local_update_intent(text: str) -> bool:
    return is_strong_local(text)


@dataclass(frozen=True)
class RouteBundle:
    candidate: RecordCode | None = None
    authority: RecordCode | None = None
    boundary: RecordCode | None = None
    binding_order: RecordCode | None = None

    @property
    def is_local_boundary(self) -> bool:
        return self.boundary == RecordCode.SHARE_BOUNDARY_LOCAL

    @property
    def is_external_boundary(self) -> bool:
        return self.boundary in {
            RecordCode.SHARE_BOUNDARY_REDACTED_EXTERNAL,
            RecordCode.SHARE_BOUNDARY_REDACTED_AFTER_SELECTION,
            RecordCode.SHARE_BOUNDARY_BLOCKED,
        }

    @property
    def is_authority_confirmed(self) -> bool:
        return self.authority in {
            RecordCode.AUTHORITY_INTERNAL_CONFIRMED,
            RecordCode.AUTHORITY_LOCAL_CONFIRMED,
        }

    @property
    def is_authority_pending(self) -> bool:
        return self.authority in {
            RecordCode.AUTHORITY_INCOMPLETE,
            RecordCode.AUTHORITY_USER_PENDING,
        }

    def as_legacy_dict(self) -> dict[str, Any]:
        data = {
            "candidate": self.candidate.value if self.candidate else "",
            "authority": self.authority.value if self.authority else "",
            "boundary": self.boundary.value if self.boundary else "",
            "binding_order": self.binding_order.value if self.binding_order else "",
        }
        data.update(
            is_local_boundary=self.is_local_boundary,
            is_external_boundary=self.is_external_boundary,
            is_authority_confirmed=self.is_authority_confirmed,
            is_authority_pending=self.is_authority_pending,
        )
        return data


@dataclass(frozen=True)
class SensitivityEvidence:
    contains: frozenset[str] = frozenset()
    sensitive_fields: frozenset[str] = frozenset()

    @property
    def has_sensitive_fields(self) -> bool:
        return bool(self.sensitive_fields)


@dataclass
class EvidenceGraph:
    intent_override: IntentOverride = IntentOverride.NONE
    latest_clause: str = ""
    route: RouteBundle = field(default_factory=RouteBundle)
    sensitivity: SensitivityEvidence = field(default_factory=SensitivityEvidence)
    hard_block: list[str] = field(default_factory=list)
    explicit_clarification: list[str] = field(default_factory=list)
    local_update: list[str] = field(default_factory=list)
    target_rebind: list[str] = field(default_factory=list)
    memory_conflict: list[str] = field(default_factory=list)
    unresolved_ambiguity: list[str] = field(default_factory=list)
    external_share: list[str] = field(default_factory=list)
    sensitive_fields: list[str] = field(default_factory=list)
    prompt_overrides: list[str] = field(default_factory=list)
    personal_memory_signals: list[str] = field(default_factory=list)
    slm_fallback_signals: list[str] = field(default_factory=list)
    duplicate_record_types: list[str] = field(default_factory=list)
    intent_evidence: IntentEvidenceSet = field(
        default_factory=lambda: IntentEvidenceSet((), (), "")
    )

    @property
    def route_bundle(self) -> dict[str, Any]:
        return self.route.as_legacy_dict()

    @property
    def has_persistent_memory_write(self) -> bool:
        return "persistent_memory_write_present" in self.local_update

    @classmethod
    def from_view(cls, view: TaskView, focal_id: str = "") -> EvidenceGraph:
        intent_evidence = IntentEvidenceExtractor.extract(view)
        latest_clause = intent_evidence.latest_clause
        route = RouteBundle(
            candidate=view.record_code(RecordType.ROUTE_CANDIDATE_SNAPSHOT),
            authority=view.record_code(RecordType.DISPATCH_AUTHORITY_CHECK),
            boundary=view.record_code(RecordType.SHARE_BOUNDARY_UPDATE),
            binding_order=view.record_code(RecordType.ROUTE_BINDING_ORDER),
        )
        graph = cls(
            intent_override=cls._classify_override(intent_evidence),
            latest_clause=latest_clause,
            route=route,
            duplicate_record_types=sorted(view.duplicate_record_types()),
            intent_evidence=intent_evidence,
        )

        if latest_clause:
            graph.prompt_overrides.append(latest_clause)

        cls._collect_hard_blocks(view, graph)
        cls._collect_clarification(view, graph)
        cls._collect_local_update(view, graph)

        if view.record_present(RecordType.TARGET_CHANGED_AFTER_TURN):
            graph.target_rebind.append("target_changed_after_turn_present")
        if view.record_present(RecordType.MEMORY_CONFLICT):
            graph.memory_conflict.append("memory_conflict_present")
        if view.record_present(RecordType.AMBIGUOUS_TARGET):
            graph.unresolved_ambiguity.append("ambiguous_target_present")
        if view.record_present(RecordType.AMBIGUOUS_FOCAL):
            graph.unresolved_ambiguity.append("ambiguous_focal_present")
        if graph.duplicate_record_types:
            graph.unresolved_ambiguity.extend(
                f"duplicate_record_type:{kind}" for kind in graph.duplicate_record_types
            )
        if view.record_present(RecordType.EXTERNAL_SHARE_POLICY):
            graph.external_share.append("external_share_policy_present")

        for entry in view.personal_memory_entries():
            kind = str(entry.get("type") or "personal_memory")
            graph.personal_memory_signals.append(kind)

        return graph.with_focal(view, focal_id) if focal_id else graph

    def with_focal(self, view: TaskView, focal_id: str) -> EvidenceGraph:
        """Attach focal-scoped facts without extracting prompt evidence again."""
        contains = frozenset(view.contains_for_object(focal_id))
        sensitive = contains & {
            "raw_quote",
            "rrn",
            "name",
            "location",
            "numeric_value",
            "doctor_note",
            "image",
            "amount",
            "card_number",
        }
        return replace(
            self,
            sensitivity=SensitivityEvidence(contains, frozenset(sensitive)),
            sensitive_fields=sorted(sensitive),
        )

    @staticmethod
    def _classify_override(intent: IntentEvidenceSet) -> IntentOverride:
        current = tuple(
            item for item in intent.evidence
            if item.provenance.source_kind == "current_prompt"
        )
        if any(item.kind == EvidenceKind.STOP_PROCESS for item in current):
            return IntentOverride.STOP
        if any(item.kind == EvidenceKind.CLARIFICATION_REQUEST for item in current):
            return IntentOverride.CLARIFY
        if any(
            item.kind == EvidenceKind.LOCAL_UPDATE_REQUEST
            and item.strength in {EvidenceStrength.STRONG, EvidenceStrength.DECISIVE}
            for item in current
        ):
            return IntentOverride.LOCAL_ONLY
        if any(item.kind == EvidenceKind.REDACTION_REQUEST for item in current):
            return IntentOverride.REDACT_ONLY
        return IntentOverride.NONE

    @staticmethod
    def _collect_hard_blocks(view: TaskView, graph: EvidenceGraph) -> None:
        if view.record_present(RecordType.SECURITY_ALERT):
            graph.hard_block.append("security_alert_present")
        if view.record_present(RecordType.SAFETY_MODE):
            graph.hard_block.append("safety_mode_present")
        if view.record_code(RecordType.CONSENT) == RecordCode.CONSENT_REVOKED:
            graph.hard_block.append("consent_revoked")
        for item in graph.intent_evidence.of_kind(EvidenceKind.STOP_PROCESS):
            if item.provenance.source_kind == "current_prompt":
                graph.hard_block.append(f"intent_stop:{item.evidence_id}")

    @staticmethod
    def _collect_clarification(view: TaskView, graph: EvidenceGraph) -> None:
        for item in graph.intent_evidence.current(
            EvidenceKind.CLARIFICATION_REQUEST,
            minimum=EvidenceStrength.STRONG,
        ):
            graph.explicit_clarification.append(f"intent_clarify:{item.evidence_id}")
        for kind in ("payment_policy", "calendar_conflict", "duration_ambiguous"):
            if view.record_present(kind):
                graph.explicit_clarification.append(f"{kind}_present")

    @staticmethod
    def _collect_local_update(view: TaskView, graph: EvidenceGraph) -> None:
        if view.record_present(RecordType.PERSISTENT_MEMORY_WRITE):
            graph.local_update.append("persistent_memory_write_present")
        if graph.intent_evidence.current(
            EvidenceKind.LOCAL_UPDATE_REQUEST,
            minimum=EvidenceStrength.STRONG,
        ):
            graph.local_update.append("prompt_local_intent")
        if graph.route.is_local_boundary:
            graph.local_update.append("route_local_boundary")

    def to_trace(self) -> dict[str, Any]:
        return {
            "intent_override": self.intent_override.value,
            "latest_clause": self.latest_clause,
            "route_bundle": self.route_bundle,
            "hard_block": list(self.hard_block),
            "explicit_clarification": list(self.explicit_clarification),
            "local_update": list(self.local_update),
            "target_rebind": list(self.target_rebind),
            "memory_conflict": list(self.memory_conflict),
            "unresolved_ambiguity": list(self.unresolved_ambiguity),
            "external_share": list(self.external_share),
            "sensitive_fields": list(self.sensitive_fields),
            "duplicate_record_types": list(self.duplicate_record_types),
            "intent": self.intent_evidence.to_trace(),
        }
