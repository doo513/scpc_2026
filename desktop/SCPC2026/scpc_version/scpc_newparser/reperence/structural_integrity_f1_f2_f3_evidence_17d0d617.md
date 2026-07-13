# F1/F2/F3 Structural Integrity Execution Evidence

- generated: 2026-07-12 KST
- source tree SHA-256: `17d0d61754b84d6120b83d5e14892975462c59677837b9ed6866b9f872e1dd1c`
- artifact role: `NON_RELEASE_AUTHORITY`
- release conclusion: `NOT_EVALUATED`
- promotion invoked during this round: `false`
- authoritative candidate manifest SHA-256 before/after: `21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389`

## F1 — property classification and fail-closed disclosure

### Code locations

- typed property/provenance contract: `core/property_policy.py:27`
- classification facts and object attr roles: `core/property_policy.py:64`
- disclosure rule effect: `core/property_policy.py:176`
- focal property inventory: `core/task_view.py:259`
- HARD activation: `core/decision.py:1355`
- disclosure exclusion projection: `core/decision.py:2423`
- provenance validation: `core/consistency.py:254`

### Executed counterexamples

Command: synthetic tasks through `FinalHarness.answer_task(..., commit=False)`.

| input | property source | classification | excluded fields | active constraint | control/mode |
| --- | --- | --- | --- | --- | --- |
| `contains=["account_password"]` | `contains` | `unknown` | `account_password` | `unknown_property_disclosure`, `hard`, `block_execution` | `hold/none` |
| `attrs.account_password` without contains/fields | `direct_attr` | `unknown` | `account_password` | `unknown_property_disclosure`, `hard`, `block_execution` | `hold/none` |
| `contains=["novel_field_123"]` | `contains` | `unknown` | `novel_field_123` | `unknown_property_disclosure`, `hard`, `block_execution` | `hold/none` |
| `attrs.novel_field_123` without contains/fields | `direct_attr` | `unknown` | `novel_field_123` | `unknown_property_disclosure`, `hard`, `block_execution` | `hold/none` |

Observed provenance examples:

```text
property:obj_release_check:contains:account_password:scpc.property-metadata.v1
property:obj_release_check:direct_attr:account_password:scpc.property-metadata.v1
property:obj_release_check:contains:novel_field_123:scpc.property-metadata.v1
property:obj_release_check:direct_attr:novel_field_123:scpc.property-metadata.v1
```

Unknown object type counterexample: `novel_object_type` with the otherwise known field `summary` produced `classification=unknown`, `control=hold`, `mode=none`, and excluded `summary`.

Official attrs-only control case: a `message` containing only the known attrs `body`, `recipient`, `ref_code`, and `thread_id` did not activate `unknown_property_disclosure`.

Tests:

```text
tests/test_safety_invariants.py:322  test_unknown_properties_fail_closed_with_typed_provenance
tests/test_safety_invariants.py:388  test_unknown_object_type_fails_closed_even_with_known_field_name
targeted result: 9 passed, 21 deselected
```

## F2 — scope/trace same-source tampering

### Code locations

- immutable authority selection and trace comparison: `core/consistency.py:62-71`
- scope mode derived from authority Blueprint/control: `core/consistency.py:100-106`
- production passes the in-memory `FinalDecision`: `harness.py:87`

### Executed counterexample

1. Produced an answer with `effective_blueprint.scope_mode=summary`.
2. Changed public `content_scope.mode` to `raw`.
3. Changed serialized `final_trace.disclosure.mode` to `raw` at the same time.
4. Passed the original immutable FinalDecision authority to `validate_strict`.

Observed result:

```text
ValueError: serialized FinalDecision trace differs from authority;
content_scope is not a pure FinalDecision projection
```

Release semantic check result:

```json
{
  "scope_trace_tampering_rejected": true
}
```

Test: `tests/test_safety_invariants.py:224`.

### Same-source authority audit

Before this round, focal, target, control, scope, policy, plan events, and plan capabilities were all compared against the mutable serialized `final_trace`. This was not limited to scope; policy and plan were additional instances of the same authority pattern.

After this round:

| public field | validator expected authority |
| --- | --- |
| focal/target/control | immutable in-memory FinalDecision or its preserved copy |
| scope mode | immutable FinalDecision control + EffectiveBlueprint |
| scope fields/confirmation | immutable FinalDecision disclosure contract |
| policy | immutable FinalDecision policy fields |
| plan events/capabilities | immutable FinalDecision plan contract |
| serialized final trace | exact equality with immutable FinalDecision trace |

Policy+trace simultaneous tampering was separately rejected by `tests/test_safety_invariants.py:261` with `serialized FinalDecision trace differs from authority`.

No remaining production `ConsistencyValidator` expected-value comparison reads mutable `final_trace` except the explicit equality comparison against the immutable authority. `core/shadow_validation.py` contains a separate shadow-model consistency calculation and does not replace the production authority passed by `FinalHarness`.

Semantic limitation: this establishes projection integrity. It does not prove that the upstream EffectiveBlueprint is semantically correct.

## F3 — failed check must not validate or promote

### Code locations

- fixed required check IDs including F1/F2: `release_gate.py:39`
- runtime F1/F2 checks: `release_gate.py:172`
- missing/unexpected/non-boolean completeness validation: `release_gate.py:239`
- promotion boundary: `release_gate.py:261`
- release computation and guarded call: `release_gate.py:706`, `release_gate.py:736`

### Executed false-check evidence

`tests/test_release_gate_analysis.py:117` set `released=False`, installed validation/promotion spies, and preserved a sentinel authoritative manifest.

```text
return value: None
validate calls: 0
promote calls: 0
authoritative manifest bytes: unchanged
pending staged manifest: absent
```

`tests/test_release_gate_analysis.py:153` exercised the isolated true path:

```text
call order: publish -> validate -> promote
pending staged manifest after return: absent
```

Targeted F3 result:

```text
2 passed, 7 deselected in 1.36s
```

Required-check contract executed with all required Boolean IDs:

```json
{
  "passed": true,
  "missing_ids": [],
  "unexpected_ids": [],
  "non_boolean_ids": []
}
```

Missing IDs and non-Boolean values have dedicated failing assertions in `tests/test_release_gate_analysis.py`.

## W4/W5 evidence

- Criteria A/B/C contract status: `structural_criteria.md`.
- required structural test: `tests/test_regression.py:23` (`focal`, absence of compatibility trace, non-empty optional outputs).
- diagnostic-only dev score test: `tests/test_regression.py:36`, marker `dev_score`.
- release exclusion selects only `-m not dev_score`; the structural test remains required.

## Regression and execution results

### Structural/runtime suite

```text
python -m pytest -q -m 'not dev_score'
260 passed, 1 deselected in 15.01s
exit code 0
```

### Diagnostic-inclusive suite

```text
python -m pytest -q
260 passed, 1 failed in 16.51s
sole failure: tests/test_regression.py::test_dev_score_diagnostics
observed diagnostic: 0.8523 < 0.9421
```

The observed `0.8523` equals the pre-round checkpoint diagnostic. It is not a release check.

### Screening 700 and output non-regression

```text
answer count before: 700
answer count after: 700
prior structural artifact SHA-256: e93a3eed8bc9bb6d4f124d1c77bb817af70dadea67806b30921d00988622076e
new temporary output SHA-256:       e93a3eed8bc9bb6d4f124d1c77bb817af70dadea67806b30921d00988622076e
changed tasks: 0
```

The temporary output was not copied to `submission.csv` and was not promoted.

### Static and anti-answer-fitting checks

```text
ruff check .: All checks passed
AST files scanned: 70
authoritative runtime files: 44
runtime specificity hits: 0
semantic checks:
  unknown_property_fail_closed: true
  scope_trace_tampering_rejected: true
```

## Contract status retained

- Official materials provide the output schema but no exhaustive input schema or universal semantic oracle.
- UNKNOWN→HARD/NONE for outbound disclosure is a project safety policy, not an official-schema claim.
- Screening 700 success is finite regression evidence, not proof for all inputs.
- No release readiness conclusion is made by this artifact.
