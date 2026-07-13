from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_keep_shadow_status_has_zero_production_influence() -> None:
    status = json.loads(
        (PROJECT_ROOT / "manifest" / "fixed_slm_status.json").read_text(
            encoding="utf-8"
        )
    )
    production_source = "\n".join(
        (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "harness.py",
            "core/state.py",
            "core/decision.py",
            "core/production_projection.py",
        )
    )

    assert status["decision"] == "KEEP_SHADOW"
    assert status["production_influence"] is False
    assert "FixedSLMClient" not in production_source
    assert "slm_contract" not in production_source


def test_fixed_slm_status_records_every_promotion_gate() -> None:
    status = json.loads(
        (PROJECT_ROOT / "manifest" / "fixed_slm_status.json").read_text(
            encoding="utf-8"
        )
    )

    assert set(status["gate_results"]) == {
        "interface_and_schema_confirmed",
        "parser_only_generalization_improvement",
        "official_dev_regression_free",
        "metamorphic_and_paraphrase_passed",
        "hard_fact_authority_violations",
        "timeout_invalid_output_parser_only_recovery_verified",
    }
