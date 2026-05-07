"""Central configuration for the credit limit strategy toolkit."""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class IncomeVerificationConfig:
    """收入认定配置"""
    income_haircuts: Dict[str, float] = field(default_factory=lambda: {
        "payroll": 1.0,
        "bank_flow": 0.8,
        "tax_return": 0.9,
        "social_security": 0.7,
        "provident_fund": 0.7,
        "self_reported": 0.5,
        "model_predicted": 0.6,
    })
    

@dataclass
class DTIConfig:
    """DTI阈值配置"""
    dti_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "conservative": 0.30,
        "moderate": 0.50,
        "aggressive": 0.70,
    })
    default_dti_level: str = "moderate"


@dataclass
class TenorFactorConfig:
    """期数系数配置"""
    tenor_factors: Dict[str, Dict[float, float]] = field(default_factory=lambda: {
        "short": {"min_months": 3, "max_months": 6, "factor_range": (0.8, 1.0)},
        "medium": {"min_months": 12, "max_months": 24, "factor_range": (1.0, 1.2)},
        "long": {"min_months": 36, "max_months": 60, "factor_range": (1.2, 1.5)},
    })
    default_factor: float = 1.0


@dataclass
class RiskCoefficientConfig:
    """Risk coefficient matrix and score binning rules."""
    coefficient_matrix: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "very_low_risk": {"dti_low": 4.0, "dti_medium": 3.0, "dti_high": 2.2, "dti_very_high": 1.4},
        "low_risk": {"dti_low": 3.5, "dti_medium": 2.5, "dti_high": 2.0, "dti_very_high": 1.2},
        "high_risk": {"dti_low": 1.5, "dti_medium": 1.5, "dti_high": 1.2, "dti_very_high": 0.8},
        "medium_risk": {"dti_low": 2.5, "dti_medium": 2.0, "dti_high": 1.5, "dti_very_high": 0.8},
    })
    dti_bins: List[float] = field(default_factory=lambda: [0.10, 0.25, 0.40, 0.50])
    risk_score_bins: List[float] = field(default_factory=lambda: [0.20, 0.50, 0.80])


@dataclass
class FloorCapConfig:
    """托底盖帽配置"""
    floor_cap_matrix: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "level_1_best": {"cap": 110000, "floor": 3000},
        "level_2": {"cap": 90000, "floor": 3000},
        "level_3": {"cap": 80000, "floor": 3000},
        "level_4": {"cap": 70000, "floor": 2000},
        "level_5_worst": {"cap": 40000, "floor": 2000},
    })
    apply_floor_only_when_affordable: bool = True


@dataclass
class DynamicAdjustmentConfig:
    """动态调整配置"""
    increase_triggers: Dict[str, Dict] = field(default_factory=lambda: {
        "passive": {
            "excellent_repayment_months": 6,
            "score_improvement_threshold": 20,
            "high_utilization_threshold": 0.80,
        },
        "active": {
            "request_allowed": True,
            "income_proof_required": True,
        }
    })
    decrease_triggers: Dict[str, Dict] = field(default_factory=lambda: {
        "immediate": {
            "fraud_signal": True,
            "overdue_m2_plus": True,
        },
        "gradual": {
            "overdue_m1": True,
            "score_drop_threshold": 30,
            "multi_lending_threshold": 5,
        }
    })
    increase_frequency_months: int = 6
    gradual_decrease_steps: int = 2
    gradual_decrease_ratio: float = 0.5
    freeze_keeps_current_limit: bool = True


@dataclass
class CausalInferenceConfig:
    """因果推断配置"""
    ab_test_config: Dict = field(default_factory=lambda: {
        "control_ratio": 0.5,
        "observation_window_months": 6,
        "min_sample_size": 1000,
    })
    psm_config: Dict = field(default_factory=lambda: {
        "caliper": 0.05,
        "matching_method": "nearest",
        "min_matches": 1,
        "min_match_rate": 0.60,
        "max_abs_smd": 0.10,
    })
    evaluation_metrics: List[str] = field(default_factory=lambda: [
        "lift", "ks", "profit_simulation"
    ])


@dataclass
class StrategyTuningConfig:
    """策略调优配置"""
    target_bad_rates: Dict[str, float] = field(default_factory=lambda: {
        "very_low_risk": 0.02,
        "low_risk": 0.05,
        "medium_risk": 0.10,
        "high_risk": 0.18,
    })
    deviation_threshold: float = 0.20
    min_cell_observations: int = 30
    lgd: float = 0.60
    mob_min_for_maturity: int = 6
    max_relax_factor: float = 1.30
    min_tighten_factor: float = 0.50


@dataclass
class VintageAnalysisConfig:
    """老贷款批次（Vintage）分析配置"""
    dpd_thresholds: List[int] = field(default_factory=lambda: [30, 60, 90])
    reference_cohort_count: int = 4
    deterioration_z_threshold: float = 1.5
    min_cohort_observations: int = 20
    maturation_mob_targets: List[int] = field(default_factory=lambda: [3, 6, 12, 18, 24])


@dataclass
class PortfolioMonitoringConfig:
    """组合监控配置 — PSI/CSI 和 KPI 追踪"""
    psi_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "stable": 0.10,
        "moderate_shift": 0.25,
    })
    psi_bins: int = 10
    csi_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "stable": 0.10,
        "moderate_shift": 0.25,
    })
    kpi_alert_rules: Dict[str, Dict] = field(default_factory=lambda: {
        "bad_rate": {"relative_increase_pct": 20.0, "absolute_increase": 0.02},
        "approval_rate": {"relative_decrease_pct": 10.0},
        "utilization_rate": {"absolute_increase": 0.10},
    })


@dataclass
class CreditLimitConfig:
    """Top-level configuration object for all strategy modules."""
    income_verification: IncomeVerificationConfig = field(default_factory=IncomeVerificationConfig)
    dti: DTIConfig = field(default_factory=DTIConfig)
    tenor_factor: TenorFactorConfig = field(default_factory=TenorFactorConfig)
    risk_coefficient: RiskCoefficientConfig = field(default_factory=RiskCoefficientConfig)
    floor_cap: FloorCapConfig = field(default_factory=FloorCapConfig)
    dynamic_adjustment: DynamicAdjustmentConfig = field(default_factory=DynamicAdjustmentConfig)
    causal_inference: CausalInferenceConfig = field(default_factory=CausalInferenceConfig)
    strategy_tuning: StrategyTuningConfig = field(default_factory=StrategyTuningConfig)
    vintage_analysis: VintageAnalysisConfig = field(default_factory=VintageAnalysisConfig)
    portfolio_monitoring: PortfolioMonitoringConfig = field(default_factory=PortfolioMonitoringConfig)

    product_cap: float = 100000.0

    _SECTION_CLASSES = {
        "income_verification": "income_verification",
        "dti": "dti",
        "tenor_factor": "tenor_factor",
        "risk_coefficient": "risk_coefficient",
        "floor_cap": "floor_cap",
        "dynamic_adjustment": "dynamic_adjustment",
        "causal_inference": "causal_inference",
        "strategy_tuning": "strategy_tuning",
        "vintage_analysis": "vintage_analysis",
        "portfolio_monitoring": "portfolio_monitoring",
    }

    @classmethod
    def from_dict(cls, config_dict: Dict) -> "CreditLimitConfig":
        """Create a config object from nested dict overrides."""
        config = cls()
        for section_key in cls._SECTION_CLASSES:
            if section_key in config_dict:
                section_obj = getattr(config, section_key)
                for k, v in config_dict[section_key].items():
                    if hasattr(section_obj, k):
                        setattr(section_obj, k, v)
        if "product_cap" in config_dict:
            config.product_cap = config_dict["product_cap"]
        return config
    
    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


DEFAULT_CONFIG = CreditLimitConfig()


def load_config(config_path: str | Path) -> CreditLimitConfig:
    """Load JSON config overrides from disk."""
    path = Path(config_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CreditLimitConfig.from_dict(payload)
