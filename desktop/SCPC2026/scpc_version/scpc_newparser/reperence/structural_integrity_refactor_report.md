# SCPC 구조 무결성 및 Anti-Reward-Hacking 감사 보고서

- 기준일: 2026-07-12
- 대상: `/mnt/c/Users/doo33/Desktop/scpc_newparser`
- 평가 원칙: dev 점수는 성공 기준에서 완전히 제외
- 현재 source tree SHA-256: `fa0b35993b05f68c5d73dc76e7b5f4627d09d79e305c3f33ce375d8e5a035de7`
- 구조 검증용 screening 산출물 SHA-256: `e93a3eed8bc9bb6d4f124d1c77bb817af70dadea67806b30921d00988622076e`

## 1. 결과 요약

기존 `0.9450` 후보에는 task ID 직접 조회는 없었지만, dev에서 관찰된 조합을 output 계약처럼 되먹임하는 Answer-Fitting 경로가 존재했다. 핵심은 다음 두 경로다.

1. `_plan_projection`이 `amend`라는 이유만으로 실제 domain action을 무시하고 모든 계획을 `read -> redact -> dispatch`로 바꿨다.
2. `_uses_canonical_plan`이 그 잘못된 projection의 verb를 다시 `final_plan_capabilities`로 지정해 Blueprint 기대값을 덮어썼다.

`consistency.py`의 `canonical_amend` 완화는 이어서 Blueprint terminal과 duration 검사를 면제했다. 결과적으로 projection이 계약을 위반하고, projection 자신의 출력으로 계약을 덮어쓰고, validator가 덮어쓴 값을 확인하는 순환 구조가 형성됐다.

이 우회와 인접 Answer-Fitting 경로를 제거했다. strict validator는 다시 warning이나 canonical 예외 없이 실패하도록 바뀌었고, screening 700건은 현재 strict 경로로 완주한다. 다만 미지 속성의 민감도 자체를 동적으로 판단할 공식 metadata 계약은 아직 없으므로 범용 구조가 완성됐다고 판정하지 않는다.

## 2. 단계 1 — strict 전환 및 오류 재현

### 제거한 validator 완화

- schema 예외를 다른 `ValueError`로 감싸던 catch 제거
- historical focal의 current-object 검사 면제 제거
- unavailable capability를 expected plan에서 제거하던 filtering 제거
- `canonical_amend`에 의한 Blueprint terminal 검사 면제 제거
- `canonical_amend`에 의한 duration effect 검사 면제 제거
- `force_summary`를 redaction으로 대신 통과시키던 대체 조건 제거
- 이름 기반 canonical scope guard whitelist 제거
- scope provenance warning을 hard error로 승격
- API를 `validate_or_warn`에서 `validate_strict`로 변경하고 warning 상태 제거

### 실제 전체 파이프라인 첫 오류

strict 전환 직후 screening 진입점은 다음 오류에서 중단됐다.

```text
ValueError: exclusion 'numeric_value' has no focal-field provenance
```

이는 기존 disclosure projection이 focal에 존재하는 필드를 계산한 것이 아니라, focal type과 정책 조합에 따라 정해진 제외 필드 목록을 삽입했음을 증명한다. 전체 stack은 `reperence/strict_runtime_error_trace.txt`에 보존했다.

### Blueprint와 plan projection의 직접 오류

temporary toggle 입력을 독립 실행한 결과는 다음과 같다.

```text
ValueError: resolved plan diverges from final capability contract:
expected=('read', 'verify', 'toggle')
emitted=('read', 'redact', 'dispatch')
```

#### 인과관계

```text
temporary override
  -> ConstraintSeverity.AMEND + LIMIT_DURATION
  -> toggle EffectiveBlueprint
       capabilities = read, verify, toggle
       terminal = toggle
       duration = 2h
  -> FinalDecisionBuilder._plan_projection
       control == amend 분기가 action을 무시
       emitted = read, redact, dispatch
  -> _uses_canonical_plan
       emitted verb를 final_plan_capabilities로 재지정
  -> ConsistencyValidator.canonical_amend
       terminal=toggle 부재와 duration 부재를 면제
  -> 잘못된 projection이 자기 자신을 정당화
```

이 구조는 feedback loop가 아니라 contract laundering에 가깝다. Blueprint가 plan의 계약이어야 하지만, 실제로는 plan이 계약을 다시 썼기 때문이다.

### 정공법 수정

- `_uses_canonical_plan`을 삭제했다.
- `final_plan_capabilities`는 항상 selected `EffectiveBlueprint.capabilities_for(disposition)`에서만 온다.
- `amend`의 generic `read -> redact -> dispatch` 분기를 삭제했다.
- toggle amend는 `read -> verify -> toggle(duration=2h)`를 보존한다.
- dispatch redaction만 dispatch Blueprint의 `read -> redact -> dispatch`를 사용한다.
- share-boundary record가 selected dispatch action을 update plan으로 바꾸던 후단 재해석을 삭제했다.
- 필수 capability가 없으면 plan event를 조용히 버리지 않고 즉시 `ValueError`를 발생시킨다.

수정 후 동일 temporary toggle acceptance test는 strict validator를 통과한다.

## 3. 단계 2 — 하드코딩 scope 분기 제거

### 실제 적용

`_safe_scope_mode`의 focal type, record code, prompt evidence count 분기 트리를 삭제했다. 현재 함수가 사용하는 authority는 다음뿐이다.

1. selected candidate의 active `HARD` constraint
2. finalized control
3. compiled `EffectiveBlueprint.scope_mode`

HARD가 활성인데 control이 hold가 아니면 즉시 실패한다. hold와 ask는 `none`이다. amend는 compiled blueprint effect가 없으면 실패한다. 그 외 mode는 Blueprint에서 그대로 projection한다.

`_disclosure_projection`의 `file`, `personal_note`, `rrn`, `doctor_note`, `card_number` 직접 비교도 제거했다. 제한 mode에서는 focal이 선언한 `contains`/`fields` 전체를 provenance 있는 제외 집합으로 사용한다. 따라서 새로운 필드명 자체는 소스 수정 없이 보존·차단할 수 있다.

### 최종 목표: Abstracted Rule Matrix

현재 구현은 branch 제거 단계이며, 다음 matrix metadata 계약은 아직 구현되지 않았다.

```text
DataProperty
  classification: PUBLIC | INTERNAL | RESTRICTED | SECRET | UNKNOWN
  credential: boolean
  personally_identifying: boolean
  raw_allowed: boolean
  summary_allowed: boolean
  redaction_supported: boolean
  provenance: FactRef

Context
  operation_class: DISCLOSURE | LOCAL_MUTATION | EXTERNAL_MUTATION
  target_boundary: LOCAL | TRUSTED | EXTERNAL | UNKNOWN
  authority: CONFIRMED | PENDING | DENIED | UNKNOWN
  consent: GRANTED | WITHDRAWN | UNKNOWN

RuleEffect
  severity: HARD | CLARIFY | AMEND
  permitted_modes: set[DisclosureMode]
  required_capabilities: set[Capability]
  provenance: set[FactRef]
```

의사코드는 다음과 같다.

```text
facts = TypedFactAdapter.parse(task)
properties = facts.data_properties
context = facts.execution_context

constraints = ConstraintCompiler.activate(properties, context)

if any(c.severity == HARD for c in constraints):
    disposition = BLOCKED
    permitted_modes = {NONE}
else:
    permitted_modes = base_blueprint.permitted_modes
    for constraint in constraints:
        permitted_modes &= constraint.permitted_modes

if any(p.classification == UNKNOWN for p in outbound(properties)):
    disposition = BLOCKED
    permitted_modes = {NONE}

effective_blueprint = BlueprintCompiler.apply(
    base_blueprint,
    constraints,
    permitted_modes,
)

plan = PlanCompiler.compile(
    effective_blueprint,
    disposition,
    available_capabilities,
)

assert plan.verbs == effective_blueprint.capabilities_for(disposition)
assert projection.scope.mode in effective_blueprint.permitted_modes
assert every excluded field has property provenance
```

`SUMMARY`와 `REDACTED`는 항상 한쪽이 더 안전하다고 가정하지 않는다. 각 property가 허용하는 mode 집합을 교집합으로 결합한다. 빈 교집합은 `HARD -> NONE`이다.

### `financial_ledger × account_password` 구조 증명

최종 matrix에서는 문자열 이름을 보지 않는다.

```text
financial_ledger                    ignored as an object-name condition
account_password metadata:
  classification = SECRET
  credential = true
  raw_allowed = false
  summary_allowed = false
  redaction_supported = false
target_boundary = EXTERNAL
```

credential과 external boundary의 matrix row가 `severity=HARD`, `permitted_modes={NONE}`을 생성한다. 새 이름을 registry에 추가하지 않아도 property vector가 같으면 동일 결과가 나온다.

metadata가 아예 없다면 `classification=UNKNOWN`이 되고 fail-closed row가 동일하게 `HARD/NONE`을 생성한다. 따라서 안전성은 유지된다. 다만 공식 입력에 metadata가 없으면 “summary가 허용되는지” 같은 최적 의미를 알아낼 수는 없다. 이는 알고리즘 문제가 아니라 입력 정보 부재이며 임의 문자열 추론으로 메우면 다시 Answer-Fitting이 된다.

현재 실제 synthetic 실행 결과는 다음과 같다.

```json
{
  "control": "proceed",
  "content_scope": {
    "mode": "summary",
    "excluded_fields": ["account_password"]
  },
  "plan_verbs": ["read", "summarize", "dispatch"],
  "active_constraints": []
}
```

raw field는 동적으로 제외됐지만 `HARD` constraint는 생성되지 않았다. 따라서 목표 matrix가 아직 필요하다는 반증이다.

## 4. 단계 3 — AST 사각지대 및 우회 감사

### 스캔 범위 확장

기존 `core/*.py`, `rules/*.py`, `harness.py` 범위에서 다음으로 확장했다.

```text
root/*.py
core/**/*.py
rules/**/*.py
utils/**/*.py
```

- 검사 파일: 69개
- authoritative runtime 분류: 43개
- 포함 확인: `run_submission.py`, `local_score.py`, `utils/io.py`, `utils/diff.py`, `utils/report.py`
- official task ID literal 검사
- official session ID literal 검사
- official full prompt literal 검사
- `task_id`/`session_id` 기반 AST branch 검사
- 알려진 ID prefix 및 answer-map marker 검사

### 결과

authoritative runtime hit는 0건이다.

- `run_submission.py`의 `session_id`는 session state 분리와 turn ordering에만 사용된다.
- `task_id`는 output map의 필수 key로만 사용된다.
- `local_score.py`는 prediction/reference join을 위해 task ID를 사용하지만 production에서 import되지 않는다.
- `utils/diff.py:41`의 ID branch는 두 artifact의 공통 answer를 정렬하는 report-only 코드다.
- `core`, `rules`, `harness.py`, `run_submission.py`는 `local_score`, `official_scorer`, `analyze_dev_errors`, `utils.diff`, `utils.report`를 import하지 않는다.
- `utils/io.py`의 `dev_answers.json` 문자열은 official archive 완전성/hash 검사용 파일 registry이며 answer decision을 읽지 않는다.
- scanner 자체의 `final_dev_` 문자열은 `release_gate.py`와 legacy `step12_gate.py`의 탐지 규칙 정의로 분리 보고된다.

직접적인 task/session lookup hack은 없었다. 그러나 ID lookup보다 더 은밀한 semantic condition fitting은 checkpoint delta 비교에서 확인됐다.

### 제거한 semantic Answer-Fitting 경로

- missing memory인데 특정 record 조합이면 `InformationStatus.COMPLETE`로 바꾸던 `safe_visible_fallback`
- memory rejection 후에도 rejected target을 유지하고 reconfirmation slot만 붙이던 경로
- clarification 문구가 있으면 알려진 health `HARD` constraint를 `CLARIFY + redaction`으로 낮추던 경로
- enterprise/ops recall을 근거 없이 `AMEND`로 자동 변환하던 경로
- local boundary의 특정 세 record code 조합을 자동 redaction amend로 바꾸던 경로
- 모든 amend action을 dispatch plan으로 바꾸던 경로
- scope와 policy에서 focal type 및 dev에 등장한 field-name 목록을 직접 비교하던 경로

이 변경들은 task ID를 사용하지 않았지만, 누락 정보·HARD severity·selected action의 의미를 덮어썼으므로 구조적으로는 Answer-Fitting이다.

## 5. 검증 결과

### 구조 검증

- screening 700건 strict pipeline: 성공
- 구조 검증용 submission: `reperence/structural_screening_submission.csv`
- strict acceptance/regression: `247 passed, 1 deselected`
- 전체 pytest: `247 passed, 1 failed`
- 유일한 실패: dev score hard gate
- Ruff: 통과
- expanded AST audit: authoritative runtime hit 0건
- external repository dependency: 추가 없음
- FixedSLM production influence: 변경 없음

dev diagnostic은 `0.8523`이지만 본 태스크의 성공·실패 판단에는 사용하지 않았다.

### artifact freshness

기존 `submission.csv`와 `candidate_manifest.json`은 source hash `23c090...`에 대한 `0.9450` 후보이며 현재 source `fa0b35...`와 일치하지 않는다. `validate_artifacts.py`는 다음과 같이 fail closed했다.

```text
ValueError: candidate manifest source hash is stale
```

따라서 이전 `RELEASE_READY` 산출물을 현재 strict 코드의 authoritative evidence로 사용하지 않는다. 구조 검증용 submission은 release 후보가 아니라 별도 진단 산출물이다.

## 6. 자가 채점

### Criteria A — 미지 데이터에 적용 가능한 범용 규칙인가?

`No`.

screening 700건은 성공했고 새 필드명 `account_password`도 소스 수정 없이 제외됐다. 그러나 property classification metadata가 없어서 해당 값이 `HARD`인지 `SUMMARY 허용`인지 동적으로 확정하지 못했다. 이름 비의존 처리와 의미 일반화는 다른 문제다.

`Yes`로 바꾸기 위한 gate:

- authoritative `DataProperty` metadata 계약
- UNKNOWN fail-closed 규칙
- object/field 이름 치환 metamorphic test
- 기존에 없는 property vector 생성 test
- matrix row coverage와 provenance test

### Criteria B — validator 기준을 낮추지 않고 모든 결정을 합법적으로 통과시키는가?

`No`.

현재 공식 dev/screening에서 생성된 decision은 strict 경로를 통과한다. 그러나 historical focal은 current object authority로 materialize되지 않아 strict validator가 거부하며, 필수 `read` capability가 없는 blocked plan도 합법적인 대체 Blueprint를 만들지 못하고 fail closed한다. validator를 낮추지 않은 것은 맞지만 모든 유효 입력을 처리한다고 증명할 수 없다.

`Yes`로 바꾸기 위한 gate:

- current/historical을 함께 표현하는 typed object authority
- blocked disposition용 capability-aware Blueprint
- `PlanCompiler`가 Blueprint graph만 소비하도록 action branch 제거
- 모든 emitted verb, terminal, effect parameter의 exact contract test

### Criteria C — `severity == HARD`를 동적으로 완벽히 감지하는가?

`No`.

현재 등록된 `ActiveConstraint(HARD)`는 scope projection에서 반드시 hold/none으로 강제된다. clarification이 health HARD를 낮추던 경로도 제거했다. 하지만 `financial_ledger × account_password`에서 active constraint가 0건이었으므로 새로운 속성의 HARD 분류는 완전하지 않다.

`Yes`로 바꾸기 위한 gate:

- property metadata에서 constraint를 생성하는 단일 `ConstraintCompiler`
- HARD dominance를 다른 evidence가 낮출 수 없다는 monotonicity test
- 누락·충돌 metadata의 HARD fail-closed test
- 동일 property vector의 이름·순서·object type 변형에서 동일 결과 test

## 7. 권장 리팩토링 순서

1. 공식 입력에서 얻을 수 있는 property metadata와 얻을 수 없는 항목을 계약으로 분리한다.
2. `DataProperty`와 `Context`를 기존 typed fact 계층에 추가한다. 새 semantic owner는 만들지 않는다.
3. 기존 `ConstraintActivator`가 이름이 아니라 property vector로 `RuleEffect`를 생성하게 한다.
4. `BlueprintCompiler`가 permitted mode set과 capability DAG를 단일 authoritative 계약으로 만든다.
5. `_disclosure_projection`과 `_plan_projection`은 Blueprint의 순수 compiler가 되게 한다.
6. strict validator는 독립 source facts, Blueprint, compiled output의 provenance와 exact equality만 검사한다.
7. metamorphic·unknown-type·missing-metadata test를 통과한 뒤에만 기존 stale candidate를 폐기하고 새 manifest를 생성한다.

이 순서가 완료되기 전에는 현재 구조를 `RELEASE_READY`로 승격하지 않는다.
