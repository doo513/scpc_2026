from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .decision_ir import (
    DecisionProjectionSet,
    PlanProjection,
    PolicyProjection,
    ScopeProjection,
)


@dataclass(frozen=True)
class ProjectionCompilerConfig:
    max_plan_events: int

    def __post_init__(self) -> None:
        if not 1 <= self.max_plan_events <= 18:
            raise ValueError("plan event limit must satisfy the official schema")


class ScopeCompiler:
    production_active = True

    @staticmethod
    def compile(projection: ScopeProjection) -> dict[str, Any]:
        if not projection.decision_id or not projection.source_lock_digest:
            raise ValueError("scope projection lacks decision lock lineage")
        return {
            "mode": projection.mode.value,
            "allowed_fields": list(projection.allowed_fields),
            "excluded_fields": list(projection.excluded_fields),
            "requires_user_confirmation": projection.requires_user_confirmation,
        }


class PolicyCompiler:
    production_active = True

    @staticmethod
    def compile(projection: PolicyProjection) -> dict[str, Any]:
        if not projection.decision_id or not projection.source_lock_digest:
            raise ValueError("policy projection lacks decision lock lineage")
        return {
            "risk_flags": list(projection.risk_flags),
            "violations": list(projection.violations),
            "requires_confirmation": projection.requires_confirmation,
        }


class PlanCompiler:
    production_active = True

    @staticmethod
    def compile(
        projection: PlanProjection,
        config: ProjectionCompilerConfig,
    ) -> list[dict[str, Any]]:
        if not projection.decision_id or not projection.source_lock_digest:
            raise ValueError("plan projection lacks decision lock lineage")
        if len(projection.steps) > config.max_plan_events:
            raise ValueError("plan event count exceeds configured schema maximum")
        return [
            {
                "verb": step.verb.value,
                "target": step.target,
                "args": dict(step.args),
            }
            for step in projection.steps
        ]


class ProjectionCompiler:
    """Structurally joins independent compiler outputs by decision lock."""

    production_active = True

    @classmethod
    def compile(
        cls,
        projections: DecisionProjectionSet,
        config: ProjectionCompilerConfig,
    ) -> dict[str, dict[str, Any]]:
        scopes = {item.decision_id: item for item in projections.scopes}
        policies = {item.decision_id: item for item in projections.policies}
        plans = {item.decision_id: item for item in projections.plans}
        output: dict[str, dict[str, Any]] = {}
        for decision_id in sorted(scopes):
            source_digests = {
                scopes[decision_id].source_lock_digest,
                policies[decision_id].source_lock_digest,
                plans[decision_id].source_lock_digest,
            }
            if len(source_digests) != 1 or not next(iter(source_digests)):
                raise ValueError("projection fields do not share one decision lock")
            output[decision_id] = {
                "content_scope": ScopeCompiler.compile(scopes[decision_id]),
                "policy": PolicyCompiler.compile(policies[decision_id]),
                "plan_events": PlanCompiler.compile(plans[decision_id], config),
            }
        return output


def validate_projection_compiler_contract() -> None:
    if not all(
        compiler.production_active
        for compiler in (
            ScopeCompiler,
            PolicyCompiler,
            PlanCompiler,
            ProjectionCompiler,
        )
    ):
        raise ValueError("authoritative projection compilers are not production-active")
