from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path

import pytest

from core.ontology import (
    CapabilityType,
    ConstraintEffect,
    Domain,
    Operation,
    PlanStepType,
)
from core.ownership import OWNERSHIP_REGISTRY
from core.plan_requirements import (
    PLAN_BLUEPRINT_REGISTRY,
    BasePlanBlueprint,
    DependencySemantic,
    FinalPlanRequirementsBuilder,
    InternalTransformType,
    PlanRequirementClass,
    PlanRequirementComposer,
    PlanRequirementDelta,
    PlanRequirementDeltaSource,
    PlanStepIdentity,
    validate_plan_blueprint_registry,
)
from core.rulepacks import (
    BLUEPRINT_CATALOG,
    RULEPACK_REGISTRY,
    RegistryImplementationStatus,
    RulePackKey,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _resolution(domain: Domain, operation: Operation):
    return RULEPACK_REGISTRY.resolve_exact(RulePackKey(domain, operation))


def _constraint_delta(
    effect_id: str,
    effect: ConstraintEffect,
    *,
    scope: str = "candidate:one",
    parameters: tuple[tuple[str, str], ...] = (),
) -> PlanRequirementDelta:
    return PlanRequirementDelta(
        effect_id=effect_id,
        effect_kind=effect,
        source_id=f"constraint:{effect_id}",
        scope=scope,
        source_kind=PlanRequirementDeltaSource.ACTIVE_CONSTRAINT,
        parameters=parameters,
    )


def test_blueprint_registry_has_exact_implemented_catalog_coverage() -> None:
    validate_plan_blueprint_registry()
    assert PLAN_BLUEPRINT_REGISTRY.production_active is False
    assert {item.blueprint_id for item in PLAN_BLUEPRINT_REGISTRY.blueprints} == {
        item.blueprint_id for item in BLUEPRINT_CATALOG
    }
    assert all(
        item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
        and item.activation_stage == 6
        for item in BLUEPRINT_CATALOG
    )
    for pack in RULEPACK_REGISTRY.rulepacks:
        blueprint = PLAN_BLUEPRINT_REGISTRY.lookup(pack.base_blueprint_id)
        assert isinstance(blueprint, BasePlanBlueprint)
        assert blueprint.key == pack.key


def test_each_blueprint_has_one_terminal_and_closed_dependencies() -> None:
    for blueprint in PLAN_BLUEPRINT_REGISTRY.blueprints:
        terminals = [step for step in blueprint.base_steps if step.semantic_terminal]
        assert len(terminals) == 1
        assert terminals[0].output_verb == blueprint.semantic_terminal
        step_ids = {step.step_id for step in blueprint.base_steps}
        assert all(
            edge.before_step_id in step_ids and edge.after_step_id in step_ids
            for edge in blueprint.dependency_semantics
        )


def test_base_blueprint_build_does_not_emit_a_completed_output_event_array() -> None:
    requirements = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:content",
        resolution=_resolution(Domain.CONTENT, Operation.SHARE),
    )
    assert requirements.semantic_terminal == PlanStepType.DISPATCH
    assert sum(step.semantic_terminal for step in requirements.required_steps) == 1
    assert not hasattr(requirements, "to_event")
    assert not hasattr(requirements, "plan_events")


def test_effect_composition_is_deterministic_idempotent_and_trace_preserving() -> None:
    deltas = (
        _constraint_delta("summary", ConstraintEffect.FORCE_SUMMARY),
        _constraint_delta("redact-b", ConstraintEffect.ADD_REDACTION),
        _constraint_delta("redact-a", ConstraintEffect.ADD_REDACTION),
        _constraint_delta("confirm", ConstraintEffect.ADD_CONFIRMATION),
    )
    kwargs = {
        "candidate_id": "candidate:content",
        "resolution": _resolution(Domain.CONTENT, Operation.SHARE),
    }
    first = FinalPlanRequirementsBuilder.build(**kwargs, deltas=deltas)
    second = FinalPlanRequirementsBuilder.build(**kwargs, deltas=reversed(deltas))

    assert first == second
    inserted = [
        step.identity
        for step in first.required_steps
        if step.insertion_point.value == "before_terminal"
    ]
    assert inserted == [
        PlanStepIdentity.REDACT,
        PlanStepIdentity.SUMMARIZE,
        PlanStepIdentity.CONFIRM,
    ]
    assert first.applied_effect_ids == (
        "redact-a",
        "redact-b",
        "summary",
        "confirm",
    )


def test_safeguards_preserve_operation_and_semantic_terminal() -> None:
    resolution = _resolution(Domain.CONTENT, Operation.SHARE)
    base = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:content",
        resolution=resolution,
    )
    amended = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:content",
        resolution=resolution,
        deltas=(
            _constraint_delta("redact", ConstraintEffect.ADD_REDACTION),
            _constraint_delta("summary", ConstraintEffect.FORCE_SUMMARY),
        ),
    )
    assert amended.domain == base.domain == Domain.CONTENT
    assert amended.operation == base.operation == Operation.SHARE
    assert amended.semantic_terminal == base.semantic_terminal == PlanStepType.DISPATCH
    assert amended.terminal_step.step_id == base.terminal_step.step_id


def test_effect_added_platform_capabilities_are_checked_as_platform_actions() -> None:
    amended = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:content",
        resolution=_resolution(Domain.CONTENT, Operation.SHARE),
        deltas=(
            _constraint_delta("redact", ConstraintEffect.ADD_REDACTION),
            _constraint_delta("summary", ConstraintEffect.FORCE_SUMMARY),
        ),
    )
    assert CapabilityType.REDACT in amended.platform_required_capabilities
    assert CapabilityType.SUMMARIZE in amended.platform_required_capabilities
    assert InternalTransformType.REDACT_CONTENT not in (
        amended.internal_transform_requirements
    )
    assert InternalTransformType.SUMMARIZE_CONTENT not in (
        amended.internal_transform_requirements
    )
    assert any(
        step.requirement_class == PlanRequirementClass.INTERNAL_PREPARATION
        for step in amended.required_steps
    )
    assert all(
        step.platform_capability is None
        for step in amended.required_steps
        if step.requirement_class != PlanRequirementClass.PLATFORM_ACTION
    )


def test_limit_duration_conflict_is_not_resolved_by_input_order() -> None:
    deltas = (
        _constraint_delta(
            "limit-short",
            ConstraintEffect.LIMIT_DURATION,
            parameters=(("duration", "5m"),),
        ),
        _constraint_delta(
            "limit-long",
            ConstraintEffect.LIMIT_DURATION,
            parameters=(("duration", "10m"),),
        ),
    )
    with pytest.raises(ValueError, match="conflicting terminal parameter"):
        FinalPlanRequirementsBuilder.build(
            candidate_id="candidate:device",
            resolution=_resolution(Domain.DEVICE, Operation.MODIFY),
            deltas=deltas,
        )


def test_modification_requires_an_explicit_authorization_reference() -> None:
    with pytest.raises(ValueError, match="authorization reference"):
        PlanRequirementDelta(
            effect_id="modification:one",
            effect_kind=ConstraintEffect.LIMIT_DURATION,
            source_id="current-user-evidence:one",
            scope="candidate:device",
            source_kind=PlanRequirementDeltaSource.AUTHORIZED_MODIFICATION,
        )


def test_unsupported_rulepack_cannot_produce_plan_requirements() -> None:
    unsupported = _resolution(Domain.PAYMENT, Operation.CANCEL)
    with pytest.raises(ValueError, match="unsupported RulePack"):
        FinalPlanRequirementsBuilder.build(
            candidate_id="candidate:unsupported",
            resolution=unsupported,
        )


def test_fallback_destination_is_built_from_its_own_rulepack_and_blueprint() -> None:
    source = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:payment",
        resolution=_resolution(Domain.PAYMENT, Operation.EXECUTE),
    )
    destination = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:share",
        resolution=_resolution(Domain.CONTENT, Operation.SHARE),
    )
    assert source.rulepack_id != destination.rulepack_id
    assert source.blueprint_id != destination.blueprint_id
    assert source.semantic_terminal == PlanStepType.PAY
    assert destination.semantic_terminal == PlanStepType.DISPATCH


def test_final_requirements_reject_unknown_dependency_steps() -> None:
    valid = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:content",
        resolution=_resolution(Domain.CONTENT, Operation.SHARE),
    )
    with pytest.raises(ValueError, match="nonexistent plan step"):
        replace(
            valid,
            dependency_semantics=(
                DependencySemantic("missing:step", valid.terminal_step.step_id),
            ),
        )


def test_effect_id_collision_and_unregistered_effect_are_rejected() -> None:
    first = _constraint_delta("same", ConstraintEffect.ADD_REDACTION)
    collision = _constraint_delta("same", ConstraintEffect.FORCE_SUMMARY)
    resolution = _resolution(Domain.CONTENT, Operation.SHARE)
    with pytest.raises(ValueError, match="effect ID collision"):
        FinalPlanRequirementsBuilder.build(
            candidate_id="candidate:content",
            resolution=resolution,
            deltas=(first, collision),
        )
    with pytest.raises(ValueError, match="unsupported plan effect"):
        FinalPlanRequirementsBuilder.build(
            candidate_id="candidate:content",
            resolution=resolution,
            deltas=(
                _constraint_delta("raw", ConstraintEffect.ALLOW_RAW),
            ),
        )


def test_final_plan_requirements_has_one_owner_and_no_raw_input_access() -> None:
    ownership = {item.field: item for item in OWNERSHIP_REGISTRY}
    assert ownership["blueprint_id"].final_owner == "BasePlanBlueprint"
    assert ownership["final_plan_requirements"].producer == (
        "PlanRequirementComposer"
    )
    assert ownership["final_plan_requirements"].final_owner == (
        "FinalPlanRequirements"
    )

    source = inspect.getsource(PlanRequirementComposer)
    for prohibited in ("prompt", "record", "history", "memory", "TaskView"):
        assert prohibited not in source


def test_step6_registry_is_not_imported_by_the_current_production_path() -> None:
    for relative in (
        "core/decision.py",
        "harness.py",
        "rules/plan.py",
    ):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "plan_requirements" not in source

