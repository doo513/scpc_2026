from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .contracts import (
    ACTIONS_ASSUMPTION_ID,
    PLAN_ORDER_ASSUMPTION_ID,
    TRANSFORM_ASSUMPTION_ID,
    ContractStatus,
    assumption_ids,
)
from .ontology import (
    CapabilityType,
    ConstraintEffect,
    DisclosureMode,
    Domain,
    InformationSlot,
    Operation,
    PlanStepType,
    TargetRole,
    constraint_effect_rank,
)
from .rulepacks import (
    BLUEPRINT_CATALOG,
    RULEPACK_REGISTRY,
    DomainOperationRulePack,
    RulePackAvailability,
    RulePackKey,
    RulePackResolution,
)


class PlanRequirementClass(str, Enum):
    PLATFORM_ACTION = "platform_action"
    INTERNAL_TRANSFORM = "internal_transform"
    INTERNAL_PREPARATION = "internal_preparation"


class PlanStepIdentity(str, Enum):
    LOCATE_CONTENT = "locate_content"
    READ = "read"
    VERIFY = "verify"
    REDACT = "redact"
    SUMMARIZE = "summarize"
    CONFIRM = "confirm"
    DISPATCH = "dispatch"
    UPDATE = "update"
    PAY = "pay"
    TOGGLE = "toggle"
    SCHEDULE = "schedule"
    CLARIFY = "clarify"


class InternalTransformType(str, Enum):
    LOCATE_CONTENT = "locate_content"
    REDACT_CONTENT = "redact_content"
    SUMMARIZE_CONTENT = "summarize_content"


class InsertionPoint(str, Enum):
    BASE = "base"
    BEFORE_TERMINAL = "before_terminal"


class DependencyKind(str, Enum):
    REQUIRES_COMPLETION = "requires_completion"


class PlanRequirementDeltaSource(str, Enum):
    ACTIVE_CONSTRAINT = "active_constraint"
    AUTHORIZED_MODIFICATION = "authorized_modification"


@dataclass(frozen=True)
class PlanStepRequirement:
    step_id: str
    identity: PlanStepIdentity
    requirement_class: PlanRequirementClass
    insertion_point: InsertionPoint
    platform_capability: CapabilityType | None = None
    output_verb: PlanStepType | None = None
    internal_transform: InternalTransformType | None = None
    semantic_terminal: bool = False

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("plan requirement requires a step ID")
        if self.requirement_class == PlanRequirementClass.PLATFORM_ACTION:
            if self.platform_capability is None or self.output_verb is None:
                raise ValueError("platform step requires capability and output verb")
            if self.internal_transform is not None:
                raise ValueError("platform step cannot own an internal transform")
        elif self.internal_transform is None:
            raise ValueError("internal requirement requires a transform type")
        elif self.platform_capability is not None or self.output_verb is not None:
            raise ValueError("internal requirement cannot own a platform capability")


@dataclass(frozen=True)
class DependencySemantic:
    before_step_id: str
    after_step_id: str
    kind: DependencyKind = DependencyKind.REQUIRES_COMPLETION


@dataclass(frozen=True)
class BasePlanBlueprint:
    blueprint_id: str
    key: RulePackKey
    semantic_terminal: PlanStepType
    base_steps: tuple[PlanStepRequirement, ...]
    platform_required_capabilities: tuple[CapabilityType, ...]
    internal_transform_requirements: tuple[InternalTransformType, ...]
    required_target_roles: tuple[TargetRole, ...]
    base_information_slots: tuple[InformationSlot, ...]
    conditional_information_slots: tuple[InformationSlot, ...]
    permitted_disclosure_modes: tuple[DisclosureMode, ...]
    dependency_semantics: tuple[DependencySemantic, ...]
    contract_status: ContractStatus
    assumption_refs: tuple[str, ...]
    version: str

    def __post_init__(self) -> None:
        ids = [item.step_id for item in self.base_steps]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate base step ID: {self.blueprint_id}")
        terminals = [item for item in self.base_steps if item.semantic_terminal]
        if len(terminals) != 1:
            raise ValueError("BasePlanBlueprint requires exactly one terminal step")
        if terminals[0].output_verb != self.semantic_terminal:
            raise ValueError("semantic terminal differs from terminal step")
        capabilities = tuple(
            item.platform_capability
            for item in self.base_steps
            if item.platform_capability is not None
        )
        if tuple(dict.fromkeys(capabilities)) != self.platform_required_capabilities:
            raise ValueError("platform capability summary differs from base steps")
        transforms = tuple(
            item.internal_transform
            for item in self.base_steps
            if item.internal_transform is not None
        )
        if tuple(dict.fromkeys(transforms)) != self.internal_transform_requirements:
            raise ValueError("internal transform summary differs from base steps")


@dataclass(frozen=True)
class PlanRequirementDelta:
    effect_id: str
    effect_kind: ConstraintEffect
    source_id: str
    scope: str
    source_kind: PlanRequirementDeltaSource
    parameters: tuple[tuple[str, str], ...] = ()
    authorization_ref: str = ""

    def __post_init__(self) -> None:
        if not self.effect_id or not self.source_id or not self.scope:
            raise ValueError("plan requirement delta requires identity and scope")
        parameter_names = [name for name, _ in self.parameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("plan requirement delta has duplicate parameters")
        if (
            self.source_kind == PlanRequirementDeltaSource.AUTHORIZED_MODIFICATION
            and not self.authorization_ref
        ):
            raise ValueError("modification delta requires an authorization reference")

    @property
    def canonical_key(self) -> tuple[object, ...]:
        return (
            self.effect_kind,
            self.scope,
            tuple(sorted(self.parameters)),
        )


@dataclass(frozen=True)
class FinalPlanRequirements:
    candidate_id: str
    rulepack_id: str
    blueprint_id: str
    domain: Domain
    operation: Operation
    semantic_terminal: PlanStepType
    required_steps: tuple[PlanStepRequirement, ...]
    platform_required_capabilities: tuple[CapabilityType, ...]
    internal_transform_requirements: tuple[InternalTransformType, ...]
    required_target_roles: tuple[TargetRole, ...]
    required_information_slots: tuple[InformationSlot, ...]
    conditional_information_slots: tuple[InformationSlot, ...]
    permitted_disclosure_modes: tuple[DisclosureMode, ...]
    dependency_semantics: tuple[DependencySemantic, ...]
    terminal_parameters: tuple[tuple[str, str], ...]
    applied_effect_ids: tuple[str, ...]
    assumption_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        terminals = [item for item in self.required_steps if item.semantic_terminal]
        if len(terminals) != 1:
            raise ValueError("FinalPlanRequirements requires one semantic terminal")
        if terminals[0].output_verb != self.semantic_terminal:
            raise ValueError("safeguard changed the semantic terminal")
        step_ids = {item.step_id for item in self.required_steps}
        if len(step_ids) != len(self.required_steps):
            raise ValueError("FinalPlanRequirements contains duplicate step IDs")
        if any(
            edge.before_step_id not in step_ids or edge.after_step_id not in step_ids
            for edge in self.dependency_semantics
        ):
            raise ValueError("dependency references a nonexistent plan step")
        capabilities = tuple(
            item.platform_capability
            for item in self.required_steps
            if item.platform_capability is not None
        )
        if tuple(dict.fromkeys(capabilities)) != self.platform_required_capabilities:
            raise ValueError("final capability summary differs from required steps")
        transforms = tuple(
            item.internal_transform
            for item in self.required_steps
            if item.internal_transform is not None
        )
        if tuple(dict.fromkeys(transforms)) != self.internal_transform_requirements:
            raise ValueError("final transform summary differs from required steps")
        unknown_assumptions = set(self.assumption_refs) - assumption_ids()
        if unknown_assumptions:
            raise ValueError(
                f"FinalPlanRequirements has unknown assumptions: {unknown_assumptions}"
            )

    @property
    def terminal_step(self) -> PlanStepRequirement:
        return next(item for item in self.required_steps if item.semantic_terminal)


def _platform_step(
    blueprint_id: str,
    name: str,
    identity: PlanStepIdentity,
    capability: CapabilityType,
    verb: PlanStepType,
    *,
    terminal: bool = False,
) -> PlanStepRequirement:
    return PlanStepRequirement(
        step_id=f"{blueprint_id}:{name}",
        identity=identity,
        requirement_class=PlanRequirementClass.PLATFORM_ACTION,
        insertion_point=InsertionPoint.BASE,
        platform_capability=capability,
        output_verb=verb,
        semantic_terminal=terminal,
    )


def _internal_step(
    blueprint_id: str,
    name: str,
    identity: PlanStepIdentity,
    transform: InternalTransformType,
) -> PlanStepRequirement:
    return PlanStepRequirement(
        step_id=f"{blueprint_id}:{name}",
        identity=identity,
        requirement_class=PlanRequirementClass.INTERNAL_PREPARATION,
        insertion_point=InsertionPoint.BASE,
        internal_transform=transform,
    )


def _base_steps_for(
    blueprint_id: str,
    key: RulePackKey,
) -> tuple[PlanStepRequirement, ...]:
    read = _platform_step(
        blueprint_id,
        "read",
        PlanStepIdentity.READ,
        CapabilityType.READ,
        PlanStepType.READ,
    )
    verify = _platform_step(
        blueprint_id,
        "verify",
        PlanStepIdentity.VERIFY,
        CapabilityType.VERIFY,
        PlanStepType.VERIFY,
    )
    if key.domain == Domain.CONTENT and key.operation == Operation.SHARE:
        return (
            _internal_step(
                blueprint_id,
                "locate",
                PlanStepIdentity.LOCATE_CONTENT,
                InternalTransformType.LOCATE_CONTENT,
            ),
            read,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.DISPATCH,
                CapabilityType.DISPATCH,
                PlanStepType.DISPATCH,
                terminal=True,
            ),
        )
    if key.domain == Domain.MEMORY:
        return (
            read,
            verify,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.UPDATE,
                CapabilityType.UPDATE,
                PlanStepType.UPDATE,
                terminal=True,
            ),
        )
    if key.operation == Operation.VERIFY:
        return (
            read,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.VERIFY,
                CapabilityType.VERIFY,
                PlanStepType.VERIFY,
                terminal=True,
            ),
        )
    if key.domain == Domain.PAYMENT:
        return (
            read,
            verify,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.PAY,
                CapabilityType.PAY,
                PlanStepType.PAY,
                terminal=True,
            ),
        )
    if key.domain == Domain.DEVICE:
        return (
            read,
            verify,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.TOGGLE,
                CapabilityType.TOGGLE,
                PlanStepType.TOGGLE,
                terminal=True,
            ),
        )
    if key.domain == Domain.CALENDAR:
        return (
            read,
            verify,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.SCHEDULE,
                CapabilityType.SCHEDULE,
                PlanStepType.SCHEDULE,
                terminal=True,
            ),
        )
    if key.domain == Domain.GENERAL and key.operation == Operation.CLARIFY:
        return (
            read,
            _platform_step(
                blueprint_id,
                "terminal",
                PlanStepIdentity.CLARIFY,
                CapabilityType.CLARIFY,
                PlanStepType.CLARIFY,
                terminal=True,
            ),
        )
    raise ValueError(f"no BasePlanBlueprint definition for {key}")


def _dependencies_for(
    steps: tuple[PlanStepRequirement, ...],
) -> tuple[DependencySemantic, ...]:
    return tuple(
        DependencySemantic(before.step_id, after.step_id)
        for before, after in zip(steps, steps[1:])
    )


def _build_blueprint(
    pack: DomainOperationRulePack,
) -> BasePlanBlueprint:
    catalog = next(
        item
        for item in BLUEPRINT_CATALOG
        if item.blueprint_id == pack.base_blueprint_id
    )
    role_spec = RULEPACK_REGISTRY.role_spec(pack.required_role_spec_id)
    information = RULEPACK_REGISTRY.information_spec(pack.information_spec_id)
    steps = _base_steps_for(catalog.blueprint_id, pack.key)
    terminal = next(item.output_verb for item in steps if item.semantic_terminal)
    assert terminal is not None
    return BasePlanBlueprint(
        blueprint_id=catalog.blueprint_id,
        key=pack.key,
        semantic_terminal=terminal,
        base_steps=steps,
        platform_required_capabilities=tuple(
            dict.fromkeys(
                item.platform_capability
                for item in steps
                if item.platform_capability is not None
            )
        ),
        internal_transform_requirements=tuple(
            dict.fromkeys(
                item.internal_transform
                for item in steps
                if item.internal_transform is not None
            )
        ),
        required_target_roles=role_spec.allowed_roles,
        base_information_slots=information.required_slots,
        conditional_information_slots=tuple(
            item.slot for item in information.conditional_slots
        ),
        permitted_disclosure_modes=pack.permitted_disclosure_modes,
        dependency_semantics=_dependencies_for(steps),
        contract_status=pack.contract_status,
        assumption_refs=tuple(
            dict.fromkeys(
                pack.assumption_refs
                + (ACTIONS_ASSUMPTION_ID, TRANSFORM_ASSUMPTION_ID)
            )
        ),
        version="1.0.0",
    )


PLAN_BLUEPRINTS = tuple(_build_blueprint(pack) for pack in RULEPACK_REGISTRY.rulepacks)


class PlanBlueprintRegistry:
    production_active = False

    def __init__(
        self,
        blueprints: Iterable[BasePlanBlueprint] = PLAN_BLUEPRINTS,
    ) -> None:
        self.blueprints = tuple(blueprints)
        self._by_id = {item.blueprint_id: item for item in self.blueprints}
        self.validate()

    def lookup(self, blueprint_id: str) -> BasePlanBlueprint | None:
        return self._by_id.get(blueprint_id)

    def validate(self) -> None:
        ids = [item.blueprint_id for item in self.blueprints]
        keys = [item.key for item in self.blueprints]
        if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
            raise ValueError("duplicate BasePlanBlueprint identity")
        catalog_ids = {item.blueprint_id for item in BLUEPRINT_CATALOG}
        if set(ids) != catalog_ids:
            raise ValueError("BasePlanBlueprint catalog coverage mismatch")
        for blueprint in self.blueprints:
            self._validate_dependency_graph(blueprint)

    @staticmethod
    def _validate_dependency_graph(blueprint: BasePlanBlueprint) -> None:
        step_ids = {item.step_id for item in blueprint.base_steps}
        if any(
            edge.before_step_id not in step_ids or edge.after_step_id not in step_ids
            for edge in blueprint.dependency_semantics
        ):
            raise ValueError("blueprint dependency references unknown step")
        incoming: dict[str, int] = {step_id: 0 for step_id in step_ids}
        outgoing: dict[str, list[str]] = {step_id: [] for step_id in step_ids}
        for edge in blueprint.dependency_semantics:
            incoming[edge.after_step_id] += 1
            outgoing[edge.before_step_id].append(edge.after_step_id)
        queue = sorted(step_id for step_id, degree in incoming.items() if degree == 0)
        visited: list[str] = []
        while queue:
            current = queue.pop(0)
            visited.append(current)
            for child in sorted(outgoing[current]):
                incoming[child] -= 1
                if incoming[child] == 0:
                    queue.append(child)
                    queue.sort()
        if len(visited) != len(step_ids):
            raise ValueError("blueprint dependency graph contains a cycle")


PLAN_BLUEPRINT_REGISTRY = PlanBlueprintRegistry()


class PlanRequirementComposer:
    @classmethod
    def compose(
        cls,
        *,
        candidate_id: str,
        rulepack: DomainOperationRulePack,
        blueprint: BasePlanBlueprint,
        deltas: Iterable[PlanRequirementDelta] = (),
    ) -> FinalPlanRequirements:
        if rulepack.base_blueprint_id != blueprint.blueprint_id:
            raise ValueError("RulePack and BasePlanBlueprint identity mismatch")
        normalized_deltas = cls._normalize_deltas(deltas)
        canonical_deltas = cls._canonical_deltas(normalized_deltas)
        steps = list(blueprint.base_steps)
        terminal = next(item for item in steps if item.semantic_terminal)
        inserted: list[PlanStepRequirement] = []
        terminal_parameters: dict[str, str] = {}
        assumptions = list(blueprint.assumption_refs)

        for delta in canonical_deltas:
            if delta.effect_kind == ConstraintEffect.ADD_REDACTION:
                inserted.append(
                    cls._effect_step(
                        blueprint,
                        delta,
                        PlanStepIdentity.REDACT,
                        CapabilityType.REDACT,
                        PlanStepType.REDACT,
                    )
                )
                assumptions.append(TRANSFORM_ASSUMPTION_ID)
            elif delta.effect_kind == ConstraintEffect.FORCE_SUMMARY:
                inserted.append(
                    cls._effect_step(
                        blueprint,
                        delta,
                        PlanStepIdentity.SUMMARIZE,
                        CapabilityType.SUMMARIZE,
                        PlanStepType.SUMMARIZE,
                    )
                )
                assumptions.append(TRANSFORM_ASSUMPTION_ID)
            elif delta.effect_kind == ConstraintEffect.ADD_CONFIRMATION:
                inserted.append(
                    cls._effect_step(
                        blueprint,
                        delta,
                        PlanStepIdentity.CONFIRM,
                        CapabilityType.CLARIFY,
                        PlanStepType.CLARIFY,
                    )
                )
            elif delta.effect_kind == ConstraintEffect.LIMIT_DURATION:
                for name, value in delta.parameters:
                    existing = terminal_parameters.get(name)
                    if existing is not None and existing != value:
                        raise ValueError(
                            f"conflicting terminal parameter: {name}"
                        )
                    terminal_parameters[name] = value
            elif delta.effect_kind in {
                ConstraintEffect.RESTRICT_TARGET,
                ConstraintEffect.BLOCK_EXECUTION,
            }:
                continue
            else:
                raise ValueError(f"unsupported plan effect: {delta.effect_kind.value}")

        inserted = cls._dedupe_inserted_steps(inserted)
        if {
            item.identity for item in inserted
        } >= {PlanStepIdentity.REDACT, PlanStepIdentity.SUMMARIZE}:
            assumptions.append(PLAN_ORDER_ASSUMPTION_ID)
        terminal_index = steps.index(terminal)
        steps[terminal_index:terminal_index] = inserted
        dependencies = _dependencies_for(tuple(steps))
        capabilities = tuple(
            dict.fromkeys(
                item.platform_capability
                for item in steps
                if item.platform_capability is not None
            )
        )
        internal_transforms = tuple(
            dict.fromkeys(
                item.internal_transform
                for item in steps
                if item.internal_transform is not None
            )
        )
        return FinalPlanRequirements(
            candidate_id=candidate_id,
            rulepack_id=rulepack.rule_id,
            blueprint_id=blueprint.blueprint_id,
            domain=rulepack.key.domain,
            operation=rulepack.key.operation,
            semantic_terminal=blueprint.semantic_terminal,
            required_steps=tuple(steps),
            platform_required_capabilities=capabilities,
            internal_transform_requirements=internal_transforms,
            required_target_roles=blueprint.required_target_roles,
            required_information_slots=blueprint.base_information_slots,
            conditional_information_slots=blueprint.conditional_information_slots,
            permitted_disclosure_modes=blueprint.permitted_disclosure_modes,
            dependency_semantics=dependencies,
            terminal_parameters=tuple(sorted(terminal_parameters.items())),
            applied_effect_ids=tuple(item.effect_id for item in normalized_deltas),
            assumption_refs=tuple(dict.fromkeys(assumptions)),
        )

    @classmethod
    def _normalize_deltas(
        cls,
        deltas: Iterable[PlanRequirementDelta],
    ) -> tuple[PlanRequirementDelta, ...]:
        by_id: dict[str, PlanRequirementDelta] = {}
        for delta in deltas:
            try:
                constraint_effect_rank(delta.effect_kind)
            except ValueError:
                raise ValueError(
                    f"unsupported plan effect: {delta.effect_kind.value}"
                ) from None
            existing_id = by_id.get(delta.effect_id)
            if existing_id is not None and existing_id != delta:
                raise ValueError(f"effect ID collision: {delta.effect_id}")
            by_id[delta.effect_id] = delta
        return tuple(
            sorted(
                by_id.values(),
                key=cls._delta_sort_key,
            )
        )

    @classmethod
    def _canonical_deltas(
        cls,
        deltas: tuple[PlanRequirementDelta, ...],
    ) -> tuple[PlanRequirementDelta, ...]:
        by_key: dict[tuple[object, ...], PlanRequirementDelta] = {}
        for delta in deltas:
            by_key.setdefault(delta.canonical_key, delta)
        return tuple(sorted(by_key.values(), key=cls._delta_sort_key))

    @classmethod
    def _delta_sort_key(
        cls,
        item: PlanRequirementDelta,
    ) -> tuple[object, ...]:
        return (
            constraint_effect_rank(item.effect_kind),
            item.scope,
            tuple(sorted(item.parameters)),
            item.effect_id,
            item.source_kind.value,
            item.source_id,
            item.authorization_ref,
        )

    @staticmethod
    def _effect_step(
        blueprint: BasePlanBlueprint,
        delta: PlanRequirementDelta,
        identity: PlanStepIdentity,
        capability: CapabilityType,
        verb: PlanStepType,
    ) -> PlanStepRequirement:
        return PlanStepRequirement(
            step_id=f"{blueprint.blueprint_id}:effect:{identity.value}",
            identity=identity,
            requirement_class=PlanRequirementClass.PLATFORM_ACTION,
            insertion_point=InsertionPoint.BEFORE_TERMINAL,
            platform_capability=capability,
            output_verb=verb,
        )

    @classmethod
    def _dedupe_inserted_steps(
        cls,
        steps: list[PlanStepRequirement],
    ) -> list[PlanStepRequirement]:
        identity_order = {
            PlanStepIdentity.REDACT: constraint_effect_rank(
                ConstraintEffect.ADD_REDACTION
            ),
            PlanStepIdentity.SUMMARIZE: constraint_effect_rank(
                ConstraintEffect.FORCE_SUMMARY
            ),
            PlanStepIdentity.CONFIRM: constraint_effect_rank(
                ConstraintEffect.ADD_CONFIRMATION
            ),
        }
        by_identity: dict[PlanStepIdentity, PlanStepRequirement] = {}
        for step in steps:
            by_identity.setdefault(step.identity, step)
        return sorted(
            by_identity.values(),
            key=lambda item: identity_order[item.identity],
        )


class FinalPlanRequirementsBuilder:
    @staticmethod
    def build(
        *,
        candidate_id: str,
        resolution: RulePackResolution,
        deltas: Iterable[PlanRequirementDelta] = (),
    ) -> FinalPlanRequirements:
        if (
            resolution.availability != RulePackAvailability.FOUND
            or resolution.rulepack is None
        ):
            raise ValueError("unsupported RulePack cannot produce plan requirements")
        blueprint = PLAN_BLUEPRINT_REGISTRY.lookup(
            resolution.rulepack.base_blueprint_id
        )
        if blueprint is None:
            raise ValueError("RulePack references an unknown BasePlanBlueprint")
        return PlanRequirementComposer.compose(
            candidate_id=candidate_id,
            rulepack=resolution.rulepack,
            blueprint=blueprint,
            deltas=deltas,
        )


def validate_plan_blueprint_registry() -> None:
    PLAN_BLUEPRINT_REGISTRY.validate()
