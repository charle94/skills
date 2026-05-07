"""Pipeline integration tests."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "scripts" / "analysis_pipeline.py"
EXAMPLES = ROOT / "examples"


def _run_pipeline(args, expect_failure=False):
    """Invoke the pipeline as a subprocess so we exercise the real CLI."""
    cmd = [sys.executable, str(PIPELINE)] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not expect_failure:
        assert result.returncode == 0, f"pipeline failed: {result.stderr}"
    return result


def test_base_limit_pipeline_writes_expected_artifacts(tmp_path):
    out = tmp_path / "out"
    _run_pipeline([
        "--input-path", str(EXAMPLES / "base_limit_sample.csv"),
        "--mode", "base_limit",
        "--output-dir", str(out),
    ])
    assert (out / "base_limit_results.csv").exists()
    assert (out / "run_summary.json").exists()
    assert (out / "validation_report.json").exists()
    assert (out / "run_metadata.json").exists()
    assert (out / "pipeline.log").exists()
    metadata = json.loads((out / "run_metadata.json").read_text())
    assert metadata["status"] == "success"


def test_invalid_input_fails_in_strict_mode(tmp_path):
    bad_input = tmp_path / "bad.csv"
    bad_input.write_text(
        "customer_id,monthly_income,income_source,existing_debt,tenor_months\n"
        "X1,-100,unknown,1000,12\n"
    )
    out = tmp_path / "out"
    result = _run_pipeline([
        "--input-path", str(bad_input),
        "--mode", "base_limit",
        "--output-dir", str(out),
        "--strict-validation",
    ], expect_failure=True)
    assert result.returncode != 0
    assert "validation failed" in result.stderr.lower()


def test_run_metadata_records_failure(tmp_path):
    bad_input = tmp_path / "bad.csv"
    bad_input.write_text("customer_id\nX1\n")
    out = tmp_path / "out"
    _run_pipeline([
        "--input-path", str(bad_input),
        "--mode", "base_limit",
        "--output-dir", str(out),
    ], expect_failure=True)
    metadata = json.loads((out / "run_metadata.json").read_text())
    assert metadata["status"] == "failed"
    assert metadata["error_message"] is not None


def test_full_limit_strategy_pipeline_runs(tmp_path):
    out = tmp_path / "out"
    _run_pipeline([
        "--input-path", str(EXAMPLES / "base_limit_sample.csv"),
        "--mode", "full_limit_strategy",
        "--output-dir", str(out),
    ])
    assert (out / "run_summary.json").exists()
    summary = json.loads((out / "run_summary.json").read_text())
    assert summary["mode"] == "full_limit_strategy"
    assert "validation_report" in summary


def test_simulation_pipeline_runs(tmp_path):
    out = tmp_path / "out"
    challenger = tmp_path / "challenger.json"
    challenger.write_text(json.dumps({"product_cap": 60000.0}))
    sim_input = tmp_path / "sim.csv"
    sim_input.write_text(
        "customer_id,monthly_income,income_source,existing_debt,tenor_months,risk_score,dti\n"
        "S001,15000,payroll,1000,24,0.85,0.2\n"
        "S002,10000,bank_flow,500,12,0.55,0.4\n"
        "S003,20000,payroll,2000,36,0.92,0.15\n"
    )
    _run_pipeline([
        "--input-path", str(sim_input),
        "--mode", "simulation",
        "--challenger-config-path", str(challenger),
        "--output-dir", str(out),
    ])
    assert (out / "simulation_side_by_side.csv").exists()
    summary = json.loads((out / "run_summary.json").read_text())
    assert "decision" in summary["summary"]
