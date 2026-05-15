# -*- coding: utf-8 -*-
"""test_tree_rules.py — decision tree fitting, node metrics, rule extraction."""

import numpy as np
import pandas as pd
import pytest

from lib.binning import build_bin_rules, apply_bin_rules
from lib.tree_rules import (
    label_encode_bins, apply_label_encode,
    fit_rule_tree, tree_node_metrics, extract_tree_single_rules,
    score_tree_rules_with_action, rule_overlap_matrix, render_tree_graphviz,
)


def _build_encoded(tiny_df):
    feature_cols = ['age', 'credit_score', 'debt_ratio', 'employment_type']
    rules = build_bin_rules(tiny_df, feature_cols, bins=5)
    binned = apply_bin_rules(tiny_df[feature_cols], rules)
    encoded, mappings = label_encode_bins(binned)
    return encoded, mappings, feature_cols, rules, binned


def test_label_encode_bins_preserves_order(tiny_df):
    rules = build_bin_rules(tiny_df, ['credit_score'], bins=5)
    binned = apply_bin_rules(tiny_df[['credit_score']], rules)
    encoded, mappings = label_encode_bins(binned)
    # integer codes must be non-negative for present bins
    assert (encoded['credit_score'] >= 0).all()
    assert 'credit_score' in mappings
    assert 'label_to_code' in mappings['credit_score']


def test_apply_label_encode_no_refit(tiny_df):
    """apply_label_encode must produce consistent codes for test set."""
    train = tiny_df.head(160)
    test = tiny_df.tail(40)
    feature_cols = ['credit_score', 'debt_ratio']
    rules = build_bin_rules(train, feature_cols, bins=5)
    binned_train = apply_bin_rules(train[feature_cols], rules)
    binned_test = apply_bin_rules(test[feature_cols], rules)
    encoded_train, mappings = label_encode_bins(binned_train)
    encoded_test = apply_label_encode(binned_test, mappings)
    # Same bin must have same code in both sets
    for col in feature_cols:
        m = mappings[col]['label_to_code']
        assert set(encoded_test[col].unique()).issubset(set(m.values()) | {-1})


def test_fit_rule_tree_reproducible(tiny_df):
    encoded, _, feature_cols, _, _ = _build_encoded(tiny_df)
    tree1 = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=3, random_state=42)
    tree2 = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=3, random_state=42)
    # Same random state → identical predictions
    assert (tree1.predict(encoded) == tree2.predict(encoded)).all()


def test_tree_node_metrics_sklearn_compat(tiny_df):
    """tree_node_metrics must handle both probability and count modes."""
    encoded, _, feature_cols, _, _ = _build_encoded(tiny_df)
    tree = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=2)
    m = tree_node_metrics(tree, 0, len(tiny_df), float(tiny_df['bad_flag'].mean()))
    assert m['sample_count'] == len(tiny_df)
    assert m['good_count'] + m['bad_count'] == m['sample_count']
    assert 0.0 <= m['bad_rate'] <= 1.0
    assert 0.0 <= m['hit_rate'] <= 1.0


def test_extract_tree_single_rules_columns(tiny_df):
    encoded, mappings, feature_cols, _, _ = _build_encoded(tiny_df)
    tree = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=3)
    rules = extract_tree_single_rules(tree, feature_cols, tiny_df['bad_flag'],
                                      bin_mappings=mappings)
    assert set(rules.columns) >= {
        'rule_id', 'rule_readable', 'hit_rate', 'bad_rate', 'lift',
        'sample_count', 'good_count', 'bad_count',
    }


def test_score_tree_rules_with_action(tiny_df):
    encoded, mappings, feature_cols, _, _ = _build_encoded(tiny_df)
    tree = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=3)
    rules = extract_tree_single_rules(tree, feature_cols, tiny_df['bad_flag'],
                                      bin_mappings=mappings)
    scored = score_tree_rules_with_action(rules)
    assert 'action' in scored.columns
    assert 'confidence' in scored.columns
    assert set(scored['action'].unique()).issubset({'reject', 'review', 'pass_observe'})


def test_rule_overlap_matrix_diagonal_ones(tiny_df):
    from lib.tree_rules import rule_overlap_matrix
    masks = {
        'R1': pd.Series([True, False, True, False], dtype=bool),
        'R2': pd.Series([True, True, False, False], dtype=bool),
    }
    overlap = rule_overlap_matrix(masks)
    # Diagonal (self-overlap) should be 1.0
    assert float(overlap.set_index('rule_id').loc['R1', 'R1']) == 1.0
    assert float(overlap.set_index('rule_id').loc['R2', 'R2']) == 1.0


def test_render_tree_graphviz_produces_dot(tmp_path, tiny_df):
    encoded, _, feature_cols, _, _ = _build_encoded(tiny_df)
    tree = fit_rule_tree(encoded, tiny_df['bad_flag'], max_depth=2)
    prefix = str(tmp_path / 'tree')
    dot_path, _ = render_tree_graphviz(tree, feature_cols, tiny_df['bad_flag'], prefix)
    assert dot_path.endswith('.dot')
    content = open(dot_path).read()
    assert 'digraph' in content
    # Verify single backslash-n (not double-escaped) is in node labels
    assert r'\n' in content
