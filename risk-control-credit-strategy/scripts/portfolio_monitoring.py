"""Portfolio health monitoring: PSI, CSI, and KPI trend alerts.

PSI (Population Stability Index): measures how much a score or variable distribution
has shifted between a base period and a monitoring period.

CSI (Characteristic Stability Index): same concept applied to individual input
features/characteristics rather than the final model score.

KPI tracking: bad rate, approval rate, utilization, and EL trends over time.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CreditLimitConfig, DEFAULT_CONFIG

REQUIRED_COLUMNS_PSI = ["customer_id", "score", "period"]


def compute_psi(
    base: pd.Series,
    current: pd.Series,
    bins: int = 10,
    epsilon: float = 1e-6,
) -> Tuple[float, pd.DataFrame]:
    """Compute the Population Stability Index between two score distributions.

    PSI = Σ (actual% - expected%) × ln(actual% / expected%)

    Parameters
    ----------
    base    : Score distribution from the base/reference period.
    current : Score distribution from the monitoring period.
    bins    : Number of equal-frequency bins derived from the base distribution.
    epsilon : Small constant to avoid log(0).

    Returns
    -------
    (psi_value, detail_df) where detail_df has one row per bin.
    """
    base_clean = base.dropna()
    current_clean = current.dropna()

    if len(base_clean) == 0 or len(current_clean) == 0:
        return np.nan, pd.DataFrame()

    quantiles = np.linspace(0, 100, bins + 1)
    bin_edges = np.unique(np.percentile(base_clean, quantiles))

    if len(bin_edges) < 2:
        return 0.0, pd.DataFrame()

    bin_edges[0] = -np.inf
    bin_edges[-1] = np.inf

    base_counts = pd.cut(base_clean, bins=bin_edges).value_counts(sort=False)
    current_counts = pd.cut(current_clean, bins=bin_edges).value_counts(sort=False)

    base_pct = (base_counts / len(base_clean)).clip(lower=epsilon)
    current_pct = (current_counts / len(current_clean)).clip(lower=epsilon)

    psi_contributions = (current_pct - base_pct) * np.log(current_pct / base_pct)
    psi_value = float(psi_contributions.sum())

    detail_df = pd.DataFrame(
        {
            "bin": base_counts.index.astype(str),
            "base_count": base_counts.values,
            "current_count": current_counts.values,
            "base_pct": base_pct.values.round(4),
            "current_pct": current_pct.values.round(4),
            "psi_contribution": psi_contributions.values.round(6),
        }
    )

    return round(psi_value, 6), detail_df


def classify_psi(psi_value: float, config: CreditLimitConfig = None) -> str:
    """Return a stability label for a PSI value."""
    if config is None:
        config = DEFAULT_CONFIG
    thresholds = config.portfolio_monitoring.psi_thresholds
    stable = thresholds.get("stable", 0.10)
    moderate = thresholds.get("moderate_shift", 0.25)
    if np.isnan(psi_value):
        return "unknown"
    if psi_value < stable:
        return "stable"
    if psi_value < moderate:
        return "moderate_shift"
    return "significant_shift"


def compute_csi(
    base_df: pd.DataFrame,
    current_df: pd.DataFrame,
    feature_cols: List[str],
    bins: int = 10,
    config: CreditLimitConfig = None,
) -> pd.DataFrame:
    """Compute CSI for a list of input features.

    Returns a DataFrame with one row per feature: csi_value, stability_label.
    """
    if config is None:
        config = DEFAULT_CONFIG

    records = []
    for col in feature_cols:
        if col not in base_df.columns or col not in current_df.columns:
            records.append({"feature": col, "csi_value": np.nan, "stability": "missing"})
            continue
        csi_val, _ = compute_psi(base_df[col], current_df[col], bins=bins)
        records.append(
            {
                "feature": col,
                "csi_value": round(csi_val, 6) if not np.isnan(csi_val) else None,
                "stability": classify_psi(csi_val, config),
            }
        )

    return pd.DataFrame(records)


def compute_kpi_trends(
    df: pd.DataFrame,
    period_col: str = "period",
    bad_flag_col: str = "bad_flag",
    approved_col: Optional[str] = "approved",
    utilization_col: Optional[str] = "utilization_rate",
    limit_col: Optional[str] = "final_limit",
) -> pd.DataFrame:
    """Aggregate portfolio KPIs by period.

    Returns a DataFrame indexed by period with: bad_rate, approval_rate,
    avg_utilization, avg_limit, customer_count.
    """
    agg: Dict = {bad_flag_col: ["count", "mean"]}
    if approved_col and approved_col in df.columns:
        agg[approved_col] = "mean"
    if utilization_col and utilization_col in df.columns:
        agg[utilization_col] = "mean"
    if limit_col and limit_col in df.columns:
        agg[limit_col] = "mean"

    trend = df.groupby(period_col).agg(agg).reset_index()
    trend.columns = [
        "_".join(c).strip("_") if isinstance(c, tuple) else c
        for c in trend.columns
    ]

    rename = {
        f"{bad_flag_col}_count": "customer_count",
        f"{bad_flag_col}_mean": "bad_rate",
        f"{approved_col}_mean": "approval_rate",
        f"{utilization_col}_mean": "avg_utilization",
        f"{limit_col}_mean": "avg_limit",
    }
    trend = trend.rename(columns={k: v for k, v in rename.items() if k in trend.columns})

    return trend.sort_values(period_col).reset_index(drop=True)


def detect_kpi_alerts(
    trend_df: pd.DataFrame,
    baseline_periods: int = 3,
    config: CreditLimitConfig = None,
) -> List[Dict]:
    """Detect KPI breaches relative to the baseline (first N periods).

    Returns a list of alert dicts with: metric, period, baseline_value,
    current_value, change, alert_type, severity.
    """
    if config is None:
        config = DEFAULT_CONFIG

    rules = config.portfolio_monitoring.kpi_alert_rules
    alerts: List[Dict] = []

    if len(trend_df) <= baseline_periods:
        return alerts

    baseline = trend_df.iloc[:baseline_periods]
    monitoring = trend_df.iloc[baseline_periods:]

    for metric in ("bad_rate", "approval_rate", "avg_utilization"):
        if metric not in trend_df.columns:
            continue
        rule = rules.get(metric, {})
        baseline_val = float(baseline[metric].mean())
        if baseline_val == 0:
            continue

        for _, row in monitoring.iterrows():
            current_val = float(row[metric])
            relative_change_pct = (current_val - baseline_val) / baseline_val * 100

            triggered = False
            if metric == "bad_rate":
                if rule.get("relative_increase_pct") and relative_change_pct > rule["relative_increase_pct"]:
                    triggered = True
                if rule.get("absolute_increase") and (current_val - baseline_val) > rule["absolute_increase"]:
                    triggered = True
            elif metric == "approval_rate":
                if rule.get("relative_decrease_pct") and relative_change_pct < -rule["relative_decrease_pct"]:
                    triggered = True
            elif metric == "avg_utilization":
                if rule.get("absolute_increase") and (current_val - baseline_val) > rule["absolute_increase"]:
                    triggered = True

            if triggered:
                severity = "high" if abs(relative_change_pct) > 40 else "medium"
                alerts.append(
                    {
                        "metric": metric,
                        "period": row.get("period", ""),
                        "baseline_value": round(baseline_val, 4),
                        "current_value": round(current_val, 4),
                        "relative_change_pct": round(relative_change_pct, 2),
                        "severity": severity,
                    }
                )

    return alerts


def run_portfolio_monitoring(
    base_df: pd.DataFrame,
    current_df: pd.DataFrame,
    score_col: str = "score",
    feature_cols: Optional[List[str]] = None,
    period_col: str = "period",
    bad_flag_col: str = "bad_flag",
    utilization_col: str = "utilization_rate",
    limit_col: str = "final_limit",
    config: CreditLimitConfig = None,
) -> Tuple[float, pd.DataFrame, pd.DataFrame, pd.DataFrame, List[Dict], Dict]:
    """Run the full portfolio monitoring workflow.

    Parameters
    ----------
    base_df    : Reference period data (used for PSI/CSI baseline).
    current_df : Current period data to compare against base.

    Returns
    -------
    (psi_score, psi_detail_df, csi_df, trend_df, alerts, summary)
    """
    if config is None:
        config = DEFAULT_CONFIG

    psi_score = np.nan
    psi_detail_df = pd.DataFrame()
    if score_col in base_df.columns and score_col in current_df.columns:
        psi_score, psi_detail_df = compute_psi(
            base_df[score_col],
            current_df[score_col],
            bins=config.portfolio_monitoring.psi_bins,
        )

    csi_df = pd.DataFrame()
    if feature_cols:
        csi_df = compute_csi(base_df, current_df, feature_cols, config=config)

    combined = pd.concat(
        [base_df.assign(**{period_col: "base"}), current_df]
        if period_col not in current_df.columns
        else [base_df.assign(**{period_col: "base"}), current_df],
        ignore_index=True,
    )

    if period_col in current_df.columns:
        combined = pd.concat([base_df, current_df], ignore_index=True)

    trend_df = pd.DataFrame()
    alerts: List[Dict] = []
    if period_col in combined.columns and bad_flag_col in combined.columns:
        trend_df = compute_kpi_trends(
            combined,
            period_col=period_col,
            bad_flag_col=bad_flag_col,
            utilization_col=utilization_col if utilization_col in combined.columns else None,
            limit_col=limit_col if limit_col in combined.columns else None,
        )
        alerts = detect_kpi_alerts(trend_df, config=config)

    summary: Dict = {
        "psi_score": round(float(psi_score), 4) if not np.isnan(psi_score) else None,
        "psi_stability": classify_psi(psi_score, config) if not np.isnan(psi_score) else "unknown",
        "features_monitored": len(csi_df) if len(csi_df) else 0,
        "features_with_significant_shift": int(
            (csi_df["stability"] == "significant_shift").sum()
        ) if len(csi_df) else 0,
        "total_alerts": len(alerts),
        "high_severity_alerts": sum(1 for a in alerts if a.get("severity") == "high"),
    }

    return psi_score, psi_detail_df, csi_df, trend_df, alerts, summary


def generate_monitoring_report(
    psi_score: float,
    psi_detail_df: pd.DataFrame,
    csi_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    alerts: List[Dict],
    summary: Dict,
    config: CreditLimitConfig = None,
) -> List[str]:
    """Render a markdown portfolio monitoring report."""
    if config is None:
        config = DEFAULT_CONFIG

    psi_label = classify_psi(psi_score if psi_score is not None else np.nan, config)

    lines: List[str] = [
        "# Portfolio Monitoring Report",
        "",
        "## Summary",
        f"- Score PSI: {summary.get('psi_score', 'N/A')} ({psi_label})",
        f"- Features monitored (CSI): {summary['features_monitored']}",
        f"- Features with significant shift: **{summary['features_with_significant_shift']}**",
        f"- Total KPI alerts: {summary['total_alerts']}",
        f"- High-severity alerts: **{summary['high_severity_alerts']}**",
        "",
    ]

    if len(psi_detail_df):
        lines += [
            "## Score PSI Detail",
            "",
            "| Bin | Base % | Current % | PSI Contribution |",
            "|-----|--------|-----------|-----------------|",
        ]
        for _, row in psi_detail_df.iterrows():
            lines.append(
                f"| {row['bin']} | {row['base_pct']:.3f} | {row['current_pct']:.3f} "
                f"| {row['psi_contribution']:.5f} |"
            )
        lines.append("")

    if len(csi_df):
        lines += [
            "## Characteristic Stability Index (CSI)",
            "",
            "| Feature | CSI | Stability |",
            "|---------|-----|-----------|",
        ]
        for _, row in csi_df.iterrows():
            csi_val = f"{row['csi_value']:.5f}" if row["csi_value"] is not None else "N/A"
            lines.append(f"| {row['feature']} | {csi_val} | {row['stability']} |")
        lines.append("")

    if len(alerts):
        lines += [
            "## KPI Alerts",
            "",
            "| Metric | Period | Baseline | Current | Change % | Severity |",
            "|--------|--------|----------|---------|----------|----------|",
        ]
        for alert in alerts:
            lines.append(
                f"| {alert['metric']} | {alert['period']} | {alert['baseline_value']:.4f} "
                f"| {alert['current_value']:.4f} | {alert['relative_change_pct']:+.1f}% "
                f"| **{alert['severity']}** |"
            )
        lines.append("")

    psi_action = {
        "stable": "No action needed. Continue regular monitoring.",
        "moderate_shift": "Investigate score distribution shift. Check input feature drift and model recalibration need.",
        "significant_shift": "**Immediate action required.** Score distribution has shifted significantly. Suspend auto-decisions pending model review.",
        "unknown": "PSI could not be computed. Check score column availability.",
    }
    lines += [
        "## Recommended Action",
        f"- Score PSI ({psi_label}): {psi_action.get(psi_label, 'Review required.')}",
        "",
    ]

    return lines
