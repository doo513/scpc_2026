from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .decision_ir import (
    AggregateOutputStatus,
    DecisionProjectionSet,
    PlanProjection,
    PlanProjectionStep,
    PolicyProjection,
    ScopeProjection,
)
from .ontology import DisclosureMode, PlanStepType, ReasonCode
from .projection_compilers import ProjectionCompiler, ProjectionCompilerConfig


@dataclass(frozen=True)
class CompiledDecisionProjection:
    decision_id: str
    bundle_id: str
    lock_digest: str
    fields: dict[str, Any]


class FinalDecisionProjectionBuilder:
    """Locks FinalDecision fields into raw-free projection DTOs.

    This is the migration boundary while the legacy semantic selector remains
    authoritative. It does not receive TaskView, prompt, records, or session.
    """

    production_active = True

    @staticmethod
    def _digest(final_decision: Any) -> str:
        payload = json.dumps(
            final_decision.to_trace(),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("ascii")).hexdigest()

    @classmethod
    def build(cls, final_decision: Any) -> DecisionProjectionSet:
        digest = cls._digest(final_decision)
        candidate_id = str(final_decision.selected_pair_id or final_decision.focal_id)
        decision_id = f"decision:{candidate_id}"
        bundle_id = f"bundle:{digest[:20]}"
        plan_steps = tuple(final_decision.plan_steps)
        terminal_verb = str(final_decision.effective_blueprint.base.terminal_verb or "")
        executing = final_decision.control in {"proceed", "amend"}
        projected_steps = tuple(
            PlanProjectionStep(
                projection_step_id=f"{decision_id}:step:{index}",
                requirement_step_id=f"legacy-final-decision:{index}",
                verb=PlanStepType.parse(step.verb),
                target=step.target,
                args=tuple(step.args),
                reason_codes=(ReasonCode.UNKNOWN,),
                semantic_terminal=executing and step.verb == terminal_verb,
            )
            for index, step in enumerate(plan_steps)
        )
        scope = ScopeProjection(
            decision_id,
            DisclosureMode.parse(final_decision.disclosure_mode),
            tuple(final_decision.allowed_fields),
            tuple(final_decision.excluded_fields),
            bool(final_decision.scope_requires_user_confirmation),
            tuple(
                sorted(
                    {
                        source_id
                        for item in final_decision.exclusion_provenance
                        for source_id in (
                            item.provenance_id,
                            *item.source_ids,
                        )
                    }
                )
            ),
            digest,
        )
        policy = PolicyProjection(
            decision_id,
            tuple(final_decision.risk_flags),
            tuple(final_decision.violations),
            bool(final_decision.policy_requires_confirmation),
            (ReasonCode.UNKNOWN,),
            (),
            digest,
        )
        plan = PlanProjection(decision_id, projected_steps, digest)
        return DecisionProjectionSet(
            bundle_id,
            AggregateOutputStatus.SINGLE,
            (scope,),
            (policy,),
            (plan,),
            digest,
        )


class ProductionProjectionPipeline:
    production_active = True
    config = ProjectionCompilerConfig(max_plan_events=18)

    @classmethod
    def compile(cls, final_decision: Any) -> CompiledDecisionProjection:
        projections = FinalDecisionProjectionBuilder.build(final_decision)
        compiled = ProjectionCompiler.compile(projections, cls.config)
        decision_id = projections.scopes[0].decision_id
        return CompiledDecisionProjection(
            decision_id,
            projections.bundle_id,
            projections.source_bundle_lock_digest,
            compiled[decision_id],
        )


def validate_production_projection_contract() -> None:
    if not FinalDecisionProjectionBuilder.production_active:
        raise ValueError("FinalDecision projection boundary is not production-active")
    if not ProductionProjectionPipeline.production_active:
        raise ValueError("production projection pipeline is inactive")
