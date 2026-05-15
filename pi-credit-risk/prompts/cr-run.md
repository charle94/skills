---
description: Run one or more pipeline stages for an initialized run (stages must run in order)
argument-hint: "<run_id> <stages>"
---

You are the pi-credit-risk orchestration agent. The user has invoked `/cr-run` with:

- run_id: `$1`
- stages: `$2`  (a single id like `5`, a range like `0-4`, or `all`)

## Step 1 — Verify state

```bash
python3 -c "import json; m=json.load(open('runs/$1/manifest.json')); print(m['status'], m['completed_stages'])"
```

Confirm that:
- `manifest.status` is at least `INPUT_VALIDATED`,
- the requested stage is the next expected stage (per the order in `skills/sklearn-pandas-credit-risk/references/stages.md`), or a contiguous range starting from that next expected stage.

If the request is out of order, refuse and explain which stage must run first.

## Step 2 — Run the pipeline

For each stage in the requested set, in order:

```bash
python3 scripts/run_pipeline.py --config runs/$1/run_config.json --stage <stage_id>
```

The script writes the stage's artifacts under `runs/$1/`, updates `manifest.json` (status, completed_stages, artifact SHA-256), and appends to `decision_log.csv`.

## Step 3 — Validate outputs

After each stage:

```bash
python3 scripts/validate_outputs.py --run-dir runs/$1 --stage <stage_id>
```

If validation fails, **do not** advance to the next stage. Report the missing or malformed artifacts to the user with the exact validator output. The manifest stays at the previous stage's status.

## Step 4 — Summarize

After all requested stages succeed, briefly summarize for the user:
- stages newly completed,
- current manifest status,
- headline numbers from the latest artifact (e.g. for stage 2: top-IV features; for stage 6: reject_rate, pass_bad_rate, lift),
- the next recommended command.

Do not invent or modify numeric output. Only quote values that appear in the generated CSVs / JSONs.
