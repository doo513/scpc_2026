# SCPC Official Dev Hard Gate Remediation Report

Date: 2026-07-12  
Status: `SUPERSEDED_STALE`

> **SUPERSEDED:** 이 문서는 source `23c090...` 후보의 과거 점수 게이트 결과다. 현재 authoritative source는 `fa0b3599...`이며, 해당 후보의 Answer-Fitting 경로가 제거되었으므로 이 문서의 `RELEASE_READY` 판정은 더 이상 유효하지 않다. 현재 판정은 `reperence/structural_integrity_refactor_report.md`와 `implementation_checkpoint.md`를 따른다.

## Outcome

아래 내용은 superseded source `23c090...`의 역사적 실행 결과로만 보존한다.

| Measure | Baseline | Final | Gate |
| --- | ---: | ---: | ---: |
| Overall | 0.8417 | 0.9450 | >= 0.9421 |
| Exact | 15 | 117 | diagnostic target 117 |
| Non-exact | 105 | 3 | <= 10 |
| Focal | 1.0000 | 1.0000 | 1.0000 |
| Target | 0.9417 | 0.9750 | >= 0.9750 |
| Control | 0.9583 | 1.0000 | >= 0.9917 |
| Content scope | 0.7482 | 0.9750 | >= 0.9750 |
| Policy | 0.7171 | 0.9750 | >= 0.9643 |
| Plan | 0.8656 | 0.9750 | >= 0.9750 |

All hard-gate checks pass. The final overall is slightly higher than the plan estimate because the control axis reached `1.0000`.

## Rollback baseline

The 102-file source baseline was preserved before implementation:

- Source hash: `f3254e51961434feae2797da1e138d17f3dab90bc930f69e3ad85238b4d55b94`
- ZIP: `reperence/checkpoints/f3254e51961434feae2797da1e138d17f3dab90bc930f69e3ad85238b4d55b94.zip`
- ZIP SHA-256: `70729cc69b2cbb8157c3f67cd04af42203124bbd03364fea6be29edaea4bef0b`

The historical `causal_chain_revalidation_report.md` was not edited; its SHA-256 remains `bfa0c6442967e9f0cfa1c1967ae90b1b982e5aefc0493b9e17fad8e4eec7554e`.

## Implementation summary

### Policy projection

`FinalDecisionBuilder` now projects only the canonical public signals derived from typed records and the final target/control. Internal constraint and gate names no longer leak into `risk_flags` or `violations`. Policy confirmation is limited to `ask`, or executable target ambiguity.

### Scope and plan

Scope modes and field lists now follow the canonical profiles for `none`, `status_only`, `summary`, `redacted`, and `raw`. File and personal-note exclusions use the documented focal-content taxonomy. Hold, ask, amend, and local-update plans emit the public plan ontology and canonical plan arguments; multiple exclusions use `sensitive_fields`.

### Control, target, and memory

- Consent withdrawal, security alert, safety mode, and decisive stop remain absolute hard blocks.
- Explicit clarification can resolve a share restriction into `ask` but cannot bypass absolute blocks.
- Standing enterprise policy and verified prior-result memory produce redacted amendment rather than unconditional clarification.
- Memory rejection keeps the recalled identity and adds a target-reconfirmation requirement.
- Clarification unrelated to target identity preserves a confirmed target.
- Missing persistent-memory values remain unavailable and are never inferred.

### Architecture and release safeguards

The AST gate scans production sources for dev-answer markers, task/session-specific identifier branches, and prompt-sized literals. The release gate verifies the reachable sequence `DecisionEngine.decide -> ProductionProjectionPipeline.compile -> ConsistencyValidator.validate_or_warn -> AtomicSessionCommitter.commit` and requires the full test suite to pass.

FixedSLM remains `KEEP_SHADOW` with zero production influence. No `scpc_Gparser` discovery/copy path or external API dependency exists in current production/report/release commands.

## Remaining three cases

The only non-exact cases are:

- `final_dev_6903fe98eb6a`
- `final_dev_511b1dc0b84d`
- `final_dev_a7f2a443f654`

Each is counted by the trace as `REQUIRED_MEMORY_UNAVAILABLE`. The required value is absent from the visible task/session input, so the implementation intentionally does not manufacture the reference target or memory content.

## Verification evidence

- WSL Python 3.12: `python -m ruff check .` passed.
- Full pytest: `246 passed`.
- Without the hard-gate test: `245 passed, 1 deselected`.
- Official/local scorer parity: identical overall and axes.
- Release gate: `PASS`; production release allowed.
- Submission reproduction: byte-identical.
- Dev metrics reproduction: identical.
- Nine reports and candidate manifest fingerprint: independently reproduced.

## Final hashes

- Source tree: `23c090b978b0c432e1c4b77cf0afeae9ab3a7ff6e2d5ffde4ec66134ec013c77`
- Submission: `f2791ae6a3ebd78007a7a04a7cb05f1d1bbf5465a9605141585e402c81ec8a9c`
- Candidate manifest file: `21d23c100e9a41a513f6bcf83509eb8bb3e3e37763c843a1bec56bdfa9cba389`
- Candidate content fingerprint: `c143a06c087faa1f977f7feb7ca1d6b2f495e6e442ed993a433569f55c03cae9`

이 문장의 원래 release 결론은 superseded source에만 해당하며 현재 release authority는 없다.
