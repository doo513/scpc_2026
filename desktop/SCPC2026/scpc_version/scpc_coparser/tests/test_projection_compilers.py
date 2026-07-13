from __future__ import annotations

from dataclasses import FrozenInstanceError
import inspect
from pathlib import Path

import pytest

from core.decision_ir import (
    AggregateOutputStatus,
    DecisionProjectionSet,
    PlanProjection,
    PlanProjectionStep,
    PolicyProjection,
    ScopeProjection,
)
from core.ontology import DisclosureMode, PlanStepType, ReasonCode
from core.projection_compilers import (
    PlanCompiler,
    PolicyCompiler,
    ProjectionCompiler,
    ProjectionCompilerConfig,
    ScopeCompiler,
    validate_projection_compiler_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = ProjectionCompilerConfig(max_plan_events=18)


def _projections(
    *,
    decision_ids: tuple[str, ...] = ("decision:one",),
    mismatched_lineage: bool = False,
) -> DecisionProjectionSet:
    scopes = tuple(
        ScopeProjection(
            decision_id,
            DisclosureMode.REDACTED,
            ("status",),
            ("secret",),
            True,
            ("effect:redact",),
            f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    policies = tuple(
        PolicyProjection(
            decision_id,
            ("risk:disclosure",),
            (),
            True,
            (ReasonCode.EXECUTABLE,),
            ("constraint:share",),
            f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    plans = tuple(
        PlanProjection(
            decision_id,
            (
                PlanProjectionStep(
                    f"projection:{decision_id}:read",
                    "requirement:read",
                    PlanStepType.READ,
                    "object:one",
                    (("opaque", "preserved"),),
                    (ReasonCode.EXECUTABLE,),
                ),
                PlanProjectionStep(
                    f"projection:{decision_id}:dispatch",
                    "requirement:dispatch",
                    PlanStepType.DISPATCH,
                    "recipient:one",
                    (("scope", "redacted"),),
                    (ReasonCode.EXECUTABLE,),
                    semantic_terminal=True,
                ),
            ),
            "lock:mismatch" if mismatched_lineage else f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    return DecisionProjectionSet(
        "bundle:test",
        (
            AggregateOutputStatus.SINGLE
            if len(decision_ids) == 1
            else AggregateOutputStatus.MULTIPLE_UNRESOLVED
        ),
        scopes,
        policies,
        plans,
        "bundle-lock:test",
    )


def test_scope_compiler_is_an_exact_projection() -> None:
    projection = _projections().scopes[0]
    assert ScopeCompiler.compile(projection) == {
        "mode": "redacted",
        "allowed_fields": ["status"],
        "excluded_fields": ["secret"],
        "requires_user_confirmation": True,
    }


def test_policy_compiler_is_an_exact_projection() -> None:
    projection = _projections().policies[0]
    assert PolicyCompiler.compile(projection) == {
        "risk_flags": ["risk:disclosure"],
        "violations": [],
        "requires_confirmation": True,
    }


def test_plan_compiler_preserves_step_order_target_and_opaque_args() -> None:
    projection = _projections().plans[0]
    assert PlanCompiler.compile(projection, CONFIG) == [
        {
            "verb": "read",
            "target": "object:one",
            "args": {"opaque": "preserved"},
        },
        {
            "verb": "dispatch",
            "target": "recipient:one",
            "args": {"scope": "redacted"},
        },
    ]


def test_same_projection_always_produces_same_fresh_output() -> None:
    projections = _projections()
    first = ProjectionCompiler.compile(projections, CONFIG)
    expected = ProjectionCompiler.compile(projections, CONFIG)
    first["decision:one"]["content_scope"]["allowed_fields"].append("mutation")
    assert ProjectionCompiler.compile(projections, CONFIG) == expected


def test_unrelated_raw_data_cannot_affect_compilation() -> None:
    projections = _projections()
    raw_data = {"prompt": "first", "records": ["one"]}
    first = ProjectionCompiler.compile(projections, CONFIG)
    raw_data["prompt"] = "changed"
    raw_data["records"].append("two")
    assert ProjectionCompiler.compile(projections, CONFIG) == first


def test_compiler_invocation_order_does_not_change_outputs() -> None:
    projections = _projections()
    scope = projections.scopes[0]
    policy = projections.policies[0]
    plan = projections.plans[0]
    forward = {
        "scope": ScopeCompiler.compile(scope),
        "policy": PolicyCompiler.compile(policy),
        "plan": PlanCompiler.compile(plan, CONFIG),
    }
    reverse: dict[str, object] = {}
    reverse["plan"] = PlanCompiler.compile(plan, CONFIG)
    reverse["policy"] = PolicyCompiler.compile(policy)
    reverse["scope"] = ScopeCompiler.compile(scope)
    assert forward == reverse


def test_projection_lineage_mismatch_is_rejected_before_join() -> None:
    with pytest.raises(ValueError, match="one decision lock"):
        ProjectionCompiler.compile(_projections(mismatched_lineage=True), CONFIG)


def test_multi_decision_projection_is_not_aggregated_into_one_control() -> None:
    compiled = ProjectionCompiler.compile(
        _projections(decision_ids=("decision:b", "decision:a")),
        CONFIG,
    )
    assert tuple(compiled) == ("decision:a", "decision:b")
    assert all("control" not in fields for fields in compiled.values())


def test_plan_event_limit_is_explicit_immutable_config() -> None:
    projection = _projections().plans[0]
    repeated = PlanProjection(
        projection.decision_id,
        tuple(
            PlanProjectionStep(
                f"projection:{index}",
                f"requirement:{index}",
                PlanStepType.READ,
                "object:one",
                (),
                (ReasonCode.EXECUTABLE,),
            )
            for index in range(19)
        ),
        projection.source_lock_digest,
    )
    with pytest.raises(ValueError, match="exceeds configured"):
        PlanCompiler.compile(repeated, CONFIG)
    with pytest.raises(FrozenInstanceError):
        CONFIG.max_plan_events = 19  # type: ignore[misc]
    with pytest.raises(ValueError, match="official schema"):
        ProjectionCompilerConfig(max_plan_events=19)


def test_compilers_are_shadow_only_and_have_no_semantic_dependencies() -> None:
    validate_projection_compiler_contract()
    source = (PROJECT_ROOT / "core" / "projection_compilers.py").read_text(
        encoding="utf-8"
    )
    for prohibited in (
        "TaskView",
        "EvidenceGraph",
        "CandidateSet",
        "DecisionMatrix",
        "visible_history",
        "personal_memory",
        "CandidateEvaluator",
        "RULEPACK_REGISTRY",
        "available_actions",
        "default dispatch",
    ):
        assert prohibited not in source
    for compiler in (ScopeCompiler, PolicyCompiler, PlanCompiler):
        compiler_source = inspect.getsource(compiler)
        assert "operation" not in compiler_source
        assert "control" not in compiler_source
    for relative in ("harness.py", "rules/plan.py", "rules/scope_policy.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "projection_compilers" not in production
