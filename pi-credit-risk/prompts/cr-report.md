---
name: cr-report
description: Render the final strategy_summary.md and management-level conclusions. Reads artifacts from runs/<run_id>/.
arguments:
  - name: run_id
    description: Run identifier (must be at REVIEW_READY or later).
    required: true
---

# /cr-report — final report

You are the pi-credit-risk orchestration agent. The user has invoked
`/cr-report <run_id>` to produce the final review materials.

## Step 1 — Verify readiness

```bash
python3 -c "import json; m=json.load(open('runs/<run_id>/manifest.json')); print(m['status'])"
```

Refuse unless `status ∈ {STAGE_7_DONE, STAGE_8_DONE, REVIEW_READY, EXPORTED}`.

## Step 2 — Render the template

```bash
python3 scripts/render_report.py --run-dir runs/<run_id>
```

This writes `runs/<run_id>/strategy_summary.md` using the artifacts.

## Step 3 — Fill the narrative sections

The agent now fills these sections of `strategy_summary.md` (and **only**
these), citing `rule_id` / `evidence_id` from the CSVs:

- §10 Go-live recommendation — `go_live | grey_release | observe | reject`.
- §12 Risk notes — sample bias, ambiguous variables, cross-period drift,
  segment differences, compliance.

Do not edit numeric tables; they come from the CSVs and must remain
faithful to them.

## Step 4 — Update manifest

After the report is finalized, update `runs/<run_id>/manifest.json` to set
`status = EXPORTED` and refresh the SHA-256 of `strategy_summary.md`.

## Step 5 — Hand-off

Report back to the user:
- Path: `runs/<run_id>/strategy_summary.md`
- Headline: recommendation + confidence
- Required follow-ups (e.g. data refresh date, monitoring start date).
