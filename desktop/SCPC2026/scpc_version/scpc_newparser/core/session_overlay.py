from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable

from .contracts import (
    PARTIAL_COMMIT_ASSUMPTION_ID,
    SESSION_COMMIT_ASSUMPTION_ID,
)
from .decision_ir import DecisionProjectionSet
from .facts import FrozenValue, freeze_value, thaw_value
from .ontology import ExecutionDisposition


class SessionNamespace(str, Enum):
    SESSION = "session"
    MEMORY = "memory"


class ProvisionalWriteState(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    COMMITTED = "committed"


class RollbackStatus(str, Enum):
    NONE = "none"
    DIRECT = "direct"
    CASCADED = "cascaded"


class OverlayReadSource(str, Enum):
    PROVISIONAL = "provisional"
    COMMITTED = "committed"
    MISSING = "missing"


class ValidationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"


class CommitEligibility(str, Enum):
    ELIGIBLE = "eligible"
    NO_WRITES = "no_writes"
    VALIDATION_FAILED = "validation_failed"
    RELEASE_INVALID = "release_invalid"
    DECISION_INELIGIBLE = "decision_ineligible"
    ROLLBACK_PRESENT = "rollback_present"
    PARTIAL_COMMIT_UNRESOLVED = "partial_commit_unresolved"


class CommitStatus(str, Enum):
    COMMITTED = "committed"
    REJECTED = "rejected"
    ATOMIC_FAILURE = "atomic_failure"


def _require_frozen_json(value: FrozenValue) -> None:
    try:
        normalized = freeze_value(thaw_value(value))
    except TypeError as exc:
        raise ValueError("session value is not frozen JSON") from exc
    if normalized != value:
        raise ValueError("session value must use the frozen JSON representation")


@dataclass(frozen=True, order=True)
class SessionValueKey:
    namespace: SessionNamespace
    key: str

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("session value key cannot be empty")

    @property
    def canonical_text(self) -> str:
        return f"{self.namespace.value}:{self.key}"


@dataclass(frozen=True)
class CommittedSessionState:
    version: int
    values: tuple[tuple[SessionValueKey, FrozenValue], ...] = ()

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("committed state version cannot be negative")
        keys = tuple(key for key, _value in self.values)
        if len(keys) != len(set(keys)) or keys != tuple(
            sorted(keys, key=lambda item: item.canonical_text)
        ):
            raise ValueError("committed state keys must be unique and canonical")
        for _key, value in self.values:
            _require_frozen_json(value)

    @classmethod
    def from_values(
        cls,
        values: dict[SessionValueKey, Any],
        *,
        version: int = 0,
    ) -> "CommittedSessionState":
        return cls(
            version,
            tuple(
                (key, freeze_value(value))
                for key, value in sorted(
                    values.items(),
                    key=lambda item: item[0].canonical_text,
                )
            ),
        )

    def resolve(self, key: SessionValueKey) -> tuple[bool, Any]:
        for item_key, value in self.values:
            if item_key == key:
                return True, thaw_value(value)
        return False, None

    def to_values(self) -> dict[SessionValueKey, Any]:
        return {key: thaw_value(value) for key, value in self.values}

    def with_writes(
        self,
        writes: Iterable["ProvisionalWrite"],
    ) -> "CommittedSessionState":
        values = {key: value for key, value in self.values}
        for write in writes:
            if (
                write.state != ProvisionalWriteState.ACTIVE
                or write.rollback_status != RollbackStatus.NONE
            ):
                raise ValueError("only active non-rolled-back writes can commit")
            values[write.key] = write.value
        return CommittedSessionState(
            self.version + 1,
            tuple(
                sorted(values.items(), key=lambda item: item[0].canonical_text)
            ),
        )


@dataclass(frozen=True)
class ProvisionalWrite:
    write_id: str
    key: SessionValueKey
    value: FrozenValue
    producer_decision_id: str
    sequence: int
    provenance_ids: tuple[str, ...]
    state: ProvisionalWriteState = ProvisionalWriteState.ACTIVE
    superseded_by: str = ""
    rollback_status: RollbackStatus = RollbackStatus.NONE
    rollback_reason: str = ""

    def __post_init__(self) -> None:
        if not self.write_id or not self.producer_decision_id or self.sequence < 1:
            raise ValueError("provisional write requires stable identity and sequence")
        if tuple(sorted(set(self.provenance_ids))) != self.provenance_ids:
            raise ValueError("write provenance must be unique and canonical")
        if self.state == ProvisionalWriteState.SUPERSEDED and not self.superseded_by:
            raise ValueError("superseded write requires replacement identity")
        if self.rollback_status == RollbackStatus.NONE and self.rollback_reason:
            raise ValueError("non-rolled-back write cannot have rollback reason")
        if self.rollback_status != RollbackStatus.NONE and not self.rollback_reason:
            raise ValueError("rolled-back write requires a reason")
        if (
            self.state == ProvisionalWriteState.COMMITTED
            and self.rollback_status != RollbackStatus.NONE
        ):
            raise ValueError("rolled-back write cannot be committed")
        _require_frozen_json(self.value)

    @property
    def visible(self) -> bool:
        return (
            self.state == ProvisionalWriteState.ACTIVE
            and self.rollback_status == RollbackStatus.NONE
        )

    def thawed_value(self) -> Any:
        return thaw_value(self.value)


@dataclass(frozen=True)
class OverlayRead:
    read_id: str
    key: SessionValueKey
    consumer_decision_id: str
    source: OverlayReadSource
    value: FrozenValue
    source_write_id: str = ""

    def __post_init__(self) -> None:
        if not self.read_id or not self.consumer_decision_id:
            raise ValueError("overlay read requires stable identity")
        if self.source == OverlayReadSource.PROVISIONAL and not self.source_write_id:
            raise ValueError("provisional read requires source write identity")
        if self.source != OverlayReadSource.PROVISIONAL and self.source_write_id:
            raise ValueError("non-provisional read cannot reference a provisional write")
        _require_frozen_json(self.value)

    def thawed_value(self) -> Any:
        return thaw_value(self.value)


@dataclass(frozen=True, order=True)
class SessionDependencyEdge:
    producer_decision_id: str
    consumer_decision_id: str
    read_reference_id: str
    key: SessionValueKey

    def __post_init__(self) -> None:
        if (
            not self.producer_decision_id
            or not self.consumer_decision_id
            or not self.read_reference_id
        ):
            raise ValueError("session dependency requires explicit read lineage")
        if self.producer_decision_id == self.consumer_decision_id:
            raise ValueError("self-read does not create an inter-decision dependency")


@dataclass(frozen=True, order=True)
class DecisionRollback:
    decision_id: str
    status: RollbackStatus
    reason: str

    def __post_init__(self) -> None:
        if not self.decision_id or self.status == RollbackStatus.NONE or not self.reason:
            raise ValueError("decision rollback requires identity, status, and reason")


@dataclass(frozen=True)
class OverlaySnapshot:
    base_version: int
    revision: int
    provisional_writes: tuple[ProvisionalWrite, ...]
    reads: tuple[OverlayRead, ...]
    dependency_edges: tuple[SessionDependencyEdge, ...]
    decision_rollbacks: tuple[DecisionRollback, ...]

    def __post_init__(self) -> None:
        if self.base_version < 0 or self.revision < 0:
            raise ValueError("overlay versions cannot be negative")
        write_ids = tuple(item.write_id for item in self.provisional_writes)
        read_ids = tuple(item.read_id for item in self.reads)
        rollback_ids = tuple(item.decision_id for item in self.decision_rollbacks)
        if len(write_ids) != len(set(write_ids)):
            raise ValueError("overlay snapshot contains duplicate writes")
        if len(read_ids) != len(set(read_ids)):
            raise ValueError("overlay snapshot contains duplicate reads")
        if len(rollback_ids) != len(set(rollback_ids)):
            raise ValueError("overlay snapshot contains duplicate rollbacks")
        if tuple(sorted(self.dependency_edges)) != self.dependency_edges:
            raise ValueError("overlay dependencies must be canonical")
        if tuple(sorted(self.decision_rollbacks)) != self.decision_rollbacks:
            raise ValueError("overlay rollbacks must be canonical")

    @property
    def write_set(self) -> tuple[SessionValueKey, ...]:
        return tuple(
            sorted(
                {write.key for write in self.provisional_writes},
                key=lambda item: item.canonical_text,
            )
        )

    @property
    def read_set(self) -> tuple[SessionValueKey, ...]:
        return tuple(
            sorted(
                {read.key for read in self.reads},
                key=lambda item: item.canonical_text,
            )
        )

    @property
    def producer_decision_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted({write.producer_decision_id for write in self.provisional_writes})
        )

    @property
    def consumer_decision_ids(self) -> tuple[str, ...]:
        return tuple(sorted({read.consumer_decision_id for read in self.reads}))


class SpeculativeSessionOverlay:
    production_active = False

    def __init__(self, committed: CommittedSessionState) -> None:
        self._committed = committed
        self._writes: dict[str, ProvisionalWrite] = {}
        self._reads: dict[str, OverlayRead] = {}
        self._dependencies: set[SessionDependencyEdge] = set()
        self._decision_rollbacks: dict[str, DecisionRollback] = {}
        self._sequence = 0
        self._revision = 0

    @property
    def committed(self) -> CommittedSessionState:
        return self._committed

    @property
    def revision(self) -> int:
        return self._revision

    def write(
        self,
        *,
        write_id: str,
        key: SessionValueKey,
        value: Any,
        producer_decision_id: str,
        provenance_ids: tuple[str, ...],
    ) -> ProvisionalWrite:
        if write_id in self._writes:
            raise ValueError("duplicate provisional write identity")
        if producer_decision_id in self._decision_rollbacks:
            raise ValueError("rolled-back decision cannot create a new write")
        self._sequence += 1
        for previous_id, previous in tuple(self._writes.items()):
            if previous.key == key and previous.visible:
                self._writes[previous_id] = replace(
                    previous,
                    state=ProvisionalWriteState.SUPERSEDED,
                    superseded_by=write_id,
                )
        write = ProvisionalWrite(
            write_id=write_id,
            key=key,
            value=freeze_value(value),
            producer_decision_id=producer_decision_id,
            sequence=self._sequence,
            provenance_ids=tuple(sorted(set(provenance_ids))),
        )
        self._writes[write_id] = write
        self._revision += 1
        return write

    def read(
        self,
        *,
        read_id: str,
        key: SessionValueKey,
        consumer_decision_id: str,
    ) -> OverlayRead:
        if read_id in self._reads:
            raise ValueError("duplicate overlay read identity")
        if consumer_decision_id in self._decision_rollbacks:
            raise ValueError("rolled-back decision cannot create a new read")
        candidates = [
            write for write in self._writes.values() if write.key == key and write.visible
        ]
        if candidates:
            source_write = max(candidates, key=lambda item: item.sequence)
            read = OverlayRead(
                read_id,
                key,
                consumer_decision_id,
                OverlayReadSource.PROVISIONAL,
                source_write.value,
                source_write.write_id,
            )
            if source_write.producer_decision_id != consumer_decision_id:
                self._dependencies.add(
                    SessionDependencyEdge(
                        source_write.producer_decision_id,
                        consumer_decision_id,
                        read_id,
                        key,
                    )
                )
        else:
            found, value = self._committed.resolve(key)
            read = OverlayRead(
                read_id,
                key,
                consumer_decision_id,
                (
                    OverlayReadSource.COMMITTED
                    if found
                    else OverlayReadSource.MISSING
                ),
                freeze_value(value),
            )
        self._reads[read_id] = read
        self._revision += 1
        return read

    def rollback_decision(self, decision_id: str, *, reason: str) -> tuple[str, ...]:
        if not decision_id or not reason:
            raise ValueError("rollback requires decision identity and reason")
        affected: dict[str, RollbackStatus] = {decision_id: RollbackStatus.DIRECT}
        queue = [decision_id]
        while queue:
            producer = queue.pop(0)
            for edge in sorted(self._dependencies):
                if edge.producer_decision_id != producer:
                    continue
                consumer = edge.consumer_decision_id
                if consumer not in affected:
                    affected[consumer] = RollbackStatus.CASCADED
                    queue.append(consumer)
        changed = False
        for affected_id, status in affected.items():
            existing = self._decision_rollbacks.get(affected_id)
            if existing is not None and (
                existing.status == RollbackStatus.DIRECT
                or status == RollbackStatus.CASCADED
            ):
                continue
            self._decision_rollbacks[affected_id] = DecisionRollback(
                affected_id,
                status,
                reason,
            )
            changed = True
        for write_id, write in tuple(self._writes.items()):
            decision_rollback = self._decision_rollbacks.get(
                write.producer_decision_id
            )
            if (
                decision_rollback is None
                or write.rollback_status != RollbackStatus.NONE
            ):
                continue
            self._writes[write_id] = replace(
                write,
                rollback_status=decision_rollback.status,
                rollback_reason=decision_rollback.reason,
            )
            changed = True
        if changed:
            self._revision += 1
        return tuple(sorted(affected))

    def mark_committed(self, write_ids: tuple[str, ...]) -> None:
        for write_id in write_ids:
            write = self._writes.get(write_id)
            if write is None or not write.visible:
                raise ValueError("commit result references a non-active write")
        for write_id in write_ids:
            self._writes[write_id] = replace(
                self._writes[write_id],
                state=ProvisionalWriteState.COMMITTED,
            )
        if write_ids:
            self._revision += 1

    def snapshot(self) -> OverlaySnapshot:
        return OverlaySnapshot(
            self._committed.version,
            self._revision,
            tuple(sorted(self._writes.values(), key=lambda item: item.sequence)),
            tuple(sorted(self._reads.values(), key=lambda item: item.read_id)),
            tuple(sorted(self._dependencies)),
            tuple(sorted(self._decision_rollbacks.values())),
        )


@dataclass(frozen=True)
class ValidationResult:
    status: ValidationStatus
    validated_decision_ids: tuple[str, ...]
    validator_id: str
    artifact_digest: str
    error_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.validated_decision_ids))) != (
            self.validated_decision_ids
        ):
            raise ValueError("validated decision IDs must be canonical")
        if tuple(sorted(set(self.error_codes))) != self.error_codes:
            raise ValueError("validation errors must be canonical")
        if not self.validator_id or not self.artifact_digest:
            raise ValueError("validation result requires validator and artifact lineage")
        if self.status == ValidationStatus.PASSED and self.error_codes:
            raise ValueError("passed validation cannot contain errors")
        if self.status == ValidationStatus.FAILED and not self.error_codes:
            raise ValueError("failed validation requires an error code")


@dataclass(frozen=True)
class DecisionDispositionSet:
    values: tuple[tuple[str, ExecutionDisposition], ...]

    def __post_init__(self) -> None:
        ids = tuple(decision_id for decision_id, _disposition in self.values)
        if not ids or len(ids) != len(set(ids)) or ids != tuple(sorted(ids)):
            raise ValueError("decision dispositions must be non-empty and canonical")

    def get(self, decision_id: str) -> ExecutionDisposition | None:
        return next(
            (
                disposition
                for item_id, disposition in self.values
                if item_id == decision_id
            ),
            None,
        )


@dataclass(frozen=True)
class RollbackPlanValidation:
    valid: bool
    overlay_revision: int
    source_bundle_lock_digest: str
    rolled_back_decision_ids: tuple[str, ...]
    terminal_decision_ids: tuple[str, ...]
    error_codes: tuple[str, ...]


class RollbackPlanValidator:
    @staticmethod
    def validate(
        snapshot: OverlaySnapshot,
        projections: DecisionProjectionSet,
        compiled: dict[str, dict[str, Any]],
    ) -> RollbackPlanValidation:
        rolled_back = tuple(
            item.decision_id for item in snapshot.decision_rollbacks
        )
        plans = {plan.decision_id: plan for plan in projections.plans}
        errors: set[str] = set()
        terminals: set[str] = set()
        if set(compiled) != set(plans):
            errors.add("compiled_projection_decision_mismatch")
        for decision_id, plan in plans.items():
            expected = [
                {
                    "verb": step.verb.value,
                    "target": step.target,
                    "args": dict(step.args),
                }
                for step in plan.steps
            ]
            if compiled.get(decision_id, {}).get("plan_events") != expected:
                errors.add("compiled_plan_differs_from_projection")
            if decision_id in rolled_back and any(
                step.semantic_terminal for step in plan.steps
            ):
                terminals.add(decision_id)
                errors.add("rolled_back_terminal_present")
        for decision_id in rolled_back:
            if decision_id not in plans:
                errors.add("rolled_back_decision_projection_missing")
        return RollbackPlanValidation(
            not errors,
            snapshot.revision,
            projections.source_bundle_lock_digest,
            rolled_back,
            tuple(sorted(terminals)),
            tuple(sorted(errors)),
        )


@dataclass(frozen=True)
class CommitAssessment:
    eligibility: CommitEligibility
    overlay_revision: int
    eligible_write_ids: tuple[str, ...]
    ineligible_decision_ids: tuple[str, ...]
    assumption_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]


class CommitEligibilityEvaluator:
    @staticmethod
    def evaluate(
        overlay: SpeculativeSessionOverlay,
        dispositions: DecisionDispositionSet,
        validation: ValidationResult,
        plan_validation: RollbackPlanValidation,
    ) -> CommitAssessment:
        snapshot = overlay.snapshot()
        assumptions = {SESSION_COMMIT_ASSUMPTION_ID}
        active = [write for write in snapshot.provisional_writes if write.visible]
        rolled_back_decisions = {
            item.decision_id for item in snapshot.decision_rollbacks
        }
        if validation.status != ValidationStatus.PASSED:
            return CommitAssessment(
                CommitEligibility.VALIDATION_FAILED,
                snapshot.revision,
                (),
                (),
                tuple(sorted(assumptions)),
                validation.error_codes,
            )
        release_validation_stale = (
            plan_validation.overlay_revision != snapshot.revision
            or set(plan_validation.rolled_back_decision_ids)
            != rolled_back_decisions
        )
        if not plan_validation.valid or release_validation_stale:
            release_errors = set(plan_validation.error_codes)
            if release_validation_stale:
                release_errors.add("stale_rollback_plan_validation")
            return CommitAssessment(
                CommitEligibility.RELEASE_INVALID,
                snapshot.revision,
                (),
                (),
                tuple(sorted(assumptions)),
                tuple(sorted(release_errors)),
            )
        if not snapshot.provisional_writes:
            return CommitAssessment(
                CommitEligibility.NO_WRITES,
                snapshot.revision,
                (),
                (),
                tuple(sorted(assumptions)),
                ("no_provisional_writes",),
            )

        validated = set(validation.validated_decision_ids)
        executable = {ExecutionDisposition.PROCEED, ExecutionDisposition.AMEND}
        ineligible = {
            write.producer_decision_id
            for write in active
            if write.producer_decision_id not in validated
            or dispositions.get(write.producer_decision_id) not in executable
        }
        eligible_writes = tuple(
            sorted(
                write.write_id
                for write in active
                if write.producer_decision_id not in ineligible
            )
        )
        failed_components = bool(ineligible or rolled_back_decisions)
        if eligible_writes and failed_components:
            assumptions.add(PARTIAL_COMMIT_ASSUMPTION_ID)
            return CommitAssessment(
                CommitEligibility.PARTIAL_COMMIT_UNRESOLVED,
                snapshot.revision,
                eligible_writes,
                tuple(
                    sorted(
                        ineligible
                        | rolled_back_decisions
                    )
                ),
                tuple(sorted(assumptions)),
                ("partial_commit_contract_unresolved",),
            )
        if rolled_back_decisions:
            return CommitAssessment(
                CommitEligibility.ROLLBACK_PRESENT,
                snapshot.revision,
                (),
                tuple(sorted(rolled_back_decisions)),
                tuple(sorted(assumptions)),
                ("rollback_present",),
            )
        if ineligible or not eligible_writes:
            return CommitAssessment(
                CommitEligibility.DECISION_INELIGIBLE,
                snapshot.revision,
                (),
                tuple(sorted(ineligible)),
                tuple(sorted(assumptions)),
                ("producer_disposition_ineligible",),
            )
        return CommitAssessment(
            CommitEligibility.ELIGIBLE,
            snapshot.revision,
            eligible_writes,
            (),
            tuple(sorted(assumptions)),
            ("validation_before_commit_passed",),
        )


class InMemoryAtomicSessionStore:
    production_active = False

    def __init__(
        self,
        state: CommittedSessionState,
        *,
        fail_on_keys: frozenset[SessionValueKey] = frozenset(),
    ) -> None:
        self._state = state
        self._fail_on_keys = fail_on_keys

    def snapshot(self) -> CommittedSessionState:
        return self._state

    def commit(
        self,
        *,
        expected_version: int,
        writes: tuple[ProvisionalWrite, ...],
    ) -> CommittedSessionState:
        if self._state.version != expected_version:
            raise RuntimeError("committed session version changed")
        next_state = self._state.with_writes(writes)
        if self._fail_on_keys & {write.key for write in writes}:
            raise RuntimeError("injected atomic commit failure")
        self._state = next_state
        return next_state


@dataclass(frozen=True)
class DecisionCommitTrace:
    decision_id: str
    write_ids: tuple[str, ...]


@dataclass(frozen=True)
class CommitResult:
    status: CommitStatus
    eligibility: CommitEligibility
    state_version_before: int
    state_version_after: int
    persistent_state_changed: bool
    decision_traces: tuple[DecisionCommitTrace, ...]
    assumption_refs: tuple[str, ...]
    error_code: str = ""


class AtomicCommitCoordinator:
    production_active = False

    @staticmethod
    def commit(
        overlay: SpeculativeSessionOverlay,
        store: InMemoryAtomicSessionStore,
        assessment: CommitAssessment,
    ) -> CommitResult:
        before = store.snapshot()
        if assessment.eligibility != CommitEligibility.ELIGIBLE:
            return CommitResult(
                CommitStatus.REJECTED,
                assessment.eligibility,
                before.version,
                before.version,
                False,
                (),
                assessment.assumption_refs,
                assessment.reason_codes[0] if assessment.reason_codes else "",
            )
        if overlay.revision != assessment.overlay_revision:
            return CommitResult(
                CommitStatus.REJECTED,
                assessment.eligibility,
                before.version,
                before.version,
                False,
                (),
                assessment.assumption_refs,
                "stale_overlay_assessment",
            )
        snapshot = overlay.snapshot()
        by_id = {write.write_id: write for write in snapshot.provisional_writes}
        writes = tuple(by_id[write_id] for write_id in assessment.eligible_write_ids)
        traces_by_decision: dict[str, list[str]] = {}
        for write in writes:
            traces_by_decision.setdefault(write.producer_decision_id, []).append(
                write.write_id
            )
        traces = tuple(
            DecisionCommitTrace(decision_id, tuple(sorted(write_ids)))
            for decision_id, write_ids in sorted(traces_by_decision.items())
        )
        try:
            after = store.commit(
                expected_version=snapshot.base_version,
                writes=writes,
            )
        except RuntimeError as exc:
            unchanged = store.snapshot() == before
            return CommitResult(
                CommitStatus.ATOMIC_FAILURE,
                assessment.eligibility,
                before.version,
                store.snapshot().version,
                not unchanged,
                traces,
                assessment.assumption_refs,
                type(exc).__name__,
            )
        overlay.mark_committed(assessment.eligible_write_ids)
        return CommitResult(
            CommitStatus.COMMITTED,
            assessment.eligibility,
            before.version,
            after.version,
            after != before,
            traces,
            assessment.assumption_refs,
        )


def validate_session_overlay_contract() -> None:
    if any(
        component.production_active
        for component in (
            SpeculativeSessionOverlay,
            InMemoryAtomicSessionStore,
            AtomicCommitCoordinator,
        )
    ):
        raise ValueError("Step 11 session lifecycle must remain shadow-only")
