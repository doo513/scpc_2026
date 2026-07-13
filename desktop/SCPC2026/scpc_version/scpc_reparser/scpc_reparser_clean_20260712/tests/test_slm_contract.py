from __future__ import annotations

from dataclasses import fields
import inspect

import pytest

from core.ontology import Domain, ExecutionDisposition, Operation
from core.rulepacks import RulePackKey
from core.slm_contract import (
    PIPELINE_ORDER,
    AuthorityAxis,
    AuthorityComparison,
    AuthorityEvidence,
    AuthorityScope,
    EvidenceAuthorityClass,
    PipelineStage,
    ProvisionalCandidateFactory,
    SLMFailureTrace,
    SLMInfluenceStatus,
    SLMMergeAssessment,
    SLMMergeFinalizer,
    SLMMergeStatus,
    SLMProposal,
    SLMProposalRejectionReason,
    SLMProposalType,
    SLMProposalValidator,
    SLMValidationContext,
    SLMValidationStatus,
    ScopedAuthorityPolicy,
    validate_slm_contract,
)


def _semantic_proposal(
    *,
    key: RulePackKey | None = None,
) -> SLMProposal:
    return SLMProposal(
        proposal_id="slm:proposal:one",
        proposal_type=SLMProposalType.SEMANTIC,
        rulepack_key=key or RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        source_span=(2, 8),
        semantic_slot="operation",
        scope="clause:one",
    )


def _context(**overrides: object) -> SLMValidationContext:
    values = {
        "prompt_length": 20,
        "verified_reference_ids": frozenset({"object:known"}),
    }
    values.update(overrides)
    return SLMValidationContext(**values)


def _authority(
    authority_class: EvidenceAuthorityClass,
    *,
    slot: str = "operation",
    scope: str = "clause:one",
    target: str = "object:one",
) -> AuthorityEvidence:
    return AuthorityEvidence(
        authority_class,
        AuthorityScope(slot, scope, target),
    )


def test_pipeline_loads_rulepack_and_blueprint_before_candidate_evaluation() -> None:
    validate_slm_contract()
    position = {stage: index for index, stage in enumerate(PIPELINE_ORDER)}
    assert position[PipelineStage.RULEPACK_LOOKUP] < position[
        PipelineStage.BASE_BLUEPRINT_LOAD
    ]
    assert position[PipelineStage.BASE_BLUEPRINT_LOAD] < position[
        PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION
    ]
    assert position[PipelineStage.CONSTRAINT_EFFECT_COMPOSITION] < position[
        PipelineStage.FINAL_PLAN_REQUIREMENTS
    ]
    assert position[PipelineStage.PAIR_CONSTRAINT_ACTIVATION] < position[
        PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION
    ]
    assert position[PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION] < position[
        PipelineStage.CONSTRAINT_EFFECT_COMPOSITION
    ]
    assert position[PipelineStage.FINAL_PLAN_REQUIREMENTS] < position[
        PipelineStage.FULL_CAPABILITY_EVALUATION
    ]
    assert position[PipelineStage.FULL_CAPABILITY_EVALUATION] < position[
        PipelineStage.CANDIDATE_EVALUATOR
    ]
    assert position[PipelineStage.CANDIDATE_EVALUATOR] < position[
        PipelineStage.AUTHORIZED_FALLBACK
    ]
    assert position[PipelineStage.AUTHORIZED_FALLBACK] < position[
        PipelineStage.DECISION_LOCK
    ]


def test_slm_status_axes_are_separate_and_have_no_accepted_shortcut() -> None:
    assert "ACCEPTED" not in SLMValidationStatus.__members__
    assert "ACCEPTED" not in SLMMergeStatus.__members__
    assert "ACCEPTED" not in SLMInfluenceStatus.__members__

    validated = SLMProposalValidator.validate(_semantic_proposal(), _context())
    assert validated.validation_status == SLMValidationStatus.VALID
    assert validated.merge_status == SLMMergeStatus.PROPOSED
    assert validated.influence_status == SLMInfluenceStatus.UNUSED


def test_semantic_proposal_needs_no_entity_reference() -> None:
    proposal = _semantic_proposal()
    validated = SLMProposalValidator.validate(proposal, _context())
    assert validated.validation_status == SLMValidationStatus.VALID
    assert validated.existing_reference_id == ""

    with pytest.raises(ValueError, match="cannot carry an entity reference"):
        SLMProposal(
            proposal_id="slm:semantic:bad-reference",
            proposal_type=SLMProposalType.SEMANTIC,
            rulepack_key=RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
            source_span=(0, 4),
            semantic_slot="operation",
            scope="clause:one",
            existing_reference_id="object:invented",
        )


def test_reference_proposal_requires_a_verified_existing_reference() -> None:
    proposal = SLMProposal(
        proposal_id="slm:reference:one",
        proposal_type=SLMProposalType.REFERENCE,
        rulepack_key=RulePackKey(Domain.DEVICE, Operation.MODIFY),
        source_span=(0, 4),
        semantic_slot="target",
        scope="clause:one",
        existing_reference_id="object:unknown",
    )
    invalid = SLMProposalValidator.validate(proposal, _context())
    assert invalid.validation_status == SLMValidationStatus.INVALID
    assert invalid.merge_status == SLMMergeStatus.REJECTED
    assert invalid.rejection_reason == SLMProposalRejectionReason.UNKNOWN_REFERENCE

    known = SLMProposalValidator.validate(
        proposal,
        _context(verified_reference_ids=frozenset({"object:unknown"})),
    )
    assert known.validation_status == SLMValidationStatus.VALID


def test_unregistered_exact_rulepack_is_rejected_without_fallback() -> None:
    proposal = _semantic_proposal(
        key=RulePackKey(Domain.PAYMENT, Operation.CANCEL)
    )
    invalid = SLMProposalValidator.validate(proposal, _context())
    assert invalid.validation_status == SLMValidationStatus.INVALID
    assert invalid.merge_status == SLMMergeStatus.REJECTED
    assert invalid.rejection_reason == (
        SLMProposalRejectionReason.UNSUPPORTED_RULEPACK
    )
    assert ProvisionalCandidateFactory.create(invalid) is None


def test_provisional_candidate_is_added_only_after_minimum_validation() -> None:
    proposed = SLMProposalValidator.validate(_semantic_proposal(), _context())
    admission = ProvisionalCandidateFactory.create(proposed)
    assert admission is not None
    assert admission.candidate.provisional is True
    assert admission.candidate.existing_reference_id == ""
    assert admission.proposal.merge_status == SLMMergeStatus.PROPOSED
    assert admission.proposal.influence_status == (
        SLMInfluenceStatus.CANDIDATE_ADDED
    )
    assert "rank" not in {field.name for field in fields(admission.candidate)}


def test_merge_finalization_uses_compatibility_not_candidate_disposition() -> None:
    proposed = SLMProposalValidator.validate(_semantic_proposal(), _context())
    assessment = SLMMergeAssessment(
        candidate_evaluation_completed=True,
        rulepack_supported=True,
        role_compatible=True,
        typed_fact_compatible=True,
        candidate_contract_valid=True,
        corroborates_parser_evidence=True,
    )
    supporting = SLMMergeFinalizer.finalize(
        proposed,
        assessment=assessment,
        influence_status=SLMInfluenceStatus.FINAL_IMPACT,
    )
    assert supporting.merge_status == SLMMergeStatus.SUPPORTING
    assert supporting.influence_status == SLMInfluenceStatus.FINAL_IMPACT
    finalizer_parameters = inspect.signature(
        SLMMergeFinalizer.finalize
    ).parameters
    assert "candidate_state" not in finalizer_parameters


def test_merge_conflict_and_contract_rejection_remain_distinct() -> None:
    proposed = SLMProposalValidator.validate(_semantic_proposal(), _context())
    conflicted = SLMMergeFinalizer.finalize(
        proposed,
        assessment=SLMMergeAssessment(
            candidate_evaluation_completed=True,
            rulepack_supported=True,
            role_compatible=True,
            typed_fact_compatible=True,
            candidate_contract_valid=True,
            conflicts_active_evidence=True,
        ),
        influence_status=SLMInfluenceStatus.CANDIDATE_ADDED,
    )
    rejected = SLMMergeFinalizer.finalize(
        proposed,
        assessment=SLMMergeAssessment(
            candidate_evaluation_completed=True,
            rulepack_supported=True,
            role_compatible=False,
            typed_fact_compatible=True,
            candidate_contract_valid=True,
        ),
        influence_status=SLMInfluenceStatus.UNUSED,
    )
    assert conflicted.merge_status == SLMMergeStatus.CONFLICTING
    assert rejected.merge_status == SLMMergeStatus.REJECTED


def test_unevaluated_proposal_cannot_claim_rank_or_final_impact() -> None:
    proposed = SLMProposalValidator.validate(_semantic_proposal(), _context())
    assessment = SLMMergeAssessment(
        candidate_evaluation_completed=False,
        rulepack_supported=None,
        role_compatible=None,
        typed_fact_compatible=None,
        candidate_contract_valid=None,
    )
    with pytest.raises(ValueError, match="cannot affect rank"):
        SLMMergeFinalizer.finalize(
            proposed,
            assessment=assessment,
            influence_status=SLMInfluenceStatus.RANK_CHANGED,
        )


def test_authority_is_a_scoped_axis_specific_partial_order() -> None:
    direct = _authority(EvidenceAuthorityClass.CURRENT_DIRECT)
    slm = _authority(EvidenceAuthorityClass.SLM_PROPOSAL)
    memory = _authority(EvidenceAuthorityClass.MEMORY_DEFAULT)
    history = _authority(EvidenceAuthorityClass.HISTORY_INFERENCE)
    assert ScopedAuthorityPolicy.compare(
        direct, slm, axis=AuthorityAxis.CURRENT_INTENT
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        slm, memory, axis=AuthorityAxis.CURRENT_INTENT
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        direct, memory, axis=AuthorityAxis.CURRENT_INTENT
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        history, slm, axis=AuthorityAxis.CURRENT_INTENT
    ) == AuthorityComparison.INCOMPARABLE

    typed = _authority(EvidenceAuthorityClass.TYPED_FACT, slot="entity")
    bound = _authority(
        EvidenceAuthorityClass.VALIDATED_HISTORY_BINDING,
        slot="entity",
    )
    entity_slm = _authority(EvidenceAuthorityClass.SLM_PROPOSAL, slot="entity")
    assert ScopedAuthorityPolicy.compare(
        typed, entity_slm, axis=AuthorityAxis.ENTITY_IDENTITY
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        bound, entity_slm, axis=AuthorityAxis.ENTITY_IDENTITY
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        typed, bound, axis=AuthorityAxis.ENTITY_IDENTITY
    ) == AuthorityComparison.INCOMPARABLE


def test_hard_constraint_authority_only_dominates_inference_in_same_scope() -> None:
    hard = _authority(EvidenceAuthorityClass.ACTIVE_HARD_FACT, slot="constraint")
    inferred = _authority(
        EvidenceAuthorityClass.SLM_PROPOSAL,
        slot="constraint",
    )
    direct = _authority(
        EvidenceAuthorityClass.CURRENT_DIRECT,
        slot="constraint",
    )
    other_scope = _authority(
        EvidenceAuthorityClass.SLM_PROPOSAL,
        slot="constraint",
        target="object:other",
    )
    assert ScopedAuthorityPolicy.compare(
        hard, inferred, axis=AuthorityAxis.HARD_CONSTRAINT
    ) == AuthorityComparison.HIGHER
    assert ScopedAuthorityPolicy.compare(
        hard, direct, axis=AuthorityAxis.HARD_CONSTRAINT
    ) == AuthorityComparison.INCOMPARABLE
    assert ScopedAuthorityPolicy.compare(
        hard, other_scope, axis=AuthorityAxis.HARD_CONSTRAINT
    ) == AuthorityComparison.INCOMPARABLE


def test_slm_confidence_cannot_raise_authority_because_it_is_not_a_field() -> None:
    assert "confidence" not in {field.name for field in fields(SLMProposal)}
    assert "confidence" not in {field.name for field in fields(AuthorityEvidence)}


def test_slm_failure_never_creates_a_direct_disposition() -> None:
    trace = SLMFailureTrace(
        slm_failure_reason="timeout",
        parser_only_disposition=ExecutionDisposition.ASK,
    )
    assert trace.parser_only_disposition == ExecutionDisposition.ASK
    assert trace.slm_direct_disposition is None
    with pytest.raises(ValueError, match="cannot create a direct disposition"):
        SLMFailureTrace(
            slm_failure_reason="timeout",
            parser_only_disposition=ExecutionDisposition.ASK,
            slm_direct_disposition=ExecutionDisposition.HOLD,
        )
    with pytest.raises(ValueError, match="parser-only disposition"):
        SLMFailureTrace(
            slm_failure_reason="invalid_schema",
            parser_only_disposition=None,  # type: ignore[arg-type]
        )


def test_step6_adds_no_slm_runtime_or_model_dependency() -> None:
    source = inspect.getsource(inspect.getmodule(SLMProposal))
    for prohibited in (
        "transformers",
        "torch",
        "requests",
        "openai",
        "temperature",
        "model.generate",
    ):
        assert prohibited not in source
