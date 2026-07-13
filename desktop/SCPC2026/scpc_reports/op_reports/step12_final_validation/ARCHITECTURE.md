# Architecture

```text
Production (unchanged)
TaskView -> legacy StateAssembler/DecisionEngine -> legacy FinalDecision
         -> legacy pure compilers -> answer -> legacy commit -> ConsistencyValidator

Shadow verified slices
Typed Facts + Deterministic Parser -> Evidence proposals
-> typed candidates -> exact RulePack -> BasePlanBlueprint
-> role/information -> pair constraint/effect algebra
-> FinalPlanRequirements -> full capability -> CandidateEvaluator
-> AuthorizedFallback -> SubDecisionIR/DecisionBundle lock
-> Projection DTO -> Pure Compiler -> ShadowConsistencyValidator
-> SpeculativeSessionOverlay -> commit eligibility -> atomic shadow store
```

The shadow slices are not wired as one production pipeline. No production switch was performed.
