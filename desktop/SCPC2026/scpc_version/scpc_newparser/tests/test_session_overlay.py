from __future__ import annotations

from pathlib import Path

import pytest

from core.contracts import PARTIAL_COMMIT_ASSUMPTION_ID
from core.decision_ir import (
    AggregateOutputStatus,
    DecisionProjectionSet,
    PlanProjection,
    PlanProjectionStep,
    PolicyProjection,
    ScopeProjection,
)
from core.ontology import DisclosureMode, ExecutionDisposition, PlanStepType, ReasonCode
from core.projection_compilers import ProjectionCompiler, ProjectionCompilerConfig
from core.session_overlay import (
    AtomicCommitCoordinator,
    CommitEligibility,
    CommitEligibilityEvaluator,
    CommitStatus,
    CommittedSessionState,
    DecisionDispositionSet,
    InMemoryAtomicSessionStore,
    OverlayReadSource,
    ProvisionalWriteState,
    RollbackPlanValidator,
    RollbackStatus,
    SessionNamespace,
    SessionValueKey,
    SpeculativeSessionOverlay,
    ValidationResult,
    ValidationStatus,
    validate_session_overlay_contract,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG = ProjectionCompilerConfig(max_plan_events=18)
SESSION_KEY = SessionValueKey(SessionNamespace.SESSION, "last_target")
MEMORY_KEY = SessionValueKey(SessionNamespace.MEMORY, "preference")


def _projection_set(
    terminal_by_decision: dict[str, bool],
) -> DecisionProjectionSet:
    decision_ids = tuple(sorted(terminal_by_decision))
    scopes = tuple(
        ScopeProjection(
            decision_id,
            DisclosureMode.STATUS_ONLY,
            ("status",),
            (),
            False,
            (),
            f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    policies = tuple(
        PolicyProjection(
            decision_id,
            (),
            (),
            False,
            (ReasonCode.EXECUTABLE,),
            (),
            f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    plans = tuple(
        PlanProjection(
            decision_id,
            (
                PlanProjectionStep(
                    f"projection:{decision_id}",
                    f"requirement:{decision_id}",
                    (
                        PlanStepType.UPDATE
                        if terminal_by_decision[decision_id]
                        else PlanStepType.GUARD
                    ),
                    "state:session",
                    (),
                    (ReasonCode.EXECUTABLE,),
                    semantic_terminal=terminal_by_decision[decision_id],
                ),
            ),
            f"lock:{decision_id}",
        )
        for decision_id in decision_ids
    )
    return DecisionProjectionSet(
        "bundle:session",
        (
            AggregateOutputStatus.SINGLE
            if len(decision_ids) == 1
            else AggregateOutputStatus.MULTIPLE_UNRESOLVED
        ),
        scopes,
        policies,
        plans,
        "bundle-lock:session",
    )


def _plan_validation(
    overlay: SpeculativeSessionOverlay,
    terminal_by_decision: dict[str, bool],
):
    projections = _projection_set(terminal_by_decision)
    compiled = ProjectionCompiler.compile(projections, CONFIG)
    return RollbackPlanValidator.validate(
        overlay.snapshot(),
        projections,
        compiled,
    )


def _validation(*decision_ids: str, passed: bool = True) -> ValidationResult:
    return ValidationResult(
        ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        tuple(sorted(decision_ids)),
        "ConsistencyValidator",
        "sha256:synthetic-validation",
        () if passed else ("consistency_failure",),
    )


def _dispositions(**values: ExecutionDisposition) -> DecisionDispositionSet:
    return DecisionDispositionSet(tuple(sorted(values.items())))


def test_same_turn_consumer_reads_provisional_value_and_creates_dependency() -> None:
    committed = CommittedSessionState.from_values({SESSION_KEY: "old"})
    overlay = SpeculativeSessionOverlay(committed)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value={"target": "new"},
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    read = overlay.read(
        read_id="read:b",
        key=SESSION_KEY,
        consumer_decision_id="decision:b",
    )
    snapshot = overlay.snapshot()
    assert read.source == OverlayReadSource.PROVISIONAL
    assert read.thawed_value() == {"target": "new"}
    assert read.source_write_id == "write:a"
    assert len(snapshot.dependency_edges) == 1
    assert snapshot.dependency_edges[0].read_reference_id == "read:b"


def test_statement_order_without_a_read_does_not_create_dependency() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    overlay.write(
        write_id="write:b",
        key=MEMORY_KEY,
        value="b",
        producer_decision_id="decision:b",
        provenance_ids=("evidence:b",),
    )
    assert overlay.snapshot().dependency_edges == ()


def test_dependency_rollback_cascades_but_independent_write_remains_active() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    overlay.read(
        read_id="read:b",
        key=SESSION_KEY,
        consumer_decision_id="decision:b",
    )
    overlay.write(
        write_id="write:b",
        key=MEMORY_KEY,
        value="b",
        producer_decision_id="decision:b",
        provenance_ids=("evidence:b",),
    )
    independent_key = SessionValueKey(SessionNamespace.SESSION, "independent")
    overlay.write(
        write_id="write:c",
        key=independent_key,
        value="c",
        producer_decision_id="decision:c",
        provenance_ids=("evidence:c",),
    )
    affected = overlay.rollback_decision("decision:a", reason="validation_failed")
    writes = {write.write_id: write for write in overlay.snapshot().provisional_writes}
    assert affected == ("decision:a", "decision:b")
    assert writes["write:a"].rollback_status == RollbackStatus.DIRECT
    assert writes["write:b"].rollback_status == RollbackStatus.CASCADED
    assert writes["write:c"].rollback_status == RollbackStatus.NONE
    assert writes["write:c"].visible


def test_validation_failure_never_mutates_persistent_state() -> None:
    initial = CommittedSessionState.from_values({SESSION_KEY: "old"}, version=4)
    store = InMemoryAtomicSessionStore(initial)
    overlay = SpeculativeSessionOverlay(initial)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="new",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    plan_validation = _plan_validation(overlay, {"decision:a": True})
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(**{"decision:a": ExecutionDisposition.PROCEED}),
        _validation("decision:a", passed=False),
        plan_validation,
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    assert assessment.eligibility == CommitEligibility.VALIDATION_FAILED
    assert result.status == CommitStatus.REJECTED
    assert store.snapshot() == initial


def test_validation_and_committed_state_require_structural_lineage() -> None:
    with pytest.raises(ValueError, match="validator and artifact lineage"):
        ValidationResult(
            ValidationStatus.PASSED,
            ("decision:a",),
            "",
            "",
        )
    with pytest.raises(ValueError, match="frozen JSON representation"):
        CommittedSessionState(0, ((SESSION_KEY, {"mutable": True}),))


def test_validated_commit_is_atomic_and_traceable_to_decision() -> None:
    initial = CommittedSessionState.from_values({SESSION_KEY: "old"}, version=2)
    store = InMemoryAtomicSessionStore(initial)
    overlay = SpeculativeSessionOverlay(initial)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value={"target": "new"},
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(**{"decision:a": ExecutionDisposition.PROCEED}),
        _validation("decision:a"),
        _plan_validation(overlay, {"decision:a": True}),
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    found, value = store.snapshot().resolve(SESSION_KEY)
    assert assessment.eligibility == CommitEligibility.ELIGIBLE
    assert result.status == CommitStatus.COMMITTED
    assert result.state_version_before == 2
    assert result.state_version_after == 3
    assert found and value == {"target": "new"}
    assert result.decision_traces[0].decision_id == "decision:a"
    assert result.decision_traces[0].write_ids == ("write:a",)
    assert (
        overlay.snapshot().provisional_writes[0].state
        == ProvisionalWriteState.COMMITTED
    )


def test_persistent_write_failure_leaves_entire_commit_unit_unchanged() -> None:
    initial = CommittedSessionState.from_values({SESSION_KEY: "old"}, version=3)
    store = InMemoryAtomicSessionStore(initial, fail_on_keys=frozenset({MEMORY_KEY}))
    overlay = SpeculativeSessionOverlay(initial)
    for write_id, key in (("write:a", SESSION_KEY), ("write:b", MEMORY_KEY)):
        overlay.write(
            write_id=write_id,
            key=key,
            value=write_id,
            producer_decision_id=f"decision:{write_id[-1]}",
            provenance_ids=(f"evidence:{write_id[-1]}",),
        )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(
            **{
                "decision:a": ExecutionDisposition.PROCEED,
                "decision:b": ExecutionDisposition.PROCEED,
            }
        ),
        _validation("decision:a", "decision:b"),
        _plan_validation(
            overlay,
            {"decision:a": True, "decision:b": True},
        ),
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    assert result.status == CommitStatus.ATOMIC_FAILURE
    assert not result.persistent_state_changed
    assert store.snapshot() == initial
    assert all(
        write.state == ProvisionalWriteState.ACTIVE
        for write in overlay.snapshot().provisional_writes
    )


def test_independent_success_is_not_rolled_back_but_partial_commit_is_withheld() -> None:
    initial = CommittedSessionState(0)
    store = InMemoryAtomicSessionStore(initial)
    overlay = SpeculativeSessionOverlay(initial)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    overlay.write(
        write_id="write:b",
        key=MEMORY_KEY,
        value="b",
        producer_decision_id="decision:b",
        provenance_ids=("evidence:b",),
    )
    overlay.rollback_decision("decision:b", reason="operation_failed")
    plan_validation = _plan_validation(
        overlay,
        {"decision:a": True, "decision:b": False},
    )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(
            **{
                "decision:a": ExecutionDisposition.PROCEED,
                "decision:b": ExecutionDisposition.HOLD,
            }
        ),
        _validation("decision:a", "decision:b"),
        plan_validation,
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    writes = {write.write_id: write for write in overlay.snapshot().provisional_writes}
    assert plan_validation.valid
    assert writes["write:a"].visible
    assert writes["write:a"].rollback_status == RollbackStatus.NONE
    assert assessment.eligibility == CommitEligibility.PARTIAL_COMMIT_UNRESOLVED
    assert PARTIAL_COMMIT_ASSUMPTION_ID in assessment.assumption_refs
    assert result.status == CommitStatus.REJECTED
    assert store.snapshot() == initial


def test_rolled_back_terminal_is_rejected_instead_of_postprocessed() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    overlay.rollback_decision("decision:a", reason="operation_failed")
    invalid = _plan_validation(overlay, {"decision:a": True})
    corrected = _plan_validation(overlay, {"decision:a": False})
    assert not invalid.valid
    assert invalid.terminal_decision_ids == ("decision:a",)
    assert "rolled_back_terminal_present" in invalid.error_codes
    assert corrected.valid


def test_cascaded_consumer_without_a_write_still_has_rollback_plan_status() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    overlay.read(
        read_id="read:b",
        key=SESSION_KEY,
        consumer_decision_id="decision:b",
    )
    overlay.rollback_decision("decision:a", reason="operation_failed")
    validation = _plan_validation(
        overlay,
        {"decision:a": False, "decision:b": True},
    )
    rollbacks = {
        item.decision_id: item.status
        for item in overlay.snapshot().decision_rollbacks
    }
    assert rollbacks == {
        "decision:a": RollbackStatus.DIRECT,
        "decision:b": RollbackStatus.CASCADED,
    }
    assert not validation.valid
    assert validation.terminal_decision_ids == ("decision:b",)


def test_later_write_explicitly_supersedes_same_key() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    first = overlay.write(
        write_id="write:first",
        key=SESSION_KEY,
        value="first",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:first",),
    )
    second = overlay.write(
        write_id="write:second",
        key=SESSION_KEY,
        value="second",
        producer_decision_id="decision:b",
        provenance_ids=("evidence:second",),
    )
    read = overlay.read(
        read_id="read:latest",
        key=SESSION_KEY,
        consumer_decision_id="decision:c",
    )
    writes = {write.write_id: write for write in overlay.snapshot().provisional_writes}
    assert first.sequence < second.sequence
    assert writes[first.write_id].state == ProvisionalWriteState.SUPERSEDED
    assert writes[first.write_id].superseded_by == second.write_id
    assert read.thawed_value() == "second"


def test_overlay_change_after_assessment_prevents_stale_commit() -> None:
    initial = CommittedSessionState(0)
    store = InMemoryAtomicSessionStore(initial)
    overlay = SpeculativeSessionOverlay(initial)
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(**{"decision:a": ExecutionDisposition.PROCEED}),
        _validation("decision:a"),
        _plan_validation(overlay, {"decision:a": True}),
    )
    overlay.read(
        read_id="read:late",
        key=SESSION_KEY,
        consumer_decision_id="decision:a",
    )
    result = AtomicCommitCoordinator.commit(overlay, store, assessment)
    assert result.status == CommitStatus.REJECTED
    assert result.error_code == "stale_overlay_assessment"
    assert store.snapshot() == initial


def test_overlay_change_after_plan_validation_requires_revalidation() -> None:
    overlay = SpeculativeSessionOverlay(CommittedSessionState(0))
    overlay.write(
        write_id="write:a",
        key=SESSION_KEY,
        value="a",
        producer_decision_id="decision:a",
        provenance_ids=("evidence:a",),
    )
    plan_validation = _plan_validation(overlay, {"decision:a": True})
    overlay.read(
        read_id="read:late",
        key=SESSION_KEY,
        consumer_decision_id="decision:a",
    )
    assessment = CommitEligibilityEvaluator.evaluate(
        overlay,
        _dispositions(**{"decision:a": ExecutionDisposition.PROCEED}),
        _validation("decision:a"),
        plan_validation,
    )
    assert assessment.eligibility == CommitEligibility.RELEASE_INVALID
    assert "stale_rollback_plan_validation" in assessment.reason_codes


def test_session_overlay_is_shadow_only_and_not_wired_to_legacy_commit() -> None:
    validate_session_overlay_contract()
    for relative in ("harness.py", "run_submission.py", "core/session_state.py"):
        production = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "session_overlay" not in production
