# 상호 영향 관계도 가설 감사

이 문서는 기존 `SCPC Harness 상호 영향 관계도.md`를 새로 작성하지 않고, 원래 11개 영역에 상태를 부여한다.

| ID | 원래 관계 | 상태 | 근거 및 현재 반영 | 최종 처리 |
| --- | --- | --- | --- | --- |
| R1 | prompt ↔ history/memory/session/object·record | SUPPORTED | `TaskView`, `StateAssembler`, `RelationGraph`, `MemoryStore`; current prompt 우선은 관찰 기반 | Typed fact와 provenance를 유지하고 배열 위치 판단 금지 |
| R2 | 절·부정·인용·정정 ↔ Evidence | SUPPORTED | `surface_parser.py`, `language_registry.py`, `evidence.py`; 공식 guide는 parser 상세를 계약하지 않음 | surface → Evidence만 허용, answer 직접 확정 금지 |
| R3 | focal·target ↔ domain·operation·role·locality | SUPPORTED | `FocalResolver`, `ActionTargetPairBuilder`, `FinalDecision`; official target 의미는 일부 해석 | 현재 FinalDecision owner 유지, typed replacement는 gate 전 shadow |
| R4 | Domain×Operation ↔ role·information·pair | SUPPORTED | legacy production과 exact `core.rulepacks` shadow registry가 모두 존재 | 중복 authority 금지; current production owner는 legacy, RulePack은 shadow |
| R5 | pair ↔ constraint ↔ effect ↔ plan requirement ↔ capability | SUPPORTED | legacy `ConstraintActivator`/`BlueprintCompiler` production, new constraint algebra shadow | official dev gate까지 legacy 하나만 authoritative |
| R6 | intent/candidate state ↔ control | SUPPORTED | `FinalDecisionBuilder`와 `ConsistencyValidator`가 production 일관성을 확인 | constraint/registry가 control 직접 생성하지 않도록 유지 |
| R7 | blocked candidate ↔ authorized fallback | UNRESOLVED | legacy authorized solver는 production, new fallback registry 기본 edge는 비어 있음; 공식 edge 목록 없음 | 무권한 자동 fallback 금지, 공식·사용자 근거가 없으면 선택하지 않음 |
| R8 | current/history/session ↔ speculative dependency/rollback | SUPPORTED | single-decision session은 validation 후 atomic commit; multi-decision overlay는 shadow | 부분 commit 공식 계약이 해결될 때까지 overlay promotion 금지 |
| R9 | selected pair ↔ immutable final decision ↔ projection | CONFIRMED | current `FinalDecision`은 frozen owner, projection lock digest가 scope/policy/plan lineage를 고정 | production compiler는 DTO만 읽고 의미 재판단 금지 |
| R10 | control·scope·policy·plan 상호 일관성 | SUPPORTED | schema, guide, dev reference, `ConsistencyValidator`가 함께 지지 | validation-before-commit hard gate로 유지 |
| R11 | 최종 answer 종단 검증 | CONFIRMED | official schema 검증, full dev scorer, available action·plan consistency, artifact reproduction | release 전에 모두 실행; 하나라도 실패하면 promotion 금지 |

## 세부 충돌과 처리

### R1 배열 위치

`objects`와 `records`의 배열 위치를 최신성이나 의미 우선순위로 사용하는 가설은 공식 guide와 충돌한다. `tests/test_regression.py`의 permutation 검증을 authoritative invariant로 유지한다.

### R2 connector

`단`, `다만`, `하지만`, `대신` 자체가 operation이나 control을 확정한다는 해석은 CONFLICTED다. connector는 clause relation 또는 supersession evidence만 생성해야 한다.

### R4~R7 이중 owner

legacy semantic engine과 `core.rulepacks`, `core.constraints`, `core.candidate_evaluation`, `core.fallbacks`가 동시에 production 결정을 만들면 이중 authority가 된다. 현 상태에서는 legacy `FinalDecision`만 production owner이며 typed replacement는 shadow 결과로만 존재한다. replacement가 release gate를 통과하면 owner registry를 원자적으로 바꾸고 legacy owner를 `SUPERSEDED` 처리해야 한다.

### R8 부분 commit

단일 answer의 session/memory commit은 validation 뒤 all-or-nothing으로 구현됐다. 복수 sub-decision의 부분 성공 규칙은 UNRESOLVED이므로 `SpeculativeSessionOverlay`를 production commit authority로 승격하지 않는다.

### R9~R11 output lock

`FinalDecision → DecisionProjectionSet → ProjectionCompiler → ConsistencyValidator → AtomicSessionCommitter` 순서가 production에 연결됐다. compiler는 prompt, record, candidate, RulePack, session을 입력받지 않는다.

## 훼손 방지 쌍 재사용 상태

- operation ↔ plan: `ConsistencyValidator` 검증 유지
- selected target ↔ answer.target: `FinalDecision` pure projection 검증 유지
- active constraint ↔ policy reason: legacy production owner로 유지, new algebra는 shadow
- safeguard ↔ scope/plan: effective blueprint와 validator로 유지
- required information ↔ ask: legacy evaluator가 owner, typed evaluator shadow
- capability unavailable ↔ hold/fallback: available action ablation 유지
- current prompt ↔ history: explicit evidence provenance 유지
- fallback ↔ authorization: 무권한 edge 거부 유지

결론적으로 관계도는 설계 가설로 유효하지만, 공식 계약으로 승격된 항목은 R9와 R11의 구조적 경계에 한정된다. 나머지는 SUPPORTED 또는 UNRESOLVED로 유지한다.
