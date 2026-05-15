# -*- coding: utf-8 -*-
"""io_utils.py — shared I/O helpers used by every pipeline stage."""

from __future__ import print_function

import json
import os
from datetime import datetime

import pandas as pd


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def save_json(obj, path):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)


def safe_rate(num, den):
    return float(num) / float(den) if den else 0.0


def now_text():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def log_decision(log_path, stage, object_id, decision, reason,
                 input_files='', output_files='', operator_note=''):
    """Append one decision row to decision_log.csv (create if not exists)."""
    row = pd.DataFrame([{
        'timestamp': now_text(),
        'stage': stage,
        'object_id': str(object_id),
        'decision': decision,
        'reason': reason,
        'input_files': input_files,
        'output_files': output_files,
        'operator_note': operator_note,
    }])
    write_header = not os.path.exists(log_path)
    row.to_csv(log_path, mode='a', index=False, header=write_header, encoding='utf-8')
