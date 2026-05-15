# -*- coding: utf-8 -*-
"""simulation.py — rule simulation on observable and full population (stage 6)."""

import pandas as pd
from .io_utils import safe_rate

EPSILON = 1e-10
PSI_STABLE_THRESHOLD = 0.1
PSI_WATCH_THRESHOLD = 0.25


def build_rule_masks(df, rules):
    """Build boolean masks for decision-tree rules using df.eval.

    IMPORTANT: rule_expression column names must be valid Python identifiers
    (no spaces, no special characters) — guaranteed when using label_encode_bins
    output as the df.  Single-variable rules should use build_bin_masks instead.
    """
    masks = {}
    for _, row in rules.iterrows():
        expr = row['rule_expression']
        if expr == 'ALL':
            masks[row['rule_id']] = pd.Series(True, index=df.index)
        else:
            try:
                masks[row['rule_id']] = df.eval(expr.replace(' AND ', ' and '))
            except Exception:
                masks[row['rule_id']] = pd.Series(False, index=df.index)
    return masks


def simulate_rule(df, mask, target, rule_id='', segment='ALL'):
    """Simulate a single rule on an observable-sample DataFrame."""
    total = len(df)
    total_bad = int(df[target].sum())
    hit = df.loc[mask]
    hit_count = len(hit)
    hit_bad = int(hit[target].sum()) if hit_count else 0
    pass_df = df.loc[~mask]
    pass_count = len(pass_df)
    pass_bad = int(pass_df[target].sum()) if pass_count else 0
    overall_bad_rate = safe_rate(total_bad, total)
    hit_bad_rate = safe_rate(hit_bad, hit_count)
    return {
        'segment': segment,
        'rule_id': rule_id,
        'sample_count': total,
        'bad_count': total_bad,
        'overall_bad_rate': overall_bad_rate,
        'hit_count': hit_count,
        'hit_rate': safe_rate(hit_count, total),
        'hit_bad_count': hit_bad,
        'hit_bad_rate': hit_bad_rate,
        'lift': safe_rate(hit_bad_rate, overall_bad_rate),
        'pass_count': pass_count,
        'pass_rate': safe_rate(pass_count, total),
        'pass_bad_count': pass_bad,
        'pass_bad_rate': safe_rate(pass_bad, pass_count),
        'captured_bad_rate': safe_rate(hit_bad, total_bad),
        'false_reject_good_count': hit_count - hit_bad,
    }


def simulate_rule_full_population(df_full, mask_full, target,
                                   rejected_lift=1.5, segment_lift_map=None,
                                   segment_col=None, rule_id='', segment='ALL'):
    """Simulate a rule on the FULL population (observable + rejected).

    Observable rows (target not null) contribute actual bad counts.
    Rejected rows (target null) contribute an inferred bad count:
      expected_bad_per_row = observable_overall_bad_rate * row_lift
    where row_lift comes from segment_lift_map[df[segment_col]] when both are
    provided, otherwise falls back to `rejected_lift` (default 1.5 per spec).

    Returns the same shape as simulate_rule plus observable_*, rejected_*,
    full_*, and reject_inference_method fields.
    """
    obs_mask_all = df_full[target].notna()
    rej_mask_all = ~obs_mask_all
    overall_bad_rate = (
        float(df_full.loc[obs_mask_all, target].mean())
        if obs_mask_all.any() else 0.0
    )

    # Observable side: real counts.
    obs_hit = mask_full & obs_mask_all
    obs_pass = (~mask_full) & obs_mask_all
    obs_hit_count = int(obs_hit.sum())
    obs_pass_count = int(obs_pass.sum())
    obs_hit_bad = int(df_full.loc[obs_hit, target].sum()) if obs_hit_count else 0
    obs_pass_bad = int(df_full.loc[obs_pass, target].sum()) if obs_pass_count else 0

    # Rejected side: inferred via lift.
    rej_hit = mask_full & rej_mask_all
    rej_pass = (~mask_full) & rej_mask_all
    rej_hit_count = int(rej_hit.sum())
    rej_pass_count = int(rej_pass.sum())
    if segment_col and segment_lift_map and segment_col in df_full.columns:
        lift_map = {str(k): float(v) for k, v in segment_lift_map.items()}
        row_lift = (
            df_full[segment_col].astype(str).map(lift_map).fillna(rejected_lift)
        )
        per_row_bad = overall_bad_rate * row_lift
        rej_hit_bad_est = float(per_row_bad.loc[rej_hit].sum())
        rej_pass_bad_est = float(per_row_bad.loc[rej_pass].sum())
        method = 'segment_lift(default=%.2f)' % rejected_lift
    else:
        rej_hit_bad_est = rej_hit_count * overall_bad_rate * rejected_lift
        rej_pass_bad_est = rej_pass_count * overall_bad_rate * rejected_lift
        method = 'default_lift_%.2f' % rejected_lift

    full_count = len(df_full)
    full_hit_count = obs_hit_count + rej_hit_count
    full_pass_count = obs_pass_count + rej_pass_count
    full_hit_bad_est = obs_hit_bad + rej_hit_bad_est
    full_pass_bad_est = obs_pass_bad + rej_pass_bad_est
    full_bad_est = full_hit_bad_est + full_pass_bad_est
    full_overall_bad_rate_est = safe_rate(full_bad_est, full_count)
    full_hit_bad_rate_est = safe_rate(full_hit_bad_est, full_hit_count)
    return {
        'segment': segment,
        'rule_id': rule_id,
        'reject_inference_method': method,
        # observable (actual)
        'observable_sample_count': int(obs_mask_all.sum()),
        'observable_overall_bad_rate': overall_bad_rate,
        'observable_hit_count': obs_hit_count,
        'observable_hit_bad_count': obs_hit_bad,
        'observable_hit_bad_rate': safe_rate(obs_hit_bad, obs_hit_count),
        'observable_pass_bad_rate': safe_rate(obs_pass_bad, obs_pass_count),
        # rejected (inferred)
        'rejected_sample_count': int(rej_mask_all.sum()),
        'rejected_hit_count': rej_hit_count,
        'rejected_hit_bad_count_est': rej_hit_bad_est,
        'rejected_pass_bad_count_est': rej_pass_bad_est,
        # full population
        'full_sample_count': full_count,
        'full_hit_count': full_hit_count,
        'full_hit_rate': safe_rate(full_hit_count, full_count),
        'full_pass_count': full_pass_count,
        'full_pass_rate': safe_rate(full_pass_count, full_count),
        'full_hit_bad_count_est': full_hit_bad_est,
        'full_pass_bad_count_est': full_pass_bad_est,
        'full_hit_bad_rate_est': full_hit_bad_rate_est,
        'full_pass_bad_rate_est': safe_rate(full_pass_bad_est, full_pass_count),
        'full_overall_bad_rate_est': full_overall_bad_rate_est,
        'full_lift_est': safe_rate(full_hit_bad_rate_est, full_overall_bad_rate_est),
    }


def simulate_rules_full_population_by_month(df_full, target, time_col, rule_masks,
                                             rejected_lift=1.5, segment_lift_map=None,
                                             segment_col=None):
    """Full-population rule simulation across ALL + per-month.

    Output: rule_simulation_full.csv
    """
    rows = []
    for rule_id, mask in rule_masks.items():
        rows.append(simulate_rule_full_population(
            df_full, mask, target,
            rejected_lift=rejected_lift,
            segment_lift_map=segment_lift_map,
            segment_col=segment_col,
            rule_id=rule_id, segment='ALL',
        ))
        if time_col and time_col in df_full.columns:
            for period, group in df_full.groupby(time_col):
                rows.append(simulate_rule_full_population(
                    group, mask.loc[group.index], target,
                    rejected_lift=rejected_lift,
                    segment_lift_map=segment_lift_map,
                    segment_col=segment_col,
                    rule_id=rule_id, segment=str(period),
                ))
    return pd.DataFrame(rows)


def simulate_combined_rules(df, rule_masks, target, selected_rule_ids=None,
                             strategy_id='S001', segment='ALL'):
    """Simulate OR-combination of selected rules."""
    selected = selected_rule_ids or list(rule_masks.keys())
    combined = pd.Series(False, index=df.index)
    for rule_id in selected:
        if rule_id in rule_masks:
            combined = combined | rule_masks[rule_id]
    result = simulate_rule(df, combined, target, rule_id=strategy_id,
                           segment=segment)
    result['strategy_id'] = strategy_id
    result['rule_count'] = len(selected)
    result['selected_rule_ids'] = ','.join(selected)
    return result


def optimize_strategy_rules(df, candidate_rules, rule_masks, target,
                             max_reject_rate=0.2, max_pass_bad_rate=None):
    """Greedily select rules maximising lift within business constraints.

    When max_pass_bad_rate is not provided defaults to baseline_bad_rate * 1.2.

    Returns
    -------
    strategy_rules_df : strategy_rules.csv — one row per selected rule
    simulation_df     : strategy_comparison.csv — cumulative simulation after
                        each rule is added
    """
    selected = []
    sim_rows = []
    ordered = candidate_rules.sort_values(
        ['lift', 'bad_rate'], ascending=[False, False]
    )
    baseline_bad_rate = float(df[target].mean())
    limit_pass_bad_rate = (
        max_pass_bad_rate if max_pass_bad_rate is not None
        else baseline_bad_rate * 1.2
    )
    for _, rule in ordered.iterrows():
        trial = selected + [rule['rule_id']]
        sim = simulate_combined_rules(
            df, rule_masks, target, selected_rule_ids=trial, strategy_id='OPT'
        )
        if (sim['hit_rate'] <= max_reject_rate
                and sim['pass_bad_rate'] <= limit_pass_bad_rate):
            selected = trial
            sim_rows.append(sim)
    strategy_rows = []
    rules_map = candidate_rules.set_index('rule_id')
    for rid in selected:
        r = rules_map.loc[rid] if rid in rules_map.index else {}
        strategy_rows.append({
            'strategy_id': 'OPT',
            'rule_id': rid,
            'action': r.get('action', 'reject'),
            'confidence': r.get('confidence', ''),
            'rule_readable': r.get('rule_readable', ''),
            'rule_variables': r.get('rule_variables', r.get('feature', '')),
        })
    return pd.DataFrame(strategy_rows), pd.DataFrame(sim_rows)


def assign_confidence(train_sim, oot_sim, psi_value=None, lift_tolerance=0.2):
    """Assign HIGH / MEDIUM / LOW confidence to a rule."""
    train_lift = float(train_sim.get('lift', 0.0))
    oot_lift = float(oot_sim.get('lift', 0.0))
    lift_gap = abs(train_lift - oot_lift) / max(abs(train_lift), EPSILON)
    pass_bad_gap = abs(
        float(train_sim.get('pass_bad_rate', 0.0)) -
        float(oot_sim.get('pass_bad_rate', 0.0))
    )
    if (lift_gap <= lift_tolerance and pass_bad_gap <= 0.02
            and (psi_value is None or psi_value <= PSI_STABLE_THRESHOLD)):
        return 'HIGH'
    if lift_gap <= 0.5 and (psi_value is None or psi_value <= PSI_WATCH_THRESHOLD):
        return 'MEDIUM'
    return 'LOW'


def simulate_rules_by_month(df, target, time_col, rule_masks):
    """Simulate each rule across ALL + per-month segments.

    Output: monthly_rule_simulation.csv
    """
    rows = []
    for rule_id, mask in rule_masks.items():
        rows.append(simulate_rule(df, mask, target, rule_id=rule_id,
                                  segment='ALL'))
        if time_col and time_col in df.columns:
            for period, group in df.groupby(time_col):
                rows.append(simulate_rule(
                    group, mask.loc[group.index], target,
                    rule_id=rule_id, segment=str(period),
                ))
    return pd.DataFrame(rows)


def simulate_rules_by_segment(df, target, segment_cols, rule_masks):
    """Simulate each rule across each segment column value.

    Output: segment_rule_simulation.csv
    """
    rows = []
    for rule_id, mask in rule_masks.items():
        for segment_col in segment_cols:
            if segment_col not in df.columns:
                continue
            for segment_value, group in df.groupby(segment_col):
                rows.append(simulate_rule(
                    group, mask.loc[group.index], target,
                    rule_id=rule_id,
                    segment='%s=%s' % (segment_col, segment_value),
                ))
    return pd.DataFrame(rows)
