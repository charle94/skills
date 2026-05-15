# Prohibitions

Inherited from the original `sklearn-risk-analysis` skill. Items marked with
✅ are enforced mechanically by the pipeline / extension; others are
honor-system but mandatory.

- ❌ Use post-loan, result, or manual-approval fields as features.  
  ✅ Enforced: `stage_0_5_audit` drops on `post_loan_field` or `keyword_hit`.
- ❌ Reject rule based on IV alone, a single-period bad rate, or a single lift number.  
  Honor system; the agent must justify with cross-period evidence in `confidence_evidence.csv`.
- ❌ Strong reject rule with too-small sample share, too-few bad samples, or cross-period instability.  
  ✅ Enforced: `filter_rule_candidates` applies `rule_min_hit_rate`, `rule_min_bad_count`, `rule_min_lift`. `assign_confidence` downgrades unstable rules.
- ❌ Hide drop reasons, bin adjustments, threshold sources, or unfavourable simulation results.  
  ✅ Enforced: `feature_drop_reason.csv`, `bin_merge_log.csv`, `decision_log.csv`, `strategy_comparison.csv` are mandatory artifacts.
- ❌ Depend on `toad`.  
  ✅ Enforced: pipeline does not import toad; CI runs without it.
- ❌ Output only the decision-tree image without the single-rule table.  
  ✅ Enforced: stage 5 always emits `decision_tree_rules.csv`.
- ❌ Tree nodes missing good/bad counts, hit rate, bad rate, or lift.  
  ✅ Enforced: `render_tree_graphviz` writes all five into the node label.
- ❌ Go-live recommendation without leakage audit, OOT / monthly validation, segment simulation, and monitoring plan.  
  ✅ Enforced: stages 0.5, 3, 6, 8 must all be complete before stage 7 emits a `recommendation == 'go_live'`.
- ❌ Use WOE values as the business rule expression.  
  Honor system; the agent must always quote bin labels or business ranges in `rule_readable`.
- ❌ Re-bin train and OOT separately and then compute PSI.  
  ✅ Enforced: `stage_3_psi` uses `apply_bin_rules` on test/OOT with training `bin_rules.json`.
- ❌ Skip single-variable rule evaluation and jump straight to combo mining.  
  ✅ Enforced: `stage_5_2_combo_rules` reads `single_var_rule_eval.csv`; missing file → stage refused.
- ❌ Leave any of `train_value`, `test_value`, `oot_value` blank in `confidence_evidence.csv`.  
  ✅ Enforced: `build_confidence_evidence` raises; `validate_outputs.py` re-checks.
- ❌ Output only the waterfall final-step conclusion and omit per-step increments.  
  ✅ Enforced: `waterfall_simulation.csv` columns include `incremental_hit`, `incremental_bad`, `incremental_captured_bad_rate`.
- ❌ Re-call `label_encode_bins` on test/OOT.  
  ✅ Enforced: pipeline calls `apply_label_encode` with the training mapping; test exercises this contract.
- ❌ Mix `target IS NULL` rows into variable evaluation, WOE/IV, KS/AUC, PSI, or tree mining.  
  ✅ Enforced: `split_observable_sample` is called once at stage 0; observable frame drives stages 1..5.x.
- ❌ Output only `rule_simulation.csv` and omit `rule_simulation_full.csv`.  
  ✅ Enforced: `stage_6_simulation` always emits both; `validate_outputs.py` checks.
- ❌ Use `dot_escape`-style double-escape on `\n` in `decision_tree.dot`; nodes must be colored by `bad_rate / overall_bad_rate`.  
  ✅ Enforced: `render_tree_graphviz` uses single-backslash literal `\n` and `node_fillcolor` HSV gradient.

## Agent-specific prohibitions

- ❌ Re-implement any algorithm from `scripts/lib/` in a chat-message Python block or bash heredoc. Edit `scripts/lib/` and re-run instead.
- ❌ Write outside `runs/<run_id>/`. ✅ Enforced by `extensions/credit-risk-workflow.ts` (protected-paths).
- ❌ Run arbitrary bash. ✅ Enforced by `extensions/credit-risk-workflow.ts` (bash whitelist: `python3 scripts/...`, `pip install -r requirements.txt`, read-only inspection).
- ❌ Skip ahead to stage k+1 before stage k's required artifacts exist. ✅ Enforced by `extensions/credit-risk-workflow.ts` (state machine) and `scripts/validate_outputs.py`.
