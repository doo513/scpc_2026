# Ontology and Ownership

Validated ontology enum types: `18`

| Field | Producer | Final owner | Validator |
| --- | --- | --- | --- |
| domain | IntentResolver | SelectionResolution | ConsistencyValidator |
| operation | IntentResolver | SelectionResolution | ConsistencyValidator |
| focal_identity | FocalResolver | FocalDecision | ConsistencyValidator |
| target_identity | ActionTargetPairBuilder | SelectionResolution | ConsistencyValidator |
| target_role | ActionTargetPairBuilder | ActionTargetCandidate | ConsistencyValidator |
| target_locality | ActionTargetPairBuilder | ActionTargetCandidate | ConsistencyValidator |
| required_information | CandidateInformationResolver | CandidateInformationAssessment | ConsistencyValidator |
| active_constraints | PairConstraintActivator | ConstraintActivationBundle | ConsistencyValidator |
| constraint_effects | ConstraintEffectAlgebra | EffectAlgebraResult | ConsistencyValidator |
| safeguards | BlueprintCompiler | EffectiveBlueprint | ConsistencyValidator |
| required_capabilities | FinalPlanRequirements | CapabilityAssessment | ConsistencyValidator |
| candidate_state | CandidateDispositionPolicy | CandidateDispositionPolicy | ConsistencyValidator |
| fallback_origin | FallbackEdgeRegistry | AuthorizedFallbackSolver | ConsistencyValidator |
| disclosure_mode | FinalDecisionBuilder | FinalDecision | ConsistencyValidator |
| blueprint_id | PlanBlueprintRegistry | BasePlanBlueprint | ConsistencyValidator |
| reason_codes | FinalDecisionBuilder | FinalDecision | ConsistencyValidator |
| final_plan_requirements | PlanRequirementComposer | FinalPlanRequirements | ConsistencyValidator |
