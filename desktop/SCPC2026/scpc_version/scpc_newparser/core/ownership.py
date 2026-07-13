from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticOwnership:
    field: str
    producer: str
    final_owner: str
    validator: str


OWNERSHIP_REGISTRY = (
    SemanticOwnership("domain", "IntentResolver", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("operation", "IntentResolver", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("focal_identity", "FocalResolver", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("execution_target", "ActionTargetPairBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("response_target", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("target_role", "ActionTargetPairBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("target_locality", "ActionTargetPairBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("required_information", "InformationResolver", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("active_constraints", "ConstraintActivator", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("constraint_effects", "BlueprintCompiler", "EffectiveBlueprint", "ConsistencyValidator"),
    SemanticOwnership("safeguards", "BlueprintCompiler", "EffectiveBlueprint", "ConsistencyValidator"),
    SemanticOwnership("required_capabilities", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("candidate_state", "CandidateEvaluator", "CandidateEvaluation", "ConsistencyValidator"),
    SemanticOwnership("execution_disposition", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("fallback_origin", "AuthorizedFallbackSolver", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("disclosure_mode", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("blueprint_id", "BlueprintRegistry", "EffectiveBlueprint", "ConsistencyValidator"),
    SemanticOwnership("reason_codes", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("public_policy_reason", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("final_plan_requirements", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("official_plan_projection", "FinalDecisionProjectionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("session_commit", "AtomicSessionCommitter", "AtomicSessionCommitter", "ConsistencyValidator"),
)


REQUIRED_OWNERSHIP_FIELDS = frozenset(
    {
        "domain",
        "operation",
        "focal_identity",
        "execution_target",
        "response_target",
        "target_role",
        "target_locality",
        "required_information",
        "active_constraints",
        "constraint_effects",
        "safeguards",
        "required_capabilities",
        "candidate_state",
        "execution_disposition",
        "fallback_origin",
        "disclosure_mode",
        "blueprint_id",
        "reason_codes",
        "public_policy_reason",
        "final_plan_requirements",
        "official_plan_projection",
        "session_commit",
    }
)


def validate_ownership_registry() -> None:
    fields = [item.field for item in OWNERSHIP_REGISTRY]
    if len(fields) != len(set(fields)):
        raise ValueError("semantic ownership registry contains duplicate fields")
    if set(fields) != REQUIRED_OWNERSHIP_FIELDS:
        missing = REQUIRED_OWNERSHIP_FIELDS - set(fields)
        extra = set(fields) - REQUIRED_OWNERSHIP_FIELDS
        raise ValueError(f"ownership fields mismatch missing={missing} extra={extra}")
    prohibited_final_owners = {
        "ScopeCompiler",
        "PolicyCompiler",
        "PlanCompiler",
        "ProjectionCompiler",
    }
    offenders = [
        item.field
        for item in OWNERSHIP_REGISTRY
        if item.final_owner in prohibited_final_owners
    ]
    if offenders:
        raise ValueError(f"compiler owns semantic fields: {offenders}")
