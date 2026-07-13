# Step 7 Constraint Registry 보고서

## 구현 범위

Typed record fact 수집, exact pair activation, canonical effect algebra를 shadow path로 구현했다. CandidateState, control, fallback은 이 단계에서 결정하지 않는다.

## 검증 결과

- Global fact rule: `18`개
- PairConstraintSpec: `7`개
- 공식 task 구조 처리: `820/820`
- 공식 task fact 수집 오류: `0`개
- record permutation 동일: `True`
- effect permutation 동일: `True`
- duplicate effect 멱등성: `True`
- local counterfactual active constraint: `0`개
- production import: `0`개

`structurally_processed`는 accuracy가 아니다. 정답 없는 screening의 semantic correctness를 주장하지 않는다.

## 회귀

- Step 7 invariant: exit `0`, 66 passed
- 전체 pytest: exit `1`, 1 failed, 135 passed
- 알려진 dev gate 제외: exit `0`, 135 passed, 1 deselected
- dev overall: `0.8036` (Step 6와 동일: `True`)
- screening submission 동일: `True`

전체 pytest의 dev hard gate 1건은 기존 baseline debt로 남아 있다.

## Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- Global fact와 pair activation 경계가 전수 구조 검사와 반례를 통과했다.
- effect permutation, idempotence, conflict 보존 검증이 통과했다.
- constraint가 control을 직접 소유하지 않고 production에서 비활성임을 확인했다.
- Step 6 대비 public dev 수치와 screening submission이 변하지 않았다.
