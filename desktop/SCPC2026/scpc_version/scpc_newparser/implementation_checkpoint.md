# Implementation Checkpoint

Updated: 2026-07-12 (test stability and logical scope round)

## Current status

- Task: strict structural-integrity and anti-reward-hacking audit
- Implementation state: `LOGICAL_VALIDITY_TEST_STABILITY_COMPLETE`
- Release state: `RELEASE_BLOCKED_STALE_ARTIFACTS_NO_PROMOTION`
- Reason: code-level required checks pass, but current submission and candidate manifest do not match the current source hash. Artifact validation and promotion were not invoked.
- FixedSLM: `KEEP_SHADOW`, production influence `false`
- Dev score: diagnostic only and excluded from success criteria

## Current hashes

- Source tree SHA-256: `1ee0a4ef2396b2a0c1c63f3f821491a947100f7b90104ef61fa9bd140a1397de`
- Structural screening submission SHA-256: `e93a3eed8bc9bb6d4f124d1c77bb817af70dadea67806b30921d00988622076e`
- Stale prior submission SHA-256: `f2791ae6a3ebd78007a7a04a7cb05f1d1bbf5465a9605141585e402c81ec8a9c`
- Stale prior manifest file SHA-256: `21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389`
- Stale prior manifest source SHA-256: `23c090b978b0c432e1c4b77cf0afeae9ab3a7ff6e2d5ffde4ec66134ec013c77`

## Completed strict changes

- Removed `FinalDecisionBuilder._uses_canonical_plan` expected-value substitution.
- Renamed the production validator entry point to `validate_strict` and removed warning/relaxation state.
- Removed historical-current-object exemption, canonical amend exemptions, summary-to-redaction substitution, named scope guard whitelist, and unavailable-capability filtering.
- Converted field-exclusion provenance warnings to hard failures.
- Removed the focal-type/record-code/evidence-count branch tree from `_safe_scope_mode`.
- Scope authority is now limited to active HARD constraints, finalized control, and compiled `EffectiveBlueprint.scope_mode`.
- Removed the generic amend `read -> redact -> dispatch` plan override.
- Removed the local-boundary record override that changed a selected dispatch into an update.
- Mandatory unavailable plan capabilities now raise instead of disappearing.
- Removed `safe_visible_fallback`, rejected-memory target reuse, health HARD demotion, and unconfirmed record-combination auto-amend paths.
- Disclosure exclusions now come from versioned typed property provenance covering declared `contains`/`fields` entries and unknown direct attrs.
- Expanded the AST audit to root scripts, submission orchestration, scorers, and every utils module.

## Captured strict errors

1. Full screening entry point before structural fixes:
   `ValueError: exclusion 'numeric_value' has no focal-field provenance`
2. Independent amend reproduction before structural fixes:
   `ValueError: resolved plan diverges from final capability contract: expected=('read', 'verify', 'toggle') emitted=('read', 'redact', 'dispatch')`

Raw trace: `reperence/strict_runtime_error_trace.txt`

## Previous-round validation (superseded by latest evidence below)

- Screening 700 tasks under current strict pipeline: passed
- Structural submission generated: `reperence/structural_screening_submission.csv`
- Pytest excluding score-only gate: `247 passed, 1 deselected`
- Full pytest: `247 passed, 1 failed`
- Sole failure: score-only dev gate, diagnostic `0.8523 < 0.9421`
- Ruff on changed files: passed
- Expanded AST audit: 69 files scanned, 43 authoritative runtime files, 0 runtime specificity hits
- Synthetic `financial_ledger × account_password`: previously ran and excluded the field without a HARD constraint; fixed in the latest round
- `validate_artifacts.py`: fails closed with `candidate manifest source hash is stale`

## Current criteria status

- Criteria A(a), screening 700 execution: `EXECUTED_PASS`
- Criteria A(b), requested unknown type/field fail-closed policy: `EXECUTED_PASS_FOR_GENERATED_COUNTEREXAMPLES`
- Criteria B(a), current output strict validation: `EXECUTED_PASS`
- Criteria B(b), every valid input has a legal decision: `UNRESOLVED_CONTRACT`
- Criteria C, activated HARD propagation: `RUNTIME_INVARIANT`; universal semantic HARD discovery remains unproven

The official materials do not provide an exhaustive input schema or universal semantic oracle. See `structural_criteria.md` for the evidence boundary.

## Output artifacts

- `reperence/structural_integrity_refactor_report.md`
- `reperence/strict_runtime_error_trace.txt`
- `reperence/anti_reward_hacking_audit.json`
- `reperence/structural_screening_submission.csv`
- `reperence/structural_integrity_f1_f2_f3_evidence_17d0d617.md`

## Next safe execution point

Review `reperence/test_stability_logicality_report.md`. Regenerate submission and reports from source `1ee0a4ef...` only in a separate artifact round, then validate a staged current-source candidate manifest. Do not promote the existing stale manifest.

## Latest test-stability evidence

- ASK now preserves a safe compiled summary/redaction scope while its plan remains non-executing; raw is capped to summary and status-only is suppressed to none.
- The property disclosure matrix validates totality, monotone restriction, and UNKNOWN/HARD/NONE at import, in tests, and in the release semantic gate.
- The dev threshold remains measured across all 120 tasks but is explicitly non-release-blocking; no scorer, answer, threshold, or task exclusion was changed.
- Full pytest: `278 passed`; Ruff: passed.
- Dev diagnostic: `0.8590 < 0.9421`, improvement `+0.0107`, still non-blocking.
- Screening: `700/700`; HARD projection violations: `0`.
- Code-level release check contract: `14/14 true`; runtime specificity hits: `0`.
- Candidate manifest and submission hashes remained unchanged; publish/validate/promote were not invoked.

## Latest counterexample remediation checkpoint

- `contains` and `fields` inventories are merged; an empty `contains` cannot shadow `fields`.
- Direct attrs on unknown object types are classified `UNKNOWN`; universal `ref_code` remains structural metadata.
- The existing property owner now maps PUBLIC/INTERNAL/RESTRICTED/SECRET/UNKNOWN to allow/summary/redaction/block effects.
- Projection exclusions now come from that policy instead of excluding every declared field by mode.
- `ConsistencyValidator.validate_strict` accepts only frozen `FinalDecision` authority, never a mutable mapping.
- Release semantic checks now execute the merged-inventory, SECRET-policy, unknown-object direct-attr, immutable-tampering, and mutable-authority counterexamples.
- Targeted pytest: `56 passed`.
- Targeted Ruff: passed.
- Release semantic counterexamples: `6/6 true`.
- Manifest and submission were not changed or promoted.
- Required pytest: `267 passed, 1 deselected`.
- Full pytest: `267 passed, 1 failed`; only `test_dev_score_diagnostics` failed at `0.8483 < 0.9421`.
- Screening: `700/700` answers and traces produced; HARD projection violations `0`.
- Screening answer semantic SHA-256: `e07201d7304dfe1fe73cb16e402d0289367eb77399c01d4c6539869001e119fe`.
- Code-level release check contract: `13/13 PASS` (read-only evaluation).
- Current candidate manifest source hash: `23c090b9...` (stale against `d215faff...`).
- Final report: `reperence/logical_validity_remediation_report.md`.

## Latest F1/F2/F3 remediation evidence

- Required release checks now have a fixed ID contract and include executable F1/F2 semantic checks.
- A false release result performs no staged publish, artifact validation, or promotion; the isolated true path preserves publish -> validate -> promote ordering.
- Strict validation now compares public output and serialized trace to the immutable FinalDecision authority supplied by production.
- Property classification facts and disclosure policy effects are separate typed contracts. Unknown declared fields, unknown direct attrs, and unknown object types fail closed for outbound disclosure.
- Official attrs-only objects are not treated as inventory anomalies.
- Criteria A/B/C contract status is explicit in `structural_criteria.md`.
- Dev-score and required structural assertions are split; dev score is diagnostic only.
- Structural/runtime pytest: `260 passed, 1 deselected`.
- Diagnostic-inclusive pytest: `260 passed, 1 failed`; sole failure remains `0.8523 < 0.9421`.
- Screening 700 output is byte-identical to the pre-round structural artifact (`e93a3eed...`), with zero changed tasks.
- Ruff passed; expanded AST audit scanned 70 files and reported zero authoritative runtime specificity hits.
- Candidate manifest SHA-256 remained `21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389`.
