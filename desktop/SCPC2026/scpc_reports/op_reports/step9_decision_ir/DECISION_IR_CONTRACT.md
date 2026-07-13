# Step 9 Decision IR Contract

## Locked meaning

- CandidateEvaluator 결과, exact RulePack lineage, target binding, disposition, disclosure, policy, safeguards, capability snapshot, plan projection을 하나의 immutable SubDecisionIR로 잠근다.
- execution target과 response target은 별도 binding이며 자동 복사하지 않는다.
- plan projection은 Decision Lock 전에 명시하고 FinalPlanRequirements의 순서와 verb를 바꾸지 못한다.
- semantic terminal 표지는 FinalPlanRequirements에서 손실 없이 복사하며 ask/hold plan에는 terminal을 만들지 않는다.
- ask/hold의 non-execution plan은 공식 미확정이므로 ASSUMPTION-DISPOSITION-PLAN-001을 남긴다.

## Bundle

- 단일 operation도 1개 SubDecision을 가진 bundle로 표현한다.
- 복수 operation은 각 disposition과 dependency DAG를 보존한다.
- 공식 aggregate 규칙이 없으므로 복수 bundle에 단일 control을 만들지 않고 MULTIPLE_UNRESOLVED로 둔다.

## Projection boundary

- ScopeProjection, PolicyProjection, PlanProjection은 lock digest를 가진 순수 DTO다.
- projection 계층은 prompt, raw record, EvidenceGraph, RulePack, CandidateEvaluator를 재조회하지 않는다.
- Step 9 경로는 shadow-only이며 production output에는 연결하지 않는다.
