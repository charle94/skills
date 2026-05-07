---
name: risk-control-credit-strategy
description: "Use when designing, launching, adjusting, or evaluating credit risk strategies for loan/credit products, especially strategy cold start, credit limit assignment, policy tuning, dynamic account management, and policy effect evaluation. Produces executable operating steps, required data checks, runnable local pipeline commands, and decision-ready risk-control outputs."
argument-hint: "Describe product stage, customer population, policy objective, available columns, target risk/profit metric, and whether you need cold_start, base_limit, risk_adjustment, dynamic_adjustment, strategy_tuning, causal_evaluation, or full_limit_strategy."
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

Build credit strategies that can be launched, controlled, tuned, and evaluated. The goal is not the lowest possible risk; the goal is stable risk-adjusted profit under clear affordability, exposure, compliance, and operational guardrails.

Use this skill when the user asks about:
- strategy cold start for a new product, new market, new segment, or missing-label portfolio;
- initial credit line / amount / quota design;
- risk-based limit coefficients, floors, caps, approval bands, or exposure allocation;
- post-loan dynamic increase, decrease, freeze, or maintain strategies;
- strategy tuning after vintage, delinquency, utilization, approval, or profit movement;
- evaluation of whether a policy change actually caused risk/profit improvement.

## End-to-End Flow

Always run the strategy in this order unless the user explicitly requests a single module:

1. **Cold start**: define objective, population, minimum viable data, conservative launch guardrails, champion/challenger design, and stop-loss rules. See `cold-start.md`.
2. **Base limit / quota**: estimate repayment capacity before willingness-to-pay overlays. See `limit-calculation.md`.
3. **Risk adjustment**: convert capacity into approved exposure using risk score, DTI, segment coefficients, floors, and caps. See `risk-adjustment.md`.
4. **Dynamic management**: manage existing accounts with increase, decrease, freeze, or maintain queues. See `dynamic-adjustment.md`.
5. **Strategy tuning**: diagnose drift, isolate bad cells, propose minimal policy edits, and define rollout gates. See `strategy-tuning.md`.
6. **Effect evaluation**: evaluate impact with A/B, quasi-experiment, matching, or explicit observational caveats. See `causal-inference.md`.

## Module Selection

| User intent | Use module | Runnable mode |
|---|---|---|
| New product/segment with little or no local performance data | `cold-start.md` | No direct script; produce launch plan and guardrails |
| How much credit a new customer can carry | `limit-calculation.md` | `base_limit` |
| Convert base amount into risk-based final limit | `risk-adjustment.md` | `risk_adjustment` |
| Increase/decrease/freeze existing accounts | `dynamic-adjustment.md` | `dynamic_adjustment` |
| Diagnose and optimize an existing strategy | `strategy-tuning.md` | Use relevant single mode or `full_limit_strategy` |
| Prove whether a policy worked | `causal-inference.md` | `causal_evaluation` |
| Full new-limit workflow from affordability to account action | All limit modules | `full_limit_strategy` |

## Execution Contract

Before giving a recommendation, identify these facts from user input or data:

- product and lifecycle stage: pre-launch, pilot, scaling, mature, or remediation;
- population: new applicants, approved users, existing accounts, rejected applicants, or campaign target;
- decision unit: approval, amount, pricing, limit increase, limit decrease, freeze, or evaluation;
- objective metric: approval rate, booked volume, utilization, 7/30/60/90+ DPD, net loss, NIM, profit, retention, or complaint rate;
- available fields and missing blockers;
- known hard constraints: regulatory cap, product cap, minimum line, funding budget, risk appetite, operational capacity.

If data is provided, choose the smallest valid runnable mode and run:

```bash
python3 scripts/analysis_pipeline.py --input-path <data-file> --mode <mode> --output-dir analysis_output
```

Optional config override:

```bash
python3 scripts/analysis_pipeline.py --input-path <data-file> --mode <mode> --config-path <config.json> --output-dir analysis_output
```

Then read:
- `analysis_output/run_summary.json`
- `analysis_output/analysis_report.md`
- generated step CSV/JSON outputs

Do not invent numeric claims. Use script outputs or clearly label estimates as assumptions.

## Input Contract

| Mode | Required columns | Best optional columns |
|---|---|---|
| `base_limit` | `customer_id`, `monthly_income`, `income_source`, `existing_debt`, `tenor_months` | `dti_level` |
| `risk_adjustment` | `customer_id`, `base_limit`, `risk_score`, `dti` | `affordability_status`, `floor_eligible`, `risk_level` |
| `dynamic_adjustment` | `customer_id`, `current_limit` | `behavior_score`, `repayment_months`, `overdue_status`, `utilization_rate`, `external_risk_flag`, `last_increase_months`, `score_change`, `multi_lending_count`, `fraud_flag`, `pd_estimate` |
| `causal_evaluation` | `customer_id`, `treatment`, `outcome`, `limit_before`, `limit_after` | `risk_score`, `income`, `age`, `dti`, `utilization_rate` |
| `full_limit_strategy` | base-limit columns | `risk_score`, `dti`, dynamic-management columns |

## Decision-Ready Output Standard

Every final deliverable must include:

1. **Policy context**: product stage, target population, decision, and objective.
2. **Data basis**: fields used, fields missing, and whether the evidence is production-ready.
3. **Strategy logic**: segmentation, formula/rules, floors, caps, exclusion rules, and conflict priority.
4. **Expected impact**: risk, approval/booked volume, utilization, loss, profit, and operational queue impact where measurable.
5. **Readiness status**: `ready`, `partial`, or `blocked`, with exact reasons.
6. **Launch or tuning plan**: rollout percentage, monitoring windows, stop-loss thresholds, and next review date.

## Hard Rules

- Separate **repayment capacity** from **risk willingness**. Capacity is the upper anchor; risk policy decides how much of it to use.
- Never apply a minimum floor to accounts with `affordability_block` or no credible repayment capacity.
- Never increase exposure for weaker risk segments unless there is a documented business exception and compensating control.
- Score direction must be normalized before binning. Higher score must consistently mean safer or riskier across the workflow.
- Freeze is an operational block, not a mathematical limit of zero unless product policy explicitly says so.
- Do not call an observational comparison causal unless treatment assignment, covariate balance, and overlap support that claim.
- Every policy must state: inclusion, exclusion, floor, cap, cooldown, stop-loss, monitoring metric, and owner.

## Blockers

Treat the answer as `blocked` rather than decision-ready when:

- no credible affordability signal exists for limit assignment;
- product/regulatory cap or minimum line is unknown;
- risk ranking is inverted after coefficient/floor/cap application;
- severe-risk, decrease, and increase rules conflict without priority resolution;
- cold-start launch has no stop-loss threshold or monitoring cadence;
- effect evaluation has no control group, no pre-period, and no covariates explaining selection.

## Workspace Hygiene

If you create `analysis_output/` or other temporary test artifacts while using this skill, delete them after reporting the results unless the user asks to keep them.
