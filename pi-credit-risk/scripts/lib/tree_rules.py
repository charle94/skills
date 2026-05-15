# -*- coding: utf-8 -*-
"""tree_rules.py — decision-tree rule mining and graphviz rendering (stage 5).

Critical notes
--------------
* Tree input MUST be integer bin codes (label_encode_bins), NOT WOE values.
* Test/OOT must use apply_label_encode with the training mappings — never
  re-call label_encode_bins on test/OOT.
* sklearn ≥1.3: tree_.value stores normalized class probabilities (rows sum
  to 1); older versions store raw counts.  tree_node_metrics auto-detects.
* DOT file: '\\n' in labels must be a single backslash + n, NOT double-escaped.
"""

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, _tree

from .io_utils import safe_rate

EPSILON = 1e-10


# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------

def label_encode_bins(binned, categorical_cols=None):
    """Encode a binned frame to integers for decision-tree input.

    For ordered numeric Categoricals the encoding preserves bin order.
    Labels are always taken from the full cat.categories (not filtered by
    what is present in the current slice) so that train/test/OOT encodings
    are identical.  Unknown labels are encoded as -1.

    Returns (encoded_df, mappings_dict).
    Pass mappings_dict to apply_label_encode for test/OOT frames.
    """
    categorical_cols = set(categorical_cols or [])
    encoded = pd.DataFrame(index=binned.index)
    mappings = {}
    for col in binned.columns:
        variable_type = (
            'categorical' if col in categorical_cols
            else 'numeric_continuous'
        )
        if (isinstance(binned[col].dtype, pd.CategoricalDtype)
                and binned[col].cat.ordered):
            labels = [str(label) for label in binned[col].cat.categories]
            variable_type = 'numeric_continuous'
        else:
            labels = sorted(binned[col].astype(str).unique().tolist())
        mapping = {label: idx for idx, label in enumerate(labels)}
        encoded[col] = (
            binned[col].astype(str).map(mapping).fillna(-1).astype(int)
        )
        mappings[col] = {
            'variable_type': variable_type,
            'label_to_code': mapping,
            'code_to_label': {idx: label for label, idx in mapping.items()},
        }
    return encoded, mappings


def apply_label_encode(binned, mappings):
    """Apply pre-built label-encode mappings to a new binned frame.

    Use for test/OOT frames so integer codes are consistent with training.
    Labels absent from the original mapping are encoded as -1.
    """
    encoded = pd.DataFrame(index=binned.index)
    for col, meta in mappings.items():
        if col not in binned.columns:
            continue
        mapping = meta.get('label_to_code', {})
        encoded[col] = (
            binned[col].astype(str).map(mapping).fillna(-1).astype(int)
        )
    return encoded


# ---------------------------------------------------------------------------
# Tree fitting
# ---------------------------------------------------------------------------

def fit_rule_tree(train_x, train_y, max_depth=3,
                  min_samples_leaf=0.03, min_samples_split=0.06,
                  random_state=20260427):
    """Fit a deterministic DecisionTreeClassifier for rule mining.

    random_state is fixed; the caller can override via the config but MUST
    keep it constant across runs to guarantee reproducibility.
    """
    n = len(train_y)
    leaf_floor = (
        max(30, int(min_samples_leaf * n))
        if isinstance(min_samples_leaf, float)
        else max(30, int(min_samples_leaf))
    )
    split_floor = (
        max(50, int(min_samples_split * n))
        if isinstance(min_samples_split, float)
        else max(50, int(min_samples_split))
    )
    tree = DecisionTreeClassifier(
        criterion='entropy',
        max_depth=max_depth,
        min_samples_leaf=leaf_floor,
        min_samples_split=split_floor,
        random_state=random_state,
    )
    tree.fit(train_x, train_y.astype(int))
    return tree


# ---------------------------------------------------------------------------
# Node metrics (sklearn ≥1.3 compatible)
# ---------------------------------------------------------------------------

def tree_node_metrics(tree, node_id, total_count, overall_bad_rate):
    """Compute per-node metrics from a fitted DecisionTreeClassifier.

    sklearn ≥1.3 stores tree_.value as normalized class probabilities
    (rows sum to 1); older versions store raw (possibly weighted) class
    counts.  We auto-detect via row sum and recover counts using
    weighted_n_node_samples so that good_count + bad_count == sample_count
    (rounded) in both regimes.
    """
    sample = int(tree.tree_.n_node_samples[node_id])
    weighted_n = float(tree.tree_.weighted_n_node_samples[node_id])
    raw = tree.tree_.value[node_id][0]
    raw_sum = float(np.sum(raw))
    if abs(raw_sum - 1.0) < 1e-6:
        # Probability mode: multiply by weighted samples to recover counts.
        good = int(round(float(raw[0]) * weighted_n))
        bad = int(round(float(raw[1]) * weighted_n)) if len(raw) > 1 else 0
    else:
        # Count mode (older sklearn or sample_weight provided as counts).
        good = int(round(float(raw[0])))
        bad = int(round(float(raw[1]))) if len(raw) > 1 else 0
    bad_rate = safe_rate(bad, good + bad)
    hit_rate = safe_rate(sample, total_count)
    return {
        'sample_count': sample,
        'good_count': good,
        'bad_count': bad,
        'hit_rate': hit_rate,
        'bad_rate': bad_rate,
        'lift': safe_rate(bad_rate, overall_bad_rate),
    }


# ---------------------------------------------------------------------------
# Rule extraction
# ---------------------------------------------------------------------------

def decode_condition(feature, operator, threshold, bin_mappings):
    meta = bin_mappings.get(feature, {})
    mapping = meta.get('code_to_label', {})
    if not mapping:
        return '%s %s %.6f' % (feature, operator, threshold)
    if operator == '<=':
        labels = [
            label for code, label in mapping.items()
            if code <= int(np.floor(threshold))
        ]
    else:
        labels = [
            label for code, label in mapping.items()
            if code > int(np.floor(threshold))
        ]
    note = (
        ' (categorical label-code split; no ordinal meaning)'
        if meta.get('variable_type') == 'categorical' else ''
    )
    return '%s in [%s]%s' % (feature, ', '.join([str(x) for x in labels]), note)


def extract_tree_single_rules(tree, feature_names, train_y, bin_mappings=None):
    """Extract one rule per leaf node from a fitted DecisionTree.

    Returns decision_tree_rules.csv sorted by lift, bad_rate, hit_rate desc.
    """
    bin_mappings = bin_mappings or {}
    total_count = len(train_y)
    overall_bad_rate = float(pd.Series(train_y).mean())
    rows = []

    def walk(node_id, path):
        left_id = tree.tree_.children_left[node_id]
        right_id = tree.tree_.children_right[node_id]
        if left_id == _tree.TREE_LEAF and right_id == _tree.TREE_LEAF:
            metrics = tree_node_metrics(
                tree, node_id, total_count, overall_bad_rate
            )
            variables = sorted(set([p['feature'] for p in path]))
            rule_expression = (
                ' AND '.join([p['expr'] for p in path]) if path else 'ALL'
            )
            rule_readable = (
                ' AND '.join([p['readable'] for p in path]) if path else 'ALL'
            )
            rows.append({
                'rule_id': 'DT_R%05d' % (len(rows) + 1),
                'node_id': int(node_id),
                'rule_expression': rule_expression,
                'rule_readable': rule_readable,
                'rule_variables': ','.join(variables),
                'variable_count': len(variables),
                'sample_count': metrics['sample_count'],
                'good_count': metrics['good_count'],
                'bad_count': metrics['bad_count'],
                'hit_rate': metrics['hit_rate'],
                'bad_rate': metrics['bad_rate'],
                'lift': metrics['lift'],
                'overall_bad_rate': overall_bad_rate,
            })
            return
        feature = feature_names[tree.tree_.feature[node_id]]
        threshold = tree.tree_.threshold[node_id]
        walk(left_id, path + [{
            'feature': feature,
            'expr': '%s <= %.6f' % (feature, threshold),
            'readable': decode_condition(
                feature, '<=', threshold, bin_mappings
            ),
        }])
        walk(right_id, path + [{
            'feature': feature,
            'expr': '%s > %.6f' % (feature, threshold),
            'readable': decode_condition(
                feature, '>', threshold, bin_mappings
            ),
        }])

    walk(0, [])
    rules = pd.DataFrame(rows)
    if len(rules):
        rules = rules.sort_values(
            ['lift', 'bad_rate', 'hit_rate'],
            ascending=[False, False, False],
        ).reset_index(drop=True)
    return rules


def score_tree_rules_with_action(rules, min_hit_rate=0.01, min_bad_count=10,
                                  high_lift=2.0, medium_lift=1.5):
    scored = rules.copy()
    actions = []
    confidences = []
    for _, row in scored.iterrows():
        if (row['hit_rate'] >= 0.03 and row['bad_count'] >= 30
                and row['lift'] >= high_lift):
            actions.append('reject')
            confidences.append('HIGH')
        elif (row['hit_rate'] >= min_hit_rate
              and row['bad_count'] >= min_bad_count
              and row['lift'] >= medium_lift):
            actions.append('review')
            confidences.append('MEDIUM')
        else:
            actions.append('pass_observe')
            confidences.append('LOW')
    scored['action'] = actions
    scored['confidence'] = confidences
    return scored


def rule_overlap_matrix(rule_masks):
    """Build a pairwise overlap fraction matrix for rule_overlap_matrix.csv."""
    rule_ids = list(rule_masks.keys())
    rows = []
    for left in rule_ids:
        row = {'rule_id': left}
        left_mask = rule_masks[left]
        left_count = int(left_mask.sum())
        for right in rule_ids:
            right_mask = rule_masks[right]
            overlap = int((left_mask & right_mask).sum())
            row[right] = safe_rate(overlap, left_count)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Graphviz rendering
# ---------------------------------------------------------------------------

def render_tree_graphviz(tree, feature_names, train_y, output_prefix):
    """Render tree to .dot (and optionally .png) with bad_rate coloring.

    Node labels use DOT's '\\n' line-break.  We write a literal backslash-n
    into the file — NOT double-escaped — so graphviz wraps lines correctly.
    Leaf nodes get a bold border (penwidth=2).  Fill color ranges from green
    (safe) to red (risky) based on bad_rate / overall_bad_rate.
    """
    total_count = len(train_y)
    overall_bad_rate = float(pd.Series(train_y).mean())
    try:
        import graphviz
    except Exception as exc:
        graphviz = None
        print('graphviz import failed:', exc)
    lines = [
        'digraph Tree {',
        'node [shape=box, style="filled,rounded", fontname="Microsoft YaHei"];',
        'edge [fontname="Microsoft YaHei"];',
    ]

    def dot_escape_label(value):
        return str(value).replace('"', '\\"')

    def node_fillcolor(bad_rate):
        ratio = (
            0.5 if overall_bad_rate <= 0
            else min(bad_rate / (overall_bad_rate * 2.0), 1.0)
        )
        ratio = max(0.0, ratio)
        hue = (1.0 - ratio) * 0.33
        return '%.3f %.3f %.3f' % (hue, 0.35, 1.0)

    def label(node_id, m):
        return (
            r'node=%d\nsample=%d\ngood=%d bad=%d\n'
            r'hit=%.2f%% bad_rate=%.2f%% lift=%.3f'
        ) % (
            node_id, m['sample_count'], m['good_count'], m['bad_count'],
            m['hit_rate'] * 100, m['bad_rate'] * 100, m['lift'],
        )

    def walk(node_id):
        m = tree_node_metrics(tree, node_id, total_count, overall_bad_rate)
        left_id = tree.tree_.children_left[node_id]
        right_id = tree.tree_.children_right[node_id]
        is_leaf = (left_id == _tree.TREE_LEAF and right_id == _tree.TREE_LEAF)
        attrs = 'label="%s", fillcolor="%s"' % (
            dot_escape_label(label(node_id, m)), node_fillcolor(m['bad_rate'])
        )
        if is_leaf:
            attrs += ', penwidth=2'
        lines.append('%d [%s];' % (node_id, attrs))
        if is_leaf:
            return
        feature = feature_names[tree.tree_.feature[node_id]]
        threshold = tree.tree_.threshold[node_id]
        lines.append('%d -> %d [label="%s <= %.6f"];' % (
            node_id, left_id, dot_escape_label(feature), threshold
        ))
        lines.append('%d -> %d [label="%s > %.6f"];' % (
            node_id, right_id, dot_escape_label(feature), threshold
        ))
        walk(left_id)
        walk(right_id)

    walk(0)
    lines.append('}')
    dot_path = output_prefix + '.dot'
    with open(dot_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    png_path = ''
    if graphviz is not None:
        try:
            src = graphviz.Source('\n'.join(lines), format='png')
            png_path = src.render(output_prefix, cleanup=True)
        except Exception as exc:
            print('graphviz png render failed:', exc)
    return dot_path, png_path
