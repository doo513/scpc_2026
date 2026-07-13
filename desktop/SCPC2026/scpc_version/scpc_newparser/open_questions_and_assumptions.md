# Open Questions and Assumptions

## 구현 전에 반드시 해결해야 하는 항목

| ID | 상태 | 질문 | 선택지와 영향 | 현재 처리 |
| --- | --- | --- | --- | --- |
| OQ-01 | BLOCKING_FOR_TYPED_PROMOTION | final answer `target`의 execution target/response target mapping은 무엇인가 | 동일시하면 잘못된 dispatch 위험; 분리하면 explicit mapping 필요 | current FinalDecision 유지, typed promotion 금지 |
| OQ-02 | BLOCKING_FOR_MULTI_DECISION | 복수 operation aggregate control/answer 규칙은 무엇인가 | 단일 control 발명 또는 subdecision 보존 | full bundle shadow-only |
| OQ-03 | BLOCKING_FOR_PARTIAL_COMMIT | 부분 성공 시 persistent commit 범위는 무엇인가 | all-or-nothing 또는 독립 unit commit | single-answer atomic only |
| OQ-04 | BLOCKING_FOR_FIXEDSLM_PROMOTE | FixedSLM timeout/invalid output 공식 계약이 있는가 | 공식 wrapper 사용 또는 local fail-closed wrapper | KEEP_SHADOW |
| OQ-05 | BLOCKING_FOR_FALLBACK | 공식 허용 fallback edge는 무엇인가 | explicit edge만 또는 fallback 비활성 | 무권한 자동 fallback 금지 |
| OQ-06 | BLOCKING_FOR_PLAN_PROMOTION | redact/summarize는 platform action인가 internal transform인가 | available_actions 적용 범위가 달라짐 | assumption ID 유지 |

## 구현 중 진단으로 남길 수 있는 항목

| ID | 상태 | 내용 | 진단 방식 |
| --- | --- | --- | --- |
| OQ-07 | NON_BLOCKING_CURRENT | semantic_response local scoring target 부재 | 축 0.0과 NOT_LOCALLY_SCOREABLE 기록 |
| OQ-08 | NON_BLOCKING_CURRENT | screening label 부재 | 구조 분포만 보고, accuracy 주장 금지 |
| OQ-09 | NON_BLOCKING_CURRENT | unknown future record type | UNKNOWN/INVALID typed status와 provenance 유지 |
| OQ-10 | NON_BLOCKING_CURRENT | historical baseline source의 task-specific 처리 | current production에 import하지 않고 diagnostic only |

## FixedSLM 가정

- 공식 facade가 제공된다는 사실은 CONFIRMED다.
- facade가 필수라는 근거는 없다.
- risk/redaction/confirmation/audit 출력이 auxiliary evidence라는 해석은 공식 notebook 설명이 지지한다.
- timeout, invalid output, retry, latency contract는 UNRESOLVED다.
- current direct evidence와 hard fact를 덮어쓰지 못한다는 boundary는 구현 정책으로 유지한다.
- parser-only 대비 일반화 개선이 입증되지 않았으므로 현재 결정은 `KEEP_SHADOW`다.

## Artifact 가정

- 동일 source/data/scorer에서 deterministic submission bytes가 생성돼야 한다.
- report 생성 시각은 내용 동일성의 증거가 아니다.
- manifest `content_fingerprint_sha256`은 `generated_at`을 제외한 모든 의미 필드를 포함한다.
- 여러 candidate manifest가 있으면 authoritative producer, source/data/scorer/submission hash가 모두 맞는 것만 current다.

## Release 차단 요소

현재 즉시 확인된 차단 요소는 다음과 같다.

1. official dev hard gate 실패: `0.8186 < 0.9421`.
2. typed RulePack/Candidate/Constraint/Bundle 경로가 actual official task의 production semantic owner로 연결되지 않음.
3. FixedSLM held-out improvement와 byte-equivalent failure recovery가 입증되지 않음.
4. multi-decision aggregate와 partial commit 공식 계약이 해결되지 않음.

이 차단 요소는 output projection, pure compiler, validation-before-commit, atomic single-answer commit의 사용을 막지는 않는다. 다만 typed semantic replacement와 FixedSLM promotion을 막는다.

## 금지된 해결 방식

- dev gate threshold 하향
- official reference/scorer/schema 수정
- task ID, 인물명, 장소명, target name, 공개 문장 exact lookup
- screening output을 정답으로 간주
- FixedSLM output으로 final fields 직접 생성
- 생성 시각만으로 stale 해제
- compiler에서 prompt/record/session 재해석
