from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

from .constraints import (
    ConstraintActivationBundle,
    ConstraintActivationState,
    ConstraintCandidateContext,
    ConstraintEffectAlgebra,
    EffectAlgebraResult,
    EffectAlgebraStatus,
    GlobalConstraintFact,
    PairConstraintActivator,
)
from .contracts import (
    ACTIONS_ASSUMPTION_ID,
    DISPOSITION_ASSUMPTION_ID,
    TRANSFORM_ASSUMPTION_ID,
)
from .facts import CapabilitySnapshot
from .ontology import (
    CandidateState,
    CapabilityType,
    ConstraintEffect,
    DisclosureMode,
    FactStatus,
    InformationSlot,
    ReasonCode,
    TargetBindingContract,
    TargetLocality,
    TargetRole,
)
from .plan_requirements import (
    PLAN_BLUEPRINT_REGISTRY,
    BasePlanBlueprint,
    FinalPlanRequirements,
    InternalTransformType,
    PlanRequirementComposer,
)
from .rulepacks import (
    RULEPACK_REGISTRY,
    CompatibilityPredicate,
    ConditionalPredicateKind,
    ConditionalSlotSpec,
    DerivationSource,
    DomainOperationRulePack,
    IdentityTypeConstraint,
    InformationSpec,
    RequiredRoleSpec,
    RulePackAvailability,
    RulePackKey,
    RulePackResolution,
    SameAsFocalPolicy,
    SourceField,
)
from .slm_contract import PipelineStage


class CandidateOrigin(str, Enum):
    PARSER = "parser"
    SLM_PROVISIONAL = "slm_provisional"
    STRUCTURAL = "structural"


class RoleCompatibilityStatus(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNRESOLVED = "unresolved"


class InformationBindingStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    CONFLICTED = "conflicted"
    DEFAULTED = "defaulted"
    UNRESOLVED = "unresolved"


class CandidateInformationStatus(str, Enum):
    COMPLETE = "complete"
    MISSING = "missing"
    CONFLICTED = "conflicted"
    UNRESOLVED = "unresolved"


class CapabilityEvaluationStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNRESOLVED = "unresolved"


class CandidateIssue(str, Enum):
    UNSUPPORTED_RULEPACK = "unsupported_rulepack"
    ROLE_INCOMPATIBLE = "role_incompatible"
    ROLE_UNRESOLVED = "role_unresolved"
    INFORMATION_MISSING = "information_missing"
    INFORMATION_CONFLICTED = "information_conflicted"
    INFORMATION_UNRESOLVED = "information_unresolved"
    CONSTRAINT_BLOCKED = "constraint_blocked"
    CONSTRAINT_CONFLICTED = "constraint_conflicted"
    CONSTRAINT_UNRESOLVED = "constraint_unresolved"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    CAPABILITY_UNRESOLVED = "capability_unresolved"
    CONFIRMATION_REQUIRED = "confirmation_required"
    MODIFICATION_REQUIRED = "modification_required"


class CandidateSelectionStatus(str, Enum):
    SELECTED = "selected"
    USER_CHOICE_REQUIRED = "user_choice_required"
    NO_VIABLE_CANDIDATE = "no_viable_candidate"


@dataclass(frozen=True)
class CandidateSemanticKey:
    rulepack_key: RulePackKey
    focal_id: str
    target_id: str

    def __post_init__(self) -> None:
        if not self.focal_id:
            raise ValueError("candidate semantic key requires a focal identity")


@dataclass(frozen=True)
class CandidateIdentity:
    sub_operation_id: str
    source_clause_id: str
    evidence_group_id: str
    semantic_key: CandidateSemanticKey

    def __post_init__(self) -> None:
        if not self.sub_operation_id or not self.source_clause_id:
            raise ValueError("candidate identity requires operation and clause identity")
        if not self.evidence_group_id:
            raise ValueError("candidate identity requires an evidence group")

    @property
    def candidate_id(self) -> str:
        payload = json.dumps(
            {
                "sub_operation_id": self.sub_operation_id,
                "source_clause_id": self.source_clause_id,
                "evidence_group_id": self.evidence_group_id,
                "domain": self.semantic_key.rulepack_key.domain.value,
                "operation": self.semantic_key.rulepack_key.operation.value,
                "variant": (
                    self.semantic_key.rulepack_key.variant.value
                    if self.semantic_key.rulepack_key.variant
                    else None
                ),
                "focal_id": self.semantic_key.focal_id,
                "target_id": self.semantic_key.target_id,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()[:20]
        return f"candidate:{digest}"


@dataclass(frozen=True)
class InformationBinding:
    slot: InformationSlot
    status: InformationBindingStatus
    canonical_value: str = ""
    source_fact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status in {
            InformationBindingStatus.PRESENT,
            InformationBindingStatus.DEFAULTED,
        } and not self.canonical_value:
            raise ValueError("present information binding requires a value")
        if tuple(sorted(set(self.source_fact_ids))) != self.source_fact_ids:
            raise ValueError("information binding provenance must be unique and sorted")


@dataclass(frozen=True)
class EvaluationCandidate:
    identity: CandidateIdentity
    target_role: TargetRole
    target_locality: TargetLocality
    target_identity_type: IdentityTypeConstraint | None
    satisfied_role_predicates: tuple[CompatibilityPredicate, ...]
    failed_role_predicates: tuple[CompatibilityPredicate, ...]
    focal_fields: tuple[tuple[SourceField, str], ...]
    operation_arguments: tuple[tuple[SourceField, str], ...]
    information_bindings: tuple[InformationBinding, ...]
    requested_disclosure: DisclosureMode | None
    intent_rank: int
    origin: CandidateOrigin
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        semantic = self.identity.semantic_key
        TargetBindingContract(
            semantic.target_id,
            self.target_role,
            self.target_locality,
        )
        if self.intent_rank < 0:
            raise ValueError("candidate rank cannot be negative")
        if set(self.satisfied_role_predicates) & set(self.failed_role_predicates):
            raise ValueError("role predicate cannot be both satisfied and failed")
        if tuple(sorted(set(self.provenance_ids))) != self.provenance_ids:
            raise ValueError("candidate provenance must be unique and sorted")
        for values, label in (
            (self.focal_fields, "focal field"),
            (self.operation_arguments, "operation argument"),
        ):
            keys = [key for key, _value in values]
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label}")

    @property
    def candidate_id(self) -> str:
        return self.identity.candidate_id

    @property
    def semantic_key(self) -> CandidateSemanticKey:
        return self.identity.semantic_key


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[EvaluationCandidate, ...]

    def __post_init__(self) -> None:
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate set contains duplicate full identities")

    def by_id(self) -> dict[str, EvaluationCandidate]:
        return {item.candidate_id: item for item in self.candidates}


class CandidateSetBuilder:
    """Builds only source-bound candidate pairs; it has no Cartesian product API."""

    @staticmethod
    def build(seeds: Iterable[EvaluationCandidate]) -> CandidateSet:
        return CandidateSet(
            tuple(
                sorted(
                    seeds,
                    key=lambda item: (
                        item.identity.source_clause_id,
                        item.identity.sub_operation_id,
                        item.candidate_id,
                    ),
                )
            )
        )


@dataclass(frozen=True)
class RoleCompatibilityAssessment:
    status: RoleCompatibilityStatus
    required_role_spec_id: str
    reasons: tuple[str, ...]


class RequiredRoleEvaluator:
    @staticmethod
    def evaluate(
        candidate: EvaluationCandidate,
        spec: RequiredRoleSpec,
    ) -> RoleCompatibilityAssessment:
        if candidate.target_role == TargetRole.UNRESOLVED:
            return RoleCompatibilityAssessment(
                RoleCompatibilityStatus.UNRESOLVED,
                spec.spec_id,
                ("target_role_unresolved",),
            )
        reasons: list[str] = []
        if not (spec.minimum_cardinality <= 1 <= spec.maximum_cardinality):
            reasons.append("target_cardinality_not_allowed")
        if candidate.target_role not in spec.allowed_roles:
            reasons.append("target_role_not_allowed")
        if candidate.target_locality not in spec.locality_constraints:
            reasons.append("target_locality_not_allowed")
        if (
            candidate.target_identity_type is not None
            and candidate.target_identity_type not in spec.identity_type_constraints
        ):
            reasons.append("target_identity_type_not_allowed")
        if (
            spec.same_as_focal_policy == SameAsFocalPolicy.FORBIDDEN
            and candidate.semantic_key.focal_id == candidate.semantic_key.target_id
        ):
            reasons.append("target_must_differ_from_focal")
        if (
            spec.same_as_focal_policy == SameAsFocalPolicy.REQUIRED
            and candidate.semantic_key.focal_id != candidate.semantic_key.target_id
        ):
            reasons.append("target_must_equal_focal")
        failed = set(candidate.failed_role_predicates) & set(
            spec.compatibility_predicates
        )
        if failed:
            reasons.append("compatibility_predicate_failed")
        if reasons:
            return RoleCompatibilityAssessment(
                RoleCompatibilityStatus.INCOMPATIBLE,
                spec.spec_id,
                tuple(sorted(reasons)),
            )
        unresolved: list[str] = []
        if candidate.target_identity_type is None:
            unresolved.append("target_identity_type_unresolved")
        missing_predicates = set(spec.compatibility_predicates) - set(
            candidate.satisfied_role_predicates
        )
        if missing_predicates:
            unresolved.append("compatibility_predicate_unresolved")
        return RoleCompatibilityAssessment(
            RoleCompatibilityStatus.UNRESOLVED
            if unresolved
            else RoleCompatibilityStatus.COMPATIBLE,
            spec.spec_id,
            tuple(unresolved),
        )


@dataclass(frozen=True)
class InformationPrecheck:
    information_spec_id: str
    bindings: tuple[InformationBinding, ...]
    base_required_slots: tuple[InformationSlot, ...]
    activated_conditional_slots: tuple[InformationSlot, ...]
    deferred_conditionals: tuple[ConditionalSlotSpec, ...]


@dataclass(frozen=True)
class CandidateInformationAssessment:
    status: CandidateInformationStatus
    information_spec_id: str
    bindings: tuple[InformationBinding, ...]
    required_slots: tuple[InformationSlot, ...]
    missing_slots: tuple[InformationSlot, ...]
    conflicted_slots: tuple[InformationSlot, ...]
    unresolved_slots: tuple[InformationSlot, ...]


class CandidateInformationResolver:
    _ROLE_SLOT = {
        TargetRole.DISPATCH_DESTINATION: InformationSlot.DESTINATION,
        TargetRole.LOCAL_RESOURCE: InformationSlot.LOCAL_RESOURCE,
        TargetRole.MEMORY_OWNER: InformationSlot.LOCAL_RESOURCE,
        TargetRole.MERCHANT: InformationSlot.MERCHANT,
        TargetRole.DEVICE_TARGET: InformationSlot.DEVICE_TARGET,
        TargetRole.CLARIFICATION_TARGET: InformationSlot.CLARIFICATION_TARGET,
        TargetRole.CONFIRMATION_AUTHORITY: InformationSlot.CLARIFICATION_TARGET,
    }

    @classmethod
    def precheck(
        cls,
        candidate: EvaluationCandidate,
        spec: InformationSpec,
    ) -> InformationPrecheck:
        bindings = list(candidate.information_bindings)
        bindings.extend(cls._derive(candidate, spec))
        role_slot = cls._ROLE_SLOT.get(candidate.target_role)
        if role_slot is not None and candidate.semantic_key.target_id:
            bindings.append(
                InformationBinding(
                    role_slot,
                    InformationBindingStatus.PRESENT,
                    candidate.semantic_key.target_id,
                    (f"candidate_target:{candidate.candidate_id}",),
                )
            )
        activated: list[InformationSlot] = []
        deferred: list[ConditionalSlotSpec] = []
        for conditional in spec.conditional_slots:
            if conditional.predicate_kind == ConditionalPredicateKind.CONSTRAINT_PRESENT:
                deferred.append(conditional)
            elif (
                conditional.predicate_kind
                == ConditionalPredicateKind.DISCLOSURE_REQUESTED
                and candidate.requested_disclosure is not None
                and candidate.requested_disclosure.value == conditional.predicate_ref
            ):
                activated.append(conditional.slot)
            elif (
                conditional.predicate_kind
                == ConditionalPredicateKind.OPERATION_VARIANT_IS
                and candidate.semantic_key.rulepack_key.variant is not None
                and candidate.semantic_key.rulepack_key.variant.value
                == conditional.predicate_ref
            ):
                activated.append(conditional.slot)
        return InformationPrecheck(
            information_spec_id=spec.spec_id,
            bindings=cls._canonical_bindings(bindings),
            base_required_slots=spec.required_slots,
            activated_conditional_slots=tuple(sorted(set(activated), key=lambda item: item.value)),
            deferred_conditionals=tuple(deferred),
        )

    @classmethod
    def finalize(
        cls,
        precheck: InformationPrecheck,
        activation: ConstraintActivationBundle | None,
    ) -> CandidateInformationAssessment:
        bindings = list(precheck.bindings)
        required = set(precheck.base_required_slots) | set(
            precheck.activated_conditional_slots
        )
        conditional_unresolved: set[InformationSlot] = set()
        evaluations = {
            item.constraint_id: item for item in activation.evaluations
        } if activation is not None else {}
        for conditional in precheck.deferred_conditionals:
            evaluation = evaluations.get(conditional.predicate_ref)
            if evaluation is None:
                conditional_unresolved.add(conditional.slot)
                continue
            if evaluation.state == ConstraintActivationState.INACTIVE:
                continue
            if evaluation.state in {
                ConstraintActivationState.CONFLICTED,
                ConstraintActivationState.UNRESOLVED,
            }:
                conditional_unresolved.add(conditional.slot)
                continue
            required.add(conditional.slot)
            if evaluation.constraint is not None:
                for effect in evaluation.constraint.effects:
                    for name, value in effect.parameters:
                        if name == conditional.slot.value:
                            bindings.append(
                                InformationBinding(
                                    conditional.slot,
                                    InformationBindingStatus.PRESENT,
                                    value,
                                    effect.source_fact_ids,
                                )
                            )
        canonical = cls._canonical_bindings(bindings)
        by_slot: dict[InformationSlot, list[InformationBinding]] = {}
        for binding in canonical:
            by_slot.setdefault(binding.slot, []).append(binding)
        missing: list[InformationSlot] = []
        conflicted: list[InformationSlot] = []
        unresolved = set(conditional_unresolved)
        for slot in sorted(required, key=lambda item: item.value):
            slot_bindings = by_slot.get(slot, [])
            statuses = {item.status for item in slot_bindings}
            values = {
                item.canonical_value
                for item in slot_bindings
                if item.status
                in {
                    InformationBindingStatus.PRESENT,
                    InformationBindingStatus.DEFAULTED,
                }
            }
            if InformationBindingStatus.CONFLICTED in statuses or len(values) > 1:
                conflicted.append(slot)
            elif InformationBindingStatus.UNRESOLVED in statuses:
                unresolved.add(slot)
            elif not values:
                missing.append(slot)
        if conflicted:
            status = CandidateInformationStatus.CONFLICTED
        elif unresolved:
            status = CandidateInformationStatus.UNRESOLVED
        elif missing:
            status = CandidateInformationStatus.MISSING
        else:
            status = CandidateInformationStatus.COMPLETE
        return CandidateInformationAssessment(
            status=status,
            information_spec_id=precheck.information_spec_id,
            bindings=canonical,
            required_slots=tuple(sorted(required, key=lambda item: item.value)),
            missing_slots=tuple(missing),
            conflicted_slots=tuple(conflicted),
            unresolved_slots=tuple(sorted(unresolved, key=lambda item: item.value)),
        )

    @staticmethod
    def _derive(
        candidate: EvaluationCandidate,
        spec: InformationSpec,
    ) -> tuple[InformationBinding, ...]:
        focal_fields = dict(candidate.focal_fields)
        operation_arguments = dict(candidate.operation_arguments)
        derived: list[InformationBinding] = []
        for rule in spec.typed_derivation_rules:
            value = ""
            source_id = ""
            if rule.source == DerivationSource.FOCAL_ATTRIBUTE:
                value = focal_fields.get(rule.source_field, "")
                source_id = f"focal_field:{rule.source_field.value}"
            elif rule.source == DerivationSource.OPERATION_ARGUMENT:
                value = operation_arguments.get(rule.source_field, "")
                source_id = f"operation_argument:{rule.source_field.value}"
            elif rule.source == DerivationSource.SELECTED_TARGET:
                value = candidate.semantic_key.target_id
                source_id = f"candidate_target:{candidate.candidate_id}"
            if value:
                derived.append(
                    InformationBinding(
                        rule.slot,
                        InformationBindingStatus.PRESENT,
                        value,
                        (source_id,),
                    )
                )
        return tuple(derived)

    @staticmethod
    def _canonical_bindings(
        bindings: Iterable[InformationBinding],
    ) -> tuple[InformationBinding, ...]:
        unique = {
            (
                item.slot,
                item.status,
                item.canonical_value,
                item.source_fact_ids,
            ): item
            for item in bindings
        }
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.slot.value,
                    item.status.value,
                    item.canonical_value,
                    item.source_fact_ids,
                ),
            )
        )


@dataclass(frozen=True)
class CapabilityAssessment:
    status: CapabilityEvaluationStatus
    required_platform_capabilities: tuple[CapabilityType, ...]
    missing_platform_capabilities: tuple[CapabilityType, ...]
    required_internal_transforms: tuple[InternalTransformType, ...]
    missing_internal_transforms: tuple[InternalTransformType, ...]
    reason: str = ""


@dataclass(frozen=True)
class CandidateEvaluationContext:
    global_constraint_facts: tuple[GlobalConstraintFact, ...]
    capability_snapshot: CapabilitySnapshot
    internal_transform_capabilities: frozenset[InternalTransformType]


class FullCapabilityEvaluator:
    @staticmethod
    def evaluate(
        requirements: FinalPlanRequirements | None,
        context: CandidateEvaluationContext,
        *,
        prior_axes_resolved: bool,
    ) -> CapabilityAssessment:
        if requirements is None or not prior_axes_resolved:
            return CapabilityAssessment(
                CapabilityEvaluationStatus.UNRESOLVED,
                (),
                (),
                (),
                (),
                "final_plan_requirements_unresolved",
            )
        required_platform = requirements.platform_required_capabilities
        required_internal = requirements.internal_transform_requirements
        snapshot = context.capability_snapshot
        if snapshot.status not in {FactStatus.PRESENT, FactStatus.UNKNOWN}:
            return CapabilityAssessment(
                CapabilityEvaluationStatus.UNRESOLVED,
                required_platform,
                (),
                required_internal,
                (),
                "available_actions_unresolved",
            )
        missing_platform = tuple(
            item for item in required_platform if item not in snapshot.capabilities
        )
        missing_internal = tuple(
            item
            for item in required_internal
            if item not in context.internal_transform_capabilities
        )
        return CapabilityAssessment(
            CapabilityEvaluationStatus.UNAVAILABLE
            if missing_platform or missing_internal
            else CapabilityEvaluationStatus.AVAILABLE,
            required_platform,
            missing_platform,
            required_internal,
            missing_internal,
        )


@dataclass(frozen=True)
class CandidateAxisAssessment:
    candidate: EvaluationCandidate
    rulepack_resolution: RulePackResolution
    rulepack: DomainOperationRulePack | None
    blueprint: BasePlanBlueprint | None
    role: RoleCompatibilityAssessment | None
    information_precheck: InformationPrecheck | None
    information: CandidateInformationAssessment | None
    constraint_activation: ConstraintActivationBundle | None
    effect_algebra: EffectAlgebraResult | None
    final_plan_requirements: FinalPlanRequirements | None
    capability: CapabilityAssessment
    assessment_order: tuple[PipelineStage, ...]


class CandidateAxisAssembler:
    """Evaluates prerequisite axes. It does not assign CandidateState."""

    @classmethod
    def assess(
        cls,
        candidate: EvaluationCandidate,
        context: CandidateEvaluationContext,
    ) -> CandidateAxisAssessment:
        order: list[PipelineStage] = [PipelineStage.RULEPACK_LOOKUP]
        resolution = RULEPACK_REGISTRY.resolve_exact(
            candidate.semantic_key.rulepack_key
        )
        if resolution.availability != RulePackAvailability.FOUND:
            return CandidateAxisAssessment(
                candidate,
                resolution,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                CapabilityAssessment(
                    CapabilityEvaluationStatus.UNRESOLVED,
                    (),
                    (),
                    (),
                    (),
                    "unsupported_rulepack",
                ),
                tuple(order),
            )
        assert resolution.rulepack is not None
        rulepack = resolution.rulepack
        blueprint = PLAN_BLUEPRINT_REGISTRY.lookup(rulepack.base_blueprint_id)
        if blueprint is None:
            raise ValueError("RulePack has no BasePlanBlueprint")
        order.append(PipelineStage.BASE_BLUEPRINT_LOAD)

        role_spec = RULEPACK_REGISTRY.role_spec(rulepack.required_role_spec_id)
        role = RequiredRoleEvaluator.evaluate(candidate, role_spec)
        order.append(PipelineStage.REQUIRED_ROLE_EVALUATION)
        information_spec = RULEPACK_REGISTRY.information_spec(
            rulepack.information_spec_id
        )
        precheck = CandidateInformationResolver.precheck(
            candidate,
            information_spec,
        )
        order.append(PipelineStage.INFORMATION_EVALUATION)
        order.append(PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION)

        activation: ConstraintActivationBundle | None = None
        if (
            candidate.target_role != TargetRole.UNRESOLVED
            and candidate.target_locality != TargetLocality.UNKNOWN
        ):
            activation = PairConstraintActivator.activate(
                context=ConstraintCandidateContext(
                    candidate_id=candidate.candidate_id,
                    rulepack_key=candidate.semantic_key.rulepack_key,
                    focal_id=candidate.semantic_key.focal_id,
                    target_id=candidate.semantic_key.target_id,
                    target_role=candidate.target_role,
                    target_locality=candidate.target_locality,
                ),
                rulepack=rulepack,
                global_facts=context.global_constraint_facts,
            )
        order.append(PipelineStage.PAIR_CONSTRAINT_ACTIVATION)
        information = CandidateInformationResolver.finalize(precheck, activation)
        order.append(PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION)

        effect_algebra: EffectAlgebraResult | None = None
        requirements: FinalPlanRequirements | None = None
        if activation is not None:
            effect_algebra = ConstraintEffectAlgebra.compose(activation.constraints)
            order.append(PipelineStage.CONSTRAINT_EFFECT_COMPOSITION)
            if effect_algebra.status == EffectAlgebraStatus.COMPOSED:
                requirements = PlanRequirementComposer.compose(
                    candidate_id=candidate.candidate_id,
                    rulepack=rulepack,
                    blueprint=blueprint,
                    deltas=effect_algebra.to_plan_requirement_deltas(),
                )
        if PipelineStage.CONSTRAINT_EFFECT_COMPOSITION not in order:
            order.append(PipelineStage.CONSTRAINT_EFFECT_COMPOSITION)
        order.append(PipelineStage.FINAL_PLAN_REQUIREMENTS)
        prior_resolved = (
            role.status != RoleCompatibilityStatus.INCOMPATIBLE
            and activation is not None
            and effect_algebra is not None
            and effect_algebra.status == EffectAlgebraStatus.COMPOSED
            and requirements is not None
        )
        capability = FullCapabilityEvaluator.evaluate(
            requirements,
            context,
            prior_axes_resolved=prior_resolved,
        )
        order.append(PipelineStage.FULL_CAPABILITY_EVALUATION)
        return CandidateAxisAssessment(
            candidate=candidate,
            rulepack_resolution=resolution,
            rulepack=rulepack,
            blueprint=blueprint,
            role=role,
            information_precheck=precheck,
            information=information,
            constraint_activation=activation,
            effect_algebra=effect_algebra,
            final_plan_requirements=requirements,
            capability=capability,
            assessment_order=tuple(order),
        )


@dataclass(frozen=True)
class CandidateDispositionResolution:
    candidate_state: CandidateState
    issues: tuple[CandidateIssue, ...]
    precedence_resolved: bool
    assumption_refs: tuple[str, ...]


class CandidateDispositionResolver:
    @staticmethod
    def resolve(issues: Iterable[CandidateIssue]) -> CandidateDispositionResolution:
        issue_set = set(issues)
        ordered = tuple(sorted(issue_set, key=lambda item: item.value))
        assumptions = (DISPOSITION_ASSUMPTION_ID,)
        if CandidateIssue.UNSUPPORTED_RULEPACK in issue_set:
            return CandidateDispositionResolution(
                CandidateState.UNSUPPORTED_RULEPACK,
                ordered,
                True,
                assumptions,
            )
        if CandidateIssue.ROLE_INCOMPATIBLE in issue_set:
            return CandidateDispositionResolution(
                CandidateState.REJECTED,
                ordered,
                True,
                assumptions,
            )
        categories: set[CandidateState] = set()
        if issue_set & {
            CandidateIssue.CONSTRAINT_BLOCKED,
            CandidateIssue.CAPABILITY_UNAVAILABLE,
        }:
            categories.add(CandidateState.BLOCKED)
        if issue_set & {
            CandidateIssue.INFORMATION_CONFLICTED,
            CandidateIssue.CONSTRAINT_CONFLICTED,
        }:
            categories.add(CandidateState.CONFLICTED)
        if issue_set & {
            CandidateIssue.ROLE_UNRESOLVED,
            CandidateIssue.INFORMATION_MISSING,
        }:
            categories.add(CandidateState.NEEDS_INFORMATION)
        if issue_set & {
            CandidateIssue.INFORMATION_UNRESOLVED,
            CandidateIssue.CONSTRAINT_UNRESOLVED,
            CandidateIssue.CAPABILITY_UNRESOLVED,
        }:
            categories.add(CandidateState.CONFLICTED)
        if CandidateIssue.CONFIRMATION_REQUIRED in issue_set:
            categories.add(CandidateState.NEEDS_CONFIRMATION)
        if len(categories) > 1:
            return CandidateDispositionResolution(
                CandidateState.CONFLICTED,
                ordered,
                False,
                assumptions,
            )
        if categories:
            state = next(iter(categories))
            return CandidateDispositionResolution(state, ordered, True, assumptions)
        if CandidateIssue.MODIFICATION_REQUIRED in issue_set:
            return CandidateDispositionResolution(
                CandidateState.AMENDABLE,
                ordered,
                True,
                assumptions,
            )
        return CandidateDispositionResolution(
            CandidateState.VIABLE,
            ordered,
            True,
            assumptions,
        )


@dataclass(frozen=True)
class CandidateEvaluationResult:
    assessment: CandidateAxisAssessment
    disposition: CandidateDispositionResolution
    reason_codes: tuple[ReasonCode, ...]
    evaluator_contract_version: str = "candidate-evaluator.v1"

    @property
    def candidate(self) -> EvaluationCandidate:
        return self.assessment.candidate

    @property
    def candidate_state(self) -> CandidateState:
        return self.disposition.candidate_state


class CandidateEvaluator:
    """Aggregates completed axis assessments; it performs no RulePack lookup."""

    @classmethod
    def evaluate(cls, assessment: CandidateAxisAssessment) -> CandidateEvaluationResult:
        issues: set[CandidateIssue] = set()
        reasons: set[ReasonCode] = set()
        if assessment.rulepack_resolution.availability != RulePackAvailability.FOUND:
            issues.add(CandidateIssue.UNSUPPORTED_RULEPACK)
            reasons.add(ReasonCode.UNSUPPORTED_OPERATION_BLUEPRINT)
        role = assessment.role
        if role is not None:
            if role.status == RoleCompatibilityStatus.INCOMPATIBLE:
                issues.add(CandidateIssue.ROLE_INCOMPATIBLE)
                reasons.add(ReasonCode.ROLE_INCOMPATIBLE)
            elif role.status == RoleCompatibilityStatus.UNRESOLVED:
                issues.add(CandidateIssue.ROLE_UNRESOLVED)
                reasons.add(ReasonCode.ROLE_UNRESOLVED)
        information = assessment.information
        role_unresolved = (
            role is not None
            and role.status == RoleCompatibilityStatus.UNRESOLVED
        )
        if information is not None:
            if information.status == CandidateInformationStatus.MISSING:
                issues.add(CandidateIssue.INFORMATION_MISSING)
                reasons.add(ReasonCode.REQUIRED_INFORMATION_MISSING)
            elif information.status == CandidateInformationStatus.CONFLICTED:
                issues.add(CandidateIssue.INFORMATION_CONFLICTED)
                reasons.add(ReasonCode.REQUIRED_INFORMATION_CONFLICT)
            elif information.status == CandidateInformationStatus.UNRESOLVED:
                if not (
                    role_unresolved
                    and assessment.constraint_activation is None
                ):
                    issues.add(CandidateIssue.INFORMATION_UNRESOLVED)
                    reasons.add(ReasonCode.CONFLICTING_INSTRUCTIONS)
        activation = assessment.constraint_activation
        if activation is None and assessment.rulepack is not None:
            if not role_unresolved:
                issues.add(CandidateIssue.CONSTRAINT_UNRESOLVED)
                reasons.add(ReasonCode.CONSTRAINT_STATUS_UNRESOLVED)
        elif activation is not None:
            for evaluation in activation.evaluations:
                if evaluation.state == ConstraintActivationState.CONFLICTED:
                    issues.add(CandidateIssue.CONSTRAINT_CONFLICTED)
                elif evaluation.state == ConstraintActivationState.UNRESOLVED:
                    issues.add(CandidateIssue.CONSTRAINT_UNRESOLVED)
                if evaluation.constraint is not None:
                    reasons.update(evaluation.constraint.reason_code_ids)
        algebra = assessment.effect_algebra
        if algebra is not None:
            if algebra.status == EffectAlgebraStatus.CONFLICTED:
                issues.add(CandidateIssue.CONSTRAINT_CONFLICTED)
            elif algebra.status == EffectAlgebraStatus.UNRESOLVED:
                issues.add(CandidateIssue.CONSTRAINT_UNRESOLVED)
            effect_kinds = {item.effect for item in algebra.effects}
            if ConstraintEffect.BLOCK_EXECUTION in effect_kinds:
                issues.add(CandidateIssue.CONSTRAINT_BLOCKED)
            if ConstraintEffect.ADD_CONFIRMATION in effect_kinds:
                issues.add(CandidateIssue.CONFIRMATION_REQUIRED)
            if effect_kinds & {
                ConstraintEffect.ADD_REDACTION,
                ConstraintEffect.FORCE_SUMMARY,
                ConstraintEffect.LIMIT_DURATION,
                ConstraintEffect.RESTRICT_TARGET,
            }:
                issues.add(CandidateIssue.MODIFICATION_REQUIRED)
        capability = assessment.capability
        if capability.status == CapabilityEvaluationStatus.UNAVAILABLE:
            issues.add(CandidateIssue.CAPABILITY_UNAVAILABLE)
            reasons.add(ReasonCode.CAPABILITY_UNAVAILABLE)
        elif (
            capability.status == CapabilityEvaluationStatus.UNRESOLVED
            and CandidateIssue.UNSUPPORTED_RULEPACK not in issues
            and CandidateIssue.ROLE_INCOMPATIBLE not in issues
            and not role_unresolved
        ):
            issues.add(CandidateIssue.CAPABILITY_UNRESOLVED)
            reasons.add(ReasonCode.CAPABILITY_STATUS_UNRESOLVED)
        disposition = CandidateDispositionResolver.resolve(issues)
        return CandidateEvaluationResult(
            assessment=assessment,
            disposition=disposition,
            reason_codes=tuple(sorted(reasons, key=lambda item: item.value)),
        )


class CandidateEvaluationEngine:
    production_active = False

    @staticmethod
    def evaluate_set(
        candidate_set: CandidateSet,
        context: CandidateEvaluationContext,
    ) -> tuple[CandidateEvaluationResult, ...]:
        return tuple(
            CandidateEvaluator.evaluate(
                CandidateAxisAssembler.assess(candidate, context)
            )
            for candidate in candidate_set.candidates
        )


@dataclass(frozen=True)
class CandidateSelection:
    status: CandidateSelectionStatus
    selected_candidate_id: str
    considered_candidate_ids: tuple[str, ...]
    equivalent_source_candidate_ids: tuple[str, ...] = ()


class CandidateRankingPolicy:
    @staticmethod
    def select(
        evaluations: Iterable[CandidateEvaluationResult],
    ) -> CandidateSelection:
        rows = tuple(evaluations)
        viable = tuple(
            item
            for item in rows
            if item.candidate_state in {CandidateState.VIABLE, CandidateState.AMENDABLE}
        )
        if not viable:
            return CandidateSelection(
                CandidateSelectionStatus.NO_VIABLE_CANDIDATE,
                "",
                tuple(sorted(item.candidate.candidate_id for item in rows)),
            )
        top_rank = max(item.candidate.intent_rank for item in viable)
        top = tuple(item for item in viable if item.candidate.intent_rank == top_rank)
        semantic_keys = {item.candidate.semantic_key for item in top}
        ids = tuple(sorted(item.candidate.candidate_id for item in top))
        if len(semantic_keys) > 1:
            return CandidateSelection(
                CandidateSelectionStatus.USER_CHOICE_REQUIRED,
                "",
                ids,
            )
        selected = ids[0]
        return CandidateSelection(
            CandidateSelectionStatus.SELECTED,
            selected,
            ids,
            ids,
        )


def validate_candidate_evaluation_contract() -> None:
    if CandidateEvaluationEngine.production_active:
        raise ValueError("Step 8 candidate evaluator must remain shadow-only")
    if ACTIONS_ASSUMPTION_ID == TRANSFORM_ASSUMPTION_ID:
        raise ValueError("capability assumptions unexpectedly collapsed")
