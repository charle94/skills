# -*- coding: utf-8 -*-
"""pipeline.py — deterministic stage orchestrators for the full credit-risk pipeline.

Each stage_N function:
  1. Reads inputs from output_dir or from the caller-supplied DataFrames.
  2. Runs the deterministic computation.
  3. Writes all required CSV/JSON artifacts to output_dir.
  4. Appends entries to decision_log.csv.
  5. Returns a dict of produced artifact paths.

All random operations use cfg['random_state'] (default 42) so that re-running
with the same config and data produces bit-identical outputs.
"""

import json
import os

import pandas as pd

from .io_utils import ensure_dir, save_json, log_decision
from .environment import capture_environment
from .config import resolve_feature_cols
from .samples import (
    split_observable_sample, validate_binary_target, sample_profile,
    split_samples,
)
from .audit import audit_fields
from .quality import data_quality, outlier_summary
from .binning import (
    build_bin_rules, apply_bin_rules, enforce_monotonic_bins,
    monotonicity_check, merge_log_for_non_monotonic,
)
from .woe import build_woe_iv, apply_woe_transform, woe_rules_to_json
from .psi import psi_by_bins
from .metrics import (
    feature_quality_from_woe, feature_correlation, build_feature_drop_reason,
)
from .tree_rules import (
    label_encode_bins, apply_label_encode,
    fit_rule_tree, extract_tree_single_rules, score_tree_rules_with_action,
    rule_overlap_matrix, render_tree_graphviz,
)
from .single_rules import (
    extract_single_var_rules, build_bin_masks,
    filter_rule_candidates, evaluate_single_var_rules_cross_set,
)
from .combo_rules import mine_rule_combinations
from .simulation import (
    build_rule_masks, simulate_rule, simulate_rule_full_population,
    simulate_rules_full_population_by_month, simulate_combined_rules,
    optimize_strategy_rules, assign_confidence,
    simulate_rules_by_month, simulate_rules_by_segment,
)
from .waterfall import (
    build_waterfall_simulation, waterfall_cross_set,
    build_waterfall_simulation_full_population,
)
from .reporting import (
    build_strategy_rules_table, compare_strategy_simulations,
    build_confidence_evidence, build_monitoring_plan,
)


# ---------------------------------------------------------------------------
# Stage 0 — Sample scope and split
# ---------------------------------------------------------------------------

def stage_0_samples(df, cfg):
    """Stage 0: validate target, split observable/rejected, split train/test/oot.

    Writes:
      run_config.json (frozen copy), environment.json,
      sample_profile.csv, sample_split_log.csv

    Returns dict of artifact paths.
    """
    out = cfg['output_dir']
    ensure_dir(out)
    target = cfg['target']
    time_col = cfg.get('time_col')
    random_state = int(cfg.get('random_state', 42))
    log_path = os.path.join(out, 'decision_log.csv')

    # Snapshot run config and environment
    save_json(cfg, os.path.join(out, 'run_config.json'))
    env = capture_environment()
    save_json(env, os.path.join(out, 'environment.json'))

    validate_binary_target(df, target)

    observable, rejected = split_observable_sample(df, target)
    log_decision(log_path, 'stage_0', 'sample_split',
                 'observable=%d rejected=%d' % (len(observable), len(rejected)),
                 'split_observable_sample',
                 output_files='sample_profile.csv,sample_split_log.csv')

    obs_split, split_log = split_samples(
        observable, target,
        time_col=time_col,
        oot_months=int(cfg.get('oot_months', 3)),
        test_ratio=float(cfg.get('test_ratio', 0.2)),
        oot_ratio=float(cfg.get('oot_ratio', 0.1)),
        random_state=random_state,
    )

    profile = sample_profile(obs_split, target, time_col=time_col)

    profile_path = os.path.join(out, 'sample_profile.csv')
    split_log_path = os.path.join(out, 'sample_split_log.csv')
    profile.to_csv(profile_path, index=False, encoding='utf-8')
    split_log.to_csv(split_log_path, index=False, encoding='utf-8')

    return {
        'observable': obs_split,
        'rejected': rejected,
        'sample_profile': profile_path,
        'sample_split_log': split_log_path,
        'run_config': os.path.join(out, 'run_config.json'),
        'environment': os.path.join(out, 'environment.json'),
    }


# ---------------------------------------------------------------------------
# Stage 0.5 — Field availability and leakage audit
# ---------------------------------------------------------------------------

def stage_0_5_audit(observable, cfg, field_meta=None):
    """Stage 0.5: field availability and leakage audit.

    field_meta: dict {col: {source, meaning, available_time, ...}} or None.
    If cfg['field_meta_csv'] is set, caller should load it and pass the dict.

    Writes: field_audit.csv, leakage_audit.csv

    Returns dict with artifact paths and surviving feature_cols list.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    feature_cols = resolve_feature_cols(observable, cfg)
    audit_df = audit_fields(
        feature_cols, field_meta=field_meta,
        decision_time=cfg.get('decision_time'),
    )

    surviving = audit_df[audit_df['decision'] == 'keep']['feature'].tolist()
    dropped = audit_df[audit_df['decision'] == 'drop']['feature'].tolist()

    audit_path = os.path.join(out, 'field_audit.csv')
    leakage_path = os.path.join(out, 'leakage_audit.csv')
    audit_df.to_csv(audit_path, index=False, encoding='utf-8')
    audit_df[audit_df['leakage_flag']].to_csv(
        leakage_path, index=False, encoding='utf-8'
    )

    log_decision(log_path, 'stage_0_5', 'leakage_audit',
                 'kept=%d dropped=%d' % (len(surviving), len(dropped)),
                 'audit_fields',
                 output_files='field_audit.csv,leakage_audit.csv')

    return {
        'feature_cols': surviving,
        'field_audit': audit_path,
        'leakage_audit': leakage_path,
    }


# ---------------------------------------------------------------------------
# Stage 1 — Data quality
# ---------------------------------------------------------------------------

def stage_1_quality(observable, cfg, feature_cols):
    """Stage 1: data quality profiling on the train set.

    Writes: data_quality.csv, outlier_summary.csv, feature_drop_reason.csv (initial)

    Returns dict with artifact paths and quality-surviving feature_cols list.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']

    dq = data_quality(train, feature_cols,
                      special_values=cfg.get('special_values', {}))
    os_df = outlier_summary(train, feature_cols)

    dq_path = os.path.join(out, 'data_quality.csv')
    os_path = os.path.join(out, 'outlier_summary.csv')
    dq.to_csv(dq_path, index=False, encoding='utf-8')
    os_df.to_csv(os_path, index=False, encoding='utf-8')

    # Initial drop reasons from quality alone
    drop_df = build_feature_drop_reason(quality_df=dq)
    drop_path = os.path.join(out, 'feature_drop_reason.csv')
    drop_df.to_csv(drop_path, index=False, encoding='utf-8')

    constant_cols = set(dq[dq['is_constant'] == True]['feature'].tolist())  # noqa: E712
    high_missing = set(dq[dq['missing_rate'] >= 0.9]['feature'].tolist())
    dropped = constant_cols | high_missing
    surviving = [f for f in feature_cols if f not in dropped]

    log_decision(log_path, 'stage_1', 'data_quality',
                 'kept=%d dropped=%d (constant=%d missing90=%d)' % (
                     len(surviving), len(dropped),
                     len(constant_cols), len(high_missing)),
                 'data_quality',
                 output_files='data_quality.csv,outlier_summary.csv,feature_drop_reason.csv')

    return {
        'feature_cols': surviving,
        'data_quality': dq_path,
        'outlier_summary': os_path,
        'feature_drop_reason': drop_path,
    }


# ---------------------------------------------------------------------------
# Stage 2 — Binning, WOE, IV
# ---------------------------------------------------------------------------

def stage_2_binning_woe(observable, cfg, feature_cols):
    """Stage 2: fit bin rules on train, apply to all sets, enforce monotonicity, compute WOE/IV.

    Mandatory call order (enforced internally):
      build_bin_rules → apply_bin_rules → enforce_monotonic_bins → build_woe_iv
    Test/OOT must reuse the training bin_rules via apply_bin_rules.

    Writes:
      bin_rules.json, bin_detail.csv, woe_rules.json,
      monotonicity_check.csv, bin_merge_log.csv

    Returns dict with artifact paths and binned DataFrames.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']
    test = observable[observable['sample_type'] == 'test']
    oot = observable[observable['sample_type'] == 'oot']

    # 1. Fit bin rules on train only
    bin_rules = build_bin_rules(
        train, feature_cols,
        bins=int(cfg.get('bins', 10)),
        max_levels=int(cfg.get('max_levels', 20)),
        special_values=cfg.get('special_values', {}),
    )

    # 2. Apply bin rules to all sets (never re-fit on test/oot)
    binned_train = apply_bin_rules(train[feature_cols], bin_rules)
    binned_test = apply_bin_rules(test[feature_cols], bin_rules) if len(test) else pd.DataFrame()
    binned_oot = apply_bin_rules(oot[feature_cols], bin_rules) if len(oot) else pd.DataFrame()

    # 3. Enforce monotonicity on train; updated_rules replaces bin_rules for downstream
    binned_train, updated_rules, merge_log = enforce_monotonic_bins(
        train, binned_train, train[target], bin_rules
    )
    if len(binned_test):
        binned_test = apply_bin_rules(test[feature_cols], updated_rules)
    if len(binned_oot):
        binned_oot = apply_bin_rules(oot[feature_cols], updated_rules)

    # 4. Compute WOE / IV
    bin_detail, iv_summary = build_woe_iv(
        train, target, binned_train, feature_cols
    )

    mono_check = monotonicity_check(bin_detail)

    # Serialize
    bin_rules_path = os.path.join(out, 'bin_rules.json')
    bin_detail_path = os.path.join(out, 'bin_detail.csv')
    woe_rules_path = os.path.join(out, 'woe_rules.json')
    mono_path = os.path.join(out, 'monotonicity_check.csv')
    merge_log_path = os.path.join(out, 'bin_merge_log.csv')

    save_json(updated_rules, bin_rules_path)
    bin_detail.to_csv(bin_detail_path, index=False, encoding='utf-8')
    save_json(woe_rules_to_json(bin_detail), woe_rules_path)
    mono_check.to_csv(mono_path, index=False, encoding='utf-8')
    merge_log.to_csv(merge_log_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_2', 'binning_woe',
                 'features=%d merges=%d' % (len(feature_cols), len(merge_log)),
                 'build_bin_rules→apply→enforce_monotonic→build_woe_iv',
                 output_files='bin_rules.json,bin_detail.csv,woe_rules.json,'
                              'monotonicity_check.csv,bin_merge_log.csv')

    return {
        'bin_rules': updated_rules,
        'bin_detail': bin_detail,
        'iv_summary': iv_summary,
        'binned_train': binned_train,
        'binned_test': binned_test,
        'binned_oot': binned_oot,
        'bin_rules_path': bin_rules_path,
        'bin_detail_path': bin_detail_path,
        'woe_rules_path': woe_rules_path,
        'monotonicity_check_path': mono_path,
        'bin_merge_log_path': merge_log_path,
    }


# ---------------------------------------------------------------------------
# Stage 3 — PSI
# ---------------------------------------------------------------------------

def stage_3_psi(observable, cfg, feature_cols, bin_rules, binned_train,
                binned_test, binned_oot):
    """Stage 3: PSI on pre-binned frames (never re-bin).

    Writes: psi_table.csv, bin_psi_detail.csv

    Returns dict with psi_summary DataFrame and surviving feature_cols.
    """
    out = cfg['output_dir']
    log_path = os.path.join(out, 'decision_log.csv')

    psi_summary, bin_psi = psi_by_bins(
        binned_train, binned_oot, feature_cols,
        test_binned=binned_test if len(binned_test) else None,
    )

    psi_path = os.path.join(out, 'psi_table.csv')
    bin_psi_path = os.path.join(out, 'bin_psi_detail.csv')
    psi_summary.to_csv(psi_path, index=False, encoding='utf-8')
    bin_psi.to_csv(bin_psi_path, index=False, encoding='utf-8')

    unstable = set(
        psi_summary[psi_summary['psi_level'] == 'unstable']['feature'].tolist()
    )
    surviving = [f for f in feature_cols if f not in unstable]

    log_decision(log_path, 'stage_3', 'psi',
                 'kept=%d unstable=%d' % (len(surviving), len(unstable)),
                 'psi_by_bins',
                 output_files='psi_table.csv,bin_psi_detail.csv')

    return {
        'psi_summary': psi_summary,
        'feature_cols': surviving,
        'psi_table_path': psi_path,
        'bin_psi_detail_path': bin_psi_path,
    }


# ---------------------------------------------------------------------------
# Stage 4 — KS / AUC / correlation
# ---------------------------------------------------------------------------

def stage_4_metrics(observable, cfg, feature_cols, bin_detail, binned_train,
                    iv_summary, psi_summary=None, leakage_df=None):
    """Stage 4: KS/AUC/correlation, update feature_drop_reason.csv.

    Writes: feature_quality.csv, feature_correlation.csv,
            feature_drop_reason.csv (updated)

    Returns dict with quality DataFrame and surviving feature_cols.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']
    woe_train = apply_woe_transform(binned_train, bin_detail)

    quality = feature_quality_from_woe(woe_train, train[target], iv_summary)
    corr = feature_correlation(
        woe_train, iv_summary,
        threshold=float(cfg.get('corr_threshold', 0.7)),
    )

    # Load existing drop_reason and extend
    drop_path = os.path.join(out, 'feature_drop_reason.csv')
    existing_drops = []
    if os.path.exists(drop_path):
        existing_df = pd.read_csv(drop_path)
        existing_drops = existing_df.to_dict('records')

    updated_drop = build_feature_drop_reason(
        leakage_df=leakage_df,
        corr_df=corr if len(corr) else None,
        psi_df=psi_summary,
    )
    # Merge existing + new drops (deduplicate by feature+stage)
    if existing_drops:
        merged = pd.concat(
            [pd.DataFrame(existing_drops), updated_drop], ignore_index=True
        ).drop_duplicates(subset=['feature', 'drop_stage'])
    else:
        merged = updated_drop

    quality_path = os.path.join(out, 'feature_quality.csv')
    corr_path = os.path.join(out, 'feature_correlation.csv')

    quality.to_csv(quality_path, index=False, encoding='utf-8')
    corr.to_csv(corr_path, index=False, encoding='utf-8')
    merged.to_csv(drop_path, index=False, encoding='utf-8')

    corr_drop_set = set(corr['suggest_drop'].tolist()) if len(corr) else set()
    surviving = [f for f in feature_cols if f not in corr_drop_set]

    log_decision(log_path, 'stage_4', 'metrics',
                 'kept=%d corr_dropped=%d' % (len(surviving), len(corr_drop_set)),
                 'feature_quality_from_woe+feature_correlation',
                 output_files='feature_quality.csv,feature_correlation.csv,'
                              'feature_drop_reason.csv')

    return {
        'feature_cols': surviving,
        'quality': quality,
        'feature_quality_path': quality_path,
        'feature_correlation_path': corr_path,
        'feature_drop_reason_path': drop_path,
    }


# ---------------------------------------------------------------------------
# Stage 5 — Decision-tree rule mining
# ---------------------------------------------------------------------------

def stage_5_tree_rules(observable, cfg, feature_cols, binned_train,
                        binned_test, binned_oot):
    """Stage 5: decision-tree rule mining.

    Tree input: integer bin codes (label_encode_bins on train).
    Test/OOT: apply_label_encode with training mappings (never re-fit).

    Writes:
      decision_tree.dot, decision_tree.png (if graphviz available),
      decision_tree_rules.csv, rule_overlap_matrix.csv

    Returns dict with rule DataFrames, masks, and artifact paths.
    """
    out = cfg['output_dir']
    target = cfg['target']
    random_state = int(cfg.get('random_state', 42))
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']

    # Integer-encode on train; apply to test/oot with same mapping
    encoded_train, label_mappings = label_encode_bins(
        binned_train[feature_cols]
    )
    encoded_test = (
        apply_label_encode(binned_test[feature_cols], label_mappings)
        if len(binned_test) else pd.DataFrame()
    )
    encoded_oot = (
        apply_label_encode(binned_oot[feature_cols], label_mappings)
        if len(binned_oot) else pd.DataFrame()
    )

    tree = fit_rule_tree(
        encoded_train, train[target],
        max_depth=int(cfg.get('tree_max_depth', 3)),
        min_samples_leaf=cfg.get('tree_min_samples_leaf', 0.03),
        min_samples_split=cfg.get('tree_min_samples_split', 0.06),
        random_state=random_state,
    )

    rules = extract_tree_single_rules(
        tree, feature_cols, train[target],
        bin_mappings=label_mappings,
    )
    rules = score_tree_rules_with_action(rules)

    dot_prefix = os.path.join(out, 'decision_tree')
    dot_path, png_path = render_tree_graphviz(
        tree, feature_cols, train[target], dot_prefix
    )

    tree_masks_train = build_rule_masks(encoded_train, rules)
    overlap = rule_overlap_matrix(tree_masks_train)

    # Build masks over the full observable encoded frame (train + test + oot)
    # so that downstream simulation stages can index any sample_type segment.
    encoded_obs_parts = [encoded_train]
    if len(encoded_test):
        encoded_obs_parts.append(encoded_test)
    if len(encoded_oot):
        encoded_obs_parts.append(encoded_oot)
    encoded_obs = pd.concat(encoded_obs_parts)
    tree_masks = build_rule_masks(encoded_obs, rules)

    rules_path = os.path.join(out, 'decision_tree_rules.csv')
    overlap_path = os.path.join(out, 'rule_overlap_matrix.csv')
    rules.to_csv(rules_path, index=False, encoding='utf-8')
    overlap.to_csv(overlap_path, index=False, encoding='utf-8')

    # Persist label mappings for use by downstream stages
    save_json(label_mappings, os.path.join(out, 'label_mappings.json'))

    log_decision(log_path, 'stage_5', 'tree_rules',
                 'rules=%d' % len(rules),
                 'fit_rule_tree+extract_tree_single_rules',
                 output_files='decision_tree.dot,decision_tree_rules.csv,'
                              'rule_overlap_matrix.csv')

    return {
        'tree': tree,
        'tree_rules': rules,
        'tree_masks': tree_masks,
        'encoded_train': encoded_train,
        'encoded_test': encoded_test,
        'encoded_oot': encoded_oot,
        'label_mappings': label_mappings,
        'decision_tree_rules_path': rules_path,
        'rule_overlap_matrix_path': overlap_path,
        'dot_path': dot_path,
        'png_path': png_path,
    }


# ---------------------------------------------------------------------------
# Stage 5.1 — Single-variable rule mining
# ---------------------------------------------------------------------------

def stage_5_1_single_rules(observable, cfg, feature_cols, bin_detail,
                            binned_train, binned_test, binned_oot):
    """Stage 5.1: extract and cross-evaluate single-variable rules.

    Writes:
      single_rule_candidates.csv, single_var_rule_eval.csv

    Returns dict with rule DataFrame, filtered rules, masks.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']

    single_rules = extract_single_var_rules(
        train, binned_train, target, feature_cols, bin_detail
    )

    filtered = filter_rule_candidates(
        single_rules,
        min_hit_rate=float(cfg.get('rule_min_hit_rate', 0.01)),
        min_bad_count=int(cfg.get('rule_min_bad_count', 10)),
        min_lift=float(cfg.get('rule_min_lift', 1.5)),
    )

    # Build combined binned frame aligned to observable index for cross-set eval
    binned_all_parts = [binned_train]
    if len(binned_test):
        binned_all_parts.append(binned_test)
    if len(binned_oot):
        binned_all_parts.append(binned_oot)
    binned_all = pd.concat(binned_all_parts)

    sv_eval = evaluate_single_var_rules_cross_set(
        observable, binned_all, filtered, target
    )

    sr_path = os.path.join(out, 'single_rule_candidates.csv')
    eval_path = os.path.join(out, 'single_var_rule_eval.csv')
    single_rules.to_csv(sr_path, index=False, encoding='utf-8')
    sv_eval.to_csv(eval_path, index=False, encoding='utf-8')

    sv_masks = build_bin_masks(binned_train, filtered)

    log_decision(log_path, 'stage_5_1', 'single_rules',
                 'candidates=%d filtered=%d' % (len(single_rules), len(filtered)),
                 'extract_single_var_rules+filter+cross_eval',
                 output_files='single_rule_candidates.csv,single_var_rule_eval.csv')

    return {
        'single_rules': single_rules,
        'filtered_single_rules': filtered,
        'sv_masks': sv_masks,
        'single_rule_candidates_path': sr_path,
        'single_var_rule_eval_path': eval_path,
    }


# ---------------------------------------------------------------------------
# Stage 5.2 — Multi-rule combination mining
# ---------------------------------------------------------------------------

def stage_5_2_combo_rules(observable, cfg, filtered_single_rules, sv_masks,
                           tree_rules=None, tree_masks=None):
    """Stage 5.2: OR combination mining from top single + tree candidates.

    Writes: rule_combination_candidates.csv

    Returns dict with combo DataFrame.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']

    # Merge single-var + tree candidates
    all_rules = filtered_single_rules.copy()
    all_masks = dict(sv_masks)
    if tree_rules is not None and len(tree_rules):
        tree_high = tree_rules[tree_rules['confidence'].isin(['HIGH', 'MEDIUM'])]
        all_rules = pd.concat([all_rules, tree_high], ignore_index=True)
        if tree_masks:
            all_masks.update(tree_masks)

    candidate_ids = all_rules.sort_values(
        'lift', ascending=False
    )['rule_id'].tolist()

    combo = mine_rule_combinations(
        train, candidate_ids, all_masks, target,
        max_combo_size=int(cfg.get('combo_max_size', 2)),
        top_n=int(cfg.get('combo_top_n', 20)),
        min_hit_rate=float(cfg.get('rule_min_hit_rate', 0.01)),
        min_bad_count=int(cfg.get('rule_min_bad_count', 10)),
        min_lift=float(cfg.get('rule_min_lift', 1.2)),
    )

    combo_path = os.path.join(out, 'rule_combination_candidates.csv')
    combo.to_csv(combo_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_5_2', 'combo_rules',
                 'combos=%d' % len(combo),
                 'mine_rule_combinations',
                 output_files='rule_combination_candidates.csv')

    return {
        'combo_rules': combo,
        'all_rule_masks': all_masks,
        'rule_combination_candidates_path': combo_path,
    }


# ---------------------------------------------------------------------------
# Stage 6 — Rule simulation
# ---------------------------------------------------------------------------

def stage_6_simulation(df_full, observable, cfg, feature_cols,
                        bin_detail, binned_train, binned_test, binned_oot,
                        filtered_single_rules,
                        tree_rules=None, tree_masks=None):
    """Stage 6: rule simulation on observable + full population.

    Both rule_simulation.csv (observable) and rule_simulation_full.csv
    (full population with reject inference) are required outputs.

    Writes:
      strategy_rules.csv, rule_simulation.csv, rule_simulation_full.csv,
      strategy_comparison.csv, strategy_level_simulation.csv,
      monthly_rule_simulation.csv, segment_rule_simulation.csv
    """
    out = cfg['output_dir']
    target = cfg['target']
    time_col = cfg.get('time_col')
    log_path = os.path.join(out, 'decision_log.csv')

    train = observable[observable['sample_type'] == 'train']

    # Build combined binned frame for observable (train + test + oot)
    binned_obs_parts = [binned_train]
    if len(binned_test):
        binned_obs_parts.append(binned_test)
    if len(binned_oot):
        binned_obs_parts.append(binned_oot)
    binned_obs = pd.concat(binned_obs_parts)

    # Merge all candidate rules and build masks on the full observable binned
    all_rules = filtered_single_rules.copy()
    sv_masks_all = build_bin_masks(binned_obs, filtered_single_rules)
    all_masks = dict(sv_masks_all)
    if tree_rules is not None and len(tree_rules):
        tree_high = tree_rules[tree_rules['confidence'].isin(['HIGH', 'MEDIUM'])]
        all_rules = pd.concat([all_rules, tree_high], ignore_index=True)
        if tree_masks:
            all_masks.update(tree_masks)

    strategy_rules_df, sim_comparison = optimize_strategy_rules(
        train, all_rules, all_masks, target,
        max_reject_rate=float(cfg.get('max_reject_rate', 0.2)),
    )

    selected_ids = strategy_rules_df['rule_id'].tolist()
    selected_masks = {
        rid: all_masks[rid] for rid in selected_ids if rid in all_masks
    }

    # Observable simulation
    obs_sim_rows = []
    for seg in ['train', 'test', 'oot']:
        seg_df = observable[observable['sample_type'] == seg]
        for rid, mask in selected_masks.items():
            seg_mask = mask.loc[seg_df.index]
            obs_sim_rows.append(
                simulate_rule(seg_df, seg_mask, target, rule_id=rid,
                              segment=seg)
            )
    obs_sim_df = pd.DataFrame(obs_sim_rows)

    # Full population simulation (observable + rejected)
    # Build full masks aligned to df_full index
    full_masks = {}
    for rid in selected_ids:
        if rid not in all_masks:
            continue
        train_mask = all_masks[rid]
        # Re-create mask for full population via binned representation
        # Use a zero-filled mask for rejected rows (target is null)
        full_mask = pd.Series(False, index=df_full.index)
        full_mask.loc[train_mask.index] = train_mask
        full_masks[rid] = full_mask

    full_sim_df = simulate_rules_full_population_by_month(
        df_full, target, time_col, full_masks,
        rejected_lift=float(cfg.get('rejected_lift', 1.5)),
        segment_col=cfg.get('segment_col'),
        segment_lift_map=cfg.get('segment_lift_map'),
    )

    monthly_sim = simulate_rules_by_month(
        observable, target, time_col, selected_masks
    ) if time_col else pd.DataFrame()

    segment_cols = cfg.get('segment_cols', [])
    segment_sim = (
        simulate_rules_by_segment(
            observable, target, segment_cols, selected_masks
        ) if segment_cols else pd.DataFrame()
    )

    # strategy_level_simulation: all obs sets combined
    strategy_level_rows = []
    for seg in ['train', 'test', 'oot']:
        seg_df = observable[observable['sample_type'] == seg]
        row = simulate_combined_rules(
            seg_df, selected_masks, target,
            selected_rule_ids=selected_ids,
            strategy_id='S001', segment=seg,
        )
        strategy_level_rows.append(row)
    strategy_level_df = pd.DataFrame(strategy_level_rows)

    # Write outputs
    strategy_rules_path = os.path.join(out, 'strategy_rules.csv')
    obs_sim_path = os.path.join(out, 'rule_simulation.csv')
    full_sim_path = os.path.join(out, 'rule_simulation_full.csv')
    comparison_path = os.path.join(out, 'strategy_comparison.csv')
    strategy_level_path = os.path.join(out, 'strategy_level_simulation.csv')
    monthly_path = os.path.join(out, 'monthly_rule_simulation.csv')
    segment_path = os.path.join(out, 'segment_rule_simulation.csv')

    strategy_rules_df.to_csv(strategy_rules_path, index=False, encoding='utf-8')
    obs_sim_df.to_csv(obs_sim_path, index=False, encoding='utf-8')
    full_sim_df.to_csv(full_sim_path, index=False, encoding='utf-8')
    sim_comparison.to_csv(comparison_path, index=False, encoding='utf-8')
    strategy_level_df.to_csv(strategy_level_path, index=False, encoding='utf-8')
    if len(monthly_sim):
        monthly_sim.to_csv(monthly_path, index=False, encoding='utf-8')
    if len(segment_sim):
        segment_sim.to_csv(segment_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_6', 'simulation',
                 'strategy_rules=%d' % len(strategy_rules_df),
                 'optimize_strategy_rules+simulate_full_population',
                 output_files='strategy_rules.csv,rule_simulation.csv,'
                              'rule_simulation_full.csv,strategy_comparison.csv,'
                              'strategy_level_simulation.csv,'
                              'monthly_rule_simulation.csv,segment_rule_simulation.csv')

    return {
        'strategy_rules': strategy_rules_df,
        'selected_masks': selected_masks,
        'full_masks': full_masks,
        'strategy_rules_path': strategy_rules_path,
        'rule_simulation_path': obs_sim_path,
        'rule_simulation_full_path': full_sim_path,
    }


# ---------------------------------------------------------------------------
# Stage 6.1 — Waterfall
# ---------------------------------------------------------------------------

def stage_6_1_waterfall(df_full, observable, cfg, strategy_rules,
                         selected_masks, full_masks):
    """Stage 6.1: sequential waterfall evaluation.

    Writes:
      waterfall_simulation.csv, waterfall_comparison.csv,
      waterfall_simulation_full.csv

    Returns dict with artifact paths.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    ordered_ids = strategy_rules['rule_id'].tolist()

    wf_obs = waterfall_cross_set(
        observable, ordered_ids, selected_masks, target
    )
    wf_full = build_waterfall_simulation_full_population(
        df_full, ordered_ids, full_masks, target,
        rejected_lift=float(cfg.get('rejected_lift', 1.5)),
        segment_col=cfg.get('segment_col'),
        segment_lift_map=cfg.get('segment_lift_map'),
    )

    wf_obs_all = build_waterfall_simulation(
        observable, ordered_ids, selected_masks, target
    )

    wf_obs_path = os.path.join(out, 'waterfall_simulation.csv')
    wf_comp_path = os.path.join(out, 'waterfall_comparison.csv')
    wf_full_path = os.path.join(out, 'waterfall_simulation_full.csv')

    wf_obs_all.to_csv(wf_obs_path, index=False, encoding='utf-8')
    wf_obs.to_csv(wf_comp_path, index=False, encoding='utf-8')
    wf_full.to_csv(wf_full_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_6_1', 'waterfall',
                 'steps=%d' % len(ordered_ids),
                 'build_waterfall_simulation+cross_set+full_population',
                 output_files='waterfall_simulation.csv,waterfall_comparison.csv,'
                              'waterfall_simulation_full.csv')

    return {
        'waterfall_simulation_path': wf_obs_path,
        'waterfall_comparison_path': wf_comp_path,
        'waterfall_simulation_full_path': wf_full_path,
    }


# ---------------------------------------------------------------------------
# Stage 7 — Summary and confidence evidence
# ---------------------------------------------------------------------------

def stage_7_summary(observable, cfg, strategy_rules, selected_masks,
                     psi_summary=None, feature_quality=None):
    """Stage 7: build confidence_evidence.csv (all three set metrics required).

    render_report.py writes strategy_summary.md from artifacts.

    Writes: confidence_evidence.csv

    Returns dict with artifact paths.
    """
    out = cfg['output_dir']
    target = cfg['target']
    log_path = os.path.join(out, 'decision_log.csv')

    evidence_rows = []
    train_df = observable[observable['sample_type'] == 'train']
    test_df = observable[observable['sample_type'] == 'test']
    oot_df = observable[observable['sample_type'] == 'oot']

    for _, rule_row in strategy_rules.iterrows():
        rid = rule_row['rule_id']
        if rid not in selected_masks:
            continue
        mask = selected_masks[rid]
        train_sim = simulate_rule(
            train_df, mask.loc[train_df.index], target, rule_id=rid
        )
        test_sim = simulate_rule(
            test_df, mask.loc[test_df.index], target, rule_id=rid
        ) if len(test_df) else {}
        oot_sim = simulate_rule(
            oot_df, mask.loc[oot_df.index], target, rule_id=rid
        ) if len(oot_df) else {}

        psi_val = None
        if psi_summary is not None:
            row = psi_summary[psi_summary['feature'].isin(
                str(rule_row.get('rule_variables', '')).split(',')
            )]
            if len(row):
                psi_val = float(row.iloc[0].get('train_oot_psi', 0))

        confidence = assign_confidence(
            train_sim, oot_sim, psi_value=psi_val
        )

        for metric_name in ('lift', 'bad_rate', 'pass_bad_rate'):
            evidence_rows.append(build_confidence_evidence(
                evidence_id='EV_%s_%s' % (rid, metric_name),
                object_type='rule',
                object_id=rid,
                metric_name=metric_name,
                train_value=float(train_sim.get(metric_name, 0.0)),
                test_value=float(test_sim.get(metric_name, 0.0)) if test_sim else 0.0,
                oot_value=float(oot_sim.get(metric_name, 0.0)) if oot_sim else 0.0,
                threshold=None,
                pass_flag=(confidence in ('HIGH', 'MEDIUM')),
                confidence=confidence,
                reason=rule_row.get('rule_readable', rid),
                source_file='rule_simulation.csv',
            ))

    evidence_df = pd.DataFrame(evidence_rows)
    ev_path = os.path.join(out, 'confidence_evidence.csv')
    evidence_df.to_csv(ev_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_7', 'summary',
                 'evidence_rows=%d' % len(evidence_df),
                 'build_confidence_evidence',
                 output_files='confidence_evidence.csv')

    return {
        'evidence': evidence_df,
        'confidence_evidence_path': ev_path,
    }


# ---------------------------------------------------------------------------
# Stage 8 — Monitoring plan
# ---------------------------------------------------------------------------

def stage_8_monitoring(cfg, strategy_rules):
    """Stage 8: generate monitoring_plan.csv.

    Writes: monitoring_plan.csv

    Returns dict with artifact path.
    """
    out = cfg['output_dir']
    log_path = os.path.join(out, 'decision_log.csv')

    rule_ids = strategy_rules['rule_id'].tolist()
    rule_variables = {}
    for _, row in strategy_rules.iterrows():
        rv = str(row.get('rule_variables', ''))
        rule_variables[row['rule_id']] = [
            v.strip() for v in rv.split(',') if v.strip()
        ]

    plan = build_monitoring_plan(rule_ids, rule_variables=rule_variables)
    plan_path = os.path.join(out, 'monitoring_plan.csv')
    plan.to_csv(plan_path, index=False, encoding='utf-8')

    log_decision(log_path, 'stage_8', 'monitoring_plan',
                 'rules=%d rows=%d' % (len(rule_ids), len(plan)),
                 'build_monitoring_plan',
                 output_files='monitoring_plan.csv')

    return {'monitoring_plan_path': plan_path}
