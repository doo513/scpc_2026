# SCPC 공식 계약 감사

## 감사 기준

- 공식 자산: `C:\Users\doo33\Desktop\data\SCPC2026_Final_data.zip`
- ZIP SHA-256: `c53751f2dc947d7a19bc5a4af861cca47f21e16ad29b7625770e82a1be7348f5`
- 기준선 소스: `C:\Users\doo33\Desktop\scpc_newparser`
- 근거 우선순위: 공식 ZIP → 재현 가능한 production runtime → 테스트 → 관계도 → 기존 리팩터링 문서 → 과거 report/manifest

## 공식 ZIP 구성

| 자산 | 역할 | 감사 결과 |
| --- | --- | --- |
| `data/dev_tasks.jsonl` | 공개 dev task 120개 | 읽기 전용 기준 자산 |
| `data/dev_answers.json` | 공개 dev reference와 plan arg ontology | scorer 입력 기준 |
| `data/screening_tasks.jsonl` | 답안 없는 screening task 700개 | submission 생성 입력 |
| `submission_schema.json` | answer JSON schema | local schema와 SHA-256 일치 |
| `sample_submission.csv` | CSV envelope 예시 | 형식 참고 |
| `TERMS_GUIDE.md` | task/field/action 용어 안내 | 계약과 설명을 구분해 사용 |
| `SCPC2026_Final_baseline.ipynb` | baseline, FixedSLM facade, 공개 scorer | interface와 scorer의 직접 근거 |

공식 데이터 파일 SHA-256은 candidate manifest의 `data_sha256`에 기록한다. local schema와 ZIP schema SHA-256은 모두 `1c88c1b357ffa7d70c0aa02b358842e39edc47c754aebeed3f4cee9f6d4cf418`이다.

## CONFIRMED_CONTRACT

### 제출 envelope

- 최상위 `schema` 값은 `scpc.final.answer.v1`이다.
- `answers`는 task ID를 key로 하는 object다.
- 각 answer는 `focal_id`, `target`, `control`, `content_scope`, `policy`, `plan_events`를 포함해야 한다.
- `control` enum은 `proceed`, `amend`, `hold`, `ask`다.
- `content_scope.mode` enum은 `raw`, `summary`, `redacted`, `status_only`, `none`이다.
- `plan_events` 최대 길이는 18이며 각 항목은 `verb`, `target`, `args`를 가진다.
- `user_response`, `audit_tags`, `counterfactual`은 schema상 선택 필드다.

### 입력과 배열

- 같은 session의 순서는 `turn_index`가 결정한다.
- `objects`, `records`, `personal_memory`의 배열 위치 자체는 의미 우선순위가 아니다.
- screening answer는 공개되지 않으므로 screening 분포를 정확도 근거로 사용할 수 없다.
- `available_actions`는 plan에 사용할 수 있는 action 목록이다. 어떤 internal transform까지 제한하는지는 공식 자료만으로 완전히 확정되지 않는다.

### 공개 scorer

- 공식 notebook scorer는 focal, target, control, content scope, policy, plan, semantic response, counterfactual 축을 가중 합산한다.
- plan event 동률에서는 `>` 비교를 사용해 첫 번째 best match를 유지한다. 기존 local scorer의 tuple `max`는 마지막 동률 index를 선택해 공식 결과와 달랐다.
- 수정 후 현재 dev 결과는 overall `0.8186`, plan `0.7723`이며 공식 notebook 계산과 일치한다.
- 공개 reference에 semantic response target이 없으므로 local semantic response 축은 `0.0`이다.

근거: `local_score.py`, `tests/test_official_scorer_parity.py`, 공식 notebook scorer cell 11.

## FixedSLM 공식 interface

공식 notebook은 다음 facade를 제공한다.

```text
class: FixedSLMClient
model_id: scpc-final-fixed-slm-local-facade
method: summarize_task(task: dict[str, Any]) -> dict[str, Any]
output: risk_flags, requires_redaction, requires_confirmation, audit_tags
```

공식 설명상 FixedSLM은 정답을 직접 제공하지 않는 evidence helper다. 최종 answer는 harness가 만든다. 공식 자료에는 timeout, exception, malformed output, retry, latency에 대한 명시적 계약이 없다.

현재 승격 결정은 `KEEP_SHADOW`다. 근거와 gate 결과는 `manifest/fixed_slm_status.json` 및 `reports/stage3_fixed_slm_report.md`에 기록한다. `production_influence=false`이므로 FixedSLM 출력은 production EvidenceGraph나 FinalDecision에 병합되지 않는다.

## SUPPORTED_INTERPRETATION

- `target`은 사람 이름으로 한정되지 않고 수신처, 채널, 앱, 장치, memory store 등이 될 수 있다.
- `redact`와 `summarize`가 platform action인지 internal transform인지 모든 경우에 동일하게 확정되지는 않는다. 현재 production은 공식 `available_actions`와 legacy FinalDecision capability를 함께 검증한다.
- `control`과 plan terminal의 일관성은 공식 schema만이 아니라 guide, dev reference, 실행 관찰이 함께 지지한다.
- current prompt가 history/memory보다 우선한다는 해석은 공식 예시와 dev 관찰이 지지하지만 모든 충돌 형태를 포괄하는 공식 우선순위 표는 없다.

## UNRESOLVED_ASSUMPTION

- 복수 sub-operation을 하나의 answer로 aggregate하는 공식 규칙
- 부분 성공 시 session/memory persistent commit 범위
- fallback의 공식 허용 edge 전체 목록
- cancel operation의 domain별 정확한 terminal mapping
- FixedSLM timeout·invalid output 처리 계약
- FixedSLM risk signal이 어떤 authority class를 갖는지에 대한 공식 순서
- `available_actions`가 internal transform까지 제한하는지 여부

이 항목은 production 결정을 새로 만들 수 없다. 관련 구현은 trace에 assumption ID를 남기거나 shadow-only로 유지한다.

## 공식 자료와 기존 문서의 충돌

| 기존 주장 | 판정 | 최종 처리 |
| --- | --- | --- |
| 모든 배열의 마지막 항목이 최신 의미를 가진다 | CONFLICTED | `turn_index`와 typed binding을 사용하고 object/record 배열 permutation을 통과해야 함 |
| FixedSLM이 FinalDecision을 생성할 수 있다 | CONFLICTED | auxiliary evidence 경계만 허용; 현재 KEEP_SHADOW |
| local score `0.8036`이 공식 재현값이다 | CONFLICTED | scorer tie fix 후 `0.8186`이 current 공식 재현값 |
| 생성 시각이 최신이면 artifact가 current다 | CONFLICTED | source/data/scorer/artifact hash 및 격리 재생성으로 판정 |
| screening 분포가 정확도 또는 priors다 | CONFLICTED | 구조 진단으로만 기록 |

## 근거 reference

- 공식 ZIP: `submission_schema.json`, `TERMS_GUIDE.md`, `SCPC2026_Final_baseline.ipynb` cells 0, 5, 11
- production call graph: `run_submission.py:33`, `harness.py:31`, `harness.py:88`, `harness.py:110`
- pure projection: `core/production_projection.py:28`, `core/projection_compilers.py`
- artifact content validation: `build_manifest.py:118`, `validate_artifacts.py:26`
- FixedSLM 결정: `manifest/fixed_slm_status.json`
