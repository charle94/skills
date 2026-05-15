#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_inputs.py — pre-flight checks before running the pipeline.

Usage: python3 scripts/validate_inputs.py --config path/to/run_config.json
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pandas as pd
from lib.config import load_config, validate_config, resolve_feature_cols
from lib.samples import split_observable_sample, validate_binary_target


def validate_inputs(cfg_path):
    errors = []
    warnings = []

    # 1. Config schema
    try:
        cfg = load_config(cfg_path)
        validate_config(cfg)
    except Exception as exc:
        errors.append('Config error: %s' % exc)
        _report(errors, warnings)
        return

    # 2. Input CSV loadable
    try:
        df = pd.read_csv(cfg['input_csv'], low_memory=False)
        print('Input CSV: %d rows × %d cols' % df.shape)
    except Exception as exc:
        errors.append('Cannot read input_csv: %s' % exc)
        _report(errors, warnings)
        return

    target = cfg['target']

    # 3. Target column exists
    if target not in df.columns:
        errors.append('target column "%s" not in CSV' % target)
        _report(errors, warnings)
        return

    # 4. Observable / rejected split
    observable, rejected = split_observable_sample(df, target)
    print('Observable rows (target not null): %d' % len(observable))
    print('Rejected rows   (target null)    : %d' % len(rejected))

    if len(observable) < 100:
        warnings.append(
            'Observable sample < 100 rows; results will be unstable.'
        )

    # 5. Binary target on observable
    try:
        validate_binary_target(observable, target)
    except ValueError as exc:
        errors.append(str(exc))

    # 6. ID column
    if cfg.get('id_col') and cfg['id_col'] not in df.columns:
        warnings.append('id_col "%s" not in CSV; skipped.' % cfg['id_col'])

    # 7. Time column
    if cfg.get('time_col') and cfg['time_col'] not in df.columns:
        warnings.append(
            'time_col "%s" not in CSV; stratified random split will be used.'
            % cfg['time_col']
        )

    # 8. Feature columns
    feature_cols = resolve_feature_cols(df, cfg)
    print('Feature columns: %d' % len(feature_cols))
    if len(feature_cols) == 0:
        errors.append(
            'No feature columns after excluding target/id/time/exclude_cols.'
        )

    # 9. Field meta CSV
    if cfg.get('field_meta_csv'):
        if not os.path.isfile(cfg['field_meta_csv']):
            warnings.append(
                'field_meta_csv not found: %s (leakage audit will skip)'
                % cfg['field_meta_csv']
            )
        else:
            meta_df = pd.read_csv(cfg['field_meta_csv'])
            if 'feature' not in meta_df.columns:
                warnings.append(
                    'field_meta_csv missing "feature" column; skipped.'
                )

    _report(errors, warnings)


def _report(errors, warnings):
    for w in warnings:
        print('[WARN]  %s' % w)
    for e in errors:
        print('[ERROR] %s' % e)
    if errors:
        sys.exit(1)
    else:
        print('[OK] All input checks passed.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    validate_inputs(args.config)


if __name__ == '__main__':
    main()
