# Portfolio Monitoring

## Purpose

Use this module to detect early warning signals in a live credit portfolio. It answers:

- Has the score distribution of new applicants or bookings shifted compared to the base period?
- Have key input characteristics (income, DTI, bureau score) drifted?
- Are bad rate, approval rate, or utilization moving outside expected bounds?

Early detection allows strategy adjustment before losses accumulate.

## Trigger Conditions

Use portfolio monitoring when:
- running regular (weekly or monthly) health checks on a live strategy;
- a data pipeline or scoring model change may have affected input quality;
- macroeconomic conditions, channel mix, or acquisition source has changed;
- bad rate or utilization shows unexpected movement in recent vintages.

## Required Inputs

For PSI/CSI comparison, two data files are needed:
1. **Base period file** (`--base-period-path`): reference population (e.g., last stable 3 months).
2. **Current period file** (`--input-path`): the population to monitor.

Minimum columns in current period data:
- `customer_id`
- `score`: model output score (for PSI)
- `period`: time label (e.g., `2024-06`) for KPI trend computation

Recommended optional columns:
- `bad_flag`: for bad rate trending
- `approved`: for approval rate trending
- `utilization_rate`: for utilization trending
- `final_limit` or `current_limit`: for average limit trending
- Feature columns for CSI (e.g., `monthly_income`, `dti`, `risk_score`)

## Execution Steps

1. **Compute Score PSI**
   - Divide the base score distribution into `psi_bins` equal-frequency bins.
   - Map the current distribution to the same bins.
   - PSI = Σ (current% − base%) × ln(current% / base%).
   - Classify: stable (<0.10), moderate shift (0.10–0.25), significant shift (>0.25).

2. **Compute Characteristic CSI**
   - Apply the same PSI formula to each input feature in `feature_cols`.
   - Flag features with significant shift for root-cause investigation.

3. **Compute KPI Trends**
   - Aggregate bad rate, approval rate, utilization, and average limit by `period`.
   - Use the first `baseline_periods` periods as the baseline.
   - Alert when:
     - bad rate increases >20% relative or >2pp absolute vs baseline;
     - approval rate drops >10% relative;
     - utilization increases >10pp absolute.

4. **Generate Alerts**
   - High severity: >40% relative change on any KPI.
   - Medium severity: trigger threshold crossed but <40% change.

## Runnable Command

```bash
python3 scripts/analysis_pipeline.py \
  --input-path <current-data.csv> \
  --base-period-path <base-data.csv> \
  --mode portfolio_monitoring \
  --output-dir analysis_output
```

Expected outputs:
- `psi_detail.csv`
- `csi_results.csv`
- `kpi_trends.csv`
- `run_summary.json`
- `analysis_report.md`

## PSI Interpretation

| PSI Value | Label | Recommended Action |
|-----------|-------|-------------------|
| < 0.10 | stable | No action needed |
| 0.10 – 0.25 | moderate_shift | Investigate root cause; monitor more frequently |
| > 0.25 | significant_shift | **Escalate immediately**; suspend auto-decisions pending model review |

## Acceptance Criteria

The monitoring result is actionable only if:
- base period has at least 30 days of data and is confirmed representative;
- score column is the same model version in both base and current data;
- KPI period labels are consistent and contiguous;
- PSI bins are derived from the base period and applied consistently to current.

## Red Flags

- using model version A for base and model version B for current period PSI;
- comparing populations with different product mixes in the base vs current file;
- treating a single-period PSI spike as definitive without checking data quality;
- ignoring CSI even when PSI is stable (input drift may not yet appear in output score);
- triggering alerts based on KPI movement without checking whether a strategy change intentionally caused it.
