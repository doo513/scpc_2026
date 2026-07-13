# SCPC AI Harness 설계 개요

## 1. 한 줄 정의

**Task JSON의 구조적 사실과 자연어 근거를 분리해 해석하고, 후보별 제약·정보·실행 가능성을 검증한 뒤 6개 필수 출력 필드를 일관되게 생성하는 결정 엔진이다.**

```text
입력
prompt + history + objects + records + memory + available_actions

출력
focal_id + target + control + content_scope + policy + plan_events
```

---

## 2. 전체 구조

```text
Task JSON
│
├─ 1. Fact Lock
│  └─ objects·records·session을 TypedFact와 Relation으로 고정
│
├─ 2. NLP Evidence Lock
│  └─ prompt를 절·인용·부정·predicate·argument Evidence로 분해
│
├─ 3. Candidate Resolution
│  └─ focal·domain·operation·target 후보를 공동 생성
│
├─ 4. Candidate Evaluation
│  └─ target role·정보·constraint·전체 plan capability 평가
│
├─ 5. Authorized Fallback
│  └─ 명시적으로 허가된 대안만 재평가
│
├─ 6. FinalDecision Lock
│  └─ 최종 의미와 실행 상태를 불변 객체로 확정
│
├─ 7. Pure Output Projection
│  └─ scope·policy·plan을 재판단 없이 출력 형식으로 변환
│
└─ 8. Validation & Commit
   └─ 종단 검증 통과 후 session·memory 갱신
```

---

## 3. 단계별 계약

| 단계 | 하는 일 | 생성물 | 절대 하면 안 되는 일 |
|---|---|---|---|
| Fact | JSON 사실 정형화 | TypedFact, Relation | 자연어 추측으로 fact 변경 |
| NLP | prompt 구조 분석 | IntentEvidence | 최종 action·target·control 확정 |
| Candidate | 의미 후보 조합 | Action–Target 후보 | raw string fallback |
| Evaluation | 후보 실행 가능성 판단 | CandidateState | 점수로 hard constraint 우회 |
| Decision | 최종 후보 선택 | FinalDecisionIR | 이후 단계에서 의미 변경 허용 |
| Output | 필수 필드 생성 | answer JSON | prompt·raw record 재조회 |
| Validation | 의미·스키마 검증 | pass/fail | 검증 전 memory commit |

---

## 4. 자연어 처리

### 처리 방식

```text
prompt
→ 문장·절 분리
→ quotation span
→ negation span
→ predicate frame
→ argument span
→ correction / supersession
→ Lexicon·Pattern 매칭
→ IntentEvidence 생성
```

### 핵심 원칙

- 자연어는 **Evidence만 생성**한다.
- 특정 단어 하나가 `pay`, `target=user`, `hold`, `dispatch`를 직접 결정하지 않는다.
- 같은 표현이라도 인용·부정·질문·명령을 구분한다.

```text
켜줘
→ ENABLE + COMMAND + POSITIVE

켜지 말고
→ ENABLE + COMMAND + NEGATIVE

켜지는지 확인해줘
→ ENABLE_STATE + VERIFY
```

### 중앙 규칙

```text
Rule
├─ rule_id
├─ semantic_slot
├─ requires
├─ forbids
├─ scope
├─ emits
├─ priority
└─ authority
```

### 금지

- 전체 prompt → 정답 lookup
- 사람·target 이름 → role 확정
- task ID → 출력 분기
- 해석 실패 → default dispatch
- compiler에서 문자열 재검색

---

## 5. 근거 우선순위

```text
현재 사용자의 직접 지시
>
현재 입력의 구조적 Fact
>
visible_history
>
personal_memory
>
인용문·데이터 payload 내부 텍스트
```

단순 점수 합산이 아니라 다음 규칙을 적용한다.

- hard constraint는 점수로 뒤집지 않는다.
- 현재 정정은 **같은 semantic slot**의 이전 Evidence만 비활성화한다.
- history·memory는 현재 prompt와 충돌하지 않을 때만 사용한다.
- `hold > ask > amend > proceed` 전역 우선순위는 사용하지 않는다.

---

## 6. 후보 구조

```text
FocalCandidate
+
DomainCandidate
+
OperationCandidate
+
TargetCandidate
→ ActionTargetCandidate
```

### Domain과 Operation 분리

```text
Domain
PAYMENT / DEVICE / CALENDAR / MEMORY / CONTENT / GENERAL

Operation
EXECUTE / CREATE / MODIFY / CANCEL / VERIFY / SHARE / STORE / DELETE / CLARIFY
```

예:

```text
PAYMENT + EXECUTE
PAYMENT + CANCEL
DEVICE + MODIFY
DEVICE + VERIFY
CALENDAR + CREATE
CONTENT + SHARE
```

### Target

```text
Target Identity
+
Target Role
+
Target Locality
```

필수 role 예:

```text
PAYMENT + EXECUTE → payment/merchant
DEVICE + MODIFY   → device
CALENDAR + MODIFY → event/calendar
CONTENT + SHARE   → recipient
```

필수 role이 없으면 일반 `user`로 우회하지 않고 `NEEDS_INFORMATION` 또는 `REJECTED`로 남긴다.

---

## 7. 후보 평가

```text
Action–Target 후보
→ target role 검사
→ required information 검사
→ base plan blueprint 생성
→ pair-specific constraint 적용
→ constraint effect 반영
→ 전체 required action 계산
→ available_actions 검사
```

### CandidateState

```text
EXECUTABLE
AMENDABLE
NEEDS_INFORMATION
NEEDS_CONFIRMATION
BLOCKED
REJECTED
SUPERSEDED
```

`UNKNOWN`, `MISSING`, `CONFLICT`를 모두 `None`으로 합치지 않는다.

### Constraint Effect

```text
BLOCK_EXECUTION
ADD_CONFIRMATION
ADD_REDACTION
FORCE_SUMMARY
LIMIT_DURATION
RESTRICT_TARGET
```

Constraint는 원래 operation을 바꾸지 않고 safeguard·modification·block 상태만 추가한다.

### 전체 plan capability

```text
read → verify → pay
```

이라면 `pay`만 확인하지 않고 `read`, `verify`, `pay` 전체를 `available_actions`와 비교한다.

---

## 8. Fallback

Fallback은 단순 차순위 후보 선택이 아니다.

```text
FallbackEdge
├─ source candidate
├─ destination candidate
├─ activation condition
├─ authorization source
├─ preserved semantics
└─ reason code
```

허가 근거:

- 현재 사용자가 명시한 대안
- 공식 policy의 대체 경로
- 공식적으로 정의된 plan transformation

```text
대안 없음 → hold
허가된 대안 1개 → 선택
허가된 대안 여러 개 → ask
```

대체 후보도 일반 후보와 동일한 평가를 다시 통과한다.

---

## 9. FinalDecision과 출력

### FinalDecisionIR

```text
FinalDecisionIR
├─ focal_id
├─ domain
├─ operation
├─ target_id
├─ target_role
├─ control
├─ active_constraints
├─ safeguards
├─ modifications
├─ reason_codes
├─ fallback_source
└─ blueprint_id
```

FinalDecision 이후 domain·operation·target은 변경할 수 없다.

### 필수 필드의 단일 소유권

| 출력 필드 | 생성 책임 |
|---|---|
| focal_id | FinalDecision.selected_focal |
| target | FinalDecision.selected_target |
| control | Decision Resolver |
| content_scope | ScopeCompiler |
| policy | PolicyCompiler |
| plan_events | PlanCompiler |

### Pure Compiler

Compiler가 볼 수 있는 것:

```text
ScopeInput
PolicyInput
PlanInput
```

Compiler가 볼 수 없는 것:

```text
prompt
TaskView
raw objects / records
EvidenceGraph
DecisionMatrix
문자열 keyword
```

Compiler는 판단하지 않고 출력 형식으로 조립만 한다.

---

## 10. 출력 일관성

```text
operation ↔ plan terminal
selected target ↔ required role
active constraint ↔ policy reason
constraint effect ↔ safeguard
safeguard ↔ content_scope
plan verbs ↔ available_actions
fallback ↔ authorization source
```

예:

```text
PAYMENT + EXECUTE → pay
DEVICE + MODIFY   → toggle
CALENDAR + CREATE → schedule
CONTENT + SHARE   → dispatch
MEMORY + STORE    → update
```

다음은 오류다.

```text
selected dispatch → update
selected toggle + amend → dispatch
merchant 없음 → pay(user)
```

---

## 11. Session·Memory

```text
CommittedSessionState
+
Current Turn Speculative Overlay
→ 현재 turn의 Context View
```

- 같은 turn의 후속 절은 임시 변경을 읽을 수 있다.
- persistent memory는 검증 전 변경하지 않는다.
- 검증 실패 시 commit하지 않는다.
- 복합 요청에서는 dependency가 있는 작업만 연쇄 rollback한다.

처리 순서:

```text
answer 생성
→ ConsistencyValidator
→ commit eligibility 확인
→ session·memory 갱신
```

---

## 12. 검증

### 필수 검증

```text
schema
focal 존재성
target role
operation-terminal
candidate state-control
constraint-policy
effect-safeguard-scope
fallback-authorization
plan verb-available_actions
```

### 일반화 검증

```text
배열 순서 변경
이름·ID 교체
paraphrase
negation 최소대립
quotation 최소대립
correction 최소대립
constraint counterfactual
capability ablation
unknown shape
session lifecycle
```

### 회귀 기준

```text
legacy 출력 차이 → 허용 가능
공식 dev reference 차이 → release failure
screening 분포 변화 → 진단 정보일 뿐 추론 근거 아님
```

---

## 13. 모듈 책임

```text
TaskView              → 입력 정규화
RecordAdapter         → record type별 의미 해석
RelationGraph         → object·record 관계
PromptDocument        → 절·인용·부정·span
NLP Rule Registry     → Lexicon·Pattern 규칙
EvidenceBuilder       → Fact·NLP 결과를 Evidence로 변환
FocalResolver         → focal 후보
TargetResolver        → target identity·role·locality
BlueprintRegistry     → domain·operation별 plan 요구사항
CandidateEvaluator    → 정보·constraint·capability 평가
FallbackSolver        → 허가된 대안 평가
DecisionResolver      → FinalDecisionIR 확정
ScopeCompiler         → content_scope
PolicyCompiler        → policy
PlanCompiler          → plan_events
ConsistencyValidator  → 종단 검증
SessionManager        → 검증 후 commit
```

---

## 14. 미확정 가정

다음은 공식 근거가 부족하므로 확정 규칙으로 사용하지 않는다.

```text
CANCEL capability의 공식 표현
cross-session memory 시간축
복합 operation의 단일 answer 집계
입력에 보이지 않는 dev target 의미
부분 성공 시 session commit 범위
safeguard action의 capability 계약
```

미확정 항목은 `assumption`으로 격리하고 trace에 표시한다.

---

## 15. 최종 요약

```text
Fact는 구조적으로 잠근다.
자연어는 Evidence로만 바꾼다.
Focal·Domain·Operation·Target을 공동 평가한다.
Constraint는 후보 쌍에만 적용한다.
정보 부족과 capability 부족을 분리한다.
Fallback은 명시적 허가가 있을 때만 수행한다.
FinalDecision 이후 의미를 바꾸지 않는다.
Compiler는 순수 투영만 한다.
검증 통과 후에만 session·memory를 갱신한다.
공식 근거가 없는 규칙은 assumption으로 격리한다.
```
