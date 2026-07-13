from __future__ import annotations

import copy
import json

import pytest

from build_manifest import (
    FIXED_SLM_STATUS_PATH,
    MANIFEST_PRODUCER,
    MANIFEST_SCHEMA,
    artifact_content_hash,
    manifest_content_fingerprint,
    promote_validated_candidate_manifest,
)


def test_manifest_fingerprint_uses_content_not_generation_time() -> None:
    first = {
        "schema": "scpc.artifact-manifest.v2",
        "producer": MANIFEST_PRODUCER,
        "generated_at": "2026-01-01T00:00:00Z",
        "submission_sha256": "a" * 64,
    }
    later = copy.deepcopy(first)
    later["generated_at"] = "2030-01-01T00:00:00Z"

    assert manifest_content_fingerprint(first) == manifest_content_fingerprint(later)

    later["submission_sha256"] = "b" * 64
    assert manifest_content_fingerprint(first) != manifest_content_fingerprint(later)


def test_fixed_slm_is_explicitly_shadow_only() -> None:
    status = json.loads(FIXED_SLM_STATUS_PATH.read_text(encoding="utf-8"))

    assert status["decision"] == "KEEP_SHADOW"
    assert status["production_influence"] is False


def test_json_artifact_hash_ignores_only_declared_generation_time(tmp_path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps({"generated_at": "2026-01-01T00:00:00Z", "status": "PASS"}),
        encoding="utf-8",
    )
    first = artifact_content_hash(report)

    report.write_text(
        json.dumps({"generated_at": "2030-01-01T00:00:00Z", "status": "PASS"}),
        encoding="utf-8",
    )
    assert artifact_content_hash(report) == first

    report.write_text(
        json.dumps({"generated_at": "2030-01-01T00:00:00Z", "status": "FAIL"}),
        encoding="utf-8",
    )
    assert artifact_content_hash(report) != first


def test_candidate_manifest_is_not_promoted_without_matching_validation(
    tmp_path,
) -> None:
    staged = tmp_path / "pending.json"
    authoritative = tmp_path / "candidate_manifest.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "producer": MANIFEST_PRODUCER,
        "generated_at": "2026-01-01T00:00:00Z",
        "submission_sha256": "a" * 64,
    }
    manifest["content_fingerprint_sha256"] = manifest_content_fingerprint(
        manifest
    )
    staged.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="not the validated content"):
        promote_validated_candidate_manifest(
            staged,
            {"manifest_content_fingerprint_sha256": "b" * 64},
            output_path=authoritative,
        )

    assert staged.is_file()
    assert not authoritative.exists()

    promote_validated_candidate_manifest(
        staged,
        {
            "manifest_content_fingerprint_sha256": manifest[
                "content_fingerprint_sha256"
            ]
        },
        output_path=authoritative,
    )
    assert not staged.exists()
    assert json.loads(authoritative.read_text(encoding="utf-8")) == manifest
