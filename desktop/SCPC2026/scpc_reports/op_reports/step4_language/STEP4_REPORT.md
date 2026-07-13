# Step 4 Surface Parser·LanguageRuleRegistry·Context Binder 보고서

## 작업 범위

Step 4에서는 자연어를 span과 Evidence 후보로 변환하는 경계를 고정했다. RulePack, candidate 평가, compiler 의미는 변경하지 않았다.

## 구현 결과

- quotation, negation, predicate, argument, correction, supersession, reference 구조를 추가했다.
- 자연어 어휘 판정을 `evidence.py`에서 LanguageRuleRegistry 경계로 이동했다.
- Context Binder는 동일 semantic slot의 현재 명시적 정정만 supersede한다.
- correction과 conditional fallback을 별도 relation으로 구분했다.
- Fixed SLM이나 외부 모델 의존성은 추가하지 않았다.

## 공식 입력 Audit

- 검사 task: `820`개
- parse 오류: `0`개
- 비결정적 parse: `0`개
- quoted execution 위반: `0`개
- unregistered rule ID: `0`개
- audit SHA-256: `c76754f2685ee524b675b8dabcde2944016c2064790cf4f5ffee2dde4e9acbbe`

공식 입력 parse 성공과 registry coverage는 semantic answer 정확도를 의미하지 않는다. 공식 reference 일치는 dev score와 submission diff로 별도 확인했다.

## 검증 결과

- Step 4 invariant: exit `0`, 43 passed
- 전체 pytest: exit `1`, 1 failed, 75 passed
- 알려진 dev gate 제외: exit `0`, 75 passed, 1 deselected
- dev overall: `0.8036` (Step 3과 동일: `True`)
- screening public submission 동일: `True`

전체 pytest의 dev hard gate 1건은 기존 baseline debt로 남아 있다.

## Step 4 Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- Surface Parser, LanguageRuleRegistry, Context Binder invariant가 통과했다.
- 공식 820개 prompt의 deterministic parse와 quotation authority 검증이 통과했다.
- Step 3 대비 public dev 수치와 screening submission이 변하지 않았다.
- 기존 dev hard gate 실패 1건은 baseline debt로 유지한다.
