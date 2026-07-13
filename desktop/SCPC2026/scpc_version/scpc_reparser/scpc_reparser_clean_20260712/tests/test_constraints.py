from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from core.constraints import (
    GLOBAL_CONSTRAINT_REGISTRY,
    PAIR_CONSTRAINT_REGISTRY,
    CandidateConstraint,
    ConstraintActivationScope,
    ConstraintActivationState,
    ConstraintCandidateContext,
    ConstraintEffectAlgebra,
    ConstraintEffectInstance,
    ConstraintFactPolarity,
    EffectAlgebraStatus,
    PairConstraintActivator,
    validate_constraint_registries,
)
from core.ontology import (
    CapabilityType,
    ConstraintEffect,
    ConstraintType,
    Domain,
    Operation,
    PlanStepType,
    ReasonCode,
    TargetLocality,
    TargetRole,
)
from core.plan_requirements import FinalPlanRequirementsBuilder
from core.ownership import OWNERSHIP_REGISTRY
from core.rulepacks import (
    CONSTRAINT_CATALOG,
    RULEPACK_REGISTRY,
    RegistryImplementationStatus,
    RulePackKey,
    RuleVariant,
)
from core.task_view import TaskView


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _view(records: list[dict[str, object]]) -> TaskView:
    return TaskView(
        {
            "id": "constraint-test",
            "session_id": "constraint-session",
            "turn_index": 1,
            "prompt": "",
            "visible_history": [],
            "personal_memory": [],
            "device_state": {"objects": [], "records": records},
            "available_actions": [item.value for item in CapabilityType],
        }
    )


def _global_facts(records: list[dict[str, object]]):
    return GLOBAL_CONSTRAINT_REGISTRY.collect(_view(records).typed_records)


def _context(
    key: RulePackKey,
    *,
    candidate_id: str = "candidate:one",
    target_id: str = "target:one",
    role: TargetRole,
    locality: TargetLocality,
) -> ConstraintCandidateContext:
    return ConstraintCandidateContext(
        candidate_id=candidate_id,
        rulepack_key=key,
        focal_id="object:focal",
        target_id=target_id,
        target_role=role,
        target_locality=locality,
    )


def _activate(
    key: RulePackKey,
    records: list[dict[str, object]],
    *,
    role: TargetRole,
    locality: TargetLocality,
):
    resolution = RULEPACK_REGISTRY.resolve_exact(key)
    assert resolution.rulepack is not None
    return PairConstraintActivator.activate(
        context=_context(key, role=role, locality=locality),
        rulepack=resolution.rulepack,
        global_facts=_global_facts(records),
    )


def _manual_constraint(
    *,
    constraint_id: str,
    effect_id: str,
    effect: ConstraintEffect,
    parameters: tuple[tuple[str, str], ...] = (),
) -> CandidateConstraint:
    scope = ConstraintActivationScope(
        Domain.DEVICE,
        Operation.MODIFY,
        "device:one",
        TargetRole.DEVICE_TARGET,
        TargetLocality.DOMAIN,
    )
    instance = ConstraintEffectInstance(
        effect_id=effect_id,
        effect=effect,
        activation_scope=scope,
        parameters=parameters,
        source_constraint_ids=(constraint_id,),
        source_fact_ids=(f"record:{constraint_id}",),
        reason_code_ids=(ReasonCode.TEMPORARY_OVERRIDE_LIMIT,),
    )
    return CandidateConstraint(
        constraint_id=constraint_id,
        constraint_type=ConstraintType.TEMPORARY_OVERRIDE,
        source_fact_ids=(f"record:{constraint_id}",),
        activation_scope=scope,
        applied_candidate_id="candidate:one",
        effects=(instance,),
        reason_code_ids=(ReasonCode.TEMPORARY_OVERRIDE_LIMIT,),
        state=ConstraintActivationState.ACTIVE,
    )


def test_constraint_registries_cover_exact_rulepack_references() -> None:
    validate_constraint_registries()
    assert GLOBAL_CONSTRAINT_REGISTRY.production_active is False
    assert PAIR_CONSTRAINT_REGISTRY.production_active is False
    assert {item.constraint_id for item in PAIR_CONSTRAINT_REGISTRY.specs} == {
        item.constraint_id for item in CONSTRAINT_CATALOG
    }
    assert all(
        item.implementation_status == RegistryImplementationStatus.IMPLEMENTED
        and item.activation_stage == 7
        for item in CONSTRAINT_CATALOG
    )
    for pack in RULEPACK_REGISTRY.rulepacks:
        for constraint_id in pack.pair_constraint_ids:
            spec = PAIR_CONSTRAINT_REGISTRY.lookup(constraint_id)
            assert spec is not None
            assert spec.applicability_for(pack.key) is not None


def test_global_constraint_facts_are_order_independent_and_deduplicated() -> None:
    records = [
        {"id": "consent-b", "type": "consent", "value": "revoked"},
        {"id": "consent-a", "type": "consent", "value": "revoked"},
        {"id": "security", "type": "security_alert", "value": "active"},
    ]
    view = _view(records)
    first = GLOBAL_CONSTRAINT_REGISTRY.collect(view.direct_record_facts)
    second = GLOBAL_CONSTRAINT_REGISTRY.collect(
        reversed(view.direct_record_facts)
    )
    assert first == second
    assert len(first) == 2
    consent = next(item for item in first if item.record_type.value == "consent")
    assert consent.polarity == ConstraintFactPolarity.ACTIVE
    assert consent.source_fact_ids == ("record:consent-a", "record:consent-b")


def test_consent_granted_and_revoked_keep_distinct_fact_polarity() -> None:
    granted = _global_facts(
        [{"id": "consent", "type": "consent", "value": "granted"}]
    )[0]
    revoked = _global_facts(
        [{"id": "consent", "type": "consent", "value": "revoked"}]
    )[0]
    assert granted.polarity == ConstraintFactPolarity.INACTIVE
    assert revoked.polarity == ConstraintFactPolarity.ACTIVE


def test_consent_is_pair_scoped_to_external_content_share() -> None:
    records = [{"id": "consent", "type": "consent", "value": "revoked"}]
    key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    external = _activate(
        key,
        records,
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.EXTERNAL,
    )
    local = _activate(
        key,
        records,
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.LOCAL,
    )
    external_consent = next(
        item
        for item in external.evaluations
        if item.constraint_id == "CONSTRAINT-DISPATCH-CONSENT"
    )
    local_consent = next(
        item
        for item in local.evaluations
        if item.constraint_id == "CONSTRAINT-DISPATCH-CONSENT"
    )
    assert external_consent.state == ConstraintActivationState.ACTIVE
    assert external_consent.constraint is not None
    assert external_consent.constraint.effects[0].effect == (
        ConstraintEffect.BLOCK_EXECUTION
    )
    assert local_consent.state == ConstraintActivationState.INACTIVE

    memory_key = RulePackKey(
        Domain.MEMORY,
        Operation.LOCAL_UPDATE,
        RuleVariant.LOCAL_STATE,
    )
    memory = _activate(
        memory_key,
        records,
        role=TargetRole.LOCAL_RESOURCE,
        locality=TargetLocality.LOCAL,
    )
    assert memory.evaluations == ()


def test_security_fact_applies_only_to_registered_action_target_pairs() -> None:
    records = [
        {"id": "security", "type": "security_alert", "value": "active"}
    ]
    content = _activate(
        RulePackKey(Domain.CONTENT, Operation.SHARE),
        records,
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.EXTERNAL,
    )
    payment = _activate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        records,
        role=TargetRole.MERCHANT,
        locality=TargetLocality.DOMAIN,
    )
    device = _activate(
        RulePackKey(Domain.DEVICE, Operation.MODIFY),
        records,
        role=TargetRole.DEVICE_TARGET,
        locality=TargetLocality.DOMAIN,
    )
    assert any(
        constraint.constraint_id == "CONSTRAINT-DISPATCH-SECURITY"
        for constraint in content.active_constraints
    )
    assert any(
        constraint.constraint_id == "CONSTRAINT-DISPATCH-SECURITY"
        for constraint in payment.active_constraints
    )
    assert all(
        constraint.constraint_id != "CONSTRAINT-DISPATCH-SECURITY"
        for constraint in device.active_constraints
    )


@pytest.mark.parametrize(
    ("code", "effect"),
    (
        ("raw_quote_forbidden", ConstraintEffect.ADD_REDACTION),
        ("raw_sensitive_forbidden", ConstraintEffect.ADD_REDACTION),
        ("summary_only_allowed", ConstraintEffect.FORCE_SUMMARY),
        ("doctor_note_forbidden", ConstraintEffect.BLOCK_EXECUTION),
    ),
)
def test_structured_external_policy_codes_map_through_typed_effect_rules(
    code: str,
    effect: ConstraintEffect,
) -> None:
    bundle = _activate(
        RulePackKey(Domain.CONTENT, Operation.SHARE),
        [{"id": "policy", "type": "external_share_policy", "value": code}],
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.EXTERNAL,
    )
    policy = next(
        item
        for item in bundle.active_constraints
        if item.constraint_id == "CONSTRAINT-EXTERNAL-SHARE-POLICY"
    )
    assert tuple(item.effect for item in policy.effects) == (effect,)


def test_temporary_override_and_duration_ambiguity_are_separate_effects() -> None:
    key = RulePackKey(Domain.DEVICE, Operation.MODIFY)
    limited = _activate(
        key,
        [
            {
                "id": "temporary",
                "type": "temporary_override_allowed",
                "value": "2h",
            }
        ],
        role=TargetRole.DEVICE_TARGET,
        locality=TargetLocality.DOMAIN,
    )
    temporary = next(
        item
        for item in limited.active_constraints
        if item.constraint_id == "CONSTRAINT-TEMPORARY-OVERRIDE"
    )
    assert temporary.effects[0].effect == ConstraintEffect.LIMIT_DURATION
    assert temporary.effects[0].parameters == (("duration", "2h"),)

    ambiguous = _activate(
        key,
        [
            {
                "id": "duration",
                "type": "duration_ambiguous",
                "value": "present",
            }
        ],
        role=TargetRole.DEVICE_TARGET,
        locality=TargetLocality.DOMAIN,
    )
    duration = next(
        item
        for item in ambiguous.active_constraints
        if item.constraint_id == "CONSTRAINT-TEMPORARY-OVERRIDE"
    )
    assert duration.effects[0].effect == ConstraintEffect.ADD_CONFIRMATION


def test_conflicting_structured_facts_remain_conflicted_without_effect() -> None:
    records = [
        {"id": "consent-old", "type": "consent", "value": "granted"},
        {"id": "consent-new", "type": "consent", "value": "revoked"},
    ]
    view = _view(records)
    facts = GLOBAL_CONSTRAINT_REGISTRY.collect(view.direct_record_facts)
    consent = next(item for item in facts if item.record_type.value == "consent")
    assert consent.polarity == ConstraintFactPolarity.CONFLICTED

    key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    resolution = RULEPACK_REGISTRY.resolve_exact(key)
    assert resolution.rulepack is not None
    bundle = PairConstraintActivator.activate(
        context=_context(
            key,
            role=TargetRole.DISPATCH_DESTINATION,
            locality=TargetLocality.EXTERNAL,
        ),
        rulepack=resolution.rulepack,
        global_facts=facts,
    )
    evaluation = next(
        item
        for item in bundle.evaluations
        if item.constraint_id == "CONSTRAINT-DISPATCH-CONSENT"
    )
    assert evaluation.state == ConstraintActivationState.CONFLICTED
    assert evaluation.constraint is not None
    assert evaluation.constraint.effects == ()
    algebra = ConstraintEffectAlgebra.compose(bundle.constraints)
    assert algebra.status == EffectAlgebraStatus.CONFLICTED


def test_effect_algebra_is_permutation_invariant_and_idempotent() -> None:
    first_constraint = _manual_constraint(
        constraint_id="constraint:a",
        effect_id="effect:a",
        effect=ConstraintEffect.LIMIT_DURATION,
        parameters=(("duration", "2h"),),
    )
    duplicate = _manual_constraint(
        constraint_id="constraint:b",
        effect_id="effect:b",
        effect=ConstraintEffect.LIMIT_DURATION,
        parameters=(("duration", "2h"),),
    )
    first = ConstraintEffectAlgebra.compose((first_constraint, duplicate))
    second = ConstraintEffectAlgebra.compose((duplicate, first_constraint))
    assert first == second
    assert first.status == EffectAlgebraStatus.COMPOSED
    assert len(first.effects) == 1
    assert first.effects[0].source_constraint_ids == (
        "constraint:a",
        "constraint:b",
    )


def test_effect_algebra_uses_one_canonical_order() -> None:
    summary = _manual_constraint(
        constraint_id="constraint:summary",
        effect_id="effect:summary",
        effect=ConstraintEffect.FORCE_SUMMARY,
    )
    block = _manual_constraint(
        constraint_id="constraint:block",
        effect_id="effect:block",
        effect=ConstraintEffect.BLOCK_EXECUTION,
    )
    redact = _manual_constraint(
        constraint_id="constraint:redact",
        effect_id="effect:redact",
        effect=ConstraintEffect.ADD_REDACTION,
    )
    result = ConstraintEffectAlgebra.compose((block, summary, redact))
    assert tuple(item.effect for item in result.effects) == (
        ConstraintEffect.ADD_REDACTION,
        ConstraintEffect.FORCE_SUMMARY,
        ConstraintEffect.BLOCK_EXECUTION,
    )


def test_target_restrictions_accumulate_without_erasing_prior_restrictions() -> None:
    first = _manual_constraint(
        constraint_id="constraint:target-a",
        effect_id="effect:target-a",
        effect=ConstraintEffect.RESTRICT_TARGET,
        parameters=(("allowed_target", "target:a"),),
    )
    second = _manual_constraint(
        constraint_id="constraint:target-b",
        effect_id="effect:target-b",
        effect=ConstraintEffect.RESTRICT_TARGET,
        parameters=(("allowed_target", "target:b"),),
    )
    one = ConstraintEffectAlgebra.compose((first,))
    two = ConstraintEffectAlgebra.compose((first, second))
    one_restrictions = {
        item.canonical_key
        for item in one.effects
        if item.effect == ConstraintEffect.RESTRICT_TARGET
    }
    two_restrictions = {
        item.canonical_key
        for item in two.effects
        if item.effect == ConstraintEffect.RESTRICT_TARGET
    }
    assert one_restrictions < two_restrictions


def test_conflicting_duration_limits_are_not_resolved_by_order() -> None:
    short = _manual_constraint(
        constraint_id="constraint:short",
        effect_id="effect:short",
        effect=ConstraintEffect.LIMIT_DURATION,
        parameters=(("duration", "1h"),),
    )
    long = _manual_constraint(
        constraint_id="constraint:long",
        effect_id="effect:long",
        effect=ConstraintEffect.LIMIT_DURATION,
        parameters=(("duration", "2h"),),
    )
    result = ConstraintEffectAlgebra.compose((long, short))
    assert result.status == EffectAlgebraStatus.CONFLICTED
    assert result.conflicts[0].conflict_id == "conflicting_duration_limits"
    with pytest.raises(ValueError, match="unresolved effect algebra"):
        result.to_plan_requirement_deltas()


def test_block_effect_is_monotonic_and_allow_raw_is_not_in_the_algebra() -> None:
    blocked = _manual_constraint(
        constraint_id="constraint:block",
        effect_id="effect:block",
        effect=ConstraintEffect.BLOCK_EXECUTION,
    )
    result = ConstraintEffectAlgebra.compose((blocked,))
    assert result.status == EffectAlgebraStatus.COMPOSED
    assert result.blocks_execution is True
    with pytest.raises(ValueError, match="unsupported constraint effect"):
        _manual_constraint(
            constraint_id="constraint:allow",
            effect_id="effect:allow",
            effect=ConstraintEffect.ALLOW_RAW,
        )


def test_effect_algebra_rejects_cross_candidate_or_cross_scope_composition() -> None:
    first = _manual_constraint(
        constraint_id="constraint:first",
        effect_id="effect:first",
        effect=ConstraintEffect.ADD_CONFIRMATION,
    )
    other = _manual_constraint(
        constraint_id="constraint:other",
        effect_id="effect:other",
        effect=ConstraintEffect.ADD_CONFIRMATION,
    )
    other = CandidateConstraint(
        constraint_id=other.constraint_id,
        constraint_type=other.constraint_type,
        source_fact_ids=other.source_fact_ids,
        activation_scope=other.activation_scope,
        applied_candidate_id="candidate:other",
        effects=other.effects,
        reason_code_ids=other.reason_code_ids,
        state=other.state,
    )
    with pytest.raises(ValueError, match="different candidates or scopes"):
        ConstraintEffectAlgebra.compose((first, other))


def test_active_constraint_has_complete_trace_links() -> None:
    bundle = _activate(
        RulePackKey(Domain.PAYMENT, Operation.EXECUTE),
        [{"id": "policy", "type": "payment_policy", "value": "active"}],
        role=TargetRole.MERCHANT,
        locality=TargetLocality.DOMAIN,
    )
    constraint = next(
        item
        for item in bundle.active_constraints
        if item.constraint_id == "CONSTRAINT-PAYMENT-POLICY"
    )
    assert constraint.source_fact_ids == ("record:policy",)
    assert constraint.activation_scope.domain == Domain.PAYMENT
    assert constraint.applied_candidate_id == "candidate:one"
    assert constraint.effect_ids
    assert constraint.reason_code_ids == (ReasonCode.PAYMENT_POLICY_REVIEW,)


def test_constraint_effects_feed_the_same_final_plan_requirements_contract() -> None:
    key = RulePackKey(Domain.CONTENT, Operation.SHARE)
    resolution = RULEPACK_REGISTRY.resolve_exact(key)
    assert resolution.rulepack is not None
    bundle = _activate(
        key,
        [
            {
                "id": "policy",
                "type": "external_share_policy",
                "value": "raw_quote_forbidden",
            }
        ],
        role=TargetRole.DISPATCH_DESTINATION,
        locality=TargetLocality.EXTERNAL,
    )
    algebra = ConstraintEffectAlgebra.compose(bundle.constraints)
    requirements = FinalPlanRequirementsBuilder.build(
        candidate_id="candidate:one",
        resolution=resolution,
        deltas=algebra.to_plan_requirement_deltas(),
    )
    assert requirements.semantic_terminal == PlanStepType.DISPATCH
    assert CapabilityType.REDACT in requirements.platform_required_capabilities
    assert requirements.applied_effect_ids == tuple(
        item.effect_id for item in algebra.effects
    )


def test_constraint_module_does_not_parse_language_or_choose_control() -> None:
    source = (PROJECT_ROOT / "core" / "constraints.py").read_text(encoding="utf-8")
    for prohibited in (
        "ExecutionDisposition",
        "CandidateDispositionPolicy",
        "prompt",
        "visible_history",
        "default_dispatch",
        "re.compile",
    ):
        assert prohibited not in source
    activator_source = inspect.getsource(PairConstraintActivator)
    assert "TaskView" not in activator_source
    assert "raw_record" not in activator_source


def test_constraint_facts_and_effects_have_single_declared_owners() -> None:
    ownership = {item.field: item for item in OWNERSHIP_REGISTRY}
    assert ownership["active_constraints"].producer == "ConstraintActivator"
    assert ownership["active_constraints"].final_owner == "FinalDecision"
    assert ownership["constraint_effects"].producer == "BlueprintCompiler"
    assert ownership["constraint_effects"].final_owner == "EffectiveBlueprint"


def test_step7_registry_is_not_imported_by_current_production_path() -> None:
    for relative in ("core/decision.py", "harness.py", "rules/plan.py"):
        source = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "from .constraints" not in source
        assert "core.constraints" not in source
