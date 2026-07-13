# SCPC v8 인과 사슬 및 결함 재검증 보고서

- 검증 기준일: 2026-07-12
- 대상 경로: `/mnt/c/Users/doo33/Desktop/scpc_newparser`
- 공식 입력: `reperence/SCPC2026_Final_data.zip`
- 최종 source tree SHA-256: `f3254e51961434feae2797da1e138d17f3dab90bc930f69e3ad85238b4d55b94`
- production release 판정: `RELEASE_BLOCKED`
- 차단 사유: 공식 dev hard gate 미달 하나뿐이며, 측정값은 `0.8417`, 기준은 `0.9421`이다.

## 1. 최종 결론

제시된 전체 인과 사슬은 현재 공식 dev 경로의 정확도 하락 원인으로 입증되지 않았다.

변경 전 코드에는 검증 완료 후 `persistent_memory_write`의 문자열 값을 근거로 raw prompt를 정규식 재해석하는 별도 경로가 실제로 존재했다. 문자열 alias 레코드를 넣은 독립 재현에서는 이 경로가 도달 가능했고, 검증 대상에 없던 값이 `MemoryStore`에 기록됐다. 이 부분은 `validation-before-commit` 불변식을 위반하므로 `CONFIRMED`이다.

그러나 공식 dev의 memory-write 레코드 다섯 건은 모두 구조화된 `dict` 값이며, 임시 계측에서 raw fallback 호출은 0건이었다. 해당 경로를 제거한 뒤에도 공식 dev 점수와 submission은 각각 `0.8417`, `9d3f2c...`로 동일했다. 따라서 다음 연결은 성립하지 않는다.

```text
한글 정규식 누락
  -> 공식 dev memory 유실
  -> 다음 턴 recall 실패
  -> DecisionEngine 오류
  -> 전체 점수 0.8417
```

정확한 판정은 다음과 같다.

```text
검증 후 raw prompt 재해석 및 persistent write: CONFIRMED, 제거 완료
옛 정규식의 한글 범위 누락: PARTIALLY_CONFIRMED, 해당 파서 자체를 제거해 해소
공식 점수 하락까지 이어지는 전체 인과 사슬: INCORRECT_PREVIOUS_JUDGMENT
```

## 2. 근거와 계약 분류

| 분류 | 항목 | 근거 | 적용 범위 | 보호하는 상태 또는 의미 | 위반 시 실제 영향 | 현재 강제 방식 | 공식 계약과의 관계 |
|---|---|---|---|---|---|---|---|
| `OFFICIAL_CONTRACT` | answer schema와 공식 입력 형식 | 공식 ZIP의 schema, task 및 answer 자산 | submission 700건과 dev 120건 | 필드 형식, 허용 값, 제출 구조 | 제출 거부 또는 scorer 입력 불능 | `submission_schema.json`, `validate_submission.py` | 공식 자산에서 직접 확인 |
| `OFFICIAL_CONTRACT` | 공식 notebook scorer 의미 | `SCPC2026_Final_baseline.ipynb` scorer cell | dev 점수 계산 | strict-first-best-tie와 축별 점수 | 로컬 점수와 공식 점수 불일치 | notebook scorer 직접 로드 후 `local_score.py`와 전 축 parity 비교 | 공식 notebook에서 직접 확인 |
| `RUNTIME_INVARIANT` | validation-before-commit | `FinalHarness.answer_task` 호출 순서와 atomic committer | session 및 process-local memory mutation | 검증되지 않은 persistent side effect 방지 | 다음 턴 입력과 persistent state 오염 | projection -> validator -> staged write -> atomic commit | 공식 schema가 직접 규정하지 않지만 데이터 무결성과 모순 없는 상태에 필수 |
| `RUNTIME_INVARIANT` | 단일 semantic ownership | `FinalDecision`에서 projection·answer가 순수 파생되고 validator가 동기화를 검사 | decision, scope, policy, plan | 같은 입력의 이중 의미 해석 방지 | trace와 output 사이의 의미 분기 | `ProductionProjectionPipeline`, `ConsistencyValidator` | 공식 계약을 구현하는 내부 불변식이며 독립 validator를 추가할 근거는 아님 |
| `RUNTIME_INVARIANT` | typed memory write만 commit | record parser가 만든 `MemoryWriteValue.as_payload()` | persistent memory write | 원천 레코드와 commit 값의 동일성 | raw prompt 재해석 결과가 검증을 우회 | 문자열 fallback 제거, 구조화 payload만 staged commit | memory 자체는 공식 schema 밖이지만 validation-before-commit에 필수 |
| `TESTED_EXPECTATION` | dev hard gate `0.9421` | `tests/specs/generalization_v1.json`, regression test | project release | 회귀 허용 한계 | production release 차단 | release gate와 pytest | 공식 scorer의 규칙이 아니라 현 프로젝트의 release 기준 |
| `DESIGN_INTENT_ONLY` | FixedSLM production 승격 | Stage 3 계획과 status manifest | FixedSLM | shadow와 production evidence 분리 | 검증 안 된 모델 출력 혼입 | 현재 `KEEP_SHADOW`, `production_influence=false` | 공식 facade 근거는 있으나 일반화 개선·복구 계약 증명이 부족 |
| `UNRESOLVED_ASSUMPTION` | `ReasonCode.UNKNOWN`을 어떤 구체 코드로 바꿀지 | projection 내부에 구체 mapping 계약 없음 | trace metadata | 사유 추적성 | trace 설명력 저하 가능 | 현재 UNKNOWN 유지 | 공식 자산에 mapping 규칙이 없어 임의 확정 불가 |

`TESTED_EXPECTATION`과 문서상 의도는 독립적인 공식 계약 또는 데이터 무결성 불변식 없이 결함 판정의 단독 근거로 사용하지 않았다.

## 3. 제기 항목별 판정

| ID | 제기 항목 | 판정 | 핵심 근거 | 현재 조치 |
|---|---|---|---|---|
| F-01 | validation 이후 raw prompt 재해석 및 무검증 memory commit | `CONFIRMED` | production 진입점에서 문자열 memory-write 레코드로 도달 가능했고 persistent state 변경을 독립 재현 | raw 재해석 함수와 fallback 호출을 제거. typed payload만 commit |
| F-02 | memory 정규식의 한글 범위 누락 | `PARTIALLY_CONFIRMED` | 옛 `[A-Za-z0-9_]+` 패턴은 한글 값을 추출하지 못함. 다만 공식 dev는 이 fallback을 호출하지 않음 | 문제 파서를 확장하지 않고 중복 파싱 경로 자체를 제거 |
| F-03 | F-02가 공식 dev recall·decision·accuracy 하락을 유발 | `INCORRECT_PREVIOUS_JUDGMENT` | 공식 dev memory-write 5건 모두 dict, fallback 0회, 변경 전후 점수·submission 동일 | 원인으로 채택하지 않음 |
| F-04 | hold에서 dispatch 외 실행 동사 검증 누락 | `STRUCTURAL_RISK` | 일관성 변조 trace는 기존 validator를 통과했으나 현재 authoritative builder가 그런 plan을 생성한다는 production 재현은 없음 | 기존 semantic owner를 늘리지 않고 같은 validator의 execution verb 집합 검사로 방어 강화 |
| F-05 | 공식 ZIP hash보다 cache 조기 반환 | `CONFIRMED` | 완전한 cache가 있으면 stale marker 확인 전에 반환하는 경로와 `SCPC_DATA_DIR` cache 우회 재현 | cache 반환 전에 공식 archive hash 기반 재검증·재추출 |
| F-06 | release gate의 주석·도달 불가 문자열 허용 | `STRUCTURAL_RISK` | 실제 current source 우회는 없었으나 기존 텍스트 인덱스 방식은 합성 source에서 우회 가능 | Python AST string constant와 reachable-call/order 검사로 강화 |
| F-07 | 독립적 의사결정 validator 부재 | `UNRESOLVED_CONTRACT` | 공식 원천 규칙을 validator가 독립 재계산해야 한다는 계약이 없고, 추가 시 `FinalDecision`과 병렬 semantic owner가 됨 | 변경 없음 |
| F-08 | projection의 `ReasonCode.UNKNOWN`, 빈 constraint index | `STRUCTURAL_RISK` | traceability 저하는 가능하지만 compiled answer·submission 영향과 공식 mapping 계약이 확인되지 않음 | 임의 의미 mapping을 추가하지 않음 |
| F-09 | plan report의 `0.9421`과 실제 `0.8417` 혼동 | `CONFIRMED` | 문서 문구와 재생성한 공식/local scorer 결과 비교 | `0.9421`은 floor, `0.8417`은 actual로 수정 |
| F-10 | `sys.executable` 사용이 release 결과를 오염 | `INCORRECT_PREVIOUS_JUDGMENT` | child 환경에서 pytest 누락 시 성공으로 오판하지 않고 non-zero로 fail closed | 변경 없음 |
| F-11 | FixedSLM 미승격 자체가 현재 정확도 결함 | `UNRESOLVED_CONTRACT` | production 개선과 회귀 없음이 입증되지 않음 | `KEEP_SHADOW`; production evidence 영향 0 |

## 4. 핵심 문제의 production 영향 분해

### F-01/F-02: memory fallback

| 검증 항목 | 결과 |
|---|---|
| 코드 도달 가능성 | 있음. `FinalHarness.answer_task -> _commit_memory` |
| 분기 활성화 가능성 | 문자열 alias인 `persistent_memory_write.value`에서 변경 전 활성화 |
| 판단 결과 영향 | 해당 턴의 `FinalDecision`은 이미 끝났으므로 없음 |
| compiled output 영향 | 해당 턴에는 없음 |
| persistent state 영향 | 있음. 변경 전 재현에서 `korean_alias` entry가 생성됨 |
| 다음 턴 영향 | 오염 entry를 명시적으로 recall하는 입력에서는 가능 |
| 공식 dev 영향 | 없음. 공식 dev의 관련 레코드는 5/5 구조화 dict, fallback 계측 0회 |
| submission 영향 | 없음. 제거 전후 SHA-256 동일 |

변경 전 최소 재현의 입력은 문자열 alias memory-write와 한글 prompt였다. 기대 결과는 검증되지 않은 raw 파싱 값이 저장되지 않는 것이었으나, 실제 snapshot은 다음과 같았다.

```text
{'korean_alias': {'memory_key': 'korean_alias'}}
```

이는 "빈 값만 적재"라는 설명과도 정확히 일치하지 않는다. 실제 결함은 한글 누락 자체보다 검증되지 않은 별도 parser가 commit 값을 새로 만들 수 있었다는 점이다.

변경 후 acceptance test는 alias-only 값이 아무것도 쓰지 않고, 구조화된 한글 값은 원본 그대로 commit되는지를 각각 검증한다.

### F-04: hold validator

| 검증 항목 | 결과 |
|---|---|
| validator 호출 도달성 | 모든 answer에서 도달 |
| 잘못된 분기 활성화 | answer, FinalDecision trace, capability를 함께 변조한 일관성 변조에서 가능 |
| 독립 production 입력 재현 | 확인되지 않음. current builder는 hold에 실행 plan을 만들지 않음 |
| persistent/submission 실제 영향 | 현재 공식 경로에서는 확인되지 않음 |

따라서 현재 결함 수에는 포함하지 않고 `STRUCTURAL_RISK`로 유지했다. 방어는 기존 validator의 동일 책임 범위 안에서 `dispatch`, `update`, `schedule`, `toggle`, `pay` 전체를 거부하도록 최소 확장했다.

### F-05: archive/cache

공식 archive가 존재하는 상태에서 cache marker를 stale 값으로 바꾼 뒤 `find_data_dir()`를 호출했다. 변경 전에는 완전한 cache 디렉터리 존재만으로 조기 반환할 수 있었다. 변경 후에는 marker가 공식 archive SHA-256으로 복구되고 공식 archive 내용이 authoritative source가 된다. `SCPC_DATA_DIR`가 바로 workspace cache를 가리키는 reproduction child 환경도 같은 검사를 거친다.

## 5. 직접 원인과 구조적 원인

| 결함 | 관찰된 증상 | 직접 원인 | 구조적 원인 | 대안 원인 검토 |
|---|---|---|---|---|
| F-01 | 검증 후 memory snapshot에 새 값 생성 | `_commit_memory`가 문자열 alias이면 raw prompt parser 호출 | record parsing과 commit parsing의 semantic ownership 중복 | parser upstream 오류가 아니라 commit 단계가 새 의미를 생성함을 확인 |
| F-05 | stale cache marker가 있어도 cache 재사용 가능 | cache 디렉터리 완전성 검사를 archive marker보다 먼저 수행 | content identity와 directory existence의 우선순위 역전 | 생성 시각·파일명은 판단 근거로 사용하지 않음 |
| F-09 | report에 현재 score처럼 `0.9421` 표기 | hard floor와 measured score 혼동 | report freshness/용어 구분 부족 | official/local scorer parity로 actual `0.8417` 재확인 |

F-02는 제거된 중복 parser의 내부 증상이다. F-01과 별도 근본 결함으로 중복 계산하지 않았다.

## 6. 적용한 최소 변경과 acceptance test

| 변경 | 해결 대상 | 최소 변경 범위 | 보존 조건 | acceptance test | rollback 조건 |
|---|---|---|---|---|---|
| raw prompt memory parser 삭제 | F-01, F-02 | `harness.py`, `core/session_state.py` | structured memory payload, atomic commit, recall | alias-only no-write; structured Korean exact-write; held write no-commit | 공식 structured write가 소실되거나 memory regression 발생 |
| hold execution verb 집합 검사 | F-04 | `core/consistency.py` | hold/ask control 의미와 기존 FinalDecision owner | self-consistent tamper에서 모든 execution verb 거부 | 정상 hold answer가 거부되거나 새로운 control regression 발생 |
| archive hash 우선 cache 검증 | F-05 | `utils/io.py` | workspace-only input, official archive authority | stale marker를 official SHA로 복구 | 동일 archive에서 비결정적 extract 또는 정상 cache 불능 |
| AST release 검사 | F-06 | `release_gate.py` | current lifecycle 순서, task-specific literal 금지 | 정상 order 통과; comment·`if False` 미인정 | 정상 reachable call을 놓치거나 비-Python 자산을 오탐 |
| score 문구 정정 | F-09 | `reports/plan_integrity_audit.md` | 과거 baseline과 현재 측정값 구분 | official/local scorer parity | 재생성 결과와 문서 수치 불일치 |

새 DTO, registry, semantic owner, persistent write 경로, execution side effect는 추가하지 않았다. FixedSLM은 production evidence에 병합하지 않았다.

## 7. 실행 및 재현 결과

### 실행 명령

```bash
PYTHONDONTWRITEBYTECODE=1 python run_submission.py --output submission.csv
PYTHONDONTWRITEBYTECODE=1 python generate_reports.py
PYTHONDONTWRITEBYTECODE=1 python release_gate.py
PYTHONDONTWRITEBYTECODE=1 python validate_artifacts.py --reproduce
PYTHONDONTWRITEBYTECODE=1 pytest -q
PYTHONDONTWRITEBYTECODE=1 pytest -q -k 'not test_dev_score_and_optional_fields'
```

### 결과

- submission 독립 재생성: byte-identical
- dev metric 독립 재생성: identical, overall `0.8417`
- report 9개: content-identical
- candidate manifest content fingerprint: identical
- 전체 pytest: `245 passed, 1 failed`
- dev hard gate 한 건 제외: `245 passed, 1 deselected`
- 유일한 실패: `tests/test_regression.py::test_dev_score_and_optional_fields`
- 실패 값: actual `0.8417` < required `0.9421`
- 현재 셸에는 `ruff` executable이 없어 마지막 반복 실행은 `NOT_RUN`이다. 같은 변경 집합에 대한 앞선 Ruff 검사는 통과했으며, 최종 전체 pytest와 import 경로 검증은 통과했다.

## 8. 정확도와 산출물 기준선

### 공식 입력 및 scorer

| 항목 | SHA-256 |
|---|---|
| 공식 archive | `c53751f2dc947d7a19bc5a4af861cca47f21e16ad29b7625770e82a1be7348f5` |
| dev tasks | `871fcb52708d66fa1eec39073a9803ef29204315c5ee3a013799cc364bc55e1d` |
| dev answers | `2ec6723345c78ccb5613ed90b4b778ecf3b5da3db92e341e8b8bfaa7724bd1c3` |
| screening tasks | `36248ede94b89fd0d89024ed14fd554ee75196d052dcac90dec579d8185ffd57` |
| 공식 notebook | `d2743c0cf15880655e5a760a272b4e9d2733b71322e545ec3e06fce4a2f43579` |
| notebook baseline submission | `fc51cdf2197c070930bcf1e01e7fdae8483343d343379b67ab05634bdef86fe7` |
| local scorer | `58db0156a8a50b8814ee3962fe93d10aa4cfcef453ef884f7d64f696f690f38e` |

공식 notebook scorer와 local scorer는 overall 및 모든 축에서 동일하다.

### 현재 dev 분포

| 축 | 값 | 오류 수 |
|---|---:|---:|
| focal | 1.0000 | 0 |
| target | 0.9417 | 7 |
| control | 0.9583 | 5 |
| content_scope | 0.7482 | 79 |
| policy | 0.7171 | 99 |
| plan | 0.8656 | 22 |

- exact: 15/120
- non-exact: 105/120
- input visibility gap: 3건

memory fallback 제거 전후 score가 같으므로 이 변경에서 측정된 정확도 회귀도 개선도 없다. 나머지 105개 non-exact를 memory 문제 하나로 설명할 수 없다.

### 최종 산출물

| 항목 | SHA-256 또는 fingerprint |
|---|---|
| source tree | `f3254e51961434feae2797da1e138d17f3dab90bc930f69e3ad85238b4d55b94` |
| submission.csv | `9d3f2c280b752c3acb26aea3a56f8ea8e4a48fcd4d03333bcee9a56a39f269a2` |
| candidate manifest raw file | `97995f6fee208a56fc05e164efab4470b3eca2944894d9a76936f49ed013264b` |
| candidate content fingerprint | `2c39ebf45c06ae47c44ebca58dd1d08d386e8ad8952e0db329dee44afb0ad3ad` |
| release report raw JSON | `3d53efb8483e3ca4245293e86b6190e7f24efa5faa534a007fae096e1dbf9ff9` |
| release report canonical content | `98c9ed5a3f511c30d173518ca32a68fc20ef4d6abe94f4c1b81e7b51d879cbc5` |

raw JSON hash와 canonical content hash의 차이는 `generated_at` 같은 비의미 시간 필드를 freshness 근거에서 제외하기 때문이다. 최신 여부는 파일명이나 생성 시각이 아니라 source tree, official input, scorer, submission 및 canonical report content 결합으로 판정했다.

## 9. FixedSLM 판정

최종 판정은 `KEEP_SHADOW`이다.

- 공식 interface/schema 확인: 통과
- parser-only 대비 일반화 개선: 미확인
- 공식 dev 회귀 없음: 통과
- metamorphic·paraphrase: 미통과
- hard fact authority 침해: 0건
- timeout·invalid output parser-only 복구: 미확인
- production influence: `false`

승격 기준을 모두 충족하지 않았으므로 FixedSLM 출력은 production evidence에 병합되지 않는다.

## 10. 최종 재검토와 남은 차단 요소

- 계약 미확정인 independent semantic validator와 reason mapping을 결함으로 확정하지 않았다.
- official production에서 활성화되지 않은 hold validator 문제와 release 문자열 우회는 `STRUCTURAL_RISK`로 유지했다.
- regex 증상과 raw reparse를 별도 근본 결함으로 중복 계산하지 않았다.
- 변경은 실제 production commit/cache 경계와 release gate에 적용되며 새 우회 경로를 만들지 않는다.
- source, submission, report, manifest를 현재 source hash로 독립 재생성했다.
- 외부 `scpc_Gparser` 자동 탐색·복사 의존성은 current production/report/release 경로에 없다.
- production release의 유일한 남은 차단 요소는 기존 official dev hard gate 미달이다.

현재 확인된 결함 수정 범위는 완료됐다. 점수 `0.8417`을 `0.9421` 이상으로 올리는 작업은 이번 인과 사슬로 정당화되지 않으며, 별도의 공식 근거 기반 정확도 분석 없이는 확대 구현하지 않는다.
