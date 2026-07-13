# SCPC Coparser

Deterministic `scpc.final.answer.v1` harness for the SCPC 2026 final task format.

## Architecture

```text
TaskView -> StateAssembler
-> FocalCandidate + CoarseIntent joint resolution
-> DomainContext + OperationIntent
-> ActionTargetPair -> InformationStatus -> CapabilityStatus
-> pair-specific ConstraintActivation -> AuthorizedFallbackSolver
-> FinalDecision
-> ScopeCompiler -> PolicyCompiler -> PlanCompiler -> ResponseBuilder
-> ConsistencyValidator -> answer JSON
```

Directly extracted records, relations, and intent evidence retain provenance. Derived
candidate and decision objects retain `derived_from` identifiers instead of claiming
source spans. Records create candidate-scoped constraints; they do not emit control
labels directly.

`FinalHarness.answer_task(task, session)` performs no filesystem or network I/O. The runner owns task ordering, traces, reports, validation, and CSV output.

## Data

Set `SCPC_DATA_DIR` to the directory containing the three JSON data files, place an extracted `data/` directory near the project, or place `SCPC2026_Final_data.zip` in the project directory. ZIP-only runs extract into the ignored `.cache/scpc_data/` directory.

## Commands

```bash
python3 -m pip install -r requirements.txt
pytest -q
python3 local_score.py
python3 analyze_dev_errors.py
python3 run_submission.py
python3 validate_submission.py submission.csv
python3 generate_reports.py
python3 validate_artifacts.py
```

`tests/specs/generalization_v1.json` makes the complete official dev score a hard
floor without score exclusions. Metamorphic, domain matrix, constraint
counterfactual, session lifecycle, evidence ablation, schema parity, and artifact
freshness checks are separate gates. Screening focal statistics remain structural
coverage checks because screening labels are unavailable.

The public dev scorer cannot score `user_response`; its `semantic_response` axis remains zero. Screening distributions are reported only for diagnostics and are never used as inference priors.
