# 재사용 및 Migration Matrix

| 영역/모듈 | 현재 분류 | 재사용 결정 | contract 변경 | legacy 유지 기간 | 삭제/승격 조건 | release gate |
| --- | --- | --- | --- | --- | --- | --- |
| `run_submission.py` | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | validation을 harness precommit으로 이동, runner는 ordering/write owner | 계속 | 없음 | schema, 700 IDs, deterministic bytes |
| `harness.py` | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | projection lock → validator → commit 순서 | 계속 | 없음 | lifecycle order invariant |
| `TaskView` | PRODUCTION_ACTIVE | REUSE_AS_IS | participant-visible field boundary 유지 | 계속 | 없음 | prompt-security tests |
| `facts.py` / `records.py` | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | typed provenance를 replacement candidate input으로 확대 | legacy semantic 전환까지 | raw record 재해석 0건 | typed fact/permutation |
| `surface_parser.py` | PARTIALLY_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | connector는 relation evidence만 생성 | 계속 | direct field rule 발견 시 교체 | quotation/negation/paraphrase |
| `language_registry.py` | PARTIALLY_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | surface→Evidence only | 계속 | keyword→answer rule 0건 | language registry scan |
| `evidence.py` / `evidence_graph.py` | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | FixedSLM proposal와 authority class 분리 | 계속 | FixedSLM PROMOTE 전 merge 금지 | authority/metamorphic |
| `context_binder.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | pre-SLM candidate identity·clause lineage output | Stage 3 gate 이후 | held-out no-regression | Stage 3 |
| `state.py` | PRODUCTION_ACTIVE | KEEP_AS_LEGACY_UNTIL_GATE | typed candidate seed adapter 필요 | Stage 4~6 통과까지 | replacement byte/field gate 통과 | official dev |
| `decision.py` | PRODUCTION_ACTIVE | KEEP_AS_LEGACY_UNTIL_GATE | owner는 현재 FinalDecision 하나로 명시 | Stage 10 promotion까지 | replacement score·invariant 통과 | vertical slice |
| `blueprint.py` | PRODUCTION_ACTIVE | KEEP_AS_LEGACY_UNTIL_GATE | exact RulePack blueprint와 1:1 diff 필요 | Stage 5 통과까지 | 모든 semantic terminal parity | plan metamorphic |
| `rulepacks.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | actual candidate adapter와 exact key만 허용 | legacy 병행 shadow | official dev 무회귀, task-specific 0건 | Stage 4 |
| `plan_requirements.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | official action/internal transform assumption 유지 | legacy 병행 shadow | whole-plan capability parity | Stage 5 |
| `constraints.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | typed facts만 입력, language parsing 금지 | legacy 병행 shadow | effect lineage·idempotence | Stage 5 |
| `candidate_evaluation.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | actual task candidate factory 필요 | legacy 병행 shadow | rank가 hard block 우회하지 않음 | Stage 6 |
| `fallbacks.py` | SHADOW_ONLY | REWIRE_TO_PRODUCTION | authorized edge source 필수 | legacy 병행 shadow | 무권한 fallback 0건 | Stage 6 |
| `decision_ir.py` projection DTO | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | FinalDecision migration adapter 사용 | current | full bundle promotion 후 adapter 삭제 검토 | lock/purity |
| `decision_ir.py` SubDecisionIR/Bundle | SHADOW_ONLY | REWIRE_TO_PRODUCTION | aggregate/response-target assumption 해결 필요 | current adapter 유지 | single/multi official gate | Stage 7 |
| `production_projection.py` | PRODUCTION_ACTIVE | REUSE_AS_IS | raw-free lock boundary | full migration까지 | full IR builder가 대체할 때 | compiler parity |
| `projection_compilers.py` | PRODUCTION_ACTIVE | REUSE_AS_IS | semantic dependency 금지 | 계속 | 없음 | pure compiler tests |
| `rules/plan.py`, `rules/scope_policy.py` | LEGACY_UNREACHABLE | DELETE_AFTER_MIGRATION | 없음 | rollback window | full release + one clean reproduction | Stage 10 |
| `session_state.py` | PRODUCTION_ACTIVE | REUSE_WITH_CONTRACT_CHANGE | clone/stage/atomic replace | 계속 | 없음 | validation failure rollback |
| `session_overlay.py` | SHADOW_ONLY | KEEP_AS_LEGACY_UNTIL_GATE | multi-decision partial commit 공식 계약 필요 | indefinite until resolved | contract + rollback release pass | Stage 8 |
| `slm_contract.py` | SHADOW_ONLY | KEEP_SHADOW | official facade adapter·timeout wrapper 없음 | current | PROMOTE gate 전체 통과 또는 REMOVE | Stage 3 FixedSLM |
| `shadow_validation.py` | SHADOW_ONLY | REUSE_AS_IS | replacement promotion audit | full release까지 | full production validator가 동등 검증 | Stage 10 |
| `build_manifest.py` | PRODUCTION_ACTIVE tooling | REUSE_WITH_CONTRACT_CHANGE | one writer, v2 content fingerprint | 계속 | 없음 | artifact reproduction |
| `validate_artifacts.py` | PRODUCTION_ACTIVE tooling | REUSE_WITH_CONTRACT_CHANGE | mtime 제거, isolated regeneration | 계속 | 없음 | content/hash gate |
| `step1`~`step12` reports | STALE_EVIDENCE 가능 | KEEP_AS_LEGACY_UNTIL_GATE | source/scorer hash 일치 시에만 증거 | current-source report 생성까지 | hash 불일치 시 stale 유지 | artifact gate |

## Migration 원칙

1. legacy semantic owner와 typed replacement owner를 같은 answer에 병합하지 않는다.
2. replacement stage는 실제 official task를 shadow로 실행하고 field-level diff를 기록한다.
3. score가 낮아도 shadow 구현은 보존할 수 있으나 production owner registry는 바꾸지 않는다.
4. production switch는 source hash 하나에 대해 tests, official dev, metamorphic, specificity, schema, artifact reproduction을 함께 통과할 때만 수행한다.
5. rollback은 이전 owner registry와 production entrypoint를 복원할 수 있는 변경 단위로 유지한다.

## FixedSLM migration 결정

현재는 `KEEP_SHADOW`다. `PROMOTE`가 되더라도 FixedSLM은 auxiliary proposal producer일 뿐이며 focal, target, control, content scope, policy, plan events의 final owner가 될 수 없다. `REMOVE`는 official interface 또는 output/recovery 계약을 검증할 수 없을 때 선택한다.
