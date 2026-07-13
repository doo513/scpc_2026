from __future__ import annotations

from dataclasses import replace
import copy
from pathlib import Path

from core.constraints import (
    CandidateConstraint,
    ConstraintActivationScope,
    ConstraintActivationState,
)
from core.decision_ir import (
    DecisionBundleBuilder,
    DecisionProjectionBuilder,
    DisclosureDecision,
    FallbackOrigin,
    PolicyDecision,
    SubDecisionIRBuilder,
)
from core.fallbacks import FallbackEdgeRegistry
from core.ontology import ConstraintType, DisclosureMode, Domain, Operation, ReasonCode
from core.projection_compilers import ProjectionCompiler, ProjectionCompilerConfig
from core.shadow_validation import (
    ShadowConsistencyValidator,
    ShadowValidationCode,
    validate_shadow_validation_contract,
)
from core.rulepacks import RulePackKey
from tests.test_candidate_evaluation import (
    _candidate as _axis_candidate,
    _context as _axis_context,
    _evaluate as _axis_evaluate,
)
from tests.test_decision_ir import (
    _candidate,
    _evaluation,
    _lock,
    _plan_for,
    _response,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = ProjectionCompilerConfig(max_plan_events=18)


def _artifacts(decision):
    bundle = DecisionBundleBuilder.lock(
        bundle_id="bundle:validation",
        primary_focal_id=decision.focal_id,
        sub_decisions=(decision,),
    )
    projections = DecisionProjectionBuilder.build(bundle)
    compiled = ProjectionCompiler.compile(projections, CONFIG)
    return bundle, projections, compiled


def _validate(decision, compiled_override=None):
    bundle, projections, compiled = _artifacts(decision)
    return ShadowConsistencyValidator.validate(
        bundle=bundle,
        projections=projections,
        compiled=compiled if compiled_override is None else compiled_override,
        compiler_config=CONFIG,
        fallback_registry=FallbackEdgeRegistry(),
    )


def test_valid_locked_path_passes_with_target_assumption_diagnostic() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="validation:valid"))
    report = _validate(_lock(evaluation, snapshot))
    assert report.hard_valid
    assert report.error_codes == ()
    assert ShadowValidationCode.TARGET_MAPPING_UNRESOLVED in report.diagnostic_codes


def test_real_redaction_constraint_has_complete_scope_and_transform_lineage() -> None:
    evaluation = _axis_evaluate(
        _axis_candidate(
            RulePackKey(Domain.CONTENT, Operation.SHARE),
            clause="validation:redaction",
        ),
        _axis_context(
            records=[
                {
                    "id": "policy",
                    "type": "external_share_policy",
                    "value": "raw_quote_forbidden",
                }
            ]
        ),
    )
    activation = evaluation.assessment.constraint_activation
    algebra = evaluation.assessment.effect_algebra
    assert activation is not None and algebra is not None
    effect_ids = tuple(sorted(item.effect_id for item in algebra.effects))
    constraint_ids = tuple(
        sorted(item.constraint_id for item in activation.active_constraints)
    )
    decision = SubDecisionIRBuilder.lock(
        evaluation=evaluation,
        response_target_binding=_response(),
        disclosure=DisclosureDecision(
            DisclosureMode.REDACTED,
            ("content",),
            ("raw_quote",),
            False,
            effect_ids,
        ),
        policy=PolicyDecision(
            ("external_disclosure",),
            (),
            False,
            constraint_ids,
        ),
        plan_decision=_plan_for(evaluation),
        capability_snapshot=_axis_context().capability_snapshot,
    )
    report = _validate(decision)
    assert report.hard_valid


def test_compiled_output_mutation_is_a_hard_error() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="validation:compiled"))
    decision = _lock(evaluation, snapshot)
    bundle, projections, compiled = _artifacts(decision)
    mutated = copy.deepcopy(compiled)
    mutated[decision.decision_id]["plan_events"][0]["target"] = "mutated"
    report = ShadowConsistencyValidator.validate(
        bundle=bundle,
        projections=projections,
        compiled=mutated,
        compiler_config=CONFIG,
        fallback_registry=FallbackEdgeRegistry(),
    )
    assert not report.hard_valid
    assert ShadowValidationCode.COMPILED_OUTPUT_MISMATCH in report.error_codes


def test_active_constraint_without_policy_or_safeguard_lineage_is_rejected() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="validation:constraint"))
    decision = _lock(evaluation, snapshot)
    scope = ConstraintActivationScope(
        decision.domain,
        decision.operation,
        decision.execution_target,
        decision.execution_target_role,
        decision.execution_target_locality,
    )
    uncovered = CandidateConstraint(
        "constraint:uncovered",
        ConstraintType.UNKNOWN,
        ("record:uncovered",),
        scope,
        decision.selected_candidate_id,
        (),
        (ReasonCode.UNKNOWN,),
        ConstraintActivationState.ACTIVE,
    )
    unlocked = replace(
        decision,
        active_constraints=(uncovered,),
        lock_digest="",
    )
    relocked = replace(unlocked, lock_digest=unlocked.compute_lock_digest())
    report = _validate(relocked)
    assert not report.hard_valid
    assert ShadowValidationCode.CONSTRAINT_LINEAGE_MISSING in report.error_codes


def test_fallback_origin_must_resolve_to_the_supplied_registry() -> None:
    evaluation, snapshot = _evaluation(_candidate(clause="validation:fallback"))
    decision = _lock(evaluation, snapshot)
    origin = FallbackOrigin(
        "edge:not-registered",
        "candidate:source",
        decision.selected_candidate_id,
        ("evidence:authorization",),
    )
    unlocked = replace(decision, fallback_origin=origin, lock_digest="")
    relocked = replace(unlocked, lock_digest=unlocked.compute_lock_digest())
    report = _validate(relocked)
    assert not report.hard_valid
    assert ShadowValidationCode.FALLBACK_EDGE_MISSING in report.error_codes


def test_shadow_validator_has_no_raw_or_language_dependency() -> None:
    validate_shadow_validation_contract()
    source = (PROJECT_ROOT / "core" / "shadow_validation.py").read_text(
        encoding="utf-8"
    )
    for prohibited in (
        "TaskView",
        "EvidenceGraph",
        "visible_history",
        "personal_memory",
        "SurfaceParser",
        "LanguageRuleRegistry",
        "re.compile",
    ):
        assert prohibited not in source
    for relative in ("harness.py", "run_submission.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "shadow_validation" not in production
