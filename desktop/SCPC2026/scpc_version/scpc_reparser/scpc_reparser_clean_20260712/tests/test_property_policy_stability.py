from __future__ import annotations

from dataclasses import replace
from itertools import permutations

import pytest

from core.blueprint import project_scope_mode
from core.property_policy import (
    PropertyClassification,
    PropertyDescriptor,
    PropertySource,
    _DISCLOSURE_RULE_BY_CLASSIFICATION,
    describe_object_properties,
    evaluate_disclosure_properties,
    validate_disclosure_policy_matrix,
)


def _descriptor(
    name: str,
    classification: PropertyClassification,
) -> PropertyDescriptor:
    return PropertyDescriptor(
        subject_id="object",
        object_type="file",
        name=name,
        classification=classification,
        source=PropertySource.CONTAINS,
    )


def test_disclosure_policy_matrix_is_total_monotone_and_fail_closed() -> None:
    validate_disclosure_policy_matrix()

    with pytest.raises(ValueError, match="must be total"):
        validate_disclosure_policy_matrix({})

    weakened = dict(_DISCLOSURE_RULE_BY_CLASSIFICATION)
    weakened[PropertyClassification.UNKNOWN] = replace(
        weakened[PropertyClassification.UNKNOWN],
        permitted_modes=frozenset({"summary", "none"}),
    )
    with pytest.raises(ValueError, match="widens disclosure modes|HARD/NONE"):
        validate_disclosure_policy_matrix(weakened)


@pytest.mark.parametrize(
    ("compiled", "control", "expected"),
    [
        ("raw", "proceed", "raw"),
        ("raw", "ask", "summary"),
        ("summary", "ask", "summary"),
        ("redacted", "ask", "redacted"),
        ("status_only", "ask", "none"),
        ("redacted", "hold", "none"),
    ],
)
def test_scope_projection_preserves_safety_without_implying_execution(
    compiled: str,
    control: str,
    expected: str,
) -> None:
    assert project_scope_mode(compiled, control) == expected


def test_unknown_dominance_is_independent_of_property_order() -> None:
    properties = (
        _descriptor("summary", PropertyClassification.PUBLIC),
        _descriptor("tone", PropertyClassification.INTERNAL),
        _descriptor("doctor_note", PropertyClassification.RESTRICTED),
        _descriptor("password", PropertyClassification.SECRET),
        _descriptor("novel", PropertyClassification.UNKNOWN),
    )

    expected = evaluate_disclosure_properties(properties)
    assert expected.governing_classification == PropertyClassification.UNKNOWN
    assert expected.severity == "hard"
    assert expected.permitted_modes == frozenset({"none"})
    assert expected.excluded_fields == (
        "doctor_note",
        "novel",
        "password",
        "tone",
    )

    for ordered in permutations(properties):
        assert evaluate_disclosure_properties(ordered) == expected


def test_merged_inventories_preserve_both_sources_without_weakening() -> None:
    properties = describe_object_properties(
        {
            "id": "object",
            "type": "file",
            "attrs": {
                "ref_code": "WM-POLICY-STABILITY",
                "contains": ["summary", "tone"],
                "fields": ["tone", "doctor_note"],
            },
        }
    )

    assert {(item.name, item.source) for item in properties} == {
        ("summary", PropertySource.CONTAINS),
        ("tone", PropertySource.CONTAINS),
        ("tone", PropertySource.FIELDS),
        ("doctor_note", PropertySource.FIELDS),
    }
    effect = evaluate_disclosure_properties(properties)
    assert effect.governing_classification == PropertyClassification.RESTRICTED
    assert effect.severity == "amend"
    assert effect.permitted_modes == frozenset({"redacted", "none"})
    assert effect.excluded_fields == ("doctor_note", "tone")
