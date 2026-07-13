from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from .blueprint import (
    BaseBlueprint,
    BlueprintCompiler,
    BlueprintEffectKind,
    BlueprintRegistry,
    EffectiveBlueprint,
    ResolvedPlanStep,
    project_scope_mode,
)
from .contracts import (
    ACTIONS_ASSUMPTION_ID,
    BUNDLE_ASSUMPTION_ID,
    CANCEL_ASSUMPTION_ID,
    DISPOSITION_ASSUMPTION_ID,
    FALLBACK_ASSUMPTION_ID,
    TARGET_ASSUMPTION_ID,
    TRANSFORM_ASSUMPTION_ID,
)
from .evidence import EvidenceKind, EvidenceStrength, IntentEvidenceSet
from .ontology import (
    CandidateDispositionPolicy,
    CandidateState,
    InformationStatus,
    RecordType,
    TargetBindingContract,
    TargetLocality,
    TargetRole,
)
from .records import RecordCode
from .property_policy import (
    DisclosureDirective,
    PolicyExclusion,
    PropertyClassification,
    derive_policy_exclusions,
    describe_object_properties,
    evaluate_disclosure_properties,
)


CandidateDisposition = CandidateState


class DomainAction(str, Enum):
    CLARIFY = "clarify"
    DISPATCH = "dispatch"
    LOCAL_UPDATE = "local_update"
    MEMORY_UPDATE = "memory_update"
    PAY = "pay"
    TOGGLE = "toggle"
    SCHEDULE = "schedule"
    UNRESOLVED = "unresolved"


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class SlotStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    CONFLICT = "conflict"
    DEFAULTED = "defaulted"


class SlotReason(str, Enum):
    VALUE_ABSENT = "VALUE_ABSENT"
    VALUE_CONFLICT = "VALUE_CONFLICT"
    REQUIRED_MEMORY_UNAVAILABLE = "REQUIRED_MEMORY_UNAVAILABLE"


class ConstraintSeverity(str, Enum):
    HARD = "hard"
    CLARIFY = "clarify"
    AMEND = "amend"


class PromotionRejectionReason(str, Enum):
    UNSUPPORTED_OPERATION_BLUEPRINT = "UNSUPPORTED_OPERATION_BLUEPRINT"
    NO_EXPLICIT_EXECUTION_INTENT = "NO_EXPLICIT_EXECUTION_INTENT"
    FOCAL_DOMAIN_MISMATCH = "FOCAL_DOMAIN_MISMATCH"
    TARGET_UNRESOLVED = "TARGET_UNRESOLVED"
    REQUIRED_SLOT_MISSING = "REQUIRED_SLOT_MISSING"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    HARD_CONSTRAINT_ACTIVE = "HARD_CONSTRAINT_ACTIVE"
    SHARE_ONLY_REQUEST = "SHARE_ONLY_REQUEST"
    VERIFY_ONLY_REQUEST = "VERIFY_ONLY_REQUEST"
    CLARIFICATION_ONLY_REQUEST = "CLARIFICATION_ONLY_REQUEST"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LOWER_RANKED_CANDIDATE = "LOWER_RANKED_CANDIDATE"


class FallbackReason(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    PREFERRED_CAPABILITY_UNAVAILABLE = "PREFERRED_CAPABILITY_UNAVAILABLE"
    NO_AUTHORIZED_FALLBACK = "NO_AUTHORIZED_FALLBACK"
    AUTHORIZED_FALLBACK_SELECTED = "AUTHORIZED_FALLBACK_SELECTED"
    USER_CHOICE_REQUIRED = "USER_CHOICE_REQUIRED"


class OperationBundleStatus(str, Enum):
    SINGLE = "single"
    AUTHORIZED_REPLACEMENT = "authorized_replacement"
    MULTIPLE_UNRESOLVED = "multiple_unresolved"


@dataclass(frozen=True)
class RequiredSlot:
    name: str
    status: SlotStatus
    value: Any = None
    derived_from: tuple[str, ...] = ()
    reason_code: SlotReason | None = None


@dataclass(frozen=True)
class InformationState:
    status: InformationStatus
    required_slots: tuple[RequiredSlot, ...]
    missing_slots: tuple[str, ...]
    conflicting_slots: tuple[str, ...]
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class ActionCandidate:
    candidate_id: str
    action: DomainAction
    confidence: str
    operation_mode: str
    base_blueprint: BaseBlueprint
    derived_from: tuple[str, ...]
    intent_rank: int
    candidate_role: str = "primary"


@dataclass(frozen=True)
class ActionTargetCandidate:
    candidate_id: str
    action_candidate: ActionCandidate
    target: str
    target_role: TargetRole
    target_locality: TargetLocality
    target_confidence: str
    derived_from: tuple[str, ...]

    def __post_init__(self) -> None:
        TargetBindingContract(
            self.target,
            self.target_role,
            self.target_locality,
        )


@dataclass(frozen=True)
class ActiveConstraint:
    constraint_id: str
    kind: str
    severity: ConstraintSeverity
    reason: str
    derived_from: tuple[str, ...]
    parameters: tuple[tuple[str, str], ...] = ()
    effect: BlueprintEffectKind | None = None

    def __post_init__(self) -> None:
        if self.effect is not None:
            return
        if self.severity == ConstraintSeverity.HARD:
            effect = BlueprintEffectKind.BLOCK_EXECUTION
        elif self.severity == ConstraintSeverity.CLARIFY:
            effect = BlueprintEffectKind.ADD_CONFIRMATION
        else:
            raise ValueError(
                f"amend constraint '{self.kind}' requires an explicit effect"
            )
        object.__setattr__(self, "effect", effect)


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: ActionTargetCandidate
    effective_blueprint: EffectiveBlueprint
    required_slots: tuple[RequiredSlot, ...]
    information: InformationState
    capability_status: CapabilityStatus
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    final_plan_capabilities: tuple[str, ...]
    missing_plan_capabilities: tuple[str, ...]
    assumption_refs: tuple[str, ...]
    active_constraints: tuple[ActiveConstraint, ...]
    disposition: CandidateDisposition
    derived_from: tuple[str, ...]


@dataclass(frozen=True)
class DecisionGate:
    gate_id: str
    kind: str
    disposition: CandidateDisposition
    reason: str
    derived_from: tuple[str, ...]

    def to_trace(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "kind": self.kind,
            "disposition": self.disposition.value,
            "reason": self.reason,
            "derived_from": list(self.derived_from),
        }


@dataclass(frozen=True)
class SelectionResolution:
    evaluation: CandidateEvaluation
    disposition: CandidateDisposition
    gates: tuple[DecisionGate, ...] = ()


@dataclass(frozen=True)
class DomainPromotionTrace:
    domain_action_candidate: str
    operation_mode: str
    domain_context_applied: bool
    promotion_eligible: bool
    promotion_applied: bool
    promotion_rejected_reason: PromotionRejectionReason | None
    fallback_profile: str
    required_slots: tuple[RequiredSlot, ...]
    capability_status: CapabilityStatus
    active_constraints: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    selected_pair_id: str = ""
    execution_emitted: bool = False

    def to_trace(self) -> dict[str, Any]:
        return {
            "domain_action_candidate": self.domain_action_candidate,
            "operation_mode": self.operation_mode,
            "domain_context_applied": self.domain_context_applied,
            "promotion_eligible": self.promotion_eligible,
            "promotion_applied": self.promotion_applied,
            "promotion_rejected_reason": (
                self.promotion_rejected_reason.value if self.promotion_rejected_reason else None
            ),
            "fallback_profile": self.fallback_profile,
            "required_slots": [
                {
                    "name": slot.name,
                    "status": slot.status.value,
                    "value": slot.value,
                    "reason_code": slot.reason_code.value
                    if slot.reason_code
                    else None,
                }
                for slot in self.required_slots
            ],
            "capability_status": self.capability_status.value,
            "active_constraints": list(self.active_constraints),
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "selected_pair_id": self.selected_pair_id,
            "execution_emitted": self.execution_emitted,
        }


@dataclass(frozen=True)
class FallbackEdge:
    edge_id: str
    source_candidate_id: str
    destination_candidate_id: str
    authorization_source: str
    semantic_preservation: str
    activation_condition: str
    reason_code: str
    derived_from: tuple[str, ...]

    AUTHORIZATION_SOURCES = frozenset(
        {
            "current_user_explicit_replacement",
            "official_policy",
            "official_plan_transformation",
        }
    )
    SEMANTIC_PRESERVATION_MODES = frozenset(
        {
            "explicit_operation_replacement",
            "policy_equivalent_operation",
            "plan_semantic_preserving_transformation",
        }
    )
    ACTIVATION_CONDITIONS = frozenset(
        {
            "source_non_executable",
            "source_capability_unavailable",
        }
    )

    @property
    def is_authorized(self) -> bool:
        return bool(
            self.source_candidate_id
            and self.destination_candidate_id
            and self.source_candidate_id != self.destination_candidate_id
            and self.authorization_source in self.AUTHORIZATION_SOURCES
            and self.semantic_preservation
            in self.SEMANTIC_PRESERVATION_MODES
            and self.activation_condition in self.ACTIVATION_CONDITIONS
            and self.reason_code
            and self.derived_from
        )

    def to_trace(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_candidate_id": self.source_candidate_id,
            "destination_candidate_id": self.destination_candidate_id,
            "authorization_source": self.authorization_source,
            "semantic_preservation": self.semantic_preservation,
            "activation_condition": self.activation_condition,
            "reason_code": self.reason_code,
            "derived_from": list(self.derived_from),
            "authorized": self.is_authorized,
        }


@dataclass(frozen=True)
class OperationBundle:
    status: OperationBundleStatus
    action_candidate_ids: tuple[str, ...]
    operation_keys: tuple[str, ...]
    candidate_pair_ids: tuple[str, ...]
    derived_from: tuple[str, ...]

    def to_trace(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action_candidate_ids": list(self.action_candidate_ids),
            "operation_keys": list(self.operation_keys),
            "candidate_pair_ids": list(self.candidate_pair_ids),
            "derived_from": list(self.derived_from),
        }


@dataclass(frozen=True)
class FallbackResolution:
    selected_candidate_id: str
    preferred_candidate_ids: tuple[str, ...]
    fallback_applied: bool
    reason: FallbackReason
    authorized_candidate_ids: tuple[str, ...]
    derived_from: tuple[str, ...]

    def to_trace(self) -> dict[str, Any]:
        return {
            "selected_candidate_id": self.selected_candidate_id,
            "preferred_candidate_ids": list(self.preferred_candidate_ids),
            "fallback_applied": self.fallback_applied,
            "reason": self.reason.value,
            "authorized_candidate_ids": list(self.authorized_candidate_ids),
            "derived_from": list(self.derived_from),
        }


@dataclass(frozen=True)
class DecisionMatrix:
    action_candidates: tuple[ActionCandidate, ...]
    evaluations: tuple[CandidateEvaluation, ...]
    selection: SelectionResolution
    promotion_traces: tuple[DomainPromotionTrace, ...]
    fallback_edges: tuple[FallbackEdge, ...]
    operation_bundle: OperationBundle
    fallback: FallbackResolution

    @property
    def selected(self) -> CandidateEvaluation:
        return self.selection.evaluation

    def to_trace(self) -> dict[str, Any]:
        return {
            "selected_candidate": self.selected.candidate.candidate_id,
            "selected_action": self.selected.candidate.action_candidate.action.value,
            "selected_operation_mode": self.selected.candidate.action_candidate.operation_mode,
            "selected_target": self.selected.candidate.target,
            "selected_disposition": self.selection.disposition.value,
            "decision_gates": [
                gate.to_trace() for gate in self.selection.gates
            ],
            "evaluations": [
                {
                    "candidate_id": item.candidate.candidate_id,
                    "action": item.candidate.action_candidate.action.value,
                    "operation_mode": item.candidate.action_candidate.operation_mode,
                    "blueprint": item.effective_blueprint.to_trace(),
                    "target": item.candidate.target,
                    "target_role": item.candidate.target_role.value,
                    "target_locality": item.candidate.target_locality.value,
                    "capability_status": item.capability_status.value,
                    "required_capabilities": list(item.required_capabilities),
                    "missing_capabilities": list(item.missing_capabilities),
                    "final_plan_capabilities": list(
                        item.final_plan_capabilities
                    ),
                    "missing_plan_capabilities": list(
                        item.missing_plan_capabilities
                    ),
                    "assumption_refs": list(item.assumption_refs),
                    "information_status": item.information.status.value,
                    "slots": {
                        slot.name: {
                            "status": slot.status.value,
                            "reason_code": slot.reason_code.value
                            if slot.reason_code
                            else None,
                        }
                        for slot in item.required_slots
                    },
                    "active_constraints": [constraint.kind for constraint in item.active_constraints],
                    "disposition": item.disposition.value,
                    "derived_from": list(item.derived_from),
                }
                for item in self.evaluations
            ],
            "domain_promotion": [trace.to_trace() for trace in self.promotion_traces],
            "fallback_edges": [edge.to_trace() for edge in self.fallback_edges],
            "operation_bundle": self.operation_bundle.to_trace(),
            "fallback": self.fallback.to_trace(),
        }


@dataclass(frozen=True)
class FinalDecision:
    focal_id: str
    selected_pair_id: str
    action: DomainAction
    operation_mode: str
    operation_target: str
    operation_target_role: TargetRole
    operation_target_locality: TargetLocality
    target: str
    target_source: str
    control: str
    effective_blueprint: EffectiveBlueprint
    information: InformationState
    capability_status: CapabilityStatus
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    final_plan_capabilities: tuple[str, ...]
    missing_plan_capabilities: tuple[str, ...]
    active_constraints: tuple[ActiveConstraint, ...]
    decision_gates: tuple[DecisionGate, ...]
    available_actions: tuple[str, ...]
    disclosure_mode: str
    allowed_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    exclusion_provenance: tuple[PolicyExclusion, ...]
    scope_requires_user_confirmation: bool
    policy_requires_confirmation: bool
    risk_flags: tuple[str, ...]
    violations: tuple[str, ...]
    plan_steps: tuple[ResolvedPlanStep, ...]
    fallback: FallbackResolution
    domain_promotion: tuple[DomainPromotionTrace, ...]
    reason_code: str
    historical_focal: bool
    unresolved_assumption_refs: tuple[str, ...]
    derived_from: tuple[str, ...]

    @property
    def requires_user_confirmation(self) -> bool:
        """Compatibility alias for the content-scope confirmation field."""
        return self.scope_requires_user_confirmation

    def to_trace(self) -> dict[str, Any]:
        return {
            "focal_id": self.focal_id,
            "selected_pair_id": self.selected_pair_id,
            "action": self.action.value,
            "operation_mode": self.operation_mode,
            "operation_target": self.operation_target,
            "operation_target_role": self.operation_target_role.value,
            "operation_target_locality": self.operation_target_locality.value,
            "target": self.target,
            "target_source": self.target_source,
            "control": self.control,
            "effective_blueprint": self.effective_blueprint.to_trace(),
            "information_status": self.information.status.value,
            "missing_slots": list(self.information.missing_slots),
            "conflicting_slots": list(self.information.conflicting_slots),
            "capability_status": self.capability_status.value,
            "required_capabilities": list(self.required_capabilities),
            "missing_capabilities": list(self.missing_capabilities),
            "final_plan_capabilities": list(self.final_plan_capabilities),
            "missing_plan_capabilities": list(
                self.missing_plan_capabilities
            ),
            "disclosure": {
                "mode": self.disclosure_mode,
                "allowed_fields": list(self.allowed_fields),
                "excluded_fields": list(self.excluded_fields),
                "exclusion_provenance": [
                    {
                        "field": item.name,
                        "source_ids": list(item.source_ids),
                        "policy_version": item.policy_version,
                        "provenance_id": item.provenance_id,
                    }
                    for item in self.exclusion_provenance
                ],
                "requires_user_confirmation": self.scope_requires_user_confirmation,
            },
            "policy_requires_confirmation": self.policy_requires_confirmation,
            "risk_flags": list(self.risk_flags),
            "violations": list(self.violations),
            "plan_steps": [step.to_event() for step in self.plan_steps],
            "active_constraints": [
                {
                    "kind": item.kind,
                    "severity": item.severity.value,
                    "derived_from": list(item.derived_from),
                    "parameters": dict(item.parameters),
                    "effect": item.effect.value if item.effect else None,
                }
                for item in self.active_constraints
            ],
            "decision_gates": [gate.to_trace() for gate in self.decision_gates],
            "fallback": self.fallback.to_trace(),
            "domain_promotion": [
                item.to_trace() for item in self.domain_promotion
            ],
            "reason_code": self.reason_code,
            "historical_focal": self.historical_focal,
            "unresolved_assumption_refs": list(
                self.unresolved_assumption_refs
            ),
            "derived_from": list(self.derived_from),
        }


class ActionCandidateResolver:
    DOMAIN_OBJECT_TYPES = {
        DomainAction.PAY: {"payment_request"},
        DomainAction.TOGGLE: {"device_setting", "iot_routine"},
        DomainAction.SCHEDULE: {"calendar_event"},
    }

    @classmethod
    def resolve(
        cls,
        view: Any,
        evidence: IntentEvidenceSet,
        focal: dict[str, Any],
        operation_intent: Any | None = None,
    ) -> tuple[ActionCandidate, ...]:
        candidates: list[ActionCandidate] = []
        focal_type = str(focal.get("type") or "")

        def add(
            action: DomainAction,
            ids: Iterable[str],
            rank: int,
            confidence: str = "high",
            operation_mode: str = "execute",
            candidate_role: str = "primary",
        ) -> None:
            if any(
                candidate.action == action
                and candidate.operation_mode == operation_mode
                for candidate in candidates
            ):
                return
            candidates.append(
                ActionCandidate(
                    candidate_id=f"action:{action.value}:{operation_mode}",
                    action=action,
                    confidence=confidence,
                    operation_mode=operation_mode,
                    base_blueprint=BlueprintRegistry.resolve(
                        action.value, operation_mode
                    ),
                    derived_from=tuple(ids),
                    intent_rank=rank,
                    candidate_role=candidate_role,
                )
            )

        if operation_intent is not None:
            for hypothesis in operation_intent.hypotheses:
                try:
                    action = DomainAction(str(hypothesis.action))
                except ValueError:
                    continue
                add(
                    action,
                    hypothesis.supporting_evidence_ids,
                    hypothesis.rank,
                    hypothesis.confidence,
                    hypothesis.mode.value,
                    hypothesis.candidate_role,
                )
            if candidates:
                return tuple(
                    sorted(
                        candidates,
                        key=lambda candidate: (
                            -candidate.intent_rank,
                            candidate.action.value,
                            candidate.operation_mode,
                        ),
                    )
                )

        local_ids = evidence.prompt_ids(
            EvidenceKind.LOCAL_UPDATE_REQUEST,
            minimum=EvidenceStrength.STRONG,
        )
        memory_ids = evidence.prompt_ids(
            EvidenceKind.MEMORY_WRITE_REQUEST,
            minimum=EvidenceStrength.STRONG,
        )
        if memory_ids or view.record_present(RecordType.PERSISTENT_MEMORY_WRITE):
            add(
                DomainAction.MEMORY_UPDATE,
                memory_ids or ("record:persistent_memory_write",),
                100,
                operation_mode="local_update",
            )
        elif local_ids:
            add(
                DomainAction.LOCAL_UPDATE,
                local_ids,
                95,
                operation_mode="local_update",
            )

        clarification_ids = tuple(
            item.evidence_id
            for item in evidence.current(
                EvidenceKind.CLARIFICATION_REQUEST,
                minimum=EvidenceStrength.DECISIVE,
            )
            if item.payload == "clarify_user"
        )
        # Clarification evidence is evaluated as an effect on the semantic
        # candidate. Only an unresolved domain/focal mismatch creates a
        # dedicated clarification candidate upstream.

        direct_domain = evidence.prompt_evidence(
            EvidenceKind.EXPLICIT_DOMAIN_VERB,
            minimum=EvidenceStrength.SUPPORTING,
        )
        mapping = {
            "PAY": DomainAction.PAY,
            "TOGGLE": DomainAction.TOGGLE,
            "SCHEDULE": DomainAction.SCHEDULE,
        }
        for item in direct_domain:
            action = mapping.get(item.payload)
            if action and focal_type in cls.DOMAIN_OBJECT_TYPES[action]:
                add(action, (item.evidence_id,), 80)

        share_ids = evidence.prompt_ids(
            EvidenceKind.SHARE_REQUEST,
            minimum=EvidenceStrength.SUPPORTING,
        )
        execution_ids = evidence.prompt_ids(
            EvidenceKind.EXECUTION_REQUEST,
            minimum=EvidenceStrength.SUPPORTING,
        )
        if execution_ids and not share_ids:
            for action, object_types in cls.DOMAIN_OBJECT_TYPES.items():
                if focal_type in object_types and not any(
                    candidate.action == action for candidate in candidates
                ):
                    add(
                        action,
                        execution_ids + (f"focal_type:{focal_type}",),
                        75,
                        "medium",
                    )
        if share_ids:
            add(
                DomainAction.DISPATCH,
                share_ids,
                60,
                "medium",
                operation_mode="share",
            )
        if not candidates:
            add(
                DomainAction.UNRESOLVED,
                clarification_ids or ("intent:operation_unresolved",),
                0,
                "none",
                operation_mode="unresolved",
            )
        return tuple(sorted(candidates, key=lambda candidate: (-candidate.intent_rank, candidate.action.value)))


class CandidateEvaluator:
    @classmethod
    def build_matrix(
        cls,
        view: Any,
        evidence_graph: Any,
        focal: dict[str, Any],
        target_candidates: Iterable[Any],
        operation_intent: Any | None = None,
        fallback_edges: Iterable[FallbackEdge] = (),
    ) -> DecisionMatrix:
        intent = evidence_graph.intent_evidence
        actions = ActionCandidateResolver.resolve(
            view, intent, focal, operation_intent
        )
        targets = tuple(target_candidates)
        evaluations: list[CandidateEvaluation] = []

        for action in actions:
            for pair in ActionTargetPairBuilder.build(
                action, targets, focal
            ):
                evaluations.append(cls._evaluate(view, evidence_graph, focal, pair))

        edges = tuple(fallback_edges) + FallbackEdgeBuilder.build(
            evaluations, evidence_graph
        )
        operation_bundle = OperationBundleAnalyzer.analyze(
            actions,
            evaluations,
            edges,
            evidence_graph,
        )
        selection, fallback = AuthorizedFallbackSolver.solve(
            evaluations,
            edges,
            operation_bundle,
        )
        selected = selection.evaluation
        traces = cls._promotion_traces(
            view,
            evidence_graph,
            actions,
            evaluations,
            selected,
            focal,
        )
        return DecisionMatrix(
            actions,
            tuple(evaluations),
            selection,
            traces,
            edges,
            operation_bundle,
            fallback,
        )

    @classmethod
    def _evaluate(cls, view: Any, evidence_graph: Any, focal: dict[str, Any], pair: ActionTargetCandidate) -> CandidateEvaluation:
        action = pair.action_candidate.action
        constraints = ConstraintActivator.activate(
            view, evidence_graph, focal, pair, CapabilityStatus.AVAILABLE
        )
        effective_blueprint = BlueprintCompiler.apply(
            pair.action_candidate.base_blueprint,
            constraints,
            raw_dispatch_allowed=ConstraintActivator.raw_dispatch_allowed(
                view, focal, pair.target
            ),
        )
        information = InformationResolver.resolve(
            effective_blueprint,
            pair,
            focal,
            evidence_graph,
        )
        slots = information.required_slots

        preliminary = CandidateDispositionPolicy.candidate_state(
            rulepack_supported=effective_blueprint.supported,
            execution_blocked=effective_blueprint.blocked,
            information_status=information.status,
            requires_confirmation=(
                action == DomainAction.CLARIFY
                or effective_blueprint.requires_confirmation
            ),
            amended=effective_blueprint.amended,
        )

        required_capabilities = effective_blueprint.capabilities_for(
            preliminary.value
        )
        capability, missing_capabilities = CapabilityResolver.resolve(
            view, required_capabilities
        )

        disposition = CandidateDispositionPolicy.apply_capability(
            preliminary,
            capability_available=(capability == CapabilityStatus.AVAILABLE),
        )
        final_plan_capabilities = effective_blueprint.capabilities_for(
            disposition.value
        )
        _, missing_plan_capabilities = CapabilityResolver.resolve(
            view,
            final_plan_capabilities,
        )
        assumption_refs = [
            DISPOSITION_ASSUMPTION_ID,
            ACTIONS_ASSUMPTION_ID,
            TRANSFORM_ASSUMPTION_ID,
        ]
        if pair.action_candidate.operation_mode == "cancel":
            assumption_refs.append(CANCEL_ASSUMPTION_ID)

        derived = tuple(dict.fromkeys(pair.derived_from + tuple(
            evidence_id for constraint in constraints for evidence_id in constraint.derived_from
        )))
        return CandidateEvaluation(
            pair,
            effective_blueprint,
            slots,
            information,
            capability,
            required_capabilities,
            missing_capabilities,
            final_plan_capabilities,
            missing_plan_capabilities,
            tuple(assumption_refs),
            constraints,
            disposition,
            derived,
        )

    @classmethod
    def _select_target_or_ask(
        cls,
        evaluations: list[CandidateEvaluation],
    ) -> SelectionResolution:
        confidence_rank = {
            "decisive": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
            "none": 0,
        }
        top_confidence = max(
            confidence_rank.get(item.candidate.target_confidence, 0)
            for item in evaluations
        )
        top = sorted(
            (
                item
                for item in evaluations
                if confidence_rank.get(item.candidate.target_confidence, 0)
                == top_confidence
            ),
            key=lambda item: item.candidate.candidate_id,
        )
        executable = [
            item for item in top if item.disposition == CandidateDisposition.EXECUTABLE
        ]
        if len({item.candidate.target for item in executable}) > 1:
            selected = executable[0]
            alternatives = tuple(item.candidate.candidate_id for item in executable)
            gate = DecisionGate(
                gate_id=(
                    f"gate:{selected.candidate.candidate_id}:"
                    "multiple_executable_alternatives"
                ),
                kind="multiple_executable_alternatives",
                disposition=CandidateDisposition.NEEDS_CLARIFICATION,
                reason="user_choice_required_between_executable_alternatives",
                derived_from=alternatives,
            )
            return SelectionResolution(
                selected,
                CandidateDisposition.NEEDS_CLARIFICATION,
                (gate,),
            )
        selected = top[0]
        return SelectionResolution(selected, selected.disposition)

    @classmethod
    def _promotion_traces(
        cls,
        view: Any,
        evidence_graph: Any,
        actions: tuple[ActionCandidate, ...],
        evaluations: list[CandidateEvaluation],
        selected: CandidateEvaluation,
        focal: dict[str, Any],
    ) -> tuple[DomainPromotionTrace, ...]:
        traces: list[DomainPromotionTrace] = []
        intent: IntentEvidenceSet = evidence_graph.intent_evidence
        domain_actions = {DomainAction.PAY, DomainAction.TOGGLE, DomainAction.SCHEDULE}
        has_execute = bool(intent.prompt_evidence(EvidenceKind.EXECUTION_REQUEST))
        has_share = bool(intent.prompt_evidence(EvidenceKind.SHARE_REQUEST))
        has_clarify = bool(intent.current(EvidenceKind.CLARIFICATION_REQUEST))
        has_verify = bool(intent.prompt_evidence(EvidenceKind.VERIFY_REQUEST))

        for action in actions:
            if action.action not in domain_actions:
                continue
            related = [item for item in evaluations if item.candidate.action_candidate == action]
            best = related[0]
            eligible = (
                action.operation_mode == "execute"
                and has_execute
                and best.capability_status == CapabilityStatus.AVAILABLE
                and all(slot.status not in {SlotStatus.MISSING, SlotStatus.CONFLICT} for slot in best.required_slots)
                and not any(constraint.severity == ConstraintSeverity.HARD for constraint in best.active_constraints)
                and best.candidate.target != ""
            )
            applied = selected.candidate.action_candidate == action and eligible
            reason: PromotionRejectionReason | None = None
            if not best.effective_blueprint.supported:
                reason = (
                    PromotionRejectionReason.UNSUPPORTED_OPERATION_BLUEPRINT
                )
            elif best.capability_status == CapabilityStatus.UNAVAILABLE:
                reason = PromotionRejectionReason.CAPABILITY_UNAVAILABLE
            elif not has_execute:
                if has_clarify:
                    reason = PromotionRejectionReason.CLARIFICATION_ONLY_REQUEST
                elif has_share:
                    reason = PromotionRejectionReason.SHARE_ONLY_REQUEST
                elif has_verify:
                    reason = PromotionRejectionReason.VERIFY_ONLY_REQUEST
                else:
                    reason = PromotionRejectionReason.NO_EXPLICIT_EXECUTION_INTENT
            elif not best.candidate.target:
                reason = PromotionRejectionReason.TARGET_UNRESOLVED
            elif any(slot.status in {SlotStatus.MISSING, SlotStatus.CONFLICT} for slot in best.required_slots):
                reason = PromotionRejectionReason.REQUIRED_SLOT_MISSING
            elif any(constraint.severity == ConstraintSeverity.HARD for constraint in best.active_constraints):
                reason = PromotionRejectionReason.HARD_CONSTRAINT_ACTIVE
            elif eligible and not applied:
                reason = PromotionRejectionReason.LOWER_RANKED_CANDIDATE

            traces.append(
                DomainPromotionTrace(
                    domain_action_candidate=action.action.value,
                    operation_mode=action.operation_mode,
                    domain_context_applied=(
                        selected.candidate.action_candidate == action
                    ),
                    promotion_eligible=eligible,
                    promotion_applied=applied,
                    promotion_rejected_reason=reason,
                    fallback_profile="authorized_pair_fallback",
                    required_slots=best.required_slots,
                    capability_status=best.capability_status,
                    active_constraints=tuple(constraint.kind for constraint in best.active_constraints),
                    supporting_evidence_ids=action.derived_from,
                    selected_pair_id=(
                        selected.candidate.candidate_id
                        if selected.candidate.action_candidate == action
                        else ""
                    ),
                )
            )

        action_by_payload = {
            "PAY": DomainAction.PAY,
            "TOGGLE": DomainAction.TOGGLE,
            "SCHEDULE": DomainAction.SCHEDULE,
        }
        present_actions = {action.action for action in actions}
        for item in intent.prompt_evidence(
            EvidenceKind.EXPLICIT_DOMAIN_VERB,
            minimum=EvidenceStrength.SUPPORTING,
        ):
            action = action_by_payload.get(item.payload)
            if action is None or action in present_actions:
                continue
            blueprint = BlueprintRegistry.resolve(action.value, "execute")
            capability = (
                CapabilityStatus.AVAILABLE
                if all(
                    required in view.available_actions
                    for required in blueprint.execution_capabilities
                )
                else CapabilityStatus.UNAVAILABLE
            )
            reason = (
                PromotionRejectionReason.FOCAL_DOMAIN_MISMATCH
                if str(focal.get("type") or "")
                not in ActionCandidateResolver.DOMAIN_OBJECT_TYPES[action]
                else PromotionRejectionReason.LOW_CONFIDENCE
            )
            traces.append(
                DomainPromotionTrace(
                    domain_action_candidate=action.value,
                    operation_mode="execute",
                    domain_context_applied=False,
                    promotion_eligible=False,
                    promotion_applied=False,
                    promotion_rejected_reason=reason,
                    fallback_profile="authorized_pair_fallback",
                    required_slots=(),
                    capability_status=capability,
                    active_constraints=(),
                    supporting_evidence_ids=(item.evidence_id,),
                )
            )
        present_modes = {
            (action.action, action.operation_mode) for action in actions
        }
        for kind, operation_mode, capability_name in (
            (EvidenceKind.DOMAIN_CANCEL_REQUEST, "cancel", "cancel"),
            (EvidenceKind.DOMAIN_VERIFY_REQUEST, "verify", "verify"),
        ):
            grouped: dict[DomainAction, list[str]] = {}
            for item in intent.prompt_evidence(
                kind, minimum=EvidenceStrength.SUPPORTING
            ):
                action = action_by_payload.get(item.payload)
                if action is not None:
                    grouped.setdefault(action, []).append(item.evidence_id)
            for action, evidence_ids in grouped.items():
                if (action, operation_mode) in present_modes:
                    continue
                capability = (
                    CapabilityStatus.AVAILABLE
                    if capability_name in view.available_actions
                    else CapabilityStatus.UNAVAILABLE
                )
                traces.append(
                    DomainPromotionTrace(
                        domain_action_candidate=action.value,
                        operation_mode=operation_mode,
                        domain_context_applied=False,
                        promotion_eligible=False,
                        promotion_applied=False,
                        promotion_rejected_reason=(
                            PromotionRejectionReason.FOCAL_DOMAIN_MISMATCH
                            if str(focal.get("type") or "")
                            not in ActionCandidateResolver.DOMAIN_OBJECT_TYPES[
                                action
                            ]
                            else PromotionRejectionReason.LOW_CONFIDENCE
                        ),
                        fallback_profile="authorized_pair_fallback",
                        required_slots=(),
                        capability_status=capability,
                        active_constraints=(),
                        supporting_evidence_ids=tuple(evidence_ids),
                    )
                )
        return tuple(traces)


class ActionTargetPairBuilder:
    @staticmethod
    def build(
        action: ActionCandidate,
        targets: tuple[Any, ...],
        focal: dict[str, Any],
    ) -> tuple[ActionTargetCandidate, ...]:
        compatible = ActionTargetPairBuilder._compatible_targets(
            action, targets, focal
        )
        if not compatible:
            compatible = (("", "unresolved", "none", ()),)
        return tuple(
            ActionTargetCandidate(
                candidate_id=(
                    f"pair:{action.action.value}:{action.operation_mode}:"
                    f"{role}:{target or 'unresolved'}"
                ),
                action_candidate=action,
                target=target,
                target_role=TargetRole.parse(role),
                target_locality=(
                    TargetLocality.UNKNOWN
                    if role == TargetRole.UNRESOLVED.value
                    else TargetLocality.LOCAL
                    if role == TargetRole.LOCAL_RESOURCE.value
                    else TargetLocality.INTERACTION
                    if role == TargetRole.CLARIFICATION_TARGET.value
                    else TargetLocality.DOMAIN
                    if role
                    in {
                        TargetRole.MERCHANT.value,
                        TargetRole.DEVICE_TARGET.value,
                        TargetRole.CALENDAR_TARGET.value,
                        TargetRole.OPERATION_TARGET.value,
                    }
                    else TargetLocality.EXTERNAL
                ),
                target_confidence=confidence,
                derived_from=tuple(
                    dict.fromkeys(action.derived_from + tuple(derived_from))
                ),
            )
            for target, role, confidence, derived_from in compatible
        )

    @staticmethod
    def _compatible_targets(
        action: ActionCandidate,
        targets: tuple[Any, ...],
        focal: dict[str, Any],
    ) -> tuple[tuple[str, str, str, tuple[str, ...]], ...]:
        attrs = focal.get("attrs") or {}
        rows: list[tuple[str, str, str, tuple[str, ...]]] = []
        unresolved_requirements = tuple(
            requirement
            for candidate in targets
            for requirement in tuple(getattr(candidate, "requirements", ()) or ())
        )
        action_name = action.action.value

        if action_name in {"local_update", "memory_update"}:
            rows.append(
                ("memory_store", "local_resource", "high", ("intent:local",))
            )
        elif action_name == "clarify":
            rows.append(
                ("user", "clarification_target", "high", ("intent:clarification",))
            )
        elif action_name == "pay" and attrs.get("merchant"):
            rows.append(
                (
                    str(attrs["merchant"]),
                    "merchant",
                    "high",
                    ("focal_attr:merchant",),
                )
            )
        elif action_name == "toggle":
            for candidate in targets:
                source = str(getattr(candidate, "source", "") or "")
                recalled_target = str(getattr(candidate, "target", "") or "")
                if recalled_target and source.startswith("persistent_memory:"):
                    rows.append(
                        (
                            recalled_target,
                            "device_target",
                            "high",
                            (source,) + unresolved_requirements,
                        )
                    )
            target = attrs.get("target") or attrs.get("name")
            if target:
                rows.append(
                    (
                        str(target),
                        "device_target",
                        "medium",
                        ("focal_attr:device_target",) + unresolved_requirements,
                    )
                )
        elif action_name == "schedule":
            target = attrs.get("attendee") or focal.get("id")
            if target:
                rows.append(
                    (
                        str(target),
                        "calendar_target",
                        "high",
                        ("focal_attr:calendar_target",),
                    )
                )
        else:
            for candidate in targets:
                target = str(getattr(candidate, "target", "") or "")
                if not target or target == "memory_store":
                    continue
                source = str(
                    getattr(candidate, "source", "target_candidate")
                    or "target_candidate"
                )
                confidence = str(
                    getattr(candidate, "confidence", "low") or "low"
                )
                rows.append(
                    (
                        target,
                        "dispatch_destination",
                        confidence,
                        (source,) + unresolved_requirements,
                    )
                )

        allowed_roles = set(action.base_blueprint.required_target_roles)
        deduped: list[tuple[str, str, str, tuple[str, ...]]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (row[0], row[1])
            if row[1] not in allowed_roles or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return tuple(deduped)


class InformationResolver:
    @staticmethod
    def resolve(
        blueprint: EffectiveBlueprint,
        pair: ActionTargetCandidate,
        focal: dict[str, Any],
        evidence_graph: Any,
    ) -> InformationState:
        attrs = focal.get("attrs") or {}
        arguments = tuple(
            item.payload
            for item in evidence_graph.intent_evidence.prompt_evidence(
                EvidenceKind.OPERATION_ARGUMENT,
                minimum=EvidenceStrength.SUPPORTING,
            )
        )
        desired_state = next(
            (
                payload.rsplit(":", 1)[-1]
                for payload in reversed(arguments)
                if payload.startswith("TOGGLE:desired_state:")
            ),
            "apply_routine" if focal.get("type") == "iot_routine" else "",
        )
        values: dict[str, tuple[Any, str]] = {
            "operation_reference": (focal.get("id"), "focal:id"),
            "merchant": (
                attrs.get("merchant") or pair.target,
                "focal_attr:merchant",
            ),
            "amount": (attrs.get("amount"), "focal_attr:amount"),
            "method": (attrs.get("method"), "focal_attr:method"),
            "device_target": (pair.target, "action_target"),
            "desired_state": (desired_state, "intent:desired_state"),
            "event": (focal.get("id"), "focal:id"),
            "time": (attrs.get("time"), "focal_attr:time"),
            "local_resource": (focal.get("id"), "focal:id"),
            "clarification_target": (pair.target, "action_target"),
            "destination": (pair.target, "action_target"),
        }
        slots: list[RequiredSlot] = []
        for spec in blueprint.required_slots:
            if not spec.required and spec.default is not None:
                slots.append(
                    RequiredSlot(
                        spec.name,
                        SlotStatus.DEFAULTED,
                        spec.default,
                        (f"safe_default:{spec.name}",),
                    )
                )
                continue
            value, source = values.get(spec.name, (None, f"slot:{spec.name}"))
            status = (
                SlotStatus.PRESENT
                if value not in (None, "")
                else SlotStatus.MISSING
            )
            slots.append(
                RequiredSlot(
                    spec.name,
                    status,
                    value,
                    (source,),
                    SlotReason.VALUE_ABSENT
                    if status == SlotStatus.MISSING
                    else None,
                )
            )
        if "requirement:memory_value:missing" in pair.derived_from:
            slots.append(
                RequiredSlot(
                    "memory_value",
                    SlotStatus.MISSING,
                    None,
                    ("record:persistent_memory_recall",),
                    SlotReason.REQUIRED_MEMORY_UNAVAILABLE,
                )
            )
        return InformationResolver._state(tuple(slots))

    @staticmethod
    def _state(slots: tuple[RequiredSlot, ...]) -> InformationState:
        missing = tuple(
            slot.name for slot in slots if slot.status == SlotStatus.MISSING
        )
        conflicting = tuple(
            slot.name for slot in slots if slot.status == SlotStatus.CONFLICT
        )
        status = (
            InformationStatus.CONFLICT
            if conflicting
            else InformationStatus.MISSING
            if missing
            else InformationStatus.COMPLETE
        )
        return InformationState(
            status=status,
            required_slots=slots,
            missing_slots=missing,
            conflicting_slots=conflicting,
            derived_from=tuple(
                dict.fromkeys(
                    evidence_id
                    for slot in slots
                    for evidence_id in slot.derived_from
                )
            ),
        )


class CapabilityResolver:
    @staticmethod
    def resolve(
        view: Any,
        required_capabilities: tuple[str, ...],
    ) -> tuple[CapabilityStatus, tuple[str, ...]]:
        missing = tuple(
            capability
            for capability in required_capabilities
            if capability not in view.available_actions
        )
        return (
            CapabilityStatus.UNAVAILABLE
            if missing
            else CapabilityStatus.AVAILABLE,
            missing,
        )


class ConstraintActivator:
    @classmethod
    def activate(
        cls,
        view: Any,
        evidence_graph: Any,
        focal: dict[str, Any],
        pair: ActionTargetCandidate,
        _capability: CapabilityStatus,
    ) -> tuple[ActiveConstraint, ...]:
        action = pair.action_candidate.action
        target_is_local = (
            pair.target_locality == TargetLocality.LOCAL
            or pair.target == "memory_store"
        )
        constraints: list[ActiveConstraint] = []
        intent = evidence_graph.intent_evidence

        def add(
            kind: str,
            severity: ConstraintSeverity,
            reason: str,
            *ids: str,
            parameters: tuple[tuple[str, str], ...] = (),
            effect: BlueprintEffectKind | None = None,
        ) -> None:
            constraints.append(
                ActiveConstraint(
                    f"constraint:{pair.candidate_id}:{kind}",
                    kind,
                    severity,
                    reason,
                    tuple(ids),
                    parameters,
                    effect,
                )
            )

        focal_id = str(focal.get("id") or "")
        property_effect = evaluate_disclosure_properties(
            evidence_graph.sensitivity.properties
        )
        if action == DomainAction.DISPATCH and property_effect.severity:
            governed_properties = tuple(
                item
                for item in evidence_graph.sensitivity.properties
                if item.name in property_effect.excluded_fields
            )
            parameters = (
                (
                    "classification",
                    property_effect.governing_classification.value
                    if property_effect.governing_classification
                    else "",
                ),
                ("excluded_fields", ",".join(property_effect.excluded_fields)),
                ("permitted_modes", ",".join(sorted(property_effect.permitted_modes))),
                ("policy_version", property_effect.policy_version),
            )
            if property_effect.severity == "hard":
                kind = (
                    "unknown_property_disclosure"
                    if property_effect.governing_classification
                    == PropertyClassification.UNKNOWN
                    else "secret_property_disclosure"
                )
                add(
                    kind,
                    ConstraintSeverity.HARD,
                    property_effect.reason,
                    *(item.provenance_id for item in governed_properties),
                    parameters=parameters,
                )
            else:
                directive_effect = {
                    DisclosureDirective.FORCE_SUMMARY: (
                        BlueprintEffectKind.FORCE_SUMMARY
                    ),
                    DisclosureDirective.ADD_REDACTION: (
                        BlueprintEffectKind.ADD_REDACTION
                    ),
                }.get(property_effect.directive)
                if directive_effect is None:
                    raise ValueError(
                        "amend disclosure policy requires a Blueprint effect"
                    )
                add(
                    "classified_property_disclosure",
                    ConstraintSeverity.AMEND,
                    property_effect.reason,
                    *(item.provenance_id for item in governed_properties),
                    parameters=parameters,
                    effect=directive_effect,
                )
        if focal_id and view.object_binding_is_ambiguous(focal_id):
            add(
                "ambiguous_object_binding",
                ConstraintSeverity.CLARIFY,
                "duplicate_object_identifier_or_reference_requires_resolution",
                f"object:{focal_id}",
            )
        if focal_id and focal_id not in view.objects_by_id():
            add(
                "historical_object_not_current",
                ConstraintSeverity.CLARIFY,
                "historical_focal_requires_non_executing_resolution",
                "session:last_focal_snapshot",
            )

        stop_ids = intent.current_ids(
            EvidenceKind.STOP_PROCESS,
            minimum=EvidenceStrength.DECISIVE,
        )
        if stop_ids:
            add(
                "decisive_user_stop",
                ConstraintSeverity.HARD,
                "user_stopped_operation",
                *stop_ids,
            )
        cancel_ids = intent.current_ids(
            EvidenceKind.CANCEL_ACTION,
            minimum=EvidenceStrength.DECISIVE,
        )
        if cancel_ids and action == DomainAction.DISPATCH:
            add(
                "decisive_dispatch_cancel",
                ConstraintSeverity.HARD,
                "user_cancelled_dispatch",
                *cancel_ids,
            )

        relevant_conflicts = {
            DomainAction.DISPATCH: {
                "resolved_target",
                "target_changed_after_turn",
                "ambiguous_target",
                "ambiguous_focal",
                "dispatch_authority_check",
                "share_boundary_update",
                "external_share_policy",
                "consent",
                "security_alert",
            },
            DomainAction.PAY: {
                "payment_policy",
                "security_alert",
                "trusted_subscription",
            },
            DomainAction.TOGGLE: {
                "safety_mode",
                "duration_ambiguous",
                "temporary_override_allowed",
            },
            DomainAction.SCHEDULE: {"calendar_conflict"},
        }.get(action, set())
        for record_type in sorted(
            view.duplicate_record_types() & relevant_conflicts
        ):
            ids = view.record_source_ids(record_type)
            add(
                f"conflicting_record:{record_type}",
                ConstraintSeverity.CLARIFY,
                "conflicting_record_state_requires_resolution",
                *ids,
            )

        if (
            action == DomainAction.DISPATCH
            and not target_is_local
            and view.record_code(RecordType.CONSENT)
            == RecordCode.CONSENT_REVOKED
        ):
            add(
                "consent_revoked",
                ConstraintSeverity.HARD,
                "consent_revoked_for_dispatch",
                "record:consent",
            )
        if (
            action == DomainAction.DISPATCH
            and not target_is_local
            and view.record_present(RecordType.SECURITY_ALERT)
        ):
            add(
                "security_alert",
                ConstraintSeverity.HARD,
                "security_alert_for_dispatch",
                "record:security_alert",
            )
        if action == DomainAction.PAY and view.record_present(
            RecordType.SECURITY_ALERT
        ):
            add(
                "security_alert",
                ConstraintSeverity.HARD,
                "security_alert_for_payment",
                "record:security_alert",
            )
        if action == DomainAction.TOGGLE and view.record_present(
            RecordType.SAFETY_MODE
        ):
            add(
                "safety_mode",
                ConstraintSeverity.HARD,
                "safety_mode_for_device_action",
                "record:safety_mode",
            )
        if action == DomainAction.PAY and view.record_present(
            RecordType.PAYMENT_POLICY
        ):
            add(
                "payment_policy",
                ConstraintSeverity.CLARIFY,
                "payment_policy_requires_resolution",
                "record:payment_policy",
            )
        trusted_subscription = view.record_reference(
            RecordType.TRUSTED_SUBSCRIPTION
        )
        if (
            action == DomainAction.PAY
            and trusted_subscription
            and trusted_subscription != pair.target
        ):
            add(
                "trusted_subscription_mismatch",
                ConstraintSeverity.CLARIFY,
                "payment_merchant_not_trusted_subscription",
                "record:trusted_subscription",
            )
        if action == DomainAction.SCHEDULE and view.record_present(
            RecordType.CALENDAR_CONFLICT
        ):
            add(
                "calendar_conflict",
                ConstraintSeverity.CLARIFY,
                "calendar_conflict_requires_resolution",
                "record:calendar_conflict",
            )
        if action == DomainAction.TOGGLE and view.record_present(
            RecordType.DURATION_AMBIGUOUS
        ):
            add(
                "duration_ambiguous",
                ConstraintSeverity.CLARIFY,
                "duration_requires_resolution",
                "record:duration_ambiguous",
            )
        temporary_override = view.record_duration()
        if action == DomainAction.TOGGLE and temporary_override:
            add(
                "temporary_override",
                ConstraintSeverity.AMEND,
                "temporary_duration_limits_toggle",
                "record:temporary_override_allowed",
                parameters=(("duration", temporary_override.canonical),),
                effect=BlueprintEffectKind.LIMIT_DURATION,
            )

        clarification_ids = intent.current_ids(
            EvidenceKind.CLARIFICATION_REQUEST,
            minimum=EvidenceStrength.DECISIVE,
        )
        if clarification_ids:
            add(
                "explicit_clarification",
                ConstraintSeverity.CLARIFY,
                "user_requested_clarification",
                *clarification_ids,
            )
        untrusted_target_ids = tuple(
            source_id
            for source_id in pair.derived_from
            if source_id.startswith("persistent_memory:untrusted:")
            or source_id.startswith("recall_record:untrusted:")
        )
        if untrusted_target_ids:
            add(
                "recalled_target_requires_confirmation",
                ConstraintSeverity.CLARIFY,
                "recalled_target_identity_is_not_execution_authority",
                *untrusted_target_ids,
            )
        redaction_ids = intent.current_ids(
            EvidenceKind.REDACTION_REQUEST,
            minimum=EvidenceStrength.STRONG,
        )
        if action == DomainAction.DISPATCH and redaction_ids:
            add(
                "explicit_redaction",
                ConstraintSeverity.AMEND,
                "user_requested_redaction",
                *redaction_ids,
                effect=BlueprintEffectKind.ADD_REDACTION,
            )
        policy = view.record_code(RecordType.EXTERNAL_SHARE_POLICY)
        if action == DomainAction.DISPATCH and not target_is_local and policy:
            if (
                focal.get("type") == "health_record"
                and policy == RecordCode.EXTERNAL_DOCTOR_NOTE_FORBIDDEN
            ):
                add(
                    "health_external_share_blocked",
                    ConstraintSeverity.HARD,
                    "doctor_note_forbidden",
                    "record:external_share_policy",
                )
            else:
                add(
                    "external_share_policy",
                    ConstraintSeverity.AMEND,
                    "external_scope_restricted",
                    "record:external_share_policy",
                    effect=BlueprintEffectKind.ADD_REDACTION,
                )

        if action == DomainAction.DISPATCH:
            explicit_domain = {
                item.payload
                for item in intent.prompt_evidence(
                    EvidenceKind.EXPLICIT_DOMAIN_VERB,
                    minimum=EvidenceStrength.SUPPORTING,
                )
            }
            if "PAY" in explicit_domain and view.record_present(
                RecordType.PAYMENT_POLICY
            ):
                add(
                    "payment_policy",
                    ConstraintSeverity.CLARIFY,
                    "payment_policy_requires_resolution",
                    "record:payment_policy",
                )
            cls._collect_dispatch_constraints(
                view,
                evidence_graph,
                focal,
                pair,
                constraints,
            )
        return tuple(constraints)

    @classmethod
    def _collect_dispatch_constraints(
        cls,
        view: Any,
        evidence_graph: Any,
        focal: dict[str, Any],
        pair: ActionTargetCandidate,
        constraints: list[ActiveConstraint],
    ) -> None:
        existing = {constraint.kind for constraint in constraints}

        def add(
            kind: str,
            severity: ConstraintSeverity,
            reason: str,
            *ids: str,
            effect: BlueprintEffectKind | None = None,
        ) -> None:
            if kind not in existing:
                constraints.append(
                    ActiveConstraint(
                        f"constraint:{pair.candidate_id}:{kind}",
                        kind,
                        severity,
                        reason,
                        tuple(ids),
                        effect=effect,
                    )
                )
                existing.add(kind)

        if (
            view.record_code(RecordType.ENTERPRISE_POLICY_RECALL)
            == RecordCode.ENTERPRISE_APPLY_STANDING_DEFAULT
        ):
            add(
                "enterprise_policy_recall",
                ConstraintSeverity.AMEND,
                "standing_policy_requires_minimal_disclosure",
                "record:enterprise_policy_recall",
                effect=BlueprintEffectKind.ADD_REDACTION,
            )
        if (
            view.record_code(RecordType.OPS_MEMORY_RECALL)
            == RecordCode.OPS_USE_PRIOR_RESULTS
        ):
            add(
                "ops_memory_recall",
                ConstraintSeverity.AMEND,
                "prior_route_requires_minimal_disclosure",
                "record:ops_memory_recall",
                effect=BlueprintEffectKind.ADD_REDACTION,
            )
        if view.record_present(RecordType.MEMORY_CONFLICT):
            add(
                "memory_conflict",
                ConstraintSeverity.CLARIFY,
                "memory_conflict_requires_resolution",
                "record:memory_conflict",
            )
        if view.record_present(RecordType.TARGET_CHANGED_AFTER_TURN):
            add(
                "target_changed",
                ConstraintSeverity.CLARIFY,
                "target_changed_requires_resolution",
                "record:target_changed_after_turn",
            )
        if (
            view.record_present(RecordType.PERSISTENT_MEMORY_RECALL)
            and evidence_graph.intent_evidence.prompt_evidence(
                EvidenceKind.VALUE_TRANSFER_REQUEST
            )
            and not view.record_present(RecordType.PAYMENT_POLICY)
        ):
            add(
                "stale_coupon_memory",
                ConstraintSeverity.HARD,
                "stale_payment_memory",
                "record:persistent_memory_recall",
            )

        boundary = view.record_code(RecordType.SHARE_BOUNDARY_UPDATE)
        ambiguous = view.record_code(RecordType.AMBIGUOUS_TARGET)
        authority = view.record_code(RecordType.DISPATCH_AUTHORITY_CHECK)
        candidates = view.record_code(RecordType.ROUTE_CANDIDATE_SNAPSHOT)
        has_redaction = bool(
            evidence_graph.intent_evidence.current(
                EvidenceKind.REDACTION_REQUEST,
                minimum=EvidenceStrength.STRONG,
            )
        )

        if boundary == RecordCode.SHARE_BOUNDARY_BLOCKED:
            if has_redaction:
                add(
                    "blocked_route_redaction",
                    ConstraintSeverity.AMEND,
                    "redaction_is_safe_fallback",
                    "record:share_boundary_update",
                    effect=BlueprintEffectKind.ADD_REDACTION,
                )
            elif view.record_present(RecordType.GUARDRAIL_LADDER_SIGNAL):
                add(
                    "blocked_route_guardrail",
                    ConstraintSeverity.HARD,
                    "guardrail_blocks_unbound_route",
                    "record:guardrail_ladder_signal",
                )
            elif (
                view.record_present(RecordType.AMBIGUOUS_FOCAL)
                and authority == RecordCode.AUTHORITY_USER_PENDING
            ):
                add(
                    "blocked_route_ambiguous_focal",
                    ConstraintSeverity.HARD,
                    "focal_and_route_unbound",
                    "record:ambiguous_focal",
                )
            elif authority in {
                RecordCode.AUTHORITY_INCOMPLETE,
                RecordCode.AUTHORITY_USER_PENDING,
            }:
                add(
                    "unresolved_route",
                    ConstraintSeverity.CLARIFY,
                    "route_binding_required",
                    "record:dispatch_authority_check",
                )
        elif boundary == RecordCode.SHARE_BOUNDARY_LOCAL:
            if ambiguous == RecordCode.AMBIGUOUS_STORED_OR_VISIBLE:
                if pair.target_confidence in {"decisive", "high"}:
                    add(
                        "local_boundary_stored_channel_restriction",
                        ConstraintSeverity.AMEND,
                        "selected_stored_channel_requires_redaction",
                        "record:ambiguous_target",
                        effect=BlueprintEffectKind.ADD_REDACTION,
                    )
                else:
                    add(
                        "local_boundary_stored_channel_conflict",
                        ConstraintSeverity.CLARIFY,
                        "stored_channel_conflicts_with_local_boundary",
                        "record:ambiguous_target",
                    )
            elif ambiguous == RecordCode.AMBIGUOUS_APPROVED_OR_VISIBLE:
                add(
                    "local_boundary_approval_ambiguity",
                    ConstraintSeverity.CLARIFY,
                    "approval_route_ambiguous",
                    "record:ambiguous_target",
                )
            elif ambiguous == RecordCode.AMBIGUOUS_RECENT_SURFACE_OR_RESOLVED:
                resolved_target = view.record_reference(
                    RecordType.RESOLVED_TARGET
                )
                if resolved_target and pair.target == resolved_target:
                    add(
                        "local_boundary_recent_target_restriction",
                        ConstraintSeverity.AMEND,
                        "selected_resolved_target_requires_redaction",
                        "record:ambiguous_target",
                        effect=BlueprintEffectKind.ADD_REDACTION,
                    )
                else:
                    add(
                        "local_boundary_recent_target_conflict",
                        ConstraintSeverity.CLARIFY,
                        "recent_targets_conflict",
                        "record:ambiguous_target",
                    )
        elif boundary in {
            RecordCode.SHARE_BOUNDARY_REDACTED_EXTERNAL,
            RecordCode.SHARE_BOUNDARY_REDACTED_AFTER_SELECTION,
        }:
            if ambiguous == RecordCode.AMBIGUOUS_RECENT_SURFACE_OR_RESOLVED:
                add(
                    "external_boundary_recent_target_conflict",
                    ConstraintSeverity.CLARIFY,
                    "recent_targets_conflict",
                    "record:ambiguous_target",
                )
            elif (
                ambiguous == RecordCode.AMBIGUOUS_STORED_OR_VISIBLE
                and view.record_present(RecordType.PERSISTENT_MEMORY_RECALL)
            ):
                add(
                    "external_boundary_memory_target_conflict",
                    ConstraintSeverity.CLARIFY,
                    "stored_route_conflicts_with_visible_target",
                    "record:ambiguous_target",
                )
            elif not (
                view.record_present(RecordType.GUARDRAIL_LADDER_SIGNAL)
                and authority == RecordCode.AUTHORITY_INTERNAL_CONFIRMED
            ):
                add(
                    "redacted_external_boundary",
                    ConstraintSeverity.AMEND,
                    "external_boundary_requires_redaction",
                    "record:share_boundary_update",
                    effect=BlueprintEffectKind.ADD_REDACTION,
                )

        if (
            view.record_present(RecordType.AMBIGUOUS_FOCAL)
            and view.record_code(RecordType.SESSION_SHARE_POLICY)
            == RecordCode.SESSION_POLICY_NORMAL
        ):
            add(
                "ambiguous_focal",
                ConstraintSeverity.CLARIFY,
                "focal_ambiguity_unresolved",
                "record:ambiguous_focal",
            )
        if view.record_present(RecordType.AMBIGUOUS_TARGET) or view.record_present(
            RecordType.AMBIGUOUS_FOCAL
        ):
            unresolved = (
                authority
                in {
                    RecordCode.AUTHORITY_INCOMPLETE,
                    RecordCode.AUTHORITY_USER_PENDING,
                }
                and boundary == RecordCode.SHARE_BOUNDARY_BLOCKED
            ) or (
                candidates == RecordCode.CANDIDATES_EXTERNAL_PRESENT
                and authority != RecordCode.AUTHORITY_INTERNAL_CONFIRMED
                and boundary
                not in {
                    RecordCode.SHARE_BOUNDARY_REDACTED_EXTERNAL,
                    RecordCode.SHARE_BOUNDARY_REDACTED_AFTER_SELECTION,
                }
            )
            if has_redaction and boundary == RecordCode.SHARE_BOUNDARY_BLOCKED:
                unresolved = False
            if unresolved:
                add(
                    "unresolved_ambiguity",
                    ConstraintSeverity.CLARIFY,
                    "target_or_focal_ambiguity",
                    "record:ambiguous_target",
                )

        if view.record_present(RecordType.AMBIGUOUS_TARGET) and view.record_present(
            RecordType.RESOLVED_TARGET
        ):
            resolved_target = view.record_reference(RecordType.RESOLVED_TARGET)
            if pair.target == resolved_target:
                add(
                    "resolved_target_restriction",
                    ConstraintSeverity.AMEND,
                    "selected_resolved_target_over_surface_target",
                    "record:resolved_target",
                    effect=BlueprintEffectKind.RESTRICT_TARGET,
                )
            else:
                add(
                    "resolved_target_conflict",
                    ConstraintSeverity.CLARIFY,
                    "surface_and_resolved_targets_conflict",
                    "record:resolved_target",
                )
        if (
            view.record_code(RecordType.SESSION_SHARE_POLICY)
            == RecordCode.SESSION_POLICY_STRICT
            and view.record_present(RecordType.RESOLVED_TARGET)
            and boundary != RecordCode.SHARE_BOUNDARY_LOCAL
            and not cls.raw_dispatch_allowed(view, focal, pair.target)
        ):
            add(
                "strict_share_policy",
                ConstraintSeverity.AMEND,
                "strict_policy_requires_minimal_disclosure",
                "record:session_share_policy",
                effect=BlueprintEffectKind.FORCE_SUMMARY,
            )

    @staticmethod
    def raw_dispatch_allowed(
        view: Any,
        focal: dict[str, Any],
        target: str,
    ) -> bool:
        property_effect = evaluate_disclosure_properties(
            describe_object_properties(focal)
        )
        if "raw" not in property_effect.permitted_modes:
            return False
        if (
            view.record_present(RecordType.GUARDRAIL_LADDER_SIGNAL)
            and view.record_code(RecordType.SHARE_BOUNDARY_UPDATE)
            == RecordCode.SHARE_BOUNDARY_REDACTED_EXTERNAL
            and view.record_code(RecordType.DISPATCH_AUTHORITY_CHECK)
            == RecordCode.AUTHORITY_INTERNAL_CONFIRMED
        ):
            return True
        if (
            view.record_code(RecordType.SESSION_SHARE_POLICY)
            != RecordCode.SESSION_POLICY_NORMAL
        ):
            return False
        if view.record_present(RecordType.EXTERNAL_SHARE_POLICY):
            return False
        if view.record_present(RecordType.AMBIGUOUS_TARGET) or view.record_present(
            RecordType.AMBIGUOUS_FOCAL
        ):
            return False
        attrs = focal.get("attrs") or {}
        return (
            focal.get("type") == "message"
            and str(attrs.get("recipient") or "") == target
            and "raw" in property_effect.permitted_modes
        )


class FallbackEdgeBuilder:
    @staticmethod
    def build(
        evaluations: list[CandidateEvaluation],
        evidence_graph: Any,
    ) -> tuple[FallbackEdge, ...]:
        cancel_ids = evidence_graph.intent_evidence.current_ids(
            EvidenceKind.CANCEL_ACTION,
            minimum=EvidenceStrength.STRONG,
        )
        local_ids = evidence_graph.intent_evidence.prompt_ids(
            EvidenceKind.LOCAL_UPDATE_REQUEST,
            minimum=EvidenceStrength.STRONG,
        )
        if not cancel_ids or not local_ids:
            return ()
        sources = [
            item
            for item in evaluations
            if item.candidate.action_candidate.action == DomainAction.DISPATCH
        ]
        destinations = [
            item
            for item in evaluations
            if item.candidate.action_candidate.action
            in {DomainAction.LOCAL_UPDATE, DomainAction.MEMORY_UPDATE}
        ]
        return tuple(
            FallbackEdge(
                edge_id=(
                    f"fallback:{source.candidate.candidate_id}:"
                    f"{destination.candidate.candidate_id}"
                ),
                source_candidate_id=source.candidate.candidate_id,
                destination_candidate_id=destination.candidate.candidate_id,
                authorization_source="current_user_explicit_replacement",
                semantic_preservation="explicit_operation_replacement",
                activation_condition="source_non_executable",
                reason_code="USER_AUTHORIZED_LOCAL_REPLACEMENT",
                derived_from=tuple(dict.fromkeys(cancel_ids + local_ids)),
            )
            for source in sources
            for destination in destinations
        )


class OperationBundleAnalyzer:
    """Classifies candidate multiplicity without choosing or rewriting meaning."""

    @staticmethod
    def analyze(
        actions: tuple[ActionCandidate, ...],
        evaluations: list[CandidateEvaluation],
        edges: tuple[FallbackEdge, ...],
        evidence_graph: Any,
    ) -> OperationBundle:
        direct_evidence_ids = {
            item.evidence_id
            for item in evidence_graph.intent_evidence.prompt_evidence()
        }
        active_actions = tuple(
            action
            for action in actions
            if action.action != DomainAction.UNRESOLVED
            and action.candidate_role == "primary"
            and direct_evidence_ids.intersection(action.derived_from)
        )
        action_ids = tuple(
            sorted(action.candidate_id for action in active_actions)
        )
        operation_keys = tuple(
            sorted(
                f"{action.action.value}:{action.operation_mode}"
                for action in active_actions
            )
        )
        pair_to_action = {
            item.candidate.candidate_id:
            item.candidate.action_candidate.candidate_id
            for item in evaluations
        }
        pair_ids = tuple(
            sorted(
                pair_id
                for pair_id, action_id in pair_to_action.items()
                if action_id in action_ids
            )
        )
        derived_from = tuple(
            dict.fromkeys(
                evidence_id
                for action in active_actions
                for evidence_id in action.derived_from
                if evidence_id in direct_evidence_ids
            )
        )
        if len(action_ids) <= 1:
            return OperationBundle(
                OperationBundleStatus.SINGLE,
                action_ids,
                operation_keys,
                pair_ids,
                derived_from,
            )

        parent = {action_id: action_id for action_id in action_ids}

        def find(action_id: str) -> str:
            while parent[action_id] != action_id:
                parent[action_id] = parent[parent[action_id]]
                action_id = parent[action_id]
            return action_id

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for edge in edges:
            if not edge.is_authorized:
                continue
            source_action = pair_to_action.get(edge.source_candidate_id)
            destination_action = pair_to_action.get(edge.destination_candidate_id)
            if source_action in parent and destination_action in parent:
                union(source_action, destination_action)

        component_count = len({find(action_id) for action_id in action_ids})
        status = (
            OperationBundleStatus.AUTHORIZED_REPLACEMENT
            if component_count == 1
            else OperationBundleStatus.MULTIPLE_UNRESOLVED
        )
        return OperationBundle(
            status,
            action_ids,
            operation_keys,
            pair_ids,
            derived_from,
        )


class AuthorizedFallbackSolver:
    """Consumes explicit candidate edges; text never authorizes a fallback here."""

    @classmethod
    def solve(
        cls,
        evaluations: list[CandidateEvaluation],
        edges: tuple[FallbackEdge, ...],
        operation_bundle: OperationBundle,
    ) -> tuple[SelectionResolution, FallbackResolution]:
        if not evaluations:
            raise ValueError("decision matrix has no candidates")
        confidence_rank = {
            "decisive": 4,
            "high": 3,
            "medium": 2,
            "low": 1,
            "none": 0,
        }
        ordered = sorted(
            evaluations,
            key=lambda item: (
                -cls._role_rank(
                    item.candidate.action_candidate.candidate_role
                ),
                -item.candidate.action_candidate.intent_rank,
                -confidence_rank.get(item.candidate.target_confidence, 0),
                item.candidate.candidate_id,
            ),
        )
        preferred_key = (
            cls._role_rank(
                ordered[0].candidate.action_candidate.candidate_role
            ),
            ordered[0].candidate.action_candidate.intent_rank,
        )
        preferred = [
            item
            for item in ordered
            if (
                cls._role_rank(
                    item.candidate.action_candidate.candidate_role
                ),
                item.candidate.action_candidate.intent_rank,
            )
            == preferred_key
        ]
        preferred_ids = tuple(item.candidate.candidate_id for item in preferred)
        selected_preferred = CandidateEvaluator._select_target_or_ask(preferred)
        preferred_evaluation = selected_preferred.evaluation
        by_id = {item.candidate.candidate_id: item for item in evaluations}

        constraint_severities = {
            item.severity for item in preferred_evaluation.active_constraints
        }
        constraint_kinds = {
            item.kind for item in preferred_evaluation.active_constraints
        }
        if (
            selected_preferred.disposition == CandidateDisposition.BLOCKED
            and ConstraintSeverity.HARD in constraint_severities
            and "explicit_clarification" in constraint_kinds
        ):
            # The execution candidate remains HARD-blocked.  Only the separate
            # non-executing interaction is selected, so ASK never authorizes
            # the blocked dispatch.
            gate = DecisionGate(
                gate_id=(
                    f"gate:{preferred_evaluation.candidate.candidate_id}:"
                    "blocked_execution_clarification"
                ),
                kind="blocked_execution_clarification",
                disposition=CandidateDisposition.NEEDS_CONFIRMATION,
                reason="blocked_execution_may_only_request_user_confirmation",
                derived_from=preferred_evaluation.derived_from,
            )
            selection = SelectionResolution(
                preferred_evaluation,
                CandidateDisposition.NEEDS_CONFIRMATION,
                selected_preferred.gates + (gate,),
            )
            return selection, FallbackResolution(
                selected_candidate_id=preferred_evaluation.candidate.candidate_id,
                preferred_candidate_ids=preferred_ids,
                fallback_applied=False,
                reason=FallbackReason.USER_CHOICE_REQUIRED,
                authorized_candidate_ids=(),
                derived_from=preferred_evaluation.derived_from,
            )

        if (
            operation_bundle.status
            == OperationBundleStatus.MULTIPLE_UNRESOLVED
            and selected_preferred.disposition != CandidateDisposition.BLOCKED
            and not any(
                constraint.severity == ConstraintSeverity.HARD
                for constraint in preferred_evaluation.active_constraints
            )
        ):
            gate = DecisionGate(
                gate_id=(
                    f"gate:{preferred_evaluation.candidate.candidate_id}:"
                    "multi_operation_unsupported"
                ),
                kind="multi_operation_unsupported",
                disposition=CandidateDisposition.NEEDS_CLARIFICATION,
                reason="independent_operations_require_bundle_resolution",
                derived_from=operation_bundle.derived_from,
            )
            selection = SelectionResolution(
                preferred_evaluation,
                CandidateDisposition.NEEDS_CLARIFICATION,
                selected_preferred.gates + (gate,),
            )
            return selection, FallbackResolution(
                selected_candidate_id=preferred_evaluation.candidate.candidate_id,
                preferred_candidate_ids=preferred_ids,
                fallback_applied=False,
                reason=FallbackReason.USER_CHOICE_REQUIRED,
                authorized_candidate_ids=(),
                derived_from=operation_bundle.derived_from,
            )

        applicable_edges = [
            edge
            for edge in edges
            if edge.is_authorized
            and edge.source_candidate_id in preferred_ids
            and cls._edge_is_active(edge, by_id[edge.source_candidate_id])
        ]
        destinations = [
            by_id[edge.destination_candidate_id]
            for edge in applicable_edges
            if edge.destination_candidate_id in by_id
            and by_id[edge.destination_candidate_id].capability_status
            == CapabilityStatus.AVAILABLE
            and by_id[edge.destination_candidate_id].disposition
            in {CandidateDisposition.EXECUTABLE, CandidateDisposition.AMENDABLE}
        ]
        unique_destinations = {
            item.candidate.candidate_id: item for item in destinations
        }
        if len(unique_destinations) == 1:
            selected = next(iter(unique_destinations.values()))
            selection = SelectionResolution(selected, selected.disposition)
            return selection, FallbackResolution(
                selected_candidate_id=selected.candidate.candidate_id,
                preferred_candidate_ids=preferred_ids,
                fallback_applied=True,
                reason=FallbackReason.AUTHORIZED_FALLBACK_SELECTED,
                authorized_candidate_ids=(selected.candidate.candidate_id,),
                derived_from=tuple(
                    dict.fromkeys(
                        evidence_id
                        for edge in applicable_edges
                        if edge.destination_candidate_id
                        == selected.candidate.candidate_id
                        for evidence_id in (edge.edge_id,) + edge.derived_from
                    )
                ),
            )
        if len(unique_destinations) > 1:
            selected = sorted(
                unique_destinations.values(),
                key=lambda item: item.candidate.candidate_id,
            )[0]
            alternatives = tuple(sorted(unique_destinations))
            gate = DecisionGate(
                gate_id=(
                    f"gate:{selected.candidate.candidate_id}:"
                    "multiple_authorized_fallbacks"
                ),
                kind="multiple_authorized_fallbacks",
                disposition=CandidateDisposition.NEEDS_CLARIFICATION,
                reason="user_choice_required_between_authorized_fallbacks",
                derived_from=alternatives,
            )
            selection = SelectionResolution(
                selected,
                CandidateDisposition.NEEDS_CLARIFICATION,
                (gate,),
            )
            return selection, FallbackResolution(
                selected_candidate_id=selected.candidate.candidate_id,
                preferred_candidate_ids=preferred_ids,
                fallback_applied=False,
                reason=FallbackReason.USER_CHOICE_REQUIRED,
                authorized_candidate_ids=alternatives,
                derived_from=tuple(edge.edge_id for edge in applicable_edges),
            )

        user_choice = any(
            gate.kind == "multiple_executable_alternatives"
            for gate in selected_preferred.gates
        )
        unavailable = (
            preferred_evaluation.capability_status
            == CapabilityStatus.UNAVAILABLE
            or selected_preferred.disposition == CandidateDisposition.BLOCKED
        )
        return selected_preferred, FallbackResolution(
            selected_candidate_id=preferred_evaluation.candidate.candidate_id,
            preferred_candidate_ids=preferred_ids,
            fallback_applied=False,
            reason=(
                FallbackReason.USER_CHOICE_REQUIRED
                if user_choice
                else FallbackReason.NO_AUTHORIZED_FALLBACK
                if unavailable
                else FallbackReason.NOT_NEEDED
            ),
            authorized_candidate_ids=(),
            derived_from=preferred_evaluation.derived_from,
        )

    @staticmethod
    def _role_rank(role: str) -> int:
        return {
            "primary": 4,
            "structural": 3,
            "contextual": 2,
            "negated": 1,
            "unresolved": 0,
        }.get(role, 0)

    @staticmethod
    def _edge_is_active(
        edge: FallbackEdge,
        source: CandidateEvaluation,
    ) -> bool:
        if edge.activation_condition == "source_non_executable":
            return source.disposition in {
                CandidateDisposition.BLOCKED,
                CandidateDisposition.NEEDS_INFORMATION,
                CandidateDisposition.NEEDS_CONFIRMATION,
                CandidateDisposition.CONFLICTED,
                CandidateDisposition.UNSUPPORTED_RULEPACK,
            }
        if edge.activation_condition == "source_capability_unavailable":
            return source.capability_status == CapabilityStatus.UNAVAILABLE
        return False


class FinalDecisionBuilder:
    @classmethod
    def build(cls, state: Any, matrix: DecisionMatrix) -> FinalDecision:
        selected = matrix.selected
        control = CandidateDispositionPolicy.execution_disposition(
            matrix.selection.disposition
        ).value
        target, target_source = cls._output_target(
            state,
            selected,
            control,
            matrix.selection.gates,
        )
        (
            disclosure_mode,
            allowed_fields,
            excluded_fields,
            exclusion_provenance,
            scope_requires_confirmation,
        ) = cls._disclosure_projection(state, selected, control)
        policy_requires_confirmation = cls._policy_requires_confirmation(
            state,
            control,
        )
        final_plan_capabilities = selected.effective_blueprint.capabilities_for(
            matrix.selection.disposition.value
        )
        risk_flags, violations = cls._policy_projection(
            state,
            selected,
            target,
            control,
        )
        plan_steps = cls._plan_projection(
            state,
            selected,
            target,
            final_plan_capabilities,
            disclosure_mode,
            excluded_fields,
        )
        projected_verbs = tuple(step.verb for step in plan_steps)
        _, missing_plan_capabilities = CapabilityResolver.resolve(
            state.view,
            final_plan_capabilities,
        )
        expected_plan_verbs = tuple(
            capability
            for capability in final_plan_capabilities
            if capability in state.view.available_actions
        )
        emitted_plan_verbs = projected_verbs
        if emitted_plan_verbs != expected_plan_verbs:
            raise ValueError(
                "resolved plan diverges from final capability contract: "
                f"expected={expected_plan_verbs} emitted={emitted_plan_verbs}"
            )
        reason_code = cls._reason_code(selected, matrix.selection.gates)
        operation_mode = selected.candidate.action_candidate.operation_mode
        domain_actions = {
            DomainAction.PAY,
            DomainAction.TOGGLE,
            DomainAction.SCHEDULE,
        }
        execution_emitted = (
            selected.candidate.action_candidate.action in domain_actions
            and operation_mode == "execute"
            and control in {"proceed", "amend"}
        )
        traces = tuple(
            replace(
                trace,
                selected_pair_id=(
                    selected.candidate.candidate_id
                    if trace.domain_context_applied
                    else trace.selected_pair_id
                ),
                execution_emitted=(
                    execution_emitted and trace.domain_context_applied
                ),
            )
            for trace in matrix.promotion_traces
        )
        derived = tuple(
            dict.fromkeys(
                selected.derived_from
                + selected.information.derived_from
                + tuple(
                    evidence_id
                    for gate in matrix.selection.gates
                    for evidence_id in gate.derived_from
                )
                + tuple(
                    evidence_id
                    for constraint in selected.active_constraints
                    for evidence_id in constraint.derived_from
                )
            )
        )
        unresolved_assumption_refs = list(selected.assumption_refs)
        unresolved_assumption_refs.append(TARGET_ASSUMPTION_ID)
        if matrix.selection.gates:
            unresolved_assumption_refs.append(BUNDLE_ASSUMPTION_ID)
        if matrix.fallback.fallback_applied:
            unresolved_assumption_refs.append(FALLBACK_ASSUMPTION_ID)
        return FinalDecision(
            focal_id=state.focal_decision.focal_id,
            selected_pair_id=selected.candidate.candidate_id,
            action=selected.candidate.action_candidate.action,
            operation_mode=operation_mode,
            operation_target=selected.candidate.target,
            operation_target_role=selected.candidate.target_role,
            operation_target_locality=selected.candidate.target_locality,
            target=target,
            target_source=target_source,
            control=control,
            effective_blueprint=selected.effective_blueprint,
            information=selected.information,
            capability_status=selected.capability_status,
            required_capabilities=selected.required_capabilities,
            missing_capabilities=selected.missing_capabilities,
            final_plan_capabilities=final_plan_capabilities,
            missing_plan_capabilities=missing_plan_capabilities,
            active_constraints=selected.active_constraints,
            decision_gates=matrix.selection.gates,
            available_actions=tuple(sorted(state.view.available_actions)),
            disclosure_mode=disclosure_mode,
            allowed_fields=allowed_fields,
            excluded_fields=excluded_fields,
            exclusion_provenance=exclusion_provenance,
            scope_requires_user_confirmation=scope_requires_confirmation,
            policy_requires_confirmation=policy_requires_confirmation,
            risk_flags=risk_flags,
            violations=violations,
            plan_steps=plan_steps,
            fallback=matrix.fallback,
            domain_promotion=traces,
            reason_code=reason_code,
            historical_focal=(state.focal_decision.source == "session_snapshot"),
            unresolved_assumption_refs=tuple(
                dict.fromkeys(unresolved_assumption_refs)
            ),
            derived_from=derived,
        )

    @staticmethod
    def _disclosure_projection(
        state: Any,
        selected: CandidateEvaluation,
        control: str,
    ) -> tuple[
        str,
        tuple[str, ...],
        tuple[str, ...],
        tuple[tuple[str, tuple[str, ...]], ...],
        bool,
    ]:
        mode = FinalDecisionBuilder._safe_scope_mode(
            state,
            selected,
            control,
        )

        properties = describe_object_properties(state.focal)
        property_effect = evaluate_disclosure_properties(properties)
        if (
            selected.candidate.action_candidate.action == DomainAction.DISPATCH
            and mode not in property_effect.permitted_modes
        ):
            raise ValueError(
                "compiled disclosure mode violates property policy: "
                f"{mode} not in {sorted(property_effect.permitted_modes)}"
            )
        def code_value(record_type: RecordType) -> str:
            code = state.view.record_code(record_type)
            return code.value if code is not None else ""

        policy_exclusions = derive_policy_exclusions(
            properties,
            mode,
            object_type=str(state.focal.get("type") or ""),
            session_policy=code_value(RecordType.SESSION_SHARE_POLICY),
            external_policy=code_value(RecordType.EXTERNAL_SHARE_POLICY),
            privacy_guard=(
                "minor_location_protected"
                if state.view.record_present(RecordType.PRIVACY_GUARD)
                else ""
            ),
        )
        excluded = tuple(item.name for item in policy_exclusions)
        exclusion_provenance = policy_exclusions
        if mode == "status_only":
            allowed = ("status",)
        elif mode == "redacted":
            allowed = ("summary",)
        elif mode == "summary":
            allowed = ("summary",)
        elif mode == "raw":
            allowed = ("summary", "title")
        else:
            mode = "none"
            allowed = ()
        requires_confirmation = control == "ask" or (
            control == "amend"
            and FinalDecisionBuilder._target_is_ambiguous(state)
        )
        return (
            mode,
            allowed,
            excluded,
            exclusion_provenance,
            requires_confirmation,
        )

    @staticmethod
    def _safe_scope_mode(
        _state: Any,
        selected: CandidateEvaluation,
        control: str,
    ) -> str:
        """Project scope only from disposition and the compiled blueprint.

        Object kinds, record codes, prompt counts, and field names are not
        scope authorities here. They must first become typed constraints and
        blueprint effects in the upstream semantic pipeline.
        """
        hard_constraint_active = any(
            constraint.severity == ConstraintSeverity.HARD
            for constraint in selected.active_constraints
        )
        if hard_constraint_active:
            interaction_only = (
                control == "ask"
                and any(
                    constraint.kind == "explicit_clarification"
                    for constraint in selected.active_constraints
                )
            )
            if control == "hold":
                return "none"
            if not interaction_only:
                raise ValueError(
                    "a HARD constraint may only hold or select a non-executing "
                    "clarification interaction"
                )
        if control == "amend" and not selected.effective_blueprint.amended:
            raise ValueError(
                "amend requires a compiled blueprint effect before scope projection"
            )
        # ASK changes execution capabilities to read/clarify, but it does not
        # erase the independently compiled disclosure contract. Keeping the
        # Blueprint mode preserves redaction/summary restrictions while the
        # validator separately forbids execution events for clarification.
        return project_scope_mode(
            selected.effective_blueprint.scope_mode,
            control,
        )

    @staticmethod
    def _policy_requires_confirmation(
        state: Any,
        control: str,
    ) -> bool:
        """Project only the public confirmation signal from typed state."""
        if control == "ask":
            return True
        if control not in {"proceed", "amend"}:
            return False
        return FinalDecisionBuilder._target_is_ambiguous(state)

    @staticmethod
    def _target_is_ambiguous(state: Any) -> bool:
        view = state.view
        if view.record_present(RecordType.AMBIGUOUS_TARGET):
            return True
        return (
            view.record_present(RecordType.AMBIGUOUS_FOCAL)
            and view.record_code(RecordType.DISPATCH_AUTHORITY_CHECK)
            == RecordCode.AUTHORITY_USER_PENDING
        )

    @staticmethod
    def _precondition_changed(state: Any) -> bool:
        view = state.view
        return (
            view.record_code(RecordType.ROUTE_CANDIDATE_SNAPSHOT)
            == RecordCode.CANDIDATES_SINGLE_INTERNAL
            and view.record_code(RecordType.DISPATCH_AUTHORITY_CHECK)
            == RecordCode.AUTHORITY_INTERNAL_CONFIRMED
        )

    @staticmethod
    def _policy_projection(
        state: Any,
        selected: CandidateEvaluation,
        target: str,
        control: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Expose the canonical public policy ontology only.

        Constraint and decision-gate identifiers are internal implementation
        details.  Public policy is derived from typed records and the finalized
        control/target projection so those names can never leak into answers.
        """
        view = state.view
        flags: list[str] = []
        if (
            view.record_code(RecordType.SESSION_SHARE_POLICY)
            == RecordCode.SESSION_POLICY_STRICT
        ):
            flags.append("strict_share_policy")
        if target not in {"memory_store", "user"}:
            flags.append("external_share")
        if (
            target in {"memory_store", "user"}
            or view.record_code(RecordType.SHARE_BOUNDARY_UPDATE)
            == RecordCode.SHARE_BOUNDARY_LOCAL
        ):
            flags.append("local_only")
        if view.record_present(RecordType.AMBIGUOUS_FOCAL):
            flags.append("ambiguous_focal")
        if FinalDecisionBuilder._target_is_ambiguous(state):
            flags.append("target_ambiguity")
        if FinalDecisionBuilder._precondition_changed(state):
            flags.append("precondition_changed")
        if any(
            effect.kind
            in {
                BlueprintEffectKind.ADD_REDACTION,
                BlueprintEffectKind.FORCE_SUMMARY,
            }
            for effect in selected.effective_blueprint.effects
        ):
            flags.append("sensitive_content")
        has_minimal_disclosure_effect = any(
            effect.kind
            in {
                BlueprintEffectKind.ADD_REDACTION,
                BlueprintEffectKind.FORCE_SUMMARY,
            }
            for effect in selected.effective_blueprint.effects
        )
        has_clarification_basis = (
            selected.information.status
            in {InformationStatus.MISSING, InformationStatus.CONFLICT}
            or any(
                constraint.severity == ConstraintSeverity.CLARIFY
                for constraint in selected.active_constraints
            )
        )
        hard_constraints = tuple(
            constraint
            for constraint in selected.active_constraints
            if constraint.severity == ConstraintSeverity.HARD
        )
        if has_minimal_disclosure_effect and control == "amend":
            flags.append("minimal_disclosure")
        if has_clarification_basis:
            flags.append("clarification_required")
        if hard_constraints:
            flags.extend(("precondition_invalidated", "safety"))
        violations = (
            ("precondition_changed_ignored",) if hard_constraints else ()
        )
        return tuple(dict.fromkeys(flags)), violations

    @staticmethod
    def _plan_projection(
        state: Any,
        selected: CandidateEvaluation,
        target: str,
        plan_capabilities: tuple[str, ...],
        disclosure_mode: str,
        excluded_fields: tuple[str, ...],
    ) -> tuple[ResolvedPlanStep, ...]:
        focal_id = str(state.focal_decision.focal_id or "")
        available = state.view.available_actions
        steps: list[ResolvedPlanStep] = []

        def add(
            verb: str,
            event_target: str,
            args: dict[str, Any],
            *,
            optional: bool = False,
        ) -> None:
            if verb not in available:
                if optional:
                    return
                raise ValueError(
                    f"required plan capability is unavailable: {verb}"
                )
            steps.append(
                ResolvedPlanStep(
                    verb,
                    event_target,
                    tuple((key, str(value)) for key, value in args.items()),
                    optional,
                )
            )

        if plan_capabilities == ("read", "guard"):
            add("read", focal_id, {"purpose": "invalidated_precondition"})
            add("guard", focal_id, {"reason": "precondition_invalidated"})
            return tuple(steps)
        if plan_capabilities == ("read", "clarify"):
            precondition_changed = FinalDecisionBuilder._precondition_changed(
                state
            )
            purpose = (
                "clarify_precondition"
                if precondition_changed
                else "route_resolution_required"
            )
            reason = (
                "precondition_changed"
                if precondition_changed
                else "route_resolution_required"
            )
            add("read", focal_id, {"purpose": purpose})
            add("clarify", "user", {"reason": reason})
            return tuple(steps)

        action = selected.candidate.action_candidate.action
        operation_mode = selected.candidate.action_candidate.operation_mode
        slot_values = {
            slot.name: slot.value
            for slot in selected.required_slots
            if slot.status in {SlotStatus.PRESENT, SlotStatus.DEFAULTED}
        }
        if action in {DomainAction.LOCAL_UPDATE, DomainAction.MEMORY_UPDATE}:
            add("read", focal_id, {"purpose": "local_update"})
            add("verify", "share_boundary_update", {"scope": "local_update"})
            add("update", focal_id, {"state": "local_status_only"})
            return tuple(steps)
        if action in {DomainAction.PAY, DomainAction.TOGGLE, DomainAction.SCHEDULE}:
            add("read", focal_id, {"purpose": "inspect_context"})
            if operation_mode == "verify":
                add("verify", target, {"check": "precondition"})
                return tuple(steps)
            if action == DomainAction.PAY:
                add("verify", target, {"check": "payment_security_check"})
                add("pay", target, {"method": slot_values.get("method") or "payment_method_check"})
            elif action == DomainAction.TOGGLE:
                add("verify", target, {"check": "safe_routine"})
                args = {"state": slot_values.get("desired_state") or "enabled"}
                duration = next(
                    (
                        dict(effect.parameters).get("duration")
                        for effect in selected.effective_blueprint.effects
                        if effect.kind.value == "limit_duration"
                    ),
                    None,
                )
                if duration:
                    args["duration"] = duration
                add("toggle", target, args)
            else:
                add("verify", target, {"check": "conflict_check"})
                add("schedule", target, {"time": slot_values.get("time") or ""})
            return tuple(steps)

        add(
            "read",
            focal_id,
            {
                "purpose": (
                    "minimal_disclosure"
                    if disclosure_mode == "redacted"
                    else "inspect_context"
                )
            },
        )
        if disclosure_mode == "redacted":
            remove = (
                "sensitive_fields"
                if len(excluded_fields) > 1
                else excluded_fields[0]
                if excluded_fields
                else "sensitive_fields"
            )
            add("redact", focal_id, {"remove": remove})
        elif disclosure_mode == "summary":
            add("summarize", focal_id, {"mode": "summary"})
        add("dispatch", target, {"scope": disclosure_mode})
        return tuple(steps)

    @staticmethod
    def _output_target(
        state: Any,
        selected: CandidateEvaluation,
        control: str,
        decision_gates: tuple[DecisionGate, ...],
    ) -> tuple[str, str]:
        action = selected.candidate.action_candidate.action
        if action == DomainAction.CLARIFY:
            return "user", "clarification_target"
        if (
            action == DomainAction.LOCAL_UPDATE
            and control in {"proceed", "amend"}
            and "record:share_boundary_update:local"
            in selected.candidate.action_candidate.derived_from
        ):
            intended = next(
                (
                    candidate
                    for candidate in state.target_candidates
                    if candidate.target != "memory_store"
                    and candidate.confidence in {"decisive", "high"}
                ),
                None,
            )
            if intended is not None:
                return intended.target, "nonexecuted_intended_destination"
        if action == DomainAction.UNRESOLVED:
            confirmed = next(
                (
                    candidate
                    for candidate in state.target_candidates
                    if candidate.target
                    and candidate.confidence in {"decisive", "high"}
                ),
                None,
            )
            if confirmed is not None:
                return confirmed.target, confirmed.source
            return "user", "clarification_target"
        constraint_kinds = {
            constraint.kind for constraint in selected.active_constraints
        }
        if "decisive_user_stop" in constraint_kinds:
            return "user", "explicit_user_stop"
        if any(
            slot.reason_code == SlotReason.REQUIRED_MEMORY_UNAVAILABLE
            for slot in selected.required_slots
        ) and control == "ask":
            return "user", "required_memory_unavailable"
        if (
            "recalled_target_requires_confirmation" in constraint_kinds
            and control == "ask"
            and selected.candidate.target
        ):
            return (
                selected.candidate.target,
                "recalled_target_pending_confirmation",
            )
        if "explicit_clarification" in constraint_kinds and control == "ask":
            return "user", "explicit_user_clarification"
        if decision_gates and not selected.candidate.target:
            return "user", "decision_gate_clarification"
        if selected.candidate.target:
            return selected.candidate.target, selected.candidate.target_role.value
        return "user", "unresolved_target"

    @staticmethod
    def _reason_code(
        selected: CandidateEvaluation,
        decision_gates: tuple[DecisionGate, ...],
    ) -> str:
        if decision_gates:
            return f"DECISION_GATE:{decision_gates[0].kind}"
        if not selected.effective_blueprint.supported:
            return "UNSUPPORTED_OPERATION_BLUEPRINT"
        hard = next(
            (
                item.kind
                for item in selected.active_constraints
                if item.severity == ConstraintSeverity.HARD
            ),
            "",
        )
        if hard:
            return f"HARD_CONSTRAINT:{hard}"
        if selected.capability_status == CapabilityStatus.UNAVAILABLE:
            return "CAPABILITY_UNAVAILABLE"
        if selected.information.status == InformationStatus.CONFLICT:
            return "REQUIRED_INFORMATION_CONFLICT"
        if selected.information.status == InformationStatus.MISSING:
            return "REQUIRED_INFORMATION_MISSING"
        clarify = next(
            (
                item.kind
                for item in selected.active_constraints
                if item.severity == ConstraintSeverity.CLARIFY
            ),
            "",
        )
        if clarify:
            return f"CLARIFY_CONSTRAINT:{clarify}"
        amend = next(
            (
                item.kind
                for item in selected.active_constraints
                if item.severity == ConstraintSeverity.AMEND
            ),
            "",
        )
        if amend:
            return f"AMEND_CONSTRAINT:{amend}"
        return "EXECUTABLE"


class DecisionEngine:
    @classmethod
    def decide(cls, state: Any) -> tuple[DecisionMatrix, FinalDecision]:
        matrix = CandidateEvaluator.build_matrix(
            state.view,
            state.evidence,
            state.focal,
            state.target_candidates,
            state.operation_intent,
        )
        final = FinalDecisionBuilder.build(state, matrix)
        matrix = replace(matrix, promotion_traces=final.domain_promotion)
        return matrix, final
