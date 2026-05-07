# Architecture: Credit Risk Strategy Skill

This document is the canonical view of how the skill is organized: which
modules exist, what data flows between them, and how an operator chains them
together to take a policy from cold-start through investigation, monitoring,
tuning, and rollout.

## 1. High-level layered architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Orchestration & CLI                                                 │
│    scripts/analysis_pipeline.py  (single CLI entry point, mode-based)  │
└────────────────────────────┬───────────────────────────────────────────┘
                             │
   ┌─────────────────────────┼──────────────────────────────────────┐
   ▼                         ▼                                      ▼
┌──────────────────┐   ┌────────────────────┐         ┌────────────────────────┐
│ 2. Cross-cutting │   │ 3. Domain modules  │         │ 4. Output layer        │
│   schema.py      │   │   limit_calculation│         │  analysis_report.md    │
│   validation.py  │   │   risk_adjustment  │         │  *.csv per stage       │
│   logging_utils  │   │   dynamic_adjust.  │         │  run_summary.json      │
│   policy_context │   │   strategy_tuning  │         │  run_metadata.json     │
│   policy_version.│   │   vintage_analysis │         │  validation_report.json│
│   simulation     │   │   portfolio_monit. │         │  pipeline.log          │
│   config.py      │   │   causal_inference │         └────────────────────────┘
└──────────────────┘   └────────────────────┘
                             │
                             ▼
                       ┌──────────────────┐
                       │ 5. Policies      │
                       │   policies/      │
                       │   versioned JSON │
                       │   snapshots      │
                       └──────────────────┘
```

## 2. End-to-end module flow (the credit risk lifecycle)

```
                       ┌────────────────────┐
   New product /       │  cold-start.md     │  knowledge-only stage
   new segment ───────►│  (rules, expert    │  (no script): seed config
                       │   knowledge,       │  produces an initial
                       │   benchmarks)      │  CreditLimitConfig
                       └─────────┬──────────┘
                                 │ produces
                                 ▼
                       ┌────────────────────┐
   Applicants ────────►│ limit_calculation  │  base_limit + affordability
                       │ (base_limit mode)  │  + floor_eligible
                       └─────────┬──────────┘
                                 ▼
                       ┌────────────────────┐
                       │ risk_adjustment    │  risk-adjusted final_limit
                       │ (risk_adjustment   │  + applied_constraint
                       │  mode)             │  (floor / cap / capacity)
                       └─────────┬──────────┘
                                 │ deploy
                                 ▼
   ┌──────────────────────► booked accounts ◄──────────────────────┐
   │                                                                │
   │ time passes, repayment data arrives                            │
   │                                                                │
   ▼                                                                │
┌────────────────────┐    ┌────────────────────┐     ┌──────────────┴───┐
│ dynamic_adjustment │    │ vintage_analysis   │     │ portfolio_       │
│ (per-customer      │    │ (cohort × MOB      │     │ monitoring       │
│  freeze/decrease/  │    │  bad-rate matrix,  │     │ (PSI, CSI, KPI   │
│  increase actions) │    │  deterioration     │     │  alerts)         │
└─────────┬──────────┘    │  detection)        │     └────────┬─────────┘
          │               └─────────┬──────────┘              │
          │                         │                         │
          └──────┬──────────────────┴───────────┬─────────────┘
                 ▼                              ▼
       ┌────────────────────┐        ┌────────────────────┐
       │ strategy_tuning    │        │ causal_inference   │
       │ (cell-level diag,  │        │ (DiD, PSM, IV) for │
       │  recommended       │        │ effect attribution │
       │  coefficient       │        │ of past changes    │
       │  factors)          │        └─────────┬──────────┘
       └─────────┬──────────┘                  │
                 │                             │
                 └──────────────┬──────────────┘
                                ▼
                    ┌────────────────────────┐
                    │ simulation             │  Champion vs Challenger
                    │ (champion vs proposed  │  E[Loss], E[Revenue],
                    │  policy on same        │  E[Profit], decision
                    │  population)           │  (promote / investigate
                    └─────────────┬──────────┘   / reject)
                                  │
                                  ▼
                    ┌────────────────────────┐
                    │ policy_versioning      │  Freeze and snapshot
                    │ (freeze, list, diff)   │  policy under
                    └─────────────┬──────────┘  policies/v*.json
                                  │
                                  ▼
                          rollout (5%-10%-50%-100%)
                                  │
                                  └────► back to dynamic_adjustment loop
```

## 3. Module catalogue

### 3.1 Cross-cutting (`scripts/`)

| File | Responsibility |
|------|----------------|
| `config.py` | Single dataclass tree of all coefficients/thresholds; loaded via `DEFAULT_CONFIG` or `load_config(path)`. |
| `schema.py` | `MODE_SCHEMAS` — column contracts (required, dtype, range, enum) for every mode. Single source of truth for "what does mode X need?". |
| `validation.py` | `validate_dataframe(df, mode)` returns a structured `ValidationReport` (errors, warnings, per-column diagnostics). |
| `logging_utils.py` | `setup_logger`, `RunMetadata`, `make_run_id`. Writes `pipeline.log` and `run_metadata.json` per run. |
| `policy_context.py` | `PolicyRun` — shared run-state object; lets stages publish summaries that downstream stages can read. |
| `policy_versioning.py` | `freeze_policy`, `list_policies`, `load_policy_config`, `diff_policies`. |
| `simulation.py` | Champion vs Challenger engine. Runs both configs end-to-end, scores expected loss/revenue/profit, produces a decision. |
| `analysis_pipeline.py` | The CLI; dispatches to one of 9 modes; wires logging + validation + readiness gating. |

### 3.2 Domain modules

| Module | Knowledge doc | Stage | Inputs | Key outputs |
|--------|---------------|-------|--------|-------------|
| `limit_calculation.py` | `base-limit.md` | Pre-credit | income, debt, tenor | `base_limit`, `affordability_status`, `floor_eligible` |
| `risk_adjustment.py` | `risk-adjustment.md` | Pre-credit | base_limit, risk_score, dti | `final_limit`, `risk_level`, `applied_constraint` |
| `dynamic_adjustment.py` | `dynamic-adjustment.md` | Post-credit | current_limit, behavior_score, overdue_status, utilization | `adjustment_action` ∈ {freeze, decrease, increase, maintain}, `suggested_limit` |
| `strategy_tuning.py` | `strategy-tuning.md` | Post-credit (analysis) | bad_flag, risk_level, dti_bin, channel | `recommended_coefficient_factor` per cell, `expected_el_reduction` |
| `vintage_analysis.py` | `vintage-analysis.md` | Post-credit (monitoring) | origination_month, mob, dpd | cohort × MOB matrix, deterioration flags, projected mature bad rate |
| `portfolio_monitoring.py` | `portfolio-monitoring.md` | Post-credit (monitoring) | score, period, KPIs, base_period_df | PSI, CSI per feature, KPI trend alerts |
| `causal_inference.py` | `causal-evaluation.md` | Effect evaluation | treatment, outcome, covariates | ATE via DiD/PSM/IV, sensitivity, recommendation |

## 4. Run modes (CLI)

`python3 scripts/analysis_pipeline.py --mode <mode> --input-path <csv> --output-dir <dir>`

| Mode | Required input columns (subset) | Special args |
|------|---------------------------------|--------------|
| `base_limit` | customer_id, monthly_income, income_source, existing_debt, tenor_months | — |
| `risk_adjustment` | customer_id, base_limit, risk_score, dti | — |
| `dynamic_adjustment` | customer_id, current_limit | — |
| `causal_evaluation` | customer_id, treatment, outcome, limit_before, limit_after | — |
| `strategy_tuning` | customer_id, bad_flag (+ segmentation cols) | — |
| `vintage_analysis` | customer_id, origination_month, mob, dpd | — |
| `portfolio_monitoring` | customer_id, score, period | `--base-period-path` |
| `full_limit_strategy` | union of base_limit + risk_adjustment | — |
| `simulation` | base_limit + risk_score + dti | `--challenger-config-path` |

Common flags:
- `--config-path <json>` override champion config.
- `--strict-validation` treat range/enum violations as hard errors.
- `--skip-validation` skip schema check (debug only).

## 5. Output contract per run

Every run writes the following into `output_dir/`:

| File | Purpose |
|------|---------|
| `analysis_report.md` | Human-readable narrative report + Policy Readiness gating |
| `run_summary.json` | Machine-readable summary, includes `policy_readiness` and `validation_report` |
| `validation_report.json` | Per-column diagnostics from validation layer |
| `run_metadata.json` | Run id, started_at, finished_at, status, error_message |
| `pipeline.log` | Structured log stream |
| `<mode>_results.csv` | Per-customer detail (when applicable) |
| `simulation_side_by_side.csv` | Champion/Challenger per-customer deltas (simulation mode only) |

## 6. Decision gating

`analysis_pipeline.determine_policy_readiness` aggregates the above into one
of:

| Status | Meaning | Operator action |
|--------|---------|-----------------|
| `ready` | All checks passed; outputs are fit for downstream decisioning. | Proceed. |
| `partial` | Some warnings (drift, capacity blocks, low data). | Investigate, may proceed with mitigation. |
| `blocked` | Hard failure (validation rank, simulation rejected, high-severity alerts). | Do **not** ship; root-cause first. |

## 7. Lifecycle from cold-start to production

1. **Seed** an initial config (rules + expert priors) — see `cold-start.md`.
2. **Validate inputs** for the production population using `validation.py`.
3. **Run** `full_limit_strategy` to produce base + risk-adjusted limits.
4. **Simulate** the proposed config against the current production config.
5. If the decision is `promote_to_champion_challenger_test`, **freeze** with
   `policy_versioning.freeze_policy(...)` to create `policies/v<n>.json`.
6. **Roll out** in stages (5% → 25% → 50% → 100%); `analysis_pipeline.py
   --mode portfolio_monitoring` against base-period data.
7. After ≥ 3 cohorts have ≥ 6 MOB observation, run `vintage_analysis` and
   `strategy_tuning` to refine coefficients.
8. Use `causal_evaluation` for any policy lever change to measure ATE.
9. Repeat from step 2.

## 8. Testing

Run the full suite with:

```
python3 -m pytest tests/ -q
```

The suite covers: validation layer, limit calculation invariants, risk
adjustment binning + cap, dynamic-adjustment freeze logic, strategy tuning
diagnostics, vintage matrix + reference curve, portfolio monitoring PSI,
simulation behaviour, and end-to-end pipeline integration including
artifact creation and failure-path metadata recording.
