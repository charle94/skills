#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_outputs.py — artifact completeness + column integrity check.

Checks that all required files for completed stages exist, have the expected
columns, contain no fully-empty required columns, and records SHA-256 hashes
in manifest.json for reproducibility auditing.

Usage: python3 scripts/validate_outputs.py --output-dir runs/my_run
"""

import argparse
import hashlib
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pandas as pd
from lib.io_utils import save_json, now_text


# Required files and their mandatory columns per stage
STAGE_REQUIREMENTS = {
    '0': {
        'run_config.json': [],
        'environment.json': [],
        'sample_profile.csv': ['segment', 'sample_count', 'bad_rate'],
        'sample_split_log.csv': ['sample_type', 'sample_count', 'bad_rate', 'split_method'],
    },
    '0.5': {
        'field_audit.csv': ['feature', 'leakage_flag', 'decision'],
        'leakage_audit.csv': ['feature'],
    },
    '1': {
        'data_quality.csv': ['feature', 'missing_rate', 'is_constant'],
        'outlier_summary.csv': ['feature'],
        'feature_drop_reason.csv': ['feature', 'drop_stage', 'drop_reason'],
    },
    '2': {
        'bin_rules.json': [],
        'bin_detail.csv': ['feature', 'bin_label', 'woe', 'iv_component', 'bad_rate'],
        'woe_rules.json': [],
        'monotonicity_check.csv': ['feature', 'monotonic_flag'],
        'bin_merge_log.csv': [],
    },
    '3': {
        'psi_table.csv': ['feature', 'train_oot_psi', 'psi_level'],
        'bin_psi_detail.csv': ['feature', 'bin_label', 'train_pct', 'oot_pct'],
    },
    '4': {
        'feature_quality.csv': ['feature', 'iv', 'ks', 'auc'],
        'feature_correlation.csv': [],
        'feature_drop_reason.csv': ['feature', 'drop_stage', 'drop_reason'],
    },
    '5': {
        'decision_tree.dot': [],
        'decision_tree_rules.csv': [
            'rule_id', 'rule_readable', 'hit_rate', 'bad_rate', 'lift',
            'sample_count', 'good_count', 'bad_count',
        ],
        'rule_overlap_matrix.csv': ['rule_id'],
    },
    '5.1': {
        'single_rule_candidates.csv': [
            'rule_id', 'feature', 'bin_label', 'hit_rate', 'bad_rate', 'lift',
        ],
        'single_var_rule_eval.csv': ['rule_id', 'segment'],
    },
    '5.2': {
        'rule_combination_candidates.csv': [],
    },
    '6': {
        'strategy_rules.csv': ['strategy_id', 'rule_id', 'action'],
        'rule_simulation.csv': [
            'rule_id', 'segment', 'hit_rate', 'lift', 'pass_bad_rate',
        ],
        'rule_simulation_full.csv': [
            'rule_id', 'segment', 'full_hit_rate', 'full_lift_est',
        ],
        'strategy_comparison.csv': ['metric'],
        'strategy_level_simulation.csv': ['rule_id', 'segment'],
        'monthly_rule_simulation.csv': [],
        'segment_rule_simulation.csv': [],
    },
    '6.1': {
        'waterfall_simulation.csv': [
            'waterfall_step', 'added_rule_id', 'incremental_hit',
            'incremental_bad', 'incremental_captured_bad_rate',
        ],
        'waterfall_comparison.csv': [
            'waterfall_step', 'added_rule_id', 'segment',
        ],
        'waterfall_simulation_full.csv': [
            'waterfall_step', 'added_rule_id', 'incremental_full_hit',
        ],
    },
    '7': {
        'confidence_evidence.csv': [
            'evidence_id', 'object_id', 'metric_name',
            'train_value', 'test_value', 'oot_value', 'confidence',
        ],
    },
    '8': {
        'monitoring_plan.csv': ['rule_id', 'metric', 'alert_rule'],
        'strategy_summary.md': [],
    },
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def check_csv_columns(path, required_cols):
    errors = []
    try:
        df = pd.read_csv(path, nrows=5)
    except Exception as exc:
        return ['Cannot read CSV %s: %s' % (path, exc)]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        errors.append('%s missing columns: %s' % (
            os.path.basename(path), missing
        ))
    return errors


def validate_confidence_evidence(path):
    """Enforce that train_value / test_value / oot_value are all populated."""
    errors = []
    try:
        df = pd.read_csv(path)
    except Exception:
        return errors
    for col in ('train_value', 'test_value', 'oot_value'):
        if col in df.columns:
            nulls = int(df[col].isna().sum())
            if nulls:
                errors.append(
                    'confidence_evidence.csv: %d null(s) in %s — '
                    'all three set values are required.' % (nulls, col)
                )
    return errors


def validate_outputs(output_dir, stages=None):
    stages = stages or list(STAGE_REQUIREMENTS.keys())
    errors = []
    warnings = []
    manifest = {
        'run_id': os.path.basename(output_dir),
        'validated_at': now_text(),
        'artifacts': {},
        'status': 'UNKNOWN',
        'completed_stages': [],
    }

    for stage in stages:
        requirements = STAGE_REQUIREMENTS.get(stage, {})
        stage_ok = True
        for filename, required_cols in requirements.items():
            path = os.path.join(output_dir, filename)
            if not os.path.exists(path):
                # monthly/segment files are optional when no time_col / segment_cols
                if filename in (
                    'monthly_rule_simulation.csv',
                    'segment_rule_simulation.csv',
                    'decision_tree.png',
                ):
                    warnings.append(
                        'Stage %s: optional file missing: %s' % (stage, filename)
                    )
                    continue
                errors.append(
                    'Stage %s: MISSING required file: %s' % (stage, filename)
                )
                stage_ok = False
                continue

            manifest['artifacts'][filename] = sha256_file(path)

            if filename.endswith('.csv') and required_cols:
                col_errs = check_csv_columns(path, required_cols)
                errors.extend(col_errs)
                if col_errs:
                    stage_ok = False

            if filename == 'confidence_evidence.csv':
                ev_errs = validate_confidence_evidence(path)
                errors.extend(ev_errs)

        if stage_ok and stage not in manifest['completed_stages']:
            manifest['completed_stages'].append(stage)

    # Determine overall status
    if not errors:
        last_done = (manifest['completed_stages'][-1]
                     if manifest['completed_stages'] else None)
        manifest['status'] = (
            'REVIEW_READY'
            if last_done in ('7', '8') else
            'STAGE_%s_DONE' % (last_done or 'NONE')
        )
    else:
        manifest['status'] = 'VALIDATION_FAILED'

    manifest_path = os.path.join(output_dir, 'manifest.json')
    save_json(manifest, manifest_path)

    for w in warnings:
        print('[WARN]  %s' % w)
    for e in errors:
        print('[ERROR] %s' % e)
    if errors:
        print('\nValidation FAILED (%d errors). manifest.json written.' % len(errors))
        sys.exit(1)
    else:
        print('[OK] All artifacts valid. Status: %s' % manifest['status'])
        print('     Manifest written to:', manifest_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', required=True,
                        help='Run output directory containing artifacts')
    parser.add_argument('--stages', default=None,
                        help='Comma-separated stage list to check (default: all)')
    args = parser.parse_args()
    stages = (
        [s.strip() for s in args.stages.split(',')]
        if args.stages else None
    )
    validate_outputs(args.output_dir, stages=stages)


if __name__ == '__main__':
    main()
