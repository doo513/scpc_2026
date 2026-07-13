# Step 8 Candidate Evaluation·Fallback 계약

## 후보 identity

CandidateSemanticKey와 source clause, sub-operation, evidence group을 포함한 CandidateIdentity를 분리한다. 동일 semantic key의 반복 후보는 보존하며 full identity만 중복 금지한다. CandidateSetBuilder는 이미 source-bound인 pair seed만 받으며 Cartesian product API를 제공하지 않는다.

## 평가 잠금

RulePack, BasePlanBlueprint, role, base information, global/pair constraint, deferred conditional information, effect algebra, FinalPlanRequirements, full capability 순서로 axis를 완성한다. CandidateEvaluator는 이 결과만 종합하며 이전 registry를 조회하지 않는다.

`CONSTRAINT_PRESENT` conditional slot은 base information precheck 후 constraint activation 결과로만 확정한다. 앞서 확정한 binding은 재해석하지 않는다.

## 상태와 rank

role-incompatible 후보는 reject한다. missing, block, conflict가 동시에 발생해 공식 precedence가 없으면 `ASSUMPTION-DISPOSITION-001`과 함께 unresolved precedence로 보존한다. rank는 VIABLE·AMENDABLE 후보 사이에서만 tie-breaker로 사용하며 SLM origin 보너스가 없다.

## Fallback

현재 사용자 명시 대안은 CURRENT_DIRECT authority Evidence만 authorization으로 인정한다. destination은 CandidateEvaluationEngine을 다시 통과한다. edge가 없으면 낮은 rank 후보를 자동 선택하지 않는다. 현재 구현은 1-hop만 지원하고 cycle·self-loop를 거부한다.

Step 8 경로는 shadow-only이며 production decision 교체는 아직 수행하지 않았다.
