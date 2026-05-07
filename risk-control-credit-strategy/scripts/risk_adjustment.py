"""Risk-based adjustment of affordability limits."""

from __future__ import annotations

import pandas as pd
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass

from config import CreditLimitConfig, DEFAULT_CONFIG


REQUIRED_COLUMNS = ["customer_id", "base_limit", "risk_score", "dti"]


@dataclass
class RiskAdjustmentResult:
    """Single-account risk adjustment output."""
    customer_id: str
    risk_level: str
    dti_bin: str
    risk_coefficient: float
    adjusted_limit: float
    floor_limit: float
    cap_limit: float
    final_limit: float
    affordability_status: str
    floor_eligible: bool
    applied_constraint: Optional[str] = None


def bin_risk_score(
    risk_score: float, 
    score_bins: List[float],
    normalize: bool = True
) -> str:
    """Convert a score into an ordered risk level."""
    if normalize and risk_score > 1:
        risk_score = risk_score / 100.0
    
    if risk_score < score_bins[0]:
        return "high_risk"
    elif risk_score < score_bins[1]:
        return "medium_risk"
    elif risk_score < score_bins[2]:
        return "low_risk"
    else:
        return "very_low_risk"


def bin_dti(dti: float, dti_bins: List[float]) -> str:
    """Bin DTI into the configured policy buckets."""
    if dti < dti_bins[0]:
        return "dti_low"
    elif dti < dti_bins[1]:
        return "dti_medium"
    elif dti < dti_bins[2]:
        return "dti_high"
    else:
        return "dti_very_high"


def lookup_coefficient(
    risk_level: str,
    dti_bin: str,
    coefficient_matrix: Dict[str, Dict[str, float]]
) -> float:
    """Fetch the risk coefficient from the policy matrix."""
    if risk_level in coefficient_matrix:
        return coefficient_matrix[risk_level].get(dti_bin, 1.0)
    return 1.0


def lookup_floor_cap(
    risk_level: str,
    floor_cap_matrix: Dict[str, Dict[str, float]]
) -> Tuple[float, float]:
    """Fetch floor and cap values for a risk level."""
    level_mapping = {
        "very_low_risk": "level_1_best",
        "low_risk": "level_2",
        "medium_risk": "level_3",
        "high_risk": "level_4",
    }
    
    mapped_level = level_mapping.get(risk_level, "level_5_worst")
    
    if mapped_level in floor_cap_matrix:
        cap = floor_cap_matrix[mapped_level].get("cap", 50000)
        floor = floor_cap_matrix[mapped_level].get("floor", 2000)
    else:
        cap = 40000
        floor = 2000
    
    return floor, cap


def adjust_single_limit(
    customer_id: str,
    base_limit: float,
    risk_score: float,
    dti: float,
    risk_level: Optional[str] = None,
    affordability_status: Optional[str] = None,
    floor_eligible: Optional[bool] = None,
    config: CreditLimitConfig = None
) -> RiskAdjustmentResult:
    """Apply the risk policy to a single base limit."""
    if config is None:
        config = DEFAULT_CONFIG

    affordability_status = affordability_status or "affordable"
    if floor_eligible is None:
        floor_eligible = base_limit > 0
    
    if risk_level is None:
        risk_level = bin_risk_score(
            risk_score, 
            config.risk_coefficient.risk_score_bins
        )
    
    dti_bin = bin_dti(dti, config.risk_coefficient.dti_bins)
    
    risk_coefficient = lookup_coefficient(
        risk_level, 
        dti_bin, 
        config.risk_coefficient.coefficient_matrix
    )
    
    adjusted_limit = base_limit * risk_coefficient
    
    floor_limit, cap_limit = lookup_floor_cap(
        risk_level, 
        config.floor_cap.floor_cap_matrix
    )
    
    applied_constraint = None
    if affordability_status == "not_affordable" or base_limit <= 0:
        final_limit = 0.0
        applied_constraint = "affordability_block"
    elif config.floor_cap.apply_floor_only_when_affordable and not floor_eligible:
        final_limit = max(adjusted_limit, 0.0)
        applied_constraint = "floor_blocked"
    elif adjusted_limit < floor_limit:
        final_limit = floor_limit
        applied_constraint = "floor"
    elif adjusted_limit > cap_limit:
        final_limit = cap_limit
        applied_constraint = "cap"
    else:
        final_limit = adjusted_limit
    
    return RiskAdjustmentResult(
        customer_id=customer_id,
        risk_level=risk_level,
        dti_bin=dti_bin,
        risk_coefficient=round(risk_coefficient, 4),
        adjusted_limit=round(adjusted_limit, 2),
        floor_limit=floor_limit,
        cap_limit=cap_limit,
        final_limit=round(final_limit, 2),
        affordability_status=affordability_status,
        floor_eligible=floor_eligible,
        applied_constraint=applied_constraint
    )


def adjust_batch_limits(
    df: pd.DataFrame,
    config: CreditLimitConfig = None,
    risk_score_col: str = "risk_score",
    dti_col: str = "dti",
    base_limit_col: str = "base_limit",
    risk_level_col: Optional[str] = None
) -> pd.DataFrame:
    """Apply the risk policy to a dataframe of base limits."""
    if config is None:
        config = DEFAULT_CONFIG
    
    required_cols = ["customer_id", base_limit_col, risk_score_col, dti_col]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns for risk adjustment: {missing_cols}")
    
    results = []
    
    for _, row in df.iterrows():
        risk_level = None
        if risk_level_col and risk_level_col in row.index and pd.notna(row[risk_level_col]):
            risk_level = row[risk_level_col]

        affordability_status = row["affordability_status"] if "affordability_status" in row.index else None
        floor_eligible = row["floor_eligible"] if "floor_eligible" in row.index else None
        
        result = adjust_single_limit(
            customer_id=row["customer_id"],
            base_limit=row[base_limit_col],
            risk_score=row[risk_score_col],
            dti=row[dti_col],
            risk_level=risk_level,
            affordability_status=affordability_status,
            floor_eligible=floor_eligible,
            config=config
        )
        results.append(result)
    
    output_df = pd.DataFrame([
        {
            "customer_id": r.customer_id,
            "risk_level": r.risk_level,
            "dti_bin": r.dti_bin,
            "risk_coefficient": r.risk_coefficient,
            "adjusted_limit": r.adjusted_limit,
            "floor_limit": r.floor_limit,
            "cap_limit": r.cap_limit,
            "final_limit": r.final_limit,
            "affordability_status": r.affordability_status,
            "floor_eligible": r.floor_eligible,
            "applied_constraint": r.applied_constraint
        }
        for r in results
    ])
    
    return output_df


def generate_risk_summary(result_df: pd.DataFrame) -> Dict:
    """Generate compact summary metrics for agent reporting."""
    summary = {
        "total_customers": len(result_df),
        "avg_final_limit": round(result_df["final_limit"].mean(), 2),
        "median_final_limit": round(result_df["final_limit"].median(), 2),
        "risk_level_distribution": result_df["risk_level"].value_counts().to_dict(),
        "dti_bin_distribution": result_df["dti_bin"].value_counts().to_dict(),
        "constraint_distribution": result_df["applied_constraint"].value_counts(dropna=False).to_dict(),
        "avg_coefficient_by_risk": result_df.groupby("risk_level")["risk_coefficient"].mean().round(4).to_dict(),
        "affordability_distribution": result_df["affordability_status"].value_counts().to_dict(),
        "floor_block_count": int((result_df["applied_constraint"] == "affordability_block").sum()),
    }
    return summary


def validate_risk_ranking(result_df: pd.DataFrame, original_df: pd.DataFrame) -> Dict:
    """Check whether safer customers still receive larger limits."""
    merged = result_df.merge(
        original_df[["customer_id", "risk_score"]], 
        on="customer_id"
    )
    
    correlation = merged["risk_score"].corr(merged["final_limit"])
    
    risk_level_order = ["very_low_risk", "low_risk", "medium_risk", "high_risk"]
    avg_by_level = merged.groupby("risk_level")["final_limit"].mean()
    
    is_correct_ranking = True
    for i in range(len(risk_level_order) - 1):
        level1 = risk_level_order[i]
        level2 = risk_level_order[i + 1]
        if level1 in avg_by_level and level2 in avg_by_level:
            if avg_by_level[level1] < avg_by_level[level2]:
                is_correct_ranking = False
                break
    
    return {
        "correlation_risk_limit": round(correlation if pd.notna(correlation) else 0.0, 4),
        "is_correct_ranking": is_correct_ranking,
        "avg_limit_by_risk_level": avg_by_level.round(2).to_dict(),
        "floor_hit_rate": round((result_df["applied_constraint"] == "floor").mean(), 4),
        "cap_hit_rate": round((result_df["applied_constraint"] == "cap").mean(), 4),
        "validation_passed": bool((correlation if pd.notna(correlation) else 0.0) > 0 and is_correct_ranking),
    }


if __name__ == "__main__":
    sample_data = pd.DataFrame([
        {
            "customer_id": "C001",
            "base_limit": 36000,
            "risk_score": 85,
            "dti": 0.15
        },
        {
            "customer_id": "C002",
            "base_limit": 25000,
            "risk_score": 45,
            "dti": 0.35
        },
        {
            "customer_id": "C003",
            "base_limit": 50000,
            "risk_score": 92,
            "dti": 0.08
        },
        {
            "customer_id": "C004",
            "base_limit": 15000,
            "risk_score": 25,
            "dti": 0.55
        },
    ])
    
    print("=" * 60)
    print("风险调整系数计算示例")
    print("=" * 60)
    
    result = adjust_batch_limits(sample_data)
    print("\n计算结果:")
    print(result[["customer_id", "risk_level", "risk_coefficient", "final_limit"]])
    
    print("\n汇总统计:")
    stats = generate_risk_summary(result)
    for k, v in stats.items():
        print(f"  {k}: {v}")
    
    print("\n风险排序验证:")
    validation = validate_risk_ranking(result, sample_data)
    for k, v in validation.items():
        print(f"  {k}: {v}")
