# -*- coding: utf-8 -*-
"""
scripts/lib — deterministic credit-risk pipeline library.

Public API (import from here):

    from lib import (
        # io
        ensure_dir, save_json, safe_rate, now_text, log_decision,
        # environment
        capture_environment,
        # config
        load_config, resolve_feature_cols,
        # samples
        split_observable_sample, validate_binary_target, sample_profile,
        split_samples, stratified_random_split, get_sample, infer_feature_cols,
        # audit
        check_time_leakage, audit_fields,
        # quality
        data_quality, outlier_summary,
        # binning
        build_bin_rules, apply_bin_rules, enforce_monotonic_bins,
        ordered_numeric_categories, ordered_labels_from_binned,
        monotonicity_check, merge_log_for_non_monotonic,
        # woe
        woe_iv_for_binned_feature, build_woe_iv,
        apply_woe_transform, woe_rules_to_json,
        # psi
        psi_from_distribution, psi_by_bins,
        # metrics
        ks_score, feature_quality_from_woe, feature_correlation,
        build_feature_drop_reason,
        # tree rules
        label_encode_bins, apply_label_encode,
        fit_rule_tree, tree_node_metrics, decode_condition,
        extract_tree_single_rules, score_tree_rules_with_action,
        rule_overlap_matrix, render_tree_graphviz,
        # single-variable rules
        extract_single_var_rules, build_bin_masks,
        filter_rule_candidates, evaluate_single_var_rules_cross_set,
        # combo rules
        mine_rule_combinations,
        # simulation
        build_rule_masks, simulate_rule, simulate_rule_full_population,
        simulate_rules_full_population_by_month, simulate_combined_rules,
        optimize_strategy_rules, assign_confidence,
        simulate_rules_by_month, simulate_rules_by_segment,
        # waterfall
        build_waterfall_simulation, waterfall_cross_set,
        build_waterfall_simulation_full_population,
        # reporting
        build_strategy_rules_table, compare_strategy_simulations,
        build_confidence_evidence, build_monitoring_plan,
        # pipeline stages
        stage_0_samples, stage_0_5_audit, stage_1_quality,
        stage_2_binning_woe, stage_3_psi, stage_4_metrics,
        stage_5_tree_rules, stage_5_1_single_rules, stage_5_2_combo_rules,
        stage_6_simulation, stage_6_1_waterfall, stage_7_summary,
        stage_8_monitoring,
    )
"""

from .io_utils import ensure_dir, save_json, safe_rate, now_text, log_decision
from .environment import capture_environment
from .config import load_config, resolve_feature_cols
from .samples import (
    split_observable_sample, validate_binary_target, sample_profile,
    split_samples, stratified_random_split, get_sample, infer_feature_cols,
)
from .audit import check_time_leakage, audit_fields
from .quality import data_quality, outlier_summary
from .binning import (
    build_bin_rules, apply_bin_rules, enforce_monotonic_bins,
    ordered_numeric_categories, ordered_labels_from_binned,
    monotonicity_check, merge_log_for_non_monotonic,
)
from .woe import (
    woe_iv_for_binned_feature, build_woe_iv,
    apply_woe_transform, woe_rules_to_json,
)
from .psi import psi_from_distribution, psi_by_bins
from .metrics import (
    ks_score, feature_quality_from_woe, feature_correlation,
    build_feature_drop_reason,
)
from .tree_rules import (
    label_encode_bins, apply_label_encode,
    fit_rule_tree, tree_node_metrics, decode_condition,
    extract_tree_single_rules, score_tree_rules_with_action,
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
from .pipeline import (
    stage_0_samples, stage_0_5_audit, stage_1_quality,
    stage_2_binning_woe, stage_3_psi, stage_4_metrics,
    stage_5_tree_rules, stage_5_1_single_rules, stage_5_2_combo_rules,
    stage_6_simulation, stage_6_1_waterfall, stage_7_summary,
    stage_8_monitoring,
)

__all__ = [
    # io
    'ensure_dir', 'save_json', 'safe_rate', 'now_text', 'log_decision',
    # environment
    'capture_environment',
    # config
    'load_config', 'resolve_feature_cols',
    # samples
    'split_observable_sample', 'validate_binary_target', 'sample_profile',
    'split_samples', 'stratified_random_split', 'get_sample', 'infer_feature_cols',
    # audit
    'check_time_leakage', 'audit_fields',
    # quality
    'data_quality', 'outlier_summary',
    # binning
    'build_bin_rules', 'apply_bin_rules', 'enforce_monotonic_bins',
    'ordered_numeric_categories', 'ordered_labels_from_binned',
    'monotonicity_check', 'merge_log_for_non_monotonic',
    # woe
    'woe_iv_for_binned_feature', 'build_woe_iv',
    'apply_woe_transform', 'woe_rules_to_json',
    # psi
    'psi_from_distribution', 'psi_by_bins',
    # metrics
    'ks_score', 'feature_quality_from_woe', 'feature_correlation',
    'build_feature_drop_reason',
    # tree rules
    'label_encode_bins', 'apply_label_encode',
    'fit_rule_tree', 'tree_node_metrics', 'decode_condition',
    'extract_tree_single_rules', 'score_tree_rules_with_action',
    'rule_overlap_matrix', 'render_tree_graphviz',
    # single-variable rules
    'extract_single_var_rules', 'build_bin_masks',
    'filter_rule_candidates', 'evaluate_single_var_rules_cross_set',
    # combo rules
    'mine_rule_combinations',
    # simulation
    'build_rule_masks', 'simulate_rule', 'simulate_rule_full_population',
    'simulate_rules_full_population_by_month', 'simulate_combined_rules',
    'optimize_strategy_rules', 'assign_confidence',
    'simulate_rules_by_month', 'simulate_rules_by_segment',
    # waterfall
    'build_waterfall_simulation', 'waterfall_cross_set',
    'build_waterfall_simulation_full_population',
    # reporting
    'build_strategy_rules_table', 'compare_strategy_simulations',
    'build_confidence_evidence', 'build_monitoring_plan',
    # pipeline stages
    'stage_0_samples', 'stage_0_5_audit', 'stage_1_quality',
    'stage_2_binning_woe', 'stage_3_psi', 'stage_4_metrics',
    'stage_5_tree_rules', 'stage_5_1_single_rules', 'stage_5_2_combo_rules',
    'stage_6_simulation', 'stage_6_1_waterfall', 'stage_7_summary',
    'stage_8_monitoring',
]
