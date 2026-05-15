# -*- coding: utf-8 -*-
"""test_validate_outputs.py — artifact validation logic."""

import json
import os

import pandas as pd
import pytest

from lib.io_utils import ensure_dir, save_json


def _make_run_dir(tmp_path, files):
    """Create a minimal run output directory with provided file dicts."""
    run_dir = tmp_path / 'test_run'
    run_dir.mkdir()
    for name, content in files.items():
        path = run_dir / name
        if isinstance(content, dict):
            with open(path, 'w') as f:
                json.dump(content, f)
        elif isinstance(content, pd.DataFrame):
            content.to_csv(path, index=False)
        else:
            with open(path, 'w') as f:
                f.write(str(content))
    return str(run_dir)


def test_validate_outputs_missing_file(tmp_path):
    """validate_outputs must fail if a required file is absent."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    from validate_outputs import validate_outputs
    run_dir = _make_run_dir(tmp_path, {
        'run_config.json': {'run_id': 'test'},
        'environment.json': {},
        # sample_profile.csv intentionally missing
    })
    with pytest.raises(SystemExit):
        validate_outputs(run_dir, stages=['0'])


def test_validate_outputs_stage_0_passes(tmp_path):
    """validate_outputs stage 0 passes when all required files are present."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    from validate_outputs import validate_outputs
    profile = pd.DataFrame([{
        'segment': 'ALL', 'sample_count': 1000, 'bad_rate': 0.1
    }])
    split_log = pd.DataFrame([{
        'sample_type': 'train', 'sample_count': 700, 'bad_rate': 0.1,
        'split_method': 'stratified'
    }])
    run_dir = _make_run_dir(tmp_path, {
        'run_config.json': {'run_id': 'test'},
        'environment.json': {},
        'sample_profile.csv': profile,
        'sample_split_log.csv': split_log,
    })
    # Should not raise
    try:
        validate_outputs(run_dir, stages=['0'])
    except SystemExit:
        pytest.fail('validate_outputs raised SystemExit for valid stage 0 artifacts')


def test_validate_outputs_confidence_evidence_null_raises(tmp_path):
    """validate_outputs must fail if confidence_evidence has null values."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    from validate_outputs import validate_outputs
    ev = pd.DataFrame([{
        'evidence_id': 'EV_001',
        'object_id': 'R001',
        'metric_name': 'lift',
        'train_value': 2.0,
        'test_value': None,   # intentional null
        'oot_value': 1.9,
        'confidence': 'HIGH',
    }])
    monitor = pd.DataFrame([{
        'rule_id': 'R001', 'metric': 'hit_rate', 'alert_rule': 'gt10pct',
    }])
    run_dir = _make_run_dir(tmp_path, {
        'confidence_evidence.csv': ev,
        'monitoring_plan.csv': monitor,
        'strategy_summary.md': '# report',
    })
    with pytest.raises(SystemExit):
        validate_outputs(run_dir, stages=['7', '8'])


def test_sha256_manifest_written(tmp_path):
    """validate_outputs must write manifest.json with sha256 hashes."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    from validate_outputs import validate_outputs
    profile = pd.DataFrame([{'segment': 'ALL', 'sample_count': 100, 'bad_rate': 0.1}])
    split_log = pd.DataFrame([{'sample_type': 'train', 'sample_count': 70,
                                'bad_rate': 0.1, 'split_method': 'rand'}])
    run_dir = _make_run_dir(tmp_path, {
        'run_config.json': {'run_id': 'x'},
        'environment.json': {},
        'sample_profile.csv': profile,
        'sample_split_log.csv': split_log,
    })
    try:
        validate_outputs(run_dir, stages=['0'])
    except SystemExit:
        pass
    manifest = json.load(open(os.path.join(run_dir, 'manifest.json')))
    assert 'artifacts' in manifest
    # At least one artifact should have a sha256 hash
    hashes = list(manifest['artifacts'].values())
    assert any(len(h) == 64 for h in hashes)  # sha256 hex = 64 chars
