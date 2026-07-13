# Step 5 RulePack·RequiredRoleSpec·InformationSpec 계약

## Exact Lookup

RulePack은 `(Domain, Operation, optional RuleVariant)` typed key로만 조회한다. 미등록 key는 유사 key나 GENERAL, dispatch로 대체하지 않고 `UNSUPPORTED_RULEPACK` 상태를 보존한다.

## Role

실행 target role과 clarification authority, confirmation authority, memory owner를 분리했다. 실행 role은 interaction principal identity를 허용하지 않는다.

## Information

required, conditional, optional slot은 상호 배타적이다. derivation과 conflict는 등록된 enum만 사용하며 capability 상태를 InformationSpec에 포함하지 않는다.

## 비활성 Reference

`base_blueprint_id`와 `pair_constraint_ids`는 각각 Step 6, Step 7용 schema stub이다. Step 5 registry는 shadow-only이며 production decision path에 연결하지 않는다.
