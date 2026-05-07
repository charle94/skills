# Vintage Analysis

## Purpose

Use this module to track how cohorts of loans (grouped by booking month) perform over time. A **vintage** is the set of all loans booked in the same calendar period (month or quarter). Vintage analysis answers:

- Are newer cohorts defaulting faster or slower than older cohorts at the same months-on-book (MOB)?
- Which origination periods produced systematically worse credit quality?
- What is the projected final bad rate for immature cohorts that have not yet seasoned fully?

## Trigger Conditions

Use vintage analysis when:
- a new product or channel has been live for at least 3 months and early DPD data is available;
- strategy changes or economic shocks may have altered credit quality across cohorts;
- forecasting reserve requirements or expected loss for immature books;
- comparing performance before and after a policy change (pre/post cohorts).

## Required Inputs

Minimum runnable columns:
- `customer_id`
- `origination_month`: booking cohort label (YYYY-MM format, e.g. `2024-03`)
- `mob`: months on book at this observation snapshot (integer, e.g. 1, 3, 6, 12)
- `dpd`: days past due at this observation (integer, used to derive bad flag)

Recommended optional columns:
- `bad_flag`: pre-computed 0/1 indicator (overrides DPD threshold derivation if present)
- `loan_amount`: original booking amount (enables amount-weighted vintage curves)
- `risk_level`, `channel`, `product`: for cohort sub-segmentation

## Execution Steps

1. **Derive ever-bad flag**
   - `bad_flag = 1` if `dpd >= dpd_threshold` at this observation.
   - The threshold is `30` by default (can be overridden via `--config-path`).

2. **Build vintage matrix**
   - Aggregate by `(origination_month, mob)` → bad rate, customer count, total amount.
   - Exclude cohorts with fewer than `min_cohort_observations` accounts.

3. **Compute reference curve**
   - Use the first `reference_cohort_count` cohorts as the maturity benchmark.
   - Compute mean and standard deviation of bad rates at each MOB.

4. **Detect deteriorating cohorts**
   - Compute z-score: `(cohort_bad_rate - reference_mean) / reference_std` at each MOB.
   - Flag any cohort where z-score > `deterioration_z_threshold` at one or more MOB points.

5. **Project final bad rate**
   - For immature cohorts, compute the seasoning factor:
     `factor = reference_rate_at_target_MOB / reference_rate_at_latest_available_MOB`.
   - Apply the factor: `projected_bad_rate = latest_bad_rate × factor`.
   - Confidence is `high` (≥6 MOB observations), `medium` (3–5), or `low` (<3).

## Runnable Command

```bash
python3 scripts/analysis_pipeline.py --input-path examples/vintage_analysis_sample.csv --mode vintage_analysis --output-dir analysis_output
```

Expected outputs:
- `vintage_bad_rate_matrix.csv`
- `vintage_z_score_matrix.csv`
- `vintage_projection.csv`
- `vintage_count_matrix.csv`
- `run_summary.json`
- `analysis_report.md`

## Output Fields

### vintage_bad_rate_matrix.csv
Pivot table: rows = origination cohorts, columns = MOB values, values = cumulative bad rate.

### vintage_z_score_matrix.csv
Same structure, values are z-scores vs reference cohorts. Includes `is_deteriorating` and `max_z_score` columns.

### vintage_projection.csv
One row per cohort:
- `origination_month`
- `latest_mob`: most recent MOB with data
- `latest_bad_rate`
- `projection_factor`: seasoning multiplier
- `projected_bad_rate_at_mob`: projected mature bad rate
- `confidence`: `high`, `medium`, `low`, `actual`, or `insufficient_reference`

## Acceptance Criteria

The vintage analysis is actionable only if:
- at least 3 cohorts with sufficient observations exist for reference curve construction;
- MOB range spans at least 3 time points;
- deteriorating cohorts have an identifiable root cause (policy change, channel shift, macro event) before strategy action is taken;
- projections are treated as estimates, not commitments, especially at `low` confidence.

## Red Flags

- using a single cohort as the reference benchmark;
- treating z-score deterioration as a policy trigger without checking whether scoring or population mix changed;
- projecting final rates from cohorts observed at only MOB 1 or 2;
- mixing product types, channels, or tenors in a single vintage curve without segmentation;
- ignoring the count matrix — a cohort with 5 accounts can show any bad rate.
