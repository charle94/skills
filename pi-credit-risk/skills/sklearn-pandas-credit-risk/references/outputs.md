# Output artifacts — required files and columns

Every artifact in `runs/<run_id>/` is hashed (SHA-256) into `manifest.json`.
`scripts/validate_outputs.py` enforces the completeness checks below for the
relevant stage and refuses to advance the state machine otherwise.

## Stage 0 — Samples and environment

| File | Required columns |
|---|---|
| `run_config.json` | (frozen copy of input config) |
| `environment.json` | `python`, `platform`, `pandas`, `numpy`, `scipy`, `sklearn` |
| `sample_profile.csv` | `segment, sample_count, bad_count, bad_rate` |
| `sample_split_log.csv` | `sample_type, sample_count, sample_rate, bad_count, bad_rate, split_method, random_state` |
| `decision_log.csv` | `timestamp, stage, object_id, decision, reason, input_files, output_files, operator_note` (appended every stage) |

## Stage 0.5 — Field audit

| File | Required columns |
|---|---|
| `field_audit.csv` | `feature, source, meaning, available_time, pre_decision_available, post_loan_field, keyword_hit, time_leakage_flag, leakage_flag, decision` |
| `leakage_audit.csv` | subset of `field_audit.csv` rows where `leakage_flag == True` |

## Stage 1 — Quality

| File | Required columns |
|---|---|
| `data_quality.csv` | `feature, dtype, sample_count, missing_count, missing_rate, coverage_rate, unique_count, unique_rate, top1_value, top1_rate, special_rate, is_constant, is_high_cardinality` |
| `outlier_summary.csv` | `feature, lower_bound, upper_bound, outlier_rate` |
| `feature_drop_reason.csv` | `feature, drop_stage, drop_reason` (appended) |

## Stage 2 — Binning and WOE/IV

| File | Required columns |
|---|---|
| `bin_rules.json` | `{feature: {type, variable_type, cut_points|levels, special_values}}` |
| `bin_detail.csv` | `feature, variable_type, bin_order, bin_label, sample_count, sample_rate, good_count, bad_count, bad_rate, overall_bad_rate, lift, woe, iv_component` |
| `woe_rules.json` | `{feature: {bin_label: woe}}` |
| `monotonicity_check.csv` | `feature, bin_count, non_decreasing, non_increasing, monotonic_flag, bad_rate_path, reason` |
| `bin_merge_log.csv` | `feature, merged_from, removed_cut_point, reason, direction` |

## Stage 3 — PSI

| File | Required columns |
|---|---|
| `psi_table.csv` | `feature, train_oot_psi, psi, psi_level [, train_test_psi, test_oot_psi]` |
| `bin_psi_detail.csv` | `feature, bin_label, train_pct, test_pct, oot_pct, train_oot_delta [, train_test_delta, test_oot_delta]` |

## Stage 4 — Metrics

| File | Required columns |
|---|---|
| `feature_quality.csv` | `feature, iv, ks, auc` |
| `feature_correlation.csv` | `feature_left, feature_right, spearman_corr, suggest_drop, reason` |

## Stage 5 — Tree rules

| File | Required columns |
|---|---|
| `decision_tree.dot` | (Graphviz DOT, label `\n` must be a literal backslash-n; nodes colored by `bad_rate / overall_bad_rate`) |
| `decision_tree.png` | (only if graphviz + system `dot` installed) |
| `decision_tree_rules.csv` | `rule_id, node_id, rule_expression, rule_readable, rule_variables, variable_count, sample_count, good_count, bad_count, hit_rate, bad_rate, lift, overall_bad_rate, action, confidence` |
| `rule_overlap_matrix.csv` | `rule_id, <rule_id columns>` |

## Stage 5.1 — Single-variable rules

| File | Required columns |
|---|---|
| `single_rule_candidates.csv` | `rule_id, source, feature, bin_label, rule_readable, rule_variables, variable_count, sample_count, good_count, bad_count, hit_rate, bad_rate, lift, overall_bad_rate, woe, iv_component` |
| `single_var_rule_eval.csv` | `segment, rule_id, sample_count, bad_count, overall_bad_rate, hit_count, hit_rate, hit_bad_count, hit_bad_rate, lift, pass_count, pass_rate, pass_bad_count, pass_bad_rate, captured_bad_rate, false_reject_good_count` |

## Stage 5.2 — Combo rules

| File | Required columns |
|---|---|
| `rule_combination_candidates.csv` | columns of `single_var_rule_eval.csv` plus `combo_rule_ids`, `combo_size` |

## Stage 6 — Simulation

| File | Required columns |
|---|---|
| `strategy_rules.csv` | `strategy_id, rule_id, action, confidence, rule_readable, rule_variables` |
| `rule_simulation.csv` | columns of `single_var_rule_eval.csv` (segment in {train,test,oot,ALL}) |
| `rule_simulation_full.csv` | `segment, rule_id, reject_inference_method, observable_*, rejected_*, full_*` |
| `strategy_comparison.csv` | `metric, <before_id>, <after_id>, delta, relative_change` |
| `strategy_level_simulation.csv` | `strategy_id, rule_count, selected_rule_ids` + simulate_rule output |
| `monthly_rule_simulation.csv` | `rule_id, segment=<period>, ...` rows |
| `segment_rule_simulation.csv` | `rule_id, segment=<seg_col=value>, ...` rows |

## Stage 6.1 — Waterfall

| File | Required columns |
|---|---|
| `waterfall_simulation.csv` | simulate_rule columns + `waterfall_step, added_rule_id, cumulative_rule_ids, incremental_hit, incremental_bad, incremental_hit_rate, incremental_captured_bad_rate` |
| `waterfall_comparison.csv` | same, with `segment` ∈ {train, test, oot} |
| `waterfall_simulation_full.csv` | full-population simulate columns + waterfall metadata + `incremental_full_*` |

## Stage 7 — Summary

| File | Required columns |
|---|---|
| `strategy_summary.md` | sections 1..12 listed in original skill (sample scope, field audit, …, monitoring, risk notes) |
| `confidence_evidence.csv` | `evidence_id, object_type, object_id, metric_name, train_value, test_value, oot_value, threshold, pass_flag, confidence, reason, source_file` — **all three of train/test/oot must be non-null** |

## Stage 8 — Monitoring

| File | Required columns |
|---|---|
| `monitoring_plan.csv` | `rule_id [, feature], metric, meaning, frequency, alert_rule` |

## Always present

| File | Purpose |
|---|---|
| `decision_log.csv` | Append-only audit log; written by every stage. |
| `manifest.json` | State machine + per-artifact SHA-256. Schema: `schema/artifact_manifest.schema.json`. |
