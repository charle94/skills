# Inputs

All inputs are declared once in `run_config.json` (validated against
`schema/run_config.schema.json`). The pipeline writes a frozen copy of the
config into `runs/<run_id>/run_config.json` at the start of stage 0 — this is
the audit-of-record.

## Required keys

| Key | Type | Meaning |
|---|---|---|
| `run_id` | string | Unique identifier for the run. Used as directory name. |
| `input_csv` | path | Path to the sample CSV (read-only). |
| `target` | string | Binary target column. `1 = bad / default / overdue`; `0 = good`. Rows where `target IS NULL` are treated as historical rejections. |
| `output_dir` | path | All artifacts written here. |

## Strongly recommended keys

| Key | Type | Meaning |
|---|---|---|
| `id_col` | string | Application or customer id. Excluded from modelling. |
| `time_col` | string | Apply month / observation month. Drives time-based OOT and monthly simulation. Without it, the split falls back to stratified random. |
| `field_meta_csv` | path | Field dictionary CSV (see below). Powers leakage audit. |
| `exclude_cols` | list[string] | Columns to exclude from features (post-loan, manual-approval, etc.). |
| `special_values` | object | `{feature_name: [special_value, ...]}` — values that should bin into the SPECIAL bucket (e.g. `-99`, `-999`). |

## Tunables (sensible defaults)

| Key | Default |
|---|---|
| `test_ratio` | 0.2 |
| `oot_ratio` | 0.1 |
| `oot_months` | 3 |
| `random_state` | 42 |
| `bins` | 10 |
| `max_levels` | 20 |
| `psi_stable_threshold` | 0.1 |
| `psi_watch_threshold` | 0.25 |
| `tree_max_depth` | 3 |
| `tree_min_samples_leaf` | 0.03 |
| `tree_min_samples_split` | 0.06 |
| `rule_min_hit_rate` | 0.01 |
| `rule_min_bad_count` | 10 |
| `rule_min_lift` | 1.5 |
| `combo_max_size` | 2 |
| `combo_top_n` | 20 |
| `rejected_lift` | 1.5 |
| `max_reject_rate` | 0.2 |

## Field metadata CSV (optional but recommended)

Columns:

```
feature,source,meaning,available_time,pre_decision_available,post_loan_field,decision_time
```

- `available_time` — earliest timestamp at which the field can be queried (ISO date).
- `pre_decision_available` — boolean (`true`/`false`). `false` means the field is not available at decision time and **must** be dropped.
- `post_loan_field` — boolean. `true` forces drop.
- `decision_time` — the run's decision timestamp; can also be supplied per-row in the run_config.

## Sample column expectations

The input CSV must contain:

- The `target` column (nullable).
- The `id_col` column (recommended, unique).
- The `time_col` column (recommended, parseable date-like).
- All feature columns referenced in `feature_cols` (or every other column if `feature_cols` is null).

Rows where `target IS NULL` are kept and used only in **full-population** rule
simulation (stages 6 / 6.1). They are excluded from variable evaluation,
binning, WOE/IV, PSI, and tree mining.
