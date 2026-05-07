"""Strategy tuning, vintage analysis, portfolio monitoring, and simulation tests."""
import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_CONFIG, CreditLimitConfig
from strategy_tuning import diagnose_strategy
from vintage_analysis import (
    build_vintage_matrix,
    compute_reference_curve,
    detect_vintage_deterioration,
    derive_ever_bad,
    project_final_bad_rate,
)
from portfolio_monitoring import classify_psi, compute_psi
from simulation import StrategyEconomics, run_simulation


# ---------- Strategy tuning ----------

def test_strategy_tuning_flags_over_target_cells():
    df = pd.DataFrame({
        "customer_id": [f"P{i:03d}" for i in range(60)],
        "risk_level": ["low_risk"] * 60,
        "dti_bin": ["dti_low"] * 60,
        "bad_flag": [1] * 30 + [0] * 30,  # 50% bad rate, way above target
        "final_limit": [10000] * 60,
        "utilization_rate": [0.7] * 60,
        "months_on_book": [12] * 60,
    })
    cell_df, summary = diagnose_strategy(df, config=DEFAULT_CONFIG)
    assert summary["over_target_cells"] >= 1
    assert (cell_df["recommended_coefficient_factor"] < 1.0).any()


def test_strategy_tuning_marks_insufficient_data():
    df = pd.DataFrame({
        "customer_id": ["S1", "S2"],
        "risk_level": ["low_risk", "low_risk"],
        "dti_bin": ["dti_low", "dti_low"],
        "bad_flag": [0, 1],
        "months_on_book": [12, 12],
    })
    cell_df, summary = diagnose_strategy(df, config=DEFAULT_CONFIG)
    assert summary["insufficient_data_cells"] >= 1


# ---------- Vintage analysis ----------

def test_derive_ever_bad_threshold():
    df = pd.DataFrame({"dpd": [0, 15, 30, 45, 90]})
    result = derive_ever_bad(df, dpd_threshold=30)
    assert list(result["bad_flag"]) == [0, 0, 1, 1, 1]


def test_vintage_matrix_has_cohort_rows_and_mob_columns():
    df = pd.DataFrame({
        "customer_id": ["A", "A", "B", "B", "C", "C"] * 5,
        "origination_month": ["2023-01"] * 30,
        "mob": [1, 2] * 15,
        "bad_flag": [0] * 30,
    })
    mat, count, _ = build_vintage_matrix(df, min_cohort_obs=1)
    assert "2023-01" in mat.index
    assert 1 in mat.columns


def test_reference_curve_excludes_newer_cohorts():
    df = pd.DataFrame({
        "customer_id": [f"L{i}" for i in range(40)],
        "origination_month": ["2023-01"] * 20 + ["2023-06"] * 20,
        "mob": [3] * 40,
        "bad_flag": [0.1] * 20 + [0.5] * 20,  # treat as bad rates aggregated already
    })
    mat, count, _ = build_vintage_matrix(df, min_cohort_obs=1)
    ref_mean, ref_std = compute_reference_curve(mat, reference_cohort_count=1)
    # Only the oldest cohort should drive the reference
    assert abs(float(ref_mean.iloc[0]) - 0.1) < 0.01


# ---------- Portfolio monitoring ----------

def test_psi_zero_for_identical_distributions():
    base = pd.Series(np.random.RandomState(0).uniform(0, 1, 1000))
    psi, _ = compute_psi(base, base.copy(), bins=10)
    assert abs(psi) < 1e-6


def test_psi_positive_for_shifted_distribution():
    rng = np.random.RandomState(1)
    base = pd.Series(rng.uniform(0, 1, 1000))
    current = pd.Series(rng.uniform(0.4, 1.4, 1000))
    psi, _ = compute_psi(base, current, bins=10)
    assert psi > 0.10


def test_classify_psi_thresholds():
    assert classify_psi(0.05, DEFAULT_CONFIG) == "stable"
    assert classify_psi(0.15, DEFAULT_CONFIG) == "moderate_shift"
    assert classify_psi(0.50, DEFAULT_CONFIG) == "significant_shift"


# ---------- Simulation ----------

def _make_sim_population(n: int = 50, seed: int = 0) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    return pd.DataFrame({
        "customer_id": [f"S{i:03d}" for i in range(n)],
        "monthly_income": rng.randint(5000, 25000, n),
        "income_source": ["payroll"] * n,
        "existing_debt": rng.randint(0, 5000, n),
        "tenor_months": [24] * n,
        "risk_score": rng.uniform(0.4, 0.95, n),
        "dti": rng.uniform(0.1, 0.6, n),
        "utilization_rate": rng.uniform(0.4, 0.8, n),
    })


def test_simulation_returns_metrics_for_both_policies():
    df = _make_sim_population()
    champion_metrics, challenger_metrics, side_by_side, summary = run_simulation(
        df, DEFAULT_CONFIG, DEFAULT_CONFIG
    )
    assert champion_metrics.customer_count == 50
    assert challenger_metrics.customer_count == 50
    assert "decision" in summary
    # Same config → no profit delta
    assert abs(summary["deltas"]["expected_profit_total_delta"]) < 1e-6


def test_simulation_lower_cap_reduces_average_limit():
    import copy
    df = _make_sim_population(n=80)
    challenger_cfg = copy.deepcopy(DEFAULT_CONFIG)
    challenger_cfg.product_cap = 30000.0
    champion_metrics, challenger_metrics, _, summary = run_simulation(
        df, DEFAULT_CONFIG, challenger_cfg
    )
    assert challenger_metrics.avg_final_limit <= champion_metrics.avg_final_limit
    assert challenger_metrics.cap_hit_rate <= champion_metrics.cap_hit_rate or (
        challenger_metrics.avg_final_limit < champion_metrics.avg_final_limit
    )
