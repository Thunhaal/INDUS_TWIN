from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

OPS_DIR = DATA_DIR / "02_operations"
FACTORY_DIR = DATA_DIR / "01_factory"
MAINT_DIR = DATA_DIR / "03_maintenance"
GRID_DIR = DATA_DIR / "04_grid"
SCENARIO_DIR = DATA_DIR / "05_scenarios"
AI_DIR = DATA_DIR / "06_ai"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = OPS_DIR / "production_data.csv"
MACHINE_METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"
MACHINE_CONSTRAINTS_FILE = FACTORY_DIR / "machine_constraints.csv"
GRID_FILE = GRID_DIR / "grid_data.csv"
SCENARIO_FILE = SCENARIO_DIR / "scenario_data.csv"

OUT_FILE = AI_DIR / "ai_features.csv"

EPS = 1e-6


# ============================================================
# FILE HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV safely and normalize column names."""
    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        df.columns = [
            str(col).strip()
            for col in df.columns
        ]
        return df
    except Exception as exc:
        print(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def to_numeric(
    df: pd.DataFrame,
    columns: list[str],
    default: float | None = np.nan
) -> pd.DataFrame:
    """Convert columns to numeric. Create missing columns."""
    for col in columns:
        if col not in df.columns:
            df[col] = default

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    return df


def clean_machine_id(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize machine IDs."""
    if "machine_id" in df.columns:
        df["machine_id"] = (
            df["machine_id"]
            .astype(str)
            .str.strip()
        )

    return df


def ensure_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """Convert timestamp to numeric seconds."""
    if "timestamp" not in df.columns:
        df["timestamp"] = np.nan

    df["timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="coerce"
    )

    return df


def global_asof_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    on: str = "timestamp",
    by: str | None = None,
    tolerance: int = 60,
    suffixes: tuple[str, str] = ("", "_right")
) -> pd.DataFrame:
    """
    Robust merge_asof helper.

    merge_asof requires the time key to be globally sorted.
    We therefore sort by timestamp first, optionally machine_id
    second, perform the merge, then restore caller ordering.
    """

    left = left.copy()
    right = right.copy()

    left = ensure_timestamp(left)
    right = ensure_timestamp(right)

    left = left.dropna(subset=[on]).copy()
    right = right.dropna(subset=[on]).copy()

    if by is not None:
        left = clean_machine_id(left)
        right = clean_machine_id(right)

        left = left.sort_values(
            [on, by]
        ).reset_index(drop=True)

        right = right.sort_values(
            [on, by]
        ).reset_index(drop=True)
    else:
        left = left.sort_values(
            [on]
        ).reset_index(drop=True)

        right = right.sort_values(
            [on]
        ).reset_index(drop=True)

    merged = pd.merge_asof(
        left,
        right,
        on=on,
        by=by,
        direction="nearest",
        tolerance=tolerance,
        suffixes=suffixes
    )

    return merged


# ============================================================
# MAIN
# ============================================================

def compute_features() -> pd.DataFrame:

    # ========================================================
    # 1. LOAD DATA
    # ========================================================

    telemetry = load_csv(
        TELEMETRY_FILE
    )

    if telemetry.empty:
        print(
            "Telemetry file missing or empty:"
            f" {TELEMETRY_FILE}"
        )
        return pd.DataFrame()

    production = load_csv(
        PRODUCTION_FILE
    )

    metadata = load_csv(
        MACHINE_METADATA_FILE
    )

    constraints = load_csv(
        MACHINE_CONSTRAINTS_FILE
    )

    grid = load_csv(
        GRID_FILE
    )

    scenarios = load_csv(
        SCENARIO_FILE
    )

    # ========================================================
    # 2. NORMALIZE TELEMETRY
    # ========================================================

    telemetry = ensure_timestamp(
        telemetry
    )

    telemetry = clean_machine_id(
        telemetry
    )

    telemetry = to_numeric(
        telemetry,
        [
            "power_kw",
            "energy_kwh",
            "load_percent",
            "temperature_c",
            "vibration_mm_s",
            "rpm",
            "production_rate",
            "units_produced"
        ]
    )

    telemetry = telemetry.dropna(
        subset=["timestamp", "machine_id"]
    ).copy()

    telemetry = telemetry.sort_values(
        ["machine_id", "timestamp"]
    ).reset_index(drop=True)

    # ========================================================
    # 3. MERGE PRODUCTION DATA
    # ========================================================

    if (
        not production.empty
        and "timestamp" in production.columns
        and "machine_id" in production.columns
    ):

        production = ensure_timestamp(
            production
        )

        production = clean_machine_id(
            production
        )

        production = to_numeric(
            production,
            [
                "target_units",
                "actual_units",
                "cycle_time_sec",
                "downtime_sec",
                "defect_count",
                "quality_percent"
            ]
        )

        production = production.dropna(
            subset=["timestamp", "machine_id"]
        ).copy()

        # Remove duplicate machine/time rows if any.
        production = (
            production
            .sort_values(
                ["machine_id", "timestamp"]
            )
            .drop_duplicates(
                subset=["timestamp", "machine_id"],
                keep="last"
            )
        )

        telemetry = global_asof_merge(
            telemetry,
            production,
            on="timestamp",
            by="machine_id",
            tolerance=60,
            suffixes=("", "_production")
        )

    # ========================================================
    # 4. MERGE MACHINE METADATA
    # ========================================================

    if (
        not metadata.empty
        and "machine_id" in metadata.columns
    ):

        metadata = clean_machine_id(
            metadata
        )

        # Avoid duplicate metadata rows.
        metadata = (
            metadata
            .drop_duplicates(
                subset=["machine_id"],
                keep="last"
            )
        )

        # Don't duplicate columns already present.
        metadata_cols = [
            col
            for col in metadata.columns
            if col == "machine_id"
            or col not in telemetry.columns
        ]

        telemetry = telemetry.merge(
            metadata[metadata_cols],
            on="machine_id",
            how="left"
        )

    # ========================================================
    # 5. MERGE MACHINE CONSTRAINTS
    # ========================================================

    if (
        not constraints.empty
        and "machine_id" in constraints.columns
    ):

        constraints = clean_machine_id(
            constraints
        )

        constraints = (
            constraints
            .drop_duplicates(
                subset=["machine_id"],
                keep="last"
            )
        )

        constraint_cols = [
            col
            for col in constraints.columns
            if col == "machine_id"
            or col not in telemetry.columns
        ]

        telemetry = telemetry.merge(
            constraints[constraint_cols],
            on="machine_id",
            how="left"
        )

    # ========================================================
    # 6. MERGE GRID DATA
    # ========================================================

    if (
        not grid.empty
        and "timestamp" in grid.columns
    ):

        grid = ensure_timestamp(
            grid
        )

        grid = to_numeric(
            grid,
            [
                "available_grid_power_kw",
                "factory_demand_kw",
                "grid_import_limit_kw",
                "grid_stress_level",
                "grid_frequency_hz",
                "grid_voltage_v",
                "solar_available_kw",
                "solar_forecast_kw",
                "battery_soc_percent",
                "battery_available_power_kw",
                "electricity_tariff_rs_kwh"
            ]
        )

        # Keep latest grid reading if duplicate timestamp exists.
        grid = (
            grid
            .dropna(subset=["timestamp"])
            .sort_values("timestamp")
            .drop_duplicates(
                subset=["timestamp"],
                keep="last"
            )
        )

        telemetry = global_asof_merge(
            telemetry,
            grid,
            on="timestamp",
            by=None,
            tolerance=60
        )

    # ========================================================
    # 7. MERGE SCENARIO HISTORY
    #
    # scenario_data.csv is an event/history file.
    # We associate each telemetry point with the latest
    # scenario event occurring at or before that timestamp.
    # ========================================================

    if (
        not scenarios.empty
        and "timestamp" in scenarios.columns
    ):

        scenarios = ensure_timestamp(
            scenarios
        )

        scenarios = scenarios.sort_values(
            "timestamp"
        ).dropna(
            subset=["timestamp"]
        )

        scenario_columns = [
            "timestamp",
            "scenario_id",
            "scenario_name",
            "scenario_type",
            "duration_min",
            "required_reduction_kw",
            "minimum_production_percent",
            "status"
        ]

        scenario_columns = [
            col
            for col in scenario_columns
            if col in scenarios.columns
        ]

        scenario_history = (
            scenarios[scenario_columns]
            .drop_duplicates(
                subset=["timestamp"],
                keep="last"
            )
            .copy()
        )

        scenario_history["timestamp"] = pd.to_numeric(
            scenario_history["timestamp"],
            errors="coerce"
        )

        scenario_history = scenario_history.dropna(
            subset=["timestamp"]
        )

        scenario_history = scenario_history.sort_values(
            "timestamp"
        )

        scenario_left = telemetry[
            ["timestamp"]
        ].drop_duplicates().sort_values(
            "timestamp"
        )

        scenario_left = scenario_left.reset_index(
            drop=True
        )

        scenario_merged = pd.merge_asof(
            scenario_left,
            scenario_history,
            on="timestamp",
            direction="backward"
        )

        telemetry = telemetry.merge(
            scenario_merged,
            on="timestamp",
            how="left",
            suffixes=("", "_scenario")
        )

    # ========================================================
    # 8. WORKING DATAFRAME
    # ========================================================

    df = telemetry.copy()

    # ========================================================
    # 9. ENSURE CORE COLUMNS
    # ========================================================

    df = to_numeric(
        df,
        [
            "power_kw",
            "energy_kwh",
            "load_percent",
            "temperature_c",
            "vibration_mm_s",
            "rpm",
            "production_rate",
            "units_produced",
            "target_units",
            "actual_units",
            "cycle_time_sec",
            "downtime_sec",
            "defect_count",
            "quality_percent",
            "rated_power_kw",
            "efficiency_percent",
            "min_operating_power_kw",
            "max_reduction_kw",
            "max_curtailment_duration_min",
            "available_grid_power_kw",
            "factory_demand_kw",
            "grid_import_limit_kw",
            "grid_stress_level",
            "grid_frequency_hz",
            "grid_voltage_v",
            "solar_available_kw",
            "solar_forecast_kw",
            "battery_soc_percent",
            "battery_available_power_kw",
            "electricity_tariff_rs_kwh",
            "duration_min",
            "required_reduction_kw",
            "minimum_production_percent"
        ]
    )

    if "state" not in df.columns:
        df["state"] = "UNKNOWN"

    if "criticality" not in df.columns:
        df["criticality"] = "UNKNOWN"

    if "controllability" not in df.columns:
        df["controllability"] = "UNKNOWN"

    # ========================================================
    # 10. SORT BY MACHINE / TIME
    # ========================================================

    df = df.sort_values(
        ["machine_id", "timestamp"]
    ).reset_index(drop=True)

    # ========================================================
    # 11. INTERVAL ENERGY
    #
    # energy_kwh is cumulative, so calculate its difference.
    # ========================================================

    df["energy_delta_kwh"] = (
        df.groupby("machine_id")["energy_kwh"]
        .diff()
    )

    df["energy_delta_kwh"] = (
        df["energy_delta_kwh"]
        .clip(lower=0)
        .fillna(0.0)
    )

    # ========================================================
    # 12. ACTUAL TIME DELTA
    # ========================================================

    df["interval_seconds"] = (
        df.groupby("machine_id")["timestamp"]
        .diff()
        .fillna(60.0)
        .clip(lower=1.0)
    )

    df["interval_hours"] = (
        df["interval_seconds"] / 3600.0
    )

    # ========================================================
    # 13. PRODUCTION SEMANTICS
    #
    # The current production logger publishes production_rate
    # / actual_units as a rate-like value (units/hour).
    #
    # Convert it into estimated production during the actual
    # telemetry interval.
    # ========================================================

    rate_source = None

    if "actual_units" in df.columns:
        rate_source = df["actual_units"]

    elif "production_rate" in df.columns:
        rate_source = df["production_rate"]

    else:
        rate_source = pd.Series(
            0.0,
            index=df.index
        )

    rate_source = pd.to_numeric(
        rate_source,
        errors="coerce"
    ).fillna(0.0).clip(lower=0.0)

    df["production_rate_units_per_hour"] = (
        rate_source
    )

    df["estimated_production_units"] = (
        df["production_rate_units_per_hour"]
        * df["interval_hours"]
    )

    # ========================================================
    # 14. PRODUCTION EFFICIENCY
    # ========================================================

    if (
        "target_units" in df.columns
        and "actual_units" in df.columns
    ):

        denominator = (
            df["target_units"]
            .abs()
            + EPS
        )

        df["production_efficiency"] = (
            df["actual_units"]
            / denominator
        ).clip(
            lower=0.0
        )

    else:

        df["production_efficiency"] = np.nan

    # ========================================================
    # 15. PRODUCTION GAP
    # ========================================================

    if (
        "target_units" in df.columns
        and "actual_units" in df.columns
    ):

        df["production_gap_units"] = (
            df["target_units"]
            - df["actual_units"]
        )

        df["production_gap_percent"] = (
            df["production_gap_units"]
            / (
                df["target_units"]
                + EPS
            )
        ) * 100.0

    else:

        df["production_gap_units"] = np.nan
        df["production_gap_percent"] = np.nan

    # ========================================================
    # 16. PRODUCTION-NORMALIZED ENERGY
    # ========================================================

    df["energy_per_unit_kwh"] = (
        df["energy_delta_kwh"]
        / (
            df["estimated_production_units"]
            + EPS
        )
    )

    # Avoid meaningless gigantic values for zero production.
    df.loc[
        df["estimated_production_units"] <= EPS,
        "energy_per_unit_kwh"
    ] = np.nan

    # ========================================================
    # 17. PAST-ONLY POWER BASELINES
    #
    # shift(1) ensures the current observation doesn't define
    # its own baseline.
    # ========================================================

    power_group = (
        df.groupby("machine_id")["power_kw"]
    )

    df["rolling_power_mean_5"] = (
        power_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=5,
                min_periods=2
            )
            .mean()
        )
    )

    df["rolling_power_std_5"] = (
        power_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=5,
                min_periods=2
            )
            .std()
        )
    )

    df["rolling_power_mean_15"] = (
        power_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=15,
                min_periods=3
            )
            .mean()
        )
    )

    df["rolling_power_std_15"] = (
        power_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=15,
                min_periods=3
            )
            .std()
        )
    )

    # Fallback for the first few observations.
    machine_mean_power = (
        df.groupby("machine_id")["power_kw"]
        .transform("mean")
    )

    df["rolling_power_mean_15"] = (
        df["rolling_power_mean_15"]
        .fillna(machine_mean_power)
    )

    df["rolling_power_mean_5"] = (
        df["rolling_power_mean_5"]
        .fillna(
            df["rolling_power_mean_15"]
        )
    )

    df["rolling_power_std_5"] = (
        df["rolling_power_std_5"]
        .fillna(0.0)
    )

    df["rolling_power_std_15"] = (
        df["rolling_power_std_15"]
        .fillna(0.0)
    )

    # ========================================================
    # 18. POWER DEVIATION
    # ========================================================

    df["power_deviation_kw"] = (
        df["power_kw"]
        - df["rolling_power_mean_15"]
    )

    df["power_deviation_percent"] = (
        df["power_deviation_kw"]
        / (
            df["rolling_power_mean_15"]
            + EPS
        )
    ) * 100.0

    df["power_to_baseline_ratio"] = (
        df["power_kw"]
        / (
            df["rolling_power_mean_15"]
            + EPS
        )
    )

    # ========================================================
    # 19. TEMPERATURE BASELINE
    # ========================================================

    temp_group = (
        df.groupby("machine_id")["temperature_c"]
    )

    df["temperature_mean_past"] = (
        temp_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .mean()
        )
    )

    df["temperature_std_past"] = (
        temp_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .std(ddof=0)
        )
    )

    machine_temp_mean = (
        df.groupby("machine_id")["temperature_c"]
        .transform("mean")
    )

    df["temperature_mean_past"] = (
        df["temperature_mean_past"]
        .fillna(machine_temp_mean)
    )

    df["temperature_std_past"] = (
        df["temperature_std_past"]
        .replace(0, np.nan)
        .fillna(1.0)
    )

    df["temperature_deviation"] = (
        df["temperature_c"]
        - df["temperature_mean_past"]
    )

    df["temperature_zscore"] = (
        df["temperature_deviation"]
        / (
            df["temperature_std_past"]
            + EPS
        )
    )

    # ========================================================
    # 20. VIBRATION BASELINE
    # ========================================================

    vibration_group = (
        df.groupby("machine_id")["vibration_mm_s"]
    )

    df["vibration_mean_past"] = (
        vibration_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .mean()
        )
    )

    df["vibration_std_past"] = (
        vibration_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .std(ddof=0)
        )
    )

    machine_vib_mean = (
        df.groupby("machine_id")["vibration_mm_s"]
        .transform("mean")
    )

    df["vibration_mean_past"] = (
        df["vibration_mean_past"]
        .fillna(machine_vib_mean)
    )

    df["vibration_std_past"] = (
        df["vibration_std_past"]
        .replace(0, np.nan)
        .fillna(1.0)
    )

    df["vibration_deviation"] = (
        df["vibration_mm_s"]
        - df["vibration_mean_past"]
    )

    df["vibration_zscore"] = (
        df["vibration_deviation"]
        / (
            df["vibration_std_past"]
            + EPS
        )
    )

    # ========================================================
    # 21. RPM BASELINE
    # ========================================================

    rpm_group = (
        df.groupby("machine_id")["rpm"]
    )

    df["rpm_mean_past"] = (
        rpm_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .mean()
        )
    )

    df["rpm_std_past"] = (
        rpm_group
        .transform(
            lambda x:
            x.shift(1)
            .rolling(
                window=30,
                min_periods=3
            )
            .std(ddof=0)
        )
    )

    machine_rpm_mean = (
        df.groupby("machine_id")["rpm"]
        .transform("mean")
    )

    df["rpm_mean_past"] = (
        df["rpm_mean_past"]
        .fillna(machine_rpm_mean)
    )

    df["rpm_std_past"] = (
        df["rpm_std_past"]
        .replace(0, np.nan)
        .fillna(1.0)
    )

    df["rpm_deviation"] = (
        df["rpm"]
        - df["rpm_mean_past"]
    )

    df["rpm_zscore"] = (
        df["rpm_deviation"]
        / (
            df["rpm_std_past"]
            + EPS
        )
    )

    # ========================================================
    # 22. RATED LOAD
    # ========================================================

    df["rated_power_kw"] = pd.to_numeric(
        df["rated_power_kw"],
        errors="coerce"
    )

    df["rated_load_percent"] = (
        df["power_kw"]
        / (
            df["rated_power_kw"]
            + EPS
        )
    ) * 100.0

    # If rated power isn't available, use telemetry load.
    df.loc[
        df["rated_power_kw"].isna(),
        "rated_load_percent"
    ] = df.loc[
        df["rated_power_kw"].isna(),
        "load_percent"
    ]

    # ========================================================
    # 23. OVERLOAD FLAGS
    # ========================================================

    df["overload_flag"] = (
        df["rated_load_percent"] > 100.0
    ).astype(int)

    df["severe_overload_flag"] = (
        df["rated_load_percent"] > 110.0
    ).astype(int)

    # ========================================================
    # 24. IDLE ENERGY
    # ========================================================

    state_upper = (
        df["state"]
        .astype(str)
        .str.upper()
    )

    df["idle_energy_flag"] = (
        (
            df["estimated_production_units"]
            <= EPS
        )
        &
        (
            df["power_kw"] > 0
        )
        &
        (
            ~state_upper.isin(
                [
                    "OFF",
                    "STOPPED"
                ]
            )
        )
    ).astype(int)

    # ========================================================
    # 25. ENERGY-WASTE FEATURES
    # ========================================================

    df["excess_power_kw"] = (
        df["power_deviation_kw"]
        .clip(lower=0)
    )

    df["excess_energy_kwh"] = (
        df["energy_delta_kwh"]
        * (
            df["power_deviation_kw"] > 0
        ).astype(float)
    )

    # ========================================================
    # 26. MACHINE FLEXIBILITY POTENTIAL
    # ========================================================

    df["available_flexibility_kw"] = (
        df["power_kw"]
        - df["min_operating_power_kw"]
    )

    df["available_flexibility_kw"] = (
        df["available_flexibility_kw"]
        .clip(lower=0)
    )

    max_reduction = (
        df["max_reduction_kw"]
        .fillna(0.0)
        .clip(lower=0)
    )

    df["available_flexibility_kw"] = np.minimum(
        df["available_flexibility_kw"],
        max_reduction
    )

    # ========================================================
    # 27. REAL GRID FEATURES
    # ========================================================

    df["grid_headroom_kw"] = (
        df["available_grid_power_kw"]
        - df["factory_demand_kw"]
    )

    df["grid_import_headroom_kw"] = (
        df["grid_import_limit_kw"]
        - df["factory_demand_kw"]
    )

    df["grid_capacity_ratio"] = (
        df["factory_demand_kw"]
        / (
            df["available_grid_power_kw"]
            + EPS
        )
    )

    # Independent machine-side demand ratio
    df["machine_power_to_factory_demand_ratio"] = (
        df["power_kw"]
        / (
            df["factory_demand_kw"]
            + EPS
        )
    )

    # ========================================================
    # 28. REQUIRED GRID REDUCTION
    # ========================================================

    if "required_reduction_kw" not in df.columns:
        df["required_reduction_kw"] = 0.0

    df["required_reduction_kw"] = (
        df["required_reduction_kw"]
        .fillna(0.0)
        .clip(lower=0)
    )

    df["flexibility_gap_kw"] = (
        df["required_reduction_kw"]
        - df["available_flexibility_kw"]
    )

    # ========================================================
    # 29. SCENARIO FEATURES
    # ========================================================

    if "scenario_id" not in df.columns:
        df["scenario_id"] = "NORMAL"

    if "scenario_name" not in df.columns:
        df["scenario_name"] = "Normal Operation"

    if "scenario_type" not in df.columns:
        df["scenario_type"] = "NORMAL"

    if "scenario_type_scenario" in df.columns:
        df["scenario_type"] = (
            df["scenario_type"]
            .fillna(df["scenario_type_scenario"])
        )

    df["scenario_id"] = (
        df["scenario_id"]
        .fillna("NORMAL")
        .astype(str)
    )

    df["scenario_type"] = (
        df["scenario_type"]
        .fillna("NORMAL")
        .astype(str)
        .str.upper()
    )

    df["scenario_active"] = (
        df["scenario_type"]
        != "NORMAL"
    ).astype(int)

    # ========================================================
    # 30. TIME FEATURES — IST
    # ========================================================

    timestamp_dt = pd.to_datetime(
        df["timestamp"],
        unit="s",
        errors="coerce",
        utc=True
    )

    local_dt = timestamp_dt.dt.tz_convert(
        "Asia/Kolkata"
    )

    df["hour"] = local_dt.dt.hour
    df["minute"] = local_dt.dt.minute
    df["day_of_week"] = local_dt.dt.dayofweek

    df["day_name"] = (
        local_dt.dt.day_name()
    )

    df["is_weekend"] = (
        df["day_of_week"] >= 5
    ).astype(int)

    # Factory shift definition:
    # SHIFT_1 = 00:00–08:00
    # SHIFT_2 = 08:00–16:00
    # SHIFT_3 = 16:00–24:00
    df["shift"] = pd.cut(
        df["hour"],
        bins=[-1, 8, 16, 24],
        labels=[
            "SHIFT_1",
            "SHIFT_2",
            "SHIFT_3"
        ],
        right=False
    ).astype(str)

    # ========================================================
    # 31. CYCLIC TIME FEATURES
    # ========================================================

    df["hour_sin"] = np.sin(
        2 * np.pi * df["hour"] / 24.0
    )

    df["hour_cos"] = np.cos(
        2 * np.pi * df["hour"] / 24.0
    )

    df["day_sin"] = np.sin(
        2 * np.pi * df["day_of_week"] / 7.0
    )

    df["day_cos"] = np.cos(
        2 * np.pi * df["day_of_week"] / 7.0
    )

    # ========================================================
    # 32. DATA QUALITY FLAGS
    # ========================================================

    df["production_data_available"] = (
        df["actual_units"].notna()
        |
        df["target_units"].notna()
    ).astype(int)

    df["grid_data_available"] = (
        df["available_grid_power_kw"].notna()
        |
        df["factory_demand_kw"].notna()
    ).astype(int)

    df["metadata_available"] = (
        df["rated_power_kw"].notna()
        |
        df["criticality"].notna()
    ).astype(int)

    # ========================================================
    # 33. CLEAN CERTAIN VALUES
    # ========================================================

    # Avoid infinities.
    df = df.replace(
        [np.inf, -np.inf],
        np.nan
    )

    # ========================================================
    # 34. FINAL FEATURE SET
    # ========================================================

    feature_columns = [
        # Identity / time
        "timestamp",
        "machine_id",
        "state",

        # Core machine telemetry
        "power_kw",
        "energy_kwh",
        "energy_delta_kwh",
        "interval_seconds",
        "interval_hours",

        "load_percent",
        "rated_load_percent",

        "temperature_c",
        "vibration_mm_s",
        "rpm",

        # Production
        "production_rate_units_per_hour",
        "estimated_production_units",
        "target_units",
        "actual_units",
        "production_efficiency",
        "production_gap_units",
        "production_gap_percent",
        "quality_percent",
        "downtime_sec",

        # Energy intensity
        "energy_per_unit_kwh",

        # Machine information
        "rated_power_kw",
        "efficiency_percent",
        "criticality",
        "controllability",

        # Operating constraints
        "min_operating_power_kw",
        "max_reduction_kw",
        "max_curtailment_duration_min",

        # Power behaviour
        "rolling_power_mean_5",
        "rolling_power_std_5",
        "rolling_power_mean_15",
        "rolling_power_std_15",
        "power_deviation_kw",
        "power_deviation_percent",
        "power_to_baseline_ratio",

        # Condition monitoring
        "temperature_mean_past",
        "temperature_std_past",
        "temperature_deviation",
        "temperature_zscore",

        "vibration_mean_past",
        "vibration_std_past",
        "vibration_deviation",
        "vibration_zscore",

        "rpm_mean_past",
        "rpm_std_past",
        "rpm_deviation",
        "rpm_zscore",

        # Flags
        "overload_flag",
        "severe_overload_flag",
        "idle_energy_flag",

        # Waste
        "excess_power_kw",
        "excess_energy_kwh",

        # Flexibility
        "available_flexibility_kw",

        # Grid
        "available_grid_power_kw",
        "factory_demand_kw",
        "grid_import_limit_kw",
        "grid_stress_level",
        "grid_headroom_kw",
        "grid_import_headroom_kw",
        "grid_capacity_ratio",
        "grid_frequency_hz",
        "grid_voltage_v",

        # Renewable / storage
        "solar_available_kw",
        "solar_forecast_kw",
        "battery_soc_percent",
        "battery_available_power_kw",

        # Economics
        "electricity_tariff_rs_kwh",

        # Grid requirement
        "required_reduction_kw",
        "flexibility_gap_kw",

        # Scenario
        "scenario_id",
        "scenario_name",
        "scenario_type",
        "scenario_active",

        # Time
        "hour",
        "minute",
        "day_of_week",
        "day_name",
        "is_weekend",
        "shift",
        "hour_sin",
        "hour_cos",
        "day_sin",
        "day_cos",

        # Data availability
        "production_data_available",
        "grid_data_available",
        "metadata_available"
    ]

    # ========================================================
    # 35. GUARANTEE STABLE OUTPUT SCHEMA
    # ========================================================

    for col in feature_columns:

        if col not in df.columns:

            if col in [
                "machine_id",
                "state",
                "criticality",
                "controllability",
                "scenario_id",
                "scenario_name",
                "scenario_type",
                "day_name",
                "shift"
            ]:

                df[col] = "UNKNOWN"

            else:

                df[col] = np.nan

    out = df[
        feature_columns
    ].copy()

    # ========================================================
    # 36. FINAL SORT
    # ========================================================

    out = out.sort_values(
        ["machine_id", "timestamp"]
    ).reset_index(drop=True)

    # ========================================================
    # 37. SAVE
    # ========================================================

    AI_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    out.to_csv(
        OUT_FILE,
        index=False
    )

    # ========================================================
    # 38. SUMMARY
    # ========================================================

    print(
        f"\nSaved AI features -> "
        f"{OUT_FILE}"
    )

    print(
        f"Rows: {len(out)}"
    )

    print(
        f"Machines: "
        f"{out['machine_id'].nunique()}"
    )

    print(
        f"Features: {len(out.columns)}"
    )

    print(
        "\nGrid data available:",
        int(out["grid_data_available"].sum())
    )

    print(
        "Production data available:",
        int(out["production_data_available"].sum())
    )

    print(
        "Scenario records:",
        out["scenario_id"].nunique()
    )

    return out


if __name__ == "__main__":
    compute_features()