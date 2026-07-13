from __future__ import annotations

from dataclasses import dataclass

from .ontology import StrictSemanticEnum


ACTIONS_ASSUMPTION_ID = "ASSUMPTION-ACTIONS-001"
BUNDLE_ASSUMPTION_ID = "ASSUMPTION-BUNDLE-001"
CANCEL_ASSUMPTION_ID = "ASSUMPTION-CANCEL-001"
DISPOSITION_ASSUMPTION_ID = "ASSUMPTION-DISPOSITION-001"
FALLBACK_ASSUMPTION_ID = "ASSUMPTION-FALLBACK-001"
TARGET_ASSUMPTION_ID = "ASSUMPTION-TARGET-001"
TRANSFORM_ASSUMPTION_ID = "ASSUMPTION-TRANSFORM-001"
PLAN_ORDER_ASSUMPTION_ID = "ASSUMPTION-PLAN-ORDER-001"
CONSTRAINT_EFFECT_ASSUMPTION_ID = "ASSUMPTION-CONSTRAINT-EFFECT-001"
DISPOSITION_PLAN_ASSUMPTION_ID = "ASSUMPTION-DISPOSITION-PLAN-001"
SESSION_COMMIT_ASSUMPTION_ID = "ASSUMPTION-SESSION-001"
PARTIAL_COMMIT_ASSUMPTION_ID = "ASSUMPTION-PARTIAL-COMMIT-001"


class ContractStatus(StrictSemanticEnum):
    CONFIRMED_CONTRACT = "CONFIRMED_CONTRACT"
    SUPPORTED_INTERPRETATION = "SUPPORTED_INTERPRETATION"
    UNRESOLVED_ASSUMPTION = "UNRESOLVED_ASSUMPTION"


@dataclass(frozen=True)
class AssumptionSpec:
    assumption_id: str
    statement: str
    status: ContractStatus
    supporting_evidence_refs: tuple[str, ...]
    counterexample_refs: tuple[str, ...]
    affected_types: tuple[str, ...]
    affected_modules: tuple[str, ...]
    current_resolution: str
    review_owner: str


ASSUMPTION_REGISTRY = (
    AssumptionSpec(
        ACTIONS_ASSUMPTION_ID,
        "available_actions가 platform action과 internal transform 중 어느 범위를 제한하는지",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CapabilityType", "CapabilitySource"),
        ("core/blueprint.py", "core/plan_requirements.py", "rules/plan.py"),
        "production은 emitted plan verb 전체를 제한 대상으로 취급한다. Step 6 shadow 계약은 platform action과 internal requirement를 별도 타입으로 유지한다.",
        "unassigned",
    ),
    AssumptionSpec(
        CANCEL_ASSUMPTION_ID,
        "cancel operation의 공식 terminal mapping",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("Operation", "PlanStepType"),
        ("core/blueprint.py",),
        "확인된 blueprint가 없어 unsupported 상태로 유지한다.",
        "unassigned",
    ),
    AssumptionSpec(
        BUNDLE_ASSUMPTION_ID,
        "복수 operation의 공식 aggregate output 규칙",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CandidateState", "ExecutionDisposition"),
        ("core/decision.py",),
        "미해결 복수 후보는 DecisionGate로 실행을 보류한다.",
        "unassigned",
    ),
    AssumptionSpec(
        SESSION_COMMIT_ASSUMPTION_ID,
        "persistent session commit의 공식 의미와 범위",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CommittedSessionState", "SpeculativeSessionOverlay", "CommitAssessment"),
        ("harness.py", "run_submission.py", "core/session_overlay.py"),
        "production single-task 경로는 validation 전에 commit한다. Step 11 shadow 경로는 validation-before-commit과 atomic store 계약을 강제한다.",
        "unassigned",
    ),
    AssumptionSpec(
        PARTIAL_COMMIT_ASSUMPTION_ID,
        "부분 성공 시 commit 범위",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CommitAssessment", "CommitEligibility"),
        ("harness.py", "core/session_overlay.py"),
        "공식 근거가 없어 shadow 경로도 부분 persistent commit을 수행하지 않는다.",
        "unassigned",
    ),
    AssumptionSpec(
        FALLBACK_ASSUMPTION_ID,
        "fallback의 공식 허용 범위",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("Operation",),
        ("core/decision.py",),
        "현재 사용자·official policy·official transformation 세 source만 허용한다.",
        "unassigned",
    ),
    AssumptionSpec(
        TARGET_ASSUMPTION_ID,
        "공식 answer.target의 execution/response target 의미",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("TargetRole", "TargetLocality"),
        ("core/decision.py",),
        "내부 operation_target과 output target을 분리하지만 공식 mapping은 미확정이다.",
        "unassigned",
    ),
    AssumptionSpec(
        TRANSFORM_ASSUMPTION_ID,
        "redact·summarize·verify의 platform action/internal transform 구분",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CapabilityType", "CapabilitySource"),
        ("core/blueprint.py", "core/plan_requirements.py"),
        "production은 모두 available_actions 검사를 받는다. Step 6 shadow 계약은 output verb의 platform capability와 내부 preparation requirement를 분리한다.",
        "unassigned",
    ),
    AssumptionSpec(
        DISPOSITION_ASSUMPTION_ID,
        "정보 부족·conflict·hard block·capability 부재가 동시에 존재할 때의 우선순위",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("CandidateState", "ExecutionDisposition"),
        ("core/ontology.py", "core/decision.py"),
        "현재 policy는 unsupported, block, conflict, missing, confirmation, amend 순으로 상태를 해소한다.",
        "unassigned",
    ),
    AssumptionSpec(
        PLAN_ORDER_ASSUMPTION_ID,
        "redact와 summarize requirement가 동시에 활성화될 때의 canonical transform 순서",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        (),
        (),
        ("BasePlanBlueprint", "FinalPlanRequirements"),
        ("core/plan_requirements.py",),
        "현재 shadow composer는 redact 후 summarize 순서를 사용하며 production projection에는 아직 연결하지 않는다.",
        "unassigned",
    ),
    AssumptionSpec(
        CONSTRAINT_EFFECT_ASSUMPTION_ID,
        "구조화된 constraint record type과 value가 만드는 정확한 effect mapping",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        ("OFFICIAL-TERMS-RECORDS",),
        (),
        ("GlobalConstraintFact", "PairConstraintSpec", "ConstraintEffect"),
        ("core/constraints.py",),
        "record label은 fact 후보만 만들며 exact RulePack과 target scope가 맞을 때만 supported interpretation effect를 활성화한다.",
        "unassigned",
    ),
    AssumptionSpec(
        DISPOSITION_PLAN_ASSUMPTION_ID,
        "ask·hold disposition의 공식 non-execution plan requirement와 target mapping",
        ContractStatus.UNRESOLVED_ASSUMPTION,
        ("OFFICIAL-TERMS-AVAILABLE-ACTIONS",),
        (),
        ("PlanProjection", "SubDecisionIR"),
        ("core/decision_ir.py",),
        "Decision Lock 전에 명시적 PlanProjection을 요구하고 ask는 clarify, hold는 guard를 포함하는지 검증하되 compiler에서 생성하지 않는다.",
        "unassigned",
    ),
)


def assumption_ids() -> frozenset[str]:
    return frozenset(item.assumption_id for item in ASSUMPTION_REGISTRY)


def validate_assumption_registry() -> None:
    ids = [item.assumption_id for item in ASSUMPTION_REGISTRY]
    if len(ids) != len(set(ids)):
        raise ValueError("assumption registry contains duplicate IDs")
    for item in ASSUMPTION_REGISTRY:
        if item.status != ContractStatus.UNRESOLVED_ASSUMPTION:
            raise ValueError(
                f"assumption {item.assumption_id} has non-assumption status"
            )
        if not item.statement or not item.affected_modules:
            raise ValueError(
                f"assumption {item.assumption_id} lacks required metadata"
            )
