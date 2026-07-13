from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from build_manifest import (
    promote_validated_candidate_manifest,
    publish_candidate_manifest,
    source_files,
    source_tree_hash,
)
from core.consistency import ConsistencyValidator
from core.decision import DecisionEngine, FinalDecision
from core.property_policy import validate_disclosure_policy_matrix
from core.session_state import MemoryStore
from core.state import StateAssembler
from core.task_view import TaskView
from harness import FinalHarness
from local_score import evaluate_dev_payload
from official_scorer import evaluate_current_scorer_parity
from run_submission import run_tasks
from utils.io import find_data_dir, load_jsonl
from validate_artifacts import validate_current_artifacts


BASE_DIR = Path(__file__).resolve().parent
KNOWN_DEV_GATE = "tests/test_regression.py::test_dev_score_diagnostics"
PROHIBITED_SPECIFICITY_MARKERS = (
    "final_dev_",
    "final_screening_",
    "answer_by_task_id",
)
EVALUATION_ASSET_MARKERS = ("dev_answers", "screening_results")
IDENTITY_KEYS = frozenset({"task_id", "session_id"})
REQUIRED_RELEASE_CHECK_IDS = frozenset(
    {
        "tests_without_dev_gate",
        "official_scorer_parity",
        "task_specific_runtime_rules_absent",
        "validation_before_commit",
        "projection_pipeline_wired",
        "authoritative_decision_engine_wired",
        "fixed_slm_status_valid",
        "unknown_property_fail_closed",
        "property_inventories_merged",
        "property_policy_matrix_valid",
        "classified_property_policy_enforced",
        "unknown_object_direct_attr_fail_closed",
        "scope_trace_tampering_rejected",
        "mutable_authority_rejected",
    }
)


def _run_pytest(arguments: list[str], log_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *arguments],
        cwd=BASE_DIR,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(completed.stdout, encoding="utf-8")
    failed = sorted(set(re.findall(r"FAILED ([^\s]+)", completed.stdout)))
    return {"exit_code": completed.returncode, "failed_tests": failed}


def _dev() -> tuple[dict[str, Any], dict[str, Any]]:
    data_dir = find_data_dir()
    references = json.loads(
        (data_dir / "dev_answers.json").read_text(encoding="utf-8")
    )
    return evaluate_dev_payload(
        run_tasks(load_jsonl(data_dir / "dev_tasks.jsonl")),
        references,
    )


def _dev_gate(dev: dict[str, Any]) -> dict[str, Any]:
    spec = json.loads(
        (BASE_DIR / "tests" / "specs" / "generalization_v1.json").read_text(
            encoding="utf-8"
        )
    )["dev_hard_gate"]
    checks = {
        "overall": dev["overall"] >= spec["minimum_overall"],
        **{
            f"axis.{axis}": dev["axes"][axis] >= floor
            for axis, floor in spec["minimum_axes"].items()
        },
        "non_exact": dev["non_exact_count"] <= spec["maximum_non_exact_tasks"],
    }
    return {
        "passed": all(checks.values()),
        "release_blocking": bool(spec.get("release_blocking", False)),
        "checks": checks,
        "contract": spec,
    }


def _synthetic_disclosure_task(
    *,
    attrs: dict[str, Any],
    object_type: str = "file",
    task_id: str = "release_semantic_check",
    extra_records: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    ref_code = str(attrs.get("ref_code") or "WM-RELEASE-CHECK")
    return {
        "schema": "scpc.final.task.v1",
        "id": task_id,
        "session_id": "release_semantic_check_session",
        "turn_index": 1,
        "prompt": "이 자료를 channel_a에 보내줘.",
        "visible_history": [],
        "personal_memory": [],
        "available_actions": [
            "read", "verify", "redact", "summarize", "dispatch",
            "guard", "clarify", "update", "schedule", "toggle", "pay",
        ],
        "device_state": {
            "objects": [
                {
                    "id": "obj_release_check",
                    "type": object_type,
                    "attrs": {**attrs, "ref_code": ref_code},
                }
            ],
            "records": [
                {
                    "id": "rec_release_markers",
                    "type": "focal_marker_refs",
                    "value": {"marker_to_ref": {"marker_alpha": ref_code}},
                },
                {
                    "id": "rec_release_trace",
                    "type": "focal_resolution_trace",
                    "value": {
                        "latest_phase": "draft",
                        "phase_to_marker": {"draft": "marker_alpha"},
                    },
                },
                {
                    "id": "rec_release_target",
                    "type": "resolved_target",
                    "value": "channel_a",
                },
                *copy.deepcopy(extra_records),
            ],
        },
    }


def _immutable_decision_authority(task: dict[str, Any]) -> FinalDecision:
    view = TaskView(task)
    state = StateAssembler.assemble(view, MemoryStore(), {})
    _matrix, decision = DecisionEngine.decide(state)
    return decision


def _unknown_property_result(
    attrs: dict[str, Any],
    *,
    field_name: str,
    object_type: str = "file",
) -> dict[str, Any]:
    result = FinalHarness().answer_task(
        _synthetic_disclosure_task(attrs=attrs, object_type=object_type),
        {},
        commit=False,
    )
    constraints = result["_trace"]["final_decision"]["active_constraints"]
    properties = result["_trace"]["evidence"]["properties"]
    field = next(
        (item for item in properties if item.get("name") == field_name),
        {},
    )
    return {
        "control_hold": result["control"] == "hold",
        "scope_none": result["content_scope"]["mode"] == "none",
        "field_excluded": field_name
        in result["content_scope"]["excluded_fields"],
        "hard_constraint": any(
            item.get("kind") == "unknown_property_disclosure"
            and item.get("severity") == "hard"
            for item in constraints
        ),
        "classification": field.get("classification"),
        "source": field.get("source"),
    }


def _semantic_safety_checks() -> dict[str, Any]:
    matrix_valid = True
    matrix_error = ""
    try:
        validate_disclosure_policy_matrix()
    except ValueError as exc:
        matrix_valid = False
        matrix_error = str(exc)

    declared_account = _unknown_property_result(
        {"contains": ["account_password"]},
        field_name="account_password",
    )
    attrs_only_account = _unknown_property_result(
        {"account_password": "secret-value"},
        field_name="account_password",
    )
    declared_novel = _unknown_property_result(
        {"contains": ["novel_field_123"]},
        field_name="novel_field_123",
    )
    attrs_only_novel = _unknown_property_result(
        {"novel_field_123": "secret-value"},
        field_name="novel_field_123",
    )
    unknown_type = _unknown_property_result(
        {"contains": ["summary"]},
        field_name="summary",
        object_type="novel_object_type",
    )
    merged_inventory = _unknown_property_result(
        {"contains": [], "fields": ["novel_field_123"]},
        field_name="novel_field_123",
    )
    unknown_direct_attr = _unknown_property_result(
        {"summary": "x"},
        field_name="summary",
        object_type="novel_object_type",
    )

    secret_task = _synthetic_disclosure_task(
        attrs={
            "body": "hello",
            "recipient": "channel_a",
            "password": "secret-value",
        },
        object_type="message",
        extra_records=(
            {
                "id": "rec_release_session_policy",
                "type": "session_share_policy",
                "value": "normal",
            },
        ),
    )
    secret_result = FinalHarness().answer_task(
        copy.deepcopy(secret_task), {}, commit=False
    )
    secret_constraints = secret_result["_trace"]["final_decision"][
        "active_constraints"
    ]
    secret_property = next(
        item
        for item in secret_result["_trace"]["evidence"]["properties"]
        if item["name"] == "password"
    )
    classified_secret = {
        "classification_secret": secret_property["classification"] == "secret",
        "control_amend": secret_result["control"] == "amend",
        "scope_redacted": secret_result["content_scope"]["mode"] == "redacted",
        "field_excluded": "password"
        in secret_result["content_scope"]["excluded_fields"],
        "redaction_constraint": any(
            item.get("kind") == "classified_property_disclosure"
            and item.get("severity") == "amend"
            and item.get("effect") == "add_redaction"
            for item in secret_constraints
        ),
    }

    task = _synthetic_disclosure_task(attrs={"contains": ["summary"]})
    result = FinalHarness().answer_task(copy.deepcopy(task), {}, commit=False)
    trace = copy.deepcopy(result["_trace"])
    authority = _immutable_decision_authority(task)
    public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    public["content_scope"]["mode"] = "raw"
    trace["final_decision"]["disclosure"]["mode"] = "raw"
    tampering_rejected = False
    tampering_error = ""
    try:
        ConsistencyValidator.validate_strict(
            public,
            TaskView(task),
            trace,
            authority,
        )
    except ValueError as exc:
        tampering_rejected = True
        tampering_error = str(exc)

    mutable_trace = copy.deepcopy(result["_trace"])
    mutable_public = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if not key.startswith("_")
    }
    mutable_public["content_scope"]["mode"] = "raw"
    mutable_trace["final_decision"]["disclosure"]["mode"] = "raw"
    mutable_trace["final_decision"]["effective_blueprint"][
        "scope_mode"
    ] = "raw"
    mutable_authority_rejected = False
    mutable_authority_error = ""
    try:
        ConsistencyValidator.validate_strict(
            mutable_public,
            TaskView(task),
            mutable_trace,
            mutable_trace["final_decision"],
        )
    except ValueError as exc:
        mutable_authority_rejected = True
        mutable_authority_error = str(exc)

    return {
        "checks": {
            "unknown_property_fail_closed": all(
                item[key]
                for item in (
                    declared_account,
                    attrs_only_account,
                    declared_novel,
                    attrs_only_novel,
                    unknown_type,
                )
                for key in (
                    "control_hold",
                    "scope_none",
                    "field_excluded",
                    "hard_constraint",
                )
            ),
            "property_inventories_merged": all(
                merged_inventory[key]
                for key in (
                    "control_hold",
                    "scope_none",
                    "field_excluded",
                    "hard_constraint",
                )
            )
            and merged_inventory["source"] == "fields",
            "property_policy_matrix_valid": matrix_valid,
            "classified_property_policy_enforced": all(
                classified_secret.values()
            ),
            "unknown_object_direct_attr_fail_closed": all(
                unknown_direct_attr[key]
                for key in (
                    "control_hold",
                    "scope_none",
                    "field_excluded",
                    "hard_constraint",
                )
            )
            and unknown_direct_attr["classification"] == "unknown"
            and unknown_direct_attr["source"] == "direct_attr",
            "scope_trace_tampering_rejected": tampering_rejected,
            "mutable_authority_rejected": mutable_authority_rejected,
        },
        "evidence": {
            "declared_unknown": declared_account,
            "attrs_only_unknown": attrs_only_account,
            "declared_novel_unknown": declared_novel,
            "attrs_only_novel_unknown": attrs_only_novel,
            "unknown_type": unknown_type,
            "merged_inventory": merged_inventory,
            "property_policy_matrix_error": matrix_error,
            "classified_secret": classified_secret,
            "unknown_direct_attr": unknown_direct_attr,
            "scope_trace_tampering_error": tampering_error,
            "mutable_authority_error": mutable_authority_error,
        },
    }


def _release_check_contract(checks: dict[str, Any]) -> dict[str, Any]:
    actual = set(checks)
    missing = sorted(REQUIRED_RELEASE_CHECK_IDS - actual)
    unexpected = sorted(actual - REQUIRED_RELEASE_CHECK_IDS)
    non_boolean = sorted(
        key for key, value in checks.items() if type(value) is not bool
    )
    passed = (
        not missing
        and not unexpected
        and not non_boolean
        and all(checks[key] is True for key in REQUIRED_RELEASE_CHECK_IDS)
    )
    return {
        "passed": passed,
        "required_ids": sorted(REQUIRED_RELEASE_CHECK_IDS),
        "missing_ids": missing,
        "unexpected_ids": unexpected,
        "non_boolean_ids": non_boolean,
    }


def _promote_release_candidate(
    *,
    released: bool,
    dev: dict[str, Any],
    reproduce: bool,
    reproduce_reports: bool,
) -> dict[str, Any] | None:
    if released is not True:
        return None
    staged_manifest = (
        BASE_DIR / "manifest" / ".candidate_manifest.release.pending.json"
    )
    try:
        publish_candidate_manifest(
            dev,
            BASE_DIR / "submission.csv",
            output_path=staged_manifest,
        )
        validation = validate_current_artifacts(
            manifest_path=staged_manifest,
            reproduce=reproduce,
            reproduce_reports=reproduce_reports,
        )
        promote_validated_candidate_manifest(staged_manifest, validation)
        return validation
    finally:
        staged_manifest.unlink(missing_ok=True)


def _specificity_hits_for_source(
    source: str,
    *,
    path: str,
    official_task_ids: frozenset[str] = frozenset(),
    official_session_ids: frozenset[str] = frozenset(),
    official_prompts: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    tree = ast.parse(source, filename=path)
    hits: list[dict[str, Any]] = []

    def identifier_key(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Subscript) and isinstance(
            node.slice, ast.Constant
        ):
            return str(node.slice.value)
        return ""

    def references_identity(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in IDENTITY_KEYS:
                return True
            if isinstance(child, ast.Attribute) and child.attr in IDENTITY_KEYS:
                return True
            if isinstance(child, ast.Subscript) and isinstance(
                child.slice, ast.Constant
            ) and child.slice.value in IDENTITY_KEYS:
                return True
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "get"
                and child.args
                and isinstance(child.args[0], ast.Constant)
                and child.args[0].value in IDENTITY_KEYS
            ):
                return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for marker in PROHIBITED_SPECIFICITY_MARKERS:
                if marker in node.value:
                    hits.append(
                        {
                            "path": path,
                            "line": node.lineno,
                            "marker": marker,
                        }
                    )
            korean_count = sum("가" <= char <= "힣" for char in node.value)
            sentence_count = sum(
                node.value.count(mark) for mark in (".", "!", "?")
            )
            if korean_count >= 80 and sentence_count >= 2:
                hits.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "marker": "full_prompt_literal",
                    }
                )
            if node.value in official_task_ids:
                hits.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "marker": "official_task_id_literal",
                    }
                )
            if node.value in official_session_ids:
                hits.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "marker": "official_session_id_literal",
                    }
                )
            if len(node.value) >= 20 and node.value in official_prompts:
                hits.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "marker": "official_prompt_literal",
                    }
                )
        if isinstance(node, ast.Compare):
            compared = [node.left, *node.comparators]
            keys = {identifier_key(item) for item in compared}
            constants = {
                item.value
                for item in compared
                if isinstance(item, ast.Constant)
                and isinstance(item.value, str)
            }
            if keys & {"task_id", "session_id", "id"} and any(
                value.startswith(("final_dev_", "final_screening_"))
                for value in constants
            ):
                hits.append(
                    {
                        "path": path,
                        "line": node.lineno,
                        "marker": "task_or_session_identifier_branch",
                    }
                )
        if isinstance(node, (ast.If, ast.IfExp)) and references_identity(
            node.test
        ):
            hits.append(
                {
                    "path": path,
                    "line": node.lineno,
                    "marker": "identity_dependent_branch",
                }
            )
        if isinstance(node, ast.Match) and references_identity(node.subject):
            hits.append(
                {
                    "path": path,
                    "line": node.lineno,
                    "marker": "identity_dependent_branch",
                }
            )
    return hits


def _specificity_scan_paths() -> tuple[Path, ...]:
    """Return every workspace Python implementation file outside tests.

    Release tooling, scorers, submission orchestration, and every utils module
    remain visible to the audit even when they cannot influence FinalHarness.
    """
    paths = set(BASE_DIR.glob("*.py"))
    for directory in ("core", "rules", "utils"):
        paths.update((BASE_DIR / directory).rglob("*.py"))
    return tuple(sorted(paths, key=lambda item: item.as_posix()))


def _evaluation_asset_references_for_source(
    source: str,
    *,
    path: str,
) -> list[dict[str, Any]]:
    tree = ast.parse(source, filename=path)
    return [
        {"path": path, "line": node.lineno, "marker": marker}
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for marker in EVALUATION_ASSET_MARKERS
        if marker in node.value
    ]


def _authoritative_runtime_specificity_paths() -> frozenset[Path]:
    paths = {
        BASE_DIR / "harness.py",
        BASE_DIR / "run_submission.py",
        BASE_DIR / "utils" / "io.py",
        BASE_DIR / "utils" / "schema_check.py",
    }
    paths.update((BASE_DIR / "core").rglob("*.py"))
    paths.update((BASE_DIR / "rules").rglob("*.py"))
    return frozenset(path.resolve() for path in paths)


def _specificity_scan() -> dict[str, Any]:
    paths = _specificity_scan_paths()
    authoritative_paths = _authoritative_runtime_specificity_paths()
    data_dir = find_data_dir()
    official_tasks = load_jsonl(data_dir / "dev_tasks.jsonl") + load_jsonl(
        data_dir / "screening_tasks.jsonl"
    )
    official_task_ids = frozenset(
        str(task.get("id") or "") for task in official_tasks
    ) - {""}
    official_session_ids = frozenset(
        str(task.get("session_id") or "") for task in official_tasks
    ) - {""}
    official_prompts = frozenset(
        str(task.get("prompt") or "") for task in official_tasks
    ) - {""}
    runtime_hits: list[dict[str, Any]] = []
    tooling_hits: list[dict[str, Any]] = []
    evaluation_asset_references: list[dict[str, Any]] = []
    for path in paths:
        relative = path.relative_to(BASE_DIR).as_posix()
        source = path.read_text(encoding="utf-8")
        path_hits = _specificity_hits_for_source(
            source,
            path=relative,
            official_task_ids=official_task_ids,
            official_session_ids=official_session_ids,
            official_prompts=official_prompts,
        )
        if path.resolve() in authoritative_paths:
            runtime_hits.extend(path_hits)
        else:
            tooling_hits.extend(path_hits)
        evaluation_asset_references.extend(
            _evaluation_asset_references_for_source(source, path=relative)
        )
    return {
        "passed": not runtime_hits,
        "prohibited_markers": sorted(
            {str(hit["marker"]) for hit in runtime_hits}
        ),
        "hits": runtime_hits,
        "tooling_diagnostics": tooling_hits,
        "evaluation_asset_references": evaluation_asset_references,
        "scanned_file_count": len(paths),
        "authoritative_runtime_file_count": len(authoritative_paths),
        "scanned_roots": ["*.py", "core/**/*.py", "rules/**/*.py", "utils/**/*.py"],
        "scanner": "workspace_python_ast_specificity_and_identity_flow",
    }


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


class _ReachableCallVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.calls: list[tuple[str, int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for statement in node.body:
                self.visit(statement)

    def visit_Lambda(self, _node: ast.Lambda) -> None:
        return

    def visit_If(self, node: ast.If) -> None:
        if isinstance(node.test, ast.Constant):
            branch = node.body if bool(node.test.value) else node.orelse
            for statement in branch:
                self.visit(statement)
            return
        self.visit(node.test)
        for statement in (*node.body, *node.orelse):
            self.visit(statement)

    def visit_Call(self, node: ast.Call) -> None:
        self.calls.append((_call_name(node.func), node.lineno))
        self.generic_visit(node)


def _harness_static_analysis(source: str) -> dict[str, Any]:
    tree = ast.parse(source, filename="harness.py")
    harness_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "FinalHarness"
        ),
        None,
    )
    answer_task = next(
        (
            node
            for node in (harness_class.body if harness_class else [])
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "answer_task"
        ),
        None,
    )
    if answer_task is None:
        return {
            "validation_before_commit": False,
            "projection_pipeline_wired": False,
            "decision_engine_called": False,
            "recognized_calls": [],
        }
    visitor = _ReachableCallVisitor(answer_task)
    visitor.visit(answer_task)
    recognized = {
        name: min(line for call, line in visitor.calls if call == name)
        for name in (
            "DecisionEngine.decide",
            "ProductionProjectionPipeline.compile",
            "ConsistencyValidator.validate_strict",
            "AtomicSessionCommitter.commit",
        )
        if any(call == name for call, _line in visitor.calls)
    }
    validation_line = recognized.get("ConsistencyValidator.validate_strict")
    commit_line = recognized.get("AtomicSessionCommitter.commit")
    projection_line = recognized.get("ProductionProjectionPipeline.compile")
    return {
        "validation_before_commit": bool(
            validation_line and commit_line and validation_line < commit_line
        ),
        "projection_pipeline_wired": bool(
            projection_line
            and validation_line
            and projection_line < validation_line
        ),
        "decision_engine_called": "DecisionEngine.decide" in recognized,
        "recognized_calls": [
            {"call": name, "line": line}
            for name, line in sorted(
                recognized.items(), key=lambda item: item[1]
            )
        ],
        "scanner": "reachable_python_ast_calls",
    }


def _markdown(result: dict[str, Any]) -> str:
    dev = result["dev"]
    lines = [
        "# Current Release Gate Report",
        "",
        f"- status: **{result['status']}**",
        f"- production release allowed: `{result['production_release_allowed']}`",
        f"- source SHA-256: `{result['source_tree_sha256']}`",
        "- artifact validation: `deferred until all required checks pass`",
        f"- official dev: `{dev['overall']:.4f}`",
        f"- exact/non-exact: `{dev['exact_match_count']}/{dev['non_exact_count']}`",
        f"- FixedSLM: `{result['fixed_slm']['decision']}` (production influence `{result['fixed_slm']['production_influence']}`)",
        "",
        "## Checks",
        "",
    ]
    lines.extend(
        f"- {name}: `{'PASS' if passed else 'FAIL'}`"
        for name, passed in result["checks"].items()
    )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            "Promotion is attempted only after the complete required-check contract passes. Official dev metrics are diagnostic and do not participate in the release decision.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument(
        "--reproduction-child",
        action="store_true",
        help="disable recursive report reproduction in an isolated child workspace",
    )
    args = parser.parse_args()
    reports = BASE_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    tests = (
        {
            "full": {"exit_code": -1, "failed_tests": []},
            "without_dev_gate": {"exit_code": -1, "failed_tests": []},
        }
        if args.skip_tests
        else {
            "full": _run_pytest([], reports / "pytest_release_full.log"),
            "without_dev_gate": _run_pytest(
                ["-m", "not dev_score"],
                reports / "pytest_release_without_dev_gate.log",
            ),
        }
    )
    dev, diagnostics = _dev()
    fixed_slm = json.loads(
        (BASE_DIR / "manifest" / "fixed_slm_status.json").read_text(
            encoding="utf-8"
        )
    )
    dev_gate = _dev_gate(dev)
    scorer_parity = evaluate_current_scorer_parity()
    specificity = _specificity_scan()
    semantic_safety = _semantic_safety_checks()
    harness_source = (BASE_DIR / "harness.py").read_text(encoding="utf-8")
    static_analysis = _harness_static_analysis(harness_source)
    checks = {
        "tests_without_dev_gate": tests["without_dev_gate"]["exit_code"] == 0,
        "official_scorer_parity": scorer_parity["identical"],
        "task_specific_runtime_rules_absent": specificity["passed"],
        "validation_before_commit": static_analysis[
            "validation_before_commit"
        ],
        "projection_pipeline_wired": static_analysis[
            "projection_pipeline_wired"
        ],
        "authoritative_decision_engine_wired": static_analysis[
            "decision_engine_called"
        ],
        "fixed_slm_status_valid": fixed_slm["decision"]
        in {"PROMOTE", "KEEP_SHADOW", "REMOVE"}
        and (
            fixed_slm["decision"] == "PROMOTE"
            or fixed_slm["production_influence"] is False
        ),
        **semantic_safety["checks"],
    }
    check_contract = _release_check_contract(checks)
    released = check_contract["passed"]
    result = {
        "schema": "scpc.release-gate.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if released else "RELEASE_BLOCKED",
        "production_release_allowed": released,
        "source_tree_sha256": source_tree_hash(source_files()),
        "dev": dev,
        "dev_diagnostics": diagnostics,
        "dev_hard_gate": dev_gate,
        "official_scorer_parity": scorer_parity,
        "artifact_validation": None,
        "fixed_slm": {
            "decision": fixed_slm["decision"],
            "production_influence": fixed_slm["production_influence"],
        },
        "specificity": specificity,
        "static_analysis": static_analysis,
        "semantic_safety": semantic_safety,
        "tests": tests,
        "checks": checks,
        "check_contract": check_contract,
    }
    json_path = reports / "release_gate_report.json"
    md_path = reports / "release_gate_report.md"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_markdown(result), encoding="utf-8")
    validation = _promote_release_candidate(
        released=released,
        dev=dev,
        reproduce=not args.reproduction_child,
        reproduce_reports=not args.reproduction_child,
    )
    if validation is not None:
        result["artifact_validation"] = validation
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if released else 1


if __name__ == "__main__":
    raise SystemExit(main())
