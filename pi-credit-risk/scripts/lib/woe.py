# -*- coding: utf-8 -*-
"""woe.py — WOE/IV computation and serialization (stage 2)."""

import numpy as np
import pandas as pd

from .io_utils import safe_rate
from .binning import ordered_labels_from_binned

EPSILON = 1e-10


def woe_iv_for_binned_feature(binned_s, target_s, feature):
    """Compute WOE / IV for a single binned feature.

    Returns a DataFrame with columns:
      feature, variable_type, bin_order, bin_label,
      sample_count, sample_rate, good_count, bad_count,
      bad_rate, overall_bad_rate, lift, woe, iv_component
    """
    total = len(target_s)
    total_bad = int(target_s.sum())
    total_good = total - total_bad
    overall_bad_rate = safe_rate(total_bad, total)
    rows = []
    variable_type = (
        'numeric_continuous'
        if isinstance(binned_s.dtype, pd.CategoricalDtype) and binned_s.cat.ordered
        else 'categorical'
    )
    temp = pd.DataFrame({
        'bin_label': binned_s.astype(str),
        'target': target_s.astype(int),
    })
    for bin_order, bin_label in enumerate(ordered_labels_from_binned(binned_s)):
        group = temp[temp['bin_label'] == str(bin_label)]
        bad = int(group['target'].sum())
        sample_count = len(group)
        good = sample_count - bad
        bad_dist = safe_rate(bad, total_bad)
        good_dist = safe_rate(good, total_good)
        woe = np.log((good_dist + EPSILON) / (bad_dist + EPSILON))
        iv_component = (good_dist - bad_dist) * woe
        bad_rate = safe_rate(bad, sample_count)
        rows.append({
            'feature': feature,
            'variable_type': variable_type,
            'bin_order': bin_order,
            'bin_label': str(bin_label),
            'sample_count': sample_count,
            'sample_rate': safe_rate(sample_count, total),
            'good_count': good,
            'bad_count': bad,
            'bad_rate': bad_rate,
            'overall_bad_rate': overall_bad_rate,
            'lift': safe_rate(bad_rate, overall_bad_rate),
            'woe': woe,
            'iv_component': iv_component,
        })
    return pd.DataFrame(rows)


def build_woe_iv(df, target, binned, feature_cols):
    """Compute WOE/IV for all features.

    Parameters
    ----------
    df           : DataFrame with target column
    target       : column name string (must exist in df)
    binned       : output of apply_bin_rules
    feature_cols : list of features to include

    Returns
    -------
    (bin_detail_df, iv_summary_df)
      bin_detail_df  → bin_detail.csv
      iv_summary_df  → used in feature_quality.csv, psi, etc.
    """
    if not isinstance(target, str) or target not in df.columns:
        raise TypeError('target must be a column name string present in df')
    detail_frames = []
    summary_rows = []
    for col in feature_cols:
        detail = woe_iv_for_binned_feature(binned[col], df[target], col)
        iv = float(detail['iv_component'].sum()) if len(detail) else 0.0
        detail_frames.append(detail)
        summary_rows.append({
            'feature': col,
            'iv': iv,
            'bin_count': int(detail['bin_label'].nunique()),
        })
    return (
        pd.concat(detail_frames, ignore_index=True),
        pd.DataFrame(summary_rows).sort_values('iv', ascending=False),
    )


def apply_woe_transform(binned, bin_detail):
    """Map binned labels to their WOE values."""
    woe_df = pd.DataFrame(index=binned.index)
    for feature, group in bin_detail.groupby('feature'):
        mapping = dict(zip(group['bin_label'].astype(str), group['woe']))
        woe_df[feature] = (
            binned[feature].astype(str).map(mapping).fillna(0.0)
        )
    return woe_df


def woe_rules_to_json(bin_detail):
    """Serialize bin_detail WOE mapping to woe_rules.json structure.

    Structure: {feature: {bin_label: woe}}
    """
    result = {}
    for feature, group in bin_detail.groupby('feature'):
        result[str(feature)] = {
            str(bl): float(w)
            for bl, w in zip(group['bin_label'], group['woe'])
        }
    return result
