# -*- coding: utf-8 -*-
"""single_rules.py — single-variable rule mining and cross-set evaluation (stage 5.1)."""

import pandas as pd
from .io_utils import safe_rate


def extract_single_var_rules(df_train, binned_train, target, feature_cols, bin_detail):
    """Extract single-variable candidate rules from bin_detail.

    Output columns align with decision-tree rule table so both sources can be
    merged for stage 5.2 combination mining.

    Returns single_rule_candidates.csv.
    """
    total = len(df_train)
    total_bad = int(df_train[target].sum())
    overall_bad_rate = safe_rate(total_bad, total)
    rows = []
    counter = [0]
    for feature in feature_cols:
        feat_detail = bin_detail[bin_detail['feature'] == feature]
        for _, bin_row in feat_detail.iterrows():
            counter[0] += 1
            bin_label = str(bin_row['bin_label'])
            rows.append({
                'rule_id': 'SV_R%05d' % counter[0],
                'source': 'single_var',
                'feature': feature,
                'bin_label': bin_label,
                'rule_readable': '%s in [%s]' % (feature, bin_label),
                'rule_variables': feature,
                'variable_count': 1,
                'sample_count': int(bin_row.get('sample_count', 0)),
                'good_count': int(bin_row.get('good_count', 0)),
                'bad_count': int(bin_row.get('bad_count', 0)),
                'hit_rate': float(bin_row.get('sample_rate', 0.0)),
                'bad_rate': float(bin_row.get('bad_rate', 0.0)),
                'lift': float(bin_row.get('lift', 0.0)),
                'overall_bad_rate': overall_bad_rate,
                'woe': float(bin_row.get('woe', 0.0)),
                'iv_component': float(bin_row.get('iv_component', 0.0)),
            })
    return pd.DataFrame(rows)


def build_bin_masks(binned, single_var_rules):
    """Build rule masks from a binned frame.

    Uses direct string equality on the binned column (avoids df.eval
    issues with special characters in column names).

    Each mask is True where the feature's bin label equals the rule's bin_label.
    """
    masks = {}
    for _, row in single_var_rules.iterrows():
        feature = row['feature']
        bin_label = str(row['bin_label'])
        if feature in binned.columns:
            masks[row['rule_id']] = binned[feature].astype(str) == bin_label
        else:
            masks[row['rule_id']] = pd.Series(False, index=binned.index)
    return masks


def filter_rule_candidates(rules, min_hit_rate=0.01, min_bad_count=10,
                            min_lift=1.5, max_bad_rate=None):
    """Filter candidate rules by minimum quality thresholds."""
    mask = (
        (rules['hit_rate'] >= min_hit_rate) &
        (rules['bad_count'] >= min_bad_count) &
        (rules['lift'] >= min_lift)
    )
    if max_bad_rate is not None:
        mask = mask & (rules['bad_rate'] <= max_bad_rate)
    return rules[mask].reset_index(drop=True)


def evaluate_single_var_rules_cross_set(df, binned, single_var_rules, target,
                                        sample_type_col='sample_type'):
    """Evaluate each single-variable rule on train / test / oot separately.

    Returns single_var_rule_eval.csv with columns:
      rule_id, segment, hit_rate, bad_rate, lift, pass_bad_rate,
      hit_count, bad_count, sample_count.

    Note: import simulate_rule lazily to avoid circular import.
    """
    from .simulation import simulate_rule
    masks = build_bin_masks(binned, single_var_rules)
    rows = []
    for seg in ['train', 'test', 'oot']:
        if sample_type_col in df.columns:
            sub_df = df[df[sample_type_col] == seg]
            sub_binned = binned.loc[sub_df.index]
        else:
            sub_df = df
            sub_binned = binned
        sub_masks = {
            rid: masks[rid].loc[sub_df.index]
            for rid in masks
            if rid in masks
        }
        for rule_id, mask in sub_masks.items():
            sim = simulate_rule(sub_df, mask, target, rule_id=rule_id,
                                segment=seg)
            rows.append(sim)
    return pd.DataFrame(rows)
