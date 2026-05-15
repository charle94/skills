#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_pipeline.py — deterministic credit-risk pipeline CLI entry point.

Usage
-----
  python3 scripts/run_pipeline.py --config runs/my_run/run_config.json --stage all
  python3 scripts/run_pipeline.py --config runs/my_run/run_config.json --stage 0
  python3 scripts/run_pipeline.py --config runs/my_run/run_config.json --stage 0-4

Stages:
  0      sample scope and split
  0.5    field availability and leakage audit
  1      data quality
  2      binning, WOE, IV
  3      PSI
  4      KS / AUC / correlation
  5      decision-tree rule mining
  5.1    single-variable rule mining
  5.2    combination rule mining
  6      rule simulation (observable + full population)
  6.1    waterfall
  7      confidence evidence
  8      monitoring plan
  all    all stages in order

Each stage re-loads pre-saved artifacts from output_dir so it is safe to run
stages individually or as a contiguous range.
"""

import argparse
import json
import os
import sys

# Allow running as scripts/run_pipeline.py from any working directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import pandas as pd
from lib.config import load_config, validate_config, resolve_feature_cols
from lib.io_utils import ensure_dir, save_json


STAGE_ORDER = ['0', '0.5', '1', '2', '3', '4', '5', '5.1', '5.2',
               '6', '6.1', '7', '8']


def parse_stage_arg(stage_str):
    """Parse --stage argument into a list of stage ids to execute."""
    if stage_str == 'all':
        return STAGE_ORDER
    if '-' in stage_str and stage_str != '0.5':
        parts = stage_str.split('-')
        start, end = parts[0], parts[-1]
        if start in STAGE_ORDER and end in STAGE_ORDER:
            si = STAGE_ORDER.index(start)
            ei = STAGE_ORDER.index(end)
            return STAGE_ORDER[si:ei + 1]
    if stage_str in STAGE_ORDER:
        return [stage_str]
    raise ValueError('Unknown stage: %s. Valid: %s or all' % (
        stage_str, ', '.join(STAGE_ORDER)
    ))


def load_artifacts(out):
    """Re-load pre-computed artifacts from output_dir for incremental runs."""
    arts = {}
    artifacts_json = os.path.join(out, 'artifacts.json')
    if os.path.exists(artifacts_json):
        with open(artifacts_json, 'r', encoding='utf-8') as f:
            arts = json.load(f)
    return arts


def save_artifact_index(out, index):
    """Save artifact file index to artifacts.json."""
    save_json(index, os.path.join(out, 'artifacts.json'))


def run(cfg_path, stages):
    cfg = load_config(cfg_path)
    validate_config(cfg)
    out = cfg['output_dir']
    ensure_dir(out)

    print('=== pi-credit-risk pipeline ===')
    print('run_id   :', cfg.get('run_id', 'unknown'))
    print('output   :', out)
    print('stages   :', stages)
    print()

    # Load input data once
    df = pd.read_csv(cfg['input_csv'], low_memory=False)
    print('Input rows: %d  cols: %d' % df.shape)

    # Load optional field meta
    field_meta = None
    if cfg.get('field_meta_csv') and os.path.isfile(cfg['field_meta_csv']):
        meta_df = pd.read_csv(cfg['field_meta_csv'])
        if 'feature' in meta_df.columns:
            field_meta = meta_df.set_index('feature').to_dict('index')

    # Shared state carried between stages
    state = {}
    art_index = load_artifacts(out)

    def _need(key, loader):
        """Load a shared state key from disk if not already in state."""
        if key not in state:
            state[key] = loader()
        return state[key]

    for stage in stages:
        print('--- Stage %s ---' % stage)

        if stage == '0':
            from lib.pipeline import stage_0_samples
            result = stage_0_samples(df, cfg)
            state['observable'] = result['observable']
            state['rejected'] = result['rejected']
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '0.5':
            def _load_obs():
                path = os.path.join(out, 'sample_profile.csv')
                # observable must have been computed; reload from input
                obs, _ = __import__('lib.samples', fromlist=['split_observable_sample']).split_observable_sample(df, cfg['target'])
                # re-attach sample_type
                split_log_path = os.path.join(out, 'sample_split_log.csv')
                if os.path.exists(split_log_path):
                    from lib.samples import split_samples
                    obs, _ = split_samples(obs, cfg['target'],
                                           time_col=cfg.get('time_col'),
                                           oot_months=int(cfg.get('oot_months', 3)),
                                           test_ratio=float(cfg.get('test_ratio', 0.2)),
                                           oot_ratio=float(cfg.get('oot_ratio', 0.1)),
                                           random_state=int(cfg.get('random_state', 42)))
                return obs
            observable = _need('observable', _load_obs)
            from lib.pipeline import stage_0_5_audit
            result = stage_0_5_audit(observable, cfg, field_meta=field_meta)
            state['feature_cols'] = result['feature_cols']
            art_index.update(result)
            save_artifact_index(out, art_index)

        elif stage == '1':
            observable = _need('observable', lambda: state.get('observable', df))
            feature_cols = _need('feature_cols', lambda: resolve_feature_cols(df, cfg))
            from lib.pipeline import stage_1_quality
            result = stage_1_quality(observable, cfg, feature_cols)
            state['feature_cols'] = result['feature_cols']
            art_index.update(result)
            save_artifact_index(out, art_index)

        elif stage == '2':
            observable = _need('observable', lambda: state.get('observable', df))
            feature_cols = _need('feature_cols', lambda: resolve_feature_cols(df, cfg))
            from lib.pipeline import stage_2_binning_woe
            result = stage_2_binning_woe(observable, cfg, feature_cols)
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '3':
            observable = state['observable']
            from lib.pipeline import stage_3_psi
            result = stage_3_psi(
                observable, cfg,
                state['feature_cols'], state['bin_rules'],
                state['binned_train'], state['binned_test'], state['binned_oot'],
            )
            state['psi_summary'] = result['psi_summary']
            state['feature_cols'] = result['feature_cols']
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '4':
            observable = state['observable']
            from lib.pipeline import stage_4_metrics
            result = stage_4_metrics(
                observable, cfg,
                state['feature_cols'],
                state['bin_detail'], state['binned_train'],
                state['iv_summary'],
                psi_summary=state.get('psi_summary'),
            )
            state['feature_cols'] = result['feature_cols']
            state['feature_quality'] = result['quality']
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '5':
            observable = state['observable']
            from lib.pipeline import stage_5_tree_rules
            result = stage_5_tree_rules(
                observable, cfg,
                state['feature_cols'],
                state['binned_train'], state['binned_test'], state['binned_oot'],
            )
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '5.1':
            observable = state['observable']
            from lib.pipeline import stage_5_1_single_rules
            result = stage_5_1_single_rules(
                observable, cfg,
                state['feature_cols'],
                state['bin_detail'],
                state['binned_train'], state['binned_test'], state['binned_oot'],
            )
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '5.2':
            observable = state['observable']
            from lib.pipeline import stage_5_2_combo_rules
            result = stage_5_2_combo_rules(
                observable, cfg,
                state['filtered_single_rules'],
                state['sv_masks'],
                tree_rules=state.get('tree_rules'),
                tree_masks=state.get('tree_masks'),
            )
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '6':
            from lib.pipeline import stage_6_simulation
            result = stage_6_simulation(
                df, state['observable'], cfg,
                state['feature_cols'],
                state['bin_detail'],
                state['binned_train'], state['binned_test'], state['binned_oot'],
                state['filtered_single_rules'],
                tree_rules=state.get('tree_rules'),
                tree_masks=state.get('tree_masks'),
            )
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '6.1':
            from lib.pipeline import stage_6_1_waterfall
            result = stage_6_1_waterfall(
                df, state['observable'], cfg,
                state['strategy_rules'],
                state['selected_masks'],
                state['full_masks'],
            )
            art_index.update(result)
            save_artifact_index(out, art_index)

        elif stage == '7':
            from lib.pipeline import stage_7_summary
            result = stage_7_summary(
                state['observable'], cfg,
                state['strategy_rules'],
                state['selected_masks'],
                psi_summary=state.get('psi_summary'),
                feature_quality=state.get('feature_quality'),
            )
            state.update(result)
            art_index.update({k: v for k, v in result.items() if isinstance(v, str)})
            save_artifact_index(out, art_index)

        elif stage == '8':
            from lib.pipeline import stage_8_monitoring
            result = stage_8_monitoring(cfg, state['strategy_rules'])
            art_index.update(result)
            # Generate strategy_summary.md from all artifacts
            sys.path.insert(0, out) if out not in sys.path else None
            import importlib.util as _ilu
            _rs_path = os.path.join(_HERE, 'render_report.py')
            _spec = _ilu.spec_from_file_location('render_report', _rs_path)
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            report_path = _mod.render_report(out)
            art_index['strategy_summary'] = report_path
            save_artifact_index(out, art_index)

        print('  done → artifacts written to %s' % out)

    print()
    print('Pipeline complete. Artifacts in:', out)


def main():
    parser = argparse.ArgumentParser(
        description='pi-credit-risk deterministic pipeline'
    )
    parser.add_argument('--config', required=True,
                        help='Path to run_config.json')
    parser.add_argument('--stage', default='all',
                        help='Stage(s) to run: 0, 0.5, 1, 2-4, all, etc.')
    args = parser.parse_args()

    stages = parse_stage_arg(args.stage)
    run(args.config, stages)


if __name__ == '__main__':
    main()
