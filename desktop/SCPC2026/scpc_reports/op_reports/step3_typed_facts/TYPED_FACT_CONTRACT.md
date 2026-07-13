# Step 3 Typed Fact 및 RecordAdapter 계약

## 처리 경계

`TaskView`는 공식 입력을 `TypedObjectFact`, `TypedRecordFact`, `CapabilitySnapshot`, `SessionSnapshot`으로 변환한다. runtime evaluator, target resolver, compiler는 raw record `value`를 읽지 않는다.

## FactStatus

| 상태 | 의미 |
| --- | --- |
| `PRESENT` | adapter 검증을 통과한 현재 fact |
| `MISSING` | 입력 필드 또는 요청한 record가 없음 |
| `UNKNOWN` | type은 알지만 value vocabulary를 해석하지 못함 |
| `CONFLICTED` | 비교 가능한 chronology 없이 값이 충돌함 |
| `INVALID` | shape, JSON 값 또는 chronology 형식이 잘못됨 |
| `NOT_APPLICABLE` | 해당 후보·도메인에 적용되지 않음 |

## Chronology

`turn_index`, `turn`, `timestamp`, `updated_at`, `created_at`은 각각 별도 domain이다. 동일 domain과 동일 value kind인 경우에만 비교하며, 배열 위치는 최신성 근거로 사용하지 않는다.

## Adapter Registry

| Record type | Unknown policy | Contract status |
| --- | --- | --- |
| `ambiguous_focal` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `ambiguous_target` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `amount_changed` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `calendar_conflict` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `consent` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `current_request_hint` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `dispatch_authority_check` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `duration_ambiguous` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `enterprise_policy_recall` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `external_share_policy` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `focal_marker_refs` | `reject_invalid` | `SUPPORTED_INTERPRETATION` |
| `focal_resolution_trace` | `reject_invalid` | `SUPPORTED_INTERPRETATION` |
| `guardrail_ladder_signal` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `guest_mode` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `health_share_policy` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `memory_conflict` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `merchant_verification` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `ops_memory_recall` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `payment_policy` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `persistent_memory_recall` | `reject_invalid` | `SUPPORTED_INTERPRETATION` |
| `persistent_memory_write` | `reject_invalid` | `SUPPORTED_INTERPRETATION` |
| `privacy_guard` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `resolved_target` | `accept_reference` | `SUPPORTED_INTERPRETATION` |
| `route_binding_order` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `route_candidate_snapshot` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `routine_scope` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `safety_mode` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `security_alert` | `accept_presence` | `SUPPORTED_INTERPRETATION` |
| `session_share_policy` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `share_boundary_update` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `target_changed_after_turn` | `accept_reference` | `SUPPORTED_INTERPRETATION` |
| `temporary_override_allowed` | `mark_unknown` | `SUPPORTED_INTERPRETATION` |
| `trusted_subscription` | `accept_reference` | `SUPPORTED_INTERPRETATION` |
| `verified_internal_target` | `accept_presence` | `SUPPORTED_INTERPRETATION` |

구조화된 record token의 의미 연결은 공식 용어집과 공개 데이터에서 확인된 범위의 `SUPPORTED_INTERPRETATION`으로 관리한다. unknown token은 default action이나 target으로 변환하지 않는다.
