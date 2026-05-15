# -*- coding: utf-8 -*-
"""test_pipeline_integration.py — end-to-end integration test on sample data.

Runs the full pipeline (stages 0–8) on examples/sample_input.csv and
verifies all required output artifacts are produced with the correct columns.
"""

import json
import os
import sys
import shutil
import tempfile

import pandas as pd
import pytest

_SCRIPTS = os.path.join(os.path.dirname(__file__), '..', 'scripts')
_EXAMPLES = os.path.join(os.path.dirname(__file__), '..', 'examples')
if _SCRIPTS not in sys.path:
    sys.path.insert(0, os.path.abspath(_SCRIPTS))


@pytest.fixture(scope='module')
def pipeline_output():
    """Run full pipeline on sample data; return output directory path."""
    out_dir = tempfile.mkdtemp(prefix='pi_cr_test_')
    cfg = {
        'run_id': 'integration_test',
        'input_csv': os.path.abspath(os.path.join(_EXAMPLES, 'sample_input.csv')),
        'field_meta_csv': os.path.abspath(os.path.join(_EXAMPLES, 'field_meta.example.csv')),
        'target': 'bad_flag',
        'id_col': 'app_id',
        'time_col': 'apply_month',
        'output_dir': out_dir,
        'random_state': 42,
        'test_ratio': 0.2,
        'oot_ratio': 0.1,
        'oot_months': 3,
        'bins': 5,
        'max_levels': 10,
        'rule_min_hit_rate': 0.01,
        'rule_min_bad_count': 3,
        'rule_min_lift': 1.2,
        'max_reject_rate': 0.5,
        'combo_max_size': 2,
        'combo_top_n': 10,
        'tree_max_depth': 3,
        'tree_min_samples_leaf': 0.05,
        'tree_min_samples_split': 0.10,
        'rejected_lift': 1.5,
        'corr_threshold': 0.95,
        'exclude_cols': ['apply_month', 'app_id', 'bad_flag'],
        'special_values': {},
        'segment_cols': [],
    }
    cfg_path = os.path.join(out_dir, 'run_config.json')
    with open(cfg_path, 'w') as f:
        json.dump(cfg, f)

    from run_pipeline import run
    run(cfg_path, ['0', '0.5', '1', '2', '3', '4', '5', '5.1', '5.2',
                   '6', '6.1', '7', '8'])
    yield out_dir
    shutil.rmtree(out_dir, ignore_errors=True)


def _csv(output_dir, name):
    path = os.path.join(output_dir, name)
    assert os.path.isfile(path), 'Missing artifact: %s' % name
    return pd.read_csv(path)


def _json(output_dir, name):
    path = os.path.join(output_dir, name)
    assert os.path.isfile(path), 'Missing artifact: %s' % name
    with open(path) as f:
        return json.load(f)


# ---- stage 0 ----

def test_sample_profile_exists(pipeline_output):
    df = _csv(pipeline_output, 'sample_profile.csv')
    assert 'segment' in df.columns
    assert 'ALL' in df['segment'].values


def test_sample_split_log_exists(pipeline_output):
    df = _csv(pipeline_output, 'sample_split_log.csv')
    assert set(df['sample_type'].unique()) >= {'train', 'test', 'oot'}


def test_environment_json_exists(pipeline_output):
    env = _json(pipeline_output, 'environment.json')
    assert 'python_version' in env


# ---- stage 0.5 ----

def test_field_audit_drops_leakage(pipeline_output):
    df = _csv(pipeline_output, 'field_audit.csv')
    # overdue_times is flagged as post_loan_field → should be leakage_flag=True
    leakage = df[df['leakage_flag'] == True]
    assert 'overdue_times' in leakage['feature'].values


# ---- stage 1 ----

def test_data_quality_no_null_features(pipeline_output):
    df = _csv(pipeline_output, 'data_quality.csv')
    assert df['missing_rate'].notna().all()


# ---- stage 2 ----

def test_bin_rules_json_valid(pipeline_output):
    rules = _json(pipeline_output, 'bin_rules.json')
    assert isinstance(rules, dict)
    assert len(rules) > 0
    for v in rules.values():
        assert 'type' in v


def test_bin_detail_has_required_columns(pipeline_output):
    df = _csv(pipeline_output, 'bin_detail.csv')
    assert set(df.columns) >= {'feature', 'bin_label', 'woe', 'iv_component', 'bad_rate'}


def test_bin_detail_iv_components_non_negative(pipeline_output):
    df = _csv(pipeline_output, 'bin_detail.csv')
    assert (df['iv_component'] >= 0).all()


# ---- stage 3 ----

def test_psi_table_labels(pipeline_output):
    df = _csv(pipeline_output, 'psi_table.csv')
    assert set(df['psi_level'].unique()).issubset({'stable', 'watch', 'unstable'})


# ---- stage 4 ----

def test_feature_quality_sorted_by_iv(pipeline_output):
    df = _csv(pipeline_output, 'feature_quality.csv')
    ivs = df['iv'].tolist()
    assert ivs == sorted(ivs, reverse=True)


# ---- stage 5 ----

def test_decision_tree_dot_exists(pipeline_output):
    dot_path = os.path.join(pipeline_output, 'decision_tree.dot')
    assert os.path.isfile(dot_path)
    content = open(dot_path).read()
    assert 'digraph' in content


def test_decision_tree_rules_columns(pipeline_output):
    df = _csv(pipeline_output, 'decision_tree_rules.csv')
    assert set(df.columns) >= {'rule_id', 'lift', 'bad_rate', 'hit_rate', 'confidence'}


# ---- stage 5.1 ----

def test_single_rule_candidates_exists(pipeline_output):
    df = _csv(pipeline_output, 'single_rule_candidates.csv')
    assert len(df) > 0


# ---- stage 6 ----

def test_strategy_rules_exists(pipeline_output):
    df = _csv(pipeline_output, 'strategy_rules.csv')
    assert 'rule_id' in df.columns
    assert 'action' in df.columns


def test_rule_simulation_full_exists(pipeline_output):
    df = _csv(pipeline_output, 'rule_simulation_full.csv')
    assert 'full_hit_rate' in df.columns


# ---- stage 6.1 ----

def test_waterfall_simulation_exists(pipeline_output):
    df = _csv(pipeline_output, 'waterfall_simulation.csv')
    assert 'waterfall_step' in df.columns
    # Hit count must be non-decreasing across steps
    hits = df['hit_count'].tolist()
    for i in range(1, len(hits)):
        assert hits[i] >= hits[i - 1]


# ---- stage 7 ----

def test_confidence_evidence_all_three_sets(pipeline_output):
    df = _csv(pipeline_output, 'confidence_evidence.csv')
    assert df['train_value'].notna().all()
    assert df['test_value'].notna().all()
    assert df['oot_value'].notna().all()


# ---- stage 8 ----

def test_monitoring_plan_exists(pipeline_output):
    df = _csv(pipeline_output, 'monitoring_plan.csv')
    assert len(df) > 0
    assert 'alert_rule' in df.columns


def test_strategy_summary_md_exists(pipeline_output):
    path = os.path.join(pipeline_output, 'strategy_summary.md')
    assert os.path.isfile(path)
    content = open(path).read()
    assert '# 信贷风控策略分析报告' in content


# ---- decision_log ----

def test_decision_log_has_all_stages(pipeline_output):
    df = _csv(pipeline_output, 'decision_log.csv')
    stages = set(df['stage'].tolist())
    # At minimum stages 0–8 must be logged
    for expected_stage in ['stage_0', 'stage_0_5', 'stage_1', 'stage_2',
                           'stage_3', 'stage_4', 'stage_5', 'stage_5_1',
                           'stage_5_2', 'stage_6', 'stage_6_1', 'stage_7',
                           'stage_8']:
        assert expected_stage in stages, 'Missing decision_log entry for %s' % expected_stage


# ---- reproducibility ----

def test_reproducibility(pipeline_output):
    """Re-running with same config must produce bit-identical bin_rules.json."""
    import tempfile
    import shutil
    cfg_path = os.path.join(pipeline_output, 'run_config.json')
    with open(cfg_path) as f:
        cfg = json.load(f)
    out_dir2 = tempfile.mkdtemp(prefix='pi_cr_repro_')
    try:
        cfg2 = dict(cfg)
        cfg2['output_dir'] = out_dir2
        cfg_path2 = os.path.join(out_dir2, 'run_config.json')
        with open(cfg_path2, 'w') as f:
            json.dump(cfg2, f)
        from run_pipeline import run
        run(cfg_path2, ['0', '0.5', '1', '2'])
        rules1 = _json(pipeline_output, 'bin_rules.json')
        rules2 = _json(out_dir2, 'bin_rules.json')
        assert rules1 == rules2, 'bin_rules.json is not reproducible!'
    finally:
        shutil.rmtree(out_dir2, ignore_errors=True)
