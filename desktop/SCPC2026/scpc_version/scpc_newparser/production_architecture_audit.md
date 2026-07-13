# Production Architecture 감사

## 실제 production call graph

```text
run_submission.run_tasks
  -> participant_task_view
  -> session/turn 정렬 및 sibling branch 격리
  -> FinalHarness.answer_task
       -> TaskView
       -> StateAssembler.assemble
            -> typed object/record index
            -> EvidenceGraph / deterministic language evidence
            -> RelationGraph / focal / operation / target candidates
       -> DecisionEngine.decide
            -> legacy ActionTargetPair/CandidateEvaluator
            -> legacy constraints/fallback
            -> FinalDecisionBuilder -> frozen FinalDecision
       -> ProductionProjectionPipeline.compile
            -> FinalDecisionProjectionBuilder (lock digest)
            -> DecisionProjectionSet
            -> ProjectionCompiler (scope/policy/plan)
       -> ResponseBuilder
       -> ConsistencyValidator.validate_or_warn
       -> staged session + staged MemoryStore
       -> AtomicSessionCommitter.commit
  -> submission payload validation
  -> write_submission / write_traces / consistency report
```

근거: `run_submission.py:33-100`, `harness.py:31-117`, `core/production_projection.py:28-118`.

## 실제 commit 순서

1. answer와 trace를 메모리에서 완성한다.
2. public answer를 schema·semantic consistency validator에 전달한다.
3. validator가 성공한 뒤 session과 memory clone을 만든다.
4. clone에 write를 적용한다.
5. `AtomicSessionCommitter`가 session과 MemoryStore를 함께 교체한다.
6. validator 실패 시 persistent state는 전혀 변경되지 않는다.

`tests/test_production_lifecycle.py`가 injected validation failure에서 session과 memory snapshot 불변을 검증한다.

## compiler 입력과 소유권

production compiler 입력은 `DecisionProjectionSet`뿐이다. projection builder만 frozen `FinalDecision`을 읽으며 prompt, visible history, raw record, TaskView, candidate registry, session을 받지 않는다.

| 의미 | final owner | compiler 역할 |
| --- | --- | --- |
| focal/domain/operation/target/control | `FinalDecision` | 접근하지 않음 |
| disclosure | `FinalDecision` | `ScopeProjection` 직렬화 |
| public policy | `FinalDecision` | `PolicyProjection` 직렬화 |
| plan steps | `FinalDecision` | 순서·verb·target·args 보존 |
| persistent commit | `AtomicSessionCommitter` | 관여하지 않음 |

전체 owner 목록은 `core/ownership.py`에 한 필드당 한 행으로 고정한다.

## module 분류

| module/group | classification | runtime reachability | output ownership | 처리 |
| --- | --- | --- | --- | --- |
| `run_submission.py` | PRODUCTION_ACTIVE | submission entrypoint | task ordering, CSV envelope | 유지 |
| `harness.py` | PRODUCTION_ACTIVE | direct | orchestration only | 유지·precommit 순서 고정 |
| `core/task_view.py`, `facts.py`, `records.py` | PRODUCTION_ACTIVE | StateAssembler 입력 | typed input boundary | 재사용 |
| `core/surface_parser.py`, `language_registry.py`, `evidence*.py` | PARTIALLY_ACTIVE | evidence path | evidence proposal | direct answer owner 금지 |
| `core/state.py`, `core/decision.py`, `core/blueprint.py` | PRODUCTION_ACTIVE | direct | current semantic owner | legacy until typed replacement gate |
| `core/production_projection.py` | PRODUCTION_ACTIVE | harness direct | lock/projection boundary | authoritative |
| `core/projection_compilers.py` | PRODUCTION_ACTIVE | projection pipeline | serialization only | authoritative compiler |
| `core/session_state.py` | PRODUCTION_ACTIVE | harness direct | memory and atomic commit | authoritative commit owner |
| `rules/response.py` | PRODUCTION_ACTIVE | harness direct | optional response fields | 유지 |
| `rules/plan.py`, `rules/scope_policy.py` | DELETE_AFTER_MIGRATION | harness에서 미도달 | 과거 compiler | full release 후 삭제 |
| `core/rulepacks.py`, `plan_requirements.py`, `constraints.py` | SHADOW_ONLY | stage/tests | typed semantic candidate spec | official dev gate 전 비활성 |
| `core/candidate_evaluation.py`, `fallbacks.py` | SHADOW_ONLY | stage/tests | replacement evaluator | official dev gate 전 비활성 |
| `core/decision_ir.py` full SubDecisionIR/Bundle | SHADOW_ONLY | stage/tests; projection DTO type만 production 사용 | multi-decision lock | aggregate contract 전 비활성 |
| `core/session_overlay.py` | SHADOW_ONLY | stage/tests | speculative multi-decision state | partial commit contract 전 비활성 |
| `core/slm_contract.py` | SHADOW_ONLY | tests/stage | proposal validation contract | FixedSLM KEEP_SHADOW |
| `core/shadow_validation.py` | SHADOW_ONLY | final gate synthetic slice | typed replacement cross-check | 유지 |

## duplicated owner 감사

- scope/policy/plan compiler: production harness에서 legacy `rules.*` imports를 제거해 `ProjectionCompiler` 하나만 호출된다.
- candidate manifest: `build_manifest.publish_candidate_manifest`만 writer다. `generate_reports.py`와 `step12_gate.py`는 동일 publisher를 호출한다.
- semantic engine: current production은 legacy `FinalDecision`; typed RulePack/evaluator는 `production_active=False`다. 두 결과가 동시에 answer에 병합되지 않는다.
- FixedSLM: production source에 client 또는 `slm_contract` import가 없고 status가 `production_influence=false`다.

## artifact freshness

기존 판정의 mtime 비교는 `SUPERSEDED`다. 현 validator는 다음을 비교한다.

- source tree SHA-256
- official data 3종 SHA-256
- official ZIP SHA-256
- local scorer SHA-256
- submission byte SHA-256
- 각 report content SHA-256
- FixedSLM status content SHA-256
- manifest 자체의 timestamp-independent content fingerprint
- 격리 재생성한 submission bytes와 dev metric

`generated_at`은 정보 필드이며 stale 판정에 사용하지 않는다.

## 금지된 task-specific 처리 검색

- production code에 dev/screening task ID 분기 없음
- production code에 공개 prompt 전체 문장 lookup 없음
- answer/reference lookup은 scorer와 diagnostic report에만 존재하며 production answer 생성에 연결되지 않음
- `tests/test_generalization.py`에 있던 screening task ID 2건은 구조적 synthetic fixture로 교체함
- 인물·target 이름 기반 production answer exception 없음
- object/record 입력 배열 permutation 회귀 검증 유지

task ID는 trace provenance와 submission key로는 사용되지만 의미 판정 key로 사용되지 않는다.

## 현재 release 상태

- output projection migration: 구현 및 production 연결
- validation-before-commit: 구현 및 production 연결
- atomic session/memory commit: 구현 및 production 연결
- official scorer parity: 구현 (`0.8186`)
- FixedSLM: `KEEP_SHADOW`
- full typed semantic pipeline promotion: 미실행
- official dev hard gate: 실패 (`0.8186 < 0.9421`)

따라서 현재 submission은 재현 가능하고 schema-valid하지만 typed semantic replacement의 production 승격 근거는 없다.
