"""Validation layer tests."""
import pandas as pd
import pytest

from validation import validate_dataframe, assert_valid


def test_base_limit_valid_input_passes():
    df = pd.DataFrame({
        "customer_id": ["A1", "A2"],
        "monthly_income": [10000, 20000],
        "income_source": ["payroll", "bank_flow"],
        "existing_debt": [1000, 2000],
        "tenor_months": [12, 24],
    })
    report = validate_dataframe(df, "base_limit")
    assert report.is_valid
    assert len(report.errors) == 0


def test_missing_required_column_is_error():
    df = pd.DataFrame({
        "customer_id": ["A1"],
        "monthly_income": [10000],
    })
    report = validate_dataframe(df, "base_limit")
    assert not report.is_valid
    assert any("income_source" in e for e in report.errors)


def test_negative_income_warns_in_non_strict_mode():
    df = pd.DataFrame({
        "customer_id": ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"],
        "monthly_income": [10000] * 9 + [-100],
        "income_source": ["payroll"] * 10,
        "existing_debt": [1000] * 10,
        "tenor_months": [12] * 10,
    })
    report = validate_dataframe(df, "base_limit", strict=False)
    assert report.is_valid  # warnings only
    assert any("monthly_income" in w and "outside expected range" in w for w in report.warnings)


def test_invalid_enum_value_is_error_in_strict_mode():
    df = pd.DataFrame({
        "customer_id": ["A1"],
        "monthly_income": [10000],
        "income_source": ["invalid_source"],
        "existing_debt": [1000],
        "tenor_months": [12],
    })
    report = validate_dataframe(df, "base_limit", strict=True)
    assert not report.is_valid
    assert any("income_source" in e and "allowed set" in e for e in report.errors)


def test_assert_valid_raises_on_invalid_input():
    df = pd.DataFrame({"customer_id": ["A1"]})
    with pytest.raises(ValueError, match="Input validation failed"):
        assert_valid(df, "base_limit")


def test_dynamic_adjustment_only_requires_id_and_limit():
    df = pd.DataFrame({
        "customer_id": ["X1"],
        "current_limit": [50000],
    })
    report = validate_dataframe(df, "dynamic_adjustment")
    assert report.is_valid


def test_duplicate_customer_id_warns():
    df = pd.DataFrame({
        "customer_id": ["A1", "A1"],
        "monthly_income": [10000, 12000],
        "income_source": ["payroll", "payroll"],
        "existing_debt": [1000, 1500],
        "tenor_months": [12, 24],
    })
    report = validate_dataframe(df, "base_limit")
    assert any("duplicate" in w for w in report.warnings)


def test_empty_dataframe_is_invalid():
    df = pd.DataFrame(columns=["customer_id"])
    report = validate_dataframe(df, "base_limit")
    assert not report.is_valid
    assert any("empty" in e for e in report.errors)
