"""Risk adjustment, dynamic adjustment, and freeze fix tests."""
import pandas as pd
import pytest

from config import DEFAULT_CONFIG
from risk_adjustment import adjust_batch_limits, adjust_single_limit, bin_dti, bin_risk_score
from dynamic_adjustment import adjust_batch_customers, adjust_single_customer


def test_risk_score_binning():
    # bins are on 0-1 scale: [0.2, 0.5, 0.8]
    assert bin_risk_score(0.95, DEFAULT_CONFIG.risk_coefficient.risk_score_bins) == "very_low_risk"
    assert bin_risk_score(0.75, DEFAULT_CONFIG.risk_coefficient.risk_score_bins) == "low_risk"
    assert bin_risk_score(0.40, DEFAULT_CONFIG.risk_coefficient.risk_score_bins) == "medium_risk"
    assert bin_risk_score(0.10, DEFAULT_CONFIG.risk_coefficient.risk_score_bins) == "high_risk"


def test_dti_binning():
    # bins: [0.1, 0.25, 0.4, 0.5] → dti_low < 0.1, then dti_medium, dti_high, dti_very_high
    assert bin_dti(0.05, DEFAULT_CONFIG.risk_coefficient.dti_bins) == "dti_low"
    assert bin_dti(0.55, DEFAULT_CONFIG.risk_coefficient.dti_bins) == "dti_very_high"


def test_high_risk_yields_lower_final_limit_than_low_risk():
    low_risk = adjust_single_limit(
        customer_id="A1", base_limit=50000, risk_score=0.90, dti=0.20,
        config=DEFAULT_CONFIG,
    )
    high_risk = adjust_single_limit(
        customer_id="A2", base_limit=50000, risk_score=0.40, dti=0.20,
        config=DEFAULT_CONFIG,
    )
    assert high_risk.final_limit <= low_risk.final_limit


def test_cap_constraint_enforced():
    # very high base limit should be capped at the segment-level limit
    result = adjust_single_limit(
        customer_id="C1", base_limit=10_000_000, risk_score=0.95, dti=0.10,
        config=DEFAULT_CONFIG,
    )
    assert result.applied_constraint == "cap"
    assert result.final_limit < 10_000_000  # was actually capped


def test_freeze_when_fraud_keeps_current_limit():
    """The freeze bug fix: with freeze_keeps_current_limit=True (default),
    suggested_limit must equal current_limit, not 0."""
    row = pd.Series({
        "customer_id": "X1",
        "current_limit": 50000,
        "fraud_flag": True,
    })
    result = adjust_single_customer(row, DEFAULT_CONFIG)
    assert result.adjustment_action == "freeze"
    assert result.suggested_limit == 50000
    assert result.adjustment_ratio == 0.0
    assert result.operational_action == "freeze_usage"


def test_freeze_with_zeroing_config():
    """With freeze_keeps_current_limit=False, suggested_limit drops to 0."""
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg.dynamic_adjustment.freeze_keeps_current_limit = False
    row = pd.Series({
        "customer_id": "X2",
        "current_limit": 50000,
        "fraud_flag": True,
    })
    result = adjust_single_customer(row, cfg)
    assert result.adjustment_action == "freeze"
    assert result.suggested_limit == 0.0
    assert result.adjustment_ratio == -1.0


def test_no_signals_yields_maintain():
    row = pd.Series({
        "customer_id": "M1",
        "current_limit": 30000,
        "behavior_score": 60,
        "utilization_rate": 0.40,
        "overdue_status": "current",
        "last_increase_months": 99,
    })
    result = adjust_single_customer(row, DEFAULT_CONFIG)
    assert result.adjustment_action == "maintain"


def test_increase_signal_blocked_by_recent_increase():
    """If last_increase_months < frequency threshold, no increase even with signal."""
    row = pd.Series({
        "customer_id": "I1",
        "current_limit": 10000,
        "behavior_score": 95,
        "utilization_rate": 0.95,
        "overdue_status": "current",
        "repayment_months": 12,
        "last_increase_months": 0,  # too recent
    })
    result = adjust_single_customer(row, DEFAULT_CONFIG)
    assert result.adjustment_action == "maintain"


def test_batch_dynamic_adjustment_returns_one_row_per_input():
    df = pd.DataFrame({
        "customer_id": [f"D{i}" for i in range(4)],
        "current_limit": [30000, 18000, 25000, 12000],
        "behavior_score": [88, 52, 40, 72],
        "overdue_status": ["current", "m1", "m2_plus", "current"],
        "utilization_rate": [0.86, 0.42, 0.30, 0.91],
        "last_increase_months": [8, 12, 12, 2],
    })
    result = adjust_batch_customers(df, config=DEFAULT_CONFIG)
    assert len(result) == 4
    assert "adjustment_action" in result.columns
