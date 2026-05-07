"""Unified pipeline for credit limit strategy workflows.

This script is the default agent entry point. It reads a local dataset,
runs the requested strategy mode, and writes structured outputs for later
inspection by the agent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from config import DEFAULT_CONFIG, load_config
from limit_calculation import REQUIRED_COLUMNS as BASE_LIMIT_COLUMNS
from limit_calculation import calculate_batch_limits, generate_summary_stats
from risk_adjustment import REQUIRED_COLUMNS as RISK_ADJUSTMENT_COLUMNS
from risk_adjustment import adjust_batch_limits, generate_risk_summary, validate_risk_ranking
from dynamic_adjustment import REQUIRED_COLUMNS as DYNAMIC_COLUMNS
from dynamic_adjustment import adjust_batch_customers, generate_adjustment_summary
from causal_inference import REQUIRED_COLUMNS as CAUSAL_COLUMNS
from causal_inference import generate_evaluation_report, run_causal_analysis
from strategy_tuning import REQUIRED_COLUMNS as TUNING_COLUMNS
from strategy_tuning import diagnose_strategy, generate_tuning_report
from vintage_analysis import REQUIRED_COLUMNS as VINTAGE_COLUMNS
from vintage_analysis import generate_vintage_report, run_vintage_analysis
from portfolio_monitoring import REQUIRED_COLUMNS_PSI as MONITORING_COLUMNS
from portfolio_monitoring import generate_monitoring_report, run_portfolio_monitoring


MODE_REQUIREMENTS = {
    "base_limit": BASE_LIMIT_COLUMNS,
    "risk_adjustment": RISK_ADJUSTMENT_COLUMNS,
    "dynamic_adjustment": DYNAMIC_COLUMNS,
    "causal_evaluation": CAUSAL_COLUMNS,
    "strategy_tuning": TUNING_COLUMNS,
    "vintage_analysis": VINTAGE_COLUMNS,
    "portfolio_monitoring": MONITORING_COLUMNS,
    "full_limit_strategy": BASE_LIMIT_COLUMNS,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run credit limit strategy workflows.")
    parser.add_argument("--input-path", required=True, help="Path to csv, json, or parquet input data.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(MODE_REQUIREMENTS.keys()),
        help="Workflow mode to execute.",
    )
    parser.add_argument("--output-dir", default="analysis_output", help="Directory for generated outputs.")
    parser.add_argument("--config-path", help="Optional JSON config override path.")
    parser.add_argument(
        "--base-period-path",
        help="Reference/base period data for portfolio_monitoring PSI/CSI comparison.",
    )
    return parser.parse_args()


def read_dataframe(input_path: Path) -> pd.DataFrame:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix == ".json":
        return pd.read_json(input_path)
    if suffix == ".parquet":
        return pd.read_parquet(input_path)
    raise ValueError(f"Unsupported input format: {input_path.suffix}")


def ensure_columns(df: pd.DataFrame, required_columns: List[str], mode: str) -> None:
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(f"Mode '{mode}' is missing required columns: {missing}")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(to_builtin(payload), indent=2, ensure_ascii=True), encoding="utf-8")


def to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_builtin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [to_builtin(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return str(value)
    return value


def write_report(path: Path, lines: List[str]) -> None:
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def determine_policy_readiness(mode: str, summary: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Classify whether the run is decision-ready, partial, or blocked."""
    reasons: List[str] = []
    status = "ready"

    if mode == "base_limit":
        affordability = summary.get("affordability_distribution", {})
        if affordability.get("not_affordable", 0) > 0:
            status = "partial"
            reasons.append("some_accounts_have_no_affordability_and_should_not_receive_floor_protection")
        if summary.get("warning_count", 0) > 0:
            status = "partial"
            reasons.append("input_or_income_quality_warnings_present")
    elif mode == "risk_adjustment":
        validation = summary.get("validation", {})
        if not validation.get("validation_passed", False):
            status = "blocked"
            reasons.append("risk_ranking_validation_failed")
        if summary.get("summary", {}).get("floor_block_count", 0) > 0:
            status = "partial" if status != "blocked" else status
            reasons.append("floor_application_was_blocked_for_non_affordable_accounts")
    elif mode == "dynamic_adjustment":
        if summary.get("heuristic_pd_count", 0) > 0:
            status = "partial"
            reasons.append("expected_loss_uses_heuristic_pd_for_some_accounts")
    elif mode == "causal_evaluation":
        evidence_tier = summary.get("evidence_tier", "")
        if evidence_tier != "causal_psm_ready":
            status = "partial"
            reasons.append(f"causal_design_is_not_fully_credible:{evidence_tier}")
    elif mode == "strategy_tuning":
        if summary.get("over_target_cells", 0) > 0 and summary.get("high_confidence_over_target", 0) > 0:
            status = "partial"
            reasons.append("high_confidence_cells_over_target_require_tightening")
        if summary.get("insufficient_data_cells", 0) > 0:
            if status == "ready":
                status = "partial"
            reasons.append("some_cells_have_insufficient_data_for_reliable_recommendations")
    elif mode == "vintage_analysis":
        if summary.get("deteriorating_cohorts", 0) > 0:
            status = "partial"
            reasons.append(f"deteriorating_cohorts_detected:{summary['deteriorating_cohorts']}")
    elif mode == "portfolio_monitoring":
        if summary.get("high_severity_alerts", 0) > 0:
            status = "blocked"
            reasons.append(f"high_severity_kpi_alerts:{summary['high_severity_alerts']}")
        elif summary.get("total_alerts", 0) > 0 or summary.get("psi_stability") in ("moderate_shift", "significant_shift"):
            status = "partial"
            reasons.append("score_distribution_or_kpi_shift_detected")
    elif mode == "full_limit_strategy":
        if summary.get("skipped_steps"):
            status = "partial"
            reasons.append("one_or_more_strategy_layers_were_skipped")
        if summary.get("risk_validation", {}).get("validation_passed") is False:
            status = "blocked"
            reasons.append("risk_ranking_validation_failed")

    return status, reasons


def run_base_limit(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    result_df = calculate_batch_limits(df, config=config)
    result_df.to_csv(output_dir / "base_limit_results.csv", index=False)
    summary = generate_summary_stats(result_df)
    report_lines = [
        "# Base Limit Analysis",
        "",
        f"Rows processed: {summary['total_customers']}",
        f"Average base limit: {summary['avg_base_limit']}",
        f"Median base limit: {summary['median_base_limit']}",
        f"Affordability distribution: {summary['affordability_distribution']}",
        f"Warnings raised: {summary['warning_count']}",
    ]
    return summary, report_lines


def run_risk_adjustment(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    result_df = adjust_batch_limits(df, config=config)
    result_df.to_csv(output_dir / "risk_adjustment_results.csv", index=False)
    summary = generate_risk_summary(result_df)
    validation = validate_risk_ranking(result_df, df)
    combined_summary = {"summary": summary, "validation": validation}
    report_lines = [
        "# Risk Adjustment Analysis",
        "",
        f"Rows processed: {summary['total_customers']}",
        f"Average final limit: {summary['avg_final_limit']}",
        f"Ranking validation passed: {validation['validation_passed']}",
        f"Floor block count: {summary['floor_block_count']}",
        f"Risk-limit correlation: {validation['correlation_risk_limit']}",
    ]
    return combined_summary, report_lines


def run_dynamic_adjustment(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    result_df = adjust_batch_customers(df, config=config)
    result_df.to_csv(output_dir / "dynamic_adjustment_results.csv", index=False)
    summary = generate_adjustment_summary(result_df)
    report_lines = [
        "# Dynamic Adjustment Analysis",
        "",
        f"Rows processed: {summary['total_customers']}",
        f"High priority accounts: {summary['high_priority_count']}",
        f"Heuristic PD count: {summary['heuristic_pd_count']}",
        f"Total expected loss change: {summary['total_expected_el_change']}",
        f"Action distribution: {summary['action_distribution']}",
    ]
    return summary, report_lines


def run_causal_evaluation(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    covariates = [column for column in ["risk_score", "income", "age", "dti", "utilization_rate"] if column in df.columns]
    result = run_causal_analysis(df, covariate_cols=covariates, config=config)
    report_text = generate_evaluation_report(result)
    result_summary = {
        "ate": result.ate,
        "att": result.att,
        "lift": result.lift,
        "ks_statistic": result.ks_statistic,
        "ks_pvalue": result.ks_pvalue,
        "confidence_interval_95": list(result.confidence_interval_95),
        "sample_sizes": result.sample_sizes,
        "default_rates": result.default_rates,
        "profit_simulation": result.profit_simulation,
        "balance_diagnostics": result.balance_diagnostics,
        "overlap_diagnostics": result.overlap_diagnostics,
        "evidence_tier": result.evidence_tier,
    }
    (output_dir / "causal_evaluation_report.md").write_text(report_text + "\n", encoding="utf-8")
    return result_summary, report_text.splitlines()


def run_full_limit_strategy(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    summary: Dict[str, Any] = {"steps_run": [], "skipped_steps": []}
    report_lines = ["# Full Limit Strategy Analysis", ""]

    ensure_columns(df, BASE_LIMIT_COLUMNS, "full_limit_strategy")
    base_result_df = calculate_batch_limits(df, config=config)
    base_result_df.to_csv(output_dir / "base_limit_results.csv", index=False)
    summary["steps_run"].append("base_limit")
    summary["base_limit"] = generate_summary_stats(base_result_df)
    report_lines.extend([
        "## Base Limit",
        f"Rows processed: {summary['base_limit']['total_customers']}",
        f"Average base limit: {summary['base_limit']['avg_base_limit']}",
        f"Affordability distribution: {summary['base_limit']['affordability_distribution']}",
        "",
    ])

    merged_df = df.merge(base_result_df[["customer_id", "base_limit"]], on="customer_id", how="left")
    merged_df = merged_df.merge(
        base_result_df[["customer_id", "affordability_status", "floor_eligible"]],
        on="customer_id",
        how="left",
    )

    if all(column in merged_df.columns for column in ["risk_score", "dti"]):
        risk_result_df = adjust_batch_limits(merged_df, config=config)
        risk_result_df.to_csv(output_dir / "risk_adjustment_results.csv", index=False)
        summary["steps_run"].append("risk_adjustment")
        summary["risk_adjustment"] = generate_risk_summary(risk_result_df)
        summary["risk_validation"] = validate_risk_ranking(risk_result_df, merged_df)
        report_lines.extend([
            "## Risk Adjustment",
            f"Average final limit: {summary['risk_adjustment']['avg_final_limit']}",
            f"Ranking validation passed: {summary['risk_validation']['validation_passed']}",
            "",
        ])
        current_limit_map = risk_result_df.set_index("customer_id")["final_limit"]
        merged_df["current_limit"] = merged_df["customer_id"].map(current_limit_map)
    else:
        summary["skipped_steps"].append("risk_adjustment")
        report_lines.extend(["## Risk Adjustment", "Skipped because `risk_score` or `dti` is missing.", ""])

    if "current_limit" in merged_df.columns:
        dynamic_result_df = adjust_batch_customers(merged_df, config=config)
        dynamic_result_df.to_csv(output_dir / "dynamic_adjustment_results.csv", index=False)
        summary["steps_run"].append("dynamic_adjustment")
        summary["dynamic_adjustment"] = generate_adjustment_summary(dynamic_result_df)
        report_lines.extend([
            "## Dynamic Adjustment",
            f"High priority accounts: {summary['dynamic_adjustment']['high_priority_count']}",
            f"Heuristic PD count: {summary['dynamic_adjustment']['heuristic_pd_count']}",
            f"Action distribution: {summary['dynamic_adjustment']['action_distribution']}",
            "",
        ])
    else:
        summary["skipped_steps"].append("dynamic_adjustment")
        report_lines.extend(["## Dynamic Adjustment", "Skipped because no `current_limit` could be constructed.", ""])

    return summary, report_lines


def run_strategy_tuning(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    cell_df, summary = diagnose_strategy(df, config=config)
    cell_df.to_csv(output_dir / "strategy_tuning_results.csv", index=False)
    report_lines = generate_tuning_report(cell_df, summary)
    return summary, report_lines


def run_vintage_analysis_mode(df: pd.DataFrame, output_dir: Path, config) -> Tuple[Dict[str, Any], List[str]]:
    bad_rate_matrix, z_matrix, projection_df, count_matrix, summary = run_vintage_analysis(df, config=config)
    bad_rate_matrix.to_csv(output_dir / "vintage_bad_rate_matrix.csv")
    z_matrix.to_csv(output_dir / "vintage_z_score_matrix.csv")
    projection_df.to_csv(output_dir / "vintage_projection.csv", index=False)
    count_matrix.to_csv(output_dir / "vintage_count_matrix.csv")
    from vintage_analysis import generate_vintage_report as _gen
    report_lines = _gen(bad_rate_matrix, z_matrix, projection_df, summary)
    return summary, report_lines


def run_portfolio_monitoring_mode(
    df: pd.DataFrame,
    base_df: pd.DataFrame,
    output_dir: Path,
    config,
) -> Tuple[Dict[str, Any], List[str]]:
    feature_cols = [c for c in df.columns if c not in ("customer_id", "score", "period", "bad_flag")]
    psi_score, psi_detail_df, csi_df, trend_df, alerts, summary = run_portfolio_monitoring(
        base_df, df, feature_cols=feature_cols if feature_cols else None, config=config
    )
    if len(psi_detail_df):
        psi_detail_df.to_csv(output_dir / "psi_detail.csv", index=False)
    if len(csi_df):
        csi_df.to_csv(output_dir / "csi_results.csv", index=False)
    if len(trend_df):
        trend_df.to_csv(output_dir / "kpi_trends.csv", index=False)
    report_lines = generate_monitoring_report(psi_score, psi_detail_df, csi_df, trend_df, alerts, summary, config)
    return summary, report_lines


def main() -> None:
    args = parse_args()
    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config(args.config_path) if args.config_path else DEFAULT_CONFIG
    df = read_dataframe(input_path)

    ensure_columns(df, MODE_REQUIREMENTS[args.mode], args.mode)

    if args.mode == "base_limit":
        summary, report_lines = run_base_limit(df, output_dir, config)
    elif args.mode == "risk_adjustment":
        summary, report_lines = run_risk_adjustment(df, output_dir, config)
    elif args.mode == "dynamic_adjustment":
        summary, report_lines = run_dynamic_adjustment(df, output_dir, config)
    elif args.mode == "causal_evaluation":
        summary, report_lines = run_causal_evaluation(df, output_dir, config)
    elif args.mode == "strategy_tuning":
        summary, report_lines = run_strategy_tuning(df, output_dir, config)
    elif args.mode == "vintage_analysis":
        summary, report_lines = run_vintage_analysis_mode(df, output_dir, config)
    elif args.mode == "portfolio_monitoring":
        base_path = getattr(args, "base_period_path", None)
        if not base_path:
            raise ValueError("portfolio_monitoring requires --base-period-path for the reference period data.")
        base_df = read_dataframe(Path(base_path))
        summary, report_lines = run_portfolio_monitoring_mode(df, base_df, output_dir, config)
    else:
        summary, report_lines = run_full_limit_strategy(df, output_dir, config)

    run_summary = {
        "mode": args.mode,
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "row_count": int(len(df)),
        "columns": list(df.columns),
        "summary": summary,
    }
    readiness_status, readiness_reasons = determine_policy_readiness(args.mode, summary)
    run_summary["policy_readiness"] = readiness_status
    run_summary["readiness_reasons"] = readiness_reasons
    report_lines.extend([
        "",
        "# Policy Readiness",
        f"Status: {readiness_status}",
        f"Reasons: {readiness_reasons}",
    ])
    write_json(output_dir / "run_summary.json", run_summary)
    write_report(output_dir / "analysis_report.md", report_lines)


if __name__ == "__main__":
    main()