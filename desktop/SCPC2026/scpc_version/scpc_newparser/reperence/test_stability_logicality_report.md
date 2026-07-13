# Test Stability / Logicality 실행 근거

- 작성일: 2026-07-12
- source tree SHA-256: `1ee0a4ef2396b2a0c1c63f3f821491a947100f7b90104ef61fa9bd140a1397de`
- release promotion: `NOT_INVOKED`
- authoritative manifest/submission mutation: `NONE`

## 1. 수정한 계약

### S1. ASK scope와 비실행 plan의 의미 분리

코드 위치:

- `core/blueprint.py:12` — `project_scope_mode()` 단일 계약
- `core/decision.py:2526` — FinalDecision projection
- `core/consistency.py:99` — frozen Blueprint authority에서 독립 검증

투영 규칙:

```text
hold                    -> none
ask + raw               -> summary
ask + status_only       -> none
ask + summary/redacted  -> compiled mode 유지
proceed/amend            -> compiled mode 유지
```

`ask` plan은 계속 `read -> clarify`만 허용하며 dispatch/update/pay/toggle/schedule은
validator가 거부한다. 합성 반례 결과:

```text
input property=doctor_note (RESTRICTED), explicit clarification
control=ask
compiled Blueprint scope=redacted
public scope=redacted
excluded_fields=[doctor_note]
plan verbs=[read, clarify]
execution verbs=[]
```

### S2. property policy matrix fail-fast

코드 위치:

- `core/property_policy.py:198` — totality, severity/directive, mode validity,
  monotonicity, UNKNOWN/HARD/NONE 검사
- `core/property_policy.py:272` — import 시 계약 검증
- `release_gate.py:54` — 필수 check `property_policy_matrix_valid`

실행한 변형:

```text
missing matrix rows                 -> ValueError
UNKNOWN permitted={summary, none}  -> ValueError
PUBLIC..UNKNOWN 모든 순열 120개     -> 동일 UNKNOWN/HARD/NONE effect
contains/fields 중복·순서 변형       -> provenance 보존, RESTRICTED 우선
```

테스트 위치: `tests/test_property_policy_stability.py:33`.

### S3. dev score를 비차단 진단으로 명문화

코드 위치:

- `tests/specs/generalization_v1.json:2` — spec `2.1.0`
- `tests/specs/generalization_v1.json:12` — `release_blocking=false`
- `tests/test_regression.py:36` — 120개 전체를 계속 채점
- `tests/test_regression.py:80` — threshold 결과를 test property로 기록

변경하지 않은 것:

```text
official dev tasks/answers
scorer와 weight
minimum thresholds
task exclusion 정책 (0개 제외)
production decision의 task/session ID 비의존성
```

테스트는 answer coverage, score 범위, 전체 120개 포함 여부를 실패 조건으로 유지한다.
공개 dev threshold 미달은 숨기지 않고 release report의 비차단 진단으로 남긴다.

## 2. 실행 결과

### Targeted

```text
67 passed in 9.24s
Ruff: All checks passed
```

### 전체 suite

```text
278 passed in 13.18s
failed=0
deselected=0
Ruff: All checks passed
```

### dev 진단

```text
before=0.8483
after=0.8590
delta=+0.0107
threshold=0.9421
thresholds_met=false
release_blocking=false
exact/non-exact=21/99
```

축별 결과:

```text
focal=1.0000
target=0.9500
control=0.9417
content_scope=0.7099
policy=0.8890
plan=0.8844
```

### screening / HARD / release checks

```text
screening answers=700
screening traces=700
HARD projection violations=0
authoritative runtime specificity hits=0
semantic checks=7/7 true
required release check contract=14/14 true
```

screening mode 분포:

```text
none=152
summary=82
redacted=297
status_only=160
raw=9
```

## 3. artifact 불변성

```text
manifest/candidate_manifest.json SHA-256
  21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389

submission.csv SHA-256
  f2791ae6a3ebd78007a7a04a7cb05f1d1bbf5465a9605141585e402c81ec8a9c

publish/validate/promote invoked=false
```

두 artifact는 새 source와 일치하지 않는 기존 stale artifact 상태를 유지한다. 이
보고서는 release readiness를 판정하거나 promotion을 승인하지 않는다.

## 4. 남은 한계

- dev threshold 자체는 충족하지 않는다. 이를 production 성공 조건으로 다시 사용하면
  과거의 answer-fitting 압력이 재발한다.
- ASK가 sanitized scope를 보존한다는 계약은 공식 reference 및 content-scope 정의와
  일치하지만, 모든 가능한 입력의 의미 정답을 증명하지는 않는다.
- property-name registry가 실제 세계의 완전한 sensitivity oracle이라는 근거는 없다.
  미등록 type/field는 계속 UNKNOWN/HARD/NONE으로 처리한다.

