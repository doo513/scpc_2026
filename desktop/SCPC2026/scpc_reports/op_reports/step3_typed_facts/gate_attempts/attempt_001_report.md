# Step 3 공식 입력 계약·Typed Fact·RecordAdapter 보고서

## 작업 범위

Step 3에서는 공식 JSON 입력을 typed fact로 변환하는 경계를 고정했다. 자연어 parser, RulePack, candidate 평가 규칙은 변경하지 않았다.

## 구현 결과

- `TaskView`에 object, record, capability, session snapshot을 추가했다.
- `FactStatus`는 missing, unknown, conflict, invalid를 서로 다른 상태로 보존한다.
- raw record value 해석은 type별 `RecordAdapter`로 제한했다.
- record chronology는 동일 domain 안에서만 비교한다.
- `gallery_item`과 공식 용어집에 기재된 record type을 ontology에 반영했다.

## 공식 입력 Audit

- 검사 task: `820`개
- object 상태: `{"present": 5040}`
- record 상태: `{"present": 6090}`
- permutation 실패: `0`개
- typed snapshot SHA-256: `513f08c1d3f0b7db0c83ce8841fb62e2e24b2d9f7d07d3d7932ce4aaad5b003a`

공식 820개 입력에서 typed parsing 오류가 없다는 결과는 입력 계약의 구조적 적합성을 뜻한다. semantic answer accuracy로 해석하지 않는다.

## 검증 결과

- Step 3 invariant: exit `0`, 33 passed
- 전체 pytest: exit `1`, 1 failed, 66 passed
- 알려진 dev gate 제외: exit `0`, 66 passed, 1 deselected
- dev overall: `0.8036` (Step 2와 동일: `False`)
- screening public submission 동일: `False`
- runtime raw record 접근 위반: `0`건

전체 pytest의 dev hard gate 1건은 Step 1에서 확인한 baseline debt다. 이번 단계에서 해소됐다고 보고하지 않는다.

## 계약 등급과 한계

record type과 기본 의미는 공식 용어집을 근거로 삼았다. 공개 자료가 모든 value vocabulary를 열거하지 않으므로, 구체 token mapping은 `SUPPORTED_INTERPRETATION`으로 유지한다. 등록되지 않은 token은 `UNKNOWN`으로 보존하며 실행 의미로 승격하지 않는다.

## Step 3 Release Gate

- 상태: **FAIL**
- 다음 단계 진입 가능: **False**
- 실패한 Step 3 gate: step2_gate_available
- 실패한 Step 3 gate: dev_unchanged
- 실패한 Step 3 gate: screening_submission_unchanged
