# Step 6 Blueprint·FinalPlanRequirements 계약

## 구성 순서

exact RulePack을 조회한 뒤 BasePlanBlueprint를 먼저 로드한다. Role과 Information을 평가하고 Global·Pair constraint를 활성화한 뒤에만 effect를 합성해 FinalPlanRequirements를 만든다. 전체 capability와 CandidateEvaluator는 그 이후 단계다.

## 단일 의미 소유권

BasePlanBlueprint는 base semantic terminal과 요구 사항을 소유한다. PlanRequirementComposer는 활성 constraint effect 또는 authorization reference가 있는 modification만 canonical delta로 합성한다. Compiler는 FinalPlanRequirements에 없는 의미를 추가할 수 없다.

## 타입 경계

platform capability와 internal requirement를 별도 enum과 필드로 유지한다. `available_actions`의 공식 적용 범위는 unresolved assumption으로 남긴다.

## 단계 잠금

Step 6 registry는 shadow-only다. Step 7 constraint activation과 Step 8 evaluator가 완료되기 전에는 production decision path에 연결하지 않는다. 따라서 이 단계의 consumer 일치는 new-path DTO 계약의 일치이며 production 전환 완료를 뜻하지 않는다.
