# -*- coding: utf-8 -*-
"""quality.py — data quality profiling (stage 1)."""

import pandas as pd
from .io_utils import safe_rate


def data_quality(df, feature_cols, special_values=None):
    """Compute per-feature data quality metrics.

    Returns data_quality.csv (one row per feature).
    """
    special_values = special_values or {}
    total = len(df)
    rows = []
    for col in feature_cols:
        s = df[col]
        vc = s.value_counts(dropna=True)
        rows.append({
            'feature': col,
            'dtype': str(s.dtype),
            'sample_count': total,
            'missing_count': int(s.isna().sum()),
            'missing_rate': float(s.isna().mean()),
            'coverage_rate': float(s.notna().mean()),
            'unique_count': int(s.nunique(dropna=True)),
            'unique_rate': safe_rate(int(s.nunique(dropna=True)), total),
            'top1_value': str(vc.index[0]) if len(vc) else '',
            'top1_rate': safe_rate(int(vc.iloc[0]), total) if len(vc) else 0.0,
            'special_rate': (
                float(s.isin(special_values.get(col, [])).mean())
                if col in special_values else 0.0
            ),
            'is_constant': int(s.nunique(dropna=True)) <= 1,
            'is_high_cardinality': (
                int(s.nunique(dropna=True)) > max(50, int(total * 0.2))
            ),
        })
    return pd.DataFrame(rows)


def outlier_summary(df, feature_cols):
    """IQR-based outlier detection for numeric columns.

    Returns outlier_summary.csv.
    """
    rows = []
    for col in feature_cols:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        s = df[col].dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        rows.append({
            'feature': col,
            'lower_bound': lower,
            'upper_bound': upper,
            'outlier_rate': float(
                ((df[col] < lower) | (df[col] > upper)).mean()
            ),
        })
    return pd.DataFrame(rows)
