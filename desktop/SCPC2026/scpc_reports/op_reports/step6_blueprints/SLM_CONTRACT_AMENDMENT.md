# SLM 통합 계약 수정

- SLM은 ambiguity trigger에서만 낮은 authority proposal을 추가한다.
- validation, merge, influence 상태를 서로 다른 축으로 유지한다.
- 검증 직후 proposal은 `PROPOSED`이며 확정 Evidence가 아니다.
- semantic proposal은 entity reference가 없어도 되며 reference proposal만 기존 ID 검증을 요구한다.
- exact RulePack이 없으면 `UNSUPPORTED_RULEPACK`으로 거절하고 유사 pack이나 dispatch로 대체하지 않는다.
- authority는 같은 semantic slot, scope, target 안에서 축별 partial order로만 비교한다.
- SLM 실패는 disposition을 직접 만들지 않는다. parser-only disposition을 별도 trace로 기록한다.
- 현재 repository에는 SLM runtime이 없으므로 adapter나 모델 dependency를 추가하지 않았다.
