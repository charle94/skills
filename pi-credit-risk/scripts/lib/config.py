# -*- coding: utf-8 -*-
"""config.py — load, validate and resolve run_config.json."""

import json
import os


DEFAULTS = {
    'random_state': 42,
    'test_ratio': 0.2,
    'oot_ratio': 0.1,
    'oot_months': 3,
    'bins': 10,
    'max_levels': 20,
    'psi_stable_threshold': 0.1,
    'psi_watch_threshold': 0.25,
    'rule_min_hit_rate': 0.01,
    'rule_min_bad_count': 10,
    'rule_min_lift': 1.5,
    'max_reject_rate': 0.2,
    'combo_max_size': 2,
    'combo_top_n': 20,
    'tree_max_depth': 3,
    'tree_min_samples_leaf': 0.03,
    'tree_min_samples_split': 0.06,
    'rejected_lift': 1.5,
    'corr_threshold': 0.7,
    'special_values': {},
}

REQUIRED_FIELDS = ['run_id', 'input_csv', 'target', 'output_dir']


def load_config(path):
    """Load run_config.json and fill in defaults for missing optional fields."""
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    for key, val in DEFAULTS.items():
        cfg.setdefault(key, val)
    return cfg


def validate_config(cfg):
    """Raise ValueError for any missing required field."""
    missing = [k for k in REQUIRED_FIELDS if not cfg.get(k)]
    if missing:
        raise ValueError('run_config is missing required fields: %s' % missing)
    if not os.path.isfile(cfg['input_csv']):
        raise FileNotFoundError('input_csv not found: %s' % cfg['input_csv'])
    if cfg.get('field_meta_csv') and not os.path.isfile(cfg['field_meta_csv']):
        raise FileNotFoundError('field_meta_csv not found: %s' % cfg['field_meta_csv'])


def resolve_feature_cols(df, cfg):
    """Determine the feature column list from config or auto-infer."""
    if cfg.get('feature_cols'):
        return list(cfg['feature_cols'])
    exclude = set(cfg.get('exclude_cols') or [])
    exclude.add(cfg['target'])
    if cfg.get('id_col'):
        exclude.add(cfg['id_col'])
    if cfg.get('time_col'):
        exclude.add(cfg['time_col'])
    return [c for c in df.columns if c not in exclude]
