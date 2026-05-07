# Strategy Tuning

## Purpose

Use this module after a strategy is live and performance data begins to arrive. The objective is to diagnose why performance changed, make the smallest effective policy edit, and verify the edit with controlled rollout rather than broad manual overrides.

## Trigger Conditions

Use tuning when:
- delinquency, loss, approval rate, utilization, or profit deviates from expectation;
- floors/caps or coefficients appear too loose or too conservative;
- a cold-start pilot needs scaling, narrowing, or rollback;
- a champion/challenger test identifies a possible better policy;
- operations report queue overload, complaints, or excessive manual review.

## Required Inputs

Minimum inputs:
- policy version and launch date;
- segment-level exposure, approval, booking, utilization, and delinquency vintages;
- score/risk bands, DTI bands, income source, channel, product, tenor;
- current policy table: coefficients, floors, caps, exclusions, cooldowns;
- business objective and risk appetite thresholds.

Recommended inputs:
- model score distribution drift, PSI/CSI, bureau changes, external macro/channel changes;
- profit components: interest, fee, funding cost, LGD, operating cost;
- treatment/control assignment for effect evaluation.

## Execution Steps

1. **Define the problem precisely**
   - State metric, direction, magnitude, affected period, and affected population.
   - Separate volume mix changes from true risk deterioration.

2. **Decompose by strategy layer**
   - Affordability layer: income source, DTI threshold, debt completeness, tenor factor.
   - Risk layer: score band, coefficient, floor/cap hit rate, ranking validation.
   - Dynamic layer: increase/decrease/freeze triggers, cooldown, queue priority.
   - Evaluation layer: whether observed change is causal or selection/mix.

3. **Find bad cells and good cells**
   - Cut by risk level, DTI bin, income source, channel, tenor, utilization, and policy version.
   - Identify cells with high exposure and high marginal loss first.
   - Do not retune the whole policy when only one cell is broken.

4. **Choose the smallest policy edit**
   - If affordability is wrong: adjust haircuts, DTI thresholds, debt treatment, or tenor factor.
   - If risk ranking is wrong: fix score direction/bins or coefficient matrix.
   - If floors/caps distort risk: reduce floor, lower cap, or block floor by segment.
   - If account management is late: tighten decrease/freeze triggers or reduce cooldown/increase ratio.
   - If growth is too conservative: relax only cells with clean vintage, good utilization, and acceptable profit.

5. **Simulate before launch**
   - Estimate affected customer count, approval/booked amount change, expected loss, profit, and operations queue impact.
   - Compare current policy vs proposed policy by segment.

6. **Roll out with guardrails**
   - Use champion/challenger, phased rollout, or limited exposure budget.
   - Define pass/fail gates before rollout.
   - Preserve a control group when future causal evaluation is required.

7. **Evaluate and decide**
   - Use `causal-inference.md` if treatment/control data exists.
   - Decide: scale, keep testing, narrow, or roll back.

## Tuning Output Template

Produce these sections:

1. Problem statement and affected population.
2. Diagnostic cuts and suspected root cause.
3. Current policy weakness.
4. Proposed minimal policy edit.
5. Expected impact simulation.
6. Rollout plan and monitoring gates.
7. Evaluation design.
8. Final decision: scale / test / narrow / rollback.

## Acceptance Criteria

The tuning recommendation is usable only if:
- the root cause is tied to a segment or strategy layer;
- the proposed edit is smaller than a full-policy rewrite unless the whole policy is broken;
- expected impact includes risk and business metrics;
- rollout has control, gate, owner, and stop-loss;
- future evaluation can distinguish policy effect from population mix.

## Red Flags

- tuning by intuition without segment cuts;
- changing coefficients and floors at the same time with no attribution plan;
- treating short-tenor early performance as mature loss performance;
- improving approval rate while ignoring utilization and loss;
- removing bad segments without checking whether channel mix caused the issue;
- scaling a challenger before control-group evidence is credible.
