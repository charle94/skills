"""Limit calculation tests."""
import pandas as pd

from config import DEFAULT_CONFIG
from limit_calculation import calculate_batch_limits, calculate_single_limit


def test_single_customer_payroll_income_full_haircut():
    result = calculate_single_limit(
        customer_id="A1",
        monthly_income=10000,
        income_source="payroll",
        existing_debt=1000,
        tenor_months=12,
        config=DEFAULT_CONFIG,
    )
    assert result.customer_id == "A1"
    assert result.income_haircut == 1.0  # payroll = no haircut
    assert result.verified_income == 10000
    assert result.base_limit > 0


def test_self_reported_income_haircut_applied():
    result = calculate_single_limit(
        customer_id="A2",
        monthly_income=10000,
        income_source="self_reported",
        existing_debt=0,
        tenor_months=12,
        config=DEFAULT_CONFIG,
    )
    assert result.income_haircut < 1.0
    assert result.verified_income < 10000


def test_existing_debt_reduces_capacity():
    result_no_debt = calculate_single_limit(
        customer_id="A3", monthly_income=10000, income_source="payroll",
        existing_debt=0, tenor_months=12, config=DEFAULT_CONFIG,
    )
    result_with_debt = calculate_single_limit(
        customer_id="A4", monthly_income=10000, income_source="payroll",
        existing_debt=3000, tenor_months=12, config=DEFAULT_CONFIG,
    )
    assert result_with_debt.base_limit < result_no_debt.base_limit


def test_batch_limits_returns_one_row_per_input():
    df = pd.DataFrame({
        "customer_id": [f"C{i}" for i in range(5)],
        "monthly_income": [10000, 8000, 15000, 5000, 20000],
        "income_source": ["payroll"] * 5,
        "existing_debt": [0, 1000, 2000, 500, 0],
        "tenor_months": [12, 24, 36, 12, 24],
    })
    result = calculate_batch_limits(df, config=DEFAULT_CONFIG)
    assert len(result) == 5
    assert "base_limit" in result.columns
    assert "affordability_status" in result.columns


def test_zero_income_yields_no_affordability():
    result = calculate_single_limit(
        customer_id="Z1", monthly_income=0, income_source="payroll",
        existing_debt=0, tenor_months=12, config=DEFAULT_CONFIG,
    )
    assert result.base_limit == 0 or result.affordability_status == "not_affordable"


def test_longer_tenor_increases_base_limit():
    short = calculate_single_limit(
        customer_id="T1", monthly_income=10000, income_source="payroll",
        existing_debt=0, tenor_months=12, config=DEFAULT_CONFIG,
    )
    long = calculate_single_limit(
        customer_id="T2", monthly_income=10000, income_source="payroll",
        existing_debt=0, tenor_months=36, config=DEFAULT_CONFIG,
    )
    assert long.base_limit > short.base_limit
