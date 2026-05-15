# Stage map — required inputs, required outputs, business rationale

Pipeline source: `scripts/lib/pipeline.py`. CLI: `scripts/run_pipeline.py --config ... --stage <id>`.

## Stage 0 — Sample scope and split

**Goal:** Establish train / test / OOT partitions and snapshot the run environment.

| Field | Detail |
|---|---|
| Driver | `scripts/lib/pipeline.py::stage_0_samples` |
| Reads  | `run_config.input_csv`, optional `time_col` |
| Writes | `run_config.json` (frozen copy), `environment.json`, `sample_profile.csv`, `sample_split_log.csv` |
| Gates  | `target` binary 0/1 on observable rows; `sample_type` column populated. |

**Sample partition rules** (from original skill):

- Observable rows (`target IS NOT NULL`) are split into `train` / `test` / `oot`.
- Rejected rows (`target IS NULL`) do **not** get a `sample_type`; they only enter
  full-population simulation in stage 6.

## Stage 0.5 — Field availability and leakage audit

| Driver | `stage_0_5_audit` |
| Reads  | `run_config.field_meta_csv` (if provided), `run_config.feature_cols` |
| Writes | `field_audit.csv`, `leakage_audit.csv` |
| Gates  | Any feature whose `available_time > decision_time`, or matches a leakage keyword, or is marked `post_loan_field`, is dropped. |

## Stage 1 — Data quality

| Driver | `stage_1_quality` |
| Reads  | observable train set + feature columns |
| Writes | `data_quality.csv`, `outlier_summary.csv`, `feature_drop_reason.csv` (initial) |
| Gates  | Constant features and `missing_rate >= 0.9` features are flagged for drop. |

## Stage 2 — Binning, WOE, IV

| Driver | `stage_2_binning_woe` |
| Reads  | train set, surviving feature columns |
| Writes | `bin_rules.json`, `bin_detail.csv`, `woe_rules.json`, `monotonicity_check.csv`, `bin_merge_log.csv` |
| Gates  | Mandatory call order: `build_bin_rules` → `apply_bin_rules` → `enforce_monotonic_bins` → `build_woe_iv`. Test/OOT must reuse `bin_rules.json` via `apply_bin_rules`, never re-fit. |

## Stage 3 — PSI stability

| Driver | `stage_3_psi` |
| Reads  | `bin_rules.json`, train/test/OOT binned frames |
| Writes | `psi_table.csv`, `bin_psi_detail.csv` |
| Gates  | Features with `psi_level == 'unstable'` (PSI > 0.25 by default) drop. |

## Stage 4 — KS / AUC / correlation

| Driver | `stage_4_metrics` |
| Reads  | WOE-transformed train data, IV summary |
| Writes | `feature_quality.csv`, `feature_correlation.csv`, updated `feature_drop_reason.csv` |
| Gates  | High-correlation pairs (Spearman >= 0.7) keep the higher-IV feature. |

## Stage 5 — Decision-tree rule mining

| Driver | `stage_5_tree_rules` |
| Reads  | label-encoded train binned frame, target |
| Writes | `decision_tree.dot`, `decision_tree.png` (when graphviz available), `decision_tree_rules.csv`, `rule_overlap_matrix.csv` |
| Gates  | Each leaf produces one rule with `rule_id`, sample counts, hit rate, bad rate, lift, readable expression. Tree input is **integer bin codes**, not WOE. Test/OOT use `apply_label_encode` with the training mapping. |

## Stage 5.1 — Single-variable rule mining

| Driver | `stage_5_1_single_rules` |
| Reads  | `bin_detail.csv`, binned train/test/OOT frames |
| Writes | `single_rule_candidates.csv` (train metrics), `single_var_rule_eval.csv` (cross-set) |
| Gates  | `filter_rule_candidates` applies `rule_min_hit_rate`, `rule_min_bad_count`, `rule_min_lift`. Cross-set lift sign must agree before promotion to stage 5.2. |

## Stage 5.2 — Multi-rule combination mining

| Driver | `stage_5_2_combo_rules` |
| Reads  | filtered single + tree candidates, rule masks |
| Writes | `rule_combination_candidates.csv` |
| Gates  | OR combinations of size 2..`combo_max_size` from the top `combo_top_n` candidates; same min-thresholds as 5.1. |

## Stage 6 — Rule simulation

| Driver | `stage_6_simulation` |
| Reads  | observable + rejected (full) frame, rule masks |
| Writes | `strategy_rules.csv`, `rule_simulation.csv`, `rule_simulation_full.csv`, `strategy_comparison.csv`, `strategy_level_simulation.csv`, `monthly_rule_simulation.csv`, `segment_rule_simulation.csv` |
| Gates  | Must emit **both** observable (`rule_simulation.csv`) and full-population (`rule_simulation_full.csv`) outputs. Full-population uses `rejected_lift` (default 1.5) or `segment_lift_map` for reject inference. |

## Stage 6.1 — Waterfall

| Driver | `stage_6_1_waterfall` |
| Reads  | ordered final rule list + masks |
| Writes | `waterfall_simulation.csv`, `waterfall_comparison.csv` (train/test/OOT), `waterfall_simulation_full.csv` |
| Gates  | Each step records `incremental_hit`, `incremental_bad`, `incremental_captured_bad_rate`. Full-population variant required. |

## Stage 7 — Summary and confidence evidence

| Driver | `stage_7_summary` + `scripts/render_report.py` |
| Reads  | every prior artifact |
| Writes | `strategy_summary.md`, `confidence_evidence.csv` |
| Gates  | Every row of `confidence_evidence.csv` must have `train_value`, `test_value`, `oot_value` populated (validator raises). Every conclusion in `strategy_summary.md` must cite a `rule_id` or `evidence_id`. |

## Stage 8 — Monitoring plan

| Driver | `stage_8_monitoring` |
| Reads  | final `strategy_rules.csv` |
| Writes | `monitoring_plan.csv` |
| Gates  | Records `hit_rate`, `bad_rate`, `pass_bad_rate`, `psi`, `coverage_rate`, `reject_rate` thresholds per rule. |
