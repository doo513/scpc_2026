from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent.parent


def find_data_dir() -> Path:
    env = os.environ.get("SCPC_DATA_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            PROJECT_DIR / "data",
            PROJECT_DIR,
            PROJECT_DIR.parent / "data" / "SCPC2026_Final_data" / "data",
            PROJECT_DIR.parent / "data" / "data",
            PROJECT_DIR.parent / "data",
            Path.cwd() / "data",
            Path.cwd(),
            Path.cwd().parent / "data",
            Path.cwd().parent,
        ]
    )
    for candidate in candidates:
        if (candidate / "screening_tasks.jsonl").is_file():
            return candidate
    zip_candidates = [
        PROJECT_DIR / "SCPC2026_Final_data.zip",
        Path.cwd() / "SCPC2026_Final_data.zip",
        PROJECT_DIR.parent / "data" / "SCPC2026_Final_data.zip",
    ]
    for archive in zip_candidates:
        if archive.is_file():
            return _extract_official_archive(archive)
    raise FileNotFoundError("screening_tasks.jsonl not found; set SCPC_DATA_DIR")


def _extract_official_archive(archive: Path) -> Path:
    cache_root = PROJECT_DIR / ".cache" / "scpc_data"
    data_dir = cache_root / "data"
    if (data_dir / "screening_tasks.jsonl").is_file():
        return data_dir
    cache_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for member in handle.infolist():
            target = (cache_root / member.filename).resolve()
            if cache_root.resolve() not in target.parents and target != cache_root.resolve():
                raise ValueError(f"unsafe ZIP member: {member.filename}")
        handle.extractall(cache_root)
    if not (data_dir / "screening_tasks.jsonl").is_file():
        raise FileNotFoundError("official archive does not contain data/screening_tasks.jsonl")
    return data_dir


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
