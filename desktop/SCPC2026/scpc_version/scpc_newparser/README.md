# SCPC New Parser

Deterministic `scpc.final.answer.v1` harness for the SCPC 2026 final task format.

## Architecture

```text
TaskView -> StateAssembler
-> FocalCandidate + CoarseIntent joint resolution
-> DomainContext + OperationIntent
-> ActionTargetPair -> InformationStatus -> CapabilityStatus
-> pair-specific ConstraintActivation -> AuthorizedFallbackSolver
-> FinalDecision
-> locked DecisionProjection DTO -> production ProjectionCompiler
-> ConsistencyValidator
-> AtomicSessionCommitter -> answer JSON
```

Directly extracted records, relations, and intent evidence retain provenance. Derived
candidate and decision objects retain `derived_from` identifiers instead of claiming
source spans. Records create candidate-scoped constraints; they do not emit control
labels directly.

`FinalHarness.answer_task(task, session)` performs no filesystem or network I/O.
Scope, policy, and plan compilers receive projection DTOs only; they cannot read
the prompt, records, session, candidates, or RulePack. Validation completes before
session or memory mutation, and the in-process commit is all-or-nothing.

The typed RulePack/Candidate/DecisionBundle semantic replacement has not passed
the official dev release gate and therefore remains shadow-only. The current
authoritative semantic owner is `FinalDecision`; keeping the shadow types in the
repository does not authorize them to influence production answers.

FixedSLM is explicitly `KEEP_SHADOW`. Its official facade is documented for
experimentation, but it has zero production evidence influence until every Stage 3
promotion gate passes.

## Data

All reproducibility inputs must be inside this project directory. Place the three
official JSON files under `data/`, or place `SCPC2026_Final_data.zip` at the
project root. ZIP-only runs extract into the ignored `.cache/scpc_data/`
directory. `SCPC_DATA_DIR`, when set, is rejected unless it resolves inside the
project.

The official archive may also be stored at
`reperence/SCPC2026_Final_data.zip`. The baseline used by
`diff_vs_baseline.md` is regenerated directly from the official notebook in
that archive and stored at
`reference/official_notebook_baseline/submission.csv`.
`SCPC_BASELINE_SUBMISSION`, when set, is restricted to an in-project path.
Parent-directory and sibling repository discovery are intentionally
unsupported. Isolated artifact reproduction uses the in-project
`.reproduction/` directory and removes it on completion.

## Commands

```bash
python3 -m pip install -r requirements.txt
pytest -q
python3 local_score.py
python3 analyze_dev_errors.py
python3 run_submission.py
python3 validate_submission.py submission.csv
python3 generate_reports.py
python3 validate_artifacts.py --reproduce
```

`tests/specs/generalization_v1.json` makes the complete official dev score a hard
floor without score exclusions. Metamorphic, domain matrix, constraint
counterfactual, session lifecycle, evidence ablation, schema parity, and artifact
content/source/data/scorer hash freshness checks are separate gates; timestamps
are informational only. Screening focal statistics remain structural
coverage checks because screening labels are unavailable.

The public dev scorer cannot score `user_response`; its `semantic_response` axis remains zero. Screening distributions are reported only for diagnostics and are never used as inference priors.
