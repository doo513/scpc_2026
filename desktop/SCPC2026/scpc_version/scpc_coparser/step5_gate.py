from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from build_manifest import sha256_file, source_files, source_tree_hash
from core.ontology import Domain, Operation
from core.rulepacks import (
    BLUEPRINT_CATALOG,
    CONSTRAINT_CATALOG,
    INFORMATION_SPECS,
    ROLE_SPECS,
    RULEPACK_REGISTRY,
    RULE_PACKS,
    RulePackAvailability,
    RulePackKey,
    RuleVariant,
    validate_rulepack_registry,
)
from stage_gate_common import (
    PreviousStageSpec,
    archive_failed_attempt,
    resolve_previous_stage,
    run_standard_regression,
    standard_regression_checks,
    write_stage_manifest,
)
from step1_baseline import BASE_DIR, combined_hash, resolve_report_root


def contract_files() -> tuple[Path, ...]:
    return (
        BASE_DIR / "core" / "ontology.py",
        BASE_DIR / "core" / "rulepacks.py",
    )


def registry_snapshot() -> dict[str, Any]:
    return {
        "production_active": RULEPACK_REGISTRY.production_active,
        "rulepacks": [
            {
                "rule_id": item.rule_id,
                "key": {
                    "domain": item.key.domain.value,
                    "operation": item.key.operation.value,
                    "variant": item.key.variant.value if item.key.variant else None,
                },
                "required_role_spec_id": item.required_role_spec_id,
                "information_spec_id": item.information_spec_id,
                "base_blueprint_id": item.base_blueprint_id,
                "pair_constraint_ids": list(item.pair_constraint_ids),
                "permitted_disclosure_modes": [
                    mode.value for mode in item.permitted_disclosure_modes
                ],
                "contract_status": item.contract_status.value,
                "basis_refs": [ref.value for ref in item.basis_refs],
                "assumption_refs": list(item.assumption_refs),
                "version": item.version,
            }
            for item in RULE_PACKS
        ],
        "role_specs": [
            {
                "spec_id": item.spec_id,
                "allowed_roles": [role.value for role in item.allowed_roles],
                "minimum_cardinality": item.minimum_cardinality,
                "maximum_cardinality": item.maximum_cardinality,
                "identity_type_constraints": [
                    value.value for value in item.identity_type_constraints
                ],
                "locality_constraints": [
                    value.value for value in item.locality_constraints
                ],
                "same_as_focal_policy": item.same_as_focal_policy.value,
                "compatibility_predicates": [
                    value.value for value in item.compatibility_predicates
                ],
                "missing_role_disposition": item.missing_role_disposition.value,
            }
            for item in ROLE_SPECS
        ],
        "information_specs": [
            {
                "spec_id": item.spec_id,
                "required_slots": [slot.value for slot in item.required_slots],
                "conditional_slots": [
                    {
                        "slot": slot.slot.value,
                        "predicate_kind": slot.predicate_kind.value,
                        "predicate_ref": slot.predicate_ref,
                    }
                    for slot in item.conditional_slots
                ],
                "optional_slots": [slot.value for slot in item.optional_slots],
                "conflict_rules": [
                    {
                        "rule_id": rule.rule_id,
                        "slot": rule.slot.value,
                        "kind": rule.kind.value,
                    }
                    for rule in item.conflict_rules
                ],
                "typed_derivation_rules": [
                    {
                        "rule_id": rule.rule_id,
                        "slot": rule.slot.value,
                        "source": rule.source.value,
                        "source_field": rule.source_field.value,
                    }
                    for rule in item.typed_derivation_rules
                ],
                "missing_slot_disposition": item.missing_slot_disposition.value,
            }
            for item in INFORMATION_SPECS
        ],
        "blueprint_catalog": [
            {
                "blueprint_id": item.blueprint_id,
                "schema_version": item.schema_version,
                "implementation_status": item.implementation_status.value,
                "activation_stage": item.activation_stage,
            }
            for item in BLUEPRINT_CATALOG
        ],
        "constraint_catalog": [
            {
                "constraint_id": item.constraint_id,
                "schema_version": item.schema_version,
                "implementation_status": item.implementation_status.value,
                "activation_stage": item.activation_stage,
            }
            for item in CONSTRAINT_CATALOG
        ],
    }


def audit_exact_lookup() -> dict[str, Any]:
    resolutions: Counter[str] = Counter()
    errors: list[str] = []
    for domain in Domain:
        if domain == Domain.UNKNOWN:
            continue
        for operation in Operation:
            if operation == Operation.UNRESOLVED:
                continue
            for variant in (None, *RuleVariant):
                key = RulePackKey(domain, operation, variant)
                try:
                    resolution = RULEPACK_REGISTRY.resolve_exact(key)
                    resolutions[resolution.availability.value] += 1
                    if (
                        resolution.availability == RulePackAvailability.FOUND
                        and resolution.rulepack is not None
                        and resolution.rulepack.key != key
                    ):
                        errors.append(f"non-exact lookup: {key}")
                except Exception as exc:
                    errors.append(f"{key}: {type(exc).__name__}: {exc}")
    registered_exact = all(
        RULEPACK_REGISTRY.lookup(item.key) is item for item in RULE_PACKS
    )
    production_imports = []
    for path in (BASE_DIR / "core" / "decision.py", BASE_DIR / "harness.py"):
        source = path.read_text(encoding="utf-8")
        if "rulepacks" in source:
            production_imports.append(str(path.relative_to(BASE_DIR)))
    return {
        "resolutions": dict(sorted(resolutions.items())),
        "registered_exact": registered_exact,
        "errors": errors,
        "production_imports": production_imports,
        "production_active": RULEPACK_REGISTRY.production_active,
        "rulepack_count": len(RULE_PACKS),
        "role_spec_count": len(ROLE_SPECS),
        "information_spec_count": len(INFORMATION_SPECS),
        "blueprint_stub_count": len(BLUEPRINT_CATALOG),
        "constraint_stub_count": len(CONSTRAINT_CATALOG),
    }


def contract_markdown() -> str:
    return "\n".join(
        [
            "# Step 5 RulePack·RequiredRoleSpec·InformationSpec 계약",
            "",
            "## Exact Lookup",
            "",
            "RulePack은 `(Domain, Operation, optional RuleVariant)` typed key로만 조회한다. 미등록 key는 유사 key나 GENERAL, dispatch로 대체하지 않고 `UNSUPPORTED_RULEPACK` 상태를 보존한다.",
            "",
            "## Role",
            "",
            "실행 target role과 clarification authority, confirmation authority, memory owner를 분리했다. 실행 role은 interaction principal identity를 허용하지 않는다.",
            "",
            "## Information",
            "",
            "required, conditional, optional slot은 상호 배타적이다. derivation과 conflict는 등록된 enum만 사용하며 capability 상태를 InformationSpec에 포함하지 않는다.",
            "",
            "## 비활성 Reference",
            "",
            "`base_blueprint_id`와 `pair_constraint_ids`는 각각 Step 6, Step 7용 schema stub이다. Step 5 registry는 shadow-only이며 production decision path에 연결하지 않는다.",
            "",
        ]
    )


def build_report(result: dict[str, Any]) -> str:
    tests = result["tests"]
    audit = result["registry_audit"]
    gate = result["release_gate"]
    return "\n".join(
        [
            "# Step 5 RulePack·Role·Information 보고서",
            "",
            "## 작업 범위",
            "",
            "Step 5에서는 exact RulePack key와 role, information 계약을 shadow registry로 추가했다. 기존 production candidate 및 blueprint 경로는 변경하지 않았다.",
            "",
            "## Registry 현황",
            "",
            f"- RulePack: `{audit['rulepack_count']}`개",
            f"- RequiredRoleSpec: `{audit['role_spec_count']}`개",
            f"- InformationSpec: `{audit['information_spec_count']}`개",
            f"- Step 6 blueprint stub: `{audit['blueprint_stub_count']}`개",
            f"- Step 7 constraint stub: `{audit['constraint_stub_count']}`개",
            f"- exact lookup 오류: `{len(audit['errors'])}`개",
            f"- production import: `{len(audit['production_imports'])}`개",
            "",
            "미등록 조합 수는 정확도 오류가 아니라 unsupported coverage를 나타낸다. 각 미등록 key는 별도 `UNSUPPORTED_RULEPACK` resolution으로 유지된다.",
            "",
            "## 검증 결과",
            "",
            f"- Step 5 invariant: exit `{tests['stage_specific']['exit_code']}`, {', '.join(tests['stage_specific']['summary'])}",
            f"- 전체 pytest: exit `{tests['full']['exit_code']}`, {', '.join(tests['full']['summary'])}",
            f"- 알려진 dev gate 제외: exit `{tests['without_known_dev_gate']['exit_code']}`, {', '.join(tests['without_known_dev_gate']['summary'])}",
            f"- dev overall: `{result['dev']['overall']:.4f}` (Step 4와 동일: `{result['dev_unchanged']}`)",
            f"- screening public submission 동일: `{result['screening_submission_unchanged']}`",
            "",
            "## Step 5 Release Gate",
            "",
            f"- 상태: **{gate['status']}**",
            f"- 다음 단계 진입 가능: **{gate['next_stage_allowed']}**",
            *[f"- {reason}" for reason in gate["reasons"]],
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    report_root, root_source = resolve_report_root()
    output_dir = (args.output_dir or report_root / "step5_rulepacks").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_failed_attempt(
        output_dir,
        result_filename="step5_result.json",
        report_filename="STEP5_REPORT.md",
    )
    previous_dir, previous_result, previous_stage = resolve_previous_stage(
        report_root.resolve(),
        PreviousStageSpec("step4_language", "step4_language", "step4_result.json"),
    )
    source_hash_before = source_tree_hash(source_files())

    validation_errors: list[str] = []
    try:
        validate_rulepack_registry()
    except Exception as exc:
        validation_errors.append(f"validate_rulepack_registry: {exc}")
    snapshot = registry_snapshot()
    registry_path = output_dir / "rulepack_registry.json"
    registry_path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    contract_path = output_dir / "RULEPACK_CONTRACT.md"
    contract_path.write_text(contract_markdown(), encoding="utf-8")
    audit = audit_exact_lookup()
    audit_path = output_dir / "registry_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    regression = run_standard_regression(
        output_dir,
        stage_test_files=(
            "tests/test_rulepacks.py",
            "tests/test_ontology.py",
            "tests/test_architecture.py",
        ),
        previous_dir=previous_dir,
        previous_result=previous_result,
    )
    source_hash_after = source_tree_hash(source_files())
    checks = {
        "step4_artifact_integrity": bool(previous_stage.get("checks"))
        and all(previous_stage["checks"].values()),
        "registry_valid": not validation_errors,
        "exact_lookup": audit["registered_exact"] and not audit["errors"],
        "shadow_only": not audit["production_active"]
        and not audit["production_imports"],
        "source_stable_during_gate": source_hash_before == source_hash_after,
        **standard_regression_checks(regression),
    }
    gate_passed = all(checks.values())
    release_gate = {
        "status": "PASS_WITH_BASELINE_DEBT" if gate_passed else "FAIL",
        "next_stage_allowed": gate_passed,
        "checks": checks,
        "reasons": [
            "RulePack exact lookup와 reference integrity 검증이 통과했다.",
            "role boundary와 required, conditional, optional information 분리가 통과했다.",
            "Step 6·7 stub이 production에서 비활성 상태임을 확인했다.",
            "Step 4 대비 public dev 수치와 screening submission이 변하지 않았다.",
        ]
        if gate_passed
        else [
            f"실패한 Step 5 gate: {name}"
            for name, passed in checks.items()
            if not passed
        ]
        + validation_errors
        + list(previous_stage.get("errors") or []),
    }
    result = {
        "stage": "step5_rulepacks",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_command": f"{sys.executable} {Path(__file__).name}",
        "report_root": str(report_root.resolve()),
        "report_root_source": root_source,
        "output_dir": str(output_dir),
        "previous_stage": previous_stage,
        "source_tree_sha256": source_hash_after,
        "contract_sha256": combined_hash(contract_files(), root=BASE_DIR),
        "registry_sha256": sha256_file(registry_path),
        "registry_audit": audit,
        "dev": regression["dev"],
        "dev_unchanged": regression["dev_unchanged"],
        "screening_submission_sha256": regression["submission_sha256"],
        "screening_submission_unchanged": regression["submission_unchanged"],
        "tests": regression["tests"],
        "validation_errors": validation_errors,
        "release_gate": release_gate,
        "stage_manifest_path": str(output_dir / "stage_manifest.json"),
    }
    result_path = output_dir / "step5_result.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path = output_dir / "STEP5_REPORT.md"
    report_path.write_text(build_report(result), encoding="utf-8")
    write_stage_manifest(
        output_dir,
        stage="step5_rulepacks",
        source_hash=source_hash_after,
        artifact_paths=(
            registry_path,
            contract_path,
            audit_path,
            regression["submission_path"],
            result_path,
            report_path,
            output_dir / "consistency_report.md",
            regression["shadow_diff_path"],
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
