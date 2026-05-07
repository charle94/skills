"""Shared policy run context that flows between pipeline stages.

A `PolicyRun` aggregates per-stage results so downstream stages can read
upstream output without rebuilding DataFrame joins. This makes the cross-
module data flow explicit:

    cold_start → base_limit → risk_adjustment → dynamic_adjustment
                                                         ↓
                              vintage_analysis ← (booked accounts)
                                                         ↓
                              portfolio_monitoring (live KPIs)
                                                         ↓
                              strategy_tuning (cell diagnostics)
                                                         ↓
                              causal_inference (effect)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class PolicyRun:
    """One execution of the strategy pipeline; carries state across stages."""

    # Identity
    run_id: str
    mode: str
    started_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    # Inputs
    input_df: Optional[pd.DataFrame] = None
    base_period_df: Optional[pd.DataFrame] = None  # for portfolio_monitoring
    config_snapshot: Dict[str, Any] = field(default_factory=dict)

    # Stage outputs
    base_limit_df: Optional[pd.DataFrame] = None
    risk_adjustment_df: Optional[pd.DataFrame] = None
    dynamic_adjustment_df: Optional[pd.DataFrame] = None
    strategy_tuning_df: Optional[pd.DataFrame] = None
    vintage_outputs: Dict[str, Any] = field(default_factory=dict)
    monitoring_outputs: Dict[str, Any] = field(default_factory=dict)
    causal_outputs: Dict[str, Any] = field(default_factory=dict)
    simulation_outputs: Dict[str, Any] = field(default_factory=dict)

    # Per-stage summary metrics (compact dict for reporting)
    stage_summaries: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    steps_run: List[str] = field(default_factory=list)
    skipped_steps: List[str] = field(default_factory=list)

    # Validation report (from validation.validate_dataframe)
    validation_report: Optional[Dict[str, Any]] = None

    def record_stage(self, stage: str, summary: Dict[str, Any]) -> None:
        """Append a stage's summary metrics and mark it as completed."""
        self.stage_summaries[stage] = summary
        if stage not in self.steps_run:
            self.steps_run.append(stage)

    def skip_stage(self, stage: str, reason: str) -> None:
        """Mark a stage as skipped with a documented reason."""
        if stage not in self.skipped_steps:
            self.skipped_steps.append(stage)
        self.stage_summaries.setdefault(stage, {})["skipped_reason"] = reason

    def to_summary_dict(self) -> Dict[str, Any]:
        """Compact JSON-friendly view for the run_summary.json artifact."""
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "started_at": self.started_at,
            "steps_run": self.steps_run,
            "skipped_steps": self.skipped_steps,
            "stage_summaries": self.stage_summaries,
            "validation_report": self.validation_report,
        }
