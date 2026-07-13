from __future__ import annotations

from pathlib import Path

from step1_baseline import (
    BASE_DIR,
    combined_hash,
    config_files,
    registry_ontology_files,
    resolve_report_root,
)


def test_report_root_priority_is_explicit(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    root, source = resolve_report_root(
        environ={"SCPC_REPORT_DIR": str(configured)},
        home=tmp_path,
        workspace=tmp_path / "workspace",
    )

    assert root == configured
    assert source == "SCPC_REPORT_DIR"


def test_step1_hash_inputs_are_stable_and_inside_workspace() -> None:
    configs = config_files()
    registry_files = registry_ontology_files()

    assert configs
    assert registry_files
    assert all(path.is_file() and path.is_relative_to(BASE_DIR) for path in configs)
    assert all(
        path.is_file() and path.is_relative_to(BASE_DIR)
        for path in registry_files
    )
    assert combined_hash(configs, root=BASE_DIR) == combined_hash(
        reversed(configs), root=BASE_DIR
    )
    assert combined_hash(registry_files, root=BASE_DIR) == combined_hash(
        reversed(registry_files), root=BASE_DIR
    )
