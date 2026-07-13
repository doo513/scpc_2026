from __future__ import annotations

import hashlib
import inspect

import pytest

from build_manifest import official_archive_path, sha256_file, write_reference_manifest
from official_baseline import (
    find_official_notebook,
    generate_official_baseline_submission,
)
from utils.io import (
    PROJECT_DIR,
    find_baseline_submission,
    find_data_dir,
    find_official_archive,
    require_workspace_path,
)
from validate_artifacts import (
    _temporary_reproduction_directory,
    reproduce_report_artifacts,
)


def test_data_discovery_has_no_parent_or_cwd_fallback() -> None:
    source = inspect.getsource(find_data_dir)

    assert "PROJECT_DIR.parent" not in source
    assert "Path.cwd" not in source
    assert "find_official_archive()" in source


def test_baseline_and_archive_discovery_are_workspace_local() -> None:
    baseline_source = inspect.getsource(find_baseline_submission)
    archive_source = inspect.getsource(official_archive_path)
    reference_source = inspect.getsource(write_reference_manifest)

    assert "PROJECT_DIR.parent" not in baseline_source
    assert "BASE_DIR.parent" not in archive_source
    assert "scpc_Gparser" not in reference_source


def test_official_assets_resolve_inside_the_workspace() -> None:
    archive = find_official_archive()

    assert archive is not None
    assert archive.resolve().is_relative_to(PROJECT_DIR.resolve())
    assert find_data_dir().resolve().is_relative_to(PROJECT_DIR.resolve())
    assert find_official_notebook().resolve().is_relative_to(
        PROJECT_DIR.resolve()
    )


def test_official_notebook_baseline_is_byte_reproducible() -> None:
    baseline = find_baseline_submission()
    before = sha256_file(baseline)

    regenerated = generate_official_baseline_submission()

    assert sha256_file(regenerated) == before


def test_archive_hash_mismatch_invalidates_complete_cache() -> None:
    archive = find_official_archive()
    assert archive is not None
    marker = PROJECT_DIR / ".cache" / "scpc_data" / ".archive.sha256"
    marker.write_text("stale-cache-hash\n", encoding="ascii")

    data_dir = find_data_dir()

    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert data_dir == PROJECT_DIR / ".cache" / "scpc_data" / "data"
    assert marker.read_text(encoding="ascii").strip() == expected


def test_report_reproduction_does_not_copy_sibling_repositories() -> None:
    source = inspect.getsource(reproduce_report_artifacts)
    temporary_source = inspect.getsource(_temporary_reproduction_directory)

    assert "scpc_Gparser" not in source
    assert "BASE_DIR.parent" not in source
    assert "dir=REPRODUCTION_ROOT" in temporary_source


def test_workspace_boundary_rejects_external_path_without_reading_it() -> None:
    external = PROJECT_DIR.parent / "outside-input"

    with pytest.raises(ValueError, match="must be inside the workspace"):
        require_workspace_path(external, label="test input")
