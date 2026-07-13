from __future__ import annotations

import json

import pytest

import release_gate

from release_gate import (
    _harness_static_analysis,
    _promote_release_candidate,
    _release_check_contract,
    _semantic_safety_checks,
    _specificity_hits_for_source,
    _specificity_scan_paths,
    REQUIRED_RELEASE_CHECK_IDS,
)


VALID_HARNESS = """
class FinalHarness:
    def answer_task(self, task, session):
        projection = ProductionProjectionPipeline.compile(task)
        ConsistencyValidator.validate_strict(projection, task, {}, {})
        if task:
            AtomicSessionCommitter.commit(session, None)
"""


def test_ast_gate_confirms_reachable_projection_validation_commit_order() -> None:
    result = _harness_static_analysis(VALID_HARNESS)

    assert result["projection_pipeline_wired"] is True
    assert result["validation_before_commit"] is True
    assert result["scanner"] == "reachable_python_ast_calls"


def test_comments_and_unreachable_calls_cannot_satisfy_lifecycle_gate() -> None:
    source = """
class FinalHarness:
    def answer_task(self, task, session):
        # ConsistencyValidator.validate_strict(...)
        if False:
            ConsistencyValidator.validate_strict(None, None, None, None)
        AtomicSessionCommitter.commit(session, None)
"""

    result = _harness_static_analysis(source)

    assert result["validation_before_commit"] is False
    assert result["projection_pipeline_wired"] is False


def test_specificity_ast_ignores_comments_but_detects_runtime_literals() -> None:
    comment_only = "# final_dev_fake must not count\nvalue = 'safe'\n"
    runtime_literal = "value = 'final_dev_forbidden'\n"

    assert _specificity_hits_for_source(comment_only, path="comment.py") == []
    hits = _specificity_hits_for_source(runtime_literal, path="runtime.py")
    assert hits == [
        {"path": "runtime.py", "line": 1, "marker": "final_dev_"}
    ]


def test_specificity_scan_covers_submission_scorer_and_utils() -> None:
    paths = {path.as_posix() for path in _specificity_scan_paths()}

    assert any(path.endswith("/run_submission.py") for path in paths)
    assert any(path.endswith("/local_score.py") for path in paths)
    assert any(path.endswith("/utils/io.py") for path in paths)


def test_specificity_ast_flags_identity_dependent_branch() -> None:
    source = "if task_id.endswith('chosen-case'):\n    return 'different'\n"

    hits = _specificity_hits_for_source(source, path="runtime.py")

    assert {
        "path": "runtime.py",
        "line": 1,
        "marker": "identity_dependent_branch",
    } in hits


def test_required_release_check_contract_rejects_missing_and_non_boolean() -> None:
    valid = {key: True for key in REQUIRED_RELEASE_CHECK_IDS}
    assert _release_check_contract(valid)["passed"] is True

    missing = dict(valid)
    missing.pop("scope_trace_tampering_rejected")
    assert _release_check_contract(missing) == {
        "passed": False,
        "required_ids": sorted(REQUIRED_RELEASE_CHECK_IDS),
        "missing_ids": ["scope_trace_tampering_rejected"],
        "unexpected_ids": [],
        "non_boolean_ids": [],
    }

    non_boolean = {**valid, "unknown_property_fail_closed": "yes"}
    result = _release_check_contract(non_boolean)
    assert result["passed"] is False
    assert result["non_boolean_ids"] == ["unknown_property_fail_closed"]


def test_semantic_release_checks_execute_f1_and_f2_counterexamples() -> None:
    result = _semantic_safety_checks()

    assert result["checks"] == {
        "unknown_property_fail_closed": True,
        "property_inventories_merged": True,
        "property_policy_matrix_valid": True,
        "classified_property_policy_enforced": True,
        "unknown_object_direct_attr_fail_closed": True,
        "scope_trace_tampering_rejected": True,
        "mutable_authority_rejected": True,
    }
    for evidence_key in (
        "declared_unknown",
        "attrs_only_unknown",
        "merged_inventory",
        "unknown_direct_attr",
    ):
        evidence = result["evidence"][evidence_key]
        assert all(
            evidence[key]
            for key in (
                "control_hold",
                "scope_none",
                "field_excluded",
                "hard_constraint",
            )
        )
    assert "authority" in result["evidence"]["scope_trace_tampering_error"]
    assert "immutable FinalDecision" in result["evidence"][
        "mutable_authority_error"
    ]


def test_failed_release_never_validates_or_promotes_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    manifest_dir = tmp_path / "manifest"
    manifest_dir.mkdir()
    authoritative = manifest_dir / "candidate_manifest.json"
    authoritative.write_text(json.dumps({"sentinel": "unchanged"}), encoding="utf-8")
    before = authoritative.read_bytes()
    calls: list[str] = []

    monkeypatch.setattr(release_gate, "BASE_DIR", tmp_path)
    monkeypatch.setattr(
        release_gate,
        "validate_current_artifacts",
        lambda **_kwargs: calls.append("validate"),
    )
    monkeypatch.setattr(
        release_gate,
        "promote_validated_candidate_manifest",
        lambda *_args, **_kwargs: calls.append("promote"),
    )

    result = _promote_release_candidate(
        released=False,
        dev={},
        reproduce=False,
        reproduce_reports=False,
    )

    assert result is None
    assert calls == []
    assert authoritative.read_bytes() == before
    assert list(manifest_dir.iterdir()) == [authoritative]


def test_successful_release_validates_before_promotion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    (tmp_path / "manifest").mkdir()
    (tmp_path / "submission.csv").write_text("id,answer\n", encoding="utf-8")
    calls: list[str] = []

    def publish(_dev, _submission, *, output_path):
        calls.append("publish")
        output_path.write_text("{}", encoding="utf-8")

    def validate(*, manifest_path, **_kwargs):
        assert manifest_path.is_file()
        calls.append("validate")
        return {"manifest_content_fingerprint_sha256": "a" * 64}

    def promote(staged_manifest, validation):
        assert staged_manifest.is_file()
        assert validation["manifest_content_fingerprint_sha256"] == "a" * 64
        calls.append("promote")

    monkeypatch.setattr(release_gate, "BASE_DIR", tmp_path)
    monkeypatch.setattr(release_gate, "publish_candidate_manifest", publish)
    monkeypatch.setattr(release_gate, "validate_current_artifacts", validate)
    monkeypatch.setattr(
        release_gate,
        "promote_validated_candidate_manifest",
        promote,
    )

    result = _promote_release_candidate(
        released=True,
        dev={},
        reproduce=False,
        reproduce_reports=False,
    )

    assert result == {"manifest_content_fingerprint_sha256": "a" * 64}
    assert calls == ["publish", "validate", "promote"]
    assert not (
        tmp_path / "manifest" / ".candidate_manifest.release.pending.json"
    ).exists()
