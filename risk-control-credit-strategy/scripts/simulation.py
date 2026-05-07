"""Champion/Challenger simulation engine.

Given the same population, run two complete strategies (current = champion,
proposed = challenger) end-to-end and compare:

- Limit distribution (mean, median, percentiles)
- Approval and floor/cap hit rates
- Expected loss (E[L] = limit × utilization × PD × LGD)
- Expected revenue (limit × utilization × interest_rate)
- Expected profit (revenue - EL - op_cost)
- Per-segment delta tables

This is the gating step before any policy change is rolled out. It does NOT
require a control group — it simulates outcomes deterministically given the
risk inputs that already exist in the data.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import CreditLimitConfig, DEFAULT_CONFIG
from limit_calculation import calculate_batch_limits
from risk_adjustment import adjust_batch_limits


@dataclass
class StrategyEconomics:
    """Economic assumptions used to score policies during simulation."""
    interest_rate: float = 0.18
    lgd: float = 0.60
    op_cost_ratio: float = 0.02
    default_utilization_rate: float = 0.55  # used when missing


@dataclass
class StrategyMetrics:
    """Compact metrics for one policy outcome on the same population."""
    label: str
    customer_count: int
    approved_count: int
    approval_rate: float
    avg_final_limit: float
    median_final_limit: float
    p25_final_limit: float
    p75_final_limit: float
    floor_hit_rate: float
    cap_hit_rate: float
    affordability_block_rate: float
    avg_pd: float
    expected_loss_total: float
    expected_revenue_total: float
    expected_profit_total: float
    expected_profit_per_customer: float
    risk_level_distribution: Dict[str, int]


def _estimate_pd(row: pd.Series) -> float:
    """Best-effort PD estimate.

    Priority:
      1. explicit pd_estimate column
      2. explicit pd column
      3. heuristic from risk_score (assumed higher score = lower PD)
    """
    if "pd_estimate" in row.index and pd.notna(row["pd_estimate"]):
        return float(np.clip(row["pd_estimate"], 0.001, 0.95))
    if "pd" in row.index and pd.notna(row["pd"]):
        return float(np.clip(row["pd"], 0.001, 0.95))
    score = row.get("risk_score", 50)
    if pd.isna(score):
        return 0.10
    if score > 1.0:
        score = score / 100.0
    return float(np.clip(1.0 - score, 0.001, 0.95))


def _compute_metrics(
    df: pd.DataFrame,
    label: str,
    economics: StrategyEconomics,
) -> Tuple[StrategyMetrics, pd.DataFrame]:
    """Compute strategy metrics and return the enriched per-customer DataFrame."""
    enriched = df.copy()

    if "utilization_rate" in enriched.columns:
        utilization = enriched["utilization_rate"].fillna(economics.default_utilization_rate)
    else:
        utilization = pd.Series(
            economics.default_utilization_rate, index=enriched.index, name="utilization_rate"
        )
    enriched["utilization_rate_used"] = utilization

    pd_series = enriched.apply(_estimate_pd, axis=1)
    enriched["pd_used"] = pd_series

    final_limits = enriched["final_limit"].fillna(0.0)
    exposure = final_limits * utilization
    enriched["expected_exposure"] = exposure
    enriched["expected_loss"] = exposure * pd_series * economics.lgd
    enriched["expected_revenue"] = exposure * economics.interest_rate
    enriched["expected_op_cost"] = exposure * economics.op_cost_ratio
    enriched["expected_profit"] = (
        enriched["expected_revenue"] - enriched["expected_loss"] - enriched["expected_op_cost"]
    )

    approved_mask = final_limits > 0
    approved_count = int(approved_mask.sum())
    customer_count = int(len(enriched))

    constraint = enriched.get("applied_constraint", pd.Series(dtype=str))
    floor_hit_rate = (
        float((constraint == "floor").mean()) if len(constraint) else 0.0
    )
    cap_hit_rate = float((constraint == "cap").mean()) if len(constraint) else 0.0
    block_rate = (
        float((constraint == "affordability_block").mean()) if len(constraint) else 0.0
    )

    risk_level_distribution: Dict[str, int] = {}
    if "risk_level" in enriched.columns:
        risk_level_distribution = enriched["risk_level"].value_counts().to_dict()

    quantiles = final_limits[approved_mask].quantile([0.25, 0.5, 0.75]) if approved_count else pd.Series([0, 0, 0], index=[0.25, 0.5, 0.75])

    metrics = StrategyMetrics(
        label=label,
        customer_count=customer_count,
        approved_count=approved_count,
        approval_rate=round(approved_count / customer_count, 4) if customer_count else 0.0,
        avg_final_limit=round(float(final_limits[approved_mask].mean()) if approved_count else 0.0, 2),
        median_final_limit=round(float(quantiles.loc[0.5]), 2),
        p25_final_limit=round(float(quantiles.loc[0.25]), 2),
        p75_final_limit=round(float(quantiles.loc[0.75]), 2),
        floor_hit_rate=round(floor_hit_rate, 4),
        cap_hit_rate=round(cap_hit_rate, 4),
        affordability_block_rate=round(block_rate, 4),
        avg_pd=round(float(pd_series.mean()), 4),
        expected_loss_total=round(float(enriched["expected_loss"].sum()), 2),
        expected_revenue_total=round(float(enriched["expected_revenue"].sum()), 2),
        expected_profit_total=round(float(enriched["expected_profit"].sum()), 2),
        expected_profit_per_customer=round(
            float(enriched["expected_profit"].sum() / customer_count) if customer_count else 0.0, 2
        ),
        risk_level_distribution=risk_level_distribution,
    )

    return metrics, enriched


def _run_full_strategy(
    df: pd.DataFrame,
    config: CreditLimitConfig,
) -> pd.DataFrame:
    """Run base_limit + risk_adjustment as one combined pass on a copy of df."""
    base_df = calculate_batch_limits(df, config=config)

    merge_keys = ["customer_id", "risk_score", "dti"]
    optional_keys = [k for k in ("utilization_rate", "pd_estimate", "pd") if k in df.columns]
    merged = df[merge_keys + optional_keys].merge(
        base_df[["customer_id", "base_limit", "affordability_status", "floor_eligible"]],
        on="customer_id",
        how="left",
    )

    risk_df = adjust_batch_limits(merged, config=config)

    output = risk_df.merge(merged[["customer_id"] + optional_keys], on="customer_id", how="left")
    return output


def run_simulation(
    df: pd.DataFrame,
    champion_config: CreditLimitConfig,
    challenger_config: CreditLimitConfig,
    economics: Optional[StrategyEconomics] = None,
    champion_label: str = "champion",
    challenger_label: str = "challenger",
) -> Tuple[StrategyMetrics, StrategyMetrics, pd.DataFrame, Dict[str, Any]]:
    """Run a champion/challenger simulation and return comparable metrics.

    Parameters
    ----------
    df                 : Population (must contain monthly_income, risk_score, dti, etc.)
    champion_config    : Current production policy.
    challenger_config  : Proposed policy.
    economics          : Cost / revenue assumptions.

    Returns
    -------
    (champion_metrics, challenger_metrics, side_by_side_df, summary_dict)
    """
    if economics is None:
        economics = StrategyEconomics()

    champion_outcome = _run_full_strategy(df, champion_config)
    challenger_outcome = _run_full_strategy(df, challenger_config)

    champion_metrics, champion_enriched = _compute_metrics(
        champion_outcome, champion_label, economics
    )
    challenger_metrics, challenger_enriched = _compute_metrics(
        challenger_outcome, challenger_label, economics
    )

    side_by_side = champion_enriched[
        ["customer_id", "risk_level", "final_limit", "expected_loss", "expected_profit"]
    ].rename(
        columns={
            "final_limit": f"final_limit_{champion_label}",
            "expected_loss": f"expected_loss_{champion_label}",
            "expected_profit": f"expected_profit_{champion_label}",
        }
    ).merge(
        challenger_enriched[
            ["customer_id", "final_limit", "expected_loss", "expected_profit"]
        ].rename(
            columns={
                "final_limit": f"final_limit_{challenger_label}",
                "expected_loss": f"expected_loss_{challenger_label}",
                "expected_profit": f"expected_profit_{challenger_label}",
            }
        ),
        on="customer_id",
        how="outer",
    )

    side_by_side["limit_delta"] = (
        side_by_side[f"final_limit_{challenger_label}"]
        - side_by_side[f"final_limit_{champion_label}"]
    )
    side_by_side["profit_delta"] = (
        side_by_side[f"expected_profit_{challenger_label}"]
        - side_by_side[f"expected_profit_{champion_label}"]
    )

    delta_summary = {
        "approval_rate_delta": round(
            challenger_metrics.approval_rate - champion_metrics.approval_rate, 4
        ),
        "avg_final_limit_delta": round(
            challenger_metrics.avg_final_limit - champion_metrics.avg_final_limit, 2
        ),
        "expected_loss_total_delta": round(
            challenger_metrics.expected_loss_total - champion_metrics.expected_loss_total, 2
        ),
        "expected_revenue_total_delta": round(
            challenger_metrics.expected_revenue_total - champion_metrics.expected_revenue_total, 2
        ),
        "expected_profit_total_delta": round(
            challenger_metrics.expected_profit_total - champion_metrics.expected_profit_total, 2
        ),
        "expected_profit_per_customer_delta": round(
            challenger_metrics.expected_profit_per_customer
            - champion_metrics.expected_profit_per_customer, 2
        ),
    }

    decision = _make_simulation_decision(champion_metrics, challenger_metrics, delta_summary)

    summary = {
        "champion": _metrics_to_dict(champion_metrics),
        "challenger": _metrics_to_dict(challenger_metrics),
        "deltas": delta_summary,
        "decision": decision,
        "economics": {
            "interest_rate": economics.interest_rate,
            "lgd": economics.lgd,
            "op_cost_ratio": economics.op_cost_ratio,
            "default_utilization_rate": economics.default_utilization_rate,
        },
    }

    return champion_metrics, challenger_metrics, side_by_side, summary


def _metrics_to_dict(m: StrategyMetrics) -> Dict[str, Any]:
    return {
        "label": m.label,
        "customer_count": m.customer_count,
        "approved_count": m.approved_count,
        "approval_rate": m.approval_rate,
        "avg_final_limit": m.avg_final_limit,
        "median_final_limit": m.median_final_limit,
        "p25_final_limit": m.p25_final_limit,
        "p75_final_limit": m.p75_final_limit,
        "floor_hit_rate": m.floor_hit_rate,
        "cap_hit_rate": m.cap_hit_rate,
        "affordability_block_rate": m.affordability_block_rate,
        "avg_pd": m.avg_pd,
        "expected_loss_total": m.expected_loss_total,
        "expected_revenue_total": m.expected_revenue_total,
        "expected_profit_total": m.expected_profit_total,
        "expected_profit_per_customer": m.expected_profit_per_customer,
        "risk_level_distribution": m.risk_level_distribution,
    }


def _make_simulation_decision(
    champion: StrategyMetrics,
    challenger: StrategyMetrics,
    deltas: Dict[str, float],
) -> Dict[str, Any]:
    """Apply rule-of-thumb gating to the challenger.

    Returns a dict with `recommendation` and `reasons` so downstream consumers
    can render or further customize.
    """
    reasons: List[str] = []
    recommendation = "promote_to_champion_challenger_test"

    if champion.expected_profit_total > 0 and deltas["expected_profit_total_delta"] < 0:
        recommendation = "reject"
        reasons.append("challenger reduces expected profit vs. champion")

    el_increase = deltas["expected_loss_total_delta"]
    if champion.expected_loss_total > 0 and el_increase > 0:
        relative_el_increase = el_increase / max(champion.expected_loss_total, 1)
        if relative_el_increase > 0.20:
            recommendation = "reject"
            reasons.append(
                f"challenger increases expected loss by {relative_el_increase:.1%} (>20% threshold)"
            )

    approval_drop = -deltas["approval_rate_delta"]
    if approval_drop > 0.10:
        recommendation = "reject"
        reasons.append(f"challenger drops approval rate by {approval_drop:.1%} (>10% threshold)")

    if challenger.affordability_block_rate > champion.affordability_block_rate + 0.05:
        recommendation = "investigate"
        reasons.append("affordability block rate jumped >5pp; check capacity calculation")

    if not reasons:
        if deltas["expected_profit_total_delta"] >= 0:
            reasons.append("challenger improves or matches expected profit and stays within risk guardrails")
        else:
            reasons.append("changes are neutral or trade-offs are within tolerance")

    return {
        "recommendation": recommendation,
        "reasons": reasons,
    }


def generate_simulation_report(summary: Dict[str, Any]) -> List[str]:
    """Render a markdown report from the simulation summary dict."""
    champion = summary["champion"]
    challenger = summary["challenger"]
    deltas = summary["deltas"]
    decision = summary["decision"]

    lines = [
        "# Champion / Challenger Simulation Report",
        "",
        "## Decision",
        f"- **Recommendation: {decision['recommendation']}**",
        "",
        "Reasons:",
    ]
    for r in decision["reasons"]:
        lines.append(f"- {r}")
    lines.append("")

    lines += [
        "## Side-by-Side Metrics",
        "",
        "| Metric | Champion | Challenger | Delta |",
        "|--------|----------|------------|-------|",
        f"| Customers | {champion['customer_count']:,} | {challenger['customer_count']:,} | - |",
        f"| Approval rate | {champion['approval_rate']:.2%} | {challenger['approval_rate']:.2%} "
        f"| {deltas['approval_rate_delta']:+.4f} |",
        f"| Avg final limit | {champion['avg_final_limit']:,.2f} | {challenger['avg_final_limit']:,.2f} "
        f"| {deltas['avg_final_limit_delta']:+,.2f} |",
        f"| Median limit | {champion['median_final_limit']:,.2f} | {challenger['median_final_limit']:,.2f} | - |",
        f"| Floor hit rate | {champion['floor_hit_rate']:.2%} | {challenger['floor_hit_rate']:.2%} | - |",
        f"| Cap hit rate | {champion['cap_hit_rate']:.2%} | {challenger['cap_hit_rate']:.2%} | - |",
        f"| Affordability block rate | {champion['affordability_block_rate']:.2%} "
        f"| {challenger['affordability_block_rate']:.2%} | - |",
        f"| Avg PD | {champion['avg_pd']:.4f} | {challenger['avg_pd']:.4f} | - |",
        f"| Expected loss total | {champion['expected_loss_total']:,.2f} "
        f"| {challenger['expected_loss_total']:,.2f} "
        f"| {deltas['expected_loss_total_delta']:+,.2f} |",
        f"| Expected revenue total | {champion['expected_revenue_total']:,.2f} "
        f"| {challenger['expected_revenue_total']:,.2f} "
        f"| {deltas['expected_revenue_total_delta']:+,.2f} |",
        f"| **Expected profit total** | **{champion['expected_profit_total']:,.2f}** "
        f"| **{challenger['expected_profit_total']:,.2f}** "
        f"| **{deltas['expected_profit_total_delta']:+,.2f}** |",
        f"| Expected profit per customer | {champion['expected_profit_per_customer']:,.2f} "
        f"| {challenger['expected_profit_per_customer']:,.2f} "
        f"| {deltas['expected_profit_per_customer_delta']:+,.2f} |",
        "",
        "## Caveats",
        "- Outcomes are deterministic given current PD estimates; they do NOT replace a real A/B test.",
        "- Expected loss assumes utilization × PD × LGD; revisit utilization assumption per product.",
        "- Always cap the rollout: start with 5–10% of traffic before broad release.",
        "",
    ]

    return lines
