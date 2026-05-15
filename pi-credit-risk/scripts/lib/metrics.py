# -*- coding: utf-8 -*-
"""metrics.py — KS / AUC / correlation / drop-reason aggregation (stage 4)."""

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .io_utils import safe_rate

EPSILON = 1e-10
PSI_STABLE_THRESHOLD = 0.1
PSI_WATCH_THRESHOLD = 0.25


def ks_score(score, target):
    temp = (
        pd.DataFrame({'score': score, 'target': target})
        .dropna()
        .sort_values('score')
    )
    total_bad = float(temp['target'].sum())
    total_good = float(len(temp) - temp['target'].sum())
    if total_bad == 0 or total_good == 0:
        return np.nan
    temp['cum_bad'] = temp['target'].cumsum() / total_bad
    temp['cum_good'] = (1 - temp['target']).cumsum() / total_good
    return float((temp['cum_bad'] - temp['cum_good']).abs().max())


def feature_quality_from_woe(woe_df, target_s, iv_summary):
    """Compute IV / KS / AUC per feature from WOE-transformed data.

    WOE convention here is "higher WOE -> lower risk".
    roc_auc_score(y, woe) measures the probability that a good sample ranks
    above a bad sample.  We fold the score with max(auc, 1-auc) so the
    reported AUC is always >= 0.5 and reflects discriminative power regardless
    of sign convention.

    Returns feature_quality.csv sorted by IV descending.
    """
    rows = []
    iv_map = dict(zip(iv_summary['feature'], iv_summary['iv']))
    for col in woe_df.columns:
        score = woe_df[col].fillna(0.0)
        try:
            raw_auc = float(roc_auc_score(target_s, score))
            auc = max(raw_auc, 1.0 - raw_auc)
        except Exception:
            auc = np.nan
        rows.append({
            'feature': col,
            'iv': iv_map.get(col, 0.0),
            'ks': ks_score(score, target_s),
            'auc': auc,
        })
    return pd.DataFrame(rows).sort_values('iv', ascending=False)


def feature_correlation(woe_df, iv_summary, threshold=0.7):
    """Identify high-correlation pairs and recommend the lower-IV to drop.

    Returns feature_correlation.csv.
    """
    corr = woe_df.corr(method='spearman').abs()
    iv_map = dict(zip(iv_summary['feature'], iv_summary['iv']))
    rows = []
    cols = list(corr.columns)
    for i, left in enumerate(cols):
        for right in cols[i + 1:]:
            value = float(corr.loc[left, right])
            if value >= threshold:
                drop_feature = (
                    left if iv_map.get(left, 0.0) < iv_map.get(right, 0.0)
                    else right
                )
                rows.append({
                    'feature_left': left,
                    'feature_right': right,
                    'spearman_corr': value,
                    'suggest_drop': drop_feature,
                    'reason': 'high_correlation',
                })
    return pd.DataFrame(rows)


def build_feature_drop_reason(quality_df=None, leakage_df=None,
                               corr_df=None, psi_df=None, manual_drops=None):
    """Aggregate feature drop reasons from all stages.

    Parameters
    ----------
    quality_df   : output of data_quality()
    leakage_df   : output of audit_fields()
    corr_df      : output of feature_correlation()
    psi_df       : summary output of psi_by_bins()
    manual_drops : list of {'feature': ..., 'reason': ...}

    Returns
    -------
    feature_drop_reason.csv
    """
    rows = []
    if quality_df is not None:
        for _, r in quality_df.iterrows():
            if r.get('is_constant'):
                rows.append({
                    'feature': r['feature'],
                    'drop_stage': 'data_quality',
                    'drop_reason': 'constant_feature',
                })
            elif float(r.get('missing_rate', 0)) >= 0.9:
                rows.append({
                    'feature': r['feature'],
                    'drop_stage': 'data_quality',
                    'drop_reason': 'missing_rate_ge_90pct',
                })
    if leakage_df is not None:
        for _, r in leakage_df[
            leakage_df.get('decision', pd.Series(dtype=str)) == 'drop'
        ].iterrows():
            kw = str(r.get('keyword_hit', ''))
            reason = (
                kw if kw
                else ('time_leakage' if r.get('time_leakage_flag')
                      else 'post_loan_field')
            )
            rows.append({
                'feature': r['feature'],
                'drop_stage': 'leakage_audit',
                'drop_reason': reason,
            })
    if corr_df is not None:
        for _, r in corr_df.iterrows():
            keep = (
                r['feature_left'] if r['suggest_drop'] == r['feature_right']
                else r['feature_right']
            )
            rows.append({
                'feature': r['suggest_drop'],
                'drop_stage': 'correlation',
                'drop_reason': 'high_corr_with_%s_spearman=%.3f' % (
                    keep, r['spearman_corr']
                ),
            })
    if psi_df is not None and 'psi_level' in psi_df.columns:
        for _, r in psi_df[psi_df['psi_level'] == 'unstable'].iterrows():
            rows.append({
                'feature': r['feature'],
                'drop_stage': 'psi_stability',
                'drop_reason': 'psi_unstable_%.4f' % float(
                    r.get('train_oot_psi', 0)
                ),
            })
    for item in (manual_drops or []):
        rows.append({
            'feature': item['feature'],
            'drop_stage': 'manual',
            'drop_reason': (
                item.get('reason') or 'manual_exclude_reason_required'
            ),
        })
    return pd.DataFrame(rows)
