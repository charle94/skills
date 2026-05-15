# -*- coding: utf-8 -*-
"""test_psi.py — PSI computation and stability classification."""

import pytest
from lib.binning import build_bin_rules, apply_bin_rules
from lib.psi import psi_from_distribution, psi_by_bins
import pandas as pd
import numpy as np


def test_psi_identical_distributions_zero(tiny_df, feature_cols):
    rules = build_bin_rules(tiny_df, ['credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['credit_score']], rules)
    dist = binned['credit_score'].astype(str).value_counts(normalize=True)
    psi = psi_from_distribution(dist, dist)
    assert psi < 1e-4  # same distribution → PSI ≈ 0


def test_psi_different_distributions_positive(tiny_df):
    rng = np.random.default_rng(99)
    n = 200
    df_train = tiny_df.copy()
    # create very different OOT distribution
    df_oot = tiny_df.copy()
    df_oot['credit_score'] = rng.integers(700, 850, n).astype(float)
    rules = build_bin_rules(df_train, ['credit_score'], bins=5)
    bt = apply_bin_rules(df_train[['credit_score']], rules)
    bo = apply_bin_rules(df_oot[['credit_score']], rules)
    psi_table, _ = psi_by_bins(bt, bo, ['credit_score'])
    row = psi_table[psi_table['feature'] == 'credit_score'].iloc[0]
    assert float(row['train_oot_psi']) > 0


def test_psi_by_bins_returns_expected_columns(tiny_df):
    rules = build_bin_rules(tiny_df, ['age', 'credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['age', 'credit_score']], rules)
    summary, detail = psi_by_bins(binned, binned, ['age', 'credit_score'])
    assert set(summary.columns) >= {'feature', 'train_oot_psi', 'psi_level'}
    assert set(detail.columns) >= {'feature', 'bin_label', 'train_pct', 'oot_pct'}


def test_psi_stability_labels(tiny_df):
    rules = build_bin_rules(tiny_df, ['credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['credit_score']], rules)
    summary, _ = psi_by_bins(binned, binned, ['credit_score'])
    # Identical train/oot → stable
    assert summary.iloc[0]['psi_level'] == 'stable'


def test_psi_by_bins_with_test_set(tiny_df):
    rules = build_bin_rules(tiny_df, ['credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['credit_score']], rules)
    train = binned.head(140)
    test = binned.iloc[140:170]
    oot = binned.tail(30)
    summary, detail = psi_by_bins(train, oot, ['credit_score'], test_binned=test)
    assert 'train_test_psi' in summary.columns
    assert 'test_pct' in detail.columns
