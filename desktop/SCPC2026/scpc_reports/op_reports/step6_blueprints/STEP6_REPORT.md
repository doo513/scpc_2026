# Step 6 Blueprint·Plan Requirements 보고서

## 구현 범위

14개 exact RulePack에 대응하는 BasePlanBlueprint와 canonical FinalPlanRequirements composer를 shadow registry로 구현했다. constraint registry는 Step 7 전까지 stub으로 유지했다.

SLM 관련 변경은 상태·pipeline·authority 계약 타입과 invariant에 한정했다. SLM adapter, 모델 호출, production EvidenceGraph 병합은 구현하지 않았다.

## 구조 검증

- Blueprint: `14`개 / catalog `14`개
- semantic terminal 1개 보장: `True`
- effect permutation 동일: `True`
- production import: `0`개
- Step 7 constraint stub 유지: `True`
- SLM ACCEPTED shortcut 없음: `True`
- SLM runtime dependency: `0`개

## 회귀 검증

- Step 6 invariant: exit `0`, 58 passed
- 전체 pytest: exit `1`, 1 failed, 113 passed
- 알려진 dev gate 제외: exit `0`, 113 passed, 1 deselected
- dev overall: `0.8036` (Step 5와 동일: `True`)
- screening submission 동일: `True`

전체 pytest의 dev hard gate 1건은 기존 baseline debt다. Step 6에서 해결하거나 허용한 것으로 처리하지 않았다.

## Release Gate

- 상태: **PASS_WITH_BASELINE_DEBT**
- 다음 단계 진입 가능: **True**
- BasePlanBlueprint coverage와 FinalPlanRequirements invariant가 통과했다.
- Blueprint 선행, capability 선행 CandidateEvaluator 순서를 계약으로 고정했다.
- SLM validation·merge·influence 상태와 scoped authority를 분리했다.
- Step 5 대비 public dev 수치와 screening submission이 변하지 않았다.
