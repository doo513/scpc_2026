from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable


PROPERTY_METADATA_VERSION = "scpc.property-metadata.v1"
DISCLOSURE_POLICY_VERSION = "scpc.property-disclosure.v2"
POLICY_EXCLUSION_VERSION = "scpc.policy-exclusion.v1"


class PropertyClassification(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    RESTRICTED = "restricted"
    SECRET = "secret"
    UNKNOWN = "unknown"


class PropertySource(str, Enum):
    CONTAINS = "contains"
    FIELDS = "fields"
    DIRECT_ATTR = "direct_attr"


class DisclosureDirective(str, Enum):
    ALLOW = "allow"
    FORCE_SUMMARY = "force_summary"
    ADD_REDACTION = "add_redaction"
    BLOCK = "block"


@dataclass(frozen=True)
class PropertyDescriptor:
    subject_id: str
    object_type: str
    name: str
    classification: PropertyClassification
    source: PropertySource
    metadata_version: str = PROPERTY_METADATA_VERSION

    @property
    def provenance_id(self) -> str:
        return (
            f"property:{self.subject_id}:{self.source.value}:{self.name}:"
            f"{self.metadata_version}"
        )

    def to_trace(self) -> dict[str, str]:
        return {
            "subject_id": self.subject_id,
            "object_type": self.object_type,
            "name": self.name,
            "classification": self.classification.value,
            "source": self.source.value,
            "metadata_version": self.metadata_version,
            "provenance_id": self.provenance_id,
        }


@dataclass(frozen=True)
class DisclosureRuleEffect:
    severity: str | None
    directive: DisclosureDirective
    governing_classification: PropertyClassification | None
    permitted_modes: frozenset[str]
    excluded_fields: tuple[str, ...]
    reason: str
    policy_version: str = DISCLOSURE_POLICY_VERSION


@dataclass(frozen=True)
class PolicyExclusion:
    """A public exclusion category with independently checkable provenance."""

    name: str
    source_ids: tuple[str, ...]
    policy_version: str = POLICY_EXCLUSION_VERSION

    def __post_init__(self) -> None:
        if not self.name or not self.source_ids:
            raise ValueError("policy exclusion requires a name and provenance")
        if tuple(sorted(set(self.source_ids))) != self.source_ids:
            raise ValueError("policy exclusion provenance must be canonical")

    @property
    def provenance_id(self) -> str:
        return f"policy-exclusion:{self.name}:{self.policy_version}"


@dataclass(frozen=True)
class ClassificationDisclosureRule:
    severity: str | None
    directive: DisclosureDirective
    permitted_modes: frozenset[str]
    reason: str


# Classification facts are declarative and do not encode control or Blueprint effects.
_CLASSIFICATION_BY_PROPERTY: dict[str, PropertyClassification] = {
    **{
        name: PropertyClassification.SECRET
        for name in ("account_token", "card_number", "password", "rrn")
    },
    **{
        name: PropertyClassification.RESTRICTED
        for name in (
            "age",
            "amount",
            "birthday",
            "checkup_time",
            "doctor_note",
            "image",
            "location",
            "medication_reminder",
            "medication_time",
            "name",
            "numeric_value",
            "person",
            "raw_memory",
            "raw_quote",
            "risk_summary",
        )
    },
    **{
        name: PropertyClassification.INTERNAL
        for name in (
            "avoid",
            "channel",
            "dusk_lights",
            "gift",
            "gift_hint",
            "privacy",
            "privacy_rule",
            "status",
            "time",
            "tone",
        )
    },
    "summary": PropertyClassification.PUBLIC,
    "title": PropertyClassification.PUBLIC,
}


# Public exclusions are policy categories, not necessarily concrete object
# attributes.  This metadata is deliberately separate from field inventory so
# a policy can deny (for example) raw quotations even when an object exposes
# only a structural ``body`` attribute.
_POLICY_CATEGORIES_BY_PROPERTY: dict[str, frozenset[str]] = {
    "account_token": frozenset({"raw_quote"}),
    "age": frozenset({"numeric_value"}),
    "amount": frozenset({"numeric_value"}),
    "birthday": frozenset({"numeric_value"}),
    "card_number": frozenset({"numeric_value"}),
    "checkup_time": frozenset({"numeric_value"}),
    "doctor_note": frozenset({"doctor_note"}),
    "image": frozenset({"raw_quote"}),
    "location": frozenset({"location"}),
    "medication_reminder": frozenset({"raw_quote"}),
    "medication_time": frozenset({"numeric_value"}),
    "name": frozenset({"name"}),
    "numeric_value": frozenset({"numeric_value"}),
    "password": frozenset({"raw_quote"}),
    "person": frozenset({"name"}),
    "raw_memory": frozenset({"raw_quote"}),
    "raw_quote": frozenset({"raw_quote"}),
    "risk_summary": frozenset({"raw_quote"}),
    "rrn": frozenset({"rrn"}),
}

_VIRTUAL_POLICY_CATEGORIES_BY_OBJECT_TYPE: dict[str, frozenset[str]] = {
    "health_record": frozenset({"raw_quote"}),
    "message": frozenset({"raw_quote"}),
    "personal_note": frozenset({"raw_quote"}),
}

_EXTERNAL_POLICY_CATEGORIES: dict[str, frozenset[str]] = {
    "doctor_note_forbidden": frozenset({"raw_quote"}),
    "raw_quote_forbidden": frozenset({"raw_quote"}),
    "raw_sensitive_forbidden": frozenset(),
    "summary_only_allowed": frozenset({"raw_quote"}),
}

_STATUS_ONLY_STRICT_CATEGORIES = frozenset(
    {"raw_quote", "location", "numeric_value"}
)


# These attrs are structural/operation inputs for known official object types. They are
# not a claim that attrs is an exhaustive property inventory. An unknown direct attr is
# preserved as an UNKNOWN property instead of disappearing.
_OPERATION_ATTRS_BY_OBJECT_TYPE: dict[str, frozenset[str]] = {
    "calendar_event": frozenset({"attendee", "conflict", "ref_code", "time", "title"}),
    "device_setting": frozenset({"current", "name", "owner", "ref_code"}),
    "file": frozenset({"owner", "ref_code", "title"}),
    "gallery_item": frozenset({"owner", "ref_code", "title"}),
    "health_record": frozenset({"ref_code", "status", "title"}),
    "iot_routine": frozenset({"actions", "name", "ref_code", "target"}),
    "message": frozenset({"body", "recipient", "ref_code", "thread_id"}),
    "payment_request": frozenset({"amount", "merchant", "method", "ref_code"}),
    "personal_note": frozenset({"owner", "ref_code", "request_hint", "title"}),
}
_KNOWN_OBJECT_TYPES = frozenset(_OPERATION_ATTRS_BY_OBJECT_TYPE)
_UNIVERSAL_OPERATION_ATTRS = frozenset({"ref_code"})


# Classification and disclosure behavior form one closed policy matrix.  The
# matrix is evaluated by classification, never by task/session identity or by a
# special-case focal type.  More restrictive rows dominate when an object has
# properties from multiple rows.
_DISCLOSURE_RULE_BY_CLASSIFICATION: dict[
    PropertyClassification, ClassificationDisclosureRule
] = {
    PropertyClassification.PUBLIC: ClassificationDisclosureRule(
        severity=None,
        directive=DisclosureDirective.ALLOW,
        permitted_modes=frozenset(
            {"raw", "summary", "redacted", "status_only", "none"}
        ),
        reason="public_properties_allow_blueprint_scope",
    ),
    PropertyClassification.INTERNAL: ClassificationDisclosureRule(
        severity="amend",
        directive=DisclosureDirective.FORCE_SUMMARY,
        permitted_modes=frozenset({"summary", "redacted", "none"}),
        reason="internal_properties_require_summary_or_stricter",
    ),
    PropertyClassification.RESTRICTED: ClassificationDisclosureRule(
        severity="amend",
        directive=DisclosureDirective.ADD_REDACTION,
        permitted_modes=frozenset({"redacted", "none"}),
        reason="restricted_properties_require_redaction_or_blocking",
    ),
    PropertyClassification.SECRET: ClassificationDisclosureRule(
        severity="amend",
        directive=DisclosureDirective.ADD_REDACTION,
        permitted_modes=frozenset({"redacted", "none"}),
        reason="secret_properties_must_be_removed_before_disclosure",
    ),
    PropertyClassification.UNKNOWN: ClassificationDisclosureRule(
        severity="hard",
        directive=DisclosureDirective.BLOCK,
        permitted_modes=frozenset({"none"}),
        reason="unknown_property_requires_fail_closed_disclosure",
    ),
}
_CLASSIFICATION_RESTRICTION_RANK = {
    PropertyClassification.PUBLIC: 0,
    PropertyClassification.INTERNAL: 1,
    PropertyClassification.RESTRICTED: 2,
    PropertyClassification.SECRET: 3,
    PropertyClassification.UNKNOWN: 4,
}

_VALID_DISCLOSURE_MODES = frozenset(
    {"raw", "summary", "redacted", "status_only", "none"}
)


def validate_disclosure_policy_matrix(
    matrix: Mapping[
        PropertyClassification, ClassificationDisclosureRule
    ] = _DISCLOSURE_RULE_BY_CLASSIFICATION,
) -> None:
    """Fail fast when the closed disclosure matrix is incomplete or weaker."""
    classifications = set(PropertyClassification)
    actual = set(matrix)
    if actual != classifications:
        missing = sorted(item.value for item in classifications - actual)
        unexpected = sorted(str(item) for item in actual - classifications)
        raise ValueError(
            "property disclosure matrix must be total: "
            f"missing={missing} unexpected={unexpected}"
        )

    expected_contract = {
        PropertyClassification.PUBLIC: (None, DisclosureDirective.ALLOW),
        PropertyClassification.INTERNAL: (
            "amend",
            DisclosureDirective.FORCE_SUMMARY,
        ),
        PropertyClassification.RESTRICTED: (
            "amend",
            DisclosureDirective.ADD_REDACTION,
        ),
        PropertyClassification.SECRET: (
            "amend",
            DisclosureDirective.ADD_REDACTION,
        ),
        PropertyClassification.UNKNOWN: (
            "hard",
            DisclosureDirective.BLOCK,
        ),
    }
    ordered = sorted(
        PropertyClassification,
        key=_CLASSIFICATION_RESTRICTION_RANK.__getitem__,
    )
    previous_modes: frozenset[str] | None = None
    for classification in ordered:
        rule = matrix[classification]
        if (rule.severity, rule.directive) != expected_contract[classification]:
            raise ValueError(
                "property disclosure row violates its severity/directive contract: "
                f"{classification.value}"
            )
        if (
            not rule.permitted_modes
            or not rule.permitted_modes <= _VALID_DISCLOSURE_MODES
        ):
            raise ValueError(
                f"property disclosure row has invalid modes: {classification.value}"
            )
        if "none" not in rule.permitted_modes:
            raise ValueError(
                f"property disclosure row cannot fail closed: {classification.value}"
            )
        if (
            previous_modes is not None
            and not rule.permitted_modes <= previous_modes
        ):
            raise ValueError(
                "more restrictive property classification widens disclosure modes: "
                f"{classification.value}"
            )
        previous_modes = rule.permitted_modes

    if matrix[PropertyClassification.UNKNOWN].permitted_modes != frozenset(
        {"none"}
    ):
        raise ValueError("UNKNOWN property disclosure must be HARD/NONE")


validate_disclosure_policy_matrix()


def classify_property(name: str) -> PropertyClassification:
    return _CLASSIFICATION_BY_PROPERTY.get(name, PropertyClassification.UNKNOWN)


def describe_object_properties(obj: dict[str, Any]) -> tuple[PropertyDescriptor, ...]:
    subject_id = str(obj.get("id") or "")
    object_type = str(obj.get("type") or "")
    attrs = obj.get("attrs") if isinstance(obj.get("attrs"), dict) else {}
    assert isinstance(attrs, dict)
    descriptors: dict[tuple[str, PropertySource], PropertyDescriptor] = {}

    for inventory_key, source in (
        ("contains", PropertySource.CONTAINS),
        ("fields", PropertySource.FIELDS),
    ):
        inventory = attrs.get(inventory_key)
        if not isinstance(inventory, list):
            continue
        for raw_name in inventory:
            name = str(raw_name)
            descriptors[(name, source)] = PropertyDescriptor(
                subject_id,
                object_type,
                name,
                (
                    classify_property(name)
                    if object_type in _KNOWN_OBJECT_TYPES
                    else PropertyClassification.UNKNOWN
                ),
                source,
            )

    known_operation_attrs = _OPERATION_ATTRS_BY_OBJECT_TYPE.get(
        object_type, frozenset()
    ) | _UNIVERSAL_OPERATION_ATTRS
    for raw_name in attrs:
        name = str(raw_name)
        if name in {"contains", "fields"} or name in known_operation_attrs:
            continue
        descriptors[(name, PropertySource.DIRECT_ATTR)] = PropertyDescriptor(
            subject_id,
            object_type,
            name,
            (
                classify_property(name)
                if object_type in _KNOWN_OBJECT_TYPES
                else PropertyClassification.UNKNOWN
            ),
            PropertySource.DIRECT_ATTR,
        )

    return tuple(
        sorted(
            descriptors.values(),
            key=lambda item: (item.name, item.source.value),
        )
    )


def derive_policy_exclusions(
    properties: Iterable[PropertyDescriptor],
    mode: str,
    *,
    object_type: str = "",
    session_policy: str = "",
    external_policy: str = "",
    privacy_guard: str = "",
) -> tuple[PolicyExclusion, ...]:
    """Compile public exclusions from policy facts, not answer templates.

    Concrete UNKNOWN fields retain their own names so fail-closed behavior is
    auditable.  Known properties are projected to stable public policy
    categories.  An empty concrete inventory therefore cannot hide a policy
    denial, and a policy category does not pretend to be a concrete attribute.
    """

    items = tuple(properties)
    sources: dict[str, set[str]] = {}

    def add(name: str, source_id: str) -> None:
        sources.setdefault(name, set()).add(source_id)

    for item in items:
        if item.classification == PropertyClassification.UNKNOWN:
            add(item.name, item.provenance_id)

    if mode in {"none", "raw"}:
        return tuple(
            PolicyExclusion(name, tuple(sorted(source_ids)))
            for name, source_ids in sorted(sources.items())
        )

    if mode == "status_only":
        if session_policy == "strict":
            for category in _STATUS_ONLY_STRICT_CATEGORIES:
                add(
                    category,
                    f"policy:session_share_policy:strict:{POLICY_EXCLUSION_VERSION}",
                )
        for item in items:
            if item.name in _STATUS_ONLY_STRICT_CATEGORIES:
                add(item.name, item.provenance_id)
        if privacy_guard == "minor_location_protected":
            for category in _STATUS_ONLY_STRICT_CATEGORIES:
                add(
                    category,
                    f"policy:privacy_guard:{privacy_guard}:{POLICY_EXCLUSION_VERSION}",
                )
    else:
        for item in items:
            if item.classification == PropertyClassification.SECRET:
                add(item.name, item.provenance_id)
                continue
            for category in _POLICY_CATEGORIES_BY_PROPERTY.get(
                item.name, frozenset()
            ):
                add(category, item.provenance_id)

        object_types = {item.object_type for item in items if item.object_type}
        if object_type:
            object_types.add(object_type)
        for object_type in object_types:
            for category in _VIRTUAL_POLICY_CATEGORIES_BY_OBJECT_TYPE.get(
                object_type, frozenset()
            ):
                add(
                    category,
                    f"policy:object_type:{object_type}:{POLICY_EXCLUSION_VERSION}",
                )

        for category in _EXTERNAL_POLICY_CATEGORIES.get(
            external_policy, frozenset()
        ):
            add(
                category,
                f"policy:external_share_policy:{external_policy}:"
                f"{POLICY_EXCLUSION_VERSION}",
            )
        if privacy_guard == "minor_location_protected":
            add(
                "location",
                f"policy:privacy_guard:{privacy_guard}:{POLICY_EXCLUSION_VERSION}",
            )

    return tuple(
        PolicyExclusion(name, tuple(sorted(source_ids)))
        for name, source_ids in sorted(sources.items())
    )


def evaluate_disclosure_properties(
    properties: Iterable[PropertyDescriptor],
) -> DisclosureRuleEffect:
    items = tuple(properties)
    if items:
        governing_classification = max(
            (item.classification for item in items),
            key=_CLASSIFICATION_RESTRICTION_RANK.__getitem__,
        )
        rule = _DISCLOSURE_RULE_BY_CLASSIFICATION[governing_classification]
        excluded = tuple(
            sorted(
                {
                    item.name
                    for item in items
                    if item.classification != PropertyClassification.PUBLIC
                }
            )
        )
        return DisclosureRuleEffect(
            severity=rule.severity,
            directive=rule.directive,
            governing_classification=governing_classification,
            permitted_modes=rule.permitted_modes,
            excluded_fields=excluded,
            reason=rule.reason,
        )
    return DisclosureRuleEffect(
        severity=None,
        directive=DisclosureDirective.ALLOW,
        governing_classification=None,
        permitted_modes=frozenset(
            {"raw", "summary", "redacted", "status_only", "none"}
        ),
        excluded_fields=(),
        reason="no_disclosure_properties_declared",
    )
