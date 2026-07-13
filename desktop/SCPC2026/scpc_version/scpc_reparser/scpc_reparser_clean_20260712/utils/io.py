from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent
OFFICIAL_DATA_FILES = (
    "dev_tasks.jsonl",
    "dev_answers.json",
    "screening_tasks.jsonl",
)
OFFICIAL_ARCHIVE_CANDIDATES = (
    PROJECT_DIR / "reperence" / "SCPC2026_Final_data.zip",
    PROJECT_DIR / "SCPC2026_Final_data.zip",
)
BASELINE_SUBMISSION_PATH = (
    PROJECT_DIR
    / "reference"
    / "official_notebook_baseline"
    / "submission.csv"
)


def require_workspace_path(path: Path, *, label: str) -> Path:
    resolved = path.expanduser().resolve()
    workspace = PROJECT_DIR.resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(
            f"{label} must be inside the workspace: {workspace}"
        )
    return resolved


def _has_official_data(path: Path) -> bool:
    return all((path / name).is_file() for name in OFFICIAL_DATA_FILES)


def find_official_archive() -> Path | None:
    return next(
        (path for path in OFFICIAL_ARCHIVE_CANDIDATES if path.is_file()),
        None,
    )


def find_data_dir() -> Path:
    env = os.environ.get("SCPC_DATA_DIR")
    archive = find_official_archive()
    cache_data = PROJECT_DIR / ".cache" / "scpc_data" / "data"
    if env:
        explicit = require_workspace_path(
            Path(env), label="SCPC_DATA_DIR"
        )
        if explicit == cache_data.resolve() and archive is not None:
            return _extract_official_archive(archive)
        if _has_official_data(explicit):
            return explicit
    for candidate in (PROJECT_DIR / "data", PROJECT_DIR):
        if _has_official_data(candidate):
            return candidate
    if archive is not None:
        return _extract_official_archive(archive)
    raise FileNotFoundError(
        "official SCPC data is missing inside the workspace; place the three "
        "JSON files under ./data or place SCPC2026_Final_data.zip at the "
        "workspace root"
    )


def find_baseline_submission() -> Path:
    env = os.environ.get("SCPC_BASELINE_SUBMISSION")
    path = (
        require_workspace_path(Path(env), label="SCPC_BASELINE_SUBMISSION")
        if env
        else BASELINE_SUBMISSION_PATH
    )
    if not path.is_file():
        raise FileNotFoundError(
            "baseline submission is missing inside the workspace: "
            f"{BASELINE_SUBMISSION_PATH.relative_to(PROJECT_DIR)}"
        )
    return path


def _extract_official_archive(archive: Path) -> Path:
    cache_root = PROJECT_DIR / ".cache" / "scpc_data"
    data_dir = cache_root / "data"
    marker = cache_root / ".archive.sha256"
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    if (
        _has_official_data(data_dir)
        and marker.is_file()
        and marker.read_text(encoding="ascii").strip() == archive_hash
    ):
        return data_dir
    if cache_root.exists():
        shutil.rmtree(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (cache_root / member.filename).resolve()
            if cache_root.resolve() not in target.parents and target != cache_root.resolve():
                raise ValueError(f"unsafe ZIP member: {member.filename}")
        handle.extractall(cache_root)
    if not _has_official_data(data_dir):
        raise FileNotFoundError(
            "official archive does not contain the complete data bundle"
        )
    marker.write_text(archive_hash + "\n", encoding="ascii")
    return data_dir


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
