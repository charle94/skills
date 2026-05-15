# Agent rules for the pi-credit-risk package

Agents working inside this package **must** follow these rules. The workflow
extension (`extensions/credit-risk-workflow.ts`) enforces a subset of them
mechanically; the rest are honor-system but mandatory.

## 1. Algorithms are frozen — do not improvise

- **Never** rewrite or re-implement algorithms from `scripts/lib/` in ad-hoc
  bash heredocs, notebook cells, or chat-message Python.
- All credit-risk computations go through `scripts/run_pipeline.py`,
  which dispatches to `scripts/lib/pipeline.py`.
- If a function in `scripts/lib/` is missing or wrong, **fix it in place** and
  re-run the pipeline. Do not paper over with inline code.

## 2. The run directory is the single source of truth

- Every run writes only to `runs/<run_id>/`.
- The input CSV and the field-metadata CSV are **read-only**. Never modify
  them, never copy them into `runs/<run_id>/raw_…` and edit.
- `runs/<run_id>/manifest.json` is the state of the run. The workflow
  extension reads it to decide whether the next stage may proceed.

## 3. Configuration is centralized

- All run parameters live in `runs/<run_id>/run_config.json`, validated
  against `schema/run_config.schema.json`.
- Do not pass parameters via environment variables or hidden flags. If a
  knob is needed, add it to the schema first.
- `random_state` (default `42`) is the only source of randomness.

## 4. Stage order is hard

The pipeline stages **must** run in order. The extension rejects out-of-order
invocations.

```
0 (samples) → 0.5 (field/leakage audit) → 1 (data quality) → 2 (binning + WOE/IV)
  → 3 (PSI) → 4 (KS/AUC + correlation) → 5 (tree rules) → 5.1 (single-var rules)
  → 5.2 (combo rules) → 6 (simulation) → 6.1 (waterfall) → 7 (summary) → 8 (monitoring)
```

Required artifacts for each stage are listed in
`skills/sklearn-pandas-credit-risk/references/outputs.md` and machine-enforced
by `scripts/validate_outputs.py`.

## 5. Evidence and traceability

- Every conclusion in `strategy_summary.md` must cite a `rule_id`,
  `feature_id`, `strategy_id`, or `evidence_id`.
- Every row of `confidence_evidence.csv` must have **all three** of
  `train_value`, `test_value`, `oot_value` populated. Missing values fail
  validation.
- Every key action must be recorded in `decision_log.csv` (timestamp, stage,
  decision, reason).

## 6. Bash usage

Allowed:
- `python3 scripts/...`
- `python3 -m pytest tests/...`
- `pip install -r requirements.txt` (initialization only)
- Read-only inspection: `ls`, `cat` on `runs/<run_id>/`, `head`, `wc`

Forbidden:
- Any write outside `runs/<run_id>/`
- `git push`, `git commit -a` from the agent process (use report_progress instead)
- Direct CSV/JSON manipulation that bypasses `scripts/lib/`

## 7. Prohibitions inherited from the original skill

See `skills/sklearn-pandas-credit-risk/references/prohibitions.md`. Highlights:

- No post-loan, result, or manual-approval fields as features.
- No reject rule based on IV alone, a single-period bad rate, or a single
  lift number.
- No strong reject rule whose sample size, bad count, or cross-period stability
  is below thresholds documented in `references/confidence.md`.
- No tree-rule export without `decision_tree.png` *and* `decision_tree_rules.csv`.
- No `rule_simulation.csv` without the matching `rule_simulation_full.csv`
  (reject-inference required).

## 8. Reporting

- Final report **template** is `skills/sklearn-pandas-credit-risk/templates/strategy_summary.template.md`.
- The agent fills in evidence-backed sections only. Do not freestyle headings.
- `scripts/render_report.py` writes the file; the agent may then edit
  narrative sections but **must not** alter numeric tables (which are
  generated from the CSVs).
