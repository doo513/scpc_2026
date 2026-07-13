from __future__ import annotations

from dataclasses import fields, FrozenInstanceError, replace
import inspect
from pathlib import Path

import pytest

from core.candidate_evaluation import (
    CandidateEvaluationContext,
    CandidateEvaluationEngine,
    CandidateIdentity,
    CandidateOrigin,
    CandidateSemanticKey,
    CandidateSetBuilder,
    EvaluationCandidate,
)
from core.contracts import (
    BUNDLE_ASSUMPTION_ID,
    DISPOSITION_PLAN_ASSUMPTION_ID,
    TARGET_ASSUMPTION_ID,
    ContractStatus,
)
from core.constraints import GLOBAL_CONSTRAINT_REGISTRY, ConstraintActivationState
from core.decision_ir import (
    AggregateOutputStatus,
    DecisionBundleBuilder,
    DecisionDependencyEdge,
    DecisionDependencyKind,
    DecisionProjectionBuilder,
    DisclosureDecision,
    FallbackOrigin,
    LockedPlanDecision,
    PlanProjectionStep,
    PolicyDecision,
    ResponseTargetBinding,
    ResponseTargetMappingStatus,
    SubDecisionIRBuilder,
    validate_decision_ir_contract,
)
from core.facts import CapabilitySnapshot
from core.ontology import (
    CapabilityType,
    DisclosureMode,
    Domain,
    ExecutionDisposition,
    FactStatus,
    Operation,
    PlanStepType,
    ReasonCode,
)
from core.plan_requirements import InternalTransformType
from core.rulepacks import (
    RULEPACK_REGISTRY,
    RulePackKey,
    SourceField,
)
from core.task_view import TaskView


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _candidate(*, clause: str, missing_amount: bool = False) -> EvaluationCandidate:
    key = RulePackKey(Domain.PAYMENT, Operation.EXECUTE)
    pack = RULEPACK_REGISTRY.lookup(key)
    assert pack is not None
    role = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    fields = [
        (SourceField.MERCHANT, "merchant:one"),
        (SourceField.METHOD, "method:token"),
    ]
    if not missing_amount:
        fields.append((SourceField.AMOUNT, "1000"))
    return EvaluationCandidate(
        identity=CandidateIdentity(
            "operation:payment",
            clause,
            f"evidence:{clause}",
            CandidateSemanticKey(
                key,
                "object:payment",
                "merchant:one",
            ),
        ),
        target_role=role.allowed_roles[0],
        target_locality=role.locality_constraints[0],
        target_identity_type=role.identity_type_constraints[0],
        satisfied_role_predicates=role.compatibility_predicates,
        failed_role_predicates=(),
        focal_fields=tuple(fields),
        operation_arguments=(),
        information_bindings=(),
        requested_disclosure=DisclosureMode.STATUS_ONLY,
        intent_rank=50,
        origin=CandidateOrigin.PARSER,
        provenance_ids=(f"evidence:{clause}",),
    )


def _capability_snapshot(
    capabilities: frozenset[CapabilityType] | None = None,
) -> CapabilitySnapshot:
    return CapabilitySnapshot(
        FactStatus.PRESENT,
        capabilities if capabilities is not None else frozenset(CapabilityType),
    )


def _evaluation(
    candidate: EvaluationCandidate,
    capabilities: frozenset[CapabilityType] | None = None,
):
    snapshot = _capability_snapshot(capabilities)
    context = CandidateEvaluationContext(
        global_constraint_facts=(),
        capability_snapshot=snapshot,
        internal_transform_capabilities=frozenset(InternalTransformType),
    )
    evaluation = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((candidate,)),
        context,
    )[0]
    return evaluation, snapshot


def _response(target: str = "response:one") -> ResponseTargetBinding:
    return ResponseTargetBinding(
        response_target=target,
        mapping_status=ResponseTargetMappingStatus.ASSUMPTION_LINKED,
        contract_status=ContractStatus.SUPPORTED_INTERPRETATION,
        contract_reference_ids=(TARGET_ASSUMPTION_ID,),
        derived_from=("evidence:response-target",),
    )


def _plan_for(evaluation) -> LockedPlanDecision:
    decision_id = SubDecisionIRBuilder.decision_id_for(evaluation)
    requirements = evaluation.assessment.final_plan_requirements
    disposition = {
        "executable": ExecutionDisposition.PROCEED,
        "amendable": ExecutionDisposition.AMEND,
        "needs_information": ExecutionDisposition.ASK,
        "needs_clarification": ExecutionDisposition.ASK,
        "conflicted": ExecutionDisposition.ASK,
        "blocked": ExecutionDisposition.HOLD,
        "rejected": ExecutionDisposition.HOLD,
        "unsupported_rulepack": ExecutionDisposition.HOLD,
    }[evaluation.candidate_state.value]
    if disposition in {ExecutionDisposition.PROCEED, ExecutionDisposition.AMEND}:
        assert requirements is not None
        steps = tuple(
            PlanProjectionStep(
                projection_step_id=f"projection:{step.step_id}",
                requirement_step_id=step.step_id,
                verb=step.output_verb,
                target=(
                    evaluation.candidate.semantic_key.target_id
                    if step.semantic_terminal
                    else evaluation.candidate.semantic_key.focal_id
                ),
                args=(),
                reason_codes=(ReasonCode.EXECUTABLE,),
                semantic_terminal=step.semantic_terminal,
            )
            for step in requirements.required_steps
            if step.output_verb is not None
        )
        return LockedPlanDecision(decision_id, steps)

    read_requirement_id = ""
    if requirements is not None:
        read_requirement_id = next(
            (
                step.step_id
                for step in requirements.required_steps
                if step.output_verb == PlanStepType.READ
            ),
            "",
        )
    assumption = (DISPOSITION_PLAN_ASSUMPTION_ID,)
    if disposition == ExecutionDisposition.ASK:
        return LockedPlanDecision(
            decision_id,
            (
                PlanProjectionStep(
                    "projection:read",
                    read_requirement_id,
                    PlanStepType.READ,
                    evaluation.candidate.semantic_key.focal_id,
                    (),
                    (ReasonCode.REQUIRED_INFORMATION_MISSING,),
                    () if read_requirement_id else assumption,
                ),
                PlanProjectionStep(
                    "projection:clarify",
                    "",
                    PlanStepType.CLARIFY,
                    "response:one",
                    (),
                    (ReasonCode.REQUIRED_INFORMATION_MISSING,),
                    assumption,
                ),
            ),
        )
    return LockedPlanDecision(
        decision_id,
        (
            PlanProjectionStep(
                "projection:read",
                read_requirement_id,
                PlanStepType.READ,
                evaluation.candidate.semantic_key.focal_id,
                (),
                (ReasonCode.CAPABILITY_UNAVAILABLE,),
                () if read_requirement_id else assumption,
            ),
            PlanProjectionStep(
                "projection:guard",
                "",
                PlanStepType.GUARD,
                evaluation.candidate.semantic_key.focal_id,
                (),
                (ReasonCode.CAPABILITY_UNAVAILABLE,),
                assumption,
            ),
        ),
    )


def _lock(evaluation, snapshot, *, response_target: str = "response:one"):
    is_hold = evaluation.candidate_state.value in {
        "blocked",
        "rejected",
        "unsupported_rulepack",
    }
    return SubDecisionIRBuilder.lock(
        evaluation=evaluation,
        response_target_binding=_response(response_target),
        disclosure=DisclosureDecision(
            DisclosureMode.NONE if is_hold else DisclosureMode.STATUS_ONLY,
            () if is_hold else ("status",),
            (),
            False,
            (),
        ),
        policy=PolicyDecision((), (), False, ()),
        plan_decision=_plan_for(evaluation),
        capability_snapshot=snapshot,
    )


def test_subdecision_lock_preserves_typed_candidate_semantics() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    decision = _lock(evaluation, snapshot)
    decision.verify_lock()
    assert decision.domain == Domain.PAYMENT
    assert decision.operation == Operation.EXECUTE
    assert decision.execution_target == "merchant:one"
    assert decision.response_target == "response:one"
    assert decision.execution_target != decision.response_target
    assert decision.execution_disposition == ExecutionDisposition.PROCEED
    assert decision.final_plan_requirements is not None
    assert decision.lock_digest
    assert ReasonCode.EXECUTABLE in decision.reason_codes
    assert "evidence:response-target" in decision.provenance_ids


def test_locked_semantics_cannot_be_changed_with_a_stale_digest() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    decision = _lock(evaluation, snapshot)
    with pytest.raises(ValueError):
        replace(decision, operation=Operation.CANCEL)
    with pytest.raises(FrozenInstanceError):
        decision.operation = Operation.CANCEL  # type: ignore[misc]


def test_response_target_mapping_never_defaults_from_execution_target() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    decision = _lock(evaluation, snapshot, response_target="user:interaction")
    assert decision.execution_target == "merchant:one"
    assert decision.response_target == "user:interaction"
    assert TARGET_ASSUMPTION_ID in decision.unresolved_assumption_refs


def test_hold_plan_is_locked_before_compiler_and_capability_checked() -> None:
    capabilities = frozenset(
        item for item in CapabilityType if item != CapabilityType.PAY
    )
    evaluation, snapshot = _evaluation(
        _candidate(clause="clause:blocked"),
        capabilities,
    )
    decision = _lock(evaluation, snapshot)
    assert decision.execution_disposition == ExecutionDisposition.HOLD
    assert tuple(step.verb for step in decision.plan_decision.steps) == (
        PlanStepType.READ,
        PlanStepType.GUARD,
    )
    assert DISPOSITION_PLAN_ASSUMPTION_ID in (
        decision.unresolved_assumption_refs
    )


def test_ask_plan_is_locked_without_execution_terminal() -> None:
    evaluation, snapshot = _evaluation(
        _candidate(clause="clause:missing", missing_amount=True)
    )
    decision = _lock(evaluation, snapshot)
    assert decision.execution_disposition == ExecutionDisposition.ASK
    assert tuple(step.verb for step in decision.plan_decision.steps) == (
        PlanStepType.READ,
        PlanStepType.CLARIFY,
    )
    assert not {
        PlanStepType.PAY,
        PlanStepType.DISPATCH,
        PlanStepType.UPDATE,
    } & {step.verb for step in decision.plan_decision.steps}


def test_output_plan_capability_is_validated_after_disposition() -> None:
    capabilities = frozenset(
        item
        for item in CapabilityType
        if item not in {CapabilityType.PAY, CapabilityType.GUARD}
    )
    evaluation, snapshot = _evaluation(
        _candidate(clause="clause:no-guard"),
        capabilities,
    )
    with pytest.raises(ValueError, match="unavailable capability"):
        _lock(evaluation, snapshot)


def test_invalid_capability_snapshot_cannot_be_locked_as_an_empty_capability_set() -> None:
    evaluation, _snapshot = _evaluation(_candidate(clause="clause:invalid-snapshot"))
    invalid_snapshot = CapabilitySnapshot(FactStatus.MISSING, frozenset())
    with pytest.raises(ValueError, match="invalid capability snapshot"):
        _lock(evaluation, invalid_snapshot)


def test_execution_projection_cannot_add_a_step_outside_requirements() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    plan = _plan_for(evaluation)
    extra = PlanProjectionStep(
        "projection:extra",
        "",
        PlanStepType.GUARD,
        "object:payment",
        (),
        (ReasonCode.UNKNOWN,),
        (DISPOSITION_PLAN_ASSUMPTION_ID,),
    )
    with pytest.raises(ValueError, match="differs from plan requirements"):
        SubDecisionIRBuilder.lock(
            evaluation=evaluation,
            response_target_binding=_response(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
            ),
            policy=PolicyDecision((), (), False, ()),
            plan_decision=replace(plan, steps=plan.steps + (extra,)),
            capability_snapshot=snapshot,
        )


def test_execution_projection_cannot_reorder_required_steps() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:reordered"))
    plan = _plan_for(evaluation)
    assert len(plan.steps) > 1
    with pytest.raises(ValueError, match="differs from plan requirements"):
        SubDecisionIRBuilder.lock(
            evaluation=evaluation,
            response_target_binding=_response(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
            ),
            policy=PolicyDecision((), (), False, ()),
            plan_decision=replace(plan, steps=tuple(reversed(plan.steps))),
            capability_snapshot=snapshot,
        )


def test_execution_projection_cannot_change_semantic_terminal() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:terminal"))
    plan = _plan_for(evaluation)
    changed = tuple(
        replace(step, semantic_terminal=not step.semantic_terminal)
        for step in plan.steps
    )
    with pytest.raises(ValueError, match="changes semantic terminal"):
        SubDecisionIRBuilder.lock(
            evaluation=evaluation,
            response_target_binding=_response(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
            ),
            policy=PolicyDecision((), (), False, ()),
            plan_decision=replace(plan, steps=changed),
            capability_snapshot=snapshot,
        )


def test_policy_and_disclosure_lineage_cannot_reference_unknown_sources() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    with pytest.raises(ValueError, match="unknown safeguard"):
        SubDecisionIRBuilder.lock(
            evaluation=evaluation,
            response_target_binding=_response(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                ("effect:not-active",),
            ),
            policy=PolicyDecision((), (), False, ()),
            plan_decision=_plan_for(evaluation),
            capability_snapshot=snapshot,
        )
    with pytest.raises(ValueError, match="inactive constraint"):
        SubDecisionIRBuilder.lock(
            evaluation=evaluation,
            response_target_binding=_response(),
            disclosure=DisclosureDecision(
                DisclosureMode.STATUS_ONLY,
                ("status",),
                (),
                False,
                (),
            ),
            policy=PolicyDecision((), (), False, ("constraint:not-active",)),
            plan_decision=_plan_for(evaluation),
            capability_snapshot=snapshot,
        )


def test_conflicted_constraint_is_not_relabelled_as_active_in_decision_ir() -> None:
    key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    pack = RULEPACK_REGISTRY.lookup(key)
    assert pack is not None
    role = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    candidate = EvaluationCandidate(
        identity=CandidateIdentity(
            "operation:share",
            "clause:conflict",
            "evidence:conflict",
            CandidateSemanticKey(key, "object:content", "recipient:external"),
        ),
        target_role=role.allowed_roles[0],
        target_locality=role.locality_constraints[0],
        target_identity_type=role.identity_type_constraints[0],
        satisfied_role_predicates=role.compatibility_predicates,
        failed_role_predicates=(),
        focal_fields=(),
        operation_arguments=(),
        information_bindings=(),
        requested_disclosure=DisclosureMode.RAW,
        intent_rank=50,
        origin=CandidateOrigin.STRUCTURAL,
        provenance_ids=("evidence:conflict",),
    )
    view = TaskView(
        {
            "id": "constraint-conflict",
            "device_state": {
                "objects": [],
                "records": [
                    {"id": "consent:a", "type": "consent", "value": "granted"},
                    {"id": "consent:b", "type": "consent", "value": "revoked"},
                ],
            },
            "available_actions": [item.value for item in CapabilityType],
        }
    )
    context = CandidateEvaluationContext(
        global_constraint_facts=GLOBAL_CONSTRAINT_REGISTRY.collect(
            view.typed_records
        ),
        capability_snapshot=_capability_snapshot(),
        internal_transform_capabilities=frozenset(InternalTransformType),
    )
    evaluation = CandidateEvaluationEngine.evaluate_set(
        CandidateSetBuilder.build((candidate,)),
        context,
    )[0]
    activation = evaluation.assessment.constraint_activation
    assert activation is not None
    assert any(
        item.state == ConstraintActivationState.CONFLICTED
        for item in activation.constraints
    )
    assert activation.active_constraints == ()
    decision = _lock(evaluation, context.capability_snapshot)
    assert decision.active_constraints == ()


def test_single_operation_is_represented_as_a_one_decision_bundle() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    decision = _lock(evaluation, snapshot)
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:one",
        primary_focal_id=decision.focal_id,
        sub_decisions=(decision,),
    )
    bundle.verify_lock()
    assert bundle.aggregate_output_status == AggregateOutputStatus.SINGLE
    assert len(bundle.sub_decisions) == 1
    assert "control" not in {field.name for field in fields(bundle)}


def test_multi_decision_bundle_keeps_subdecision_dispositions() -> None:
    first_eval, snapshot = _evaluation(_candidate(clause="clause:first"))
    second_eval, _ = _evaluation(
        _candidate(clause="clause:second", missing_amount=True)
    )
    first = _lock(first_eval, snapshot)
    second = _lock(second_eval, snapshot)
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:multiple",
        primary_focal_id=first.focal_id,
        sub_decisions=(second, first),
    )
    assert bundle.aggregate_output_status == (
        AggregateOutputStatus.MULTIPLE_UNRESOLVED
    )
    assert BUNDLE_ASSUMPTION_ID in bundle.unresolved_assumption_refs
    assert {item.execution_disposition for item in bundle.sub_decisions} == {
        ExecutionDisposition.PROCEED,
        ExecutionDisposition.ASK,
    }


def test_dependency_edges_require_explicit_references_and_form_a_dag() -> None:
    first_eval, snapshot = _evaluation(_candidate(clause="clause:first"))
    second_eval, _ = _evaluation(_candidate(clause="clause:second"))
    first = _lock(first_eval, snapshot)
    second = _lock(second_eval, snapshot)
    edge = DecisionDependencyEdge(
        first.decision_id,
        second.decision_id,
        DecisionDependencyKind.READ_AFTER_WRITE,
        "reference:memory-value",
    )
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:dependency",
        primary_focal_id=first.focal_id,
        sub_decisions=(first, second),
        dependency_edges=(edge,),
    )
    bundle.verify_lock()
    reverse = DecisionDependencyEdge(
        second.decision_id,
        first.decision_id,
        DecisionDependencyKind.REQUIRES_SUCCESS,
        "reference:reverse",
    )
    with pytest.raises(ValueError, match="cycle"):
        DecisionBundleBuilder.lock(
            bundle_id="bundle:cycle",
            primary_focal_id=first.focal_id,
            sub_decisions=(first, second),
            dependency_edges=(edge, reverse),
        )
    with pytest.raises(ValueError, match="explicit reference"):
        DecisionDependencyEdge(
            first.decision_id,
            second.decision_id,
            DecisionDependencyKind.REQUIRES_SUCCESS,
            "",
        )


def test_projection_dtos_are_lossless_pure_views_of_locked_decisions() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:one"))
    decision = _lock(evaluation, snapshot)
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:projection",
        primary_focal_id=decision.focal_id,
        sub_decisions=(decision,),
    )
    first = DecisionProjectionBuilder.build(bundle)
    second = DecisionProjectionBuilder.build(bundle)
    assert first == second
    assert first.scopes[0].mode == decision.disclosure.mode
    assert first.policies[0].reason_codes == decision.reason_codes
    assert first.plans[0].steps == decision.plan_decision.steps
    assert first.scopes[0].source_lock_digest == decision.lock_digest
    assert first.source_bundle_lock_digest == bundle.bundle_lock_digest


def test_fallback_origin_records_actual_selected_destination() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="clause:destination"))
    origin = FallbackOrigin(
        "edge:one",
        "candidate:source",
        evaluation.candidate.candidate_id,
        ("evidence:fallback",),
    )
    decision = SubDecisionIRBuilder.lock(
        evaluation=evaluation,
        response_target_binding=_response(),
        disclosure=DisclosureDecision(
            DisclosureMode.STATUS_ONLY,
            ("status",),
            (),
            False,
            (),
        ),
        policy=PolicyDecision((), (), False, ()),
        plan_decision=_plan_for(evaluation),
        capability_snapshot=snapshot,
        fallback_origin=origin,
    )
    assert decision.fallback_origin is not None
    assert decision.fallback_origin.destination_candidate_id == (
        decision.selected_candidate_id
    )
    assert ReasonCode.AVOIDED_BY_AUTHORIZED_FALLBACK in decision.reason_codes
    assert "evidence:fallback" in decision.provenance_ids


def test_derived_ir_uses_lineage_not_fake_source_spans() -> None:
    ir_fields = {field.name for field in fields(__import__(
        "core.decision_ir", fromlist=["SubDecisionIR"]
    ).SubDecisionIR)}
    assert "provenance_ids" in ir_fields
    assert "source_span" not in ir_fields
    assert "raw_text" not in ir_fields


def test_decision_ir_and_projection_layers_are_shadow_only_and_raw_free() -> None:
    validate_decision_ir_contract()
    source = (PROJECT_ROOT / "core" / "decision_ir.py").read_text(encoding="utf-8")
    for prohibited in (
        "TaskView",
        "EvidenceGraph",
        "visible_history",
        "personal_memory",
        "raw_record",
        "ActionProfile",
    ):
        assert prohibited not in source
    projection_source = inspect.getsource(DecisionProjectionBuilder)
    assert "CandidateEvaluator" not in projection_source
    assert "prompt" not in projection_source
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "decision_ir" not in production
