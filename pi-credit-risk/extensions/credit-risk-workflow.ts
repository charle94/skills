/**
 * pi-credit-risk workflow extension
 * -------------------------------------------------------------------------
 * Enforces stable, reproducible execution of the credit-risk pipeline by:
 *   1. Maintaining a per-run state machine persisted in
 *      runs/<run_id>/manifest.json.
 *   2. Whitelisting bash commands to a safe subset.
 *   3. Restricting file writes to runs/<run_id>/.
 *   4. Auto-refreshing manifest.json after a successful run_pipeline.py
 *      invocation (recomputing artifact SHA-256 + advancing manifest.status).
 *   5. Injecting run context (current stage, missing artifacts) into the
 *      system prompt at every turn via before_agent_start.
 *
 * Authoritative API reference:
 *   https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md
 */

import * as fs from "node:fs";
import * as path from "node:path";
import * as crypto from "node:crypto";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/**
 * Ordered list of stage ids. cr-run is only allowed to invoke a contiguous
 * range starting from the next expected stage.
 */
const STAGE_ORDER: ReadonlyArray<string> = [
	"0",
	"0.5",
	"1",
	"2",
	"3",
	"4",
	"5",
	"5.1",
	"5.2",
	"6",
	"6.1",
	"7",
	"8",
];

const STAGE_STATUS: Readonly<Record<string, string>> = {
	"0": "STAGE_0_DONE",
	"0.5": "STAGE_0_5_DONE",
	"1": "STAGE_1_DONE",
	"2": "STAGE_2_DONE",
	"3": "STAGE_3_DONE",
	"4": "STAGE_4_DONE",
	"5": "STAGE_5_DONE",
	"5.1": "STAGE_5_1_DONE",
	"5.2": "STAGE_5_2_DONE",
	"6": "STAGE_6_DONE",
	"6.1": "STAGE_6_1_DONE",
	"7": "STAGE_7_DONE",
	"8": "STAGE_8_DONE",
};

/**
 * Required artifacts per stage. Mirrors
 * skills/sklearn-pandas-credit-risk/references/outputs.md and
 * scripts/validate_outputs.py — duplicated here so the extension can do a
 * fast, local pre-flight check before Python is invoked, and so the
 * before_agent_start context message can list missing files.
 */
const REQUIRED_ARTIFACTS: Readonly<Record<string, ReadonlyArray<string>>> = {
	"0": [
		"run_config.json",
		"environment.json",
		"sample_profile.csv",
		"sample_split_log.csv",
		"decision_log.csv",
	],
	"0.5": ["field_audit.csv", "leakage_audit.csv"],
	"1": ["data_quality.csv", "outlier_summary.csv", "feature_drop_reason.csv"],
	"2": [
		"bin_rules.json",
		"bin_detail.csv",
		"woe_rules.json",
		"monotonicity_check.csv",
		"bin_merge_log.csv",
	],
	"3": ["psi_table.csv", "bin_psi_detail.csv"],
	"4": ["feature_quality.csv", "feature_correlation.csv"],
	"5": ["decision_tree.dot", "decision_tree_rules.csv", "rule_overlap_matrix.csv"],
	"5.1": ["single_rule_candidates.csv", "single_var_rule_eval.csv"],
	"5.2": ["rule_combination_candidates.csv"],
	"6": [
		"strategy_rules.csv",
		"rule_simulation.csv",
		"rule_simulation_full.csv",
		"strategy_comparison.csv",
		"strategy_level_simulation.csv",
		"monthly_rule_simulation.csv",
		"segment_rule_simulation.csv",
	],
	"6.1": [
		"waterfall_simulation.csv",
		"waterfall_comparison.csv",
		"waterfall_simulation_full.csv",
	],
	"7": ["confidence_evidence.csv"],
	"8": ["monitoring_plan.csv", "strategy_summary.md"],
};

/**
 * Bash whitelist. The agent may only invoke commands whose trimmed text
 * matches one of these patterns.
 */
const BASH_WHITELIST: ReadonlyArray<RegExp> = [
	/^python3?\s+scripts\/(run_pipeline|validate_inputs|validate_outputs|run_stage|render_report)\.py(\s|$)/,
	/^python3?\s+-m\s+pytest(\s|$)/,
	/^python3?\s+-c\s/,
	/^pip3?\s+install\s+-r\s+requirements\.txt(\s|$)/,
	/^(ls|cat|head|tail|wc|file|stat)(\s|$)/,
	/^git\s+(status|log|diff|show)(\s|$)/,
];

/**
 * Path-write whitelist. Writes (write/edit/create tools) are allowed only
 * beneath runs/<run_id>/ (any run_id).
 */
const WRITE_WHITELIST_RE = /^runs[/\\][A-Za-z0-9][A-Za-z0-9_.\-/\\]*$/;

// ---------------------------------------------------------------------------
// Manifest helpers
// ---------------------------------------------------------------------------

interface Manifest {
	run_id: string;
	status: string;
	completed_stages: string[];
	artifacts: Record<string, string>;
	stage_history?: Array<Record<string, unknown>>;
	last_error?: string | null;
	updated_at: string;
}

function runsDir(cwd: string): string {
	return path.join(cwd, "runs");
}

function manifestPath(cwd: string, runId: string): string {
	return path.join(runsDir(cwd), runId, "manifest.json");
}

function readManifest(cwd: string, runId: string): Manifest | null {
	const p = manifestPath(cwd, runId);
	if (!fs.existsSync(p)) return null;
	try {
		return JSON.parse(fs.readFileSync(p, "utf-8")) as Manifest;
	} catch {
		return null;
	}
}

function writeManifest(cwd: string, runId: string, m: Manifest): void {
	m.updated_at = new Date().toISOString();
	fs.writeFileSync(manifestPath(cwd, runId), JSON.stringify(m, null, 2));
}

function sha256(filePath: string): string {
	const buf = fs.readFileSync(filePath);
	return `sha256:${crypto.createHash("sha256").update(buf).digest("hex")}`;
}

function nextExpectedStage(m: Manifest): string | null {
	for (const s of STAGE_ORDER) {
		if (!m.completed_stages.includes(s)) return s;
	}
	return null;
}

function missingArtifacts(cwd: string, runId: string, stage: string): string[] {
	const required = REQUIRED_ARTIFACTS[stage] ?? [];
	const runDir = path.join(runsDir(cwd), runId);
	return required.filter((rel) => !fs.existsSync(path.join(runDir, rel)));
}

/**
 * Parse `--config <path> --stage <id>` (any order) out of a python command.
 * Returns { config, stage } or null if either flag is missing.
 */
function parsePipelineFlags(
	cmd: string,
): { config: string; stage: string } | null {
	const cfg = cmd.match(/--config\s+(\S+)/);
	const stg = cmd.match(/--stage\s+(\S+)/);
	if (!cfg || !stg) return null;
	return { config: cfg[1], stage: stg[1] };
}

// ---------------------------------------------------------------------------
// Extension factory
// ---------------------------------------------------------------------------

export default function pi_credit_risk(pi: ExtensionAPI) {
	// =========================================================================
	// Guard #1 — bash whitelist
	// =========================================================================
	pi.on("tool_call", async (event, ctx) => {
		if (!isToolCallEventType("bash", event)) return undefined;
		const cmd = String(event.input.command ?? "").trim();
		if (!cmd) return undefined;
		const allowed = BASH_WHITELIST.some((re) => re.test(cmd));
		if (!allowed) {
			if (ctx.hasUI) {
				ctx.ui.notify(`pi-credit-risk: refused bash command`, "warning");
			}
			return {
				block: true,
				reason:
					`[pi-credit-risk] bash command refused by extension whitelist.\n` +
					`Got: ${cmd}\n` +
					`Allowed patterns:\n` +
					`  - python3 scripts/{run_pipeline,validate_inputs,validate_outputs,run_stage,render_report}.py\n` +
					`  - python3 -m pytest …\n` +
					`  - python3 -c "…"\n` +
					`  - pip install -r requirements.txt\n` +
					`  - ls/cat/head/tail/wc/file/stat …\n` +
					`  - git status/log/diff/show …`,
			};
		}
		return undefined;
	});

	// =========================================================================
	// Guard #2 — protected paths (writes only beneath runs/<run_id>/)
	// =========================================================================
	pi.on("tool_call", async (event, ctx) => {
		if (
			event.toolName !== "write" &&
			event.toolName !== "edit" &&
			event.toolName !== "create"
		) {
			return undefined;
		}
		const target = String((event.input as { path?: string }).path ?? "");
		if (!target) return undefined;
		const rel = path.relative(ctx.cwd, path.resolve(ctx.cwd, target));
		const inRunsDir = WRITE_WHITELIST_RE.test(rel);
		if (!inRunsDir) {
			if (ctx.hasUI) {
				ctx.ui.notify(`pi-credit-risk: blocked write to ${rel}`, "warning");
			}
			return {
				block: true,
				reason:
					`[pi-credit-risk] file write refused: ${rel}. ` +
					`Writes are allowed only beneath runs/<run_id>/. ` +
					`If you need to modify package source, edit it outside the agent and reinstall.`,
			};
		}
		return undefined;
	});

	// =========================================================================
	// Guard #3 — pipeline stage order
	// =========================================================================
	pi.on("tool_call", async (event, _ctx) => {
		if (!isToolCallEventType("bash", event)) return undefined;
		const cmd = String(event.input.command ?? "");
		if (!/scripts\/run_pipeline\.py/.test(cmd)) return undefined;
		const flags = parsePipelineFlags(cmd);
		if (!flags) return undefined;
		if (flags.stage === "all") return undefined; // pipeline self-orders
		let config: { run_id?: string } = {};
		try {
			config = JSON.parse(fs.readFileSync(flags.config, "utf-8"));
		} catch {
			return {
				block: true,
				reason: `[pi-credit-risk] cannot read config ${flags.config}`,
			};
		}
		if (!config.run_id) {
			return {
				block: true,
				reason: `[pi-credit-risk] config ${flags.config} is missing run_id.`,
			};
		}
		const m = readManifest(_ctx.cwd, config.run_id);
		if (!m) {
			return {
				block: true,
				reason: `[pi-credit-risk] manifest.json missing for run_id=${config.run_id}. Run /cr-init first.`,
			};
		}
		const expected = nextExpectedStage(m);
		if (expected !== null && flags.stage !== expected) {
			return {
				block: true,
				reason:
					`[pi-credit-risk] stage out of order. ` +
					`manifest says next expected = ${expected}, you requested = ${flags.stage}. ` +
					`Run the expected stage first.`,
			};
		}
		return undefined;
	});

	// =========================================================================
	// Hook — refresh manifest.json after a successful pipeline invocation
	// =========================================================================
	pi.on("tool_result", async (event, ctx) => {
		if (event.toolName !== "bash" || event.isError) return undefined;
		const cmd = String((event.input as { command?: string }).command ?? "");
		if (!/scripts\/run_pipeline\.py/.test(cmd)) return undefined;
		const flags = parsePipelineFlags(cmd);
		if (!flags) return undefined;
		let config: { run_id?: string } = {};
		try {
			config = JSON.parse(fs.readFileSync(flags.config, "utf-8"));
		} catch {
			return undefined;
		}
		if (!config.run_id) return undefined;
		const m = readManifest(ctx.cwd, config.run_id);
		if (!m) return undefined;

		const stagesToCheck = flags.stage === "all" ? STAGE_ORDER : [flags.stage];
		for (const s of stagesToCheck) {
			const missing = missingArtifacts(ctx.cwd, config.run_id, s);
			if (missing.length > 0) {
				m.last_error = `stage ${s} missing artifacts: ${missing.join(", ")}`;
				writeManifest(ctx.cwd, config.run_id, m);
				return undefined;
			}
			const runDir = path.join(runsDir(ctx.cwd), config.run_id);
			for (const rel of REQUIRED_ARTIFACTS[s] ?? []) {
				m.artifacts[rel] = sha256(path.join(runDir, rel));
			}
			if (!m.completed_stages.includes(s)) m.completed_stages.push(s);
			m.status = STAGE_STATUS[s] ?? m.status;
			m.last_error = null;
		}
		writeManifest(ctx.cwd, config.run_id, m);
		return undefined;
	});

	// =========================================================================
	// Context injection — prepend run state to the system prompt
	// =========================================================================
	pi.on("before_agent_start", async (event) => {
		const text = event.prompt ?? "";
		const m = text.match(/\/cr-(?:init|run|review|report|status)\s+(\S+)/);
		if (!m) return undefined;
		const runId = m[1];
		// ctx is not passed to before_agent_start in some versions; use cwd from
		// the systemPromptOptions if available, else process.cwd().
		const cwd = event.systemPromptOptions?.cwd ?? process.cwd();
		const manifest = readManifest(cwd, runId);
		if (!manifest) return undefined;
		const expected = nextExpectedStage(manifest);
		const lines: string[] = [
			`## pi-credit-risk run context`,
			``,
			`- run_id: \`${runId}\``,
			`- status: \`${manifest.status}\``,
			`- completed_stages: ${
				manifest.completed_stages.length > 0 ? manifest.completed_stages.join(", ") : "(none)"
			}`,
			`- next_expected_stage: ${expected ?? "(all done)"}`,
		];
		if (manifest.last_error) lines.push(`- last_error: ${manifest.last_error}`);
		if (expected) {
			const missing = missingArtifacts(cwd, runId, expected);
			if (missing.length > 0) {
				lines.push(`- missing_for_next_stage: ${missing.join(", ")}`);
			}
		}
		return {
			systemPrompt: `${event.systemPrompt}\n\n${lines.join("\n")}\n`,
		};
	});

	// =========================================================================
	// Custom tool — /cr-status equivalent for the LLM
	// =========================================================================
	pi.registerTool({
		name: "cr_status",
		label: "cr-status",
		description:
			"Read runs/<run_id>/manifest.json and report status, completed stages, missing artifacts, and last error. Use when the user asks 'what's the status of run X' or before invoking /cr-run to confirm the next expected stage.",
		parameters: Type.Object({
			run_id: Type.String({ description: "The run identifier." }),
		}),
		async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
			const m = readManifest(ctx.cwd, params.run_id);
			if (!m) {
				return {
					content: [
						{
							type: "text",
							text: `manifest.json not found for run_id=${params.run_id}.`,
						},
					],
					details: {},
					isError: true,
				};
			}
			const expected = nextExpectedStage(m);
			const missing = expected ? missingArtifacts(ctx.cwd, params.run_id, expected) : [];
			const payload = {
				run_id: m.run_id,
				status: m.status,
				completed_stages: m.completed_stages,
				next_expected_stage: expected,
				missing_for_next_stage: missing,
				last_error: m.last_error ?? null,
				updated_at: m.updated_at,
			};
			return {
				content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
				details: payload,
			};
		},
	});
}
