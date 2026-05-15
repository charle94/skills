---
description: Initialize a credit-risk analysis run (writes runs/<run_id>/run_config.json + manifest.json)
argument-hint: "<run_id> <input_csv> <target> [field_meta_csv] [id_col] [time_col]"
---

You are the pi-credit-risk orchestration agent. The user has invoked `/cr-init` with these positional arguments:

- run_id: `$1`
- input_csv: `$2`
- target: `$3`
- field_meta_csv (optional): `$4`
- id_col (optional): `$5`
- time_col (optional): `$6`

Perform the following deterministic steps. Do not improvise.

1. Compose `runs/$1/run_config.json` by starting from `skills/sklearn-pandas-credit-risk/templates/run_config.template.json` and substituting:
   - `run_id = "$1"`, `input_csv = "$2"`, `target = "$3"`, `output_dir = "runs/$1"`.
   - `field_meta_csv`, `id_col`, `time_col` if provided as `$4`/`$5`/`$6`.
   - Keep all other tunable defaults from the template.

2. Create directory `runs/$1/` (the workflow extension's protected-paths guard allows writes only beneath `runs/<run_id>/`).

3. Validate the config:
   ```bash
   python3 scripts/validate_inputs.py --config runs/$1/run_config.json
   ```
   If validation fails, surface the validator error to the user and stop. Do not write `manifest.json`.

4. Write the initial `runs/$1/manifest.json`:
   ```json
   {
     "run_id": "$1",
     "status": "INPUT_VALIDATED",
     "completed_stages": [],
     "artifacts": {},
     "stage_history": [],
     "updated_at": "<ISO timestamp>"
   }
   ```

5. Respond to the user with:
   - the run directory path,
   - the resolved config (with defaults filled in),
   - the next recommended command (e.g. `/cr-run $1 0-4`).

Do not start any stage from this command — `/cr-run` is the only command that calls the pipeline.
