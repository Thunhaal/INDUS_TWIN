from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

OPS_DIR = DATA_DIR / "02_operations"
FACTORY_DIR = DATA_DIR / "01_factory"
GRID_DIR = DATA_DIR / "04_grid"
SCENARIO_DIR = DATA_DIR / "05_scenarios"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"

BASELINE_FILE = BASE_DIR / "baseline_output.csv"
ANOMALY_FILE = BASE_DIR / "anomaly_output.csv"
MAINT_FILE = BASE_DIR / "maintenance_output.csv"
PRODUCTION_IMPACT_FILE = BASE_DIR / "production_impact_output.csv"
FLEXIBILITY_FILE = BASE_DIR / "flexibility_output.csv"
FORECAST_FILE = BASE_DIR / "forecast_output.csv"

AI_FEATURES_FILE = DATA_DIR / "06_ai" / "ai_features.csv"

GRID_FILE = GRID_DIR / "grid_data.csv"
SCENARIO_FILE = SCENARIO_DIR / "scenario_data.csv"

OUT_FILE = BASE_DIR / "final_decision_output.csv"


# ============================================================
# SETTINGS
# ============================================================

EPS = 1e-6

DEFAULT_REQUIRED_REDUCTION_KW = 0.0

# Minimum confidence used before automatically recommending
# an anomaly-based reduction.
MIN_ANOMALY_CONFIDENCE = 0.50


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Load CSV safely and normalize column names."""

    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        df.columns = [
            str(c).strip()
            for c in df.columns
        ]
        return df

    except Exception as exc:
        print(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def numeric(
    df: pd.DataFrame,
    column: str,
    default: float = np.nan
) -> pd.Series:
    """Return numeric series."""

    if column not in df.columns:
        return pd.Series(
            default,
            index=df.index,
            dtype=float
        )

    return pd.to_numeric(
        df[column],
        errors="coerce"
    )


def latest_by_machine(
    df: pd.DataFrame,
    timestamp_column: str = "timestamp"
) -> pd.DataFrame:
    """Return the latest record for each machine."""

    if df.empty or "machine_id" not in df.columns:
        return pd.DataFrame()

    out = df.copy()

    out["machine_id"] = (
        out["machine_id"]
        .astype(str)
        .str.strip()
    )

    if timestamp_column in out.columns:

        out[timestamp_column] = pd.to_numeric(
            out[timestamp_column],
            errors="coerce"
        )

        out = (
            out
            .dropna(subset=[timestamp_column])
            .sort_values(
                [
                    "machine_id",
                    timestamp_column
                ]
            )
        )

    return (
        out
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .reset_index(drop=True)
    )


def safe_float(
    value,
    default: float = 0.0
) -> float:

    try:

        if value is None or pd.isna(value):
            return default

        value = float(value)

        if not np.isfinite(value):
            return default

        return value

    except (TypeError, ValueError):
        return default


def text_value(
    value,
    default: str = "UNKNOWN"
) -> str:

    if value is None or pd.isna(value):
        return default

    text = str(value).strip()

    if not text:
        return default

    return text


# ============================================================
# GRID CONTEXT
# ============================================================

def load_grid_context() -> dict:

    grid = load_csv(
        GRID_FILE
    )

    if grid.empty or "timestamp" not in grid.columns:

        return {
            "grid_status": "UNKNOWN",
            "grid_stress_level": 0.0,
            "factory_demand_kw": 0.0,
            "available_grid_power_kw": 0.0,
            "grid_import_limit_kw": 0.0,
            "required_reduction_kw": 0.0,
            "solar_available_kw": 0.0,
            "battery_available_power_kw": 0.0,
            "electricity_tariff_rs_kwh": 0.0
        }

    grid["timestamp"] = pd.to_numeric(
        grid["timestamp"],
        errors="coerce"
    )

    grid = (
        grid
        .dropna(subset=["timestamp"])
        .sort_values("timestamp")
    )

    if grid.empty:

        return {
            "grid_status": "UNKNOWN",
            "grid_stress_level": 0.0,
            "factory_demand_kw": 0.0,
            "available_grid_power_kw": 0.0,
            "grid_import_limit_kw": 0.0,
            "required_reduction_kw": 0.0,
            "solar_available_kw": 0.0,
            "battery_available_power_kw": 0.0,
            "electricity_tariff_rs_kwh": 0.0
        }

    latest = grid.iloc[-1]

    required_reduction = safe_float(
        latest.get(
            "required_reduction_kw"
        ),
        0.0
    )

    return {
        "grid_status": text_value(
            latest.get(
                "grid_status"
            ),
            "UNKNOWN"
        ),
        "grid_stress_level": safe_float(
            latest.get(
                "grid_stress_level"
            ),
            0.0
        ),
        "factory_demand_kw": safe_float(
            latest.get(
                "factory_demand_kw"
            ),
            0.0
        ),
        "available_grid_power_kw": safe_float(
            latest.get(
                "available_grid_power_kw"
            ),
            0.0
        ),
        "grid_import_limit_kw": safe_float(
            latest.get(
                "grid_import_limit_kw"
            ),
            0.0
        ),
        "required_reduction_kw": required_reduction,
        "solar_available_kw": safe_float(
            latest.get(
                "solar_available_kw"
            ),
            0.0
        ),
        "battery_available_power_kw": safe_float(
            latest.get(
                "battery_available_power_kw"
            ),
            0.0
        ),
        "electricity_tariff_rs_kwh": safe_float(
            latest.get(
                "electricity_tariff_rs_kwh"
            ),
            0.0
        )
    }


# ============================================================
# SCENARIO CONTEXT
# ============================================================

def load_scenario_context() -> dict:

    scenario = load_csv(
        SCENARIO_FILE
    )

    if scenario.empty or "timestamp" not in scenario.columns:

        return {
            "scenario_id": "UNKNOWN",
            "scenario_name": "Unknown",
            "scenario_type": "UNKNOWN",
            "scenario_status": "UNKNOWN"
        }

    scenario["timestamp"] = pd.to_numeric(
        scenario["timestamp"],
        errors="coerce"
    )

    scenario = (
        scenario
        .dropna(subset=["timestamp"])
        .sort_values("timestamp")
    )

    if scenario.empty:

        return {
            "scenario_id": "UNKNOWN",
            "scenario_name": "Unknown",
            "scenario_type": "UNKNOWN",
            "scenario_status": "UNKNOWN"
        }

    latest = scenario.iloc[-1]

    return {
        "scenario_id": text_value(
            latest.get(
                "scenario_id"
            ),
            "UNKNOWN"
        ),
        "scenario_name": text_value(
            latest.get(
                "scenario_name"
            ),
            "Unknown"
        ),
        "scenario_type": text_value(
            latest.get(
                "scenario_type"
            ),
            "UNKNOWN"
        ).upper(),
        "scenario_status": text_value(
            latest.get(
                "status"
            ),
            "UNKNOWN"
        ).upper()
    }


# ============================================================
# MAIN DECISION ENGINE
# ============================================================

def compute_final_decision(
    telemetry_df: pd.DataFrame | None = None,
    baseline_df: pd.DataFrame | None = None,
    anomalies_df: pd.DataFrame | None = None,
    maintenance_df: pd.DataFrame | None = None,
    production_impact_df: pd.DataFrame | None = None,
    flexibility_df: pd.DataFrame | None = None,
    forecast_df: pd.DataFrame | None = None,
    features_df: pd.DataFrame | None = None
) -> pd.DataFrame:

    # ========================================================
    # 1. LOAD
    # ========================================================

    if telemetry_df is None:
        telemetry_df = load_csv(
            TELEMETRY_FILE
        )

    if telemetry_df.empty:
        raise FileNotFoundError(
            "No telemetry available."
        )

    if baseline_df is None:
        baseline_df = load_csv(
            BASELINE_FILE
        )

    if anomalies_df is None:
        anomalies_df = load_csv(
            ANOMALY_FILE
        )

    if maintenance_df is None:
        maintenance_df = load_csv(
            MAINT_FILE
        )

    if production_impact_df is None:
        production_impact_df = load_csv(
            PRODUCTION_IMPACT_FILE
        )

    if flexibility_df is None:
        flexibility_df = load_csv(
            FLEXIBILITY_FILE
        )

    if forecast_df is None:
        forecast_df = load_csv(
            FORECAST_FILE
        )

    if features_df is None:
        features_df = load_csv(
            AI_FEATURES_FILE
        )

    # ========================================================
    # 2. LATEST TELEMETRY
    # ========================================================

    telemetry = latest_by_machine(
        telemetry_df
    )

    if telemetry.empty:
        return pd.DataFrame()

    telemetry["actual_power_kw"] = numeric(
        telemetry,
        "power_kw",
        default=0.0
    ).fillna(0.0)

    if "state" not in telemetry.columns:
        telemetry["state"] = "UNKNOWN"

    telemetry["state"] = (
        telemetry["state"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
    )

    # ========================================================
    # 3. LATEST OUTPUTS FROM EACH AI MODULE
    # ========================================================

    baseline = latest_by_machine(
        baseline_df,
        timestamp_column="timestamp"
        if "timestamp" in baseline_df.columns
        else "machine_id"
    )

    anomalies = latest_by_machine(
        anomalies_df
    )

    maintenance = latest_by_machine(
        maintenance_df
    )

    production_impact = latest_by_machine(
        production_impact_df
    )

    flexibility = latest_by_machine(
        flexibility_df
    )

    forecast = latest_by_machine(
        forecast_df
    )

    # ========================================================
    # 4. MERGE BASELINE
    # ========================================================

    if not baseline.empty:

        baseline_columns = [
            "machine_id",
            "state",
            "expected_power_kw"
        ]

        baseline_columns = [
            c
            for c in baseline_columns
            if c in baseline.columns
        ]

        baseline_for_merge = (
            baseline[
                baseline_columns
            ]
            .drop_duplicates(
                subset=["machine_id"],
                keep="last"
            )
        )

        # If baseline contains state, merge it only by machine
        # here because telemetry already represents the current
        # state. We then validate state compatibility below.
        telemetry = telemetry.merge(
            baseline_for_merge[
                [
                    c
                    for c in baseline_for_merge.columns
                    if c != "state"
                ]
            ],
            on="machine_id",
            how="left"
        )

    # ========================================================
    # 5. EXPECTED POWER
    # ========================================================

    telemetry["expected_power_kw"] = numeric(
        telemetry,
        "expected_power_kw"
    )

    telemetry["expected_power_kw"] = (
        telemetry["expected_power_kw"]
        .fillna(
            telemetry["actual_power_kw"]
        )
    )

    telemetry["deviation_kw"] = (
        telemetry["actual_power_kw"]
        - telemetry["expected_power_kw"]
    )

    telemetry["deviation_percent"] = (
        telemetry["deviation_kw"]
        / (
            telemetry["expected_power_kw"].abs()
            + EPS
        )
    ) * 100.0

    # ========================================================
    # 6. ANOMALY OUTPUT
    # ========================================================

    if not anomalies.empty:

        anomaly_columns = [
            "machine_id",
            "anomaly",
            "anomaly_type",
            "severity",
            "confidence",
            "detection_reason"
        ]

        anomaly_columns = [
            c
            for c in anomaly_columns
            if c in anomalies.columns
        ]

        telemetry = telemetry.merge(
            anomalies[
                anomaly_columns
            ],
            on="machine_id",
            how="left"
        )

    if "anomaly" not in telemetry.columns:
        telemetry["anomaly"] = False

    if "anomaly_type" not in telemetry.columns:
        telemetry["anomaly_type"] = "NORMAL"

    if "severity" not in telemetry.columns:
        telemetry["severity"] = "NONE"

    if "confidence" not in telemetry.columns:
        telemetry["confidence"] = 0.0

    telemetry["anomaly"] = (
        telemetry["anomaly"]
        .fillna(False)
        .astype(bool)
    )

    telemetry["confidence"] = numeric(
        telemetry,
        "confidence",
        default=0.0
    ).fillna(0.0).clip(
        0.0,
        1.0
    )

    # ========================================================
    # 7. MAINTENANCE
    # ========================================================

    if not maintenance.empty:

        maintenance_columns = [
            "machine_id",
            "maintenance_risk",
            "maintenance_label",
            "maintenance_trigger",
            "maintenance_confidence",
            "maintenance_reason"
        ]

        maintenance_columns = [
            c
            for c in maintenance_columns
            if c in maintenance.columns
        ]

        telemetry = telemetry.merge(
            maintenance[
                maintenance_columns
            ],
            on="machine_id",
            how="left"
        )

    if "maintenance_risk" not in telemetry.columns:
        telemetry["maintenance_risk"] = 0.0

    if "maintenance_label" not in telemetry.columns:
        telemetry["maintenance_label"] = "NONE"

    if "maintenance_trigger" not in telemetry.columns:
        telemetry["maintenance_trigger"] = False

    if "maintenance_reason" not in telemetry.columns:
        telemetry["maintenance_reason"] = "NORMAL"

    telemetry["maintenance_risk"] = numeric(
        telemetry,
        "maintenance_risk",
        default=0.0
    ).fillna(0.0).clip(
        0.0,
        1.0
    )

    telemetry["maintenance_trigger"] = (
        telemetry["maintenance_trigger"]
        .fillna(False)
        .astype(bool)
    )

    # ========================================================
    # 8. PRODUCTION IMPACT
    # ========================================================

    if not production_impact.empty:

        production_columns = [
            "machine_id",
            "feasible_reduce_kw",
            "production_loss_percent",
            "remaining_production_percent",
            "estimated_energy_saved_kwh",
            "production_safe",
            "safe_to_reduce",
            "recommendation"
        ]

        production_columns = [
            c
            for c in production_columns
            if c in production_impact.columns
        ]

        telemetry = telemetry.merge(
            production_impact[
                production_columns
            ],
            on="machine_id",
            how="left"
        )

    if "feasible_reduce_kw" not in telemetry.columns:
        telemetry["feasible_reduce_kw"] = 0.0

    if "production_loss_percent" not in telemetry.columns:
        telemetry["production_loss_percent"] = np.nan

    if "remaining_production_percent" not in telemetry.columns:
        telemetry["remaining_production_percent"] = np.nan

    if "production_safe" not in telemetry.columns:
        telemetry["production_safe"] = False

    telemetry["feasible_reduce_kw"] = numeric(
        telemetry,
        "feasible_reduce_kw",
        default=0.0
    ).fillna(0.0).clip(
        lower=0.0
    )

    telemetry["production_safe"] = (
        telemetry["production_safe"]
        .fillna(False)
        .astype(bool)
    )

    # ========================================================
    # 9. FLEXIBILITY
    # ========================================================

    if not flexibility.empty:

        flexibility_columns = [
            "machine_id",
            "physical_flexibility_kw",
            "safe_flexibility_kw",
            "deployable_flexibility_kw",
            "flexible_energy_reserve_kwh",
            "deployment_status",
            "total_deployable_flexibility_kw",
            "reserve_margin_kw",
            "reserve_status",
            "recommended_reduction_kw"
        ]

        flexibility_columns = [
            c
            for c in flexibility_columns
            if c in flexibility.columns
        ]

        telemetry = telemetry.merge(
            flexibility[
                flexibility_columns
            ],
            on="machine_id",
            how="left"
        )

    # Defaults
    for col in [
        "physical_flexibility_kw",
        "safe_flexibility_kw",
        "deployable_flexibility_kw",
        "flexible_energy_reserve_kwh",
        "recommended_reduction_kw"
    ]:

        if col not in telemetry.columns:
            telemetry[col] = 0.0

        telemetry[col] = numeric(
            telemetry,
            col,
            default=0.0
        ).fillna(0.0).clip(
            lower=0.0
        )

    if "deployment_status" not in telemetry.columns:
        telemetry["deployment_status"] = "UNKNOWN"

    # ========================================================
    # 10. FORECAST
    # ========================================================

    if not forecast.empty:

        forecast_columns = [
            "machine_id",
            "pred_15min",
            "pred_30min",
            "pred_60min",
            "forecast_change_60min_kw"
        ]

        forecast_columns = [
            c
            for c in forecast_columns
            if c in forecast.columns
        ]

        telemetry = telemetry.merge(
            forecast[
                forecast_columns
            ],
            on="machine_id",
            how="left"
        )

    for col in [
        "pred_15min",
        "pred_30min",
        "pred_60min",
        "forecast_change_60min_kw"
    ]:

        if col not in telemetry.columns:
            telemetry[col] = np.nan

        telemetry[col] = numeric(
            telemetry,
            col
        )

    # ========================================================
    # 11. FEATURES
    # ========================================================

    if not features_df.empty:

        features = latest_by_machine(
            features_df
        )

        feature_columns = [
            "machine_id",
            "power_to_baseline_ratio",
            "excess_power_kw",
            "grid_capacity_ratio"
        ]

        feature_columns = [
            c
            for c in feature_columns
            if c in features.columns
        ]

        if len(feature_columns) > 1:

            telemetry = telemetry.merge(
                features[
                    feature_columns
                ],
                on="machine_id",
                how="left"
            )

    for col in [
        "power_to_baseline_ratio",
        "excess_power_kw",
        "grid_capacity_ratio"
    ]:

        if col not in telemetry.columns:
            telemetry[col] = np.nan

    # ========================================================
    # 12. GRID + SCENARIO CONTEXT
    # ========================================================

    grid = load_grid_context()
    scenario = load_scenario_context()

    telemetry["grid_status"] = (
        grid["grid_status"]
    )

    telemetry["grid_stress_level"] = (
        grid["grid_stress_level"]
    )

    telemetry["factory_demand_kw"] = (
        grid["factory_demand_kw"]
    )

    telemetry["available_grid_power_kw"] = (
        grid["available_grid_power_kw"]
    )

    telemetry["grid_import_limit_kw"] = (
        grid["grid_import_limit_kw"]
    )

    telemetry["required_reduction_kw"] = (
        grid["required_reduction_kw"]
    )

    telemetry["solar_available_kw"] = (
        grid["solar_available_kw"]
    )

    telemetry["battery_available_power_kw"] = (
        grid["battery_available_power_kw"]
    )

    telemetry["electricity_tariff_rs_kwh"] = (
        grid["electricity_tariff_rs_kwh"]
    )

    telemetry["scenario_id"] = (
        scenario["scenario_id"]
    )

    telemetry["scenario_name"] = (
        scenario["scenario_name"]
    )

    telemetry["scenario_type"] = (
        scenario["scenario_type"]
    )

    telemetry["scenario_status"] = (
        scenario["scenario_status"]
    )

    # ========================================================
    # 13. TARGET REDUCTION
    # ========================================================

    required_reduction = max(
        0.0,
        safe_float(
            grid["required_reduction_kw"],
            DEFAULT_REQUIRED_REDUCTION_KW
        )
    )

    telemetry["required_reduction_kw"] = (
        required_reduction
    )

    # ========================================================
    # 14. PRIORITY / DECISION SCORE
    #
    # This is an internal decision score, NOT a public ranking
    # of machines. It is used only to determine which machine
    # records satisfy the current control conditions.
    # ========================================================

    flexibility_component = (
        telemetry["deployable_flexibility_kw"]
        / (
            telemetry[
                "deployable_flexibility_kw"
            ].max()
            + EPS
        )
    )

    anomaly_component = np.where(
        telemetry["anomaly"],
        telemetry["confidence"],
        0.0
    )

    maintenance_component = (
        telemetry["maintenance_risk"]
    )

    energy_waste_component = (
        telemetry["excess_power_kw"]
        .fillna(0.0)
        .clip(lower=0.0)
    )

    energy_waste_component = (
        energy_waste_component
        / (
            energy_waste_component.max()
            + EPS
        )
    )

    # Machines with HIGH criticality should be less likely to
    # be selected for demand response.
    criticality_text = (
        telemetry.get(
            "criticality",
            pd.Series(
                "UNKNOWN",
                index=telemetry.index
            )
        )
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
    )

    criticality_protection = np.select(
        [
            criticality_text.eq("HIGH"),
            criticality_text.eq("MEDIUM"),
            criticality_text.eq("LOW")
        ],
        [
            0.00,
            0.50,
            1.00
        ],
        default=0.50
    )

    telemetry["decision_score"] = (
        flexibility_component * 0.40
        +
        anomaly_component * 0.20
        +
        maintenance_component * 0.10
        +
        energy_waste_component * 0.20
        +
        criticality_protection * 0.10
    )

    # ========================================================
    # 15. DECISION LOGIC
    # ========================================================

    def make_decision(
        row: pd.Series
    ) -> str:

        anomaly = bool(
            row["anomaly"]
        )

        confidence = safe_float(
            row["confidence"],
            0.0
        )

        maintenance_risk = safe_float(
            row["maintenance_risk"],
            0.0
        )

        deployable = safe_float(
            row["deployable_flexibility_kw"],
            0.0
        )

        required = required_reduction

        scenario_type = str(
            row["scenario_type"]
        ).upper()

        # ----------------------------------------------------
        # Safety first: maintenance risk
        # ----------------------------------------------------

        if maintenance_risk >= 0.70:

            if deployable > EPS:

                return (
                    "HOLD — MAINTENANCE RISK HIGH"
                )

            return (
                "INSPECT — MAINTENANCE RISK HIGH"
            )

        # ----------------------------------------------------
        # Safety: strong anomaly
        # ----------------------------------------------------

        if (
            anomaly
            and confidence >= MIN_ANOMALY_CONFIDENCE
        ):

            anomaly_type = str(
                row["anomaly_type"]
            ).upper()

            if anomaly_type in [
                "TEMPERATURE_ANOMALY",
                "VIBRATION_ANOMALY",
                "SEVERE_OVERLOAD",
                "OVERLOAD"
            ]:

                return (
                    "PROTECT / INSPECT — "
                    f"{anomaly_type}"
                )

            if (
                anomaly_type == "OVERCONSUMPTION"
                and deployable > EPS
            ):

                if required > EPS:

                    return (
                        f"REDUCE {min(deployable, required):.2f} kW"
                    )

                return (
                    f"REDUCE {deployable:.2f} kW"
                )

        # ----------------------------------------------------
        # Grid demand response
        # ----------------------------------------------------

        if required > EPS:

            if deployable > EPS:

                reduction = min(
                    deployable,
                    required
                )

                return (
                    f"GRID RESPONSE — "
                    f"REDUCE {reduction:.2f} kW"
                )

            return (
                "GRID RESPONSE — "
                "NO SAFE FLEXIBILITY"
            )

        # ----------------------------------------------------
        # Scenario-driven opportunity
        # ----------------------------------------------------

        if scenario_type in [
            "PEAK_DEMAND",
            "LOW_RENEWABLE"
        ]:

            if deployable > EPS:

                return (
                    f"PROACTIVE FLEX — "
                    f"{deployable:.2f} kW"
                )

        # ----------------------------------------------------
        # Energy waste
        # ----------------------------------------------------

        if (
            safe_float(
                row["excess_power_kw"],
                0.0
            ) > EPS
            and
            deployable > EPS
        ):

            return (
                f"EFFICIENCY ACTION — "
                f"REDUCE {deployable:.2f} kW"
            )

        # ----------------------------------------------------
        # Flexibility available but no current request
        # ----------------------------------------------------

        if deployable > EPS:

            return (
                f"FLEX AVAILABLE — "
                f"{deployable:.2f} kW"
            )

        # ----------------------------------------------------
        # Normal
        # ----------------------------------------------------

        return "MONITOR"

    telemetry["recommended_action"] = (
        telemetry.apply(
            make_decision,
            axis=1
        )
    )

    # ========================================================
    # 16. SYSTEM-LEVEL ACTION
    # ========================================================

    total_deployable = safe_float(
        telemetry[
            "deployable_flexibility_kw"
        ].sum(),
        0.0
    )

    reserve_margin = (
        total_deployable
        - required_reduction
    )

    if required_reduction <= EPS:

        system_action = (
            "NO GRID RESPONSE REQUIRED"
        )

    elif total_deployable + EPS >= required_reduction:

        system_action = (
            f"SUFFICIENT FLEXIBILITY — "
            f"{required_reduction:.2f} kW TARGET"
        )

    else:

        system_action = (
            f"INSUFFICIENT FLEXIBILITY — "
            f"{required_reduction:.2f} kW REQUIRED, "
            f"{total_deployable:.2f} kW AVAILABLE"
        )

    telemetry["system_total_deployable_kw"] = (
        total_deployable
    )

    telemetry["system_required_reduction_kw"] = (
        required_reduction
    )

    telemetry["system_reserve_margin_kw"] = (
        reserve_margin
    )

    telemetry["system_action"] = (
        system_action
    )

    # ========================================================
    # 17. FINAL OUTPUT
    # ========================================================

    output_columns = [
        "timestamp",
        "machine_id",

        "state",

        "actual_power_kw",
        "expected_power_kw",
        "deviation_kw",
        "deviation_percent",

        "anomaly",
        "anomaly_type",
        "severity",
        "confidence",
        "detection_reason",

        "maintenance_risk",
        "maintenance_label",
        "maintenance_trigger",
        "maintenance_confidence",
        "maintenance_reason",

        "physical_flexibility_kw",
        "safe_flexibility_kw",
        "deployable_flexibility_kw",
        "flexible_energy_reserve_kwh",
        "deployment_status",

        "feasible_reduce_kw",
        "production_loss_percent",
        "remaining_production_percent",
        "production_safe",

        "pred_15min",
        "pred_30min",
        "pred_60min",
        "forecast_change_60min_kw",

        "excess_power_kw",

        "grid_status",
        "grid_stress_level",
        "factory_demand_kw",
        "available_grid_power_kw",
        "grid_import_limit_kw",
        "required_reduction_kw",

        "solar_available_kw",
        "battery_available_power_kw",
        "electricity_tariff_rs_kwh",

        "scenario_id",
        "scenario_name",
        "scenario_type",
        "scenario_status",

        "decision_score",
        "recommended_action",

        "system_total_deployable_kw",
        "system_required_reduction_kw",
        "system_reserve_margin_kw",
        "system_action"
    ]

    output_columns = [
        c
        for c in output_columns
        if c in telemetry.columns
    ]

    out = telemetry[
        output_columns
    ].copy()

    # ========================================================
    # 18. CLEAN OUTPUT
    # ========================================================

    out = out.replace(
        [np.inf, -np.inf],
        np.nan
    )

    out = out.sort_values(
        "machine_id"
    ).reset_index(drop=True)

    # ========================================================
    # 19. SAVE
    # ========================================================

    Path(
        OUT_FILE
    ).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    out.to_csv(
        OUT_FILE,
        index=False
    )

    # ========================================================
    # 20. SUMMARY
    # ========================================================

    print(
        f"\nSaved FINAL DECISION -> "
        f"{OUT_FILE}"
    )

    print(
        f"Machines analysed: "
        f"{len(out)}"
    )

    print(
        f"Grid status: "
        f"{grid['grid_status']}"
    )

    print(
        f"Grid stress: "
        f"{grid['grid_stress_level']:.2f}"
    )

    print(
        f"Factory demand: "
        f"{grid['factory_demand_kw']:.2f} kW"
    )

    print(
        f"Required reduction: "
        f"{required_reduction:.2f} kW"
    )

    print(
        f"Deployable flexibility: "
        f"{total_deployable:.2f} kW"
    )

    print(
        f"Reserve margin: "
        f"{reserve_margin:.2f} kW"
    )

    print(
        f"System action: "
        f"{system_action}"
    )

    print(
        "\n=== MACHINE DECISIONS ==="
    )

    print(
        out[
            [
                "machine_id",
                "actual_power_kw",
                "anomaly_type",
                "maintenance_label",
                "deployable_flexibility_kw",
                "recommended_action"
            ]
        ].to_string(
            index=False
        )
    )

    return out


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    compute_final_decision()