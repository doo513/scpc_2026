# SCPC 통합 Implementation Master Plan

## Authoritative status

이 파일만 최종 구현 에이전트가 따를 authoritative plan이다. 다음 자료는 근거 또는 이력이며 병렬 계획이 아니다.

- `SCPC_Harness_Rule_Registry_Refactoring_FINAL_REVIEWED.md`: historical requirements
- `SCPC Harness 상호 영향 관계도.md`: audited hypothesis map
- 기존 `STEP*_REPORT.md`, `FINAL_REPORT.md`: source/scorer hash가 일치할 때만 evidence
- 본 디렉터리의 나머지 5개 감사 문서: 이 plan의 근거와 상태 설명

충돌할 경우 이 파일이 우선하며 충돌 문구는 아래 change ledger에서 `SUPERSEDED`로 처리한다.

## 현재 authoritative architecture

```text
Task Input
-> TaskView + Typed Object/Record Facts
-> Deterministic Surface Evidence + Context/Relation Binding
-> legacy semantic candidate path (current sole production owner)
-> frozen FinalDecision
-> locked DecisionProjectionSet
-> production Pure ProjectionCompiler
-> ConsistencyValidator
-> Commit Eligibility
-> AtomicSessionCommitter
-> answer / trace / submission

FixedSLM: KEEP_SHADOW, production influence 0

Typed replacement (shadow until release):
Pre-SLM Candidate
-> exact DomainOperationRulePack
-> BasePlanBlueprint + RequiredRole/Information
-> Pair/Global Constraint + Effect Algebra
-> FinalPlanRequirements + whole-plan Capability
-> CandidateEvaluator + AuthorizedFallback
-> SubDecisionIR/DecisionBundle
```

현재 semantic production owner는 `FinalDecision`이다. typed replacement가 전체 release gate를 통과하기 전까지 두 체계의 결과를 병합하지 않는다. compiler는 의미 owner가 아니다. persistent commit owner는 `AtomicSessionCommitter` 하나다.

## 통합 change ledger

### 변경된 기존 조항

- artifact freshness를 `mtime + hash`에서 `source/data/scorer/artifact content hash + isolated regeneration`으로 변경했다.
- output compiler를 legacy `rules.*` 호출에서 locked projection DTO 기반 `ProjectionCompiler` 호출로 변경했다.
- validation을 runner의 post-commit 단계에서 harness의 pre-commit 단계로 이동했다.
- session/memory write를 live state 직접 변경에서 clone-stage 후 atomic replace로 변경했다.
- ownership registry를 future shadow owner 혼합표에서 current production owner 단일표로 변경했다.
- scorer plan 동률 처리를 공식 notebook과 동일한 strict-first-best로 변경했다.
- evaluation task ID를 직접 읽던 테스트 2건을 synthetic structural fixture로 변경했다.

### 보완 조건으로 대체된 조항

- `SUPERSEDED — FixedSLM을 계속 shadow로 둔다` → Stage 3은 매 current-source run에서 `PROMOTE`, `KEEP_SHADOW`, `REMOVE` 중 정확히 하나를 결정하고 근거를 기록한다.
- `SUPERSEDED — FixedSLM proposal을 향후 production evidence에 연결 가능` → `PROMOTE` 전 production evidence 영향은 반드시 0이다.
- `SUPERSEDED — Step 10 compiler는 shadow-only` → pure projection compiler는 production-active이며 semantic owner가 아니다.
- `SUPERSEDED — Step 11은 validation-before-commit 미연결` → single-answer production lifecycle은 validator 성공 뒤 atomic commit한다.
- `SUPERSEDED — artifact_hash_and_mtime_current` → `artifact_content_hash_current`와 격리 재현 비교를 사용한다.
- `SUPERSEDED — generate_reports와 step12가 각각 candidate manifest를 생성` → `build_manifest.publish_candidate_manifest`만 writer다.
- `SUPERSEDED — future ownership registry가 현 production owner를 나타낸다` → current owner와 planned replacement를 문서·matrix에서 분리한다.
- `SUPERSEDED — official dev 0.9421을 current FinalDecision artifact release의 hard gate로 사용` → current artifact release는 executable structural contract를 따르고, 동일 dev 기준은 typed semantic owner 교체의 별도 promotion gate로 보존한다.

### 삭제된 조항

- 생성 시각이 source보다 늦다는 사실을 freshness 통과 근거로 쓰는 조항
- harness에서 `rules.scope_policy.ScopeCompiler`, `PolicyCompiler`, `rules.plan.PlanCompiler`를 직접 호출하는 조항
- runner가 commit 완료 뒤 `ConsistencyValidator`를 호출하는 조항
- screening task ID 또는 공개 고유 문장으로 test case를 선택하는 조항
- 승격되지 않은 FixedSLM output을 risk/policy evidence에 조용히 합치는 조항
- semantic owner가 둘인 동안 production switch를 허용하는 조항

### 유지된 조항

- 공식 ZIP, schema, dev reference, scorer는 읽기 전용이다.
- task/session ID, 인물명, 장소명, target 이름, 전체 prompt, dev answer, screening 결과, 배열 위치를 answer rule key로 사용하지 않는다.
- surface language rule은 Evidence만 생성하고 answer field를 직접 확정하지 않는다.
- RulePack lookup은 typed exact key만 사용한다.
- hard fact와 current direct evidence는 SLM proposal보다 높은 authority를 가진다.
- compiler는 raw task/record/session을 재해석하지 않는다.
- official dev `0.9421` 진단 기준을 낮추거나 exclusion을 추가하지 않는다. 이 기준은 typed semantic owner 교체의 promotion gate이며 current FinalDecision artifact release의 hard gate는 아니다.
- typed replacement가 release gate를 통과하기 전 legacy semantic path를 삭제하지 않는다.
- schema, consistency, task specificity, metamorphic, official dev, artifact freshness는 서로 다른 gate다.

### 재검증이 필요한 release gate

Current `FinalDecision` artifact release hard gate:

- `REQUIRED_RELEASE_CHECK_IDS`의 정확한 boolean contract 전체 통과
- source/scorer/data hash 하나에 대한 full pytest와 official dev 진단의 동시 실행
- official/local scorer parity, task-specific runtime rule 0건
- projection lock, pure compiler, validation-before-commit, atomic rollback
- submission/schema/manifest/report isolated regeneration byte/content 일치

Typed semantic owner 교체 promotion gate:

- official dev overall `>= 0.9421`, focal `1.0`, target `>= 0.975`, control `>= 0.9917`, content scope `>= 0.975`, policy `>= 0.9643`, plan `>= 0.975`, non-exact `<= 10`
- typed replacement actual-task shadow diff와 unexplained exact regression 0건
- FixedSLM Stage 3 결정 및 recovery/authority gates
- paraphrase, negation, quotation, connector, array permutation, capability ablation
- task-specific source/test/report-generator scan 0건

## Stage 0

- Stage ID: `STAGE-0-CONTRACT-BASELINE-ARTIFACT`
- 목표: 공식 계약, scorer parity, current source/artifact 기준선을 하나의 hash set으로 고정한다.
- 변경하는 의미 축: 평가·freshness만; answer semantics는 변경하지 않는다.
- 입력 contract: 공식 ZIP, local source, existing submission/report/manifest.
- 출력 contract: official-equivalent dev metrics, v2 candidate manifest, stale 판정, reproduction result.
- authoritative owner: scorer는 `local_score.py`; manifest writer는 `publish_candidate_manifest`.
- 재사용 모듈: `run_submission`, `validate_submission`, `build_manifest` hashing.
- 교체 모듈: tuple-max plan tie와 mtime freshness 판정.
- legacy 유지 범위: 이전 artifact는 삭제하지 않고 stale evidence로 분류한다.
- 구현 작업: strict-first tie, canonical dev evaluator, content fingerprint, data/scorer/report hash, isolated regeneration.
- 신규 invariant tests: tie fixture, official dev snapshot, timestamp-independent fingerprint.
- 기존 회귀 테스트: full pytest, schema, screening 700 IDs.
- official dev 검증: current source 진단값을 매 실행 기록한다. `0.9421`은 typed-owner promotion 기준으로 보존하며 current artifact release에는 비차단이다.
- metamorphic·ablation 검증: array/input order invariance.
- 실패 시 rollback: scorer parity patch와 manifest v2를 한 단위로 되돌리되 공식 자산은 변경하지 않는다.
- release gate: scorer snapshot 일치, official schema hash 일치, isolated regeneration 일치.
- 다음 단계 진입 조건: PASS_WITH_BASELINE_DEBT 허용; unexplained score change는 금지.
- 남은 assumption: semantic response server scoring 세부.
- 예상 비용 수준: LOW.
- 현재 상태: `IMPLEMENTED / PASS_WITH_BASELINE_DEBT`.

## Stage 1

- Stage ID: `STAGE-1-ONTOLOGY-OWNERSHIP`
- 목표: current production과 planned replacement의 owner를 혼합하지 않고 필드별 final owner를 하나로 고정한다.
- 변경하는 의미 축: ownership metadata만.
- 입력 contract: runtime call graph와 frozen FinalDecision fields.
- 출력 contract: unique `OWNERSHIP_REGISTRY`.
- authoritative owner: `core/ownership.py`.
- 재사용 모듈: ontology enums, legacy FinalDecision.
- 교체 모듈: future shadow type을 current final owner로 적은 혼합 ownership table.
- legacy 유지 범위: semantic implementation 자체는 변경하지 않는다.
- 구현 작업: execution/response target 분리, disposition, policy reason, projection, commit owner 추가.
- 신규 invariant tests: unique fields, no compiler semantic owner, AtomicSessionCommitter owner.
- 기존 회귀 테스트: ontology/constraints/plan requirements.
- official dev 검증: Stage 0과 동일해야 한다.
- metamorphic·ablation 검증: 없음; metadata stage.
- 실패 시 rollback: owner registry만 복원하되 다음 stage 진입 금지.
- release gate: duplicate field 0, missing owner 0.
- 다음 단계 진입 조건: current call graph와 registry 일치.
- 남은 assumption: replacement promotion 시 owner swap 시점.
- 예상 비용 수준: LOW.
- 현재 상태: `IMPLEMENTED`.

## Stage 2

- Stage ID: `STAGE-2-TYPED-FACT-RECORD-ADAPTER`
- 목표: official task의 object/record를 typed status와 provenance로 한 번만 해석한다.
- 변경하는 의미 축: input normalization.
- 입력 contract: participant-visible task fields.
- 출력 contract: TypedObjectFact, TypedRecordFact, CapabilitySnapshot, session snapshot.
- authoritative owner: `TaskView`와 record adapter registry.
- 재사용 모듈: `facts.py`, `records.py`, `task_view.py`.
- 교체 모듈: raw dict를 downstream에서 반복 해석하는 branch.
- legacy 유지 범위: legacy semantic engine은 typed indexes를 계속 소비한다.
- 구현 작업: invalid/missing/conflicted 상태 보존, provenance, array-order independence.
- 신규 invariant tests: official 820 task parse, permutation, invalid shape.
- 기존 회귀 테스트: typed facts/task view/architecture.
- official dev 검증: Stage 0과 동일.
- metamorphic·ablation 검증: records/objects reverse.
- 실패 시 rollback: production semantics는 그대로 두고 adapter promotion 취소.
- release gate: raw record downstream interpretation 목록 0 또는 명시적 legacy debt.
- 다음 단계 진입 조건: 모든 official shape가 typed parse됨.
- 남은 assumption: unknown future record types.
- 예상 비용 수준: MEDIUM.
- 현재 상태: `IMPLEMENTED_WITH_LEGACY_DEBT`.

## Stage 3

- Stage ID: `STAGE-3-PARSER-FIXED-SLM-EVIDENCE`
- 목표: deterministic surface evidence 경계를 고정하고 FixedSLM의 production 승격 상태를 단일 결정한다.
- 변경하는 의미 축: auxiliary language evidence만.
- 입력 contract: prompt/history typed text spans, pre-SLM candidates, official FixedSLM facade.
- 출력 contract: parser Evidence; FixedSLM은 validated low-authority proposal 또는 영향 0.
- authoritative owner: deterministic parser는 `SurfaceParser`; FixedSLM status는 `manifest/fixed_slm_status.json`.
- 재사용 모듈: `surface_parser.py`, `language_registry.py`, `context_binder.py`, `slm_contract.py`.
- 교체 모듈: connector/keyword에서 answer field로 직접 가는 rule.
- legacy 유지 범위: parser compatibility evidence; FixedSLM은 결정에 따라 분리.
- 구현 작업: clause/quote/negation/correction evidence, ambiguity trigger, proposal schema validation, status report.
- 신규 invariant tests: quote authority, negation binding, paraphrase, invalid output, timeout recovery, authority non-overwrite.
- 기존 회귀 테스트: language registry, prompt security, SLM contract.
- official dev 검증: parser-only baseline과 selected status를 각각 측정.
- metamorphic·ablation 검증: parser-only vs FixedSLM-on paired held-out paraphrases.
- 실패 시 rollback: FixedSLM proposal 폐기 후 parser-only bytes로 복귀.
- release gate: 아래 PROMOTE/KEEP_SHADOW/REMOVE 결정표.
- 다음 단계 진입 조건: status 하나와 evidence hash가 report/manifest에 기록됨.
- 남은 assumption: official timeout/failure contract.
- 예상 비용 수준: HIGH.
- 현재 상태: `KEEP_SHADOW`.

### FixedSLM production 승격 결정표

`PROMOTE`

- 공식 interface와 schema 확인
- parser-only 대비 held-out 일반화 개선을 최소 1건 확인하고 regression 0건
- 공식 dev 회귀 없음
- metamorphic·paraphrase 검증 통과
- hard fact·current direct evidence authority 침해 0건
- timeout·invalid output에서 parser-only submission/answer byte-equivalent 복구
- FixedSLM이 focal, target, control, content scope, policy, plan events를 직접 생성하지 않음

`KEEP_SHADOW`

- facade는 사용할 수 있으나 개선 효과가 확인되지 않음
- 공식 계약이 불명확함
- 회귀 또는 authority 위반이 존재함
- recovery가 아직 입증되지 않음

`REMOVE`

- 공식 interface를 사용할 수 없음
- 출력 계약 검증이 불가능함
- failure recovery를 안전하게 보장할 수 없음

현재 결과는 `KEEP_SHADOW`다. interface는 확인됐지만 held-out 개선과 timeout/invalid-output byte-equivalent recovery가 입증되지 않았다. 승격되지 않은 FixedSLM output은 production EvidenceGraph에 병합하지 않는다.

## Stage 4

- Stage ID: `STAGE-4-CANDIDATE-RULEPACK-BASE-BLUEPRINT`
- 목표: actual task에서 source-bound typed candidate를 만들고 exact RulePack/Blueprint를 조회한다.
- 변경하는 의미 축: domain·operation·role·information candidate representation.
- 입력 contract: Stage 2 facts와 Stage 3 parser evidence.
- 출력 contract: CandidateSet, exact RulePackResolution, BasePlanBlueprint.
- authoritative owner: shadow에서는 RulePackRegistry; production은 gate 전 FinalDecision.
- 재사용 모듈: `rulepacks.py`, `plan_requirements.py`, `context_binder.py`.
- 교체 모듈: legacy ActionCandidate/BlueprintRegistry는 gate 후 교체.
- legacy 유지 범위: official dev shadow comparison 전체 기간.
- 구현 작업: actual candidate factory, no Cartesian product, clause/sub-operation identity, exact key lookup.
- 신규 invariant tests: unsupported key, role boundary, no task ID/name/prompt key.
- 기존 회귀 테스트: rulepack, typed facts, architecture.
- official dev 검증: field-level legacy/new/reference 3-way diff.
- metamorphic·ablation 검증: paraphrase same key, object order, missing role.
- 실패 시 rollback: typed candidate path shadow 유지, production owner 변경 금지.
- release gate: unexplained exact regression 0, task-specific rule 0.
- 다음 단계 진입 조건: all supported actual candidates resolve exactly.
- 남은 assumption: final answer.target mapping.
- 예상 비용 수준: HIGH.
- 현재 상태: `SHADOW_IMPLEMENTED / ACTUAL-TASK PROMOTION BLOCKED`.

## Stage 5

- Stage ID: `STAGE-5-CONSTRAINT-PLAN-CAPABILITY`
- 목표: global/pair constraint effect를 FinalPlanRequirements와 whole-plan capability로 합성한다.
- 변경하는 의미 축: constraint effect와 plan requirement.
- 입력 contract: Stage 4 candidate/RulePack/Blueprint와 typed constraint facts.
- 출력 contract: ConstraintActivationBundle, EffectAlgebraResult, FinalPlanRequirements, CapabilityAssessment.
- authoritative owner: shadow modules; production은 gate 전 legacy EffectiveBlueprint/FinalDecision.
- 재사용 모듈: `constraints.py`, `plan_requirements.py`, capability snapshot.
- 교체 모듈: legacy ConstraintActivator/BlueprintCompiler는 gate 후 교체.
- legacy 유지 범위: all official task parity까지.
- 구현 작업: applicability, idempotence, effect conflict, terminal preservation, capability sequence.
- 신규 invariant tests: pair scope, hard block monotonic, effect permutation, unavailable terminal.
- 기존 회귀 테스트: constraints/plan requirements/safety.
- official dev 검증: policy/scope/plan axes separately.
- metamorphic·ablation 검증: capability removal, constraint removal/addition.
- 실패 시 rollback: shadow results discard.
- release gate: constraint cannot directly choose control; one semantic terminal; no capability bypass.
- 다음 단계 진입 조건: every active effect has plan/policy lineage.
- 남은 assumption: platform action vs internal transform.
- 예상 비용 수준: HIGH.
- 현재 상태: `SHADOW_ONLY`.

## Stage 6

- Stage ID: `STAGE-6-EVALUATOR-AUTHORIZED-FALLBACK`
- 목표: role, information, constraints, capability를 한 evaluator에서 disposition으로 합성하고 authorized fallback만 재평가한다.
- 변경하는 의미 축: candidate state/disposition/fallback selection.
- 입력 contract: Stage 5 completed assessment.
- 출력 contract: CandidateEvaluationResult, CandidateSelection, FallbackResolution.
- authoritative owner: shadow CandidateEvaluationEngine; production은 gate 전 legacy evaluator.
- 재사용 모듈: `candidate_evaluation.py`, `fallbacks.py`.
- 교체 모듈: legacy CandidateEvaluator/AuthorizedFallbackSolver는 gate 후 교체.
- legacy 유지 범위: selection parity와 official dev gate까지.
- 구현 작업: actual candidate set evaluation, hard issue priority, explicit authorization, destination re-evaluation.
- 신규 invariant tests: rank cannot bypass block, no fallback on similarity, multi-choice ask.
- 기존 회귀 테스트: candidate/fallback/generalization.
- official dev 검증: target/control and reason diff.
- metamorphic·ablation 검증: missing slot, revoked consent, capability loss.
- 실패 시 rollback: production selection unchanged.
- release gate: no unauthorized automatic fallback, no new exact mismatch.
- 다음 단계 진입 조건: selection owner swap candidate prepared but not activated.
- 남은 assumption: official fallback edge inventory.
- 예상 비용 수준: HIGH.
- 현재 상태: `SHADOW_ONLY`.

## Stage 7

- Stage ID: `STAGE-7-DECISION-LOCK-PROJECTION`
- 목표: selected meaning을 immutable lock으로 고정하고 raw-free projection을 만든다.
- 변경하는 의미 축: output lineage; semantics는 변경하지 않는다.
- 입력 contract: current frozen FinalDecision 또는 future CandidateEvaluationResult.
- 출력 contract: DecisionProjectionSet와 lock digest; future SubDecisionIR/Bundle.
- authoritative owner: current adapter는 `FinalDecisionProjectionBuilder`; meaning owner는 FinalDecision.
- 재사용 모듈: `decision_ir.py` DTO, `production_projection.py`.
- 교체 모듈: full typed promotion 시 migration adapter를 SubDecisionIRBuilder로 교체.
- legacy 유지 범위: adapter는 typed semantic gate까지.
- 구현 작업: scope/policy/plan projection lock, target separation diagnostics.
- 신규 invariant tests: lock present, stale mutation rejection, raw-free boundary.
- 기존 회귀 테스트: decision IR/projection/lifecycle.
- official dev 검증: output byte-equivalence.
- metamorphic·ablation 검증: compiler call order and unrelated raw context.
- 실패 시 rollback: legacy compilers를 rollback point로 보존하되 production release 중단.
- release gate: screening submission byte-identical, dev identical, lock lineage valid.
- 다음 단계 진입 조건: validator consumes compiled output before any commit.
- 남은 assumption: multi-decision aggregate.
- 예상 비용 수준: MEDIUM.
- 현재 상태: `SINGLE-DECISION PRODUCTION ADAPTER IMPLEMENTED; FULL BUNDLE SHADOW`.

## Stage 8

- Stage ID: `STAGE-8-VALIDATION-ATOMIC-COMMIT`
- 목표: 검증 전 persistent side effect를 제거한다.
- 변경하는 의미 축: lifecycle only.
- 입력 contract: completed public answer, trace, current session/memory.
- 출력 contract: validated answer and all-or-nothing committed state.
- authoritative owner: validator는 `ConsistencyValidator`; commit은 `AtomicSessionCommitter`.
- 재사용 모듈: MemoryStore, session update semantics.
- 교체 모듈: runner post-commit validation.
- legacy 유지 범위: multi-decision `session_overlay.py` shadow.
- 구현 작업: clone, stage, validate, atomic replace, branch isolation.
- 신규 invariant tests: injected validator failure changes no state.
- 기존 회귀 테스트: safety/session/regression.
- official dev 검증: identical.
- metamorphic·ablation 검증: branch siblings and failed commit.
- 실패 시 rollback: staged copies discard, live state unchanged.
- release gate: validator source order precedes commit; rollback test pass.
- 다음 단계 진입 조건: pure compiler artifact included in validator input.
- 남은 assumption: partial multi-decision commit.
- 예상 비용 수준: MEDIUM.
- 현재 상태: `IMPLEMENTED`.

## Stage 9

- Stage ID: `STAGE-9-PURE-COMPILER-END-VALIDATOR`
- 목표: scope/policy/plan을 projection DTO에서만 직렬화하고 terminal consistency를 검증한다.
- 변경하는 의미 축: serialization only.
- 입력 contract: locked ScopeProjection, PolicyProjection, PlanProjection.
- 출력 contract: official content_scope, policy, plan_events.
- authoritative owner: `ProjectionCompiler`는 serialization owner; semantic owner 아님.
- 재사용 모듈: projection compilers, schema validator.
- 교체 모듈: legacy rules compilers의 production imports.
- legacy 유지 범위: files remain rollback-only until final release.
- 구현 작업: production_active, max 18, exact args order preservation, lineage lock.
- 신규 invariant tests: no semantic imports, deterministic output, plan limit.
- 기존 회귀 테스트: architecture/projection/full pytest.
- official dev 검증: identical.
- metamorphic·ablation 검증: call-order and raw-context independence.
- 실패 시 rollback: switch harness import back as one reversible unit.
- release gate: output bytes identical and no raw dependency.
- 다음 단계 진입 조건: artifact publication on current source hash.
- 남은 assumption: none for single answer serialization.
- 예상 비용 수준: LOW.
- 현재 상태: `IMPLEMENTED`.

## Stage 10

- Stage ID: `STAGE-10-VERTICAL-SLICE-RELEASE`
- 목표: current lifecycle artifact release와 typed semantic owner switch를 분리해 각각 최종 판정한다.
- 변경하는 의미 축: artifact publication 및 production owner switch를 별도 상태로 관리.
- 입력 contract: one immutable source hash, official assets, all stage reports.
- 출력 contract: `PROMOTE_CURRENT_ARTIFACT`/`BLOCK_CURRENT_ARTIFACT`와 `PROMOTE_TYPED_OWNER`/`KEEP_TYPED_SHADOW`를 각각 기록.
- authoritative owner: release gate result와 `OWNERSHIP_REGISTRY`.
- 재사용 모듈: all validators, scorer, artifact publisher.
- 교체 모듈: typed-owner promotion gate 통과 시에만 legacy semantic engine.
- legacy 유지 범위: typed replacement가 모든 gate를 통과할 때까지.
- 구현 작업: full pytest, official dev, specificity, metamorphic, schema, reproduction, FixedSLM status aggregation.
- 신규 invariant tests: source hash stable across gate, one manifest producer, one owner per field.
- 기존 회귀 테스트: complete suite와 executable release-check contract assertion.
- official dev 검증: 전체 120건을 진단하고 threshold를 낮추지 않는다. current artifact release에는 비차단, typed-owner 교체에는 차단이다.
- metamorphic·ablation 검증: complete matrix.
- 실패 시 rollback: current FinalDecision semantic owner 유지; projection/lifecycle improvements는 독립 gate를 통과했으면 유지.
- release gate: current artifact는 executable structural hard gate 전체 true. typed-owner 교체는 dev·shadow·authority promotion gate까지 별도 통과.
- 다음 단계 진입 조건: 없음; terminal stage.
- 남은 assumption: unresolved 항목이 production behavior를 좌우하면 release 금지.
- 예상 비용 수준: HIGH.
- 현재 상태: `CURRENT_ARTIFACT_CANDIDATE_READY / KEEP_TYPED_SHADOW` — current artifact는 structural release·freshness 검증 대상으로 진행할 수 있다. current overall `0.9185 < 0.9421`이므로 typed semantic owner는 production으로 승격하지 않는다.

## 최종 구현 에이전트 규칙

1. 이 plan과 충돌하는 이전 문구를 다시 활성화하지 않는다.
2. stage report의 `generated_at`만 보고 current라고 판단하지 않는다.
3. FixedSLM status가 PROMOTE가 아니면 proposal을 production answer 또는 evidence에 병합하지 않는다.
4. typed-owner official dev promotion gate 실패를 테스트 threshold 변경, reference 수정, task-specific rule, exclusion로 해결하지 않는다.
5. typed replacement가 blocked인 동안 current FinalDecision과 replacement decision을 혼합하지 않는다.
6. 완료 보고는 코드 작성, unit pass, invariant pass, official dev pass, release pass를 구분한다.
