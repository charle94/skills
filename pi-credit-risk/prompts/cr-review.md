---
description: Audit a run for completeness (reads manifest.json + runs validate_outputs.py per stage)
argument-hint: "<run_id>"
---

You are the pi-credit-risk orchestration agent. The user has invoked `/cr-review $1` to audit the run.

## Step 1 — Load the manifest

```bash
cat runs/$1/manifest.json
```

## Step 2 — Validate each completed stage

For each stage in `manifest.completed_stages`:

```bash
python3 scripts/validate_outputs.py --run-dir runs/$1 --stage <stage_id>
```

Collect the JSON output of each validator call.

## Step 3 — Cross-stage checks

Beyond per-stage required-file presence, verify:

1. `confidence_evidence.csv` exists (if stage 7 is completed) and every row has non-null `train_value`, `test_value`, `oot_value`.
2. `rule_simulation.csv` and `rule_simulation_full.csv` are both present (if stage 6 is completed).
3. `decision_tree.dot` (and ideally `decision_tree.png`) plus `decision_tree_rules.csv` are both present (if stage 5 is completed).
4. `waterfall_simulation.csv`, `waterfall_comparison.csv`, `waterfall_simulation_full.csv` are all present (if stage 6.1 is completed).
5. Artifact SHA-256 in `manifest.json` matches the files on disk (re-hash and compare).

## Step 4 — Report

Produce a structured response:

```
Run: $1
Status: <manifest.status>
Completed stages: [...]
Missing artifacts: [...]            # empty list ⇒ complete
Stale hashes: [...]                  # files whose hash no longer matches manifest
Cross-stage issues: [...]
Recommendation: <next action>
```

Do not modify any files during review. If issues exist, point the user to `/cr-run $1 <stage>` to regenerate the missing artifacts (the pipeline is idempotent: re-running a completed stage overwrites its outputs and re-hashes them).
