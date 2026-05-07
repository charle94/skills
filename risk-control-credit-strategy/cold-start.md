# Strategy Cold Start

## Purpose

Use this module when a credit product, market, channel, or customer segment has little or no local performance history. The objective is to launch safely, learn quickly, and avoid irreversible exposure mistakes while collecting the data needed for later tuning.

## Trigger Conditions

Use cold-start mode when:
- there is no mature local default/loss label;
- a new product, region, acquisition channel, risk band, or pricing plan is launching;
- model score exists but has not been validated on the target population;
- the user asks for an initial strategy, pilot strategy, grey launch, or first version of risk policy.

## Required Inputs

Minimum business inputs:
- product type, tenor, APR/pricing, repayment method, and product cap;
- target customer population and acquisition channel;
- available data fields: identity, income, debt, bureau, behavior, device, bank flow, employment, fraud signals;
- risk appetite: maximum acceptable bad rate/loss, approval target, funding budget, operational capacity;
- legal/regulatory constraints and customer communication constraints.

If any of these are unknown, proceed with conservative assumptions and mark them as blockers or partial readiness.

## Execution Steps

1. **Define the launch objective**
   - Choose one primary objective: learn risk ranking, acquire high-quality customers, test utilization, or validate pricing.
   - Do not optimize approval rate and loss simultaneously without a declared trade-off.

2. **Build minimum viable segmentation**
   - Segment by the strongest available stable signals: verified income, bureau/score band, DTI/debt pressure, channel, fraud risk, tenure/relationship, geography if relevant.
   - Keep early cells coarse enough to accumulate observations.
   - Exclude segments with identity risk, fraud flags, severe delinquency, blacklist, sanctions, or no repayment-capacity signal.

3. **Set conservative initial exposure**
   - Use `limit-calculation.md` as the affordability anchor.
   - Apply conservative DTI and lower product caps during pilot.
   - Prefer smaller limits across more clean customers over large limits to uncertain customers.
   - Never use floor protection for no-capacity accounts.

4. **Define pilot allocation**
   - Start with low rollout percentage and explicit sample-size target per key segment.
   - Use champion/challenger cells if volume allows: current conservative policy vs slightly higher/lower limit or coefficient.
   - Randomize within eligible cells when possible; otherwise preserve a clear control group.

5. **Set stop-loss and monitoring gates**
   - Define daily/weekly monitoring for approval rate, booked amount, utilization, early DPD, fraud hit, complaints, manual review rate, and funding consumption.
   - Define hard stop thresholds before launch, not after losses appear.
   - Include both absolute thresholds and relative movement versus control or expectation.

6. **Prepare operational controls**
   - Manual review rules for uncertain or high-exposure cases.
   - Maximum exposure per customer, segment, channel, and day.
   - Rollback switch: which rules to disable, who owns the decision, and how fast it can be executed.

7. **Plan learning loop**
   - First review: operational metrics and fraud signals.
   - Second review: utilization and early delinquency.
   - Third review: mature loss/profit and causal evaluation.
   - Feed results into `strategy-tuning.md` and `causal-inference.md`.

## Cold-Start Output Template

Produce these sections:

1. Launch objective and target population.
2. Available data and missing blockers.
3. Eligible / excluded population rules.
4. Initial segmentation table.
5. Initial limit policy: base limit, risk coefficient, floor, cap, DTI, product cap.
6. Pilot allocation and control design.
7. Monitoring dashboard: metrics, thresholds, cadence, owner.
8. Stop-loss and rollback plan.
9. Data collection plan for tuning and effect evaluation.
10. Readiness status: `ready`, `partial`, or `blocked`.

## Acceptance Criteria

The cold-start plan is usable only if:
- launch objective is singular and measurable;
- exclusions and no-go segments are explicit;
- initial exposure is tied to affordability and risk bands;
- pilot size and control design are defined;
- stop-loss thresholds and owners are named;
- the plan states what evidence is needed before scaling.

## Red Flags

- launching without a rollback switch;
- using mature-market coefficients in an unvalidated new population;
- no control group or no holdout population;
- pilot cells too fragmented to learn anything;
- early success judged only by approval/booked volume;
- no fraud and complaint monitoring during growth.
