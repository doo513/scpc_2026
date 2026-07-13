from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .ontology import Domain, ExecutionDisposition, Operation
from .rulepacks import (
    RULEPACK_REGISTRY,
    RulePackAvailability,
    RulePackKey,
)


class SLMValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNRESOLVED = "unresolved"


class SLMMergeStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTING = "supporting"
    CONFLICTING = "conflicting"
    REJECTED = "rejected"


class SLMInfluenceStatus(str, Enum):
    UNUSED = "unused"
    CANDIDATE_ADDED = "candidate_added"
    RANK_CHANGED = "rank_changed"
    FINAL_IMPACT = "final_impact"


class SLMProposalType(str, Enum):
    SEMANTIC = "semantic"
    REFERENCE = "reference"


class SLMProposalRejectionReason(str, Enum):
    AUTHORITY_OR_SYSTEM_CONTRACT_VIOLATION = (
        "authority_or_system_contract_violation"
    )
    SOURCE_SPAN_OUT_OF_BOUNDS = "source_span_out_of_bounds"
    UNSUPPORTED_RULEPACK = "unsupported_rulepack"
    UNKNOWN_REFERENCE = "unknown_reference"
    HARD_STRUCTURAL_CONFLICT = "hard_structural_conflict"
    ROLE_COMPATIBILITY_UNRESOLVED = "role_compatibility_unresolved"


class AuthorityAxis(str, Enum):
    CURRENT_INTENT = "current_intent"
    ENTITY_IDENTITY = "entity_identity"
    HARD_CONSTRAINT = "hard_constraint"


class EvidenceAuthorityClass(str, Enum):
    CURRENT_DIRECT = "current_direct"
    TYPED_FACT = "typed_fact"
    VALIDATED_HISTORY_BINDING = "validated_history_binding"
    ACTIVE_HARD_FACT = "active_hard_fact"
    SLM_PROPOSAL = "slm_proposal"
    HISTORY_INFERENCE = "history_inference"
    MEMORY_DEFAULT = "memory_default"
    REPORTED_CONTENT = "reported_content"


class AuthorityComparison(str, Enum):
    HIGHER = "higher"
    LOWER = "lower"
    EQUAL = "equal"
    INCOMPARABLE = "incomparable"


class PipelineStage(str, Enum):
    DETERMINISTIC_PARSER = "deterministic_parser"
    PARSER_EVIDENCE = "parser_evidence"
    PRE_SLM_CANDIDATE_SET = "pre_slm_candidate_set"
    AMBIGUITY_TRIGGER = "ambiguity_trigger"
    SLM_ADAPTER = "slm_adapter"
    SLM_PROPOSAL_VALIDATION = "slm_proposal_validation"
    PROPOSAL_MERGE = "proposal_merge"
    UPDATED_CANDIDATE_SET = "updated_candidate_set"
    RULEPACK_LOOKUP = "rulepack_lookup"
    BASE_BLUEPRINT_LOAD = "base_blueprint_load"
    REQUIRED_ROLE_EVALUATION = "required_role_evaluation"
    INFORMATION_EVALUATION = "information_evaluation"
    GLOBAL_CONSTRAINT_ACTIVATION = "global_constraint_activation"
    PAIR_CONSTRAINT_ACTIVATION = "pair_constraint_activation"
    CONDITIONAL_INFORMATION_FINALIZATION = (
        "conditional_information_finalization"
    )
    CONSTRAINT_EFFECT_COMPOSITION = "constraint_effect_composition"
    FINAL_PLAN_REQUIREMENTS = "final_plan_requirements"
    FULL_CAPABILITY_EVALUATION = "full_capability_evaluation"
    CANDIDATE_EVALUATOR = "candidate_evaluator"
    CANDIDATE_DISPOSITION = "candidate_disposition"
    AUTHORIZED_FALLBACK = "authorized_fallback"
    DECISION_LOCK = "decision_lock"


PIPELINE_ORDER = tuple(PipelineStage)


@dataclass(frozen=True)
class AuthorityScope:
    semantic_slot: str
    scope: str
    target: str


@dataclass(frozen=True)
class AuthorityEvidence:
    authority_class: EvidenceAuthorityClass
    authority_scope: AuthorityScope


class ScopedAuthorityPolicy:
    _DIRECT_DOMINANCE = {
        AuthorityAxis.CURRENT_INTENT: frozenset(
            {
                (
                    EvidenceAuthorityClass.CURRENT_DIRECT,
                    EvidenceAuthorityClass.SLM_PROPOSAL,
                ),
                (
                    EvidenceAuthorityClass.SLM_PROPOSAL,
                    EvidenceAuthorityClass.MEMORY_DEFAULT,
                ),
            }
        ),
        AuthorityAxis.ENTITY_IDENTITY: frozenset(
            {
                (
                    EvidenceAuthorityClass.TYPED_FACT,
                    EvidenceAuthorityClass.SLM_PROPOSAL,
                ),
                (
                    EvidenceAuthorityClass.VALIDATED_HISTORY_BINDING,
                    EvidenceAuthorityClass.SLM_PROPOSAL,
                ),
            }
        ),
        AuthorityAxis.HARD_CONSTRAINT: frozenset(
            {
                (
                    EvidenceAuthorityClass.ACTIVE_HARD_FACT,
                    inferred,
                )
                for inferred in {
                    EvidenceAuthorityClass.SLM_PROPOSAL,
                    EvidenceAuthorityClass.HISTORY_INFERENCE,
                    EvidenceAuthorityClass.MEMORY_DEFAULT,
                    EvidenceAuthorityClass.REPORTED_CONTENT,
                }
            }
        ),
    }

    @classmethod
    def compare(
        cls,
        left: AuthorityEvidence,
        right: AuthorityEvidence,
        *,
        axis: AuthorityAxis,
    ) -> AuthorityComparison:
        if left.authority_scope != right.authority_scope:
            return AuthorityComparison.INCOMPARABLE
        if left.authority_class == right.authority_class:
            return AuthorityComparison.EQUAL
        dominance = cls._transitive_dominance(axis)
        pair = (left.authority_class, right.authority_class)
        if pair in dominance:
            return AuthorityComparison.HIGHER
        if (pair[1], pair[0]) in dominance:
            return AuthorityComparison.LOWER
        return AuthorityComparison.INCOMPARABLE

    @classmethod
    def _transitive_dominance(
        cls,
        axis: AuthorityAxis,
    ) -> frozenset[tuple[EvidenceAuthorityClass, EvidenceAuthorityClass]]:
        dominance = set(cls._DIRECT_DOMINANCE[axis])
        changed = True
        while changed:
            changed = False
            additions = {
                (left, right)
                for left, middle in dominance
                for next_middle, right in dominance
                if middle == next_middle and left != right
            } - dominance
            if additions:
                dominance.update(additions)
                changed = True
        return frozenset(dominance)


@dataclass(frozen=True)
class SLMProposal:
    proposal_id: str
    proposal_type: SLMProposalType
    rulepack_key: RulePackKey
    source_span: tuple[int, int]
    semantic_slot: str
    scope: str
    existing_reference_id: str = ""
    validation_status: SLMValidationStatus = SLMValidationStatus.UNRESOLVED
    merge_status: SLMMergeStatus = SLMMergeStatus.PROPOSED
    influence_status: SLMInfluenceStatus = SLMInfluenceStatus.UNUSED
    rejection_reason: SLMProposalRejectionReason | None = None

    def __post_init__(self) -> None:
        if not self.proposal_id or not self.semantic_slot or not self.scope:
            raise ValueError("SLM proposal requires identity, slot, and scope")
        start, end = self.source_span
        if start < 0 or end <= start:
            raise ValueError("SLM proposal has an invalid source span")
        if (
            self.proposal_type == SLMProposalType.REFERENCE
            and not self.existing_reference_id
        ):
            raise ValueError("reference proposal requires an existing reference")
        if (
            self.proposal_type == SLMProposalType.SEMANTIC
            and self.existing_reference_id
        ):
            raise ValueError("semantic proposal cannot carry an entity reference")

    @property
    def domain(self) -> Domain:
        return self.rulepack_key.domain

    @property
    def operation(self) -> Operation:
        return self.rulepack_key.operation


@dataclass(frozen=True)
class SLMValidationContext:
    prompt_length: int
    verified_reference_ids: frozenset[str]
    authority_contract_valid: bool = True
    system_contract_valid: bool = True
    role_compatibility_possible: bool = True
    hard_structural_conflict: bool = False


class SLMProposalValidator:
    @staticmethod
    def validate(
        proposal: SLMProposal,
        context: SLMValidationContext,
    ) -> SLMProposal:
        if (
            not context.authority_contract_valid
            or not context.system_contract_valid
        ):
            return replace(
                proposal,
                validation_status=SLMValidationStatus.INVALID,
                merge_status=SLMMergeStatus.REJECTED,
                rejection_reason=(
                    SLMProposalRejectionReason.AUTHORITY_OR_SYSTEM_CONTRACT_VIOLATION
                ),
            )
        if proposal.source_span[1] > context.prompt_length:
            return replace(
                proposal,
                validation_status=SLMValidationStatus.INVALID,
                merge_status=SLMMergeStatus.REJECTED,
                rejection_reason=SLMProposalRejectionReason.SOURCE_SPAN_OUT_OF_BOUNDS,
            )
        resolution = RULEPACK_REGISTRY.resolve_exact(proposal.rulepack_key)
        if resolution.availability != RulePackAvailability.FOUND:
            return replace(
                proposal,
                validation_status=SLMValidationStatus.INVALID,
                merge_status=SLMMergeStatus.REJECTED,
                rejection_reason=SLMProposalRejectionReason.UNSUPPORTED_RULEPACK,
            )
        if (
            proposal.proposal_type == SLMProposalType.REFERENCE
            and proposal.existing_reference_id
            not in context.verified_reference_ids
        ):
            return replace(
                proposal,
                validation_status=SLMValidationStatus.INVALID,
                merge_status=SLMMergeStatus.REJECTED,
                rejection_reason=SLMProposalRejectionReason.UNKNOWN_REFERENCE,
            )
        if context.hard_structural_conflict:
            return replace(
                proposal,
                validation_status=SLMValidationStatus.INVALID,
                merge_status=SLMMergeStatus.REJECTED,
                rejection_reason=SLMProposalRejectionReason.HARD_STRUCTURAL_CONFLICT,
            )
        if not context.role_compatibility_possible:
            return replace(
                proposal,
                validation_status=SLMValidationStatus.UNRESOLVED,
                merge_status=SLMMergeStatus.PROPOSED,
                rejection_reason=(
                    SLMProposalRejectionReason.ROLE_COMPATIBILITY_UNRESOLVED
                ),
            )
        return replace(
            proposal,
            validation_status=SLMValidationStatus.VALID,
            merge_status=SLMMergeStatus.PROPOSED,
            influence_status=SLMInfluenceStatus.UNUSED,
            rejection_reason=None,
        )


@dataclass(frozen=True)
class ProvisionalCandidate:
    candidate_id: str
    rulepack_key: RulePackKey
    proposal_id: str
    existing_reference_id: str
    provisional: bool = True


@dataclass(frozen=True)
class ProvisionalCandidateAdmission:
    proposal: SLMProposal
    candidate: ProvisionalCandidate


class ProvisionalCandidateFactory:
    @staticmethod
    def create(proposal: SLMProposal) -> ProvisionalCandidateAdmission | None:
        if (
            proposal.validation_status != SLMValidationStatus.VALID
            or proposal.merge_status != SLMMergeStatus.PROPOSED
        ):
            return None
        if (
            RULEPACK_REGISTRY.resolve_exact(proposal.rulepack_key).availability
            != RulePackAvailability.FOUND
        ):
            return None
        candidate = ProvisionalCandidate(
            candidate_id=f"provisional:{proposal.proposal_id}",
            rulepack_key=proposal.rulepack_key,
            proposal_id=proposal.proposal_id,
            existing_reference_id=proposal.existing_reference_id,
        )
        return ProvisionalCandidateAdmission(
            proposal=replace(
                proposal,
                influence_status=SLMInfluenceStatus.CANDIDATE_ADDED,
            ),
            candidate=candidate,
        )


@dataclass(frozen=True)
class SLMMergeAssessment:
    candidate_evaluation_completed: bool
    rulepack_supported: bool | None
    role_compatible: bool | None
    typed_fact_compatible: bool | None
    candidate_contract_valid: bool | None
    conflicts_active_evidence: bool = False
    conflict_resolved: bool = False
    corroborates_parser_evidence: bool = False


class SLMMergeFinalizer:
    @staticmethod
    def finalize(
        proposal: SLMProposal,
        *,
        assessment: SLMMergeAssessment,
        influence_status: SLMInfluenceStatus,
    ) -> SLMProposal:
        if proposal.validation_status != SLMValidationStatus.VALID:
            return proposal
        if (
            not assessment.candidate_evaluation_completed
            and influence_status
            in {
                SLMInfluenceStatus.RANK_CHANGED,
                SLMInfluenceStatus.FINAL_IMPACT,
            }
        ):
            raise ValueError("unevaluated SLM proposal cannot affect rank or decision")
        compatibility = (
            assessment.rulepack_supported,
            assessment.role_compatible,
            assessment.typed_fact_compatible,
            assessment.candidate_contract_valid,
        )
        if not assessment.candidate_evaluation_completed:
            merge = SLMMergeStatus.PROPOSED
        elif any(value is False for value in compatibility):
            merge = SLMMergeStatus.REJECTED
        elif any(value is None for value in compatibility):
            merge = SLMMergeStatus.PROPOSED
        elif (
            assessment.conflicts_active_evidence
            and not assessment.conflict_resolved
        ):
            merge = SLMMergeStatus.CONFLICTING
        elif assessment.corroborates_parser_evidence:
            merge = SLMMergeStatus.SUPPORTING
        else:
            merge = SLMMergeStatus.PROPOSED
        return replace(
            proposal,
            merge_status=merge,
            influence_status=SLMMergeFinalizer._max_influence(
                proposal.influence_status,
                influence_status,
            ),
        )

    @staticmethod
    def _max_influence(
        current: SLMInfluenceStatus,
        requested: SLMInfluenceStatus,
    ) -> SLMInfluenceStatus:
        order = {
            SLMInfluenceStatus.UNUSED: 0,
            SLMInfluenceStatus.CANDIDATE_ADDED: 1,
            SLMInfluenceStatus.RANK_CHANGED: 2,
            SLMInfluenceStatus.FINAL_IMPACT: 3,
        }
        return current if order[current] >= order[requested] else requested


@dataclass(frozen=True)
class SLMFailureTrace:
    slm_failure_reason: str
    parser_only_disposition: ExecutionDisposition
    slm_direct_disposition: ExecutionDisposition | None = None

    def __post_init__(self) -> None:
        if not self.slm_failure_reason:
            raise ValueError("SLM failure trace requires a failure reason")
        if not isinstance(self.parser_only_disposition, ExecutionDisposition):
            raise ValueError("SLM failure requires a parser-only disposition")
        if self.slm_direct_disposition is not None:
            raise ValueError("SLM failure cannot create a direct disposition")


def validate_pipeline_order() -> None:
    positions = {stage: index for index, stage in enumerate(PIPELINE_ORDER)}
    required_pairs = (
        (PipelineStage.DETERMINISTIC_PARSER, PipelineStage.PARSER_EVIDENCE),
        (PipelineStage.PARSER_EVIDENCE, PipelineStage.PRE_SLM_CANDIDATE_SET),
        (PipelineStage.DETERMINISTIC_PARSER, PipelineStage.PRE_SLM_CANDIDATE_SET),
        (PipelineStage.SLM_PROPOSAL_VALIDATION, PipelineStage.PROPOSAL_MERGE),
        (PipelineStage.PROPOSAL_MERGE, PipelineStage.UPDATED_CANDIDATE_SET),
        (PipelineStage.UPDATED_CANDIDATE_SET, PipelineStage.RULEPACK_LOOKUP),
        (PipelineStage.RULEPACK_LOOKUP, PipelineStage.BASE_BLUEPRINT_LOAD),
        (
            PipelineStage.BASE_BLUEPRINT_LOAD,
            PipelineStage.REQUIRED_ROLE_EVALUATION,
        ),
        (
            PipelineStage.REQUIRED_ROLE_EVALUATION,
            PipelineStage.INFORMATION_EVALUATION,
        ),
        (
            PipelineStage.INFORMATION_EVALUATION,
            PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION,
        ),
        (
            PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION,
            PipelineStage.PAIR_CONSTRAINT_ACTIVATION,
        ),
        (
            PipelineStage.PAIR_CONSTRAINT_ACTIVATION,
            PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION,
        ),
        (
            PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION,
            PipelineStage.CONSTRAINT_EFFECT_COMPOSITION,
        ),
        (
            PipelineStage.CONSTRAINT_EFFECT_COMPOSITION,
            PipelineStage.FINAL_PLAN_REQUIREMENTS,
        ),
        (
            PipelineStage.FINAL_PLAN_REQUIREMENTS,
            PipelineStage.FULL_CAPABILITY_EVALUATION,
        ),
        (
            PipelineStage.FULL_CAPABILITY_EVALUATION,
            PipelineStage.CANDIDATE_EVALUATOR,
        ),
        (
            PipelineStage.CANDIDATE_EVALUATOR,
            PipelineStage.CANDIDATE_DISPOSITION,
        ),
        (
            PipelineStage.CANDIDATE_DISPOSITION,
            PipelineStage.AUTHORIZED_FALLBACK,
        ),
        (PipelineStage.CANDIDATE_EVALUATOR, PipelineStage.AUTHORIZED_FALLBACK),
        (PipelineStage.AUTHORIZED_FALLBACK, PipelineStage.DECISION_LOCK),
    )
    for before, after in required_pairs:
        if positions[before] >= positions[after]:
            raise ValueError(f"invalid pipeline order: {before.value} -> {after.value}")


def validate_slm_contract() -> None:
    validate_pipeline_order()
