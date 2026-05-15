# -*- coding: utf-8 -*-
"""test_binning_woe.py — binning, WOE/IV, monotonicity."""

import numpy as np
import pandas as pd
import pytest

from lib.binning import (
    build_bin_rules, apply_bin_rules, enforce_monotonic_bins,
    monotonicity_check, ordered_numeric_categories, ordered_labels_from_binned,
)
from lib.woe import woe_iv_for_binned_feature, build_woe_iv, woe_rules_to_json


def test_build_bin_rules_numeric(tiny_df, feature_cols):
    train = tiny_df[tiny_df['apply_month'] <= '2023-08']
    rules = build_bin_rules(train, ['age', 'credit_score', 'debt_ratio'], bins=5)
    assert 'age' in rules
    assert rules['age']['type'] == 'numeric'
    assert isinstance(rules['age']['cut_points'], list)


def test_build_bin_rules_categorical(tiny_df, feature_cols):
    train = tiny_df
    rules = build_bin_rules(train, ['employment_type'])
    assert rules['employment_type']['type'] == 'categorical'
    assert set(rules['employment_type']['levels']).issubset({'A', 'B', 'C'})


def test_apply_bin_rules_no_refitting(tiny_df, feature_cols):
    """apply_bin_rules must work on test set without re-fitting."""
    train = tiny_df.head(160)
    test = tiny_df.tail(40)
    rules = build_bin_rules(train, feature_cols, bins=5)
    binned_train = apply_bin_rules(train[feature_cols], rules)
    binned_test = apply_bin_rules(test[feature_cols], rules)
    # Categories must be identical (same bin rules used)
    for col in ['age', 'credit_score', 'debt_ratio']:
        assert list(binned_train[col].cat.categories) == list(binned_test[col].cat.categories)


def test_apply_bin_rules_missing_col_raises(tiny_df):
    rules = build_bin_rules(tiny_df, ['age'], bins=5)
    rules['nonexistent_col'] = {'type': 'numeric', 'cut_points': []}
    with pytest.raises(KeyError):
        apply_bin_rules(tiny_df[['age']], rules)


def test_apply_bin_rules_missing_values(tiny_df):
    df = tiny_df.copy()
    df.loc[0, 'age'] = np.nan
    rules = build_bin_rules(df, ['age'], bins=5)
    binned = apply_bin_rules(df[['age']], rules)
    assert 'MISSING' in binned['age'].cat.categories
    assert binned['age'].iloc[0] == 'MISSING'


def test_woe_iv_for_binned_feature(tiny_df, feature_cols):
    rules = build_bin_rules(tiny_df, ['age', 'credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['age', 'credit_score']], rules)
    detail = woe_iv_for_binned_feature(binned['credit_score'], tiny_df['bad_flag'], 'credit_score')
    assert set(detail.columns) >= {'feature', 'bin_label', 'woe', 'iv_component', 'bad_rate'}
    assert (detail['iv_component'] >= 0).all()


def test_build_woe_iv_string_target(tiny_df):
    """build_woe_iv must accept target as a string column name."""
    rules = build_bin_rules(tiny_df, ['age', 'credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['age', 'credit_score']], rules)
    bin_detail, iv_summary = build_woe_iv(tiny_df, 'bad_flag', binned, ['age', 'credit_score'])
    assert 'iv' in iv_summary.columns
    assert iv_summary['iv'].notna().all()


def test_build_woe_iv_series_target_raises(tiny_df):
    """build_woe_iv must raise TypeError when target is not a string."""
    rules = build_bin_rules(tiny_df, ['age'], bins=5)
    binned = apply_bin_rules(tiny_df[['age']], rules)
    with pytest.raises(TypeError):
        build_woe_iv(tiny_df, tiny_df['bad_flag'], binned, ['age'])


def test_monotonicity_check_all_numeric(tiny_df):
    rules = build_bin_rules(tiny_df, ['credit_score', 'debt_ratio'], bins=5)
    binned = apply_bin_rules(tiny_df[['credit_score', 'debt_ratio']], rules)
    _, iv_summary = build_woe_iv(tiny_df, 'bad_flag', binned, ['credit_score', 'debt_ratio'])
    from lib.woe import build_woe_iv as bwi
    bin_detail, _ = bwi(tiny_df, 'bad_flag', binned, ['credit_score', 'debt_ratio'])
    check = monotonicity_check(bin_detail)
    assert set(check.columns) >= {'feature', 'monotonic_flag'}


def test_enforce_monotonic_bins_reduces_violations(tiny_df):
    rules = build_bin_rules(tiny_df, ['credit_score'], bins=10)
    binned = apply_bin_rules(tiny_df[['credit_score']], rules)
    fixed_binned, updated_rules, merge_log = enforce_monotonic_bins(
        tiny_df, binned, tiny_df['bad_flag'], rules, min_bins=2
    )
    from lib.woe import build_woe_iv as bwi
    bin_detail, _ = bwi(tiny_df, 'bad_flag', fixed_binned, ['credit_score'])
    check = monotonicity_check(bin_detail)
    row = check[check['feature'] == 'credit_score'].iloc[0]
    assert row['monotonic_flag'] in (True, None)


def test_woe_rules_to_json_structure(tiny_df):
    rules = build_bin_rules(tiny_df, ['age'], bins=5)
    binned = apply_bin_rules(tiny_df[['age']], rules)
    bin_detail, _ = build_woe_iv(tiny_df, 'bad_flag', binned, ['age'])
    woe_json = woe_rules_to_json(bin_detail)
    assert isinstance(woe_json, dict)
    assert 'age' in woe_json
    for v in woe_json['age'].values():
        assert isinstance(v, float)
