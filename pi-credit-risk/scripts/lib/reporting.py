# -*- coding: utf-8 -*-
"""reporting.py — strategy table, comparison, confidence evidence, monitoring plan (stage 7/8)."""

import pandas as pd


def build_strategy_rules_table(selected_rule_ids, rules_df, strategy_id='S001',
                                default_action='reject'):
    """Build strategy_rules.csv: one row per rule in the final strategy."""
    rules_map = (
        rules_df.set_index('rule_id') if len(rules_df) else pd.DataFrame()
    )
    rows = []
    for rid in selected_rule_ids:
        r = (
            rules_map.loc[rid]
            if (len(rules_map) and rid in rules_map.index) else {}
        )
        rows.append({
            'strategy_id': strategy_id,
            'rule_id': rid,
            'action': r.get('action', default_action),
            'confidence': r.get('confidence', ''),
            'rule_readable': r.get('rule_readable', ''),
            'rule_variables': r.get('rule_variables', r.get('feature', '')),
        })
    return pd.DataFrame(rows)


def compare_strategy_simulations(before_sim, after_sim,
                                  strategy_id_before='before',
                                  strategy_id_after='after'):
    """Compare two strategy simulation results for strategy_comparison.csv."""
    metrics = [
        'hit_rate', 'hit_bad_rate', 'lift', 'pass_bad_rate',
        'captured_bad_rate', 'false_reject_good_count',
    ]

    def _get(sim, key):
        if isinstance(sim, dict):
            return float(sim.get(key, 0.0))
        return float(sim[key].iloc[0]) if hasattr(sim, '__getitem__') else 0.0

    from .io_utils import safe_rate
    EPSILON = 1e-10
    rows = []
    for m in metrics:
        bv = _get(before_sim, m)
        av = _get(after_sim, m)
        delta = av - bv
        rows.append({
            'metric': m,
            strategy_id_before: bv,
            strategy_id_after: av,
            'delta': delta,
            'relative_change': safe_rate(delta, abs(bv) + EPSILON),
        })
    return pd.DataFrame(rows)


def build_confidence_evidence(evidence_id, object_type, object_id, metric_name,
                               train_value, test_value, oot_value,
                               threshold, pass_flag, confidence, reason,
                               source_file):
    """Build one confidence_evidence row.

    Raises ValueError if any of train_value / test_value / oot_value is None.
    All three must be populated before an evidence row can support an online
    deployment conclusion.
    """
    for field, val in [
        ('train_value', train_value),
        ('test_value', test_value),
        ('oot_value', oot_value),
    ]:
        if val is None:
            raise ValueError(
                'confidence_evidence: %s is required for traceability '
                '(evidence_id=%s). Compute the metric on all three sample '
                'sets before building evidence.' % (field, evidence_id)
            )
    return {
        'evidence_id': evidence_id,
        'object_type': object_type,
        'object_id': object_id,
        'metric_name': metric_name,
        'train_value': train_value,
        'test_value': test_value,
        'oot_value': oot_value,
        'threshold': threshold,
        'pass_flag': bool(pass_flag),
        'confidence': confidence,
        'reason': reason,
        'source_file': source_file,
    }


def build_monitoring_plan(rule_ids, rule_variables=None):
    """Build monitoring_plan.csv for all selected rules.

    Each rule gets standard metric rows plus per-variable rows (if
    rule_variables dict is provided).
    """
    rule_variables = rule_variables or {}
    rows = []
    metrics = [
        ('hit_rate',       '规则触碰率',       'daily/monthly', 'relative_change_gt_30pct'),
        ('bad_rate',       '命中坏账率',       'monthly',       'relative_change_gt_30pct'),
        ('pass_bad_rate',  '通过样本坏账率',   'monthly',       'relative_change_gt_20pct'),
        ('psi',            '规则相关变量PSI',  'monthly',       'psi_gt_0.25'),
        ('coverage_rate',  '三方字段覆盖率',   'daily/monthly', 'relative_change_gt_20pct'),
        ('reject_rate',    '策略拒绝率',       'daily/monthly', 'relative_change_gt_20pct'),
    ]
    for rule_id in rule_ids:
        for metric, meaning, frequency, alert_rule in metrics:
            rows.append({
                'rule_id': rule_id,
                'metric': metric,
                'meaning': meaning,
                'frequency': frequency,
                'alert_rule': alert_rule,
            })
        for feature in rule_variables.get(rule_id, []):
            rows.append({
                'rule_id': rule_id,
                'feature': feature,
                'metric': 'missing_rate',
                'meaning': '规则变量缺失率',
                'frequency': 'daily/monthly',
                'alert_rule': 'relative_change_gt_20pct',
            })
            rows.append({
                'rule_id': rule_id,
                'feature': feature,
                'metric': 'bin_psi',
                'meaning': '规则变量分箱PSI',
                'frequency': 'monthly',
                'alert_rule': 'psi_gt_0.25',
            })
            rows.append({
                'rule_id': rule_id,
                'feature': feature,
                'metric': 'top1_rate',
                'meaning': '规则变量TOP1占比',
                'frequency': 'monthly',
                'alert_rule': 'relative_change_gt_20pct',
            })
    return pd.DataFrame(rows)
