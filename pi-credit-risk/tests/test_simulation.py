# -*- coding: utf-8 -*-
"""test_simulation.py — rule simulation (observable + full population)."""

import numpy as np
import pandas as pd
import pytest

from lib.simulation import (
    simulate_rule, simulate_rule_full_population,
    simulate_combined_rules, optimize_strategy_rules,
    assign_confidence, simulate_rules_by_month,
)


def _make_masks(df):
    """Simple masks: high-risk = bottom-third debt_ratio."""
    q = df['debt_ratio'].quantile(0.67)
    return {
        'R001': df['debt_ratio'] > q,
        'R002': df['debt_ratio'] > 0.5,
    }


def test_simulate_rule_fields(tiny_df):
    masks = _make_masks(tiny_df)
    result = simulate_rule(tiny_df, masks['R001'], 'bad_flag', rule_id='R001')
    assert result['sample_count'] == len(tiny_df)
    assert result['hit_count'] + result['pass_count'] == result['sample_count']
    assert 0.0 <= result['hit_bad_rate'] <= 1.0
    assert result['lift'] >= 0.0


def test_simulate_rule_all_reject(tiny_df):
    all_mask = pd.Series(True, index=tiny_df.index)
    result = simulate_rule(tiny_df, all_mask, 'bad_flag')
    assert result['hit_count'] == len(tiny_df)
    assert result['pass_count'] == 0
    assert result['pass_bad_rate'] == 0.0


def test_simulate_rule_full_population(tiny_df_with_rejected):
    df = tiny_df_with_rejected.copy()
    mask = df['debt_ratio'].fillna(0) > 0.6
    result = simulate_rule_full_population(
        df, mask, 'bad_flag', rejected_lift=1.5, rule_id='R001'
    )
    assert result['full_sample_count'] == len(df)
    assert result['full_hit_count'] + result['full_pass_count'] == result['full_sample_count']
    assert result['full_hit_bad_count_est'] >= 0
    assert result['reject_inference_method'] == 'default_lift_1.50'


def test_simulate_rule_full_population_segment_lift(tiny_df_with_rejected):
    df = tiny_df_with_rejected.copy()
    df['channel'] = 'A'
    mask = df['debt_ratio'].fillna(0) > 0.5
    result = simulate_rule_full_population(
        df, mask, 'bad_flag',
        rejected_lift=1.5,
        segment_col='channel',
        segment_lift_map={'A': 2.0},
        rule_id='R001'
    )
    assert 'segment_lift' in result['reject_inference_method']


def test_simulate_combined_rules(tiny_df):
    masks = _make_masks(tiny_df)
    result = simulate_combined_rules(
        tiny_df, masks, 'bad_flag',
        selected_rule_ids=['R001', 'R002'], strategy_id='S001'
    )
    assert result['strategy_id'] == 'S001'
    assert result['rule_count'] == 2
    # OR combination must hit at least as many as either individual rule
    r1_hit = int(masks['R001'].sum())
    assert result['hit_count'] >= r1_hit


def test_optimize_strategy_rules_respects_reject_rate(tiny_df):
    masks = _make_masks(tiny_df)
    candidates = pd.DataFrame([
        {'rule_id': 'R001', 'lift': 2.0, 'bad_rate': 0.3, 'action': 'reject', 'confidence': 'HIGH'},
        {'rule_id': 'R002', 'lift': 1.8, 'bad_rate': 0.25, 'action': 'reject', 'confidence': 'HIGH'},
    ])
    strategy, _ = optimize_strategy_rules(
        tiny_df, candidates, masks, 'bad_flag', max_reject_rate=0.5
    )
    # If both rules are selected, combined hit rate must still be <= 0.5
    if len(strategy) == 2:
        from lib.simulation import simulate_combined_rules
        sim = simulate_combined_rules(
            tiny_df, masks, 'bad_flag',
            selected_rule_ids=strategy['rule_id'].tolist()
        )
        assert sim['hit_rate'] <= 0.5 + 1e-6


def test_assign_confidence_high(tiny_df):
    train_sim = {'lift': 2.5, 'pass_bad_rate': 0.04}
    oot_sim = {'lift': 2.4, 'pass_bad_rate': 0.04}
    conf = assign_confidence(train_sim, oot_sim, psi_value=0.05)
    assert conf == 'HIGH'


def test_assign_confidence_low_on_big_drift(tiny_df):
    train_sim = {'lift': 3.0, 'pass_bad_rate': 0.04}
    oot_sim = {'lift': 1.0, 'pass_bad_rate': 0.12}
    conf = assign_confidence(train_sim, oot_sim, psi_value=0.3)
    assert conf == 'LOW'


def test_simulate_rules_by_month(tiny_df):
    masks = _make_masks(tiny_df)
    monthly = simulate_rules_by_month(
        tiny_df, 'bad_flag', 'apply_month', masks
    )
    assert 'segment' in monthly.columns
    assert 'ALL' in monthly['segment'].values
    # Should have one row per rule per month + one ALL row per rule
    assert len(monthly) >= len(masks) * (tiny_df['apply_month'].nunique() + 1)
