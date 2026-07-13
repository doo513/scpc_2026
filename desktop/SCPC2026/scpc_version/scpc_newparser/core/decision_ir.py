from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
from typing import Any, Iterable

from .candidate_evaluation import (
    CandidateEvaluationResult,
    CandidateInformationStatus,
)
from .constraints import CandidateConstraint, ConstraintEffectInstance
from .contracts import (
    BUNDLE_ASSUMPTION_ID,
    DISPOSITION_PLAN_ASSUMPTION_ID,
    FALLBACK_ASSUMPTION_ID,
    TARGET_ASSUMPTION_ID,
    ContractStatus,
    assumption_ids,
)
from .facts import CapabilitySnapshot
from .ontology import (
    CandidateDispositionPolicy,
    CandidateState,
    CapabilityType,
    ConstraintEffect,
    DisclosureMode,
    Domain,
    ExecutionDisposition,
    FactStatus,
    Operation,
    PlanStepType,
    ReasonCode,
    TargetBindingContract,
    TargetLocality,
    TargetRole,
)
from .plan_requirements import FinalPlanRequirements, InternalTransformType


class ResponseTargetMappingStatus(str, Enum):
    CONFIRMED = "confirmed"
    ASSUMPTION_LINKED = "assumption_linked"
    UNRESOLVED = "unresolved"


class AggregateOutputStatus(str, Enum):
    SINGLE = "single"
    MULTIPLE_UNRESOLVED = "multiple_unresolved"


class DecisionDependencyKind(str, Enum):
    REQUIRES_SUCCESS = "requires_success"
    READ_AFTER_WRITE = "read_after_write"


@dataclass(frozen=True)
class ResponseTargetBinding:
    response_target: str
    mapping_status: ResponseTargetMappingStatus
    contract_status: ContractStatus
    contract_reference_ids: tuple[str, ...]
    derived_from: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.mapping_status == ResponseTargetMappingStatus.CONFIRMED:
            if (
                not self.response_target
                or self.contract_status != ContractStatus.CONFIRMED_CONTRACT
            ):
                raise ValueError("confirmed response target lacks confirmed contract")
        elif self.mapping_status == ResponseTargetMappingStatus.ASSUMPTION_LINKED:
            if not self.response_target or TARGET_ASSUMPTION_ID not in (
                self.contract_reference_ids
            ):
                raise ValueError("assumption-linked target lacks target assumption")
        elif self.response_target:
            raise ValueError("unresolved response target must not contain a value")
        for values, label in (
            (self.contract_reference_ids, "response target contract references"),
            (self.derived_from, "response target provenance"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and sorted")


@dataclass(frozen=True)
class DisclosureDecision:
    mode: DisclosureMode
    allowed_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    requires_user_confirmation: bool
    source_effect_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for values, label in (
            (self.allowed_fields, "allowed fields"),
            (self.excluded_fields, "excluded fields"),
            (self.source_effect_ids, "disclosure effect IDs"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and sorted")
        if set(self.allowed_fields) & set(self.excluded_fields):
            raise ValueError("disclosure field cannot be both allowed and excluded")


@dataclass(frozen=True)
class PolicyDecision:
    risk_flags: tuple[str, ...]
    violations: tuple[str, ...]
    requires_confirmation: bool
    source_constraint_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for values, label in (
            (self.risk_flags, "risk flags"),
            (self.violations, "violations"),
            (self.source_constraint_ids, "policy constraint IDs"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and sorted")


@dataclass(frozen=True)
class PlanProjectionStep:
    projection_step_id: str
    requirement_step_id: str
    verb: PlanStepType
    target: str
    args: tuple[tuple[str, str], ...]
    reason_codes: tuple[ReasonCode, ...]
    contract_reference_ids: tuple[str, ...] = ()
    semantic_terminal: bool = False

    def __post_init__(self) -> None:
        if not self.projection_step_id or not self.target:
            raise ValueError("plan projection step requires identity and target")
        names = [name for name, _value in self.args]
        if len(names) != len(set(names)):
            raise ValueError("plan projection args must have unique keys")
        if tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        ) != self.reason_codes:
            raise ValueError("plan projection reason codes must be canonical")
        if tuple(sorted(set(self.contract_reference_ids))) != (
            self.contract_reference_ids
        ):
            raise ValueError("plan projection contract references must be canonical")
        if self.semantic_terminal and not self.requirement_step_id:
            raise ValueError("semantic terminal requires requirement lineage")

    @property
    def capability(self) -> CapabilityType:
        return CapabilityType.parse(self.verb.value)


@dataclass(frozen=True)
class LockedPlanDecision:
    decision_id: str
    steps: tuple[PlanProjectionStep, ...]

    def __post_init__(self) -> None:
        ids = [item.projection_step_id for item in self.steps]
        if not self.decision_id or len(ids) != len(set(ids)):
            raise ValueError("locked plan has invalid or duplicate step identity")


@dataclass(frozen=True)
class FallbackOrigin:
    edge_id: str
    source_candidate_id: str
    destination_candidate_id: str
    authorization_reference_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.edge_id or not self.source_candidate_id:
            raise ValueError("fallback origin requires edge and source identity")
        if not self.destination_candidate_id:
            raise ValueError("fallback origin requires actual destination identity")
        if tuple(sorted(set(self.authorization_reference_ids))) != (
            self.authorization_reference_ids
        ):
            raise ValueError("fallback authorization references must be canonical")


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _canonicalize(getattr(value, item.name))
            for item in fields(value)
            if item.name not in {"lock_digest", "bundle_lock_digest"}
        }
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    if isinstance(value, frozenset):
        return sorted(_canonicalize(item) for item in value)
    if isinstance(value, dict):
        return {
            str(key): _canonicalize(child)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(
        _canonicalize(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class SubDecisionIR:
    decision_id: str
    selected_candidate_id: str
    domain: Domain
    operation: Operation
    focal_id: str
    execution_target: str
    execution_target_role: TargetRole
    execution_target_locality: TargetLocality
    response_target_binding: ResponseTargetBinding
    candidate_state: CandidateState
    execution_disposition: ExecutionDisposition
    disclosure: DisclosureDecision
    policy: PolicyDecision
    active_constraints: tuple[CandidateConstraint, ...]
    applied_safeguards: tuple[ConstraintEffectInstance, ...]
    modifications: tuple[ConstraintEffectInstance, ...]
    information_status: CandidateInformationStatus | None
    required_platform_capabilities: tuple[CapabilityType, ...]
    required_internal_transforms: tuple[InternalTransformType, ...]
    available_platform_capabilities: tuple[CapabilityType, ...]
    capability_snapshot_status: FactStatus
    fallback_origin: FallbackOrigin | None
    reason_codes: tuple[ReasonCode, ...]
    blueprint_id: str
    final_plan_requirements: FinalPlanRequirements | None
    plan_decision: LockedPlanDecision
    provenance_ids: tuple[str, ...]
    unresolved_assumption_refs: tuple[str, ...]
    lock_digest: str = ""

    def __post_init__(self) -> None:
        if not self.decision_id or not self.selected_candidate_id or not self.focal_id:
            raise ValueError("SubDecisionIR requires stable decision identities")
        expected_disposition = CandidateDispositionPolicy.execution_disposition(
            self.candidate_state
        )
        if self.execution_disposition != expected_disposition:
            raise ValueError("candidate state and execution disposition differ")
        TargetBindingContract(
            self.execution_target,
            self.execution_target_role,
            self.execution_target_locality,
        )
        if self.plan_decision.decision_id != self.decision_id:
            raise ValueError("plan decision is bound to a different decision")
        if self.capability_snapshot_status not in {
            FactStatus.PRESENT,
            FactStatus.UNKNOWN,
        }:
            raise ValueError("cannot lock output plan from an invalid capability snapshot")
        if self.final_plan_requirements is not None:
            requirements = self.final_plan_requirements
            if requirements.candidate_id != self.selected_candidate_id:
                raise ValueError("FinalPlanRequirements candidate differs from lock")
            if requirements.domain != self.domain:
                raise ValueError("locked domain differs from FinalPlanRequirements")
            if requirements.operation != self.operation:
                raise ValueError("locked operation differs from FinalPlanRequirements")
            if requirements.blueprint_id != self.blueprint_id:
                raise ValueError("locked blueprint differs from plan requirements")
            if requirements.platform_required_capabilities != (
                self.required_platform_capabilities
            ):
                raise ValueError("locked platform capabilities differ from plan")
            if requirements.internal_transform_requirements != (
                self.required_internal_transforms
            ):
                raise ValueError("locked internal transforms differ from plan")
            if set(requirements.applied_effect_ids) != {
                item.effect_id for item in self.applied_safeguards
            }:
                raise ValueError("locked safeguards differ from plan effect lineage")
        if any(
            item.applied_candidate_id != self.selected_candidate_id
            for item in self.active_constraints
        ):
            raise ValueError("constraint is bound to a different candidate")
        if self.fallback_origin is not None and (
            self.fallback_origin.destination_candidate_id
            != self.selected_candidate_id
        ):
            raise ValueError("fallback trace destination differs from selected candidate")
        safeguard_ids = {item.effect_id for item in self.applied_safeguards}
        if not set(self.disclosure.source_effect_ids) <= safeguard_ids:
            raise ValueError("disclosure references an unknown safeguard")
        if not {item.effect_id for item in self.modifications} <= safeguard_ids:
            raise ValueError("modification is not an applied safeguard")
        modification_kinds = {
            ConstraintEffect.ADD_REDACTION,
            ConstraintEffect.FORCE_SUMMARY,
            ConstraintEffect.LIMIT_DURATION,
            ConstraintEffect.RESTRICT_TARGET,
        }
        if any(item.effect not in modification_kinds for item in self.modifications):
            raise ValueError("modification contains a non-modifying safeguard")
        active_constraint_ids = {
            item.constraint_id for item in self.active_constraints
        }
        if not set(self.policy.source_constraint_ids) <= active_constraint_ids:
            raise ValueError("policy references an inactive constraint")
        known_assumptions = assumption_ids()
        if set(self.unresolved_assumption_refs) - known_assumptions:
            raise ValueError("SubDecisionIR contains an unknown assumption")
        for values, label in (
            (self.provenance_ids, "decision provenance"),
            (self.unresolved_assumption_refs, "decision assumptions"),
        ):
            if tuple(sorted(set(values))) != values:
                raise ValueError(f"{label} must be unique and sorted")
        if tuple(
            sorted(set(self.reason_codes), key=lambda item: item.value)
        ) != self.reason_codes:
            raise ValueError("decision reason codes must be canonical")
        plan_reason_codes = {
            reason
            for step in self.plan_decision.steps
            for reason in step.reason_codes
        }
        if not plan_reason_codes <= set(self.reason_codes):
            raise ValueError("plan reason code is absent from the locked decision")
        if tuple(
            sorted(
                set(self.available_platform_capabilities),
                key=lambda item: item.value,
            )
        ) != self.available_platform_capabilities:
            raise ValueError("available capabilities must be canonical")
        if self.execution_disposition == ExecutionDisposition.HOLD and (
            self.disclosure.mode != DisclosureMode.NONE
        ):
            raise ValueError("hold decision must lock none disclosure")
        self._validate_plan_projection()
        if self.lock_digest and self.lock_digest != self.compute_lock_digest():
            raise ValueError("SubDecisionIR lock digest mismatch")

    @property
    def response_target(self) -> str:
        return self.response_target_binding.response_target

    @property
    def disclosure_mode(self) -> DisclosureMode:
        return self.disclosure.mode

    def compute_lock_digest(self) -> str:
        return _digest(self)

    def verify_lock(self) -> None:
        if not self.lock_digest or self.lock_digest != self.compute_lock_digest():
            raise ValueError("SubDecisionIR is not locked")

    def _validate_plan_projection(self) -> None:
        available = set(self.available_platform_capabilities)
        missing_projection_capabilities = {
            step.capability
            for step in self.plan_decision.steps
            if step.capability not in available
        }
        if missing_projection_capabilities:
            raise ValueError("locked output plan contains unavailable capability")
        if self.execution_disposition in {
            ExecutionDisposition.PROCEED,
            ExecutionDisposition.AMEND,
        }:
            requirements = self.final_plan_requirements
            if requirements is None:
                raise ValueError("execution disposition requires plan requirements")
            platform_step_sequence = tuple(
                step
                for step in requirements.required_steps
                if step.output_verb is not None
            )
            projected_step_ids = tuple(
                step.requirement_step_id for step in self.plan_decision.steps
            )
            required_step_ids = tuple(
                step.step_id for step in platform_step_sequence
            )
            if not all(projected_step_ids) or projected_step_ids != required_step_ids:
                raise ValueError("execution projection differs from plan requirements")
            if any(
                projection.verb != requirement.output_verb
                for projection, requirement in zip(
                    self.plan_decision.steps,
                    platform_step_sequence,
                )
            ):
                raise ValueError("execution projection changes a required plan verb")
            if any(
                projection.semantic_terminal != requirement.semantic_terminal
                for projection, requirement in zip(
                    self.plan_decision.steps,
                    platform_step_sequence,
                )
            ):
                raise ValueError("execution projection changes semantic terminal")
        elif self.execution_disposition == ExecutionDisposition.ASK:
            if tuple(step.verb for step in self.plan_decision.steps) != (
                PlanStepType.READ,
                PlanStepType.CLARIFY,
            ):
                raise ValueError("ask projection must read and clarify without execution")
            if any(
                DISPOSITION_PLAN_ASSUMPTION_ID not in step.contract_reference_ids
                for step in self.plan_decision.steps
                if not step.requirement_step_id
            ):
                raise ValueError("ask plan addition lacks disposition plan contract")
            if any(step.semantic_terminal for step in self.plan_decision.steps):
                raise ValueError("ask projection cannot contain a semantic terminal")
        elif tuple(step.verb for step in self.plan_decision.steps) != (
            PlanStepType.READ,
            PlanStepType.GUARD,
        ):
            raise ValueError("hold projection must read and guard without execution")
        elif any(
            DISPOSITION_PLAN_ASSUMPTION_ID not in step.contract_reference_ids
            for step in self.plan_decision.steps
            if not step.requirement_step_id
        ):
            raise ValueError("hold plan addition lacks disposition plan contract")
        elif any(step.semantic_terminal for step in self.plan_decision.steps):
            raise ValueError("hold projection cannot contain a semantic terminal")


class SubDecisionIRBuilder:
    production_active = False

    @staticmethod
    def decision_id_for(evaluation: CandidateEvaluationResult) -> str:
        return f"decision:{evaluation.candidate.candidate_id}"

    @classmethod
    def lock(
        cls,
        *,
        evaluation: CandidateEvaluationResult,
        response_target_binding: ResponseTargetBinding,
        disclosure: DisclosureDecision,
        policy: PolicyDecision,
        plan_decision: LockedPlanDecision,
        capability_snapshot: CapabilitySnapshot,
        fallback_origin: FallbackOrigin | None = None,
    ) -> SubDecisionIR:
        candidate = evaluation.candidate
        assessment = evaluation.assessment
        requirements = assessment.final_plan_requirements
        activation = assessment.constraint_activation
        constraints = activation.active_constraints if activation is not None else ()
        algebra = assessment.effect_algebra
        safeguards = algebra.effects if algebra is not None else ()
        modification_kinds = {
            ConstraintEffect.ADD_REDACTION,
            ConstraintEffect.FORCE_SUMMARY,
            ConstraintEffect.LIMIT_DURATION,
            ConstraintEffect.RESTRICT_TARGET,
        }
        modifications = tuple(
            item for item in safeguards if item.effect in modification_kinds
        )
        reason_codes = set(evaluation.reason_codes)
        reason_codes.update(
            code for item in safeguards for code in item.reason_code_ids
        )
        reason_codes.update(
            code for step in plan_decision.steps for code in step.reason_codes
        )
        assumptions = set(evaluation.disposition.assumption_refs)
        assumptions.update(
            requirements.assumption_refs if requirements is not None else ()
        )
        assumptions.update(
            reference
            for reference in response_target_binding.contract_reference_ids
            if reference in assumption_ids()
        )
        assumptions.update(
            reference
            for step in plan_decision.steps
            for reference in step.contract_reference_ids
            if reference in assumption_ids()
        )
        if evaluation.candidate_state not in {
            CandidateState.VIABLE,
            CandidateState.AMENDABLE,
        }:
            assumptions.add(DISPOSITION_PLAN_ASSUMPTION_ID)
        if fallback_origin is not None:
            assumptions.add(FALLBACK_ASSUMPTION_ID)
            reason_codes.add(ReasonCode.AVOIDED_BY_AUTHORIZED_FALLBACK)
        information_status = (
            assessment.information.status if assessment.information is not None else None
        )
        decision_id = cls.decision_id_for(evaluation)
        if plan_decision.decision_id != decision_id:
            raise ValueError("provided plan decision ID differs from candidate decision")
        ir = SubDecisionIR(
            decision_id=decision_id,
            selected_candidate_id=candidate.candidate_id,
            domain=candidate.semantic_key.rulepack_key.domain,
            operation=candidate.semantic_key.rulepack_key.operation,
            focal_id=candidate.semantic_key.focal_id,
            execution_target=candidate.semantic_key.target_id,
            execution_target_role=candidate.target_role,
            execution_target_locality=candidate.target_locality,
            response_target_binding=response_target_binding,
            candidate_state=evaluation.candidate_state,
            execution_disposition=CandidateDispositionPolicy.execution_disposition(
                evaluation.candidate_state
            ),
            disclosure=disclosure,
            policy=policy,
            active_constraints=constraints,
            applied_safeguards=safeguards,
            modifications=modifications,
            information_status=information_status,
            required_platform_capabilities=(
                requirements.platform_required_capabilities
                if requirements is not None
                else ()
            ),
            required_internal_transforms=(
                requirements.internal_transform_requirements
                if requirements is not None
                else ()
            ),
            available_platform_capabilities=tuple(
                sorted(capability_snapshot.capabilities, key=lambda item: item.value)
            ),
            capability_snapshot_status=capability_snapshot.status,
            fallback_origin=fallback_origin,
            reason_codes=tuple(sorted(reason_codes, key=lambda item: item.value)),
            blueprint_id=requirements.blueprint_id if requirements is not None else "",
            final_plan_requirements=requirements,
            plan_decision=plan_decision,
            provenance_ids=tuple(
                sorted(
                    set(candidate.provenance_ids)
                    | set(response_target_binding.derived_from)
                    | (
                        set(fallback_origin.authorization_reference_ids)
                        if fallback_origin is not None
                        else set()
                    )
                    | {
                        source_id
                        for constraint in constraints
                        for source_id in constraint.source_fact_ids
                    }
                )
            ),
            unresolved_assumption_refs=tuple(sorted(assumptions)),
        )
        return replace(ir, lock_digest=ir.compute_lock_digest())


@dataclass(frozen=True)
class DecisionDependencyEdge:
    source_decision_id: str
    destination_decision_id: str
    kind: DecisionDependencyKind
    reference_id: str

    def __post_init__(self) -> None:
        if not self.reference_id:
            raise ValueError("decision dependency requires an explicit reference")
        if self.source_decision_id == self.destination_decision_id:
            raise ValueError("decision dependency cannot be a self-loop")


@dataclass(frozen=True)
class DecisionBundle:
    bundle_id: str
    primary_focal_id: str
    sub_decisions: tuple[SubDecisionIR, ...]
    dependency_edges: tuple[DecisionDependencyEdge, ...]
    aggregate_output_status: AggregateOutputStatus
    aggregate_reason_codes: tuple[ReasonCode, ...]
    unresolved_assumption_refs: tuple[str, ...]
    bundle_lock_digest: str = ""

    def __post_init__(self) -> None:
        if not self.bundle_id or not self.primary_focal_id or not self.sub_decisions:
            raise ValueError("DecisionBundle requires identity, focal, and decisions")
        for decision in self.sub_decisions:
            decision.verify_lock()
        ids = {item.decision_id for item in self.sub_decisions}
        if len(ids) != len(self.sub_decisions):
            raise ValueError("DecisionBundle contains duplicate decision IDs")
        if self.primary_focal_id not in {
            item.focal_id for item in self.sub_decisions
        }:
            raise ValueError("primary focal is not represented in the bundle")
        if any(
            edge.source_decision_id not in ids
            or edge.destination_decision_id not in ids
            for edge in self.dependency_edges
        ):
            raise ValueError("dependency references a decision outside the bundle")
        dependency_keys = [
            (
                edge.source_decision_id,
                edge.destination_decision_id,
                edge.kind,
                edge.reference_id,
            )
            for edge in self.dependency_edges
        ]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError("DecisionBundle contains duplicate dependency edges")
        self._validate_dependency_dag(ids)
        expected_status = (
            AggregateOutputStatus.SINGLE
            if len(self.sub_decisions) == 1
            else AggregateOutputStatus.MULTIPLE_UNRESOLVED
        )
        if self.aggregate_output_status != expected_status:
            raise ValueError("bundle aggregate status uses an unconfirmed rule")
        if (
            len(self.sub_decisions) > 1
            and BUNDLE_ASSUMPTION_ID not in self.unresolved_assumption_refs
        ):
            raise ValueError("multi-decision bundle lacks aggregate assumption")
        if tuple(
            sorted(set(self.aggregate_reason_codes), key=lambda item: item.value)
        ) != self.aggregate_reason_codes:
            raise ValueError("aggregate reason codes must be canonical")
        if tuple(sorted(set(self.unresolved_assumption_refs))) != (
            self.unresolved_assumption_refs
        ):
            raise ValueError("bundle assumptions must be canonical")
        if self.bundle_lock_digest and (
            self.bundle_lock_digest != self.compute_lock_digest()
        ):
            raise ValueError("DecisionBundle lock digest mismatch")

    def _validate_dependency_dag(self, ids: set[str]) -> None:
        incoming = {decision_id: 0 for decision_id in ids}
        outgoing = {decision_id: [] for decision_id in ids}
        for edge in self.dependency_edges:
            incoming[edge.destination_decision_id] += 1
            outgoing[edge.source_decision_id].append(edge.destination_decision_id)
        queue = sorted(item for item, degree in incoming.items() if degree == 0)
        visited: list[str] = []
        while queue:
            current = queue.pop(0)
            visited.append(current)
            for child in sorted(outgoing[current]):
                incoming[child] -= 1
                if incoming[child] == 0:
                    queue.append(child)
                    queue.sort()
        if len(visited) != len(ids):
            raise ValueError("DecisionBundle dependency graph contains a cycle")

    def compute_lock_digest(self) -> str:
        return _digest(self)

    def verify_lock(self) -> None:
        if not self.bundle_lock_digest or (
            self.bundle_lock_digest != self.compute_lock_digest()
        ):
            raise ValueError("DecisionBundle is not locked")


class DecisionBundleBuilder:
    @staticmethod
    def lock(
        *,
        bundle_id: str,
        primary_focal_id: str,
        sub_decisions: Iterable[SubDecisionIR],
        dependency_edges: Iterable[DecisionDependencyEdge] = (),
    ) -> DecisionBundle:
        decisions = tuple(sorted(sub_decisions, key=lambda item: item.decision_id))
        reasons = tuple(
            sorted(
                {
                    code for decision in decisions for code in decision.reason_codes
                },
                key=lambda item: item.value,
            )
        )
        assumptions = {
            assumption
            for decision in decisions
            for assumption in decision.unresolved_assumption_refs
        }
        status = (
            AggregateOutputStatus.SINGLE
            if len(decisions) == 1
            else AggregateOutputStatus.MULTIPLE_UNRESOLVED
        )
        if len(decisions) > 1:
            assumptions.add(BUNDLE_ASSUMPTION_ID)
        bundle = DecisionBundle(
            bundle_id=bundle_id,
            primary_focal_id=primary_focal_id,
            sub_decisions=decisions,
            dependency_edges=tuple(
                sorted(
                    dependency_edges,
                    key=lambda item: (
                        item.source_decision_id,
                        item.destination_decision_id,
                        item.kind.value,
                        item.reference_id,
                    ),
                )
            ),
            aggregate_output_status=status,
            aggregate_reason_codes=reasons,
            unresolved_assumption_refs=tuple(sorted(assumptions)),
        )
        return replace(bundle, bundle_lock_digest=bundle.compute_lock_digest())


@dataclass(frozen=True)
class ScopeProjection:
    decision_id: str
    mode: DisclosureMode
    allowed_fields: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    requires_user_confirmation: bool
    source_effect_ids: tuple[str, ...]
    source_lock_digest: str


@dataclass(frozen=True)
class PolicyProjection:
    decision_id: str
    risk_flags: tuple[str, ...]
    violations: tuple[str, ...]
    requires_confirmation: bool
    reason_codes: tuple[ReasonCode, ...]
    source_constraint_ids: tuple[str, ...]
    source_lock_digest: str


@dataclass(frozen=True)
class PlanProjection:
    decision_id: str
    steps: tuple[PlanProjectionStep, ...]
    source_lock_digest: str


@dataclass(frozen=True)
class DecisionProjectionSet:
    bundle_id: str
    aggregate_output_status: AggregateOutputStatus
    scopes: tuple[ScopeProjection, ...]
    policies: tuple[PolicyProjection, ...]
    plans: tuple[PlanProjection, ...]
    source_bundle_lock_digest: str

    def __post_init__(self) -> None:
        scope_ids = tuple(item.decision_id for item in self.scopes)
        policy_ids = tuple(item.decision_id for item in self.policies)
        plan_ids = tuple(item.decision_id for item in self.plans)
        if not scope_ids or scope_ids != policy_ids or scope_ids != plan_ids:
            raise ValueError("projection DTO decision sets differ")
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("projection DTO contains duplicate decision IDs")
        if not self.source_bundle_lock_digest:
            raise ValueError("projection DTO lacks bundle lock lineage")


class DecisionProjectionBuilder:
    production_active = False

    @staticmethod
    def build(bundle: DecisionBundle) -> DecisionProjectionSet:
        bundle.verify_lock()
        scopes = tuple(
            ScopeProjection(
                decision.decision_id,
                decision.disclosure.mode,
                decision.disclosure.allowed_fields,
                decision.disclosure.excluded_fields,
                decision.disclosure.requires_user_confirmation,
                decision.disclosure.source_effect_ids,
                decision.lock_digest,
            )
            for decision in bundle.sub_decisions
        )
        policies = tuple(
            PolicyProjection(
                decision.decision_id,
                decision.policy.risk_flags,
                decision.policy.violations,
                decision.policy.requires_confirmation,
                decision.reason_codes,
                decision.policy.source_constraint_ids,
                decision.lock_digest,
            )
            for decision in bundle.sub_decisions
        )
        plans = tuple(
            PlanProjection(
                decision.decision_id,
                decision.plan_decision.steps,
                decision.lock_digest,
            )
            for decision in bundle.sub_decisions
        )
        return DecisionProjectionSet(
            bundle.bundle_id,
            bundle.aggregate_output_status,
            scopes,
            policies,
            plans,
            bundle.bundle_lock_digest,
        )


def validate_decision_ir_contract() -> None:
    if SubDecisionIRBuilder.production_active:
        raise ValueError("Step 9 SubDecisionIR path must remain shadow-only")
    if DecisionProjectionBuilder.production_active:
        raise ValueError("Step 9 projection path must remain shadow-only")
