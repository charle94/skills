/**
 * pi-credit-risk workflow extension
 * -------------------------------------------------------------------------
 * Enforces stable, reproducible execution of the credit-risk pipeline by:
 *   1. Maintaining a per-run state machine persisted in
 *      runs/<run_id>/manifest.json.
 *   2. Whitelisting bash commands to a safe subset.
 *   3. Restricting file writes to runs/<run_id>/.
 *   4. Auto-validating artifact completeness after each stage and refusing
 *      to advance the state machine on gaps.
 *   5. Injecting run context (current stage, missing artifacts) into the
 *      agent's prompt at every turn.
 *
 * Reference: https://pi.dev/docs/latest/packages — exact type names may
 * vary by SDK version; this module imports them defensively.
 */

// The exact import shape depends on the installed Pi SDK. We import what we
// use and the consumer's tsconfig will resolve it.
import type {
  ExtensionContext,
  Tool,
  ToolCall,
  ToolCallResult,
  Hook,
  AgentTurnContext,
} from "@earendil-works/pi-coding-agent";

import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";
import { execSync } from "child_process";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PACKAGE_ROOT = path.resolve(__dirname, "..");
const RUNS_DIR = path.resolve(process.cwd(), "runs");

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

/**
 * Stage status → manifest.status. Used both as a state transition and as the
 * gate check before allowing stage k+1.
 */
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
 * skills/sklearn-pandas-credit-risk/references/outputs.md and the assertions
 * inside scripts/validate_outputs.py — duplicated here for fast, local
 * pre-flight checks before the Python process is even invoked.
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
  "7": ["strategy_summary.md", "confidence_evidence.csv"],
  "8": ["monitoring_plan.csv"],
};

/**
 * Bash whitelist. The agent may only invoke commands whose first non-empty
 * token matches one of these patterns.
 *
 * Notes:
 *   • `python3 scripts/...` is the ONLY way to run computations.
 *   • `pip install -r requirements.txt` is allowed once at init.
 *   • Read-only file inspection is allowed for the agent to read its own
 *     run directory.
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
 * Path-write whitelist. Writes are allowed only beneath runs/<run_id>/
 * (any run_id) and a small set of package-managed directories during initial
 * scaffolding.
 */
const WRITE_WHITELIST: ReadonlyArray<RegExp> = [
  /^runs\/[A-Za-z0-9][A-Za-z0-9_.\-\/]*$/,
];

// ---------------------------------------------------------------------------
// Manifest helpers
// ---------------------------------------------------------------------------

interface Manifest {
  run_id: string;
  status: string;
  completed_stages: string[];
  artifacts: Record<string, string>;
  config_sha256?: string;
  input_sha256?: string;
  environment?: Record<string, unknown>;
  stage_history?: Array<Record<string, unknown>>;
  last_error?: string | null;
  updated_at: string;
}

function manifestPath(runId: string): string {
  return path.join(RUNS_DIR, runId, "manifest.json");
}

function readManifest(runId: string): Manifest | null {
  const p = manifestPath(runId);
  if (!fs.existsSync(p)) return null;
  return JSON.parse(fs.readFileSync(p, "utf-8")) as Manifest;
}

function writeManifest(runId: string, m: Manifest): void {
  m.updated_at = new Date().toISOString();
  fs.writeFileSync(manifestPath(runId), JSON.stringify(m, null, 2));
}

function sha256(filePath: string): string {
  const buf = fs.readFileSync(filePath);
  return "sha256:" + crypto.createHash("sha256").update(buf).digest("hex");
}

function nextExpectedStage(m: Manifest): string | null {
  for (const s of STAGE_ORDER) {
    if (!m.completed_stages.includes(s)) return s;
  }
  return null;
}

function missingArtifacts(runId: string, stage: string): string[] {
  const required = REQUIRED_ARTIFACTS[stage] || [];
  const runDir = path.join(RUNS_DIR, runId);
  return required.filter((rel) => !fs.existsSync(path.join(runDir, rel)));
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

/**
 * Block any bash command not matching BASH_WHITELIST.
 */
function bashGuard(call: ToolCall): ToolCallResult | null {
  if (call.tool !== "bash") return null;
  const cmd = String(call.arguments?.command ?? "").trim();
  if (!cmd) return null;
  const allowed = BASH_WHITELIST.some((re) => re.test(cmd));
  if (!allowed) {
    return {
      ok: false,
      error:
        `[pi-credit-risk] bash command refused by extension whitelist.\n` +
        `Got: ${cmd}\n` +
        `Allowed patterns:\n  - python3 scripts/<run_pipeline|validate_inputs|validate_outputs|run_stage|render_report>.py\n` +
        `  - python3 -m pytest …\n` +
        `  - python3 -c "…"\n` +
        `  - pip install -r requirements.txt\n` +
        `  - ls/cat/head/tail/wc/file/stat …\n` +
        `  - git status/log/diff/show …`,
    };
  }
  return null;
}

/**
 * Block any write whose path falls outside WRITE_WHITELIST.
 */
function pathWriteGuard(call: ToolCall): ToolCallResult | null {
  if (!["create", "edit", "write_file"].includes(call.tool)) return null;
  const target = String(call.arguments?.path ?? "");
  const rel = path.relative(process.cwd(), path.resolve(target));
  const allowed = WRITE_WHITELIST.some((re) => re.test(rel));
  if (!allowed) {
    return {
      ok: false,
      error:
        `[pi-credit-risk] file write refused: ${rel}. ` +
        `Writes are allowed only beneath runs/<run_id>/. ` +
        `If you need to modify package source, do it outside the agent.`,
    };
  }
  return null;
}

/**
 * Refuse stage invocations that violate stage order, and refresh manifest
 * after a successful invocation.
 */
function pipelineGuardBefore(call: ToolCall): ToolCallResult | null {
  if (call.tool !== "bash") return null;
  const cmd = String(call.arguments?.command ?? "");
  const m = cmd.match(/scripts\/run_pipeline\.py.*--stage\s+(\S+)/);
  if (!m) return null;
  const requestedStage = m[1];
  const configMatch = cmd.match(/--config\s+(\S+)/);
  if (!configMatch) return null;
  const config = JSON.parse(fs.readFileSync(configMatch[1], "utf-8"));
  const runId = config.run_id;
  const manifest = readManifest(runId);
  if (!manifest) {
    return {
      ok: false,
      error: `[pi-credit-risk] manifest.json missing for run_id=${runId}. Run /cr-init first.`,
    };
  }
  if (requestedStage === "all") return null; // pipeline self-orders
  const expected = nextExpectedStage(manifest);
  if (expected !== null && requestedStage !== expected) {
    return {
      ok: false,
      error:
        `[pi-credit-risk] stage out of order. ` +
        `Manifest says next expected stage = ${expected}, you requested = ${requestedStage}. ` +
        `Either invoke the expected stage or roll back manifest.completed_stages.`,
    };
  }
  return null;
}

/**
 * Post-stage hook: confirm required artifacts now exist on disk, refresh
 * SHA-256s in manifest.json, and advance manifest.status. If anything is
 * missing, manifest.last_error is set and status stays at the previous value.
 */
function pipelineHookAfter(call: ToolCall, result: ToolCallResult): void {
  if (call.tool !== "bash") return;
  const cmd = String(call.arguments?.command ?? "");
  const m = cmd.match(/scripts\/run_pipeline\.py.*--stage\s+(\S+).*--config\s+(\S+)/) ||
            cmd.match(/scripts\/run_pipeline\.py.*--config\s+(\S+).*--stage\s+(\S+)/);
  if (!m) return;
  const stage = m[1].startsWith("--") ? m[2] : m[1];
  const configPath = m[1].startsWith("--") ? m[1] : m[2];
  const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
  const runId = config.run_id;
  const manifest = readManifest(runId);
  if (!manifest) return;

  const stagesToCheck = stage === "all" ? STAGE_ORDER : [stage];
  for (const s of stagesToCheck) {
    const missing = missingArtifacts(runId, s);
    if (missing.length > 0) {
      manifest.last_error = `stage ${s} missing artifacts: ${missing.join(", ")}`;
      writeManifest(runId, manifest);
      return;
    }
    // Refresh hashes
    const runDir = path.join(RUNS_DIR, runId);
    for (const rel of REQUIRED_ARTIFACTS[s] || []) {
      manifest.artifacts[rel] = sha256(path.join(runDir, rel));
    }
    if (!manifest.completed_stages.includes(s)) manifest.completed_stages.push(s);
    manifest.status = STAGE_STATUS[s] ?? manifest.status;
    manifest.last_error = null;
  }
  writeManifest(runId, manifest);
}

// ---------------------------------------------------------------------------
// Context injection
// ---------------------------------------------------------------------------

/**
 * Before each agent turn, prepend a system message describing the active run:
 * its current stage, missing artifacts, last error. This prevents "amnesia"
 * across multi-turn conversations.
 */
function beforeAgentStart(ctx: AgentTurnContext): void {
  // Detect the active run from the most recent user message, e.g.
  // /cr-run <run_id> … or /cr-review <run_id>.
  const text = ctx.lastUserMessage ?? "";
  const m = text.match(/\/cr-(?:init|run|review|report|status)\s+(\S+)/);
  if (!m) return;
  const runId = m[1];
  const manifest = readManifest(runId);
  if (!manifest) return;
  const expected = nextExpectedStage(manifest);
  const lines: string[] = [
    `[pi-credit-risk context]`,
    `run_id: ${runId}`,
    `status: ${manifest.status}`,
    `completed_stages: ${manifest.completed_stages.join(", ") || "(none)"}`,
    `next_expected_stage: ${expected ?? "(all done)"}`,
  ];
  if (manifest.last_error) lines.push(`last_error: ${manifest.last_error}`);
  if (expected) {
    const missing = missingArtifacts(runId, expected);
    if (missing.length > 0) {
      lines.push(`missing_for_next_stage: ${missing.join(", ")}`);
    }
  }
  ctx.appendSystemEntry?.(lines.join("\n"));
}

// ---------------------------------------------------------------------------
// Tools — /cr-status (optional convenience)
// ---------------------------------------------------------------------------

const crStatusTool: Tool = {
  name: "cr_status",
  description:
    "Read runs/<run_id>/manifest.json and report status, completed_stages, missing artifacts, last_error.",
  inputSchema: {
    type: "object",
    required: ["run_id"],
    properties: { run_id: { type: "string" } },
  },
  async run(args: { run_id: string }): Promise<ToolCallResult> {
    const m = readManifest(args.run_id);
    if (!m) {
      return { ok: false, error: `manifest.json not found for run_id=${args.run_id}` };
    }
    const expected = nextExpectedStage(m);
    const missing = expected ? missingArtifacts(args.run_id, expected) : [];
    return {
      ok: true,
      data: {
        run_id: m.run_id,
        status: m.status,
        completed_stages: m.completed_stages,
        next_expected_stage: expected,
        missing_for_next_stage: missing,
        last_error: m.last_error ?? null,
        updated_at: m.updated_at,
      },
    };
  },
};

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export function activate(ctx: ExtensionContext): void {
  // Register pre-tool-call hooks (guards).
  ctx.registerHook("before_tool_call", (call: ToolCall) => {
    return bashGuard(call) ?? pathWriteGuard(call) ?? pipelineGuardBefore(call);
  });

  // Register post-tool-call hooks (manifest refresh).
  ctx.registerHook("after_tool_call", (call: ToolCall, result: ToolCallResult) => {
    if (result.ok) pipelineHookAfter(call, result);
  });

  // Register context-injection hook.
  ctx.registerHook("before_agent_start", beforeAgentStart);

  // Register the /cr-status tool.
  ctx.registerTool(crStatusTool);
}

export default { activate };
