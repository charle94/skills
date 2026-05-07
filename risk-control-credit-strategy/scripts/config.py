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
class CreditLimitConfig:
    """Top-level configuration object for all strategy modules."""
    income_verification: IncomeVerificationConfig = field(default_factory=IncomeVerificationConfig)
    dti: DTIConfig = field(default_factory=DTIConfig)
    tenor_factor: TenorFactorConfig = field(default_factory=TenorFactorConfig)
    risk_coefficient: RiskCoefficientConfig = field(default_factory=RiskCoefficientConfig)
    floor_cap: FloorCapConfig = field(default_factory=FloorCapConfig)
    dynamic_adjustment: DynamicAdjustmentConfig = field(default_factory=DynamicAdjustmentConfig)
    causal_inference: CausalInferenceConfig = field(default_factory=CausalInferenceConfig)
    
    product_cap: float = 100000.0
    
    @classmethod
    def from_dict(cls, config_dict: Dict) -> "CreditLimitConfig":
        """Create a config object from nested dict overrides."""
        config = cls()
        
        if "income_verification" in config_dict:
            for k, v in config_dict["income_verification"].items():
                if hasattr(config.income_verification, k):
                    setattr(config.income_verification, k, v)
        
        if "dti" in config_dict:
            for k, v in config_dict["dti"].items():
                if hasattr(config.dti, k):
                    setattr(config.dti, k, v)
        
        if "tenor_factor" in config_dict:
            for k, v in config_dict["tenor_factor"].items():
                if hasattr(config.tenor_factor, k):
                    setattr(config.tenor_factor, k, v)
        
        if "risk_coefficient" in config_dict:
            for k, v in config_dict["risk_coefficient"].items():
                if hasattr(config.risk_coefficient, k):
                    setattr(config.risk_coefficient, k, v)
        
        if "floor_cap" in config_dict:
            for k, v in config_dict["floor_cap"].items():
                if hasattr(config.floor_cap, k):
                    setattr(config.floor_cap, k, v)
        
        if "dynamic_adjustment" in config_dict:
            for k, v in config_dict["dynamic_adjustment"].items():
                if hasattr(config.dynamic_adjustment, k):
                    setattr(config.dynamic_adjustment, k, v)
        
        if "causal_inference" in config_dict:
            for k, v in config_dict["causal_inference"].items():
                if hasattr(config.causal_inference, k):
                    setattr(config.causal_inference, k, v)
        
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
