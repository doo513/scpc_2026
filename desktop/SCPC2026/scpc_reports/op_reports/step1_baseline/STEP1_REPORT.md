# Step 1 현재 상태 재검증 보고서

## 실행 범위

본 단계는 현재 소스, 공식 데이터, scorer, schema와 생성 산출물을 같은 환경에서 재실행해 기준선을 고정했다. 기존 보고서의 수치는 재사용하지 않았다.

## 재현 명령

```bash
/home/doo33/.venv/bin/python step1_baseline.py
```

## 검증된 사실

- source SHA-256: `e7eb0149dd914338c966ff2abb1abbf04defdc975d79a38a076a36f330d1959a`
- data aggregate SHA-256: `597cc3bbf3e1f2d631d76f8e46fc7144602aa4f4ec3d222a1427e45003278e06`
- config SHA-256: `a9ef5e9909ebbb2cc8cb455e820926554569a3280208d172d80f41889bdd98a1`
- registry/ontology snapshot SHA-256: `46b28bc31be864ec46acdc5c8cefe66c37a330eea2ba1493dad64930dda75428`
- generated submission SHA-256: `bef9b996db7c883e26ea2c6bf595b4f4ea8597dd0f5b61913dc2d8ab87e241f0`
- dev overall: `0.8036`
- exact match: `15 / 120`
- non-exact: `105`
- screening submission answers: `700`

## 필드별 dev 오류

- content_scope: 79
- control: 5
- plan: 49
- policy: 99
- target: 8

## 테스트와 검증

- 전체 pytest: exit `1`, 1 failed, 51 passed
- 알려진 dev gate 제외: exit `0`, 51 passed, 1 deselected
- generated submission validation: `PASS`
- reference manifest data hash: `PASS`

전체 pytest의 유일한 실패는 현재 dev hard gate다. 이 실패는 Step 1에서 재현된 baseline debt로 유지하며 통과로 표기하지 않는다.

## 기존 산출물 상태

- 기존 artifact validator: `STALE`
- 기존 manifest source hash 일치: `False`
- 기존 manifest dev 수치 일치: `False`
- 기존 dev report 수치 일치: `False`
- 기존 submission이 최신 source보다 오래됨: `True`

기존 `reports/`, `submission.csv`, candidate manifest는 삭제하거나 덮어쓰지 않았으며 stale 기준 자산으로 분리했다.

## 진단 재검증

- 일반화된 DomainOperationRulePack Registry: 존재하지 않음. `BlueprintRegistry`와 enum/record catalog만 부분적으로 존재한다.
- Compiler raw state 재조회: 현재 Scope/Policy/Plan compiler는 FinalDecision만 입력받으므로 해당 주장은 재현되지 않았다.
- validation-before-commit: 현재 single-task production 경로는 commit 후 validator를 호출하므로 충족되지 않는다.
- generic user execution target: TargetResolver의 일반 user fallback은 제거되어 있다. user는 clarification/stop/unresolved output에만 사용된다.
- plan capability/plan 생성 중복: blueprint capability와 FinalDecisionBuilder의 plan branch가 병존하므로 부분적으로 재현된다. 현재는 verb equality assertion으로 불일치를 차단한다.
- 기존 manifest/report: 현재 source 및 dev 실행값과 불일치해 stale이다.

## 공식 계약·해석·가정

- `CONFIRMED_CONTRACT`: 공식 schema, task/answer ID 집합, 제공 scorer 입력과 공식 데이터 hash.
- `SUPPORTED_INTERPRETATION`: current compiler가 FinalDecision의 pure projection이라는 코드·테스트 기반 판단.
- `UNRESOLVED_ASSUMPTION`: 8건. 상세는 `assumptions.json`에 기록했다.

## Step 1 Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- 재현 명령, current hash, generated artifact validation과 stage-specific test가 일치한다.
- 전체 pytest의 dev hard gate 실패 1건은 해결되지 않은 baseline debt로 고정한다.
- 기존 report/submission/manifest는 current baseline과 분리해 stale로 표시했다.

Step 1은 기준선 재현과 stale 분리를 완료했다. dev hard gate 실패는 해결된 것으로 간주하지 않으며 이후 단계의 shadow baseline debt로 유지한다.
