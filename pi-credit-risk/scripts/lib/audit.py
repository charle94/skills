# -*- coding: utf-8 -*-
"""audit.py — field availability and data-leakage audit (stage 0.5)."""

import pandas as pd


RISKY_KEYWORDS = [
    'overdue', 'dpd', 'due_date', 'm0', 'm1', 'm2', 'ever_30', 'ever30',
    'collection', 'write_off', 'repay', 'repayment', 'settle', 'default',
    'delinquency', '逾期', '逾期天数', '逾期金额', '催收', '还款', '核销',
    '坏账', '违约', '放款后', '审批结果', '人工审核', '拒绝原因', '贷后', '结清',
]


def check_time_leakage(available_time, decision_time):
    if available_time in (None, '') or decision_time in (None, ''):
        return False
    try:
        return pd.to_datetime(available_time) > pd.to_datetime(decision_time)
    except Exception:
        return False


def audit_fields(feature_cols, field_meta=None, decision_time=None):
    """Audit each feature for leakage risk and data-availability issues.

    Parameters
    ----------
    feature_cols : list[str]
    field_meta   : dict mapping feature name -> dict with keys:
                   source, meaning, available_time, pre_decision_available,
                   post_loan_field, decision_time
    decision_time : str ISO date used as fallback when field_meta has no
                   per-column decision_time.

    Returns
    -------
    pd.DataFrame — field_audit.csv (one row per feature)
    """
    field_meta = field_meta or {}
    rows = []
    for col in feature_cols:
        meta = field_meta.get(col, {})
        text = (
            col + ' ' +
            str(meta.get('meaning', '')) + ' ' +
            str(meta.get('available_time', ''))
        ).lower()
        keyword_hit = [kw for kw in RISKY_KEYWORDS if kw.lower() in text]
        pre_decision_available = bool(meta.get('pre_decision_available', True))
        field_decision_time = meta.get('decision_time', decision_time)
        time_leakage_flag = check_time_leakage(
            meta.get('available_time', ''), field_decision_time
        )
        leakage_flag = (
            bool(keyword_hit) or
            (not pre_decision_available) or
            bool(meta.get('post_loan_field', False)) or
            time_leakage_flag
        )
        rows.append({
            'feature': col,
            'source': meta.get('source', ''),
            'meaning': meta.get('meaning', ''),
            'available_time': meta.get('available_time', ''),
            'pre_decision_available': pre_decision_available,
            'post_loan_field': bool(meta.get('post_loan_field', False)),
            'keyword_hit': ','.join(keyword_hit),
            'time_leakage_flag': time_leakage_flag,
            'leakage_flag': leakage_flag,
            'decision': 'drop' if leakage_flag else 'keep',
        })
    return pd.DataFrame(rows)
