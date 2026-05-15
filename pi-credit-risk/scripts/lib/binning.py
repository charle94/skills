# -*- coding: utf-8 -*-
"""binning.py — numeric/categorical binning, monotonicity enforcement (stage 2).

Call order is mandatory:
  build_bin_rules  →  apply_bin_rules  →  enforce_monotonic_bins
Test/OOT frames must reuse the training bin_rules via apply_bin_rules, never
re-fit.
"""

import numpy as np
import pandas as pd

from .io_utils import safe_rate

EPSILON = 1e-10


# ---------------------------------------------------------------------------
# Rule building
# ---------------------------------------------------------------------------

def build_bin_rules(df, feature_cols, bins=10, max_levels=20,
                    special_values=None):
    """Fit binning rules on the training frame.

    Returns a dict: {col: rule_dict} suitable for apply_bin_rules.
    Persist to bin_rules.json (caller's responsibility).
    """
    special_values = special_values or {}
    rules = {}
    for col in feature_cols:
        s = df[col]
        if pd.api.types.is_numeric_dtype(s):
            regular = s.loc[~s.isna() & ~s.isin(special_values.get(col, []))]
            if regular.nunique(dropna=True) <= 1:
                cut_points = []
            else:
                try:
                    cut_points = sorted(
                        pd.qcut(regular, q=bins, duplicates='drop')
                        .cat.categories.right.astype(float).tolist()
                    )
                    cut_points = cut_points[:-1]
                except Exception:
                    cut_points = sorted(
                        pd.cut(
                            regular,
                            bins=min(bins, regular.nunique()),
                            duplicates='drop',
                        ).cat.categories.right.astype(float).tolist()
                    )[:-1]
            rules[col] = {
                'type': 'numeric',
                'variable_type': 'numeric_continuous',
                'cut_points': cut_points,
                'special_values': special_values.get(col, []),
            }
        else:
            top_values = (
                s.astype('object')
                .where(s.notna(), 'MISSING')
                .astype(str)
                .value_counts()
                .head(max_levels)
                .index.tolist()
            )
            rules[col] = {
                'type': 'categorical',
                'variable_type': 'categorical',
                'levels': top_values,
            }
    return rules


# ---------------------------------------------------------------------------
# Rule application
# ---------------------------------------------------------------------------

def ordered_numeric_categories(cuts, has_special=False):
    interval_labels = pd.IntervalIndex.from_breaks(cuts).astype(str).tolist()
    categories = ['MISSING'] + interval_labels
    if has_special:
        categories.append('SPECIAL')
    return categories


def ordered_labels_from_binned(binned_s):
    present = set(binned_s.astype(str).dropna().tolist())
    if (isinstance(binned_s.dtype, pd.CategoricalDtype)
            and binned_s.cat.ordered):
        return [
            str(label)
            for label in binned_s.cat.categories
            if str(label) in present
        ]
    return sorted(present)


def apply_bin_rules(df, bin_rules):
    """Apply pre-fitted bin_rules to any frame (train/test/OOT).

    Never re-fit on the test/OOT frame.  The result is an ordered Categorical
    for numeric columns (MISSING first, then intervals by edge value, SPECIAL
    last).
    """
    missing_cols = set(bin_rules.keys()) - set(df.columns)
    if missing_cols:
        raise KeyError(
            'bin_rules contains columns not in df: %s' % sorted(missing_cols)
        )
    binned = pd.DataFrame(index=df.index)
    for col, rule in bin_rules.items():
        s = df[col]
        if rule['type'] == 'numeric':
            result = pd.Series(index=s.index, dtype='object')
            special = rule.get('special_values', [])
            special_mask = s.isin(special) if special else pd.Series(
                False, index=s.index
            )
            missing_mask = s.isna() & (~special_mask)
            result.loc[special_mask] = 'SPECIAL'
            result.loc[missing_mask] = 'MISSING'
            cuts = [-np.inf] + list(rule.get('cut_points', [])) + [np.inf]
            regular = s.loc[~special_mask & ~missing_mask]
            result.loc[regular.index] = pd.cut(
                regular, bins=cuts, duplicates='drop'
            ).astype(str)
            categories = ordered_numeric_categories(
                cuts, has_special=bool(special)
            )
            binned[col] = pd.Categorical(
                result.fillna('MISSING'), categories=categories, ordered=True
            )
        else:
            levels = set(rule.get('levels', []))
            values = s.astype('object').where(s.notna(), 'MISSING').astype(str)
            binned[col] = values.where(values.isin(levels), 'OTHER')
    return binned


# ---------------------------------------------------------------------------
# Monotonicity check and enforcement
# ---------------------------------------------------------------------------

def monotonicity_check(bin_detail):
    """Check whether bad_rate is monotone across numeric bins.

    Returns monotonicity_check.csv.
    """
    rows = []
    for feature, group in bin_detail.groupby('feature', sort=False):
        ordered = group.copy()
        if 'bin_order' in ordered.columns:
            ordered = ordered.sort_values('bin_order')
        ordered = ordered.reset_index(drop=True)
        variable_type = (
            ordered.get('variable_type', pd.Series(['categorical'])).iloc[0]
        )
        if variable_type != 'numeric_continuous':
            rows.append({
                'feature': feature,
                'bin_count': len(ordered),
                'non_decreasing': None,
                'non_increasing': None,
                'monotonic_flag': None,
                'bad_rate_path': '',
                'reason': 'categorical feature has no natural order; skipped',
            })
            continue
        regular = ordered[
            ~ordered['bin_label'].isin(['MISSING', 'SPECIAL'])
        ].reset_index(drop=True)
        rates = regular['bad_rate'].astype(float).tolist()
        non_decreasing = all(
            rates[i] <= rates[i + 1] + EPSILON for i in range(len(rates) - 1)
        )
        non_increasing = all(
            rates[i] + EPSILON >= rates[i + 1] for i in range(len(rates) - 1)
        )
        rows.append({
            'feature': feature,
            'bin_count': len(ordered),
            'non_decreasing': non_decreasing,
            'non_increasing': non_increasing,
            'monotonic_flag': non_decreasing or non_increasing,
            'bad_rate_path': ' -> '.join(['%.4f' % x for x in rates]),
            'reason': '',
        })
    return pd.DataFrame(rows)


def merge_log_for_non_monotonic(bin_detail):
    check = monotonicity_check(bin_detail)
    rows = []
    for _, row in check[check['monotonic_flag'] == False].iterrows():  # noqa: E712
        rows.append({
            'feature': row['feature'],
            'issue': 'non_monotonic_bad_rate',
            'bad_rate_path': row['bad_rate_path'],
            'suggestion': (
                'merge adjacent bins or keep with business exception'
            ),
        })
    return pd.DataFrame(rows)


def enforce_monotonic_bins(df, binned, target, bin_rules,
                           direction='auto', min_bins=3):
    """Iteratively merge adjacent bins that violate monotonicity.

    Returns (fixed_binned, updated_bin_rules, merge_log_df).
    merge_log_df → bin_merge_log.csv
    """
    from .woe import woe_iv_for_binned_feature

    fixed = binned.copy()
    updated_rules = {k: dict(v) for k, v in bin_rules.items()}
    logs = []
    for feature in fixed.columns:
        if updated_rules.get(feature, {}).get('type') != 'numeric':
            continue
        while True:
            detail = woe_iv_for_binned_feature(
                fixed[feature], target, feature
            ).reset_index(drop=True)
            regular = detail[
                ~detail['bin_label'].isin(['MISSING', 'SPECIAL'])
            ].reset_index(drop=True)
            if len(regular) <= min_bins:
                break
            cut_points = list(
                updated_rules.get(feature, {}).get('cut_points', [])
            )
            if len(cut_points) != len(regular) - 1:
                logs.append({
                    'feature': feature,
                    'merged_from': '',
                    'removed_cut_point': '',
                    'reason': 'skip_cut_point_mismatch',
                    'direction': direction,
                })
                break
            rates = regular['bad_rate'].astype(float).tolist()
            if direction == 'auto':
                trend = 'increasing' if rates[-1] >= rates[0] else 'decreasing'
            else:
                trend = direction
            violations = []
            for i in range(len(rates) - 1):
                bad_order = (
                    (trend == 'increasing' and rates[i] > rates[i + 1] + EPSILON) or
                    (trend == 'decreasing' and rates[i] + EPSILON < rates[i + 1])
                )
                if bad_order:
                    violations.append((i, abs(rates[i] - rates[i + 1])))
            if not violations:
                break
            merge_idx = sorted(violations, key=lambda x: x[1], reverse=True)[0][0]
            left_label = regular.loc[merge_idx, 'bin_label']
            right_label = regular.loc[merge_idx + 1, 'bin_label']
            removed_cut_point = cut_points.pop(merge_idx)
            updated_rules[feature]['cut_points'] = cut_points
            fixed[feature] = apply_bin_rules(
                df[[feature]], {feature: updated_rules[feature]}
            )[feature]
            logs.append({
                'feature': feature,
                'merged_from': '%s,%s' % (left_label, right_label),
                'removed_cut_point': removed_cut_point,
                'reason': 'monotonicity_violation',
                'direction': trend,
            })
    return fixed, updated_rules, pd.DataFrame(logs)
