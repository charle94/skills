# pi-credit-risk

A reproducible **pi-agent package** for credit-risk third-party data evaluation, rule mining, and rule simulation, built around `pandas` + `scikit-learn` (no `toad` dependency).

This package is the productionized, deterministic, stage-by-stage version of the original `sklearn-risk-analysis` skill (preserved in the repository root). The agent **does not invent core algorithms**; it orchestrates a fixed Python pipeline whose artifact list and contracts are enforced by a workflow extension.

## Architecture (4 layers)

```
┌────────────────────────────────────────────────────────────────┐
│ Skill (规范层)        skills/sklearn-pandas-credit-risk/       │
│   What stages exist, what inputs/outputs are required,         │
│   audit & confidence rules, prohibitions.                      │
├────────────────────────────────────────────────────────────────┤
│ Prompt Templates      prompts/cr-{init,run,review,report}.md   │
│   Standard agent entry points so each run follows the same     │
│   path regardless of user phrasing.                            │
├────────────────────────────────────────────────────────────────┤
│ Extension             extensions/credit-risk-workflow.ts       │
│   • Run-state machine (INIT → STAGE_k_DONE → REVIEW → EXPORT). │
│   • Bash whitelist (only `python3 scripts/...` + read checks). │
│   • Protected paths (input data read-only, writes restricted   │
│     to runs/<run_id>/).                                        │
│   • Per-stage artifact completeness gate (won't allow stage    │
│     k+1 until k's required artifacts exist and hash into       │
│     manifest.json).                                            │
│   • Context injection: current run_id, stage, missing files.   │
├────────────────────────────────────────────────────────────────┤
│ Python scripts (确定性执行层) scripts/                          │
│   scripts/run_pipeline.py    — single CLI entry                │
│   scripts/validate_inputs.py — config & data sanity            │
│   scripts/run_stage.py       — per-stage dispatcher            │
│   scripts/validate_outputs.py— artifact completeness + SHA256  │
│   scripts/render_report.py   — strategy_summary.md from CSVs   │
│   scripts/lib/               — deterministic algorithms        │
│     (samples, binning, woe, psi, metrics, tree_rules,          │
│      single_rules, combo_rules, simulation, waterfall,         │
│      reporting, pipeline)                                      │
└────────────────────────────────────────────────────────────────┘
```

## Reproducibility guarantees

1. **Pinned dependencies** — `requirements.txt` pins exact versions of `pandas`, `numpy`, `scipy`, `scikit-learn`.
2. **Captured environment** — every run writes `environment.json` (python version, library versions, OS).
3. **Single random_state** — `run_config.random_state` (default `42`) is threaded into `split_samples` and `fit_rule_tree`.
4. **Deterministic outputs** — DataFrames are sorted by stable keys before CSV write; JSON is dumped `sort_keys=True`.
5. **Artifact manifest with SHA-256** — `manifest.json` records the hash of every artifact; `make reproducibility` runs the pipeline twice and asserts identical hashes.
6. **Schema-validated config** — `schema/run_config.schema.json` rejects malformed configs at start.

## Quickstart

```bash
# Install pinned deps
make install

# Run the bundled example pipeline end-to-end
make example RUN_ID=example_run

# Verify reproducibility (runs twice, diffs SHA-256 hashes)
make reproducibility

# Run tests
make test
```

After a successful run, see `runs/<run_id>/`:

```
runs/<run_id>/
├── run_config.json          # frozen copy of inputs
├── environment.json         # captured environment
├── manifest.json            # state machine + artifact SHA-256
├── decision_log.csv         # all stage decisions
├── confidence_evidence.csv  # train/test/oot evidence
├── strategy_summary.md      # final report
└── ... (per-stage CSVs/JSONs — see skills/sklearn-pandas-credit-risk/references/outputs.md)
```

## Pi-agent workflow

```text
/cr-init <run_id> <input.csv> <field_meta.csv>   # initialize run_config.json + runs/<run_id>/
/cr-run  <run_id> 0-4                            # stages 0..4 (data, audit, quality, binning, PSI, KS/AUC)
/cr-run  <run_id> 5                              # rule mining (tree + single-var + combo)
/cr-run  <run_id> 6                              # simulation (observable + full population)
/cr-run  <run_id> 7-8                            # summary + monitoring plan
/cr-review <run_id>                              # manifest completeness audit
/cr-report <run_id>                              # render strategy_summary.md
```

The workflow extension enforces stage order, blocks unsafe bash, and rejects writes outside `runs/<run_id>/`. If any required artifact is missing for stage *k*, stage *k+1* is rejected.

## Layout

```
pi-credit-risk/
├── package.json
├── requirements.txt
├── Makefile
├── AGENTS.md
├── README.md
├── skills/sklearn-pandas-credit-risk/
│   ├── SKILL.md
│   ├── references/{stages,inputs,outputs,confidence,prohibitions}.md
│   └── templates/{run_config.template.json, strategy_summary.template.md}
├── prompts/{cr-init,cr-run,cr-review,cr-report}.md
├── extensions/credit-risk-workflow.ts
├── schema/{run_config.schema.json, artifact_manifest.schema.json}
├── scripts/
│   ├── run_pipeline.py
│   ├── validate_inputs.py
│   ├── run_stage.py
│   ├── validate_outputs.py
│   ├── render_report.py
│   └── lib/  (Python package: see scripts/lib/README.md)
├── examples/{run_config.example.json, field_meta.example.csv, sample_input.csv}
└── tests/
```

## Relationship to the original `sklearn-risk-analysis` skill

This package is the **stable, reproducible incarnation** of `sklearn-risk-analysis` (kept at the repo root). The original is preserved as the methodology reference. The Python code blocks embedded there are now organized into `scripts/lib/` modules with the same function signatures and semantics, plus deterministic-output guarantees and stage-completeness enforcement.
