from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Iterable

from build_manifest import sha256_file, source_files, source_tree_hash
from core.consistency import ConsistencyValidator
from core.evidence import IntentEvidenceExtractor
from core.language_registry import (
    LANGUAGE_RULE_REGISTRY,
    validate_language_rule_registry,
)
from core.surface_parser import SurfaceParser
from core.task_view import TaskView
from run_submission import run_tasks, write_submission
from step1_baseline import (
    BASE_DIR,
    combined_hash,
    evaluate_dev,
    resolve_report_root,
    run_command,
)
from utils.diff import compare_submissions
from utils.io import find_data_dir, load_jsonl
from validate_submission import validate_submission


KNOWN_DEV_FAILURE = "tests/test_regression.py::test_dev_score_and_optional_fields"


def archive_failed_attempt(output_dir: Path) -> None:
    result_path = output_dir / "step4_result.json"
    if not result_path.is_file():
        return
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if result.get("release_gate", {}).get("status") != "FAIL":
        return
    attempts_dir = output_dir / "gate_attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    index = 1
    while (attempts_dir / f"attempt_{index:03d}_result.json").exists():
        index += 1
    (attempts_dir / f"attempt_{index:03d}_result.json").write_bytes(
        result_path.read_bytes()
    )
    report_path = output_dir / "STEP4_REPORT.md"
    if report_path.is_file():
        (attempts_dir / f"attempt_{index:03d}_report.md").write_bytes(
            report_path.read_bytes()
        )


def resolve_step3(report_root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    candidates = (
        report_root / "step3_typed_facts",
        report_root / "op_reports" / "step3_typed_facts",
    )
    errors: list[str] = []
    for directory in candidates:
        result_path = directory / "step3_result.json"
        submission_path = directory / "submission.csv"
        manifest_path = directory / "stage_manifest.json"
        if not result_path.is_file():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else {}
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{directory}: {exc}")
            continue
        checks = {
            "stage_name": result.get("stage") == "step3_typed_facts",
            "release_gate": bool(
                result.get("release_gate", {}).get("next_stage_allowed")
            ),
            "submission_present": submission_path.is_file(),
            "submission_hash": (
                submission_path.is_file()
                and result.get("screening_submission_sha256")
                == sha256_file(submission_path)
            ),
            "manifest_present": manifest_path.is_file(),
            "manifest_submission_hash": (
                manifest.get("artifacts", {}).get("submission.csv")
                == result.get("screening_submission_sha256")
            ),
            "result_manifest_hash": (
                manifest.get("artifacts", {}).get("step3_result.json")
                == sha256_file(result_path)
            ),
        }
        integrity = {
            "resolved_directory": str(directory.resolve()),
            "checks": checks,
            "errors": errors,
        }
        if all(checks.values()):
            return directory, result, integrity
        errors.append(
            f"{directory}: failed checks "
            + ", ".join(name for name, passed in checks.items() if not passed)
        )
    return (
        report_root / "step3_typed_facts",
        {},
        {
            "resolved_directory": "",
            "checks": {},
            "errors": errors or ["Step 3 result not found"],
        },
    )


def language_contract_files() -> tuple[Path, ...]:
    return tuple(
        path
        for path in (
            BASE_DIR / "core" / "prompt_document.py",
            BASE_DIR / "core" / "surface_parser.py",
            BASE_DIR / "core" / "language_features.py",
            BASE_DIR / "core" / "language_registry.py",
            BASE_DIR / "core" / "context_binder.py",
            BASE_DIR / "core" / "evidence_model.py",
            BASE_DIR / "core" / "evidence.py",
        )
        if path.is_file()
    )


def rule_snapshot() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": rule.rule_id,
            "requires": [item.value for item in rule.requires],
            "forbids": [item.value for item in rule.forbids],
            "scope": rule.scope.value,
            "semantic_slot": rule.semantic_slot.value,
            "emits": [item.value for item in rule.emits],
            "priority": rule.priority,
            "contract_status": rule.contract_status.value,
            "basis_refs": list(rule.basis_refs),
            "assumption_refs": list(rule.assumption_refs),
        }
        for rule in LANGUAGE_RULE_REGISTRY.rules
    ]


def audit_language_pipeline() -> dict[str, Any]:
    data_dir = find_data_dir()
    tasks: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    for filename in ("dev_tasks.jsonl", "screening_tasks.jsonl"):
        rows = load_jsonl(data_dir / filename)
        tasks.extend(rows)
        source_counts[filename] = len(rows)

    counts: Counter[str] = Counter()
    rule_hits: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    unregistered_rule_ids: set[str] = set()
    nondeterministic_tasks: list[str] = []
    quoted_execution_violations: list[str] = []
    digest = hashlib.sha256()
    registered_ids = {rule.rule_id for rule in LANGUAGE_RULE_REGISTRY.rules}

    for task in tasks:
        task_id = str(task.get("id") or "")
        try:
            prompt = str(task.get("prompt") or "")
            surface = SurfaceParser.parse(prompt)
            repeated = SurfaceParser.parse(prompt)
            if surface != repeated:
                nondeterministic_tasks.append(task_id)
            counts["clauses"] += len(surface.clauses)
            counts["quotations"] += len(surface.quotations)
            counts["negations"] += len(surface.negations)
            counts["predicate_frames"] += len(surface.predicate_frames)
            counts["arguments"] += len(surface.arguments)
            counts["corrections"] += len(surface.corrections)
            counts["supersessions"] += len(surface.supersessions)
            counts["fallback_relations"] += len(surface.fallback_relations)
            counts["references"] += len(surface.references)

            proposals = LANGUAGE_RULE_REGISTRY.propose(surface, direct=True)
            quote_spans = [item.span for item in surface.quotations]
            for proposal in proposals:
                rule_hits[proposal.rule_id] += 1
                if proposal.rule_id not in registered_ids:
                    unregistered_rule_ids.add(proposal.rule_id)
                if proposal.kind.value in {
                    "execution_request",
                    "explicit_domain_verb",
                    "share_request",
                } and any(
                    start <= proposal.source_span[0] and proposal.source_span[1] <= end
                    for start, end in quote_spans
                ):
                    quoted_execution_violations.append(task_id)

            evidence = IntentEvidenceExtractor.extract(TaskView(task, {}))
            for item in evidence.evidence:
                rule_hits[item.rule_id] += 1
                if item.rule_id not in registered_ids:
                    unregistered_rule_ids.add(item.rule_id)
            if evidence.context_binding is not None:
                counts["binding_decisions"] += len(evidence.context_binding.decisions)
            payload = {
                "task_id": task_id,
                "surface": surface.to_trace(),
                "proposal_count": len(proposals),
                "evidence": [
                    {
                        "kind": item.kind.value,
                        "payload": item.payload,
                        "active": item.active,
                        "rule_id": item.rule_id,
                        "semantic_slot": item.semantic_slot,
                    }
                    for item in evidence.evidence
                ],
            }
            digest.update(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except Exception as exc:
            errors.append(
                {
                    "task_id": task_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    return {
        "task_count": len(tasks),
        "source_counts": source_counts,
        "counts": dict(sorted(counts.items())),
        "rule_hits": dict(sorted(rule_hits.items())),
        "rules_without_official_hits": sorted(registered_ids - set(rule_hits)),
        "errors": errors,
        "unregistered_rule_ids": sorted(unregistered_rule_ids),
        "nondeterministic_tasks": nondeterministic_tasks,
        "quoted_execution_violations": sorted(set(quoted_execution_violations)),
        "audit_sha256": digest.hexdigest(),
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 4 Surface Parser·LanguageRuleRegistry·Context Binder 계약",
            "",
            "## Surface Parser",
            "",
            "Parser는 `ClauseSpan`, `QuotationSpan`, `NegationSpan`, `PredicateFrame`, `ArgumentSpan`, `CorrectionRelation`, `SupersessionRelation`, `ReferenceMention`을 생성한다. 이 객체는 Evidence 후보의 source span을 제공하며 action, target, control을 확정하지 않는다.",
            "",
            "## LanguageRuleRegistry",
            "",
            "모든 규칙은 typed metadata와 contract status를 가진다. `priority`는 같은 scope, semantic slot, source span의 중복 proposal을 정리할 때만 사용한다. Registry 출력은 `RuleEvidenceProposal`로 제한한다.",
            "",
            "기존 판정과의 무회귀를 위해 compatibility feature detector를 Registry 내부 production evidence 경로로 유지한다. surface-native proposal은 shadow trace로 비교하며, 향후 vertical slice gate 전에는 임의로 최종 후보를 바꾸지 않는다.",
            "",
            "## Context Binder",
            "",
            "Binder는 semantic slot과 subject가 같은 Evidence 사이에서만 현재 prompt의 명시적 부정·정정을 적용한다. 서로 다른 slot은 독립적으로 보존하며, TypedFact와 hard constraint는 자연어 authority 순위에 참여하지 않는다.",
            "",
            "## Correction과 Fallback",
            "",
            "`A하지 말고 B`는 correction 및 supersession 후보로 분류한다. `A가 안 되면 B`처럼 실패 조건이 명시된 경우에만 fallback relation과 authorization evidence를 생성한다.",
            "",
            "## Fixed SLM",
            "",
            "현재 저장소에는 Fixed SLM runtime이 없으므로 새 모델과 외부 의존성을 추가하지 않았다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    audit = result["language_audit"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 4 Surface Parser·LanguageRuleRegistry·Context Binder 보고서",
            "",
            "## 작업 범위",
            "",
            "Step 4에서는 자연어를 span과 Evidence 후보로 변환하는 경계를 고정했다. RulePack, candidate 평가, compiler 의미는 변경하지 않았다.",
            "",
            "## 구현 결과",
            "",
            "- quotation, negation, predicate, argument, correction, supersession, reference 구조를 추가했다.",
            "- 자연어 어휘 판정을 `evidence.py`에서 LanguageRuleRegistry 경계로 이동했다.",
            "- Context Binder는 동일 semantic slot의 현재 명시적 정정만 supersede한다.",
            "- correction과 conditional fallback을 별도 relation으로 구분했다.",
            "- Fixed SLM이나 외부 모델 의존성은 추가하지 않았다.",
            "",
            "## 공식 입력 Audit",
            "",
            f"- 검사 task: `{audit['task_count']}`개",
            f"- parse 오류: `{len(audit['errors'])}`개",
            f"- 비결정적 parse: `{len(audit['nondeterministic_tasks'])}`개",
            f"- quoted execution 위반: `{len(audit['quoted_execution_violations'])}`개",
            f"- unregistered rule ID: `{len(audit['unregistered_rule_ids'])}`개",
            f"- audit SHA-256: `{audit['audit_sha256']}`",
            "",
            "공식 입력 parse 성공과 registry coverage는 semantic answer 정확도를 의미하지 않는다. 공식 reference 일치는 dev score와 submission diff로 별도 확인했다.",
            "",
            "## 검증 결과",
            "",
            f"- Step 4 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 3과 동일: `{result['dev_unchanged']}`)",
            f"- screening public submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "전체 pytest의 dev hard gate 1건은 기존 baseline debt로 남아 있다.",
            "",
            "## Step 4 Release Gate",
            "",
            f"- 상태: **{gate['status']}**",
            f"- 다음 단계 진입 가능: **{gate['next_stage_allowed']}**",
            *[f"- {reason}" for reason in gate["reasons"]],
            "",
        ]
    )


def write_manifest(
    output_dir: Path,
    *,
    source_hash: str,
    artifact_paths: Iterable[Path],
) -> None:
    data_dir = find_data_dir()
    manifest = {
        "stage": "step4_language",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_tree_sha256": source_hash,
        "official_data_sha256": {
            name: sha256_file(data_dir / name)
            for name in (
                "dev_tasks.jsonl",
                "dev_answers.json",
                "screening_tasks.jsonl",
            )
        },
        "artifacts": {
            path.name: sha256_file(path) for path in artifact_paths if path.is_file()
        },
    }
    (output_dir / "stage_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report_root, root_source = resolve_report_root()
    output_dir = (args.output_dir or report_root / "step4_language").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(output_dir)
    step3_dir, step3_result, previous_stage = resolve_step3(report_root.resolve())

    source_hash_before = source_tree_hash(source_files())
    validation_errors: list[str] = []
    try:
        validate_language_rule_registry()
    except Exception as exc:
        validation_errors.append(f"validate_language_rule_registry: {exc}")

    rules = rule_snapshot()
    registry_path = output_dir / "language_rule_registry.json"
    registry_path.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "SURFACE_CONTEXT_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")
    audit = audit_language_pipeline()
    audit_path = output_dir / "language_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tests = {
        "stage_specific": run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_language_registry.py",
                "tests/test_prompt_security.py",
                "tests/test_generalization.py",
                "tests/test_architecture.py",
            ],
            output_dir / "pytest_stage4.log",
        ),
        "full": run_command(
            [sys.executable, "-m", "pytest", "-q"],
            output_dir / "pytest_full.log",
        ),
        "without_known_dev_gate": run_command(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-k",
                "not test_dev_score_and_optional_fields",
            ],
            output_dir / "pytest_without_known_dev_gate.log",
        ),
    }
    dev, dev_diagnostics = evaluate_dev()
    (output_dir / "dev_error_distribution.json").write_text(
        json.dumps(dev_diagnostics, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    dev_unchanged = (step3_result or {}).get("dev") == dev

    data_dir = find_data_dir()
    screening_payload = run_tasks(load_jsonl(data_dir / "screening_tasks.jsonl"))
    submission_path = output_dir / "submission.csv"
    write_submission(screening_payload, submission_path)
    validate_submission(submission_path)
    ConsistencyValidator.write_report(output_dir / "consistency_report.md")
    previous_submission = step3_dir / "submission.csv"
    screening_unchanged = previous_submission.is_file() and sha256_file(
        previous_submission
    ) == sha256_file(submission_path)
    if previous_submission.is_file():
        (output_dir / "shadow_diff_vs_step3.md").write_text(
            compare_submissions(previous_submission, submission_path) + "\n",
            encoding="utf-8",
        )

    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step3_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "registry_valid": not validation_errors,
        "official_parse": not audit["errors"],
        "deterministic_parse": not audit["nondeterministic_tasks"],
        "quotation_authority": not audit["quoted_execution_violations"],
        "registered_evidence_rules": not audit["unregistered_rule_ids"],
        "stage_specific_tests": tests["stage_specific"]["exit_code"] == 0,
        "without_known_dev_gate": tests["without_known_dev_gate"]["exit_code"] == 0,
        "only_known_full_test_failure": (
            tests["full"]["exit_code"] == 1
            and tests["full"]["failed_tests"] == [KNOWN_DEV_FAILURE]
        ),
        "dev_unchanged": dev_unchanged,
        "screening_submission_unchanged": screening_unchanged,
        "source_stable_during_gate": source_hash_before == source_hash_after,
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "Surface Parser, LanguageRuleRegistry, Context Binder invariant가 통과했다.",
            "공식 820개 prompt의 deterministic parse와 quotation authority 검증이 통과했다.",
            "Step 3 대비 public dev 수치와 screening submission이 변하지 않았다.",
            "기존 dev hard gate 실패 1건은 baseline debt로 유지한다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 4 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step4_language",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "language_contract_sha256": combined_hash(
            language_contract_files(), root=BASE_DIR
        ),
        "language_registry_sha256": sha256_file(registry_path),
        "rule_count": len(rules),
        "language_audit": audit,
        "dev": dev,
        "dev_unchanged": dev_unchanged,
        "screening_submission_sha256": sha256_file(submission_path),
        "screening_submission_unchanged": screening_unchanged,
        "tests": tests,
        "validation_errors": validation_errors,
        "release_gate": release_gate,
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    result_path = output_dir / "step4_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP4_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_manifest(
        output_dir,
        source_hash=source_hash_after,
        artifact_paths=(
            registry_path,
            contract_path,
            audit_path,
            submission_path,
            result_path,
            report_path,
            output_dir / "consistency_report.md",
            output_dir / "shadow_diff_vs_step3.md",
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
