---
name: risk-control-credit-strategy
description: "Use when the user asks about credit / loan / consumer-finance risk strategy: cold-start launch playbooks, base credit-limit and quota sizing, risk-based limit adjustment with floors/caps/coefficients, post-loan dynamic limit management (increase / decrease / freeze / maintain), strategy tuning by risk × DTI cell, vintage / cohort analysis, portfolio monitoring (PSI, CSI, KPI alerts), champion-vs-challenger pre-rollout simulation (E[Loss] / E[Revenue] / E[Profit]), policy versioning and rollback, or causal effect evaluation (A/B, DiD, PSM, IV) of a past policy change. Runs a schema-validated, structured-logged Python pipeline (`scripts/analysis_pipeline.py`) with 9 modes plus a frozen-policy snapshot store (`policies/`) and emits decision-ready artifacts (analysis_report.md, run_summary.json with policy_readiness, validation_report.json, run_metadata.json, pipeline.log, per-mode CSVs)."
argument-hint: "State (1) product/lifecycle stage [pre-launch | pilot | scaling | mature | remediation], (2) population [new applicants | approved users | existing accounts | rejected | campaign target], (3) decision unit [approval | amount | pricing | increase | decrease | freeze | evaluation], (4) objective metric [approval_rate | bad_rate | NIM | profit | retention | …], (5) available columns and known constraints (regulatory cap, product cap, min line, risk appetite), and (6) which mode you want — one of: base_limit, risk_adjustment, dynamic_adjustment, strategy_tuning, vintage_analysis, portfolio_monitoring, simulation, causal_evaluation, full_limit_strategy — or say 'cold_start' for a launch plan only."
user-invocable: true
metadata:
    clawdbot:
        emoji: 🛡️
        os:
            - linux
            - darwin
            - win32
        requires:
            bins: []
---

# Credit Risk Strategy Operating Skill

## Mission

Build credit strategies that can be **launched, controlled, tuned, simulated, and evaluated**. The objective is stable risk-adjusted profit under affordability, exposure, compliance, and operational guardrails — **not** lowest possible risk.

Trigger this skill when the user asks about any of:

- strategy **cold start** for a new product, market, segment, or label-poor portfolio;
- initial **credit line / quota** sizing from income and capacity;
- **risk-based limit adjustment** (segment coefficients, floors, caps, exposure allocation);
- post-loan **dynamic limit management** (increase, decrease, freeze, maintain);
- **strategy tuning** after vintage, delinquency, utilization, approval, or profit movement;
- **vintage / cohort** analysis and projected mature bad-rate;
- **portfolio drift** monitoring (PSI / CSI / KPI alerts);
- **champion vs. challenger** simulation before any policy rollout;
- **policy versioning, freeze, diff, rollback**;
- **causal evaluation** of whether a policy change actually moved the metric.

## Architecture (LLM-agent quick map)

The skill is split into three layers. The agent should think of them as: *infrastructure used implicitly* + *one of nine domain modes invoked explicitly* + *outputs read back deterministically*.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Orchestration: scripts/analysis_pipeline.py    (single CLI, 9 modes)     │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │
   ┌─────────────────────────┼────────────────────────────────────────┐
   ▼                         ▼                                        ▼
┌───────────────────────┐ ┌──────────────────────────┐  ┌─────────────────────────┐
│ Cross-cutting (auto)  │ │ Domain modes (invoke 1)  │  │ Output (read all)       │
│  • schema.py          │ │  • base_limit            │  │  analysis_report.md     │
│  • validation.py      │ │  • risk_adjustment       │  │  run_summary.json       │
│    → validation_      │ │  • dynamic_adjustment    │  │    (.policy_readiness,  │
│      report.json      │ │  • strategy_tuning       │  │     .validation_report) │
│  • logging_utils.py   │ │  • vintage_analysis      │  │  validation_report.json │
│    → pipeline.log,    │ │  • portfolio_monitoring  │  │  run_metadata.json      │
│      run_metadata.json│ │  • simulation            │  │  pipeline.log           │
│  • policy_context.py  │ │  • causal_evaluation     │  │  <mode>_results.csv     │
│  • policy_versioning  │ │  • full_limit_strategy   │  │  simulation_side_by_    │
│    → policies/v*.json │ │                          │  │    side.csv (sim only)  │
│  • simulation.py      │ │                          │  │                         │
│  • config.py          │ │                          │  │                         │
└───────────────────────┘ └──────────────────────────┘  └─────────────────────────┘
```

**Read `ARCHITECTURE.md` for the full lifecycle diagram, module catalogue, and decision-gating semantics.** It is the canonical reference for module-to-module data flow.

## Agent Decision Recipe

Use this checklist on every user request — in order — before producing an answer.

### Step 1. Classify the request → pick exactly one mode

| If the user is asking about… | Pick mode | Reads doc |
|---|---|---|
| New product / market / segment with little or no local data | (no script — produce launch plan) | `cold-start.md` |
| "How big a limit should we give a new customer?" | `base_limit` | `limit-calculation.md` |
| "Convert an affordability number into a risk-adjusted final limit" | `risk_adjustment` | `risk-adjustment.md` |
| "Should we raise / lower / freeze this account's limit?" | `dynamic_adjustment` | `dynamic-adjustment.md` |
| "Which risk × DTI cells are over target? What coefficients to change?" | `strategy_tuning` | `strategy-tuning.md` |
| "How are recent cohorts performing vs. older ones?" | `vintage_analysis` | `vintage-analysis.md` |
| "Has score distribution drifted? Are KPIs deteriorating?" | `portfolio_monitoring` (needs `--base-period-path`) | `portfolio-monitoring.md` |
| "Will this proposed config improve profit / loss vs. current production?" | `simulation` (needs `--challenger-config-path`) | `ARCHITECTURE.md` §3.1 |
| "Did our previous policy change actually cause the improvement?" | `causal_evaluation` | `causal-inference.md` |
| Full new-applicant flow (base_limit + risk_adjustment combined) | `full_limit_strategy` | `limit-calculation.md` + `risk-adjustment.md` |

If the user wants to ship a policy change, the **canonical pre-rollout sequence** is:

```
strategy_tuning  →  simulation  →  policy_versioning.freeze  →  staged rollout  →  portfolio_monitoring + vintage_analysis  →  causal_evaluation
```

### Step 2. Confirm execution prerequisites

Before running anything, identify:

1. **Lifecycle stage**: pre-launch, pilot, scaling, mature, remediation.
2. **Population**: new applicants, approved users, existing accounts, rejected, campaign target.
3. **Decision unit**: approval, amount, pricing, increase, decrease, freeze, evaluation.
4. **Objective metric**: approval rate, booked volume, utilization, 7/30/60/90+ DPD, net loss, NIM, profit, retention, complaint rate.
5. **Available columns** vs. the mode's required columns (next section).
6. **Hard constraints**: regulatory cap, product cap, minimum line, funding budget, risk appetite, operational capacity.

If any of these are missing **and** they affect the chosen mode's required columns or guardrails, ask the user before running.

### Step 3. Run the pipeline

```bash
python3 scripts/analysis_pipeline.py \
  --input-path <data-file>            \
  --mode <mode>                       \
  --output-dir analysis_output        \
  [--config-path <champion.json>]     \
  [--challenger-config-path <c.json>] \
  [--base-period-path <base.csv>]     \
  [--strict-validation | --skip-validation]
```

| Flag | When to use |
|------|-------------|
| `--config-path` | The user wants to override the default champion config. |
| `--challenger-config-path` | **Required** for `simulation` mode. |
| `--base-period-path` | **Required** for `portfolio_monitoring` mode. |
| `--strict-validation` | The user is preparing a production run; range/enum violations must hard-fail. |
| `--skip-validation` | **Debug only.** Never recommend this in a production answer. |

Or use the `Makefile` shortcuts: `make base`, `make risk`, `make dynamic`, `make tuning`, `make vintage`, `make full`, `make simulate CHALLENGER=<json>`, `make monitor BASE=<csv>`, `make test`.

### Step 4. Read every output, in this order

1. **`analysis_output/run_metadata.json`** — confirm `status == "success"`. If `failed`, read `error_message` and `pipeline.log` and stop.
2. **`analysis_output/validation_report.json`** — list any range/enum/null warnings; surface them to the user.
3. **`analysis_output/run_summary.json`** — read `.policy_readiness` and `.readiness_reasons`. This is the gating signal.
4. **`analysis_output/analysis_report.md`** — narrative; cite specific numbers from here, never invent.
5. **`analysis_output/<mode>_results.csv`** — per-customer detail when the user wants drill-down.
6. For `simulation` mode also read **`simulation_side_by_side.csv`** and `summary.decision.recommendation` ∈ {`promote_to_champion_challenger_test`, `investigate`, `reject`}.

### Step 5. Decide what the user can do next

Map `policy_readiness` to action:

| Readiness | Meaning | Tell the user |
|---|---|---|
| `ready` | Decision-quality output. | Proceed. State the recommendation, expected impact, and rollout/monitoring plan. |
| `partial` | Warnings or trade-offs. | List the reasons; propose mitigation; recommend pilot rollout instead of full. |
| `blocked` | A guardrail tripped. | **Do not** ship. Explain which guardrail tripped (rank inversion, simulation reject, KPI alert, etc.) and what evidence is needed to unblock. |

## Cross-Cutting Infrastructure (use these directly)

### Schema & validation (`scripts/schema.py`, `scripts/validation.py`)

The single source of truth for "what columns does mode X need, and in what range / enum?" is `MODE_SCHEMAS` in `scripts/schema.py`. The pipeline calls `validation.validate_dataframe(df, mode)` automatically. To pre-check input from a notebook or REPL:

```python
import sys; sys.path.insert(0, "scripts")
import pandas as pd
from validation import validate_dataframe

df = pd.read_csv("my_input.csv")
report = validate_dataframe(df, "base_limit", strict=True)
print(report.to_dict())  # errors, warnings, per-column diagnostics
```

### Structured logging & run metadata (`scripts/logging_utils.py`)

Every pipeline run gets a unique `run_id`, writes `pipeline.log` and `run_metadata.json`, and records `status` (`success` / `failed`) + `error_message`. The agent should always quote the `run_id` when reporting results, so the user can correlate with any later complaint or audit.

### Champion / Challenger simulation (`scripts/simulation.py`)

Before recommending any policy change, run `simulation` mode. It executes the current production config (champion) and the proposed config (challenger) on the **same population** and reports E[Loss], E[Revenue], E[Profit], approval-rate delta, floor/cap hit-rate delta, and a recommendation. Default rejection rules:

- challenger reduces expected profit while champion is profitable → **reject**;
- challenger raises expected loss by > 20 % → **reject**;
- challenger drops approval rate by > 10 pp → **reject**;
- challenger raises affordability-block rate by > 5 pp → **investigate**.

These thresholds live in `simulation._make_simulation_decision`.

### Policy versioning (`scripts/policy_versioning.py`, `policies/`)

When the agent recommends a config change that the user approves, capture it for audit and rollback:

```python
import sys; sys.path.insert(0, "scripts")
from pathlib import Path
from config import load_config
from policy_versioning import freeze_policy, list_policies, diff_policies

cfg = load_config("challenger.json")
freeze_policy(
    config=cfg,
    version="v1.1.0_q2_tightening",
    policies_dir=Path("policies"),
    description="Tightened cap from 100k → 60k for medium-risk × dti_high",
    author="risk-strategy-team",
)
print(list_policies(Path("policies")))
print(diff_policies(
    Path("policies/v1.0.0_baseline.json"),
    Path("policies/v1.1.0_q2_tightening.json"),
))
```

The starter `policies/v1.0.0_baseline.json` is the snapshot of `DEFAULT_CONFIG` and should never be deleted — it is the rollback target.

## Module Selection Quick Table

| User intent | Use module | Runnable mode | Key script |
|---|---|---|---|
| New product/segment, little local data | `cold-start.md` | (planning only) | — |
| New customer credit line | `limit-calculation.md` | `base_limit` | `scripts/limit_calculation.py` |
| Risk-based final limit | `risk-adjustment.md` | `risk_adjustment` | `scripts/risk_adjustment.py` |
| Increase/decrease/freeze existing account | `dynamic-adjustment.md` | `dynamic_adjustment` | `scripts/dynamic_adjustment.py` |
| Cell-level diagnosis & coefficient tuning | `strategy-tuning.md` | `strategy_tuning` | `scripts/strategy_tuning.py` |
| Cohort default curves & projection | `vintage-analysis.md` | `vintage_analysis` | `scripts/vintage_analysis.py` |
| Score drift + KPI alerts | `portfolio-monitoring.md` | `portfolio_monitoring` | `scripts/portfolio_monitoring.py` |
| Pre-rollout config comparison | `ARCHITECTURE.md` §3.1 | `simulation` | `scripts/simulation.py` |
| Effect evaluation of past change | `causal-inference.md` | `causal_evaluation` | `scripts/causal_inference.py` |
| Full new-applicant flow | all of the above | `full_limit_strategy` | combined |

## Input Contract

Authoritative source: `scripts/schema.py` (`MODE_SCHEMAS`). Summary:

| Mode | Required columns | Best optional columns |
|---|---|---|
| `base_limit` | `customer_id`, `monthly_income`, `income_source`, `existing_debt`, `tenor_months` | `dti_level` |
| `risk_adjustment` | `customer_id`, `base_limit`, `risk_score`, `dti` | `affordability_status`, `floor_eligible`, `risk_level` |
| `dynamic_adjustment` | `customer_id`, `current_limit` | `behavior_score`, `repayment_months`, `overdue_status`, `utilization_rate`, `external_risk_flag`, `last_increase_months`, `score_change`, `multi_lending_count`, `fraud_flag`, `pd_estimate` |
| `strategy_tuning` | `customer_id`, `bad_flag` | `risk_level` or `risk_score`, `dti_bin` or `dti`, `final_limit`, `utilization_rate`, `months_on_book`, `channel` |
| `vintage_analysis` | `customer_id`, `origination_month`, `mob`, `dpd` | `bad_flag`, `loan_amount`, `risk_level`, `channel` |
| `portfolio_monitoring` | `customer_id`, `score`, `period` (current file) + `--base-period-path` | `bad_flag`, `approved`, `utilization_rate`, feature columns for CSI |
| `simulation` | `customer_id`, `monthly_income`, `income_source`, `existing_debt`, `tenor_months`, `risk_score`, `dti` | `utilization_rate`, `pd_estimate` |
| `causal_evaluation` | `customer_id`, `treatment`, `outcome`, `limit_before`, `limit_after` | `risk_score`, `income`, `age`, `dti`, `utilization_rate` |
| `full_limit_strategy` | base-limit columns | `risk_score`, `dti`, dynamic-management columns |

Allowed enum values (e.g. `income_source ∈ {payroll, bank_flow, tax_return, social_security, provident_fund, self_reported, model_predicted}`) and numeric ranges are encoded in `schema.py`. The pipeline auto-rejects out-of-range values when `--strict-validation` is set.

## Decision-Ready Output Standard

Every final answer the agent gives the user must contain:

1. **Policy context**: product stage, target population, decision, and objective.
2. **Data basis**: fields used, fields missing, and whether the evidence is production-ready (cite `validation_report.json`).
3. **Strategy logic**: segmentation, formula/rules, floors, caps, exclusion rules, conflict priority.
4. **Expected impact**: risk, approval/booked volume, utilization, loss, profit, operational queue impact — all from the run artifacts, never invented.
5. **Readiness status**: `ready`, `partial`, or `blocked`, with exact reasons (cite `run_summary.json`).
6. **Launch or tuning plan**: rollout percentage (start 5–10 %), monitoring windows, stop-loss thresholds, next review date.
7. **`run_id` reference** so the user can audit the run later.

## Hard Rules (do not violate)

- Separate **repayment capacity** from **risk willingness**. Capacity is the upper anchor; risk policy decides how much of it to use.
- Never apply a minimum floor to accounts with `affordability_block` or no credible repayment capacity.
- Never increase exposure for weaker risk segments unless there is a documented business exception and compensating control.
- Score direction must be normalized before binning. Higher score must consistently mean safer or riskier across the workflow.
- **Freeze is an operational block**, not a mathematical limit of zero — unless `freeze_keeps_current_limit=False` is explicitly set.
- Do not call an observational comparison causal unless treatment assignment, covariate balance, and overlap support that claim.
- Every policy must state: inclusion, exclusion, floor, cap, cooldown, stop-loss, monitoring metric, and owner.
- Never recommend a config change that has not passed `simulation` mode with `recommendation != reject`.
- Never recommend skipping `--strict-validation` for a production run.

## Blockers

Treat the answer as `blocked` rather than decision-ready when **any** of these is true:

- no credible affordability signal exists for limit assignment;
- product/regulatory cap or minimum line is unknown;
- risk ranking is inverted after coefficient/floor/cap application (`validation_passed=false` in `risk_adjustment`);
- severe-risk, decrease, and increase rules conflict without priority resolution;
- cold-start launch has no stop-loss threshold or monitoring cadence;
- effect evaluation has no control group, no pre-period, and no covariates explaining selection;
- vintage analysis uses fewer than 3 mature reference cohorts;
- PSI score shift is significant (>0.25) and auto-decisions have not been suspended;
- `simulation` mode returned `recommendation == "reject"`.

## Self-Verification

Before claiming the toolchain is healthy on a fresh checkout, run:

```bash
cd risk-control-credit-strategy
make install   # one-time
make test      # 38 pytest cases, ~6 s
```

If any test fails, do **not** trust pipeline outputs from that environment until fixed.

## Workspace Hygiene

If the agent creates `analysis_output/` or other temporary artifacts while serving a request, clean them up after reporting unless the user asked to keep them. **Never** delete `policies/` — it holds the audit trail of frozen production configs.

## Reference Files

| File | Purpose for the agent |
|---|---|
| `ARCHITECTURE.md` | Canonical lifecycle diagram + module catalogue. Read once per session. |
| `cold-start.md` … `causal-inference.md` | Domain knowledge per module — cite when explaining a decision. |
| `scripts/schema.py` | Authoritative input contract (column / type / range / enum). |
| `scripts/analysis_pipeline.py` | The CLI; do not bypass it. |
| `scripts/simulation.py` | Champion/Challenger logic and decision rules. |
| `scripts/policy_versioning.py` | `freeze_policy`, `list_policies`, `diff_policies`. |
| `policies/v1.0.0_baseline.json` | Rollback target for every change. |
| `Makefile` | Shortcut commands for every mode + `make test`. |
| `tests/` | 38 pytest cases — the regression contract for every refactor. |
