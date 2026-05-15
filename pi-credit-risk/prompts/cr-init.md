---
name: cr-init
description: Initialize a credit-risk analysis run. Creates runs/<run_id>/, generates run_config.json from arguments, validates inputs, and writes the initial manifest.json with status=INPUT_VALIDATED.
arguments:
  - name: run_id
    description: Unique identifier (alnum / _-., 1..64 chars).
    required: true
  - name: input_csv
    description: Path to the sample CSV. Will be read-only.
    required: true
  - name: target
    description: Binary target column. Rows with NULL target are treated as historical rejections.
    required: true
  - name: field_meta_csv
    description: Optional path to field metadata CSV.
    required: false
  - name: id_col
    description: Optional unique-id column.
    required: false
  - name: time_col
    description: Optional time / month column for time-based OOT.
    required: false
---

# /cr-init — initialize a credit-risk run

You are the pi-credit-risk orchestration agent. The user has invoked
`/cr-init` to start a new run. Perform the following deterministic steps; do
not improvise.

1. **Compose `run_config.json`** by merging user arguments into
   `skills/sklearn-pandas-credit-risk/templates/run_config.template.json`.
   - Set `run_id`, `input_csv`, `target`, and any provided optional fields.
   - Set `output_dir` to `runs/<run_id>`.
   - Leave defaults for tunables unless the user specified otherwise.

2. **Create the run directory** `runs/<run_id>/` (the workflow extension's
   protected-paths guard allows only writes under `runs/<run_id>/`).

3. **Write `run_config.json`** into `runs/<run_id>/run_config.json`.

4. **Validate the config**:
   ```bash
   python3 scripts/validate_inputs.py --config runs/<run_id>/run_config.json
   ```
   If this fails, surface the error to the user, set manifest status to
   `FAILED`, and stop.

5. **Initialize `manifest.json`** by writing:
   ```json
   {
     "run_id": "<run_id>",
     "status": "INPUT_VALIDATED",
     "completed_stages": [],
     "artifacts": {},
     "stage_history": [],
     "updated_at": "<now>"
   }
   ```

6. **Report back** to the user with:
   - run directory path
   - the resolved config (with defaults filled in)
   - the next recommended command, e.g. `/cr-run <run_id> 0-4`.

**Do not** start any stage from this command — `cr-run` is the only command
that calls the pipeline.
