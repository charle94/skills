"""Vintage cohort analysis for credit portfolio performance tracking.

A vintage is a cohort of loans booked in the same calendar period (month or quarter).
This module builds cumulative bad-rate curves across vintages and months-on-book (MOB),
detects deteriorating cohorts, and projects mature bad rates for immature cohorts.

Input: one row per loan × observation snapshot (long format).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CreditLimitConfig, DEFAULT_CONFIG

REQUIRED_COLUMNS = ["customer_id", "origination_month", "mob", "dpd"]


def derive_ever_bad(
    df: pd.DataFrame,
    dpd_col: str = "dpd",
    dpd_threshold: int = 30,
    bad_flag_col: str = "bad_flag",
) -> pd.DataFrame:
    """Add an ever-bad indicator: 1 if dpd >= threshold at this MOB observation."""
    working = df.copy()
    if bad_flag_col not in working.columns:
        working[bad_flag_col] = (working[dpd_col] >= dpd_threshold).astype(int)
    return working


def build_vintage_matrix(
    df: pd.DataFrame,
    cohort_col: str = "origination_month",
    mob_col: str = "mob",
    bad_flag_col: str = "bad_flag",
    loan_amount_col: Optional[str] = "loan_amount",
    min_cohort_obs: int = 20,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build vintage matrices for bad rate, customer count, and total loan amount.

    For each (cohort, MOB), we compute the fraction of accounts that have
    ever reached the bad threshold by that MOB.  This is a cumulative measure:
    an account that was bad at MOB 3 is still counted as bad at MOB 6+.

    Returns
    -------
    bad_rate_matrix : pivot(cohort × mob → cumulative bad rate)
    count_matrix    : pivot(cohort × mob → account count observed at that MOB)
    amount_matrix   : pivot(cohort × mob → total original loan amount), or empty
    """
    working = df.copy()

    cohort_mob = (
        working.groupby([cohort_col, mob_col], observed=True)
        .agg(
            customer_count=(bad_flag_col, "count"),
            bad_count=(bad_flag_col, "sum"),
        )
        .reset_index()
    )
    cohort_mob["bad_rate"] = cohort_mob["bad_count"] / cohort_mob["customer_count"]

    bad_rate_matrix = cohort_mob.pivot(
        index=cohort_col, columns=mob_col, values="bad_rate"
    )
    count_matrix = cohort_mob.pivot(
        index=cohort_col, columns=mob_col, values="customer_count"
    )

    # Drop cohorts with consistently insufficient data across all MOB
    valid_cohorts = count_matrix[count_matrix.max(axis=1) >= min_cohort_obs].index
    bad_rate_matrix = bad_rate_matrix.loc[bad_rate_matrix.index.isin(valid_cohorts)]
    count_matrix = count_matrix.loc[count_matrix.index.isin(valid_cohorts)]

    if loan_amount_col and loan_amount_col in working.columns:
        amount_agg = (
            working.groupby([cohort_col, mob_col], observed=True)[loan_amount_col]
            .sum()
            .reset_index()
        )
        amount_matrix = amount_agg.pivot(
            index=cohort_col, columns=mob_col, values=loan_amount_col
        )
        amount_matrix = amount_matrix.loc[amount_matrix.index.isin(valid_cohorts)]
    else:
        amount_matrix = pd.DataFrame()

    return bad_rate_matrix, count_matrix, amount_matrix


def compute_reference_curve(
    bad_rate_matrix: pd.DataFrame,
    reference_cohort_count: int = 4,
) -> Tuple[pd.Series, pd.Series]:
    """Compute mean and standard deviation of the reference (oldest) cohorts.

    The oldest cohorts are the most mature and serve as the benchmark.
    """
    sorted_cohorts = sorted(bad_rate_matrix.index)
    ref_cohorts = sorted_cohorts[:reference_cohort_count]
    ref_df = bad_rate_matrix.loc[ref_cohorts]
    return ref_df.mean(), ref_df.std()


def detect_vintage_deterioration(
    bad_rate_matrix: pd.DataFrame,
    reference_mean: pd.Series,
    reference_std: pd.Series,
    z_threshold: float = 1.5,
) -> pd.DataFrame:
    """Return a z-score matrix indicating how far each cohort deviates from reference.

    Positive z-score → cohort is worse than reference at that MOB.
    A cohort is flagged as deteriorating if its z-score exceeds z_threshold
    in at least one MOB column with sufficient reference data.
    """
    z_matrix = (bad_rate_matrix - reference_mean) / reference_std.replace(0, np.nan)

    deteriorating_flags = (z_matrix > z_threshold).any(axis=1)
    z_matrix["is_deteriorating"] = deteriorating_flags
    z_matrix["max_z_score"] = z_matrix.drop(columns="is_deteriorating").max(axis=1).round(3)

    return z_matrix


def project_final_bad_rate(
    bad_rate_matrix: pd.DataFrame,
    reference_mean: pd.Series,
    target_mob: int = 12,
    current_mob_col: Optional[int] = None,
) -> pd.DataFrame:
    """Project the mature bad rate for immature cohorts using seasoning ratios.

    Method: for each immature cohort at its latest available MOB, compute the
    ratio (reference_rate_at_target_mob / reference_rate_at_observed_mob).
    Apply this seasoning factor to the cohort's current bad rate.

    Returns a DataFrame with: latest_mob, latest_bad_rate, projection_factor,
    projected_bad_rate, and projection_confidence.
    """
    if target_mob not in reference_mean.index:
        available = [m for m in reference_mean.index if m <= target_mob]
        if not available:
            raise ValueError(f"target_mob {target_mob} not in reference curve range.")
        target_mob = max(available)

    target_ref = reference_mean[target_mob]
    records = []

    for cohort in bad_rate_matrix.index:
        row = bad_rate_matrix.loc[cohort].dropna()
        if row.empty:
            continue
        latest_mob = int(row.index.max())
        latest_rate = float(row[latest_mob])

        if latest_mob >= target_mob:
            projected_rate = latest_rate
            factor = 1.0
            confidence = "actual"
        else:
            ref_at_latest = reference_mean.get(latest_mob, np.nan)
            if pd.isna(ref_at_latest) or ref_at_latest == 0:
                factor = np.nan
                projected_rate = np.nan
                confidence = "insufficient_reference"
            else:
                factor = float(target_ref / ref_at_latest)
                projected_rate = latest_rate * factor
                obs_count = int(row.count())
                confidence = "high" if obs_count >= 6 else ("medium" if obs_count >= 3 else "low")

        records.append(
            {
                "origination_month": cohort,
                "latest_mob": latest_mob,
                "latest_bad_rate": round(latest_rate, 4),
                "projection_factor": round(factor, 4) if not np.isnan(factor) else None,
                "projected_bad_rate_at_mob": round(projected_rate, 4) if not np.isnan(projected_rate) else None,
                "target_mob": target_mob,
                "confidence": confidence,
            }
        )

    return pd.DataFrame(records)


def generate_vintage_summary(
    bad_rate_matrix: pd.DataFrame,
    z_matrix: pd.DataFrame,
    projection_df: pd.DataFrame,
    reference_mean: pd.Series,
) -> Dict:
    """Produce a compact dictionary summary for pipeline reporting."""
    total_cohorts = len(bad_rate_matrix)
    deteriorating = int(z_matrix["is_deteriorating"].sum()) if "is_deteriorating" in z_matrix.columns else 0
    worst_cohort = (
        z_matrix["max_z_score"].idxmax() if "max_z_score" in z_matrix.columns and total_cohorts > 0 else None
    )

    target_mob = int(projection_df["target_mob"].iloc[0]) if len(projection_df) else None
    projected_col = "projected_bad_rate_at_mob"
    projected_rates = (
        projection_df[projected_col].dropna()
        if len(projection_df) and projected_col in projection_df.columns
        else pd.Series(dtype=float)
    )

    summary: Dict = {
        "total_cohorts": total_cohorts,
        "deteriorating_cohorts": deteriorating,
        "worst_cohort": str(worst_cohort) if worst_cohort is not None else None,
        "mob_range": list(bad_rate_matrix.columns.astype(int).tolist()) if len(bad_rate_matrix.columns) else [],
        "reference_curve_mobs": sorted(reference_mean.dropna().index.tolist()),
        "projection_target_mob": target_mob,
        "avg_projected_bad_rate": round(float(projected_rates.mean()), 4) if len(projected_rates) else None,
        "max_projected_bad_rate": round(float(projected_rates.max()), 4) if len(projected_rates) else None,
        "high_confidence_projections": int(
            (projection_df["confidence"] == "high").sum()
        ) if len(projection_df) and "confidence" in projection_df.columns else 0,
    }
    return summary


def generate_vintage_report(
    bad_rate_matrix: pd.DataFrame,
    z_matrix: pd.DataFrame,
    projection_df: pd.DataFrame,
    summary: Dict,
) -> List[str]:
    """Render a markdown vintage analysis report."""
    lines: List[str] = [
        "# Vintage Analysis Report",
        "",
        "## Summary",
        f"- Total cohorts: {summary['total_cohorts']}",
        f"- **Deteriorating cohorts: {summary['deteriorating_cohorts']}**",
        f"- Worst cohort: {summary['worst_cohort']}",
        f"- MOB range: {summary['mob_range']}",
        "",
    ]

    if len(bad_rate_matrix):
        # Format as CSV-style table for markdown compatibility without tabulate
        header = "| cohort | " + " | ".join(str(c) for c in bad_rate_matrix.columns) + " |"
        separator = "|--------|" + "|".join(["--------"] * len(bad_rate_matrix.columns)) + "|"
        lines += [
            "## Vintage Bad Rate Matrix (cumulative bad rate by MOB)",
            "",
            header,
            separator,
        ]
        for cohort, row in bad_rate_matrix.round(4).iterrows():
            values = " | ".join(str(v) if pd.notna(v) else "-" for v in row)
            lines.append(f"| {cohort} | {values} |")
        lines.append("")

    deter_cohorts = (
        z_matrix[z_matrix["is_deteriorating"]].index.tolist()
        if "is_deteriorating" in z_matrix.columns else []
    )
    if deter_cohorts:
        lines += [
            f"## Deteriorating Cohorts (z-score > threshold)",
            "",
            "| Cohort | Max Z-Score |",
            "|--------|------------|",
        ]
        for cohort in deter_cohorts:
            z = z_matrix.loc[cohort, "max_z_score"]
            lines.append(f"| {cohort} | {z:.2f} |")
        lines.append("")

    if len(projection_df):
        lines += [
            f"## Projected Mature Bad Rate (MOB {summary['projection_target_mob']})",
            "",
            "| Cohort | Latest MOB | Latest BR | Projection Factor | Projected BR | Confidence |",
            "|--------|-----------|-----------|------------------|-------------|------------|",
        ]
        for _, row in projection_df.iterrows():
            lines.append(
                f"| {row['origination_month']} | {row['latest_mob']} | {row['latest_bad_rate']:.3f} "
                f"| {row['projection_factor'] or 'N/A'} | {row['projected_bad_rate_at_mob'] or 'N/A'} "
                f"| {row['confidence']} |"
            )
        lines.append("")

    lines += [
        "## Caveats",
        "- Projections assume seasoning pattern of reference cohorts applies to new cohorts.",
        "- Cohorts flagged as deteriorating require root-cause analysis before policy action.",
        "- Channel, product, or scoring changes between cohorts can invalidate projections.",
        "",
    ]
    return lines


def run_vintage_analysis(
    df: pd.DataFrame,
    cohort_col: str = "origination_month",
    mob_col: str = "mob",
    dpd_col: str = "dpd",
    bad_flag_col: str = "bad_flag",
    loan_amount_col: Optional[str] = "loan_amount",
    dpd_threshold: int = 30,
    target_mob: int = 12,
    config: CreditLimitConfig = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict]:
    """Run the full vintage analysis workflow.

    Returns
    -------
    (bad_rate_matrix, z_matrix, projection_df, count_matrix, summary)
    """
    if config is None:
        config = DEFAULT_CONFIG

    va_cfg = config.vintage_analysis
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        if dpd_col in df.columns and bad_flag_col not in df.columns:
            pass
        elif bad_flag_col not in df.columns:
            raise ValueError(f"vintage_analysis requires columns: {missing}")

    working = derive_ever_bad(df, dpd_col=dpd_col, dpd_threshold=dpd_threshold, bad_flag_col=bad_flag_col)

    bad_rate_matrix, count_matrix, amount_matrix = build_vintage_matrix(
        working,
        cohort_col=cohort_col,
        mob_col=mob_col,
        bad_flag_col=bad_flag_col,
        loan_amount_col=loan_amount_col,
        min_cohort_obs=va_cfg.min_cohort_observations,
    )

    reference_mean, reference_std = compute_reference_curve(
        bad_rate_matrix,
        reference_cohort_count=va_cfg.reference_cohort_count,
    )

    z_matrix = detect_vintage_deterioration(
        bad_rate_matrix,
        reference_mean,
        reference_std,
        z_threshold=va_cfg.deterioration_z_threshold,
    )

    projection_df = project_final_bad_rate(
        bad_rate_matrix,
        reference_mean,
        target_mob=target_mob,
    )

    summary = generate_vintage_summary(bad_rate_matrix, z_matrix, projection_df, reference_mean)

    return bad_rate_matrix, z_matrix, projection_df, count_matrix, summary
