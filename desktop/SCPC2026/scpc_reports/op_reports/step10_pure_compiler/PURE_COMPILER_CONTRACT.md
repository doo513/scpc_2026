# Step 10 Pure Compiler Contract

- ScopeCompiler는 ScopeProjection의 enum과 필드를 공식 content_scope shape로 복사한다.
- PolicyCompiler는 PolicyProjection의 필드를 공식 policy shape로 복사한다.
- PlanCompiler는 PlanProjection의 step 순서, verb, target, args를 그대로 복사한다.
- ProjectionCompiler는 같은 decision lock을 가진 세 projection만 구조적으로 결합한다.
- compiler는 raw input, Evidence, candidate, RulePack, evaluator, session을 조회하지 않는다.
- compiler는 operation, outer target, control을 생성하거나 재판단하지 않는다.
- event 개수 제한은 immutable config로 명시하며 공식 schema 최대값 18을 넘길 수 없다.
- Step 10 경로는 shadow-only이며 production output에는 연결하지 않는다.
