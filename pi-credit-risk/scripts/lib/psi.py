# -*- coding: utf-8 -*-
"""psi.py — Population Stability Index (stage 3).

PSI must be computed on the training bin distribution, NOT by re-binning
train/OOT independently.  Always call psi_by_bins with the already-binned
frames (output of apply_bin_rules with the training bin_rules).
"""

import numpy as np
import pandas as pd

EPSILON = 1e-10
PSI_STABLE_THRESHOLD = 0.1
PSI_WATCH_THRESHOLD = 0.25


def psi_from_distribution(expected_dist, actual_dist):
    """PSI between two bin frequency distributions (Series with bin labels as index)."""
    all_bins = set(expected_dist.index).union(set(actual_dist.index))
    value = 0.0
    for b in all_bins:
        e = float(expected_dist.get(b, 0.0)) + EPSILON
        a = float(actual_dist.get(b, 0.0)) + EPSILON
        value += (a - e) * np.log(a / e)
    return float(value)


def psi_by_bins(train_binned, oot_binned, feature_cols, test_binned=None):
    """Compute PSI for all features using pre-binned frames.

    Returns
    -------
    (psi_summary_df, bin_psi_detail_df)
      psi_summary_df  → psi_table.csv
      bin_psi_detail_df → bin_psi_detail.csv
    """
    summary_rows = []
    detail_rows = []
    for col in feature_cols:
        train_dist = (
            train_binned[col].astype(str)
            .value_counts(normalize=True, dropna=False)
        )
        oot_dist = (
            oot_binned[col].astype(str)
            .value_counts(normalize=True, dropna=False)
        )
        train_oot_psi = psi_from_distribution(train_dist, oot_dist)
        psi_level = (
            'stable' if train_oot_psi < PSI_STABLE_THRESHOLD
            else ('watch' if train_oot_psi <= PSI_WATCH_THRESHOLD else 'unstable')
        )
        row = {
            'feature': col,
            'train_oot_psi': train_oot_psi,
            'psi': train_oot_psi,
            'psi_level': psi_level,
        }
        test_dist = None
        if test_binned is not None:
            test_dist = (
                test_binned[col].astype(str)
                .value_counts(normalize=True, dropna=False)
            )
            row['train_test_psi'] = psi_from_distribution(train_dist, test_dist)
            row['test_oot_psi'] = psi_from_distribution(test_dist, oot_dist)
        summary_rows.append(row)
        all_bins = set(train_dist.index).union(set(oot_dist.index))
        if test_dist is not None:
            all_bins = all_bins.union(set(test_dist.index))
        for bin_label in sorted(all_bins):
            train_pct = float(train_dist.get(bin_label, 0.0))
            test_pct = (
                float(test_dist.get(bin_label, 0.0))
                if test_dist is not None else None
            )
            oot_pct = float(oot_dist.get(bin_label, 0.0))
            detail_rows.append({
                'feature': col,
                'bin_label': bin_label,
                'train_pct': train_pct,
                'test_pct': test_pct,
                'oot_pct': oot_pct,
                'train_oot_delta': oot_pct - train_pct,
                'train_test_delta': (
                    None if test_pct is None else test_pct - train_pct
                ),
                'test_oot_delta': (
                    None if test_pct is None else oot_pct - test_pct
                ),
            })
    return pd.DataFrame(summary_rows), pd.DataFrame(detail_rows)
