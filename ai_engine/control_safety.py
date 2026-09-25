#!/usr/bin/env python3

"""
INDUS_TWIN Control Safety Layer

Purpose
-------
Validate AI energy-control decisions before they are sent to ROS2.

Decision types:
    REDUCE
    HOLD
    RESTORE

Safety rules:
    1. Already reduced/curtailed machines are not reduced again.
    2. HIGH/CRITICAL maintenance blocks new reduction.
    3. HIGH/CRITICAL maintenance on an already-reduced machine requests restore.
    4. FIXED machines cannot be reduced.
    5. Production-unsafe machines cannot be reduced.
    6. A machine marked safe_to_reduce=False cannot be reduced.
    7. REDUCE target must be strictly below current power.
    8. REDUCE target must not be below minimum operating power.
    9. Reduction cannot exceed configured maximum.
   10. Missing production evidence fails safe and blocks reduction.

Important
---------
Production safety is loaded from:
    ai_engine/production_impact_output.csv

This is deliberate: the optimizer output does not currently carry the
production_safe / safe_to_reduce fields. The safety layer therefore enriches
each optimizer decision with the latest production-impact result before
making the final REDUCE / HOLD / RESTORE decision.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

AI_DIR = ROOT / "ai_engine"

OPTIMIZATION_PATH = AI_DIR / "optimization_output.csv"
MAINTENANCE_PATH = AI_DIR / "maintenance_output.csv"
PRODUCTION_IMPACT_PATH = AI_DIR / "production_impact_output.csv"
OUTPUT_PATH = AI_DIR / "control_safety_output.csv"

EPS = 1e-6


# ============================================================================
# MACHINE STATES / LABELS
# ============================================================================

ACTIVE_CONTROL_STATES = {
    "REDUCED",
    "CURTAILED",
    "SHIFTED",
    "CONTROLLED",
}

HIGH_RISK_LABELS = {
    "HIGH",
    "CRITICAL",
}

FIXED_CONTROL_TYPES = {
    "FIXED",
}


# ============================================================================
# HELPERS
# ============================================================================

def to_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
        if math.isfinite(value):
            return value
    except (TypeError, ValueError):
        pass
    return default


def clean(value: Any) -> str:
    return (
        str(value if value is not None else "")
        .strip()
        .upper()
        .replace(" ", "_")
    )


def to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    return clean(value) in {
        "TRUE",
        "YES",
        "Y",
        "1",
        "ON",
    }


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found:\n{path}"
        )


def latest_per_machine(df: pd.DataFrame) -> pd.DataFrame:
    """Return the newest row for each machine based on timestamp."""
    if "machine_id" not in df.columns:
        return df.copy()

    work = df.copy()

    if "timestamp" in work.columns:
        work["_ts"] = pd.to_numeric(
            work["timestamp"],
            errors="coerce",
        ).fillna(-1)

        work = work.sort_values(
            ["machine_id", "_ts"]
        )

    work = work.drop_duplicates(
        "machine_id",
        keep="last",
    )

    return work.drop(
        columns="_ts",
        errors="ignore",
    )


def safe_machine_id(value: Any) -> str:
    return str(value if value is not None else "").strip()


def safe_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            separators=(",", ":"),
        )
    except Exception:
        return "{}"


# ============================================================================
# DATA LOADING
# ============================================================================

def load_production_impact_latest() -> pd.DataFrame:
    """
    Load latest production-impact result for every machine.

    Missing production-impact data is treated as a safety problem rather than
    assuming a machine is safe to reduce.
    """
    if not PRODUCTION_IMPACT_PATH.exists():
        return pd.DataFrame(
            columns=[
                "machine_id",
                "production_safe",
                "safe_to_reduce",
                "production_loss_percent",
                "remaining_production_percent",
                "estimated_units_lost",
                "estimated_energy_saved_kwh",
                "recommendation",
            ]
        )

    production = pd.read_csv(PRODUCTION_IMPACT_PATH)

    if production.empty:
        return pd.DataFrame(
            columns=[
                "machine_id",
                "production_safe",
                "safe_to_reduce",
                "production_loss_percent",
                "remaining_production_percent",
                "estimated_units_lost",
                "estimated_energy_saved_kwh",
                "recommendation",
            ]
        )

    production = latest_per_machine(production)

    # Normalize expected production-safety fields.
    for col in [
        "production_safe",
        "safe_to_reduce",
    ]:
        if col not in production.columns:
            production[col] = False
        production[col] = production[col].map(to_bool)

    for col in [
        "production_loss_percent",
        "remaining_production_percent",
        "estimated_units_lost",
        "estimated_energy_saved_kwh",
    ]:
        if col not in production.columns:
            production[col] = 0.0
        production[col] = pd.to_numeric(
            production[col],
            errors="coerce",
        ).fillna(0.0)

    if "recommendation" not in production.columns:
        production["recommendation"] = "UNKNOWN"

    return production


def load_inputs() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    require_file(OPTIMIZATION_PATH)
    require_file(MAINTENANCE_PATH)

    optimization = pd.read_csv(
        OPTIMIZATION_PATH
    )

    maintenance = pd.read_csv(
        MAINTENANCE_PATH
    )

    production = load_production_impact_latest()

    if optimization.empty:
        raise ValueError(
            "optimization_output.csv is empty."
        )

    if maintenance.empty:
        raise ValueError(
            "maintenance_output.csv is empty."
        )

    optimization = latest_per_machine(
        optimization
    )

    maintenance = latest_per_machine(
        maintenance
    )

    return (
        optimization,
        maintenance,
        production,
    )


# ============================================================================
# PREPARE / MERGE
# ============================================================================

def _coalesce_columns(
    df: pd.DataFrame,
    preferred: str,
    alternate: str,
    default: Any,
) -> None:
    """Fill preferred from alternate, then default."""
    if preferred not in df.columns:
        df[preferred] = default

    if alternate in df.columns:
        mask = df[preferred].isna()
        df.loc[mask, preferred] = df.loc[
            mask,
            alternate,
        ]

    df[preferred] = df[preferred].fillna(
        default
    )


def prepare(
    optimization: pd.DataFrame,
    maintenance: pd.DataFrame,
    production: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:

    df = optimization.copy()

    # ------------------------------------------------------------------------
    # Maintenance merge
    # ------------------------------------------------------------------------

    maintenance_columns = [
        "machine_id",
        "maintenance_risk",
        "maintenance_label",
        "maintenance_trigger",
        "maintenance_reason",
    ]

    keep = [
        column
        for column in maintenance_columns
        if column in maintenance.columns
    ]

    if (
        "machine_id" in maintenance.columns
        and len(keep) > 1
    ):
        df = df.merge(
            maintenance[keep],
            on="machine_id",
            how="left",
            suffixes=(
                "",
                "_maintenance",
            ),
        )

        for col in [
            "maintenance_risk",
            "maintenance_label",
            "maintenance_trigger",
            "maintenance_reason",
        ]:
            alt = f"{col}_maintenance"
            if alt in df.columns:
                if col not in df.columns:
                    df[col] = df[alt]
                else:
                    if col == "maintenance_risk":
                        current = pd.to_numeric(
                            df[col],
                            errors="coerce",
                        )
                        fallback = pd.to_numeric(
                            df[alt],
                            errors="coerce",
                        )
                        df[col] = current.fillna(
                            fallback
                        )
                    elif col == "maintenance_trigger":
                        current = df[col].map(to_bool)
                        fallback = df[alt].map(to_bool)
                        df[col] = current | fallback
                    else:
                        current = df[col].astype(str)
                        fallback = df[alt].astype(str)
                        bad = (
                            df[col].isna()
                            | current.str.strip().eq("")
                            | current.str.upper().eq("NAN")
                        )
                        df.loc[
                            bad,
                            col,
                        ] = df.loc[
                            bad,
                            alt,
                        ]

                df = df.drop(
                    columns=alt
                )

    # ------------------------------------------------------------------------
    # Production-impact merge
    #
    # This is the key fix for the current live-system issue.
    # ------------------------------------------------------------------------

    if production is None:
        production = load_production_impact_latest()

    production_columns = [
        "machine_id",
        "production_safe",
        "safe_to_reduce",
        "production_loss_percent",
        "remaining_production_percent",
        "estimated_units_lost",
        "estimated_units_remaining",
        "estimated_energy_saved_kwh",
        "minimum_production_percent",
        "recommendation",
    ]

    pkeep = [
        column
        for column in production_columns
        if column in production.columns
    ]

    if (
        "machine_id" in production.columns
        and len(pkeep) > 1
    ):
        df = df.merge(
            production[pkeep],
            on="machine_id",
            how="left",
            suffixes=(
                "",
                "_production",
            ),
        )

        for col in [
            "production_safe",
            "safe_to_reduce",
            "production_loss_percent",
            "remaining_production_percent",
            "estimated_units_lost",
            "estimated_units_remaining",
            "estimated_energy_saved_kwh",
            "minimum_production_percent",
            "recommendation",
        ]:
            alt = f"{col}_production"

            if alt not in df.columns:
                continue

            if col not in df.columns:
                df[col] = df[alt]
            else:
                if col in {
                    "production_safe",
                    "safe_to_reduce",
                }:
                    current = df[col].map(to_bool)
                    fallback = df[alt].map(to_bool)

                    # The authoritative production-impact result should
                    # override a missing / default value, but a false value
                    # must never become true through OR logic.
                    missing = (
                        df[col].isna()
                        | df[col].astype(str).str.upper().eq("NAN")
                    )

                    df.loc[
                        missing,
                        col,
                    ] = fallback.loc[
                        missing
                    ]

                else:
                    current = pd.to_numeric(
                        df[col],
                        errors="coerce",
                    )
                    fallback = pd.to_numeric(
                        df[alt],
                        errors="coerce",
                    )
                    df[col] = current.fillna(
                        fallback
                    )

            df = df.drop(
                columns=alt
            )

    # ------------------------------------------------------------------------
    # Normalize numeric columns
    # ------------------------------------------------------------------------

    numeric_columns = [
        "current_power_kw",
        "normal_target_kw",
        "min_operating_power_kw",
        "allowed_reduction_kw",
        "optimized_reduction_kw",
        "optimized_target_kw",
        "maintenance_risk",
        "required_reduction_kw",
        "factory_demand_kw",
        "available_grid_power_kw",
        "active_reduction_estimate_kw",
        "system_already_active_reduction_kw",
        "system_additional_achievable_reduction_kw",
        "system_selected_additional_reduction_kw",
        "system_projected_reduction_kw",
        "system_remaining_reduction_kw",
        "objective_cost",
        "production_loss_percent",
        "remaining_production_percent",
        "estimated_units_lost",
        "estimated_units_remaining",
        "estimated_energy_saved_kwh",
        "minimum_production_percent",
    ]

    for column in numeric_columns:
        if column not in df.columns:
            df[column] = 0.0

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        ).fillna(0.0)

    # ------------------------------------------------------------------------
    # Normalize categorical columns
    # ------------------------------------------------------------------------

    categorical_defaults = {
        "state": "RUNNING",
        "criticality": "MEDIUM",
        "controllability": "FIXED",
        "maintenance_label": "NONE",
        "maintenance_reason": "NORMAL",
        "optimization_action": "NO_ACTION",
        "optimization_status": "PROTECTED",
        "scenario_id": "UNKNOWN",
        "scenario_name": "UNKNOWN",
        "recommendation": "UNKNOWN",
    }

    for column, default in categorical_defaults.items():
        if column not in df.columns:
            df[column] = default

        df[column] = (
            df[column]
            .fillna(default)
            .astype(str)
            .map(clean)
        )

    # ------------------------------------------------------------------------
    # Normalize booleans
    # ------------------------------------------------------------------------

    for column, default in {
        "maintenance_trigger": False,
        "control_active": False,
        "below_normal_baseline": False,
        "production_safe": False,
        "safe_to_reduce": False,
    }.items():
        if column not in df.columns:
            df[column] = default

        df[column] = df[column].map(to_bool)

    # ------------------------------------------------------------------------
    # Derive active-control state carefully
    # ------------------------------------------------------------------------

    df["state"] = df["state"].map(clean)

    df["control_active"] = (
        df["control_active"].astype(bool)
        | df["state"].isin(ACTIVE_CONTROL_STATES)
    )

    # If optimizer explicitly supplied an active reduction estimate, use it
    # as another indication that control is already active.
    df["control_active"] = (
        df["control_active"]
        | (df["active_reduction_estimate_kw"] > EPS)
    )

    # ------------------------------------------------------------------------
    # Normalize machine IDs / timestamp
    # ------------------------------------------------------------------------

    if "machine_id" not in df.columns:
        raise ValueError(
            "optimization_output.csv does not contain machine_id."
        )

    df["machine_id"] = (
        df["machine_id"]
        .astype(str)
        .str.strip()
    )

    if "timestamp" not in df.columns:
        df["timestamp"] = int(time.time())

    return df


# ============================================================================
# SAFETY EVALUATION
# ============================================================================

def evaluate_machine(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate one machine decision.

    This function accepts a plain dict because ai_engine_node.py uses it
    directly. If production fields are missing, the latest production-impact
    row is loaded here as a second line of defense.
    """

    machine_id = safe_machine_id(
        row.get("machine_id", "")
    )

    state = clean(
        row.get("state", "RUNNING")
    )

    controllability = clean(
        row.get("controllability", "FIXED")
    )

    maintenance_label = clean(
        row.get("maintenance_label", "NONE")
    )

    maintenance_risk = to_float(
        row.get("maintenance_risk", 0.0),
        0.0,
    )

    maintenance_trigger = to_bool(
        row.get("maintenance_trigger", False)
    )

    control_active = (
        to_bool(
            row.get("control_active", False)
        )
        or state in ACTIVE_CONTROL_STATES
    )

    current_power_kw = to_float(
        row.get("current_power_kw", 0.0)
    )

    normal_target_kw = to_float(
        row.get("normal_target_kw", current_power_kw)
    )

    min_operating_power_kw = to_float(
        row.get("min_operating_power_kw", 0.0)
    )

    allowed_reduction_kw = max(
        0.0,
        to_float(
            row.get("allowed_reduction_kw", 0.0)
        ),
    )

    optimized_reduction_kw = max(
        0.0,
        to_float(
            row.get("optimized_reduction_kw", 0.0)
        ),
    )

    optimized_target_kw = to_float(
        row.get(
            "optimized_target_kw",
            current_power_kw,
        ),
        current_power_kw,
    )

    required_reduction_kw = max(
        0.0,
        to_float(
            row.get("required_reduction_kw", 0.0)
        ),
    )

    # ------------------------------------------------------------------------
    # Production evidence
    #
    # This is the root-cause fix:
    # optimization_output.csv currently lacks these fields, so when the AI
    # node passes only optimizer data we explicitly retrieve the latest
    # production-impact decision for this machine.
    # ------------------------------------------------------------------------

    has_production_safe = (
        "production_safe" in row
    )

    has_safe_to_reduce = (
        "safe_to_reduce" in row
    )

    production_safe = (
        to_bool(row.get("production_safe"))
        if has_production_safe
        else False
    )

    safe_to_reduce = (
        to_bool(row.get("safe_to_reduce"))
        if has_safe_to_reduce
        else False
    )

    production_loss_percent = to_float(
        row.get("production_loss_percent", 0.0)
    )

    remaining_production_percent = to_float(
        row.get("remaining_production_percent", 0.0)
    )

    estimated_units_lost = to_float(
        row.get("estimated_units_lost", 0.0)
    )

    estimated_energy_saved_kwh = to_float(
        row.get("estimated_energy_saved_kwh", 0.0)
    )

    production_recommendation = clean(
        row.get("recommendation", "UNKNOWN")
    )

    if (
        machine_id
        and (
            not has_production_safe
            or not has_safe_to_reduce
        )
    ):
        try:
            production = load_production_impact_latest()

            if not production.empty:
                match = production[
                    production["machine_id"].astype(str).str.strip()
                    == machine_id
                ]

                if not match.empty:
                    p = match.iloc[-1]

                    production_safe = to_bool(
                        p.get("production_safe", False)
                    )

                    safe_to_reduce = to_bool(
                        p.get("safe_to_reduce", False)
                    )

                    production_loss_percent = to_float(
                        p.get("production_loss_percent", 0.0)
                    )

                    remaining_production_percent = to_float(
                        p.get("remaining_production_percent", 0.0)
                    )

                    estimated_units_lost = to_float(
                        p.get("estimated_units_lost", 0.0)
                    )

                    estimated_energy_saved_kwh = to_float(
                        p.get("estimated_energy_saved_kwh", 0.0)
                    )

                    production_recommendation = clean(
                        p.get("recommendation", "UNKNOWN")
                    )
        except Exception:
            # Fail safe: retain False values for production safety.
            production_safe = False
            safe_to_reduce = False

    high_maintenance_risk = (
        maintenance_label in HIGH_RISK_LABELS
        or maintenance_risk >= 0.75
        or (
            maintenance_trigger
            and maintenance_risk >= 0.75
        )
    )

    below_normal_baseline = to_bool(
        row.get("below_normal_baseline", False)
    )

    fixed_machine = (
        controllability in FIXED_CONTROL_TYPES
    )

    production_constraint = not (
        production_safe
        and safe_to_reduce
    )

    # Requested reduction from optimizer.
    requested_reduction_kw = max(
        optimized_reduction_kw,
        max(
            0.0,
            current_power_kw
            - optimized_target_kw,
        ),
    )

    # Never approve more than the configured allowed reduction.
    validated_reduction_kw = min(
        requested_reduction_kw,
        allowed_reduction_kw,
    )

    if current_power_kw > min_operating_power_kw:
        physically_available_reduction_kw = (
            current_power_kw
            - min_operating_power_kw
        )
    else:
        physically_available_reduction_kw = 0.0

    validated_reduction_kw = min(
        validated_reduction_kw,
        physically_available_reduction_kw,
    )

    validated_target_kw = (
        current_power_kw
        - validated_reduction_kw
    )

    # ------------------------------------------------------------------------
    # RULE 1 + RULE 2:
    # Active reduction + high maintenance => RESTORE
    # ------------------------------------------------------------------------

    if (
        control_active
        and high_maintenance_risk
    ):
        command = {
            "machine_id": machine_id,
            "command": "RESTORE_NORMAL",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "RESTORE",
            "safety_status": "RESTORE_FOR_MAINTENANCE",
            "safety_reason": (
                "Machine is under active energy control while "
                "maintenance risk is HIGH. Restore normal operation."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 1:
    # Active control => HOLD to avoid repeated reduction.
    # ------------------------------------------------------------------------

    if control_active:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "ALREADY_CONTROLLED",
            "safety_reason": (
                "Machine is already under active energy control. "
                "No additional reduction is permitted."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 2:
    # New reduction blocked by high maintenance.
    # ------------------------------------------------------------------------

    if high_maintenance_risk:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "MAINTENANCE_RISK",
            "safety_reason": (
                "HIGH/CRITICAL maintenance risk blocks a new "
                "energy reduction command."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 4:
    # Fixed machines cannot be reduced.
    # ------------------------------------------------------------------------

    if fixed_machine:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "PROTECTED_FIXED_MACHINE",
            "safety_reason": (
                "Machine controllability is FIXED. "
                "Energy reduction is not permitted."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 5 + RULE 6:
    # Production constraints block reduction.
    # ------------------------------------------------------------------------

    if production_constraint:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "PROTECTED_PRODUCTION",
            "safety_reason": (
                "Production constraints do not allow reduction "
                f"(production_safe={production_safe}, "
                f"safe_to_reduce={safe_to_reduce})."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 7:
    # Below normal baseline => do not ask for further reduction.
    # ------------------------------------------------------------------------

    if below_normal_baseline:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "HOLD_BELOW_BASELINE",
            "safety_reason": (
                "Current power is already below the normal baseline."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 8:
    # No requested reduction => HOLD.
    # ------------------------------------------------------------------------

    if validated_reduction_kw <= EPS:
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "NO_SAFE_REDUCTION",
            "safety_reason": (
                "No positive validated reduction is available."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 9:
    # Target must be strictly below current power.
    # ------------------------------------------------------------------------

    if (
        validated_target_kw
        >= current_power_kw - EPS
    ):
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "INVALID_TARGET",
            "safety_reason": (
                "Validated reduction does not lower machine power."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # RULE 10:
    # Target cannot be below minimum operating power.
    # ------------------------------------------------------------------------

    if (
        validated_target_kw
        < min_operating_power_kw - EPS
    ):
        command = {
            "machine_id": machine_id,
            "command": "HOLD",
        }

        return {
            "timestamp": row.get("timestamp", int(time.time())),
            "machine_id": machine_id,
            "state": state,
            "current_power_kw": current_power_kw,
            "normal_target_kw": normal_target_kw,
            "min_operating_power_kw": min_operating_power_kw,
            "allowed_reduction_kw": allowed_reduction_kw,
            "requested_reduction_kw": requested_reduction_kw,
            "validated_reduction_kw": 0.0,
            "validated_target_kw": current_power_kw,
            "production_safe": production_safe,
            "safe_to_reduce": safe_to_reduce,
            "production_loss_percent": production_loss_percent,
            "remaining_production_percent": remaining_production_percent,
            "estimated_units_lost": estimated_units_lost,
            "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
            "production_recommendation": production_recommendation,
            "maintenance_risk": maintenance_risk,
            "maintenance_label": maintenance_label,
            "maintenance_trigger": maintenance_trigger,
            "criticality": clean(row.get("criticality", "MEDIUM")),
            "controllability": controllability,
            "control_active": control_active,
            "below_normal_baseline": below_normal_baseline,
            "safety_action": "HOLD",
            "safety_status": "MIN_POWER_VIOLATION",
            "safety_reason": (
                "Requested target would fall below the minimum "
                "operating power."
            ),
            "command": safe_json(command),
        }

    # ------------------------------------------------------------------------
    # APPROVAL:
    # All safety checks passed.
    # ------------------------------------------------------------------------

    command = {
        "machine_id": machine_id,
        "command": "REDUCE_LOAD",
        "target_kw": round(
            validated_target_kw,
            2,
        ),
        "duration_sec": int(
            to_float(
                row.get(
                    "duration_sec",
                    300,
                ),
                300,
            )
        ),
    }

    return {
        "timestamp": row.get("timestamp", int(time.time())),
        "machine_id": machine_id,
        "state": state,
        "current_power_kw": current_power_kw,
        "normal_target_kw": normal_target_kw,
        "min_operating_power_kw": min_operating_power_kw,
        "allowed_reduction_kw": allowed_reduction_kw,
        "requested_reduction_kw": requested_reduction_kw,
        "validated_reduction_kw": validated_reduction_kw,
        "validated_target_kw": validated_target_kw,
        "production_safe": production_safe,
        "safe_to_reduce": safe_to_reduce,
        "production_loss_percent": production_loss_percent,
        "remaining_production_percent": remaining_production_percent,
        "estimated_units_lost": estimated_units_lost,
        "estimated_energy_saved_kwh": estimated_energy_saved_kwh,
        "production_recommendation": production_recommendation,
        "maintenance_risk": maintenance_risk,
        "maintenance_label": maintenance_label,
        "maintenance_trigger": maintenance_trigger,
        "criticality": clean(row.get("criticality", "MEDIUM")),
        "controllability": controllability,
        "control_active": control_active,
        "below_normal_baseline": below_normal_baseline,
        "safety_action": "REDUCE",
        "safety_status": "APPROVED",
        "safety_reason": (
            "Production and maintenance constraints are satisfied "
            "and the target remains within operating limits."
        ),
        "command": safe_json(command),
    }


# ============================================================================
# DATAFRAME EVALUATION
# ============================================================================

def evaluate_dataframe(
    df: pd.DataFrame,
) -> pd.DataFrame:

    records = []

    for _, row in df.iterrows():
        records.append(
            evaluate_machine(
                row.to_dict()
            )
        )

    result = pd.DataFrame(
        records
    )

    if result.empty:
        raise ValueError(
            "No machine safety decisions were produced."
        )

    return result


# ============================================================================
# WRITE OUTPUT
# ============================================================================

def write_output(
    result: pd.DataFrame,
) -> None:

    result.to_csv(
        OUTPUT_PATH,
        index=False,
    )


# ============================================================================
# SUMMARY
# ============================================================================

def print_summary(
    result: pd.DataFrame,
) -> None:

    actions = (
        result["safety_action"]
        .value_counts()
        .to_dict()
    )

    print(
        "\n===== CONTROL SAFETY SUMMARY ====="
    )

    print(
        f"Machines evaluated : {len(result)}"
    )

    print(
        f"REDUCE             : {actions.get('REDUCE', 0)}"
    )

    print(
        f"HOLD               : {actions.get('HOLD', 0)}"
    )

    print(
        f"RESTORE            : {actions.get('RESTORE', 0)}"
    )

    print(
        "\n===== MACHINE DECISIONS ====="
    )

    display_columns = [
        "machine_id",
        "state",
        "current_power_kw",
        "optimized_target_kw",
        "production_safe",
        "safe_to_reduce",
        "maintenance_label",
        "safety_action",
        "safety_status",
        "safety_reason",
    ]

    display_columns = [
        c
        for c in display_columns
        if c in result.columns
    ]

    print(
        result[
            display_columns
        ].to_string(index=False)
    )


# ============================================================================
# STANDALONE TESTS
# ============================================================================

def run_standalone_tests() -> None:
    """
    Lightweight tests for the critical safety paths.
    """

    print(
        "\n===== STANDALONE SAFETY TESTS ====="
    )

    # ------------------------------------------------------------------------
    # NORMAL / fixed / safe / controllable examples
    # ------------------------------------------------------------------------

    normal_rows = [
        {
            "machine_id": "CNC_01",
            "state": "RUNNING",
            "current_power_kw": 27.64,
            "normal_target_kw": 27.0,
            "min_operating_power_kw": 20.0,
            "allowed_reduction_kw": 0.0,
            "optimized_reduction_kw": 0.0,
            "optimized_target_kw": 27.64,
            "maintenance_risk": 0.203,
            "maintenance_label": "LOW",
            "maintenance_trigger": False,
            "criticality": "HIGH",
            "controllability": "FIXED",
            "control_active": False,
            "below_normal_baseline": False,
            "production_safe": True,
            "safe_to_reduce": False,
        },
        {
            "machine_id": "COMP_01",
            "state": "RUNNING",
            "current_power_kw": 31.53,
            "normal_target_kw": 31.45,
            "min_operating_power_kw": 20.0,
            "allowed_reduction_kw": 3.75,
            "optimized_reduction_kw": 3.75,
            "optimized_target_kw": 27.70,
            "maintenance_risk": 0.440,
            "maintenance_label": "MEDIUM",
            "maintenance_trigger": False,
            "criticality": "MEDIUM",
            "controllability": "MODULATING",
            "control_active": False,
            "below_normal_baseline": False,
            "production_safe": True,
            "safe_to_reduce": True,
        },
    ]

    normal_result = pd.DataFrame(
        [
            evaluate_machine(r)
            for r in normal_rows
        ]
    )

    assert (
        normal_result.loc[
            normal_result["machine_id"] == "CNC_01",
            "safety_action",
        ].iloc[0]
        == "HOLD"
    )

    assert (
        normal_result.loc[
            normal_result["machine_id"] == "COMP_01",
            "safety_action",
        ].iloc[0]
        == "REDUCE"
    )

    # ------------------------------------------------------------------------
    # GRID_STRESS-style case:
    # CNC high-risk blocked, COMP/HVAC approved, pump blocked.
    # ------------------------------------------------------------------------

    stress_rows = [
        {
            "machine_id": "CNC_03",
            "state": "RUNNING",
            "current_power_kw": 26.44,
            "normal_target_kw": 26.40,
            "min_operating_power_kw": 20.0,
            "allowed_reduction_kw": 0.0,
            "optimized_reduction_kw": 0.0,
            "optimized_target_kw": 26.44,
            "maintenance_risk": 0.85,
            "maintenance_label": "HIGH",
            "maintenance_trigger": True,
            "criticality": "HIGH",
            "controllability": "FIXED",
            "control_active": False,
            "production_safe": True,
            "safe_to_reduce": False,
        },
        {
            "machine_id": "COMP_01",
            "state": "RUNNING",
            "current_power_kw": 31.53,
            "normal_target_kw": 31.45,
            "min_operating_power_kw": 20.0,
            "allowed_reduction_kw": 3.75,
            "optimized_reduction_kw": 3.75,
            "optimized_target_kw": 27.70,
            "maintenance_risk": 0.44,
            "maintenance_label": "MEDIUM",
            "maintenance_trigger": False,
            "criticality": "MEDIUM",
            "controllability": "MODULATING",
            "control_active": False,
            "production_safe": True,
            "safe_to_reduce": True,
        },
        {
            "machine_id": "HVAC_01",
            "state": "RUNNING",
            "current_power_kw": 16.95,
            "normal_target_kw": 16.72,
            "min_operating_power_kw": 8.0,
            "allowed_reduction_kw": 5.0,
            "optimized_reduction_kw": 5.0,
            "optimized_target_kw": 11.72,
            "maintenance_risk": 0.379,
            "maintenance_label": "LOW",
            "maintenance_trigger": False,
            "criticality": "LOW",
            "controllability": "CURTAILABLE",
            "control_active": False,
            "production_safe": True,
            "safe_to_reduce": True,
        },
        {
            "machine_id": "PUMP_01",
            "state": "RUNNING",
            "current_power_kw": 12.15,
            "normal_target_kw": 12.30,
            "min_operating_power_kw": 8.0,
            "allowed_reduction_kw": 0.0,
            "optimized_reduction_kw": 0.0,
            "optimized_target_kw": 12.15,
            "maintenance_risk": 0.492,
            "maintenance_label": "MEDIUM",
            "maintenance_trigger": False,
            "criticality": "MEDIUM",
            "controllability": "MODULATING",
            "control_active": False,
            "production_safe": False,
            "safe_to_reduce": False,
        },
    ]

    stress_result = pd.DataFrame(
        [
            evaluate_machine(r)
            for r in stress_rows
        ]
    )

    actions = dict(
        zip(
            stress_result["machine_id"],
            stress_result["safety_action"],
        )
    )

    assert actions["CNC_03"] == "HOLD"
    assert actions["COMP_01"] == "REDUCE"
    assert actions["HVAC_01"] == "REDUCE"
    assert actions["PUMP_01"] == "HOLD"

    # ------------------------------------------------------------------------
    # Restore test
    # ------------------------------------------------------------------------

    restore_row = {
        "machine_id": "HVAC_01",
        "state": "REDUCED",
        "current_power_kw": 12.0,
        "normal_target_kw": 16.72,
        "min_operating_power_kw": 8.0,
        "allowed_reduction_kw": 5.0,
        "optimized_reduction_kw": 5.0,
        "optimized_target_kw": 11.72,
        "maintenance_risk": 0.92,
        "maintenance_label": "HIGH",
        "maintenance_trigger": True,
        "criticality": "LOW",
        "controllability": "CURTAILABLE",
        "control_active": True,
        "below_normal_baseline": False,
        "production_safe": True,
        "safe_to_reduce": True,
    }

    restore_result = evaluate_machine(
        restore_row
    )

    assert (
        restore_result["safety_action"]
        == "RESTORE"
    )

    assert (
        restore_result["safety_status"]
        == "RESTORE_FOR_MAINTENANCE"
    )

    print(
        "All standalone safety tests PASSED."
    )


# ============================================================================
# MAIN
# ============================================================================

def main() -> None:

    print(
        "INDUS_TWIN CONTROL SAFETY VALIDATOR"
    )

    print(
        f"Optimization source : {OPTIMIZATION_PATH}"
    )

    print(
        f"Maintenance source  : {MAINTENANCE_PATH}"
    )

    print(
        f"Production source   : {PRODUCTION_IMPACT_PATH}"
    )

    print(
        f"Output              : {OUTPUT_PATH}"
    )

    run_standalone_tests()

    (
        optimization,
        maintenance,
        production,
    ) = load_inputs()

    prepared = prepare(
        optimization,
        maintenance,
        production,
    )

    result = evaluate_dataframe(
        prepared
    )

    write_output(
        result
    )

    print_summary(
        result
    )

    print(
        f"\nSafety decision file written to:\n{OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
