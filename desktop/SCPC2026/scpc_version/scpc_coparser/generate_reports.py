from __future__ import annotations

from pathlib import Path

from analyze_dev_errors import analyze_errors
from build_manifest import build_manifest, write_reference_manifest
from local_score import score_dev
from run_submission import run_submission
from utils.report import generate_distribution_report
from utils.diff import compare_submissions
from validate_submission import validate_submission
from validate_artifacts import validate_current_artifacts


BASE_DIR = Path(__file__).resolve().parent


def main() -> None:
    dev_result = score_dev()
    analyze_errors()
    submission = run_submission(BASE_DIR / "submission.csv")
    validate_submission(submission)
    structural = generate_distribution_report(submission)
    reports = BASE_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "screening_structural_report.md").write_text(structural + "\n", encoding="utf-8")
    baseline_submission = (
        BASE_DIR.parent
        / "scpc_Gparser"
        / "reference"
        / "V5_modular_harness"
        / "submission.csv"
    )
    if baseline_submission.is_file():
        (reports / "diff_vs_baseline.md").write_text(
            compare_submissions(baseline_submission, submission) + "\n",
            encoding="utf-8",
        )
    write_reference_manifest()
    build_manifest(dev_result, submission)
    validate_current_artifacts(submission)
    print("generated reports, manifests, and validated submission")


if __name__ == "__main__":
    main()
