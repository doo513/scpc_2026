from __future__ import annotations

import inspect
from pathlib import Path

from core.candidate_evaluation import (
    CandidateEvaluationContext,
    CandidateEvaluationEngine,
    CandidateEvaluator,
    CandidateIdentity,
    CandidateInformationStatus,
    CandidateOrigin,
    CandidateRankingPolicy,
    CandidateSelectionStatus,
    CandidateSemanticKey,
    CandidateSetBuilder,
    CapabilityEvaluationStatus,
    EvaluationCandidate,
    InformationBinding,
    InformationBindingStatus,
    RoleCompatibilityStatus,
    validate_candidate_evaluation_contract,
)
from core.constraints import GLOBAL_CONSTRAINT_REGISTRY
from core.contracts import DISPOSITION_ASSUMPTION_ID
from core.facts import CapabilitySnapshot
from core.ontology import (
    CandidateState,
    CapabilityType,
    DisclosureMode,
    Domain,
    FactStatus,
    InformationSlot,
    Operation,
    TargetLocality,
    TargetRole,
)
from core.plan_requirements import InternalTransformType
from core.rulepacks import (
    RULEPACK_REGISTRY,
    CompatibilityPredicate,
    IdentityTypeConstraint,
    RulePackKey,
    RuleVariant,
    SourceField,
)
from core.task_view import TaskView
from core.slm_contract import PipelineStage


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _role_defaults(key: RulePackKey):
    pack = RULEPACK_REGISTRY.lookup(key)
    if pack is None:
        return (
            TargetRole.MERCHANT,
            TargetLocality.DOMAIN,
            IdentityTypeConstraint.DOMAIN_IDENTIFIER,
            (CompatibilityPredicate.FOCAL_MERCHANT_COMPATIBLE,),
        )
    spec = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    return (
        spec.allowed_roles[0],
        spec.locality_constraints[0],
        spec.identity_type_constraints[0],
        spec.compatibility_predicates,
    )


def _default_information(key: RulePackKey):
    focal_fields: tuple[tuple[SourceField, str], ...] = ()
    operation_arguments: tuple[tuple[SourceField, str], ...] = ()
    bindings: tuple[InformationBinding, ...] = ()
    if key.domain == Domain.PAYMENT and key.operation != Operation.VERIFY:
        focal_fields = (
            (SourceField.MERCHANT, "merchant:one"),
            (SourceField.AMOUNT, "1000"),
            (SourceField.METHOD, "method:token"),
        )
    elif key.domain == Domain.DEVICE and key.operation != Operation.VERIFY:
        focal_fields = ((SourceField.NAME, "device:one"),)
        operation_arguments = ((SourceField.DESIRED_STATE, "enabled"),)
    elif key.domain == Domain.CALENDAR and key.operation != Operation.VERIFY:
        focal_fields = (
            (SourceField.TITLE, "event:one"),
            (SourceField.TIME, "10:00"),
        )
    elif key.operation == Operation.VERIFY:
        focal_fields = ((SourceField.OPERATION_REFERENCE, "operation:one"),)
    if key.domain == Domain.MEMORY and key.variant == RuleVariant.PERSISTENT_MEMORY:
        bindings = (
            InformationBinding(
                InformationSlot.MEMORY_VALUE,
                InformationBindingStatus.PRESENT,
                "memory:value",
                ("record:memory",),
            ),
        )
    return focal_fields, operation_arguments, bindings


def _candidate(
    key: RulePackKey,
    *,
    clause: str,
    sub_operation: str = "operation:one",
    evidence_group: str = "evidence:one",
    rank: int = 50,
    origin: CandidateOrigin = CandidateOrigin.PARSER,
    focal_id: str = "object:focal",
    target_id: str | None = None,
    role: TargetRole | None = None,
    locality: TargetLocality | None = None,
    identity_type: IdentityTypeConstraint | None = None,
    predicates: tuple[CompatibilityPredicate, ...] | None = None,
    failed_predicates: tuple[CompatibilityPredicate, ...] = (),
    focal_fields: tuple[tuple[SourceField, str], ...] | None = None,
    operation_arguments: tuple[tuple[SourceField, str], ...] | None = None,
    bindings: tuple[InformationBinding, ...] | None = None,
) -> EvaluationCandidate:
    default_role, default_locality, default_identity, default_predicates = (
        _role_defaults(key)
    )
    default_fields, default_arguments, default_bindings = _default_information(key)
    if target_id is None:
        target_id = {
            Domain.PAYMENT: "merchant:one",
            Domain.DEVICE: "device:one",
            Domain.CALENDAR: "event:one",
            Domain.MEMORY: "memory_store",
            Domain.GENERAL: "user",
        }.get(key.domain, "target:one")
    return EvaluationCandidate(
        identity=CandidateIdentity(
            sub_operation,
            clause,
            evidence_group,
            CandidateSemanticKey(key, focal_id, target_id),
        ),
        target_role=role or default_role,
        target_locality=locality or default_locality,
        target_identity_type=(
            default_identity if identity_type is None else identity_type
        ),
        satisfied_role_predicates=(
            default_predicates if predicates is None else predicates
        ),
        failed_role_predicates=failed_predicates,
        focal_fields=default_fields if focal_fields is None else focal_fields,
        operation_arguments=(
            default_arguments
            if operation_arguments is None
            else operation_arguments
        ),
        information_bindings=(
            default_bindings if bindings is None else bindings
        ),
        requested_disclosure=DisclosureMode.RAW,
        intent_rank=rank,
        origin=origin,
        provenance_ids=(f"evidence:{clause}",),
    )


def _context(
    *,
    records: list[dict[str, object]] | None = None,
    capabilities: frozenset[CapabilityType] | None = None,
    capability_status: FactStatus = FactStatus.PRESENT,
    internal: frozenset[InternalTransformType] | None = None,
) -> CandidateEvaluationContext:
    task = {
        "id": "candidate-test",
        "session_id": "candidate-session",
        "prompt": "",
        "device_state": {"objects": [], "records": records or []},
        "available_actions": [],
    }
    view = TaskView(task)
    facts = GLOBAL_CONSTRAINT_REGISTRY.collect(view.typed_records)
    return CandidateEvaluationContext(
        global_constraint_facts=facts,
        capability_snapshot=CapabilitySnapshot(
            capability_status,
            capabilities
            if capabilities is not None
            else frozenset(CapabilityType),
        ),
        internal_transform_capabilities=(
            internal
            if internal is not None
            else frozenset(InternalTransformType)
        ),
    )


def _evaluate(candidate: EvaluationCandidate, context=None):
    result = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((candidate,)),
        context or _context(),
    )
    assert len(result) == 1
    return result[0]


def test_same_semantic_key_from_different_clauses_is_not_overwritten() -> None:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    first = _candidate(key, clause="clause:one")
    second = _candidate(key, clause="clause:two")
    candidate_set = CandidateSetBuilder.build((second, first))
    assert len(candidate_set.candidates) == 2
    assert first.semantic_key == second.semantic_key
    assert first.candidate_id != second.candidate_id

    evaluations = CandidateEvaluationEngine.evaluate_set(candidate_set, _context())
    selection = CandidateRankingPolicy.select(evaluations)
    assert selection.status == CandidateSelectionStatus.SELECTED
    assert set(selection.equivalent_source_candidate_ids) == {
        first.candidate_id,
        second.candidate_id,
    }


def test_candidate_set_builder_has_no_cartesian_product_path() -> None:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    seeds = tuple(
        _candidate(key, clause=f"clause:{index}") for index in range(4)
    )
    candidate_set = CandidateSetBuilder.build(seeds)
    assert len(candidate_set.candidates) == len(seeds)
    source = inspect.getsource(CandidateSetBuilder)
    for prohibited in ("product(", "itertools", "for focal", "for target"):
        assert prohibited not in source


def test_axis_order_precedes_candidate_evaluator_aggregation() -> None:
    result = _evaluate(
        _candidate(
            RulePackKey(Domain.CONTENT, Operation.SHARE),
            clause="clause:share",
        )
    )
    assert result.assessment.assessment_order == (
        PipelineStage.RULEPACK_LOOKUP,
        PipelineStage.BASE_BLUEPRINT_LOAD,
        PipelineStage.REQUIRED_ROLE_EVALUATION,
        PipelineStage.INFORMATION_EVALUATION,
        PipelineStage.GLOBAL_CONSTRAINT_ACTIVATION,
        PipelineStage.PAIR_CONSTRAINT_ACTIVATION,
        PipelineStage.CONDITIONAL_INFORMATION_FINALIZATION,
        PipelineStage.CONSTRAINT_EFFECT_COMPOSITION,
        PipelineStage.FINAL_PLAN_REQUIREMENTS,
        PipelineStage.FULL_CAPABILITY_EVALUATION,
    )
    evaluator_source = inspect.getsource(CandidateEvaluator)
    for prohibited in (
        "RULEPACK_REGISTRY",
        "PLAN_BLUEPRINT_REGISTRY",
        "PairConstraintActivator",
        "FullCapabilityEvaluator",
    ):
        assert prohibited not in evaluator_source


def test_complete_candidate_is_viable_with_full_plan_capability() -> None:
    result = _evaluate(
        _candidate(
            RulePackKey(Domain.CONTENT, Operation.SHARE),
            clause="clause:share",
        )
    )
    assert result.candidate_state == CandidateState.VIABLE
    assert result.assessment.role is not None
    assert result.assessment.role.status == RoleCompatibilityStatus.COMPATIBLE
    assert result.assessment.information is not None
    assert result.assessment.information.status == (
        CandidateInformationStatus.COMPLETE
    )
    assert result.assessment.capability.status == CapabilityEvaluationStatus.AVAILABLE
    assert result.assessment.final_plan_requirements is not None
    assert result.assessment.final_plan_requirements.semantic_terminal.value == (
        "dispatch"
    )


def test_every_registered_rulepack_reaches_full_axis_evaluation() -> None:
    for index, pack in enumerate(RULEPACK_REGISTRY.rulepacks):
        result = _evaluate(
            _candidate(pack.key, clause=f"clause:rulepack:{index}")
        )
        assert result.assessment.rulepack is pack
        assert result.assessment.blueprint is not None
        assert result.assessment.information is not None
        assert result.assessment.information.status == (
            CandidateInformationStatus.COMPLETE
        )
        assert result.assessment.final_plan_requirements is not None
        assert result.assessment.capability.status == (
            CapabilityEvaluationStatus.AVAILABLE
        )
        assert result.candidate_state == CandidateState.VIABLE


def test_each_generated_platform_requirement_participates_in_capability_ablation() -> None:
    for index, pack in enumerate(RULEPACK_REGISTRY.rulepacks):
        candidate = _candidate(pack.key, clause=f"clause:ablation:{index}")
        baseline = _evaluate(candidate)
        requirements = baseline.assessment.final_plan_requirements
        assert requirements is not None
        for capability in requirements.platform_required_capabilities:
            ablated = _evaluate(
                candidate,
                _context(
                    capabilities=frozenset(
                        item for item in CapabilityType if item != capability
                    )
                ),
            )
            assert ablated.assessment.capability.status == (
                CapabilityEvaluationStatus.UNAVAILABLE
            )
            assert capability in (
                ablated.assessment.capability.missing_platform_capabilities
            )


def test_information_and_capability_are_independent_axes() -> None:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    missing_amount = _candidate(
        key,
        clause="clause:payment",
        focal_fields=(
            (SourceField.MERCHANT, "merchant:one"),
            (SourceField.METHOD, "method:token"),
        ),
    )
    result = _evaluate(missing_amount)
    assert result.assessment.information is not None
    assert result.assessment.information.status == CandidateInformationStatus.MISSING
    assert result.assessment.information.missing_slots == (InformationSlot.AMOUNT,)
    assert result.assessment.capability.status == CapabilityEvaluationStatus.AVAILABLE
    assert result.candidate_state == CandidateState.NEEDS_INFORMATION


def test_effect_added_capability_is_included_in_full_capability_check() -> None:
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.REDACT
    )
    result = _evaluate(
        _candidate(
            RulePackKey(Domain.CONTENT, Operation.SHARE),
            clause="clause:share",
        ),
        _context(
            records=[
                {
                    "id": "policy",
                    "type": "external_share_policy",
                    "value": "raw_quote_forbidden",
                }
            ],
            capabilities=capabilities,
        ),
    )
    assert result.assessment.capability.status == CapabilityEvaluationStatus.UNAVAILABLE
    assert result.assessment.capability.missing_platform_capabilities == (
        CapabilityType.REDACT,
    )
    assert result.candidate_state == CandidateState.BLOCKED


def test_internal_transform_capability_is_not_hidden_in_available_actions() -> None:
    result = _evaluate(
        _candidate(
            RulePackKey(Domain.CONTENT, Operation.SHARE),
            clause="clause:share",
        ),
        _context(internal=frozenset()),
    )
    assert result.assessment.capability.status == CapabilityEvaluationStatus.UNAVAILABLE
    assert result.assessment.capability.missing_internal_transforms == (
        InternalTransformType.LOCATE_CONTENT,
    )


def test_high_rank_role_incompatible_candidate_cannot_beat_viable_candidate() -> None:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    incompatible = _candidate(
        key,
        clause="clause:wrong-role",
        rank=100,
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.EXTERNAL,
        identity_type=IdentityTypeConstraint.EXTERNAL_IDENTIFIER,
        predicates=(),
    )
    viable = _candidate(key, clause="clause:valid", rank=10)
    evaluations = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((incompatible, viable)),
        _context(),
    )
    by_id = {item.candidate.candidate_id: item for item in evaluations}
    assert by_id[incompatible.candidate_id].candidate_state == CandidateState.REJECTED
    selection = CandidateRankingPolicy.select(evaluations)
    assert selection.selected_candidate_id == viable.candidate_id


def test_high_rank_blocked_candidate_cannot_beat_lower_viable_candidate() -> None:
    blocked = _candidate(
        RulePackKey(Domain.CONTENT, Operation.SHARE),
        clause="clause:external",
        rank=100,
    )
    local = _candidate(
        RulePackKey(
            Domain.MEMORY,
            Operation.LOCAL_UPDATE,
            RuleVariant.LOCAL_STATE,
        ),
        clause="clause:local",
        rank=10,
        target_id="memory_store",
    )
    evaluations = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((blocked, local)),
        _context(
            records=[
                {"id": "consent", "type": "consent", "value": "revoked"}
            ]
        ),
    )
    by_id = {item.candidate.candidate_id: item for item in evaluations}
    assert by_id[blocked.candidate_id].candidate_state == CandidateState.BLOCKED
    assert by_id[local.candidate_id].candidate_state == CandidateState.VIABLE
    selection = CandidateRankingPolicy.select(evaluations)
    assert selection.selected_candidate_id == local.candidate_id


def test_missing_information_plus_block_does_not_use_an_implicit_precedence() -> None:
    candidate = _candidate(
        RulePackKey(Domain.CONTENT, Operation.SHARE),
        clause="clause:blocked-missing",
        target_id="",
        role=TargetRole.UNRESOLVED,
        locality=TargetLocality.UNKNOWN,
        identity_type=None,
        predicates=(),
    )
    result = _evaluate(
        candidate,
        _context(
            records=[
                {"id": "consent", "type": "consent", "value": "revoked"}
            ]
        ),
    )
    # Target-dependent consent is not activated before the target is known.
    assert result.candidate_state == CandidateState.NEEDS_INFORMATION
    assert result.disposition.precedence_resolved is True

    payment = _candidate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        clause="clause:payment-missing-blocked",
        focal_fields=((SourceField.MERCHANT, "merchant:one"),),
    )
    blocked_and_missing = _evaluate(
        payment,
        _context(capabilities=frozenset()),
    )
    assert blocked_and_missing.candidate_state == CandidateState.CONFLICTED
    assert blocked_and_missing.disposition.precedence_resolved is False
    assert DISPOSITION_ASSUMPTION_ID in (
        blocked_and_missing.disposition.assumption_refs
    )


def test_constraint_dependent_information_is_finalized_after_activation() -> None:
    candidate = _candidate(
        RulePackKey(Domain.DEVICE, Operation.MODIFY),
        clause="clause:device",
    )
    limited = _evaluate(
        candidate,
        _context(
            records=[
                {
                    "id": "temporary",
                    "type": "temporary_override_allowed",
                    "value": "2h",
                }
            ]
        ),
    )
    assert limited.assessment.information is not None
    assert limited.assessment.information.status == CandidateInformationStatus.COMPLETE
    duration = [
        item
        for item in limited.assessment.information.bindings
        if item.slot == InformationSlot.DURATION
    ]
    assert duration and duration[0].canonical_value == "2h"
    assert limited.candidate_state == CandidateState.AMENDABLE

    ambiguous = _evaluate(
        candidate,
        _context(
            records=[
                {
                    "id": "duration",
                    "type": "duration_ambiguous",
                    "value": "present",
                }
            ]
        ),
    )
    assert ambiguous.assessment.information is not None
    assert ambiguous.assessment.information.status == CandidateInformationStatus.MISSING
    assert ambiguous.candidate_state == CandidateState.CONFLICTED
    assert ambiguous.disposition.precedence_resolved is False


def test_unsupported_rulepack_stays_unsupported_without_default_dispatch() -> None:
    result = _evaluate(
        _candidate(
            RulePackKey(Domain.PAYMENT, Operation.CANCEL),
            clause="clause:cancel",
        )
    )
    assert result.candidate_state == CandidateState.UNSUPPORTED_RULEPACK
    assert result.assessment.rulepack is None
    assert result.assessment.blueprint is None
    assert result.assessment.final_plan_requirements is None


def test_slm_origin_receives_no_ranking_or_authority_bonus() -> None:
    parser = _candidate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        clause="clause:parser",
        rank=50,
        origin=CandidateOrigin.PARSER,
    )
    slm = _candidate(
        RulePackKey(Domain.DEVICE, Operation.MODIFY),
        clause="clause:slm",
        rank=50,
        origin=CandidateOrigin.SLM_PROVISIONAL,
    )
    evaluations = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((slm, parser)),
        _context(),
    )
    selection = CandidateRankingPolicy.select(evaluations)
    assert selection.status == CandidateSelectionStatus.USER_CHOICE_REQUIRED
    assert "origin" not in inspect.getsource(CandidateRankingPolicy)


def test_conflicting_constraint_fact_is_not_collapsed_to_blocked() -> None:
    candidate = _candidate(
        RulePackKey(Domain.CONTENT, Operation.SHARE),
        clause="clause:share",
    )
    task = {
        "id": "conflict",
        "device_state": {
            "objects": [],
            "records": [
                {"id": "a", "type": "consent", "value": "granted"},
                {"id": "b", "type": "consent", "value": "revoked"},
            ],
        },
        "available_actions": [item.value for item in CapabilityType],
    }
    view = TaskView(task)
    context = CandidateEvaluationContext(
        GLOBAL_CONSTRAINT_REGISTRY.collect(view.typed_records),
        view.capability_snapshot,
        frozenset(InternalTransformType),
    )
    result = _evaluate(candidate, context)
    assert result.candidate_state == CandidateState.CONFLICTED
    assert result.disposition.precedence_resolved is True


def test_missing_available_actions_is_unresolved_not_empty_capability() -> None:
    candidate = _candidate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        clause="clause:payment",
    )
    result = _evaluate(
        candidate,
        _context(capability_status=FactStatus.MISSING),
    )
    assert result.assessment.capability.status == CapabilityEvaluationStatus.UNRESOLVED
    assert result.candidate_state == CandidateState.CONFLICTED


def test_conflicted_capability_snapshot_remains_unresolved() -> None:
    candidate = _candidate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        clause="clause:payment",
    )
    result = _evaluate(
        candidate,
        _context(capability_status=FactStatus.CONFLICTED),
    )
    assert result.assessment.capability.status == CapabilityEvaluationStatus.UNRESOLVED
    assert result.candidate_state == CandidateState.CONFLICTED


def test_candidate_evaluator_is_shadow_only_and_has_no_raw_text_access() -> None:
    validate_candidate_evaluation_contract()
    source = (PROJECT_ROOT / "core" / "candidate_evaluation.py").read_text(
        encoding="utf-8"
    )
    for prohibited in (
        "visible_history",
        "personal_memory",
        "default_dispatch",
        "re.compile",
        "TaskView",
    ):
        assert prohibited not in source
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "candidate_evaluation" not in production
