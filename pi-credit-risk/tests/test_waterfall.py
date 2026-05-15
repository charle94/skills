# -*- coding: utf-8 -*-
"""test_waterfall.py — waterfall evaluation (observable + full population)."""

import numpy as np
import pandas as pd
import pytest

from lib.waterfall import (
    build_waterfall_simulation, waterfall_cross_set,
    build_waterfall_simulation_full_population,
)


def _make_masks_and_rules(df):
    masks = {
        'R001': df['debt_ratio'].fillna(0) > 0.7,
        'R002': df['debt_ratio'].fillna(0) > 0.5,
        'R003': df['credit_score'].fillna(600) < 450,
    }
    return masks


def test_build_waterfall_simulation_rows(tiny_df):
    masks = _make_masks_and_rules(tiny_df)
    ordered = ['R001', 'R002', 'R003']
    wf = build_waterfall_simulation(tiny_df, ordered, masks, 'bad_flag')
    assert len(wf) == 3
    assert list(wf['waterfall_step']) == [1, 2, 3]


def test_build_waterfall_simulation_monotone_hit_count(tiny_df):
    """Cumulative OR must always increase or stay constant."""
    masks = _make_masks_and_rules(tiny_df)
    ordered = ['R001', 'R002', 'R003']
    wf = build_waterfall_simulation(tiny_df, ordered, masks, 'bad_flag')
    hit_counts = wf['hit_count'].tolist()
    for i in range(1, len(hit_counts)):
        assert hit_counts[i] >= hit_counts[i - 1]


def test_waterfall_cross_set_segments(tiny_df):
    """waterfall_cross_set must produce rows for each sample_type segment."""
    masks = _make_masks_and_rules(tiny_df)
    # Add sample_type manually
    df = tiny_df.copy()
    n = len(df)
    sample_type = ['train'] * int(n * 0.7) + ['test'] * int(n * 0.2) + ['oot'] * (n - int(n * 0.7) - int(n * 0.2))
    df['sample_type'] = sample_type
    # Realign mask indexes to match df index
    masks = {rid: df['debt_ratio'].fillna(0) > 0.7 for rid in masks}
    ordered = list(masks.keys())[:2]
    wf = waterfall_cross_set(df, ordered, masks, 'bad_flag')
    assert 'segment' in wf.columns
    assert set(wf['segment'].unique()).issubset({'train', 'test', 'oot'})


def test_build_waterfall_simulation_full_population(tiny_df_with_rejected):
    df = tiny_df_with_rejected.copy()
    masks = {
        'R001': df['debt_ratio'].fillna(0) > 0.7,
        'R002': df['credit_score'].fillna(600) < 450,
    }
    ordered = ['R001', 'R002']
    wf = build_waterfall_simulation_full_population(
        df, ordered, masks, 'bad_flag', rejected_lift=1.5
    )
    assert len(wf) == 2
    assert 'incremental_full_hit' in wf.columns
    # Full hit must be >= observable hit
    for _, row in wf.iterrows():
        assert row['full_hit_count'] >= row['observable_hit_count']


def test_waterfall_missing_rule_skipped(tiny_df):
    """Rules not in masks dict are silently skipped."""
    masks = {'R001': tiny_df['debt_ratio'].fillna(0) > 0.7}
    ordered = ['R001', 'R999']  # R999 not in masks
    wf = build_waterfall_simulation(tiny_df, ordered, masks, 'bad_flag')
    assert len(wf) == 1  # only R001
    assert wf.iloc[0]['added_rule_id'] == 'R001'
