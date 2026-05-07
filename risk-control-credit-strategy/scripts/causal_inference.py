"""Causal and quasi-causal evaluation for limit policy changes."""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from dataclasses import dataclass
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from config import CreditLimitConfig, DEFAULT_CONFIG


REQUIRED_COLUMNS = ["customer_id", "treatment", "outcome", "limit_before", "limit_after"]


@dataclass
class CausalInferenceResult:
    """Top-level output from policy effect evaluation."""
    ate: float
    att: float
    lift: float
    ks_statistic: float
    ks_pvalue: float
    profit_simulation: Dict
    confidence_interval_95: Tuple[float, float]
    sample_sizes: Dict[str, int]
    default_rates: Dict[str, float]
    balance_diagnostics: Dict[str, Dict[str, float]]
    overlap_diagnostics: Dict[str, float]
    evidence_tier: str


def standardized_mean_difference(treated: pd.Series, control: pd.Series) -> float:
    """Compute standardized mean difference for one covariate."""
    treated_std = treated.std(ddof=1)
    control_std = control.std(ddof=1)
    pooled_std = np.sqrt(((treated_std ** 2) + (control_std ** 2)) / 2)
    if pooled_std == 0 or np.isnan(pooled_std):
        return 0.0
    return float((treated.mean() - control.mean()) / pooled_std)


def compute_balance_diagnostics(
    df: pd.DataFrame,
    treatment_col: str,
    covariate_cols: List[str],
    treated_indices: List[int] | None = None,
    control_indices: List[int] | None = None,
) -> Dict[str, float]:
    """Compute covariate balance diagnostics using standardized mean differences."""
    working_df = df if treated_indices is None else df.loc[treated_indices + control_indices]
    if treated_indices is None:
        treated_df = working_df[working_df[treatment_col] == 1]
        control_df = working_df[working_df[treatment_col] == 0]
    else:
        treated_df = df.loc[treated_indices]
        control_df = df.loc[control_indices]

    diagnostics: Dict[str, float] = {}
    for column in covariate_cols:
        if column not in df.columns:
            continue
        diagnostics[f"smd_{column}"] = round(
            standardized_mean_difference(treated_df[column], control_df[column]),
            4,
        )

    diagnostics["max_abs_smd"] = round(max((abs(value) for value in diagnostics.values()), default=0.0), 4)
    return diagnostics


def compute_overlap_diagnostics(df: pd.DataFrame, treatment_col: str) -> Dict[str, float]:
    """Summarize common support based on estimated propensity score."""
    treated = df[df[treatment_col] == 1]["propensity_score"]
    control = df[df[treatment_col] == 0]["propensity_score"]
    if len(treated) == 0 or len(control) == 0:
        return {"treated_in_support_rate": 0.0, "common_support_lower": 0.0, "common_support_upper": 0.0}

    lower = max(float(treated.min()), float(control.min()))
    upper = min(float(treated.max()), float(control.max()))
    if lower > upper:
        support_rate = 0.0
    else:
        support_rate = float(((treated >= lower) & (treated <= upper)).mean())

    return {
        "treated_in_support_rate": round(support_rate, 4),
        "common_support_lower": round(lower, 4),
        "common_support_upper": round(upper, 4),
    }


def calculate_ate(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome"
) -> Tuple[float, float, Dict[str, float]]:
    """Calculate ATE and its standard error from group averages."""
    treated = df[df[treatment_col] == 1]
    control = df[df[treatment_col] == 0]

    if len(treated) == 0 or len(control) == 0:
        raise ValueError("ATE requires both treated and control observations.")
    
    treated_rate = treated[outcome_col].mean()
    control_rate = control[outcome_col].mean()
    
    ate = treated_rate - control_rate
    
    n_treated = len(treated)
    n_control = len(control)
    
    var_treated = treated_rate * (1 - treated_rate) / n_treated
    var_control = control_rate * (1 - control_rate) / n_control
    se = np.sqrt(var_treated + var_control)
    
    return ate, se, {
        "treated_rate": treated_rate,
        "control_rate": control_rate
    }


def calculate_lift(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome"
) -> float:
    """Calculate treated bad-rate lift versus the portfolio average."""
    treated_rate = df[df[treatment_col] == 1][outcome_col].mean()
    overall_rate = df[outcome_col].mean()
    
    if overall_rate == 0:
        return 0.0
    
    return treated_rate / overall_rate


def calculate_ks(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome"
) -> Tuple[float, float]:
    """Compare treated and control outcome distributions with KS."""
    treated_outcomes = df[df[treatment_col] == 1][outcome_col].values
    control_outcomes = df[df[treatment_col] == 0][outcome_col].values
    
    ks_stat, pvalue = stats.ks_2samp(treated_outcomes, control_outcomes)
    
    return ks_stat, pvalue


def bootstrap_confidence_interval(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome",
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95
) -> Tuple[float, float]:
    """Estimate a bootstrap confidence interval for ATE."""
    ate_samples = []
    treated = df[df[treatment_col] == 1]
    control = df[df[treatment_col] == 0]
    
    for _ in range(n_bootstrap):
        treated_sample = treated.sample(n=len(treated), replace=True)
        control_sample = control.sample(n=len(control), replace=True)
        sample = pd.concat([treated_sample, control_sample], ignore_index=True)
        ate, _, _ = calculate_ate(sample, treatment_col, outcome_col)
        ate_samples.append(ate)
    
    lower = np.percentile(ate_samples, (1 - confidence_level) / 2 * 100)
    upper = np.percentile(ate_samples, (1 + confidence_level) / 2 * 100)
    
    return lower, upper


def estimate_propensity_score(
    df: pd.DataFrame,
    treatment_col: str,
    covariate_cols: List[str]
) -> np.ndarray:
    """Estimate treatment propensity using logistic regression."""
    X = df[covariate_cols].values
    y = df[treatment_col].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    model = LogisticRegression(max_iter=1000, random_state=42)
    model.fit(X_scaled, y)
    
    propensity_scores = model.predict_proba(X_scaled)[:, 1]
    
    return propensity_scores


def psm_matching(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome",
    covariate_cols: List[str] = None,
    caliper: float = 0.05
) -> Tuple[pd.DataFrame, Dict]:
    """Run nearest-neighbor matching within a caliper on propensity score."""
    if covariate_cols is None:
        covariate_cols = ["risk_score", "income", "dti"]

    df = df.copy()
    
    available_cols = [col for col in covariate_cols if col in df.columns]
    if not available_cols:
        df["propensity_score"] = 0.5
    else:
        df["propensity_score"] = estimate_propensity_score(df, treatment_col, available_cols)
    
    treated = df[df[treatment_col] == 1].copy()
    control = df[df[treatment_col] == 0].copy()
    overlap_diagnostics = compute_overlap_diagnostics(df, treatment_col)
    
    matched_pairs = []
    unmatched_treated = []
    used_control_indices = set()
    
    for idx, treated_row in treated.iterrows():
        ps_treated = treated_row["propensity_score"]
        
        control_candidates = control[
            abs(control["propensity_score"] - ps_treated) <= caliper
        ]
        control_candidates = control_candidates[~control_candidates.index.isin(used_control_indices)]
        
        if len(control_candidates) > 0:
            closest_idx = (
                control_candidates["propensity_score"] - ps_treated
            ).abs().idxmin()
            used_control_indices.add(closest_idx)
            
            matched_pairs.append({
                "treated_idx": idx,
                "control_idx": closest_idx,
                "treated_outcome": treated_row[outcome_col],
                "control_outcome": control.loc[closest_idx, outcome_col],
                "propensity_diff": abs(control.loc[closest_idx, "propensity_score"] - ps_treated)
            })
        else:
            unmatched_treated.append(idx)
    
    matching_stats = {
        "total_treated": len(treated),
        "matched_treated": len(matched_pairs),
        "unmatched_treated": len(unmatched_treated),
        "matching_rate": len(matched_pairs) / len(treated) if len(treated) > 0 else 0,
        "avg_propensity_diff": np.mean([p["propensity_diff"] for p in matched_pairs]) if matched_pairs else 0,
        "matched_control_count": len(used_control_indices),
        "control_reuse_rate": 0.0,
        **overlap_diagnostics,
    }
    
    matched_df = pd.DataFrame(matched_pairs)
    
    return matched_df, matching_stats


def calculate_att_from_matched(matched_df: pd.DataFrame) -> float:
    """Calculate ATT from matched treated-control pairs."""
    if len(matched_df) == 0:
        return 0.0
    
    treated_outcome_mean = matched_df["treated_outcome"].mean()
    control_outcome_mean = matched_df["control_outcome"].mean()
    
    return treated_outcome_mean - control_outcome_mean


def simulate_profit(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome",
    limit_before_col: str = "limit_before",
    limit_after_col: str = "limit_after",
    interest_rate: float = 0.15,
    lgd: float = 0.6,
    op_cost_ratio: float = 0.02
) -> Dict:
    """Simulate simple average profit before and after treatment."""
    treated = df[df[treatment_col] == 1].copy()
    control = df[df[treatment_col] == 0].copy()
    
    def calculate_group_profit(group, limit_col):
        if len(group) == 0:
            return {"total_profit": 0, "avg_profit": 0, "total_expected_loss": 0}
        
        avg_limit = group[limit_col].mean()
        default_rate = group[outcome_col].mean()
        
        interest_income = avg_limit * interest_rate
        expected_loss = avg_limit * default_rate * lgd
        op_cost = avg_limit * op_cost_ratio
        
        profit = interest_income - expected_loss - op_cost
        
        return {
            "total_profit": profit * len(group),
            "avg_profit": profit,
            "total_expected_loss": expected_loss * len(group),
            "avg_limit": avg_limit,
            "default_rate": default_rate
        }
    
    treated_profit_before = calculate_group_profit(treated, limit_before_col)
    treated_profit_after = calculate_group_profit(treated, limit_after_col)
    control_profit = calculate_group_profit(control, limit_before_col)
    
    return {
        "treated_before": treated_profit_before,
        "treated_after": treated_profit_after,
        "control": control_profit,
        "marginal_profit": treated_profit_after["avg_profit"] - treated_profit_before["avg_profit"],
        "profit_per_treated_customer": treated_profit_after["avg_profit"]
    }


def run_causal_analysis(
    df: pd.DataFrame,
    treatment_col: str = "treatment",
    outcome_col: str = "outcome",
    limit_before_col: str = "limit_before",
    limit_after_col: str = "limit_after",
    covariate_cols: List[str] = None,
    config: CreditLimitConfig = None
) -> CausalInferenceResult:
    """Execute the full causal evaluation workflow."""
    if config is None:
        config = DEFAULT_CONFIG

    missing_cols = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns for causal evaluation: {missing_cols}")
    
    ate, se, default_rates = calculate_ate(df, treatment_col, outcome_col)
    
    lift = calculate_lift(df, treatment_col, outcome_col)
    
    ks_stat, ks_pvalue = calculate_ks(df, treatment_col, outcome_col)
    
    ci_lower, ci_upper = bootstrap_confidence_interval(
        df, treatment_col, outcome_col,
        n_bootstrap=500
    )
    
    profit_sim = simulate_profit(
        df, treatment_col, outcome_col,
        limit_before_col, limit_after_col
    )
    
    if covariate_cols:
        available_covars = [col for col in covariate_cols if col in df.columns]
        if available_covars:
            pre_balance = compute_balance_diagnostics(df, treatment_col, available_covars)
            matched_df, matching_stats = psm_matching(
                df, treatment_col, outcome_col, available_covars,
                caliper=config.causal_inference.psm_config["caliper"]
            )
            att = calculate_att_from_matched(matched_df)
            profit_sim["psm_matching_stats"] = matching_stats
            if len(matched_df) > 0:
                post_balance = compute_balance_diagnostics(
                    df,
                    treatment_col,
                    available_covars,
                    treated_indices=matched_df["treated_idx"].tolist(),
                    control_indices=matched_df["control_idx"].tolist(),
                )
            else:
                post_balance = {}
            balance_diagnostics = {"pre_match": pre_balance, "post_match": post_balance}
            overlap_diagnostics = {
                key: matching_stats[key]
                for key in ["treated_in_support_rate", "common_support_lower", "common_support_upper"]
                if key in matching_stats
            }
            evidence_tier = "causal_psm_ready"
            if matching_stats.get("matching_rate", 0) < config.causal_inference.psm_config["min_match_rate"]:
                evidence_tier = "causal_psm_weak_overlap"
            if post_balance and post_balance.get("max_abs_smd", 0.0) > config.causal_inference.psm_config["max_abs_smd"]:
                evidence_tier = "causal_psm_unbalanced"
        else:
            att = ate
            balance_diagnostics = {"pre_match": {}, "post_match": {}}
            overlap_diagnostics = {}
            evidence_tier = "observational_no_covariates"
    else:
        att = ate
        balance_diagnostics = {"pre_match": {}, "post_match": {}}
        overlap_diagnostics = {}
        evidence_tier = "observational_no_covariates"
    
    return CausalInferenceResult(
        ate=round(ate, 6),
        att=round(att, 6),
        lift=round(lift, 4),
        ks_statistic=round(ks_stat, 4),
        ks_pvalue=round(ks_pvalue, 4),
        profit_simulation=profit_sim,
        confidence_interval_95=(round(ci_lower, 6), round(ci_upper, 6)),
        sample_sizes={
            "total": len(df),
            "treated": (df[treatment_col] == 1).sum(),
            "control": (df[treatment_col] == 0).sum()
        },
        default_rates=default_rates,
        balance_diagnostics=balance_diagnostics,
        overlap_diagnostics=overlap_diagnostics,
        evidence_tier=evidence_tier,
    )


def generate_evaluation_report(result: CausalInferenceResult) -> str:
    """Render a concise markdown-ready evaluation report."""
    report = []
    report.append("=" * 60)
    report.append("Causal Evaluation Report")
    report.append("=" * 60)
    
    report.append("\n[Sample]")
    report.append(f"  Total rows: {result.sample_sizes['total']}")
    report.append(f"  Treated rows: {result.sample_sizes['treated']}")
    report.append(f"  Control rows: {result.sample_sizes['control']}")
    
    report.append("\n[Outcome Rates]")
    report.append(f"  Treated default rate: {result.default_rates['treated_rate']:.4f}")
    report.append(f"  Control default rate: {result.default_rates['control_rate']:.4f}")
    
    report.append("\n[Effect Estimates]")
    report.append(f"  ATE: {result.ate:.6f}")
    report.append(f"  ATT: {result.att:.6f}")
    report.append(f"  95% CI: [{result.confidence_interval_95[0]:.6f}, {result.confidence_interval_95[1]:.6f}]")
    report.append(f"  Evidence tier: {result.evidence_tier}")
    
    report.append("\n[Diagnostics]")
    report.append(f"  Lift: {result.lift:.4f}")
    report.append(f"  KS statistic: {result.ks_statistic:.4f}")
    report.append(f"  KS p-value: {result.ks_pvalue:.4f}")
    if result.balance_diagnostics.get("pre_match"):
        report.append(f"  Pre-match max abs SMD: {result.balance_diagnostics['pre_match'].get('max_abs_smd', 0.0):.4f}")
    if result.balance_diagnostics.get("post_match"):
        report.append(f"  Post-match max abs SMD: {result.balance_diagnostics['post_match'].get('max_abs_smd', 0.0):.4f}")
    if result.overlap_diagnostics:
        report.append(f"  Treated in support rate: {result.overlap_diagnostics.get('treated_in_support_rate', 0.0):.4f}")
    
    report.append("\n[Profit Simulation]")
    profit = result.profit_simulation
    report.append(f"  Treated average profit before: {profit['treated_before']['avg_profit']:.2f}")
    report.append(f"  Treated average profit after: {profit['treated_after']['avg_profit']:.2f}")
    report.append(f"  Marginal profit: {profit['marginal_profit']:.2f}")
    
    if "psm_matching_stats" in profit:
        report.append("\n[PSM Matching]")
        psm_stats = profit["psm_matching_stats"]
        report.append(f"  Match rate: {psm_stats['matching_rate']:.2%}")
        report.append(f"  Average propensity difference: {psm_stats['avg_propensity_diff']:.4f}")
    
    report.append("\n[Conclusion]")
    if result.ate > 0:
        report.append("  Limit treatment is associated with higher default risk.")
    else:
        report.append("  Limit treatment does not increase default risk on the point estimate.")
    
    if result.confidence_interval_95[0] > 0 or result.confidence_interval_95[1] < 0:
        report.append("  The estimated effect is statistically non-zero under the reported interval.")
    else:
        report.append("  The estimated effect is not statistically distinct from zero under the reported interval.")
    
    return "\n".join(report)
