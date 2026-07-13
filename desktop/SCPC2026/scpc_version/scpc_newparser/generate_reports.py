from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_dev_errors import analyze_errors
from build_manifest import publish_candidate_manifest, write_reference_manifest
from local_score import score_dev
from official_baseline import generate_official_baseline_submission
from run_submission import run_submission
from utils.report import generate_distribution_report
from utils.diff import compare_submissions
from utils.io import find_data_dir
from validate_submission import validate_submission
from validate_artifacts import validate_current_artifacts


BASE_DIR = Path(__file__).resolve().parent


def _fixed_slm_report(status: dict[str, object]) -> str:
    interface = status["official_interface"]
    assert isinstance(interface, dict)
    fields = interface["output_fields"]
    assert isinstance(fields, list)
    gates = status["gate_results"]
    assert isinstance(gates, dict)
    gate_rows = (
        ("공식 interface·schema 확인", "PASS" if gates["interface_and_schema_confirmed"] else "FAIL"),
        ("parser-only 대비 일반화 개선", "PASS" if gates["parser_only_generalization_improvement"] else "NOT_PROVEN"),
        ("공식 dev 회귀 없음", "PASS (production 비연결)" if gates["official_dev_regression_free"] else "FAIL"),
        ("metamorphic·paraphrase", "PASS" if gates["metamorphic_and_paraphrase_passed"] else "NOT_PROVEN"),
        ("hard fact·current direct evidence authority 침해", f"{gates['hard_fact_authority_violations']}건"),
        ("timeout·invalid output parser-only 복구", "PASS" if gates["timeout_invalid_output_parser_only_recovery_verified"] else "NOT_PROVEN"),
    )
    lines = [
        "# Stage 3 FixedSLM 승격 보고서",
        "",
        f"- 결정: `{status['decision']}`",
        f"- production evidence 영향: `0` (`{str(status['production_influence']).lower()}`)",
        f"- 공식 facade: `{interface['class']}.{interface['method']}`",
        f"- model ID: `{interface['model_id']}`",
        "- 공식 출력: " + ", ".join(f"`{field}`" for field in fields),
        "",
        "## 판정 근거",
        "",
        "공식 notebook은 facade와 보조 evidence 역할을 제공하지만 timeout·invalid output 계약을 명시하지 않는다. 현재 소스에는 parser-only 대비 held-out paraphrase 개선 및 byte-equivalent recovery를 입증한 결과가 없다. 따라서 production evidence 병합 조건을 충족하지 못한다.",
        "",
        "| Gate | 결과 |",
        "| --- | --- |",
        *(f"| {name} | {value} |" for name, value in gate_rows),
        "",
        "`PROMOTE` 전까지 FixedSLM proposal은 FinalDecision의 `focal_id`, `target`, `control`, `content_scope`, `policy`, `plan_events`를 생성하거나 덮어쓸 수 없다.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reproduction-child",
        action="store_true",
        help="disable recursive report reproduction in an isolated child workspace",
    )
    parser.parse_args()
    # Resolve every required immutable input before any report is overwritten.
    find_data_dir()
    baseline_submission = generate_official_baseline_submission()
    dev_result = score_dev()
    analyze_errors()
    submission = run_submission(BASE_DIR / "submission.csv")
    validate_submission(submission)
    structural = generate_distribution_report(submission)
    reports = BASE_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "screening_structural_report.md").write_text(structural + "\n", encoding="utf-8")
    fixed_slm = json.loads(
        (BASE_DIR / "manifest" / "fixed_slm_status.json").read_text(
            encoding="utf-8"
        )
    )
    (reports / "stage3_fixed_slm_report.md").write_text(
        _fixed_slm_report(fixed_slm), encoding="utf-8"
    )
    (reports / "diff_vs_baseline.md").write_text(
        compare_submissions(
            baseline_submission,
            submission,
            reference_label="official_notebook_baseline/submission.csv",
            new_label="scpc_newparser/submission.csv",
        )
        + "\n",
        encoding="utf-8",
    )
    write_reference_manifest()
    staged_manifest = (
        BASE_DIR / "manifest" / ".candidate_manifest.generate.pending.json"
    )
    try:
        publish_candidate_manifest(
            dev_result,
            submission,
            output_path=staged_manifest,
        )
        validate_current_artifacts(
            submission,
            staged_manifest,
            reproduce=True,
            reproduce_reports=False,
            require_complete_reports=False,
        )
    finally:
        staged_manifest.unlink(missing_ok=True)
    print(
        "generated reports and validated submission; "
        "candidate manifest awaits release gate"
    )


if __name__ == "__main__":
    main()
