SCPC Harness 상호 영향 관계도
│
├─ 1. 입력 해석
│  │
│  ├─ (prompt ↔ visible_history)
│  │  ├─ 현재 요청
│  │  ├─ 이전 요청
│  │  ├─ 정정
│  │  ├─ 취소
│  │  └─ 최신 지시 우선순위
│  │
│  ├─ (prompt ↔ personal_memory)
│  │  ├─ 현재 명시적 지시 우선
│  │  ├─ 저장된 선호 보조
│  │  └─ 충돌 시 memory 비활성화
│  │
│  ├─ (visible_history ↔ session_state)
│  │  ├─ 이전 focal
│  │  ├─ 이전 target
│  │  ├─ 대명사 해소
│  │  └─ entity lifecycle
│  │
│  └─ (device_state.objects ↔ device_state.records)
│     ├─ object identity
│     ├─ ref_code 관계
│     ├─ focal binding
│     ├─ target relation
│     └─ constraint 적용 대상
│
├─ 2. 자연어 처리
│  │
│  ├─ (절 경계 ↔ operation 후보)
│  │  ├─ 복수 요청 분리
│  │  ├─ 실행
│  │  ├─ 취소
│  │  ├─ 확인
│  │  └─ 공유
│  │
│  ├─ (부정 범위 ↔ polarity)
│  │  ├─ 실행 활성
│  │  ├─ 실행 부정
│  │  ├─ 켜기 부정
│  │  └─ 취소 활성
│  │
│  ├─ (인용 범위 ↔ intent authority)
│  │  ├─ 인용된 실행 문장
│  │  ├─ 실제 사용자 요청
│  │  └─ quoted evidence 비활성화
│  │
│  ├─ (역접·정정 ↔ Evidence supersession)
│  │  ├─ 이전 evidence
│  │  ├─ 최신 evidence
│  │  ├─ 동일 semantic slot
│  │  └─ active / inactive
│  │
│  ├─ (Lexicon ↔ Pattern DSL)
│  │  ├─ 단어 의미 후보
│  │  ├─ 문맥 조건
│  │  ├─ 금지 조건
│  │  └─ IntentEvidence 생성
│  │
│  └─ (자연어 Evidence ↔ 구조적 Fact)
│     ├─ 자연어는 후보 제안
│     ├─ 구조 정보는 binding 근거
│     ├─ 충돌 시 authority 비교
│     └─ 최종 후보 confidence
│
├─ 3. Focal·Target 해소
│  │
│  ├─ (FocalCandidate ↔ DomainCandidate)
│  │  ├─ payment object ↔ PAYMENT
│  │  ├─ device object ↔ DEVICE
│  │  ├─ calendar object ↔ CALENDAR
│  │  └─ semantic compatibility
│  │
│  ├─ (FocalCandidate ↔ OperationCandidate)
│  │  ├─ 취소 가능한 대상
│  │  ├─ 수정 가능한 대상
│  │  ├─ 공유 가능한 대상
│  │  └─ verification 대상
│  │
│  ├─ (TargetCandidate ↔ OperationCandidate)
│  │  ├─ 실행 target
│  │  ├─ 공유 recipient
│  │  ├─ local storage
│  │  └─ clarification target
│  │
│  ├─ (Target identity ↔ Target role)
│  │  ├─ merchant
│  │  ├─ recipient
│  │  ├─ device
│  │  ├─ event
│  │  └─ memory_store
│  │
│  └─ (Target role ↔ Target locality)
│     ├─ internal
│     ├─ external
│     ├─ local
│     └─ constraint 적용 범위
│
├─ 4. 의미 후보 구성
│  │
│  ├─ (Domain ↔ Operation)
│  │  ├─ PAYMENT × EXECUTE
│  │  ├─ PAYMENT × CANCEL
│  │  ├─ PAYMENT × SHARE
│  │  ├─ DEVICE × MODIFY
│  │  ├─ DEVICE × VERIFY
│  │  ├─ CALENDAR × CREATE
│  │  └─ CALENDAR × CANCEL
│  │
│  ├─ (Domain·Operation ↔ Required target role)
│  │  ├─ PAYMENT·EXECUTE ↔ payment target
│  │  ├─ PAYMENT·SHARE ↔ recipient
│  │  ├─ DEVICE·MODIFY ↔ device
│  │  └─ CALENDAR·MODIFY ↔ event/calendar
│  │
│  ├─ (Domain·Operation ↔ Required information)
│  │  ├─ merchant
│  │  ├─ amount
│  │  ├─ device state
│  │  ├─ date/time
│  │  └─ recipient
│  │
│  └─ (ActionCandidate ↔ TargetCandidate)
│     ├─ role compatibility
│     ├─ locality compatibility
│     ├─ information completeness
│     └─ Action–Target Pair
│
├─ 5. 제약·실행 가능성
│  │
│  ├─ (Action–Target Pair ↔ Constraint)
│  │  ├─ consent
│  │  ├─ security
│  │  ├─ safety
│  │  ├─ payment policy
│  │  ├─ local boundary
│  │  └─ temporary override
│  │
│  ├─ (Target locality ↔ Constraint activation)
│  │  ├─ external dispatch 차단
│  │  ├─ internal target 허용
│  │  ├─ local update 비적용
│  │  └─ scoped constraint
│  │
│  ├─ (Constraint ↔ Constraint effect)
│  │  ├─ BLOCK_EXECUTION
│  │  ├─ ADD_CONFIRMATION
│  │  ├─ ADD_REDACTION
│  │  ├─ FORCE_SUMMARY
│  │  ├─ LIMIT_DURATION
│  │  └─ RESTRICT_TARGET
│  │
│  ├─ (Constraint effect ↔ Plan requirements)
│  │  ├─ redaction 필요
│  │  ├─ summary 필요
│  │  ├─ verification 추가
│  │  └─ duration parameter 추가
│  │
│  ├─ (Plan requirements ↔ available_actions)
│  │  ├─ 전체 verb 확인
│  │  ├─ terminal action 확인
│  │  ├─ safeguard action 확인
│  │  └─ Candidate executable 여부
│  │
│  └─ (Required information ↔ Candidate state)
│     ├─ 충족 → 평가 계속
│     ├─ 누락 → NEEDS_INFORMATION
│     ├─ 충돌 → CONFLICTED
│     └─ role 불일치 → REJECTED
│
├─ 6. Control 결정
│  │
│  ├─ (사용자 의도 ↔ Candidate state)
│  │  ├─ 명시적 실행
│  │  ├─ 명시적 취소
│  │  ├─ 확인 요청
│  │  └─ 정보 보충 요청
│  │
│  ├─ (Candidate state ↔ control)
│  │  ├─ EXECUTABLE → proceed
│  │  ├─ AMENDABLE → amend
│  │  ├─ NEEDS_INFORMATION → ask
│  │  └─ BLOCKED → hold
│  │
│  ├─ (control ↔ operation)
│  │  ├─ control은 operation 상태만 표현
│  │  ├─ operation 변경 금지
│  │  └─ domain 변경 금지
│  │
│  └─ (control ↔ active constraint)
│     ├─ hold 원인
│     ├─ amend 원인
│     ├─ ask 원인
│     └─ policy reason 연결
│
├─ 7. Fallback
│  │
│  ├─ (차단된 원 후보 ↔ FallbackEdge)
│  │  ├─ 사용자 대안 지시
│  │  ├─ 공식 policy 대체 경로
│  │  └─ 의미 보존 transformation
│  │
│  ├─ (FallbackEdge ↔ 대체 Action–Target Pair)
│  │  ├─ external dispatch → local update
│  │  ├─ raw dispatch → redacted dispatch
│  │  └─ 실행 → clarification
│  │
│  ├─ (대체 후보 ↔ Constraint·Capability)
│  │  ├─ 동일 evaluator 재사용
│  │  ├─ shortcut 평가 금지
│  │  └─ executable 재검증
│  │
│  └─ (Fallback 후보 수 ↔ control)
│     ├─ 0개 → hold
│     ├─ 허가된 1개 → fallback 선택
│     ├─ 여러 개 → ask
│     └─ 허가 없음 → 자동 전환 금지
│
├─ 8. 이전 맥락·세션
│  │
│  ├─ (Current Prompt ↔ History)
│  │  ├─ 현재 명시적 지시 우선
│  │  ├─ 이전 요청 보조
│  │  └─ 정정 scope 일치 여부
│  │
│  ├─ (Previous Focal ↔ Current Objects)
│  │  ├─ 현재 존재
│  │  ├─ 삭제
│  │  ├─ 완료
│  │  ├─ 대체
│  │  └─ stale ID 검증
│  │
│  ├─ (Provisional Memory ↔ 후속 절)
│  │  ├─ 같은 turn 참조
│  │  ├─ read dependency
│  │  └─ speculative state
│  │
│  └─ (선행 operation 실패 ↔ 후속 operation)
│     ├─ 실제 의존 → cascading rollback
│     ├─ 독립 operation → 별도 유지
│     └─ dependency graph
│
├─ 9. 최종 결정 잠금
│  │
│  ├─ (Selected Pair ↔ FinalDecision)
│  │  ├─ domain 보존
│  │  ├─ operation 보존
│  │  ├─ focal 보존
│  │  └─ target 보존
│  │
│  ├─ (FinalDecision ↔ ScopeInput)
│  │  ├─ disclosure mode
│  │  ├─ target locality
│  │  ├─ safeguards
│  │  └─ disposition
│  │
│  ├─ (FinalDecision ↔ PolicyInput)
│  │  ├─ active constraints
│  │  ├─ reason codes
│  │  ├─ fallback reason
│  │  └─ modifications
│  │
│  └─ (FinalDecision ↔ PlanInput)
│     ├─ domain
│     ├─ operation
│     ├─ target
│     ├─ blueprint
│     ├─ capabilities
│     └─ modifications
│
├─ 10. 출력 필드 상호 관계
│  │
│  ├─ (control ↔ content_scope)
│  │  ├─ hold/ask → none
│  │  ├─ local execution → status_only
│  │  └─ dispatch → raw/summary/redacted
│  │
│  ├─ (content_scope ↔ plan_events)
│  │  ├─ summary ↔ summarize
│  │  ├─ redacted ↔ redact
│  │  ├─ raw ↔ dispatch
│  │  └─ status_only ↔ domain terminal
│  │
│  ├─ (operation ↔ plan terminal semantics)
│  │  ├─ PAYMENT·EXECUTE ↔ pay
│  │  ├─ DEVICE·MODIFY ↔ toggle
│  │  ├─ CALENDAR·CREATE/MODIFY ↔ schedule
│  │  ├─ MEMORY·STORE ↔ update
│  │  └─ CONTENT·SHARE ↔ dispatch
│  │
│  ├─ (active constraint ↔ policy)
│  │  ├─ consent revoked
│  │  ├─ security block
│  │  ├─ safety block
│  │  ├─ information missing
│  │  └─ capability unavailable
│  │
│  └─ (safeguard ↔ scope·plan·policy)
│     ├─ redaction
│     ├─ summary
│     ├─ confirmation
│     └─ duration limit
│
└─ 11. 종단 검증
   │
   ├─ (selected focal ↔ answer.focal_id)
   ├─ (selected target ↔ answer.target)
   ├─ (selected operation ↔ plan semantics)
   ├─ (candidate state ↔ control)
   ├─ (constraint effect ↔ safeguard)
   ├─ (safeguard ↔ content_scope)
   ├─ (content_scope ↔ plan event)
   ├─ (active constraint ↔ policy reason)
   ├─ (fallback 선택 ↔ authorization source)
   ├─ (plan verb ↔ available_actions)
   ├─ (rollback state ↔ terminal event 부재)
   └─ (official dev reference ↔ 최종 answer)

핵심 상호 영향 경로

(prompt ↔ history)
→ (자연어 Evidence ↔ 구조적 Fact)
→ (Domain ↔ Operation)
→ (Action ↔ Target)
→ (Pair ↔ Constraint)
→ (Constraint effect ↔ Plan requirements)
→ (Plan requirements ↔ Capability)
→ (Candidate state ↔ Control)
→ (차단 후보 ↔ Fallback)
→ (FinalDecision ↔ Scope·Policy·Plan)
→ (내부 결정 ↔ 최종 JSON 검증)

가장 중요한 훼손 방지 쌍

(선택된 operation ↔ 최종 plan)
(선택된 target ↔ 최종 target)
(active constraint ↔ policy reason)
(safeguard ↔ content_scope)
(content_scope ↔ plan event)
(required information ↔ ask)
(capability unavailable ↔ hold/fallback)
(현재 prompt ↔ 이전 history)
(선행 operation ↔ 의존 operation)
(fallback 후보 ↔ 사용자·정책 허가)