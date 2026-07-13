# Step 4 Surface Parser·LanguageRuleRegistry·Context Binder 계약

## Surface Parser

Parser는 `ClauseSpan`, `QuotationSpan`, `NegationSpan`, `PredicateFrame`, `ArgumentSpan`, `CorrectionRelation`, `SupersessionRelation`, `ReferenceMention`을 생성한다. 이 객체는 Evidence 후보의 source span을 제공하며 action, target, control을 확정하지 않는다.

## LanguageRuleRegistry

모든 규칙은 typed metadata와 contract status를 가진다. `priority`는 같은 scope, semantic slot, source span의 중복 proposal을 정리할 때만 사용한다. Registry 출력은 `RuleEvidenceProposal`로 제한한다.

기존 판정과의 무회귀를 위해 compatibility feature detector를 Registry 내부 production evidence 경로로 유지한다. surface-native proposal은 shadow trace로 비교하며, 향후 vertical slice gate 전에는 임의로 최종 후보를 바꾸지 않는다.

## Context Binder

Binder는 semantic slot과 subject가 같은 Evidence 사이에서만 현재 prompt의 명시적 부정·정정을 적용한다. 서로 다른 slot은 독립적으로 보존하며, TypedFact와 hard constraint는 자연어 authority 순위에 참여하지 않는다.

## Correction과 Fallback

`A하지 말고 B`는 correction 및 supersession 후보로 분류한다. `A가 안 되면 B`처럼 실패 조건이 명시된 경우에만 fallback relation과 authorization evidence를 생성한다.

## Fixed SLM

현재 저장소에는 Fixed SLM runtime이 없으므로 새 모델과 외부 의존성을 추가하지 않았다.
