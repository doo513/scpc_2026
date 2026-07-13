# Step 9 Decision IR 보고서

## 구현 범위

CandidateEvaluator 이후 의미를 immutable SubDecisionIR에 잠그고, 단일·복합 요청 bundle과 raw-free projection DTO를 shadow path로 구현했다.

## 구조 검증

- disposition: `proceed/ask/hold`
- ask/hold plan: `['read', 'clarify']/['read', 'guard']`
- target 분리: `True`
- stale mutation 차단: `True`
- plan order/lineage: `True/True`
- semantic terminal 보존: `True/True`
- multi aggregate: `multiple_unresolved`
- dependency cycle 차단: `True`
- production import: `0`개

## 회귀

- Step 9 invariant: exit `0`, 131 passed
- 전체 pytest: exit `1`, 1 failed, 210 passed
- 알려진 dev gate 제외: exit `0`, 210 passed, 1 deselected
- dev overall: `0.8036` (Step 8과 동일: `True`)
- screening submission 동일: `True`

전체 pytest의 dev hard gate 1건은 기존 baseline debt다. Step 9는 shadow-only이므로 공식 reference 정확도 개선을 주장하지 않는다.

## Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- CandidateEvaluator 이후 의미와 plan 순서를 immutable SubDecisionIR에 잠갔다.
- execution target과 response target을 분리하고 lineage를 보존했다.
- 복수 operation의 disposition·dependency를 보존하고 임의 aggregate control을 만들지 않았다.
- Step 8 대비 public dev 수치와 screening submission이 변하지 않았다.
