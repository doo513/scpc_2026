from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from utils.io import (
    BASELINE_SUBMISSION_PATH,
    find_data_dir,
    require_workspace_path,
)


NOTEBOOK_NAME = "SCPC2026_Final_baseline.ipynb"


def find_official_notebook() -> Path:
    data_dir = find_data_dir()
    package_root = data_dir.parent if data_dir.name == "data" else data_dir
    notebook = require_workspace_path(
        package_root / NOTEBOOK_NAME,
        label="official baseline notebook",
    )
    if not notebook.is_file():
        raise FileNotFoundError(
            f"official baseline notebook is missing: {NOTEBOOK_NAME}"
        )
    return notebook


def _execute_official_notebook(notebook: Path) -> dict[str, Any]:
    document = json.loads(notebook.read_text(encoding="utf-8"))
    namespace: dict[str, Any] = {
        "__name__": "__scpc_official_baseline__",
        "__file__": str(notebook),
    }
    package_root = notebook.parent
    previous_cwd = Path.cwd()
    try:
        os.chdir(package_root)
        for index, cell in enumerate(document.get("cells") or []):
            if cell.get("cell_type") != "code":
                continue
            source = "".join(cell.get("source") or [])
            # The dev demonstration is diagnostic and does not contribute to
            # the official screening baseline submission.
            if source.lstrip().startswith("dev_payload = run_harness"):
                continue
            exec(
                compile(source, f"{notebook}:cell-{index}", "exec"),
                namespace,
            )
    finally:
        os.chdir(previous_cwd)
    payload = namespace.get("submission_payload")
    if not isinstance(payload, dict):
        raise RuntimeError("official notebook did not produce submission_payload")
    expected = namespace.get("screening_tasks")
    if not isinstance(expected, list):
        raise RuntimeError("official notebook did not load screening_tasks")
    answers = payload.get("answers")
    if not isinstance(answers, dict) or len(answers) != len(expected):
        raise RuntimeError("official notebook baseline answer count is incomplete")
    return payload


def generate_official_baseline_submission(
    output_path: Path = BASELINE_SUBMISSION_PATH,
) -> Path:
    output = require_workspace_path(
        output_path,
        label="official baseline output",
    )
    notebook = find_official_notebook()
    _execute_official_notebook(notebook)
    generated = notebook.parent / "submission.csv"
    if not generated.is_file():
        raise RuntimeError("official notebook did not write submission.csv")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.name}.",
        delete=False,
    ) as handle:
        handle.write(generated.read_bytes())
        temporary = Path(handle.name)
    os.replace(temporary, output)
    return output


if __name__ == "__main__":
    print(generate_official_baseline_submission())
