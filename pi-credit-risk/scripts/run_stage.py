#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_stage.py — thin wrapper that runs exactly ONE pipeline stage.

Useful when the workflow extension calls a specific stage id directly.

Usage: python3 scripts/run_stage.py --config runs/<run_id>/run_config.json --stage 2
"""

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from run_pipeline import run, parse_stage_arg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, help='Path to run_config.json')
    parser.add_argument('--stage', required=True, help='Single stage id: 0, 0.5, 1, …, 8')
    args = parser.parse_args()
    stages = parse_stage_arg(args.stage)
    if len(stages) != 1:
        print('run_stage.py accepts exactly one stage id (not a range). '
              'Use run_pipeline.py for ranges.', file=sys.stderr)
        sys.exit(1)
    run(args.config, stages)


if __name__ == '__main__':
    main()
