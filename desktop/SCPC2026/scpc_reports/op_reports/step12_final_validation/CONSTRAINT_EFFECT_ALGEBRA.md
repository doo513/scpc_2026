# Step 7 Constraint Effect Algebra 계약

## Fact와 Activation 분리

GlobalConstraintRegistry는 TypedRecordFact를 canonical GlobalConstraintFact로 정규화한다. record presence 자체는 control이 아니며, exact RulePack의 PairConstraintSpec과 target locality가 일치할 때만 후보별 effect가 활성화된다.

## 상태 보존

ACTIVE, INACTIVE, CONFLICTED, UNRESOLVED를 분리한다. 서로 다른 값의 duplicate record에는 배열 순서나 임의 최신값을 적용하지 않는다.

## Effect Algebra

동일 `(effect, scope, parameters)`는 멱등 병합하면서 모든 source constraint와 fact ID를 보존한다. canonical 순서는 redact, summarize, confirmation, duration, target restriction, block이다. 서로 다른 duration limit처럼 공식 우선순위가 없는 충돌은 CONFLICTED다. BLOCK_EXECUTION을 해제하는 effect는 등록하지 않는다.

## 계약 경계

ConstraintEffect는 disposition이나 output control을 확정하지 않는다. record type/value에서 exact effect로의 mapping은 supported interpretation이며 `ASSUMPTION-CONSTRAINT-EFFECT-001`로 추적한다. Step 8 전까지 registry는 shadow-only다.
