# -*- coding: utf-8 -*-
"""waterfall.py — sequential waterfall rule evaluation (stage 6.1)."""

import pandas as pd
from .io_utils import safe_rate
from .simulation import simulate_rule, simulate_rule_full_population


def build_waterfall_simulation(df, ordered_rule_ids, rule_masks, target,
                                strategy_id_prefix='WF', segment='ALL'):
    """Sequential cumulative waterfall for observable samples.

    Add rules one by one and record incremental gain at each step.

    Extra columns vs simulate_rule:
      waterfall_step, added_rule_id, cumulative_rule_ids,
      incremental_hit, incremental_bad, incremental_hit_rate,
      incremental_captured_bad_rate

    Output: waterfall_simulation.csv
    """
    rows = []
    cumulative = pd.Series(False, index=df.index)
    prev_hit = 0
    prev_bad = 0
    total_bad = int(df[target].sum())
    for step, rule_id in enumerate(ordered_rule_ids):
        if rule_id not in rule_masks:
            continue
        cumulative = cumulative | rule_masks[rule_id]
        strategy_id = '%s_S%02d_%s' % (strategy_id_prefix, step + 1, rule_id)
        sim = simulate_rule(df, cumulative, target, rule_id=strategy_id,
                            segment=segment)
        sim['waterfall_step'] = step + 1
        sim['added_rule_id'] = rule_id
        sim['cumulative_rule_ids'] = ','.join(ordered_rule_ids[:step + 1])
        sim['incremental_hit'] = sim['hit_count'] - prev_hit
        sim['incremental_bad'] = sim['hit_bad_count'] - prev_bad
        sim['incremental_hit_rate'] = safe_rate(
            sim['incremental_hit'], sim['sample_count']
        )
        sim['incremental_captured_bad_rate'] = safe_rate(
            sim['incremental_bad'], total_bad
        )
        rows.append(sim)
        prev_hit = sim['hit_count']
        prev_bad = sim['hit_bad_count']
    return pd.DataFrame(rows)


def waterfall_cross_set(df, ordered_rule_ids, rule_masks, target,
                        sample_type_col='sample_type'):
    """Run build_waterfall_simulation on train / test / oot and concat.

    Output: waterfall_comparison.csv — use waterfall_step + added_rule_id +
    segment to compare incremental lift stability across sets.
    """
    frames = []
    for seg in ['train', 'test', 'oot']:
        if sample_type_col in df.columns:
            sub_df = df[df[sample_type_col] == seg]
        else:
            sub_df = df
        sub_masks = {
            rid: rule_masks[rid].loc[sub_df.index]
            for rid in ordered_rule_ids
            if rid in rule_masks
        }
        wf = build_waterfall_simulation(
            sub_df, ordered_rule_ids, sub_masks, target, segment=seg
        )
        frames.append(wf)
    return pd.concat(frames, ignore_index=True)


def build_waterfall_simulation_full_population(
        df_full, ordered_rule_ids, rule_masks, target,
        rejected_lift=1.5, segment_lift_map=None, segment_col=None,
        strategy_id_prefix='WF_FULL', segment='ALL'):
    """Full-population waterfall: cumulative OR-add with reject inference.

    At each step k the cumulative mask covers rules 1..k; metrics come from
    simulate_rule_full_population so observable rows contribute real bad counts
    and rejected rows contribute overall_bad_rate * row_lift.

    Incremental columns are computed on full_hit_count / full_hit_bad_count_est
    so they stay consistent with the full-population denominators.

    Output: waterfall_simulation_full.csv
    """
    rows = []
    cumulative = pd.Series(False, index=df_full.index)
    prev_hit = 0
    prev_bad_est = 0.0
    for step, rule_id in enumerate(ordered_rule_ids):
        if rule_id not in rule_masks:
            continue
        cumulative = cumulative | rule_masks[rule_id]
        strategy_id = '%s_S%02d_%s' % (strategy_id_prefix, step + 1, rule_id)
        sim = simulate_rule_full_population(
            df_full, cumulative, target,
            rejected_lift=rejected_lift,
            segment_lift_map=segment_lift_map,
            segment_col=segment_col,
            rule_id=strategy_id, segment=segment,
        )
        sim['waterfall_step'] = step + 1
        sim['added_rule_id'] = rule_id
        sim['cumulative_rule_ids'] = ','.join(ordered_rule_ids[:step + 1])
        sim['incremental_full_hit'] = sim['full_hit_count'] - prev_hit
        sim['incremental_full_bad_est'] = sim['full_hit_bad_count_est'] - prev_bad_est
        sim['incremental_full_hit_rate'] = safe_rate(
            sim['incremental_full_hit'], sim['full_sample_count']
        )
        rows.append(sim)
        prev_hit = sim['full_hit_count']
        prev_bad_est = sim['full_hit_bad_count_est']
    return pd.DataFrame(rows)
