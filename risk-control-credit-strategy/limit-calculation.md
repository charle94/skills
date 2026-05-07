# Base Limit / Quota Calculation

## Purpose

Use this module to answer: **before risk overlays, how much credit can the customer reasonably repay?** This is the affordability anchor for initial amount, credit line, or额度策略. It should be conservative enough for launch and transparent enough for audit.

## Trigger Conditions

Use this module for:
- new-customer initial quota design;
- strategy cold-start pilot limits where repayment capacity is the safest anchor;
- recalculating base exposure after income, debt, tenor, or product cap changes;
- diagnosing whether risk-adjusted limits are being distorted by affordability errors.

Do not use this module alone to approve a final limit. Final exposure still needs risk adjustment, floors/caps, exclusions, and operational guardrails.

## Required Inputs

Minimum runnable columns:
- `customer_id`
- `monthly_income`
- `income_source`
- `existing_debt`
- `tenor_months`

Recommended optional columns:
- `dti_level`: `conservative`, `moderate`, or `aggressive`
- verified debt source, income verification timestamp, employment stability, region/product cap, customer segment

## Execution Steps

1. **Validate income credibility**
   - Rank income evidence: payroll/tax > bank flow > social security/provident fund > model predicted > self reported.
   - Apply haircut from `scripts/config.py` by `income_source`.
   - If income is self-reported or model-predicted, mark the output as constrained unless later verification exists.

2. **Calculate verified income**
   - `verified_income = monthly_income × income_haircut`.
   - Negative or missing income becomes a blocker/warning, not an opportunity to use a floor.

3. **Choose DTI threshold**
   - Conservative stage: use `conservative` unless the user provides a stronger risk appetite.
   - Mature, stable, well-verified segment: `moderate` is acceptable.
   - Aggressive threshold requires explicit business justification, monitoring, and stop-loss.

4. **Calculate monthly repayment capacity**
   - `max_monthly_repayment = verified_income × dti_threshold`.
   - `available_capacity = max_monthly_repayment - existing_debt`.
   - If `available_capacity <= 0`, set `base_limit = 0`, `affordability_status = not_affordable`, and `floor_eligible = False`.

5. **Apply tenor factor and product cap**
   - `base_limit = available_capacity × tenor_months × tenor_factor`.
   - Apply product cap after the formula.
   - Do not use long tenor to manufacture affordability where monthly capacity is already weak.

6. **Segment and review output**
   - Review by income source, DTI level, tenor bucket, and affordability status.
   - Check zero-capacity count and warning count before using outputs downstream.

## Runnable Command

```bash
python3 scripts/analysis_pipeline.py --input-path examples/base_limit_sample.csv --mode base_limit --output-dir analysis_output
```

Expected outputs:
- `base_limit_results.csv`
- `run_summary.json`
- `analysis_report.md`

## Output Fields to Use

- `verified_income`
- `income_haircut`
- `dti_threshold`
- `max_monthly_repayment`
- `available_capacity`
- `tenor_factor`
- `base_limit`
- `affordability_status`
- `floor_eligible`
- `warnings`

## Acceptance Criteria

The base-limit strategy is usable only if:
- all required columns are present;
- income source is mapped to a documented haircut;
- negative affordability never receives floor protection;
- product cap is applied;
- warning population is quantified;
- the output can be explained by formula, not by hidden manual overrides.

## Red Flags

- self-reported income drives high limits without constraint;
- stale or incomplete existing debt is treated as complete;
- one DTI threshold is applied to all risk/income segments;
- long tenor inflates exposure without repayment-capacity review;
- negative affordability is silently converted to a positive limit.
