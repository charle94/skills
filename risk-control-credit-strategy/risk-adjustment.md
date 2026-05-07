# Risk Adjustment and Final Limit Policy

## Purpose

Use this module to answer: **given repayment capacity, how much exposure are we willing to take for this risk segment?** It converts base limit into final usable limit through score bands, DTI buckets, coefficients, floors, caps, and validation.

## Trigger Conditions

Use this module when:
- base limits already exist and need risk-based scaling;
- setting approval/limit bands by risk score, DTI, or customer segment;
- checking whether floors/caps distort risk ranking;
- preparing final limits for launch, pilot, or strategy tuning.

## Required Inputs

Minimum runnable columns:
- `customer_id`
- `base_limit`
- `risk_score`
- `dti`

Recommended optional columns:
- `affordability_status`
- `floor_eligible`
- `risk_level`
- segment, product, channel, income_source, expected PD, profit estimate

## Execution Steps

1. **Normalize score direction**
   - Confirm whether higher score means safer.
   - The current script treats higher `risk_score` as safer after normalization to `0-1` when needed.
   - If the score direction differs, transform it before running the module.

2. **Create risk and DTI buckets**
   - Risk levels: `very_low_risk`, `low_risk`, `medium_risk`, `high_risk`.
   - DTI bins: `dti_low`, `dti_medium`, `dti_high`, `dti_very_high`.
   - Avoid catch-all defaults for important production segments.

3. **Apply coefficient matrix**
   - `adjusted_limit = base_limit × risk_coefficient`.
   - Safer segments may receive higher multipliers only if affordability is still respected.
   - Higher DTI should generally reduce the coefficient within the same risk level.

4. **Apply floor and cap**
   - `final_limit = min(max(adjusted_limit, floor), cap)`.
   - If `affordability_status = not_affordable` or `base_limit <= 0`, final limit must be `0`.
   - If `floor_eligible = False`, do not apply the floor.

5. **Validate ranking**
   - Average final limit must be monotonic: safer risk levels should not receive lower average limits than worse levels, unless explicitly explained by affordability mix.
   - Risk-score / final-limit correlation should be positive under the current score direction.
   - A failed ranking validation is a blocker, not a warning.

6. **Prepare final policy table**
   - For each segment, document risk level, DTI bin, coefficient, floor, cap, exclusion, and monitoring metric.

## Runnable Command

```bash
python scripts/analysis_pipeline.py --input-path <risk-adjustment-data.csv> --mode risk_adjustment --output-dir analysis_output
```

Expected outputs:
- `risk_adjustment_results.csv`
- `run_summary.json`
- `analysis_report.md`

## Output Fields to Use

- `risk_level`
- `dti_bin`
- `risk_coefficient`
- `adjusted_limit`
- `floor_limit`
- `cap_limit`
- `final_limit`
- `affordability_status`
- `floor_eligible`
- `applied_constraint`

## Acceptance Criteria

The risk-adjusted limit policy is usable only if:
- score direction and scale are known;
- all material segments have explicit coefficients;
- `affordability_block` accounts receive no positive final limit;
- floor and cap hit rates are reviewed;
- ranking validation passes or the policy is marked `blocked`;
- final recommendation includes floor, cap, and operational guardrails.

## Red Flags

- high-risk customers receive higher average limits than safer customers;
- floors erase affordability or risk differentiation;
- score values mix `0-1` and `0-100` without normalization;
- missing segments fall through to default coefficient `1.0`;
- product cap is treated as a risk-control substitute.
