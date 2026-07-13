from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticOwnership:
    field: str
    producer: str
    final_owner: str
    validator: str


OWNERSHIP_REGISTRY = (
    SemanticOwnership("domain", "IntentResolver", "SelectionResolution", "ConsistencyValidator"),
    SemanticOwnership("operation", "IntentResolver", "SelectionResolution", "ConsistencyValidator"),
    SemanticOwnership("focal_identity", "FocalResolver", "FocalDecision", "ConsistencyValidator"),
    SemanticOwnership("target_identity", "ActionTargetPairBuilder", "SelectionResolution", "ConsistencyValidator"),
    SemanticOwnership("target_role", "ActionTargetPairBuilder", "ActionTargetCandidate", "ConsistencyValidator"),
    SemanticOwnership("target_locality", "ActionTargetPairBuilder", "ActionTargetCandidate", "ConsistencyValidator"),
    SemanticOwnership("required_information", "CandidateInformationResolver", "CandidateInformationAssessment", "ConsistencyValidator"),
    SemanticOwnership("active_constraints", "PairConstraintActivator", "ConstraintActivationBundle", "ConsistencyValidator"),
    SemanticOwnership("constraint_effects", "ConstraintEffectAlgebra", "EffectAlgebraResult", "ConsistencyValidator"),
    SemanticOwnership("safeguards", "BlueprintCompiler", "EffectiveBlueprint", "ConsistencyValidator"),
    SemanticOwnership("required_capabilities", "FinalPlanRequirements", "CapabilityAssessment", "ConsistencyValidator"),
    SemanticOwnership("candidate_state", "CandidateDispositionPolicy", "CandidateDispositionPolicy", "ConsistencyValidator"),
    SemanticOwnership("fallback_origin", "FallbackEdgeRegistry", "AuthorizedFallbackSolver", "ConsistencyValidator"),
    SemanticOwnership("disclosure_mode", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("blueprint_id", "PlanBlueprintRegistry", "BasePlanBlueprint", "ConsistencyValidator"),
    SemanticOwnership("reason_codes", "FinalDecisionBuilder", "FinalDecision", "ConsistencyValidator"),
    SemanticOwnership("final_plan_requirements", "PlanRequirementComposer", "FinalPlanRequirements", "ConsistencyValidator"),
)


REQUIRED_OWNERSHIP_FIELDS = frozenset(
    {
        "domain",
        "operation",
        "focal_identity",
        "target_identity",
        "target_role",
        "target_locality",
        "required_information",
        "active_constraints",
        "constraint_effects",
        "safeguards",
        "required_capabilities",
        "candidate_state",
        "fallback_origin",
        "disclosure_mode",
        "blueprint_id",
        "reason_codes",
        "final_plan_requirements",
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
    prohibited_final_owners = {"ScopeCompiler", "PolicyCompiler", "PlanCompiler"}
    offenders = [
        item.field
        for item in OWNERSHIP_REGISTRY
        if item.final_owner in prohibited_final_owners
    ]
    if offenders:
        raise ValueError(f"compiler owns semantic fields: {offenders}")
