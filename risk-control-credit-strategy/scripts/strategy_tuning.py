"""Cell-level strategy diagnostics and coefficient tuning recommendations.

Input: individual loan/customer performance data (post-approval) that includes
segment labels (risk_level, dti_bin) and an outcome flag (bad_flag).

Output: per-cell bad rate analysis, deviation from target, and recommended
coefficient adjustment factors with a portfolio impact simulation.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CreditLimitConfig, DEFAULT_CONFIG
from risk_adjustment import bin_dti, bin_risk_score

REQUIRED_COLUMNS = ["customer_id", "bad_flag"]


def _prepare_segment_columns(
    df: pd.DataFrame,
    config: CreditLimitConfig,
    limit_col: str,
) -> pd.DataFrame:
    """Derive risk_level and dti_bin from raw scores when not already present."""
    working = df.copy()

    if "risk_level" not in working.columns and "risk_score" in working.columns:
        working["risk_level"] = working["risk_score"].apply(
            lambda s: bin_risk_score(s, config.risk_coefficient.risk_score_bins)
        )

    if "dti_bin" not in working.columns and "dti" in working.columns:
        working["dti_bin"] = working["dti"].apply(
            lambda d: bin_dti(d, config.risk_coefficient.dti_bins)
        )

    if limit_col not in working.columns:
        for alt in ("current_limit", "base_limit", "adjusted_limit"):
            if alt in working.columns:
                working[limit_col] = working[alt]
                break
        if limit_col not in working.columns:
            working[limit_col] = 0.0

    return working


def diagnose_strategy(
    df: pd.DataFrame,
    group_cols: Optional[List[str]] = None,
    target_bad_rates: Optional[Dict[str, float]] = None,
    lgd: Optional[float] = None,
    deviation_threshold: Optional[float] = None,
    mob_min: Optional[int] = None,
    config: CreditLimitConfig = None,
    limit_col: str = "final_limit",
    bad_flag_col: str = "bad_flag",
    util_col: str = "utilization_rate",
) -> Tuple[pd.DataFrame, Dict]:
    """Aggregate performance by segment cell and produce per-cell diagnostic metrics.

    Parameters
    ----------
    df : DataFrame with individual loan/customer records.
    group_cols : Columns to segment by (defaults to available risk_level + dti_bin + channel).
    target_bad_rates : Dict mapping risk_level → target bad rate (uses config defaults if None).
    lgd : Loss-given-default fraction (uses config default if None).
    deviation_threshold : Fraction deviation from target that triggers action (uses config default if None).
    mob_min : Only include accounts with months_on_book >= this value (maturity filter).
    config : Full config object (uses DEFAULT_CONFIG if None).
    limit_col : Column name for limit/exposure.
    bad_flag_col : Column name for default indicator (0/1).
    util_col : Column name for utilization rate.

    Returns
    -------
    (cell_df, summary_dict) where cell_df is sorted by bad_rate_deviation_pct descending.
    """
    if config is None:
        config = DEFAULT_CONFIG

    tuning_cfg = config.strategy_tuning
    if target_bad_rates is None:
        target_bad_rates = tuning_cfg.target_bad_rates
    if lgd is None:
        lgd = tuning_cfg.lgd
    if deviation_threshold is None:
        deviation_threshold = tuning_cfg.deviation_threshold
    if mob_min is None:
        mob_min = tuning_cfg.mob_min_for_maturity

    min_obs = tuning_cfg.min_cell_observations

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"strategy_tuning requires columns: {missing}")

    working = _prepare_segment_columns(df, config, limit_col)

    if "months_on_book" in working.columns:
        working = working[working["months_on_book"] >= mob_min].copy()

    if group_cols is None:
        group_cols = [
            c for c in ("risk_level", "dti_bin", "channel", "income_source")
            if c in working.columns
        ]
    if not group_cols:
        raise ValueError(
            "Cannot determine segment columns. Provide group_cols or ensure "
            "risk_level/risk_score is available in the data."
        )

    missing_group = [c for c in group_cols if c not in working.columns]
    if missing_group:
        raise ValueError(f"Grouping columns not found in data: {missing_group}")

    agg: Dict = {bad_flag_col: ["count", "sum", "mean"]}
    if limit_col in working.columns:
        agg[limit_col] = "mean"
    if util_col in working.columns:
        agg[util_col] = "mean"

    cell_df = working.groupby(group_cols, observed=True).agg(agg).reset_index()
    cell_df.columns = [
        "_".join(c).strip("_") if isinstance(c, tuple) else c
        for c in cell_df.columns
    ]

    rename_map = {
        f"{bad_flag_col}_count": "customer_count",
        f"{bad_flag_col}_sum": "bad_count",
        f"{bad_flag_col}_mean": "observed_bad_rate",
        f"{limit_col}_mean": "avg_limit",
        f"{util_col}_mean": "avg_utilization",
    }
    cell_df = cell_df.rename(columns={k: v for k, v in rename_map.items() if k in cell_df.columns})

    if "avg_utilization" not in cell_df.columns:
        cell_df["avg_utilization"] = 0.70
    if "avg_limit" not in cell_df.columns:
        cell_df["avg_limit"] = 0.0

    cell_df["bad_count"] = cell_df["bad_count"].fillna(0).astype(int)
    cell_df["customer_count"] = cell_df["customer_count"].astype(int)

    if "risk_level" in cell_df.columns:
        cell_df["target_bad_rate"] = cell_df["risk_level"].map(target_bad_rates).fillna(0.10)
    else:
        cell_df["target_bad_rate"] = 0.05

    cell_df["bad_rate_deviation_pct"] = (
        (cell_df["observed_bad_rate"] - cell_df["target_bad_rate"])
        / cell_df["target_bad_rate"].replace(0, np.nan)
        * 100
    ).round(2).fillna(0.0)

    cell_df["expected_loss_per_customer"] = (
        cell_df["avg_limit"] * cell_df["avg_utilization"]
        * cell_df["observed_bad_rate"] * lgd
    ).round(2)
    cell_df["total_expected_loss"] = (
        cell_df["expected_loss_per_customer"] * cell_df["customer_count"]
    ).round(2)

    threshold_pct = deviation_threshold * 100
    cell_df["status"] = np.select(
        [
            cell_df["customer_count"] < min_obs,
            cell_df["bad_rate_deviation_pct"] > threshold_pct,
            cell_df["bad_rate_deviation_pct"] < -threshold_pct,
        ],
        ["insufficient_data", "over_target", "under_target"],
        default="on_target",
    )

    action_map = {
        "over_target": "tighten",
        "on_target": "hold",
        "under_target": "relax",
        "insufficient_data": "monitor",
    }
    cell_df["recommended_action"] = cell_df["status"].map(action_map)

    raw_factor = (
        cell_df["target_bad_rate"] / cell_df["observed_bad_rate"].replace(0, np.nan)
    ).fillna(1.0)

    cell_df["recommended_coefficient_factor"] = np.where(
        cell_df["status"] == "over_target",
        raw_factor.clip(tuning_cfg.min_tighten_factor, 0.99),
        np.where(
            cell_df["status"] == "under_target",
            raw_factor.clip(1.01, tuning_cfg.max_relax_factor),
            1.0,
        ),
    )

    cell_df["confidence"] = pd.cut(
        cell_df["customer_count"],
        bins=[0, min_obs, 100, float("inf")],
        labels=["low", "medium", "high"],
        right=True,
    ).astype(str)

    cell_df["estimated_el_reduction"] = 0.0
    tighten = cell_df["status"] == "over_target"
    if tighten.any():
        cell_df.loc[tighten, "estimated_el_reduction"] = (
            cell_df.loc[tighten, "total_expected_loss"]
            * (1.0 - cell_df.loc[tighten, "recommended_coefficient_factor"])
        ).round(2)

    cell_df = cell_df.sort_values("bad_rate_deviation_pct", ascending=False).reset_index(drop=True)

    summary: Dict = {
        "total_cells": int(len(cell_df)),
        "over_target_cells": int((cell_df["status"] == "over_target").sum()),
        "on_target_cells": int((cell_df["status"] == "on_target").sum()),
        "under_target_cells": int((cell_df["status"] == "under_target").sum()),
        "insufficient_data_cells": int((cell_df["status"] == "insufficient_data").sum()),
        "total_customers_analyzed": int(cell_df["customer_count"].sum()),
        "total_portfolio_expected_loss": round(float(cell_df["total_expected_loss"].sum()), 2),
        "estimated_el_reduction_from_tightening": round(
            float(cell_df["estimated_el_reduction"].sum()), 2
        ),
        "high_confidence_over_target": int(
            ((cell_df["status"] == "over_target") & (cell_df["confidence"] == "high")).sum()
        ),
    }

    return cell_df, summary


def generate_tuning_report(cell_df: pd.DataFrame, summary: Dict) -> List[str]:
    """Render a structured markdown strategy tuning report."""
    id_cols = [c for c in ("risk_level", "dti_bin", "channel", "income_source") if c in cell_df.columns]

    def seg_label(row: pd.Series) -> str:
        return " / ".join(str(row[c]) for c in id_cols if pd.notna(row.get(c)))

    lines: List[str] = [
        "# Strategy Tuning Diagnostic Report",
        "",
        "## Portfolio Summary",
        f"- Cells analyzed: {summary['total_cells']}",
        f"- Customers analyzed: {summary['total_customers_analyzed']:,}",
        f"- **Cells over target (need tightening): {summary['over_target_cells']}**",
        f"- Cells on target: {summary['on_target_cells']}",
        f"- Cells under target (can relax): {summary['under_target_cells']}",
        f"- Insufficient data: {summary['insufficient_data_cells']}",
        f"- Total portfolio EL: {summary['total_portfolio_expected_loss']:,.2f}",
        f"- **Estimated EL reduction from tightening: {summary['estimated_el_reduction_from_tightening']:,.2f}**",
        "",
    ]

    over = cell_df[cell_df["status"] == "over_target"]
    if len(over):
        lines += [
            "## Cells Requiring Tightening",
            "",
            "| Segment | Obs BR | Target BR | Deviation | Count | Confidence | Coeff Factor | Est EL Reduction |",
            "|---------|--------|-----------|-----------|-------|------------|-------------|-----------------|",
        ]
        for _, row in over.iterrows():
            lines.append(
                f"| {seg_label(row)} | {row['observed_bad_rate']:.3f} | {row['target_bad_rate']:.3f} "
                f"| +{row['bad_rate_deviation_pct']:.1f}% | {row['customer_count']:,} "
                f"| {row['confidence']} | {row['recommended_coefficient_factor']:.2f}x "
                f"| {row['estimated_el_reduction']:,.0f} |"
            )
        lines.append("")

    under = cell_df[cell_df["status"] == "under_target"]
    if len(under):
        lines += [
            "## Cells Eligible for Relaxation",
            "",
            "| Segment | Obs BR | Target BR | Deviation | Count | Confidence | Coeff Factor |",
            "|---------|--------|-----------|-----------|-------|------------|-------------|",
        ]
        for _, row in under.iterrows():
            lines.append(
                f"| {seg_label(row)} | {row['observed_bad_rate']:.3f} | {row['target_bad_rate']:.3f} "
                f"| {row['bad_rate_deviation_pct']:.1f}% | {row['customer_count']:,} "
                f"| {row['confidence']} | {row['recommended_coefficient_factor']:.2f}x |"
            )
        lines.append("")

    insufficient = cell_df[cell_df["status"] == "insufficient_data"]
    if len(insufficient):
        lines += [
            "## Cells With Insufficient Data (monitor only)",
            "",
            "| Segment | Obs BR | Count |",
            "|---------|--------|-------|",
        ]
        for _, row in insufficient.iterrows():
            lines.append(
                f"| {seg_label(row)} | {row['observed_bad_rate']:.3f} | {row['customer_count']:,} |"
            )
        lines.append("")

    lines += [
        "## Caveats and Next Steps",
        "1. Coefficient factors are estimates. Simulate on holdout data before applying.",
        "2. Apply tightening only to high-confidence cells with confirmed root cause.",
        "3. Test relaxation via champion/challenger before broad rollout.",
        "4. Only cells with months_on_book >= maturity filter are included.",
        "5. Override default target bad rates with product-specific benchmarks for production use.",
        "",
    ]

    return lines
