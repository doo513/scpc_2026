# Performance and Logical Remediation Evidence

Date: 2026-07-12  
Target: `scpc_reparser_clean_20260712`  
Runtime source SHA-256: `4454fcebe5d20741987010712c460ef59dc5de4bd0ce22641bae14192123aff7`

No release artifact was promoted and `scpc_newparser` was not modified.

## Implemented causes

1. Concrete property inventory and public policy exclusions are separate.
   `PolicyExclusion` carries versioned source IDs; strict validation independently
   recompiles the expected policy exclusions.
2. Production `ScopeProjection` rejects duplicate fields and any
   allowed/excluded intersection.
3. `enterprise_policy_recall` and `ops_memory_recall` retain typed values and
   compile to scoped AMEND effects instead of unconditional presence-based ASK.
4. A HARD-blocked execution with an explicit confirmation request remains HARD,
   while a separate non-executing clarification gate selects ASK.
5. Recalled target identity is retained as untrusted identity; it is not treated
   as execution authority.
6. A typed local boundary for a file creates a local-update candidate upstream.
   The intended destination remains traceable but is not executed.
7. Public policy flags now require constraint/effect causes instead of being
   generated solely from a final control label.
8. Non-executing plans are selected from the finalized Blueprint capability
   contract (`read/guard` or `read/clarify`), not reconstructed from control.

## Executed counterexamples

### Policy exclusion without a concrete property

`final_dev_7286d93e3d0f` has no concrete disclosure inventory.

```json
{
  "control": "proceed",
  "mode": "status_only",
  "allowed_fields": ["status"],
  "excluded_fields": ["location", "numeric_value", "raw_quote"],
  "provenance": "policy:session_share_policy:strict:scpc.policy-exclusion.v1"
}
```

The strict validator accepted this answer using independently recompiled policy
provenance. It no longer pretends that these categories are concrete attrs.

### HARD execution plus clarification

Both `final_dev_891dd2e62a0a` and `final_dev_5181075801a4` produced:

```text
active health_external_share_blocked = HARD
selected interaction                 = blocked_execution_clarification
control                              = ask
target                               = user
plan                                 = read -> clarify
execution events                     = 0
```

### Typed recall semantics

```text
final_dev_7add02f9e8b8  ops recall        -> amend, redacted, dispatch
final_dev_c2ab61cbcfa6  enterprise recall -> amend, redacted, dispatch
```

### Local-boundary operation

```text
final_dev_b0696e0a0b55  action=local_update target=project_room
final_dev_d2a3fd50f334  action=local_update target=vendor_alpha
plan for both           read -> verify -> update
```

### Target identity versus authority

`final_dev_1dbd7642dad4` now retains `security_review` while returning ASK; no
execution plan is emitted.

## Verification

```text
Ruff:                    All checks passed
Full pytest:             281 passed
Official/local parity:   identical=true
Screening execution:     700/700
Scope overlap:           0
Screening answer SHA:    46fc9186b5e04bd2a4a6d5592de27c46ff47821bca1ade9cde6b0e518e43da9e
```

Official dev diagnostic, before -> after:

| Metric | Before | After |
|---|---:|---:|
| overall | 0.8590 | 0.9185 |
| focal | 1.0000 | 1.0000 |
| target | 0.9500 | 0.9750 |
| control | 0.9417 | 0.9917 |
| content_scope | 0.7099 | 0.8834 |
| policy | 0.8890 | 0.9346 |
| plan | 0.8844 | 0.9519 |
| exact | 21/120 | 46/120 |

## Remaining observable limits

- Three official target values have no matching memory write in the public dev
  inputs. The diagnostic identifies these as input-visibility gaps; no value was
  fabricated.
- The non-blocking dev diagnostic remains below its historical threshold. This
  report does not make a RELEASE_READY decision.
- Existing `submission.csv`/manifest artifacts were not regenerated or promoted.
