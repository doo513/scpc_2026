# Step 10 Pure Compiler 보고서

## 구현 범위

잠긴 Projection DTO를 공식 content_scope·policy·plan_events shape로 복사하는 shadow compiler를 구현했다.

## 구조 검증

- 결정론: `True`
- raw context 독립: `True`
- 호출 순서 독립: `True`
- lineage mismatch 차단: `True`
- opaque args 보존: `True`
- plan 순서: `['read', 'dispatch']`
- prohibited dependency: `0`개
- mutable global: `0`개

## 회귀

- Step 10 invariant: exit `0`, 141 passed
- 전체 pytest: exit `1`, 1 failed, 210 passed
- 알려진 dev gate 제외: exit `0`, 210 passed, 1 deselected
- dev overall: `0.8036` (Step 9와 동일: `True`)
- screening submission 동일: `True`

전체 pytest의 dev hard gate 1건은 기존 baseline debt다. 이 단계는 의미 정확도 개선이나 production 전환을 주장하지 않는다.

## Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- 세 compiler가 잠긴 Projection만 받아 공식 field shape로 복사한다.
- 동일 Projection·호출 순서·외부 raw context 변화에 대해 출력이 결정적이다.
- plan step 순서와 임의 args를 재해석 없이 보존하고 lock lineage 불일치를 차단했다.
- Step 9 대비 public dev 수치와 screening submission이 변하지 않았다.
