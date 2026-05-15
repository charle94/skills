# -*- coding: utf-8 -*-
"""conftest.py — shared fixtures for all pi-credit-risk tests."""

import sys
import os

import numpy as np
import pandas as pd
import pytest

# Add scripts/ to sys.path so lib can be imported
_SCRIPTS = os.path.join(os.path.dirname(__file__), '..', 'scripts')
if _SCRIPTS not in sys.path:
    sys.path.insert(0, os.path.abspath(_SCRIPTS))


@pytest.fixture
def tiny_df():
    """200-row observable-only synthetic dataset (no nulls in target)."""
    rng = np.random.default_rng(0)
    n = 200
    age = rng.integers(20, 55, n).astype(float)
    score = rng.integers(300, 850, n).astype(float)
    ratio = rng.uniform(0.0, 0.9, n)
    etype = rng.choice(['A', 'B', 'C'], n)
    log_odds = -2.0 + (-0.003 * score) + (1.5 * ratio)
    prob = 1.0 / (1.0 + np.exp(-log_odds))
    bad = (rng.random(n) < prob).astype(int)
    months = ['2023-%02d' % m for m in range(1, 13)]
    month = rng.choice(months, n)
    return pd.DataFrame({
        'app_id': ['A%04d' % i for i in range(n)],
        'apply_month': month,
        'age': age,
        'credit_score': score,
        'debt_ratio': ratio,
        'employment_type': etype,
        'bad_flag': bad,
    })


@pytest.fixture
def tiny_df_with_rejected(tiny_df):
    """Like tiny_df but with 10% rejected rows (bad_flag = NaN)."""
    df = tiny_df.copy()
    rng = np.random.default_rng(7)
    mask = rng.random(len(df)) < 0.10
    df.loc[mask, 'bad_flag'] = np.nan
    return df


@pytest.fixture
def feature_cols():
    return ['age', 'credit_score', 'debt_ratio', 'employment_type']
