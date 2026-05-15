# -*- coding: utf-8 -*-
"""samples.py — sample scope, split, and observable/rejected separation."""

import pandas as pd
from sklearn.model_selection import train_test_split

from .io_utils import safe_rate


def split_observable_sample(df, target):
    """Split df into (observable, rejected) by whether target is null.

    Variable evaluation, WOE/IV, KS/AUC, PSI and decision-tree mining run on
    the observable frame. Rule simulation must additionally feed the full
    frame (observable + rejected) into simulate_rule_full_population so that
    pass-through and reject-inference effects are captured.
    """
    observable = df[df[target].notna()].copy()
    rejected = df[df[target].isna()].copy()
    return observable, rejected


def validate_binary_target(df, target):
    """Validate that observable target is binary 0/1.

    Null rows are treated as rejected/unobservable and skipped here.
    """
    values = sorted(pd.Series(df[target]).dropna().unique().tolist())
    if values != [0, 1]:
        raise ValueError(
            'target must be binary 0/1 on observable rows, got: %s' % values
        )


def sample_profile(df, target, time_col=None, sample_type_col='sample_type'):
    rows = [
        {
            'segment': 'ALL',
            'sample_count': len(df),
            'bad_count': int(df[target].sum()),
            'bad_rate': float(df[target].mean()),
        }
    ]
    if sample_type_col in df.columns:
        for sample_type, group in df.groupby(sample_type_col):
            rows.append({
                'segment': str(sample_type),
                'sample_count': len(group),
                'bad_count': int(group[target].sum()),
                'bad_rate': float(group[target].mean()),
            })
    if time_col and time_col in df.columns:
        for period, group in df.groupby(time_col):
            rows.append({
                'segment': str(period),
                'sample_count': len(group),
                'bad_count': int(group[target].sum()),
                'bad_rate': float(group[target].mean()),
            })
    return pd.DataFrame(rows)


def split_samples(df, target, time_col=None, oot_months=3, test_ratio=0.2,
                  oot_ratio=0.1, random_state=42, sample_type_col='sample_type'):
    """Split observable rows into train/test/oot.

    Call only on the observable frame (target not null); rejected rows have no
    sample_type.  Caller is responsible for filtering with
    split_observable_sample first.
    """
    if df[target].isna().any():
        raise ValueError(
            'split_samples requires non-null target; '
            'call split_observable_sample first.'
        )
    result = df.copy()
    log_rows = []
    if time_col and time_col in result.columns:
        periods = sorted(pd.Series(result[time_col]).dropna().unique().tolist())
        if len(periods) > oot_months:
            oot_periods = set(periods[-oot_months:])
            base_idx = result.index[~result[time_col].isin(oot_periods)]
            oot_idx = result.index[result[time_col].isin(oot_periods)]
            ordered_base = result.loc[base_idx].sort_values(time_col)
            test_size = int(round(len(ordered_base) * test_ratio))
            test_idx = ordered_base.index[-test_size:] if test_size else []
            train_idx = ordered_base.index.difference(test_idx)
            method = 'time_oot_time_test'
        else:
            train_idx, test_idx, oot_idx = stratified_random_split(
                result, target, test_ratio, oot_ratio, random_state
            )
            method = 'fallback_stratified_random_insufficient_periods'
    else:
        train_idx, test_idx, oot_idx = stratified_random_split(
            result, target, test_ratio, oot_ratio, random_state
        )
        method = 'stratified_random_no_time_col'
    result[sample_type_col] = 'train'
    result.loc[test_idx, sample_type_col] = 'test'
    result.loc[oot_idx, sample_type_col] = 'oot'
    for sample_type, group in result.groupby(sample_type_col):
        log_rows.append({
            'sample_type': sample_type,
            'sample_count': len(group),
            'sample_rate': safe_rate(len(group), len(result)),
            'bad_count': int(group[target].sum()),
            'bad_rate': float(group[target].mean()),
            'split_method': method,
            'random_state': random_state,
        })
    return result, pd.DataFrame(log_rows)


def stratified_random_split(df, target, test_ratio=0.2, oot_ratio=0.1,
                             random_state=42):
    rest_idx, test_idx = train_test_split(
        df.index, test_size=test_ratio,
        stratify=df[target], random_state=random_state,
    )
    rest = df.loc[rest_idx]
    relative_oot_ratio = safe_rate(oot_ratio, 1.0 - test_ratio)
    train_idx, oot_idx = train_test_split(
        rest.index, test_size=relative_oot_ratio,
        stratify=rest[target], random_state=random_state,
    )
    return train_idx, test_idx, oot_idx


def get_sample(df, sample_type_col='sample_type', label='train'):
    if sample_type_col not in df.columns:
        print(
            'WARNING: %s missing; using all rows as train, '
            'risk accepted by operator' % sample_type_col
        )
        return df.copy()
    return df[df[sample_type_col] == label].copy()


def infer_feature_cols(df, target, id_col=None, time_col=None,
                       exclude_cols=None):
    excluded = set(exclude_cols or [])
    excluded.add(target)
    if id_col:
        excluded.add(id_col)
    if time_col:
        excluded.add(time_col)
    return [c for c in df.columns if c not in excluded]
