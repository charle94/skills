# Confidence levels and traceability

Every rule, variable, and strategy must end up in `confidence_evidence.csv`
with a confidence tag. The pipeline assigns the tag via
`scripts/lib/simulation.py::assign_confidence`; the agent may downgrade
(never upgrade) with a written reason in `decision_log.csv`.

## Confidence definitions

| Tag | When |
|---|---|
| `HIGH` | Sample share sufficient; bad count sufficient; train/test/OOT bad rate direction consistent; PSI acceptable; business interpretation clear; no leakage. |
| `MEDIUM` | Effect is clear but sample size is small, cross-period direction wobbles, or business interpretation needs human review. Suggest *review* / *observe* / small grey release. |
| `LOW` | Sample insufficient, cross-period unstable, weak interpretation, suspected leakage, or only one-period effective. **Not** suitable for go-live as a hard reject rule. |

Decision rule (in `assign_confidence`):

```
lift_gap = |train_lift - oot_lift| / max(|train_lift|, EPSILON)
pass_bad_gap = |train_pass_bad_rate - oot_pass_bad_rate|

HIGH   ⇐ lift_gap ≤ 0.20 AND pass_bad_gap ≤ 0.02 AND (psi is None OR psi ≤ 0.10)
MEDIUM ⇐ lift_gap ≤ 0.50 AND (psi is None OR psi ≤ 0.25)
LOW    ⇐ otherwise
```

## Required columns of `confidence_evidence.csv`

```
evidence_id, object_type, object_id, metric_name,
train_value, test_value, oot_value,
threshold, pass_flag, confidence, reason, source_file
```

**Hard rule:** all three of `train_value`, `test_value`, `oot_value` must be
non-null. If any sample set is missing, compute it (or explicitly mark the
sample-set unavailable in `sample_split_log.csv`) before building evidence.
`scripts/lib/reporting.py::build_confidence_evidence` raises ValueError if any
of the three is None — `validate_outputs.py` re-checks the CSV at stage 7.

## Required columns of `decision_log.csv`

```
timestamp, stage, object_id, decision, reason, input_files, output_files, operator_note
```

Every stage appends at least one row. The agent appends one extra row per
significant decision (e.g. "downgrade rule DT_R00012 from HIGH to MEDIUM
because OOT lift dropped 35%").

## Traceability identifiers

| Object | ID pattern | Origin |
|---|---|---|
| Feature | column name | input CSV |
| Bin | `<feature>::<bin_label>` (logical), `bin_id` (assigned in `bin_detail.csv`) | stage 2 |
| Tree rule | `DT_R<5-digit>` | stage 5 |
| Single-variable rule | `SV_R<5-digit>` | stage 5.1 |
| Combo rule | `COMBO_<5-digit>` | stage 5.2 |
| Strategy | `S<3-digit>` or `OPT` | stage 6 |
| Evidence | `EV_<8-char>` | stage 7 |
