# Dynamic Limit Adjustment

## Purpose

Use this module to manage existing accounts after booking: **increase, decrease, freeze, or maintain**. The output should be directly usable as an operations queue and should prioritize risk containment over growth triggers when signals conflict.

## Trigger Conditions

Use this module when:
- deciding account-level limit increase/decrease/freeze actions;
- building monthly or weekly post-loan management queues;
- reacting to delinquency, fraud, external risk, multi-lending, score movement, or high utilization;
- tuning exposure after observing behavior performance.

## Required Inputs

Minimum runnable columns:
- `customer_id`
- `current_limit`

Recommended fields for production quality:
- `behavior_score`
- `repayment_months`
- `overdue_status`
- `utilization_rate`
- `external_risk_flag`
- `last_increase_months`
- `score_change`
- `multi_lending_count`
- `behavior_change_flag`
- `fraud_flag`
- `pd_estimate` or `pd`
- `user_request`

## Conflict Priority

Apply actions in this order:

1. **Freeze**: fraud, M2+, severe external risk, serious behavior abnormality.
2. **Decrease**: M1, large score drop, high multi-lending, material deterioration.
3. **Increase**: good repayment, improved score, high healthy utilization, eligible active request.
4. **Maintain**: no trigger, insufficient evidence, or cooldown not satisfied.

Increase rules must never override freeze or decrease rules.

## Execution Steps

1. **Validate account state**
   - Confirm current limit, status, overdue bucket, and whether the account is active.
   - Exclude closed, charged-off, written-off, deceased, legal, or fraud-confirmed accounts from normal increase logic.

2. **Detect negative triggers**
   - Immediate freeze: fraud, M2+, severe external risk.
   - Gradual decrease: M1, large score drop, multi-lending threshold breach.
   - Behavior abnormality can freeze or route to manual review depending on policy.

3. **Detect positive triggers**
   - Repayment months meet threshold.
   - Score improves materially.
   - Utilization is high but repayment is healthy.
   - User request is allowed and required proof exists.

4. **Apply cooldown and frequency limits**
   - Increase only after configured cooldown, currently `increase_frequency_months` in `scripts/config.py`.
   - Do not repeatedly increase customers whose last adjustment is too recent.

5. **Calculate suggested action**
   - Freeze: keep current limit if `freeze_keeps_current_limit = True`, but set operational action to `freeze_usage`.
   - Decrease: reduce limit by severity-based amount.
   - Increase: calculate increase ratio based on utilization, repayment history, and behavior score.

6. **Estimate loss impact**
   - Prefer `pd_estimate` or `pd` from a model.
   - If only heuristic behavior score is used, mark readiness as partial.

7. **Sort operations queue**
   - Lower priority number means earlier handling.
   - Freeze and severe decrease queues must be reviewed before growth queues.

## Runnable Command

```bash
python3 scripts/analysis_pipeline.py --input-path <dynamic-adjustment-data.csv> --mode dynamic_adjustment --output-dir analysis_output
```

Expected outputs:
- `dynamic_adjustment_results.csv`
- `run_summary.json`
- `analysis_report.md`

## Output Fields to Use

- `adjustment_action`
- `adjustment_type`
- `operational_action`
- `trigger_reasons`
- `suggested_limit`
- `adjustment_ratio`
- `expected_el_change`
- `pd_source`
- `priority`
- `current_limit`

## Acceptance Criteria

The dynamic strategy is usable only if:
- action conflict priority is explicit;
- severe-risk accounts cannot be increased;
- cooldown is applied to increases;
- freeze is represented as an operational block, not confused with a zero limit;
- expected loss impact is calculated or the limitation is clearly marked;
- operations queue can be sorted by priority and reason.

## Red Flags

- the same account qualifies for increase and decrease without conflict resolution;
- increase logic ignores recent delinquency or score deterioration;
- freeze action appears as ordinary maintain;
- no PD or loss-impact basis exists for large exposure changes;
- growth queues are run before urgent risk queues.
