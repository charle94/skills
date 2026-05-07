"""Centralized data schema for every pipeline mode.

Each mode declares: required columns, optional columns, expected dtype family,
value range / enum constraints, and an optional descriptive note.

This is the single source of truth for "what does mode X need to receive?"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class ColumnSpec:
    """Single column contract."""
    name: str
    required: bool = False
    dtype: str = "any"  # "numeric", "categorical", "boolean", "string", "date", "any"
    value_range: Optional[Tuple[float, float]] = None  # for numeric
    allowed_values: Optional[List[Any]] = None  # for categorical/enum
    note: str = ""


# Income source enum used in base_limit
INCOME_SOURCES = [
    "payroll", "bank_flow", "tax_return", "social_security",
    "provident_fund", "self_reported", "model_predicted",
]
DTI_LEVELS = ["conservative", "moderate", "aggressive"]
RISK_LEVELS = ["very_low_risk", "low_risk", "medium_risk", "high_risk"]
DTI_BINS = ["dti_low", "dti_medium", "dti_high", "dti_very_high"]
OVERDUE_STATES = ["current", "m1", "m2", "m2_plus"]


MODE_SCHEMAS: Dict[str, List[ColumnSpec]] = {
    "base_limit": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("monthly_income", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("income_source", required=True, dtype="categorical", allowed_values=INCOME_SOURCES),
        ColumnSpec("existing_debt", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("tenor_months", required=True, dtype="numeric", value_range=(1, 120)),
        ColumnSpec("dti_level", required=False, dtype="categorical", allowed_values=DTI_LEVELS),
    ],
    "risk_adjustment": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("base_limit", required=True, dtype="numeric", value_range=(0, 10_000_000)),
        ColumnSpec("risk_score", required=True, dtype="numeric", value_range=(0, 1000),
                   note="Either 0-1 or 0-100 scale; auto-normalized in code."),
        ColumnSpec("dti", required=True, dtype="numeric", value_range=(0, 5)),
        ColumnSpec("affordability_status", required=False, dtype="categorical",
                   allowed_values=["affordable", "constrained", "not_affordable"]),
        ColumnSpec("floor_eligible", required=False, dtype="boolean"),
        ColumnSpec("risk_level", required=False, dtype="categorical", allowed_values=RISK_LEVELS),
    ],
    "dynamic_adjustment": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("current_limit", required=True, dtype="numeric", value_range=(0, 10_000_000)),
        ColumnSpec("behavior_score", required=False, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("repayment_months", required=False, dtype="numeric", value_range=(0, 240)),
        ColumnSpec("overdue_status", required=False, dtype="categorical", allowed_values=OVERDUE_STATES),
        ColumnSpec("utilization_rate", required=False, dtype="numeric", value_range=(0, 1.5)),
        ColumnSpec("external_risk_flag", required=False, dtype="boolean"),
        ColumnSpec("last_increase_months", required=False, dtype="numeric", value_range=(0, 240)),
        ColumnSpec("score_change", required=False, dtype="numeric", value_range=(-1000, 1000)),
        ColumnSpec("multi_lending_count", required=False, dtype="numeric", value_range=(0, 100)),
        ColumnSpec("behavior_change_flag", required=False, dtype="boolean"),
        ColumnSpec("fraud_flag", required=False, dtype="boolean"),
        ColumnSpec("pd_estimate", required=False, dtype="numeric", value_range=(0, 1)),
        ColumnSpec("pd", required=False, dtype="numeric", value_range=(0, 1)),
        ColumnSpec("user_request", required=False, dtype="boolean"),
    ],
    "causal_evaluation": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("treatment", required=True, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("outcome", required=True, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("limit_before", required=True, dtype="numeric", value_range=(0, 10_000_000)),
        ColumnSpec("limit_after", required=True, dtype="numeric", value_range=(0, 10_000_000)),
        ColumnSpec("risk_score", required=False, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("income", required=False, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("age", required=False, dtype="numeric", value_range=(18, 100)),
        ColumnSpec("dti", required=False, dtype="numeric", value_range=(0, 5)),
        ColumnSpec("utilization_rate", required=False, dtype="numeric", value_range=(0, 1.5)),
    ],
    "strategy_tuning": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("bad_flag", required=True, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("risk_level", required=False, dtype="categorical", allowed_values=RISK_LEVELS),
        ColumnSpec("risk_score", required=False, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("dti_bin", required=False, dtype="categorical", allowed_values=DTI_BINS),
        ColumnSpec("dti", required=False, dtype="numeric", value_range=(0, 5)),
        ColumnSpec("final_limit", required=False, dtype="numeric", value_range=(0, 10_000_000)),
        ColumnSpec("utilization_rate", required=False, dtype="numeric", value_range=(0, 1.5)),
        ColumnSpec("months_on_book", required=False, dtype="numeric", value_range=(0, 240)),
        ColumnSpec("channel", required=False, dtype="string"),
    ],
    "vintage_analysis": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("origination_month", required=True, dtype="string",
                   note="Cohort label, typically YYYY-MM"),
        ColumnSpec("mob", required=True, dtype="numeric", value_range=(0, 240)),
        ColumnSpec("dpd", required=True, dtype="numeric", value_range=(0, 365)),
        ColumnSpec("bad_flag", required=False, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("loan_amount", required=False, dtype="numeric", value_range=(0, 10_000_000)),
    ],
    "portfolio_monitoring": [
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("score", required=True, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("period", required=True, dtype="string", note="Period label like YYYY-MM"),
        ColumnSpec("bad_flag", required=False, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("approved", required=False, dtype="numeric", allowed_values=[0, 1]),
        ColumnSpec("utilization_rate", required=False, dtype="numeric", value_range=(0, 1.5)),
        ColumnSpec("final_limit", required=False, dtype="numeric", value_range=(0, 10_000_000)),
    ],
    "full_limit_strategy": [
        # mirrors base_limit; additional columns surfaced via individual stage schemas
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("monthly_income", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("income_source", required=True, dtype="categorical", allowed_values=INCOME_SOURCES),
        ColumnSpec("existing_debt", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("tenor_months", required=True, dtype="numeric", value_range=(1, 120)),
        ColumnSpec("risk_score", required=False, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("dti", required=False, dtype="numeric", value_range=(0, 5)),
    ],
    "simulation": [
        # simulation reuses the base_limit input plus optional risk fields
        ColumnSpec("customer_id", required=True, dtype="string"),
        ColumnSpec("monthly_income", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("income_source", required=True, dtype="categorical", allowed_values=INCOME_SOURCES),
        ColumnSpec("existing_debt", required=True, dtype="numeric", value_range=(0, 1_000_000)),
        ColumnSpec("tenor_months", required=True, dtype="numeric", value_range=(1, 120)),
        ColumnSpec("risk_score", required=True, dtype="numeric", value_range=(0, 1000)),
        ColumnSpec("dti", required=True, dtype="numeric", value_range=(0, 5)),
    ],
}


def get_required_columns(mode: str) -> List[str]:
    """Return the list of required column names for a mode."""
    if mode not in MODE_SCHEMAS:
        raise ValueError(f"Unknown mode: {mode}")
    return [c.name for c in MODE_SCHEMAS[mode] if c.required]


def get_schema(mode: str) -> List[ColumnSpec]:
    """Return the full column spec list for a mode."""
    if mode not in MODE_SCHEMAS:
        raise ValueError(f"Unknown mode: {mode}")
    return MODE_SCHEMAS[mode]
