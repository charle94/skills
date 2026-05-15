---
name: sklearn-pandas-credit-risk
description: Stable, reproducible credit-risk third-party data evaluation, WOE/IV/PSI analysis, decision-tree rule mining, and rule simulation via a fixed Python pipeline (scripts/run_pipeline.py). Replaces toad with pandas + scikit-learn. The agent orchestrates the pipeline and interprets outputs; it does NOT improvise algorithms. Use this skill when a user asks for credit-risk third-party data admission review, variable validity analysis, rule mining, rule simulation, or pre-go-live review materials. Every run produces a fixed, schema-validated artifact set in runs/<run_id>/.
allowed-tools: Bash(python3:*) Bash(python:*) Bash(pip:*) Bash(pip3:*) Bash(ls:*) Bash(cat:*) Bash(head:*) Bash(wc:*)
metadata:
  entry_prompts:
    - cr-init
    - cr-run
    - cr-review
    - cr-report
  os:
    - linux
    - darwin
---

# Sklearn + Pandas Credit-Risk Operating Skill (规范层)

## Mission

The agent must complete credit-risk third-party data evaluation, rule mining, rule policy, rule simulation, and traceable delivery using **only the fixed pipeline in `scripts/`**. Final results must include sample scope, variable evidence, rule evidence, cross-period stability, business interpretation, confidence level, and a decision log.

This skill is the operating contract. The algorithms live in `scripts/lib/` and the orchestrator is `scripts/run_pipeline.py`. **The agent must not rewrite algorithms in chat.**

## Applicable tasks

Third-party data admission evaluation, variable validity analysis, feature screening, automatic / manual binning, WOE / IV / KS / AUC / PSI analysis, scorecard auxiliary analysis, single-variable rule mining, combined rule mining, reject / review / reduce-limit strategy simulation, pre-go-live review material generation.

## How the agent works

The agent's job is split into **four verbs**: *initialize*, *run*, *review*, *report*. Each maps to a prompt template in `prompts/` and a script invocation.

| Verb | Command | What the agent does |
|---|---|---|
| Initialize | `/cr-init` → writes `runs/<run_id>/run_config.json` + scaffolds dir; calls `scripts/validate_inputs.py` |
| Run | `/cr-run <run_id> <stages>` → calls `scripts/run_pipeline.py --config ... --stage <k>`; after each stage calls `scripts/validate_outputs.py` |
| Review | `/cr-review <run_id>` → reads `manifest.json`, flags missing artifacts and stale stages |
| Report | `/cr-report <run_id>` → calls `scripts/render_report.py`, then the agent fills narrative sections backed by evidence |

The workflow extension (`extensions/credit-risk-workflow.ts`) enforces stage order and artifact completeness; the agent cannot skip stages.

## Stage map

See [`references/stages.md`](references/stages.md) for the full table. Each stage has:

- A required set of input artifacts (must exist in `runs/<run_id>/` from prior stages).
- A required set of output artifacts (must be produced before the stage is considered done).
- A confidence-evidence contribution.
- A decision-log contribution.

| Stage | Goal | Driver function (in `scripts/lib/pipeline.py`) | Key outputs |
|---|---|---|---|
| 0   | Sample scope, environment, train/test/OOT split | `stage_0_samples` | `run_config.json`, `environment.json`, `sample_profile.csv`, `sample_split_log.csv` |
| 0.5 | Field availability + leakage audit | `stage_0_5_audit` | `field_audit.csv`, `leakage_audit.csv` |
| 1   | Data quality | `stage_1_quality` | `data_quality.csv`, `outlier_summary.csv`, `feature_drop_reason.csv` |
| 2   | Binning + WOE/IV (monotonicity-enforced) | `stage_2_binning_woe` | `bin_rules.json`, `bin_detail.csv`, `woe_rules.json`, `monotonicity_check.csv`, `bin_merge_log.csv` |
| 3   | PSI stability across train/test/OOT | `stage_3_psi` | `psi_table.csv`, `bin_psi_detail.csv` |
| 4   | KS / AUC / correlation | `stage_4_metrics` | `feature_quality.csv`, `feature_correlation.csv` |
| 5   | Decision-tree multivariate rules | `stage_5_tree_rules` | `decision_tree.dot`, `decision_tree.png`, `decision_tree_rules.csv`, `rule_overlap_matrix.csv` |
| 5.1 | Single-variable rules + cross-set eval | `stage_5_1_single_rules` | `single_rule_candidates.csv`, `single_var_rule_eval.csv` |
| 5.2 | OR-combinations of candidate rules | `stage_5_2_combo_rules` | `rule_combination_candidates.csv` |
| 6   | Rule simulation (observable + full population) | `stage_6_simulation` | `strategy_rules.csv`, `rule_simulation.csv`, `rule_simulation_full.csv`, `strategy_comparison.csv`, `strategy_level_simulation.csv`, `monthly_rule_simulation.csv`, `segment_rule_simulation.csv` |
| 6.1 | Waterfall (observable + full population) | `stage_6_1_waterfall` | `waterfall_simulation.csv`, `waterfall_comparison.csv`, `waterfall_simulation_full.csv` |
| 7   | Summary + confidence evidence | `stage_7_summary` | `strategy_summary.md`, `confidence_evidence.csv` |
| 8   | Monitoring plan | `stage_8_monitoring` | `monitoring_plan.csv` |

The `decision_log.csv` is appended at every stage.

## Inputs

See [`references/inputs.md`](references/inputs.md) for the full schema. Mandatory keys in `run_config.json`:

- `run_id`, `input_csv`, `target`, `output_dir`.

Strongly recommended:

- `id_col`, `time_col`, `field_meta_csv`, `exclude_cols`, `special_values`.

The pipeline validates the config against `schema/run_config.schema.json`; malformed configs fail before stage 0.

## Outputs

See [`references/outputs.md`](references/outputs.md) for the required column list of every artifact. The agent **must not** rename outputs, drop columns, or change the directory layout.

## Confidence and traceability

See [`references/confidence.md`](references/confidence.md). Highlights:

- Every variable / rule / strategy has a stable `feature_id` / `rule_id` / `strategy_id`.
- Every conclusion in `strategy_summary.md` cites an `evidence_id`.
- `confidence_evidence.csv` must populate **all three** of `train_value`, `test_value`, `oot_value`. Missing values fail `validate_outputs.py`.

## Prohibitions

See [`references/prohibitions.md`](references/prohibitions.md) for the full list (inherited from the original `sklearn-risk-analysis` skill). Notable mechanical enforcements:

- Pipeline refuses to load `toad`.
- `stage_5_tree_rules` requires `decision_tree_rules.csv` *and* the `.dot` (PNG when graphviz is installed).
- `stage_6_simulation` always emits **both** `rule_simulation.csv` and `rule_simulation_full.csv`.
- `stage_2_binning_woe` reuses training bin rules for test/OOT — never re-fits.
- `apply_label_encode` (never `label_encode_bins`) is used on test/OOT.

## What the agent decides

After the pipeline runs, the agent reads the CSVs and **chooses**, with reasoning recorded in `decision_log.csv`:

1. Which features to drop (combining `data_quality.csv`, `leakage_audit.csv`, `feature_correlation.csv`, `psi_table.csv`).
2. Which candidate rules to keep (from `decision_tree_rules.csv`, `single_var_rule_eval.csv`, `rule_combination_candidates.csv`).
3. Which strategy actions (reject / review / observe) to apply, citing cross-period lift and confidence.
4. Whether to recommend go-live, grey release, observation, or rejection.

The agent **never** invents the underlying numbers; they always come from the pipeline outputs.
