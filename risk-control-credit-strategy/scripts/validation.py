"""Input data validation against mode schemas.

Performs:
- Required column presence check
- dtype family check (numeric/categorical/boolean/string)
- Value range check (numeric)
- Enum check (categorical)
- Null rate report
- Returns a structured ValidationReport with errors and warnings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from schema import ColumnSpec, get_schema


@dataclass
class ValidationReport:
    """Structured outcome of input validation."""
    mode: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    column_diagnostics: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def to_dict(self) -> Dict:
        return {
            "mode": self.mode,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "column_diagnostics": self.column_diagnostics,
        }


def _is_numeric(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series)


def _is_boolean_like(series: pd.Series) -> bool:
    if pd.api.types.is_bool_dtype(series):
        return True
    non_null = series.dropna()
    if len(non_null) == 0:
        return True
    return set(non_null.unique()).issubset({True, False, 0, 1, "true", "false", "True", "False"})


def _check_dtype(series: pd.Series, expected: str) -> str | None:
    """Return None if ok, otherwise an error message."""
    if expected == "any":
        return None
    if expected == "numeric" and not _is_numeric(series):
        return f"expected numeric dtype, found {series.dtype}"
    if expected == "boolean" and not _is_boolean_like(series):
        return f"expected boolean-like values, found {series.dtype}"
    if expected == "string" and pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        # Numeric IDs are tolerable as strings
        return None
    return None


def _check_range(series: pd.Series, lo: float, hi: float) -> Dict[str, Any] | None:
    """Return summary of out-of-range values, or None if all in range."""
    numeric_series = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric_series) == 0:
        return None
    out_of_range = numeric_series[(numeric_series < lo) | (numeric_series > hi)]
    if len(out_of_range) == 0:
        return None
    return {
        "out_of_range_count": int(len(out_of_range)),
        "out_of_range_pct": round(float(len(out_of_range) / len(numeric_series)), 4),
        "expected_range": [lo, hi],
        "actual_min": float(numeric_series.min()),
        "actual_max": float(numeric_series.max()),
    }


def _check_enum(series: pd.Series, allowed: List[Any]) -> Dict[str, Any] | None:
    """Return summary of unexpected values, or None if all values are allowed."""
    non_null = series.dropna()
    if len(non_null) == 0:
        return None
    allowed_set = set(allowed)
    bad_mask = ~non_null.isin(allowed_set)
    if not bad_mask.any():
        return None
    bad_values = non_null[bad_mask].unique().tolist()[:10]
    return {
        "invalid_count": int(bad_mask.sum()),
        "invalid_pct": round(float(bad_mask.mean()), 4),
        "sample_invalid_values": [str(v) for v in bad_values],
        "allowed_values": [str(v) for v in allowed],
    }


def validate_dataframe(df: pd.DataFrame, mode: str, strict: bool = True) -> ValidationReport:
    """Validate a DataFrame against the schema for the given mode.

    Parameters
    ----------
    df     : DataFrame to validate.
    mode   : One of the modes registered in `schema.MODE_SCHEMAS`.
    strict : If True, range/enum violations become errors. If False, they become warnings.

    Returns
    -------
    ValidationReport with errors, warnings, and per-column diagnostics.
    """
    report = ValidationReport(mode=mode)
    schema = get_schema(mode)

    if len(df) == 0:
        report.errors.append("input dataframe is empty")
        return report

    actual_cols = set(df.columns)

    # 1. Required columns
    for spec in schema:
        if spec.required and spec.name not in actual_cols:
            report.errors.append(f"missing required column: '{spec.name}'")

    # 2. Per-column diagnostics
    for spec in schema:
        if spec.name not in actual_cols:
            continue

        col_diag: Dict[str, Any] = {
            "dtype": str(df[spec.name].dtype),
            "null_count": int(df[spec.name].isna().sum()),
            "null_pct": round(float(df[spec.name].isna().mean()), 4),
        }

        # dtype check
        dtype_err = _check_dtype(df[spec.name], spec.dtype)
        if dtype_err:
            msg = f"column '{spec.name}': {dtype_err}"
            if strict:
                report.errors.append(msg)
            else:
                report.warnings.append(msg)

        # value_range check
        if spec.value_range is not None:
            range_diag = _check_range(df[spec.name], spec.value_range[0], spec.value_range[1])
            if range_diag is not None:
                col_diag["range_violations"] = range_diag
                msg = (
                    f"column '{spec.name}': {range_diag['out_of_range_count']} values "
                    f"({range_diag['out_of_range_pct']:.1%}) outside expected range "
                    f"{range_diag['expected_range']} (actual min/max: "
                    f"{range_diag['actual_min']}/{range_diag['actual_max']})"
                )
                if strict and range_diag["out_of_range_pct"] > 0.05:
                    report.errors.append(msg)
                else:
                    report.warnings.append(msg)

        # enum check
        if spec.allowed_values is not None:
            enum_diag = _check_enum(df[spec.name], spec.allowed_values)
            if enum_diag is not None:
                col_diag["enum_violations"] = enum_diag
                msg = (
                    f"column '{spec.name}': {enum_diag['invalid_count']} values "
                    f"({enum_diag['invalid_pct']:.1%}) not in allowed set "
                    f"{enum_diag['allowed_values']}; sample invalid: "
                    f"{enum_diag['sample_invalid_values']}"
                )
                if strict:
                    report.errors.append(msg)
                else:
                    report.warnings.append(msg)

        # high null warning
        if col_diag["null_pct"] > 0.20 and spec.required:
            report.warnings.append(
                f"column '{spec.name}': high null rate {col_diag['null_pct']:.1%} on a required column"
            )

        report.column_diagnostics[spec.name] = col_diag

    # 3. Customer ID uniqueness for non-time-series modes
    if "customer_id" in df.columns and mode not in ("vintage_analysis", "portfolio_monitoring"):
        dupes = int(df["customer_id"].duplicated().sum())
        if dupes > 0:
            report.warnings.append(
                f"customer_id has {dupes} duplicate values; downstream aggregation may double-count"
            )

    return report


def assert_valid(df: pd.DataFrame, mode: str, strict: bool = True) -> ValidationReport:
    """Validate and raise if errors are found. Returns the report on success."""
    report = validate_dataframe(df, mode, strict=strict)
    if not report.is_valid:
        joined = "\n  - ".join(report.errors)
        raise ValueError(f"Input validation failed for mode '{mode}':\n  - {joined}")
    return report
