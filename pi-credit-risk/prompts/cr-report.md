---
description: Render the final strategy_summary.md and management-level conclusions for a run
argument-hint: "<run_id>"
---

You are the pi-credit-risk orchestration agent. The user has invoked `/cr-report $1` to produce final review materials.

## Step 1 — Verify readiness

```bash
python3 -c "import json; print(json.load(open('runs/$1/manifest.json'))['status'])"
```

Refuse unless `status ∈ {STAGE_7_DONE, STAGE_8_DONE, REVIEW_READY, EXPORTED}`.

## Step 2 — Render the template

```bash
python3 scripts/render_report.py --run-dir runs/$1
```

This writes `runs/$1/strategy_summary.md` using the artifacts.

## Step 3 — Fill the narrative sections

The agent now fills these sections of `strategy_summary.md` (and only these), citing `rule_id` / `evidence_id` from the CSVs:

- §10 Go-live recommendation — `go_live | grey_release | observe | reject`.
- §12 Risk notes — sample bias, ambiguous variables, cross-period drift, segment differences, compliance.

Do not edit numeric tables; they come from the CSVs and must remain faithful to them.

## Step 4 — Update manifest

After the report is finalized, update `runs/$1/manifest.json` to set `status = EXPORTED` and refresh the SHA-256 of `strategy_summary.md`.

## Step 5 — Hand-off

Report back to the user:
- Path: `runs/$1/strategy_summary.md`
- Headline: recommendation + confidence
- Required follow-ups (e.g. data refresh date, monitoring start date).
