# Policy Effect Evaluation

## Purpose

Use this module to answer: **did the strategy change cause a measurable improvement or deterioration in risk, profit, utilization, or customer behavior?** In credit strategy, raw before/after or treated/control differences are often selection bias, so the evaluation must grade evidence quality.

## Trigger Conditions

Use this module when:
- evaluating a limit increase/decrease/cold-start pilot/campaign;
- deciding whether to scale, rollback, or retune a strategy;
- comparing champion and challenger policies;
- checking whether observed risk/profit movement is causal or only descriptive.

## Required Inputs

Minimum runnable columns:
- `customer_id`
- `treatment`: 1 if exposed to the new strategy, 0 otherwise
- `outcome`: target outcome such as default flag, bad flag, profit flag, or other binary outcome
- `limit_before`
- `limit_after`

Recommended covariates:
- `risk_score`
- `income`
- `age`
- `dti`
- `utilization_rate`
- channel, region, tenure, previous DPD, product type, pre-period balance/utilization

## Evidence Tiers

Use the strongest valid tier available:

1. **Randomized A/B**: treatment assigned randomly with stable control group. Best for causal claims.
2. **Quasi-experiment**: threshold, phased rollout, geographic split, or policy cutover with credible comparison.
3. **PSM / matched observational**: use only when covariates explain treatment selection and balance diagnostics pass.
4. **Descriptive only**: no reliable control/covariates. Do not use causal language.

## Execution Steps

1. **Define treatment and outcome window**
   - Treatment date must precede outcome window.
   - Outcome window must be long enough for the metric, e.g. 30/60/90+ DPD needs seasoning.
   - Exclude accounts where treatment status is ambiguous.

2. **Check sample and control validity**
   - Treatment and control groups must both exist.
   - Control group must be eligible under similar business conditions.
   - If rejected or ineligible customers are used as controls, state the bias risk.

3. **Run effect estimation**
   - Estimate ATE from treated vs control outcome rates.
   - Estimate ATT after matching when covariates are available.
   - Report confidence interval; do not rely only on point estimate.

4. **Check balance and overlap**
   - Standardized mean difference after matching should be below the configured threshold, default `max_abs_smd <= 0.10`.
   - Matching rate should meet configured minimum, default `>= 0.60`.
   - Weak overlap means the result is partial, not decision-ready.

5. **Simulate business impact**
   - Pair default/risk movement with limit, revenue, loss, cost, and profit assumptions.
   - Separate statistical significance from business significance.

6. **Make scale/rollback decision**
   - Scale only if risk, profit, and operational metrics pass gates.
   - Roll back or narrow if bad rate, loss, complaints, or liquidity usage breach stop-loss.
   - Continue pilot if evidence is underpowered but no stop-loss is triggered.

## Runnable Command

```bash
python scripts/analysis_pipeline.py --input-path <evaluation-data.csv> --mode causal_evaluation --output-dir analysis_output
```

Expected outputs:
- `causal_evaluation_report.md`
- `run_summary.json`
- `analysis_report.md`

## Output Fields to Use

- `ate`
- `att`
- `lift`
- `ks_statistic`
- `ks_pvalue`
- `confidence_interval_95`
- `sample_sizes`
- `default_rates`
- `balance_diagnostics`
- `overlap_diagnostics`
- `profit_simulation`
- `evidence_tier`

## Acceptance Criteria

The evaluation is decision-ready only if:
- treatment and outcome windows are clearly ordered;
- treatment and control groups both exist;
- covariate balance and overlap are acceptable for matched designs;
- confidence interval and business impact are both reported;
- the conclusion uses causal wording only when evidence tier supports it;
- the scale/rollback recommendation is tied to predefined gates.

## Red Flags

- no untreated/control group exists;
- treatment assignment depends on variables missing from the dataset;
- outcome window is too short for delinquency to mature;
- treated customers were preselected because they were already safer;
- a raw average difference is described as causal impact;
- profit simulation ignores loss or operational cost.
