# Logical / Validity 구조 결함 수정 보고서

작성일: 2026-07-12  
대상: `/mnt/c/Users/doo33/Desktop/scpc_newparser`  
현재 source tree SHA-256: `d215faff629b0f6397a28492cc71485e76c84a3268fd8b082f6c27c5ee1a260f`

## 1. 결론

제보된 네 가지 구조 반례를 현재 production 경로에서 모두 재현한 뒤 수정했다.

- `contains=[]`가 `fields`를 가리는 inventory 우선순위를 제거했다.
- 기존 property classification을 실제 disclosure constraint와 Blueprint effect의 단일 정책 소유자로 연결했다.
- 알려지지 않은 object type의 direct attr는 필드명만 보고 PUBLIC 등으로 승격하지 않고 `UNKNOWN`으로 처리한다.
- strict validator는 mutable dict를 decision authority로 받지 않고 정확한 frozen `FinalDecision` 인스턴스만 받는다.
- release semantic gate가 위 반례를 직접 실행하도록 필수 check ID를 확장했다.

구조 테스트와 screening 700건 실행은 통과했다. 다만 현재 `submission.csv`와 authoritative candidate manifest는 수정 전 source에 대응하는 stale 산출물이므로 release 승격은 수행하지 않았다.

## 2. 반례별 재현과 수정 결과

### F1. 빈 `contains`가 `fields`를 가리는 문제

수정 전 입력:

```text
contains=[]
fields=["novel_field_123"]
```

수정 전 결과:

```text
control=proceed
mode=summary
properties=[]
active_constraints=[]
excluded_fields=[]
```

직접 원인은 `describe_object_properties()`와 `TaskView.contains_for_object()`가 `contains` 또는 `fields` 중 하나만 선택한 것이었다. 두 inventory를 합집합으로 읽고 provenance source는 각각 유지하도록 변경했다.

수정 후 결과:

```text
classification=unknown
source=fields
control=hold
mode=none
excluded_fields=["novel_field_123"]
constraint=unknown_property_disclosure / hard / block_execution
```

관련 코드: `core/property_policy.py:197`, `core/task_view.py:249`

### F2. classification이 disclosure 동작에 영향을 주지 않는 문제

기존에는 `UNKNOWN`만 실제 effect를 만들고 PUBLIC/INTERNAL/RESTRICTED/SECRET은 이름만 분류했다. 이 때문에 `password`가 SECRET이어도 raw 허용 판단과 scope/exclusion에 영향을 주지 않았다.

현재 정책 행은 다음과 같다.

| Classification | Severity | Directive | 허용 mode | 결과 |
|---|---|---|---|---|
| PUBLIC | 없음 | ALLOW | raw, summary, redacted, status_only, none | Blueprint 기본 scope 유지 |
| INTERNAL | AMEND | FORCE_SUMMARY | summary, redacted, none | 비공개 필드 제외, summary 이상으로 제한 |
| RESTRICTED | AMEND | ADD_REDACTION | redacted, none | 비공개 필드 제거 후 전송 |
| SECRET | AMEND | ADD_REDACTION | redacted, none | secret 필드 제거 후 전송 |
| UNKNOWN | HARD | BLOCK | none | 의미를 모르는 필드는 fail-closed |

SECRET 자체를 곧바로 전체 작업 금지로 해석하지 않았다. 제거 가능한 필드는 redaction으로 없애고, 안전한 변환을 선택할 근거가 없는 UNKNOWN만 HARD로 차단한다. 첫 구현에서 SECRET까지 HARD로 처리했을 때 `rrn`처럼 제거 가능한 필드가 있는 18개 dev 경로가 불필요하게 HOLD가 되는 반례가 확인되어 이 구분을 바로잡았다. 임계값이나 기대값은 변경하지 않았다.

최종 `message.password` 반례 결과:

```text
classification=secret
control=amend
mode=redacted
excluded_fields=["password"]
constraint=classified_property_disclosure / amend / add_redaction
```

정책은 `property_policy`에서 한 번 결정되고, `ConstraintActivator`는 해당 directive를 Blueprint effect로 변환하며, projection은 정책이 허용하지 않은 mode를 거부한다. `_safe_scope_mode`에 field name, task ID, object-type 분기를 추가하지 않았다.

관련 코드: `core/property_policy.py:144`, `core/decision.py:1359`, `core/decision.py:2447`

### F3. 알려지지 않은 object type의 direct attr 오분류

수정 전에는 `object_type=novel_object_type`의 `attrs.summary`가 필드명만으로 PUBLIC이 됐다. 수정 후 known object type이 아닌 경우 direct attr도 `UNKNOWN`이다. `ref_code`는 object resolution용 공통 구조 메타데이터이므로 disclosure property에서 제외했다.

수정 후 결과:

```text
property=summary
source=direct_attr
classification=unknown
control=hold
mode=none
excluded_fields=["summary"]
```

관련 코드: `core/property_policy.py:225`

### F4. mutable dict decision authority

수정 전에는 answer, serialized trace, authority로 같은 mutable dict를 사용해 scope를 함께 `raw`로 바꾸면 strict validator가 통과했다.

수정 후 `validate_strict()`는 정확한 `FinalDecision` 타입만 받는다. dict와 subclass는 authority가 될 수 없다. production `FinalHarness`는 이미 frozen `FinalDecision` 객체를 넘기므로 production 호출 계약은 유지됐다.

수정 후 오류:

```text
[release_semantic_check] decision authority must be an immutable FinalDecision
```

독립 frozen authority를 유지한 상태에서 serialized trace만 변조한 경우에도 다음과 같이 거부된다.

```text
serialized FinalDecision trace differs from authority;
content_scope is not a pure FinalDecision projection
```

관련 코드: `core/consistency.py:38`

## 3. projection과 semantic ownership 점검

- property 이름의 분류 및 classification별 disclosure 규칙: `core/property_policy.py`
- focal property evidence와 provenance 전달: `core/evidence_graph.py`
- constraint 및 Blueprint effect 활성화: `core/decision.py::ConstraintActivator`
- 최종 mode/exclusion projection: `core/decision.py::FinalDecisionBuilder`
- immutable 결정과 출력의 일치 검증: `core/consistency.py`

새 semantic owner를 추가하지 않았다. 기존 `property_policy`를 완성하고 downstream은 그 typed effect만 소비한다. `raw_dispatch_allowed()`도 먼저 policy의 `permitted_modes`를 확인하므로 guardrail 경로가 restricted/secret/unknown 필드에 `ALLOW_RAW`를 추가할 수 없다.

projection은 더 이상 `summary/redacted`라는 이유만으로 `contains` 전체를 제외하지 않는다. policy가 비공개로 분류한 필드만 `excluded_fields`에 투영한다. PUBLIC 필드는 제외 목록에 들어가지 않고, raw는 policy가 raw를 허용한 경우에만 dispatch mode가 될 수 있다.

## 4. release semantic check 보강

필수 semantic check에 다음 항목을 추가했다.

```text
property_inventories_merged
classified_property_policy_enforced
unknown_object_direct_attr_fail_closed
mutable_authority_rejected
```

기존 항목과 함께 실행한 결과는 6/6 `true`였다.

```text
unknown_property_fail_closed=true
property_inventories_merged=true
classified_property_policy_enforced=true
unknown_object_direct_attr_fail_closed=true
scope_trace_tampering_rejected=true
mutable_authority_rejected=true
```

F3 release false-path와 W5 test 분리는 변경하지 않았다. `released is not True`인 경우 publish, validate, promote 호출은 계속 0회다. `dev_score` marker도 유지했다.

## 5. 검증 결과

### 테스트 및 정적 검사

```text
targeted structural tests: 56 passed
required suite (-m "not dev_score"): 267 passed, 1 deselected
full suite: 267 passed, 1 failed
Ruff: All checks passed
```

deselected된 1개는 `tests/test_regression.py::test_dev_score_diagnostics`이다. 전체 suite의 유일한 실패도 같은 진단 테스트다.

```text
measured overall=0.8483
diagnostic threshold=0.9421
```

이 라운드에서 Criteria 정의, score weight, threshold, 기대 answer, 공식 data, scorer는 수정하지 않았다. 수정 전 보고값 `0.8523` 대비 실제 측정 변화는 `-0.0040`이다. 점수는 구조 성공 조건에서 제외했지만 측정값은 숨기지 않았다. 별도의 official-scorer parity 검사는 `0.8483 == 0.8483`으로 통과했고 기존 snapshot floor `0.8186`도 통과했다.

### dev / screening / official 820 관계

```text
dev=120
screening=700
ID intersection=0
union=820
```

- dev 120: scorer와 회귀 진단을 실제 실행했다.
- screening 700: 현재 source로 전부 실행했으며 answer 700개와 trace 700개를 생성했다.
- official 820: 위 두 집합의 합집합 관계와 ID 비중복을 확인했다. 820을 하나의 별도 입력 파일로 실행한 것은 아니다.

screening 700 실행 결과:

```text
control: amend=210, ask=176, hold=145, proceed=169
mode: none=321, raw=9, redacted=205, status_only=160, summary=5
HARD constraint projection violations=0
answer semantic SHA-256=e07201d7304dfe1fe73cb16e402d0289367eb77399c01d4c6539869001e119fe
```

### anti-reward-hacking 검사

AST specificity scan은 70개 Python 파일과 44개 authoritative runtime 파일을 확인했다.

```text
authoritative runtime specificity hits=0
scan passed=true
```

tooling diagnostics에는 release scanner 자체의 금지 marker 상수, scorer/data 자산 참조, `utils/diff.py`의 ID 기반 diff 정렬/비교가 남는다. 이들은 FinalHarness 결정 경로가 아니며 runtime hit로 승격하지 않았다. 이번 수정에는 `task_id`, `session_id`, `control` 값에 따른 새 property-policy 분기가 없다.

`validate_artifacts.py`, `build_manifest.py`, `release_gate.py`, `run_submission.py`와 current runtime에는 `scpc_Gparser` 탐색·복사 의존성이 없다. 다만 실행하지 않은 legacy stage 도구 `step1_baseline.py`와 `step12_gate.py`에는 외부 historical submission이 존재할 때만 선택적으로 비교하는 경로 문자열이 남아 있다. 외부 경로가 없으면 `NOT_RUN` 또는 비교 생략으로 끝나며 현재 판단과 산출물에는 사용되지 않았다. 이 두 legacy command를 다시 authoritative workflow로 사용할 경우에는 외부 비교 입력을 명시적 인자로 바꾸는 별도 정리가 필요하다.

## 6. Hash와 artifact freshness

```text
source tree SHA-256:
d215faff629b0f6397a28492cc71485e76c84a3268fd8b082f6c27c5ee1a260f

dev_tasks.jsonl:
871fcb52708d66fa1eec39073a9803ef29204315c5ee3a013799cc364bc55e1d

dev_answers.json:
2ec6723345c78ccb5613ed90b4b778ecf3b5da3db92e341e8b8bfaa7724bd1c3

screening_tasks.jsonl:
36248ede94b89fd0d89024ed14fd554ee75196d052dcac90dec579d8185ffd57

official_scorer.py:
157f34ac7f620936575474fba367eb9e33d864643a010dd5f624b4934535f48c

submission.csv:
f2791ae6a3ebd78007a7a04a7cb05f1d1bbf5465a9605141585e402c81ec8a9c

manifest/candidate_manifest.json:
21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389

manifest recorded source tree:
23c090b978b0c432e1c4b77cf0afeae9ab3a7ff6e2d5ffde4ec66134ec013c77
```

manifest의 source hash와 현재 source hash가 다르다. 기존 `submission.csv`는 현재 screening 결과와 640/700건이 다르고, 이전 structural reference submission과도 현재 결과가 276/700건 다르다. 따라서 기존 submission, manifest, 과거 screening artifact는 현재 source의 release evidence로 사용할 수 없다.

## 7. 변경 파일

Production/runtime:

```text
core/property_policy.py
core/task_view.py
core/evidence_graph.py
core/decision.py
core/consistency.py
release_gate.py
```

Tests:

```text
tests/test_safety_invariants.py
tests/test_architecture.py
tests/test_release_gate_analysis.py
```

Checkpoint/report:

```text
implementation_checkpoint.md
reperence/logical_validity_remediation_report.md
```

수정하지 않은 항목:

```text
tests/test_regression.py
tests/specs/generalization_v1.json
official data
official_scorer.py
submission.csv
manifest/candidate_manifest.json
production FixedSLM 연결 상태
```

## 8. 남은 한계와 release 판단

Read-only로 계산한 코드-level release required-check contract는 13/13 통과했다. 그러나 artifact validation과 promotion은 실행하지 않았고 authoritative submission/manifest가 stale이다. 따라서 이 보고서는 `RELEASE_READY` 또는 production 승격을 선언하지 않는다.

현재 상태:

```text
CODE_LEVEL_REQUIRED_CHECKS=PASS
ARTIFACT_FRESHNESS=FAIL
ARTIFACT_VALIDATION=NOT_RUN
MANIFEST_PROMOTION=NOT_RUN
RELEASE_STATUS=RELEASE_BLOCKED
FixedSLM=KEEP_SHADOW (production_influence=false)
```

또한 기존 property-name 분류표가 공식적으로 완전한 민감도 ontology라는 근거는 없다. 새 필드와 새 object type은 UNKNOWN/HARD/none으로 안전하게 차단되지만, 그 필드의 진짜 의미 분류를 자동으로 알아낸다는 뜻은 아니다.

Criteria 재판정:

- Criteria A: `NO`. screening 700 실행 성공과 unknown fail-closed는 증명했지만 모든 미지 입력의 의미적 정답까지 증명하지 못했다.
- Criteria B: `NO`(보편 명제 기준). 관찰한 820 경로와 구조 테스트는 validator 완화 없이 통과했지만 모든 유효 입력에 합법적 결정이 존재한다는 공식 계약은 없다.
- Criteria C: `NO`(“완벽한 의미 감지” 기준). 활성화된 HARD는 모두 hold/none으로 전파되고 unknown은 HARD가 되지만, 미지 필드의 실제 semantic classification을 완전하게 식별하는 oracle은 없다.

다음 release 작업은 현재 source로 submission과 report를 재생성하고, source/data/scorer/submission hash가 일치하는 candidate manifest를 별도 artifact-validation 경로에서 검증한 뒤에만 수행해야 한다.
