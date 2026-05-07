"""Dynamic account-level limit management."""

from __future__ import annotations

import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum

from config import CreditLimitConfig, DEFAULT_CONFIG


REQUIRED_COLUMNS = ["customer_id", "current_limit"]


class AdjustmentAction(Enum):
    """调整动作"""
    INCREASE = "increase"
    DECREASE = "decrease"
    FREEZE = "freeze"
    MAINTAIN = "maintain"


class AdjustmentType(Enum):
    """调整类型"""
    PASSIVE = "passive"
    ACTIVE = "active"
    IMMEDIATE = "immediate"
    GRADUAL = "gradual"


@dataclass
class AdjustmentResult:
    """Single-account dynamic adjustment output."""
    customer_id: str
    adjustment_action: str
    adjustment_type: str
    operational_action: str
    trigger_reasons: List[str]
    suggested_limit: float
    adjustment_ratio: float
    expected_el_change: float
    pd_source: str
    priority: int
    current_limit: float


def detect_increase_signals(
    row: pd.Series,
    config: CreditLimitConfig
) -> Tuple[List[str], int]:
    """Return increase reasons and queue priority."""
    signals = []
    priority = 99
    
    passive_config = config.dynamic_adjustment.increase_triggers["passive"]
    
    if row.get("repayment_months", 0) >= passive_config["excellent_repayment_months"]:
        signals.append("excellent_repayment_history")
        priority = min(priority, 3)
    
    score_change = row.get("score_change", 0)
    if score_change >= passive_config["score_improvement_threshold"]:
        signals.append("score_improvement")
        priority = min(priority, 3)
    
    utilization = row.get("utilization_rate", 0)
    if utilization >= passive_config["high_utilization_threshold"]:
        signals.append("high_utilization")
        priority = min(priority, 4)
    
    if row.get("user_request", False):
        active_config = config.dynamic_adjustment.increase_triggers["active"]
        if active_config["request_allowed"]:
            signals.append("user_request")
            priority = min(priority, 5)
    
    return signals, priority


def detect_decrease_signals(
    row: pd.Series,
    config: CreditLimitConfig
) -> Tuple[List[str], str, int]:
    """Return decrease or freeze reasons, execution style, and priority."""
    signals = []
    adjustment_type = "gradual"
    priority = 99

    def mark_freeze(reason: str, new_priority: int) -> None:
        nonlocal adjustment_type, priority
        signals.append(reason)
        adjustment_type = "freeze"
        priority = min(priority, new_priority)

    def mark_gradual(reason: str, new_priority: int) -> None:
        nonlocal adjustment_type, priority
        signals.append(reason)
        if adjustment_type != "freeze":
            adjustment_type = "gradual"
            priority = min(priority, new_priority)
    
    immediate_config = config.dynamic_adjustment.decrease_triggers["immediate"]
    gradual_config = config.dynamic_adjustment.decrease_triggers["gradual"]
    
    if immediate_config.get("fraud_signal") and row.get("fraud_flag", False):
        mark_freeze("fraud_signal", 1)
    
    overdue_status = row.get("overdue_status", "current")
    if immediate_config.get("overdue_m2_plus") and overdue_status in ["m2", "m2_plus"]:
        mark_freeze("severe_overdue", 1)
    
    if gradual_config.get("overdue_m1") and overdue_status == "m1":
        mark_gradual("m1_overdue", 2)
    
    if row.get("external_risk_flag", False):
        mark_freeze("external_risk_signal", 1)
    
    score_change = row.get("score_change", 0)
    if score_change < 0 and abs(score_change) >= gradual_config["score_drop_threshold"]:
        mark_gradual("significant_score_drop", 2)

    multi_lending = row.get("multi_lending_count", 0)
    if multi_lending >= gradual_config["multi_lending_threshold"]:
        mark_gradual("high_multi_lending", 3)
    
    if row.get("behavior_change_flag", False):
        mark_freeze("behavior_change", 2)
    
    return signals, adjustment_type, priority


def calculate_increase_amount(
    current_limit: float,
    utilization_rate: float,
    repayment_months: int,
    behavior_score: float,
    config: CreditLimitConfig
) -> float:
    """Estimate an increase amount from healthy behavior and demand."""
    base_increase_ratio = 0.2
    
    if utilization_rate > 0.9:
        utilization_factor = 1.5
    elif utilization_rate > 0.7:
        utilization_factor = 1.2
    else:
        utilization_factor = 1.0
    
    if repayment_months >= 12:
        repayment_factor = 1.3
    elif repayment_months >= 6:
        repayment_factor = 1.1
    else:
        repayment_factor = 1.0
    
    score_factor = behavior_score / 50.0 if behavior_score <= 100 else 1.0
    
    increase_ratio = base_increase_ratio * utilization_factor * repayment_factor * score_factor
    increase_ratio = min(increase_ratio, 0.5)
    
    return current_limit * increase_ratio


def calculate_decrease_amount(
    current_limit: float,
    signals: List[str],
    adjustment_type: str,
    config: CreditLimitConfig
) -> float:
    """Estimate a decrease amount from risk severity."""
    if adjustment_type == "freeze":
        return current_limit

    if "m1_overdue" in signals:
        return current_limit * 0.4
    if "significant_score_drop" in signals:
        return current_limit * 0.3
    if "high_multi_lending" in signals:
        return current_limit * 0.25

    steps = config.dynamic_adjustment.gradual_decrease_steps
    ratio = config.dynamic_adjustment.gradual_decrease_ratio
    return current_limit * (ratio / steps)


def calculate_el_change(
    current_limit: float,
    new_limit: float,
    pd_estimate: float,
    lgd: float = 0.6
) -> float:
    """Estimate expected loss delta from the limit change."""
    current_el = current_limit * pd_estimate * lgd
    new_el = new_limit * pd_estimate * lgd
    return new_el - current_el


def adjust_single_customer(
    row: pd.Series,
    config: CreditLimitConfig = None
) -> AdjustmentResult:
    """Decide increase, decrease, freeze, or maintain for one account."""
    if config is None:
        config = DEFAULT_CONFIG
    
    current_limit = row["current_limit"]
    customer_id = row["customer_id"]
    
    increase_signals, increase_priority = detect_increase_signals(row, config)
    decrease_signals, decrease_type, decrease_priority = detect_decrease_signals(row, config)
    
    if decrease_signals:
        adjustment_action = "freeze" if decrease_type == "freeze" else "decrease"
        adjustment_type = "immediate" if decrease_type == "freeze" else decrease_type
        trigger_reasons = decrease_signals
        priority = decrease_priority
        adjustment_amount = calculate_decrease_amount(
            current_limit, decrease_signals, decrease_type, config
        )
        if adjustment_action == "freeze":
            # freeze_keeps_current_limit controls whether the recorded limit stays
            # at the current value (operational block only) or drops to zero.
            if config.dynamic_adjustment.freeze_keeps_current_limit:
                suggested_limit = current_limit
                adjustment_ratio = 0.0
            else:
                suggested_limit = 0.0
                adjustment_ratio = -1.0
        else:
            suggested_limit = max(current_limit - adjustment_amount, 0.0)
            adjustment_ratio = -adjustment_amount / current_limit if current_limit else 0.0
    
    elif increase_signals:
        last_increase_months = row.get("last_increase_months", 999)
        if last_increase_months < config.dynamic_adjustment.increase_frequency_months:
            return AdjustmentResult(
                customer_id=customer_id,
                adjustment_action="maintain",
                adjustment_type="none",
                operational_action="no_change",
                trigger_reasons=["frequency_limit_not_reached"],
                suggested_limit=current_limit,
                adjustment_ratio=0.0,
                expected_el_change=0.0,
                pd_source="not_used",
                priority=99,
                current_limit=current_limit
            )
        
        adjustment_action = "increase"
        adjustment_type = "passive" if "user_request" not in increase_signals else "active"
        trigger_reasons = increase_signals
        priority = increase_priority
        adjustment_amount = calculate_increase_amount(
            current_limit,
            row.get("utilization_rate", 0),
            row.get("repayment_months", 0),
            row.get("behavior_score", 50),
            config
        )
        suggested_limit = current_limit + adjustment_amount
        adjustment_ratio = adjustment_amount / current_limit
    
    else:
        return AdjustmentResult(
            customer_id=customer_id,
            adjustment_action="maintain",
            adjustment_type="none",
            operational_action="no_change",
            trigger_reasons=[],
            suggested_limit=current_limit,
            adjustment_ratio=0.0,
            expected_el_change=0.0,
            pd_source="not_used",
            priority=99,
            current_limit=current_limit
        )

    if "pd_estimate" in row.index and pd.notna(row["pd_estimate"]):
        pd_estimate = float(row["pd_estimate"])
        pd_source = "pd_estimate"
    elif "pd" in row.index and pd.notna(row["pd"]):
        pd_estimate = float(row["pd"])
        pd_source = "pd"
    else:
        pd_estimate = max(0.01, min(0.95, 1 - row.get("behavior_score", 50) / 100.0))
        pd_source = "heuristic_behavior_score"

    pd_estimate = max(0.01, min(0.95, pd_estimate))

    el_change = calculate_el_change(current_limit, suggested_limit, pd_estimate)

    if adjustment_action == "freeze":
        operational_action = "freeze_usage"
    elif adjustment_action == "decrease":
        operational_action = "decrease_limit"
    elif adjustment_action == "increase":
        operational_action = "increase_limit"
    else:
        operational_action = "no_change"
    
    return AdjustmentResult(
        customer_id=customer_id,
        adjustment_action=adjustment_action,
        adjustment_type=adjustment_type,
        operational_action=operational_action,
        trigger_reasons=trigger_reasons,
        suggested_limit=round(suggested_limit, 2),
        adjustment_ratio=round(adjustment_ratio, 4),
        expected_el_change=round(el_change, 2),
        pd_source=pd_source,
        priority=priority,
        current_limit=current_limit
    )


def adjust_batch_customers(
    df: pd.DataFrame,
    config: CreditLimitConfig = None
) -> pd.DataFrame:
    """Apply dynamic limit management rules to a dataframe of accounts."""
    if config is None:
        config = DEFAULT_CONFIG
    
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns for dynamic adjustment: {missing_cols}")
    
    results = []
    for _, row in df.iterrows():
        result = adjust_single_customer(row, config)
        results.append(result)
    
    output_df = pd.DataFrame([
        {
            "customer_id": r.customer_id,
            "adjustment_action": r.adjustment_action,
            "adjustment_type": r.adjustment_type,
            "operational_action": r.operational_action,
            "trigger_reasons": r.trigger_reasons,
            "suggested_limit": r.suggested_limit,
            "adjustment_ratio": r.adjustment_ratio,
            "expected_el_change": r.expected_el_change,
            "pd_source": r.pd_source,
            "priority": r.priority,
            "current_limit": r.current_limit
        }
        for r in results
    ])
    
    output_df = output_df.sort_values("priority")
    
    return output_df


def generate_adjustment_summary(result_df: pd.DataFrame) -> Dict:
    """Generate compact summary metrics for agent reporting."""
    summary = {
        "total_customers": len(result_df),
        "action_distribution": result_df["adjustment_action"].value_counts().to_dict(),
        "operational_action_distribution": result_df["operational_action"].value_counts().to_dict(),
        "type_distribution": result_df[result_df["adjustment_action"] != "maintain"]["adjustment_type"].value_counts().to_dict(),
        "increase_stats": {
            "count": (result_df["adjustment_action"] == "increase").sum(),
            "avg_ratio": result_df[result_df["adjustment_action"] == "increase"]["adjustment_ratio"].mean(),
            "total_limit_increase": result_df[result_df["adjustment_action"] == "increase"]["suggested_limit"].sum() - 
                                    result_df[result_df["adjustment_action"] == "increase"]["current_limit"].sum(),
        },
        "decrease_stats": {
            "count": (result_df["adjustment_action"] == "decrease").sum(),
            "avg_ratio": result_df[result_df["adjustment_action"] == "decrease"]["adjustment_ratio"].mean(),
            "total_limit_decrease": result_df[result_df["adjustment_action"] == "decrease"]["current_limit"].sum() - 
                                    result_df[result_df["adjustment_action"] == "decrease"]["suggested_limit"].sum(),
        },
        "freeze_stats": {
            "count": int((result_df["adjustment_action"] == "freeze").sum()),
        },
        "total_expected_el_change": round(result_df["expected_el_change"].sum(), 2),
        "heuristic_pd_count": int((result_df["pd_source"] == "heuristic_behavior_score").sum()),
        "high_priority_count": int((result_df["priority"] <= 2).sum()),
    }
    
    if summary["increase_stats"]["count"] > 0:
        summary["increase_stats"]["avg_ratio"] = round(summary["increase_stats"]["avg_ratio"], 4)
        summary["increase_stats"]["total_limit_increase"] = round(summary["increase_stats"]["total_limit_increase"], 2)
    
    if summary["decrease_stats"]["count"] > 0:
        summary["decrease_stats"]["avg_ratio"] = round(summary["decrease_stats"]["avg_ratio"], 4)
        summary["decrease_stats"]["total_limit_decrease"] = round(summary["decrease_stats"]["total_limit_decrease"], 2)
    
    return summary
