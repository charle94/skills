"""Affordability-based base limit calculation."""

from __future__ import annotations

import pandas as pd
from typing import Dict, List
from dataclasses import dataclass

from config import CreditLimitConfig, DEFAULT_CONFIG


REQUIRED_COLUMNS = [
     "customer_id",
     "monthly_income",
     "income_source",
     "existing_debt",
     "tenor_months",
]


@dataclass
class LimitCalculationResult:
    """Single-account base limit output."""
    customer_id: str
    verified_income: float
    income_haircut: float
    dti_threshold: float
    max_monthly_repayment: float
    available_capacity: float
    tenor_factor: float
    base_limit: float
    affordability_status: str
    floor_eligible: bool
    warnings: List[str] = None


def get_income_haircut(income_source: str, config: CreditLimitConfig) -> float:
    """Map income evidence to a haircut factor."""
    haircuts = config.income_verification.income_haircuts
    return haircuts.get(income_source, haircuts.get("self_reported", 0.5))


def get_dti_threshold(dti_level: str, config: CreditLimitConfig) -> float:
    """Map a DTI policy label to a threshold."""
    thresholds = config.dti.dti_thresholds
    return thresholds.get(dti_level, thresholds.get(config.dti.default_dti_level, 0.5))


def get_tenor_factor(tenor_months: int, config: CreditLimitConfig) -> float:
    """Interpolate the tenor factor from the configured ranges."""
    tenor_config = config.tenor_factor.tenor_factors
    
    for params in tenor_config.values():
        min_months = params.get("min_months", 0)
        max_months = params.get("max_months", 999)
        factor_range = params.get("factor_range", (1.0, 1.0))
        
        if min_months <= tenor_months <= max_months:
            if min_months == max_months:
                return factor_range[0]
            ratio = (tenor_months - min_months) / (max_months - min_months)
            return factor_range[0] + ratio * (factor_range[1] - factor_range[0])
    
    if tenor_months < 12:
        return 1.0
    elif tenor_months < 36:
        return 1.2
    else:
        return 1.5


def calculate_single_limit(
    customer_id: str,
    monthly_income: float,
    income_source: str,
    existing_debt: float,
    tenor_months: int,
    dti_level: str = "moderate",
    config: CreditLimitConfig = None
) -> LimitCalculationResult:
    """Calculate the affordability anchor for one customer."""
    if config is None:
        config = DEFAULT_CONFIG
    
    warnings = []
    affordability_status = "affordable"
    floor_eligible = True

    if monthly_income < 0:
        warnings.append("negative_income_detected")
        monthly_income = 0

    if existing_debt < 0:
        warnings.append("negative_existing_debt_detected")
        existing_debt = 0

    if tenor_months <= 0:
        warnings.append("invalid_tenor_detected")
        tenor_months = 1
    
    income_haircut = get_income_haircut(income_source, config)
    verified_income = monthly_income * income_haircut

    if income_source in {"self_reported", "model_predicted"}:
        warnings.append("low_confidence_income_signal")
    
    dti_threshold = get_dti_threshold(dti_level, config)
    max_monthly_repayment = verified_income * dti_threshold
    
    available_capacity = max_monthly_repayment - existing_debt
    
    if available_capacity < 0:
        warnings.append(
            f"available_capacity_below_zero: existing debt exceeds affordable repayment by {abs(available_capacity):.2f}"
        )
        available_capacity = 0
        affordability_status = "not_affordable"
        floor_eligible = False

    if verified_income <= 0:
        warnings.append("verified_income_not_positive")
        affordability_status = "not_affordable"
        floor_eligible = False

    if affordability_status == "affordable" and income_source in {"self_reported", "model_predicted"}:
        affordability_status = "constrained"
    
    tenor_factor = get_tenor_factor(tenor_months, config)
    
    base_limit = available_capacity * tenor_months * tenor_factor
    base_limit = min(base_limit, config.product_cap)
    
    return LimitCalculationResult(
        customer_id=customer_id,
        verified_income=round(verified_income, 2),
        income_haircut=income_haircut,
        dti_threshold=dti_threshold,
        max_monthly_repayment=round(max_monthly_repayment, 2),
        available_capacity=round(available_capacity, 2),
        tenor_factor=round(tenor_factor, 4),
        base_limit=round(base_limit, 2),
        affordability_status=affordability_status,
        floor_eligible=floor_eligible,
        warnings=warnings if warnings else None
    )


def calculate_batch_limits(
    df: pd.DataFrame,
    config: CreditLimitConfig = None,
    dti_level_col: str = "dti_level"
) -> pd.DataFrame:
    """Calculate base limits for a dataframe of applicants or accounts."""
    if config is None:
        config = DEFAULT_CONFIG

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns for base limit calculation: {missing_cols}")

    def _apply_row(row: pd.Series) -> pd.Series:
        dti_level = row.get(dti_level_col, config.dti.default_dti_level)
        result = calculate_single_limit(
            customer_id=row["customer_id"],
            monthly_income=row["monthly_income"],
            income_source=row["income_source"],
            existing_debt=row["existing_debt"],
            tenor_months=row["tenor_months"],
            dti_level=dti_level,
            config=config,
        )
        return pd.Series(
            {
                "customer_id": result.customer_id,
                "verified_income": result.verified_income,
                "income_haircut": result.income_haircut,
                "dti_threshold": result.dti_threshold,
                "max_monthly_repayment": result.max_monthly_repayment,
                "available_capacity": result.available_capacity,
                "tenor_factor": result.tenor_factor,
                "base_limit": result.base_limit,
                "affordability_status": result.affordability_status,
                "floor_eligible": result.floor_eligible,
                "warnings": result.warnings,
            }
        )

    return df.apply(_apply_row, axis=1).reset_index(drop=True)


def generate_summary_stats(result_df: pd.DataFrame) -> Dict:
    """Generate compact summary metrics for agent reporting."""
    return {
        "total_customers": len(result_df),
        "avg_base_limit": round(result_df["base_limit"].mean(), 2),
        "median_base_limit": round(result_df["base_limit"].median(), 2),
        "min_base_limit": round(result_df["base_limit"].min(), 2),
        "max_base_limit": round(result_df["base_limit"].max(), 2),
        "avg_verified_income": round(result_df["verified_income"].mean(), 2),
        "avg_available_capacity": round(result_df["available_capacity"].mean(), 2),
        "zero_capacity_count": int((result_df["available_capacity"] == 0).sum()),
        "affordability_distribution": result_df["affordability_status"].value_counts().to_dict(),
        "floor_eligible_count": int(result_df["floor_eligible"].sum()),
        "warning_count": int(result_df["warnings"].notna().sum()),
    }
