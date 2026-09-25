#!/usr/bin/env python3

from pathlib import Path
from typing import Optional
import time
import uuid
import json
import shlex
import subprocess

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ============================================================
# PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path.home() / "INDUS_TWIN"

DATA_DIR = PROJECT_ROOT / "data"

FACTORY_DIR = DATA_DIR / "01_factory"
OPERATIONS_DIR = DATA_DIR / "02_operations"
MAINTENANCE_DIR = DATA_DIR / "03_maintenance"
GRID_DIR = DATA_DIR / "04_grid"
SCENARIO_DIR = DATA_DIR / "05_scenarios"

METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"
CONSTRAINTS_FILE = FACTORY_DIR / "machine_constraints.csv"

TELEMETRY_FILE = OPERATIONS_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = OPERATIONS_DIR / "production_data.csv"
QUALITY_FILE = OPERATIONS_DIR / "quality_inspection.csv"

MAINTENANCE_FILE = (
    MAINTENANCE_DIR / "maintenance_events.csv"
)

GRID_FILE = GRID_DIR / "grid_data.csv"
SCENARIO_FILE = SCENARIO_DIR / "scenario_data.csv"

AI_DIR = PROJECT_ROOT / "ai_engine"

ANOMALY_FILE = AI_DIR / "anomaly_output.csv"
MAINTENANCE_OUTPUT_FILE = (
    AI_DIR / "maintenance_output.csv"
)
FORECAST_FILE = (
    AI_DIR / "forecast_output.csv"
)
PRODUCTION_IMPACT_FILE = (
    AI_DIR / "production_impact_output.csv"
)
FLEXIBILITY_FILE = (
    AI_DIR / "flexibility_output.csv"
)
FINAL_DECISION_FILE = (
    AI_DIR / "final_decision_output.csv"
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="INDUS_TWIN Backend",
    description=(
        "Industrial Energy and Process "
        "Digital Twin API"
    ),
    version="1.3.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATA HELPERS
# ============================================================

def read_csv_file(path: Path) -> pd.DataFrame:
    """
    Read a CSV file safely.
    """

    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)

    except Exception as exc:

        print(
            f"[WARNING] Could not read "
            f"{path}: {exc}"
        )

        return pd.DataFrame()


def safe_value(value):
    """
    Recursively convert NumPy/Pandas values into
    standard Python values that FastAPI can serialize.
    """

    if value is None:
        return None

    try:

        if pd.isna(value):
            return None

    except (
        TypeError,
        ValueError,
    ):
        pass

    # NumPy scalar
    if hasattr(value, "item"):

        try:
            return safe_value(
                value.item()
            )

        except Exception:
            pass

    # Dictionary
    if isinstance(value, dict):

        return {
            str(key): safe_value(val)
            for key, val in value.items()
        }

    # List / tuple
    if isinstance(
        value,
        (list, tuple)
    ):

        return [
            safe_value(item)
            for item in value
        ]

    return value


def dataframe_records(
    df: pd.DataFrame
):
    """
    Convert DataFrame to JSON-safe list of dictionaries.
    """

    if df.empty:
        return []

    records = df.to_dict(
        orient="records"
    )

    return [
        {
            str(key): safe_value(value)
            for key, value in record.items()
        }
        for record in records
    ]


def latest_per_machine(
    df: pd.DataFrame
):
    """
    Return the latest observation for every machine.
    """

    if df.empty:
        return df

    if "machine_id" not in df.columns:
        return df

    result = df.copy()

    if "timestamp" in result.columns:

        numeric_timestamp = pd.to_numeric(
            result["timestamp"],
            errors="coerce"
        )

        if numeric_timestamp.notna().any():

            result["_sort_timestamp"] = (
                numeric_timestamp
            )

            result = (
                result
                .sort_values(
                    "_sort_timestamp"
                )
                .groupby(
                    "machine_id",
                    as_index=False
                )
                .tail(1)
                .drop(
                    columns=[
                        "_sort_timestamp"
                    ],
                    errors="ignore",
                )
            )

            return result

    return (
        result
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
    )


def latest_record(
    df: pd.DataFrame
):
    """
    Return the final row of a DataFrame
    as a JSON-safe dictionary.
    """

    if df.empty:
        return {}

    records = dataframe_records(
        df.tail(1)
    )

    if not records:
        return {}

    return records[0]


# ============================================================
# ANALYTICS HELPERS
# ============================================================

def _numeric_timestamp_series(df: pd.DataFrame):
    """Return a numeric timestamp series when possible."""
    if df.empty or "timestamp" not in df.columns:
        return pd.Series(index=df.index, dtype="float64")
    return pd.to_numeric(df["timestamp"], errors="coerce")


def _filter_time_window(
    df: pd.DataFrame,
    hours: int,
) -> pd.DataFrame:
    """
    Filter a dataframe to the latest `hours` of available timestamped data.

    The project uses simulation timestamps, so the window is based on the
    latest timestamp present in the dataset rather than the wall clock.
    """
    if df.empty or "timestamp" not in df.columns:
        return df

    result = df.copy()
    ts = _numeric_timestamp_series(result)

    if not ts.notna().any():
        return result

    latest_ts = float(ts.max())
    start_ts = latest_ts - (hours * 60 * 60)
    return result[ts >= start_ts].copy()


def _aggregate_energy_history(
    df: pd.DataFrame,
    hours: int,
    bucket_minutes: int = 15,
):
    """Aggregate machine telemetry into factory-level time buckets."""
    if df.empty or "timestamp" not in df.columns:
        return []

    result = df.copy()
    result["_timestamp"] = pd.to_numeric(
        result["timestamp"],
        errors="coerce",
    )
    result["_power_kw"] = pd.to_numeric(
        result.get("power_kw", pd.Series(0.0, index=result.index)),
        errors="coerce",
    ).fillna(0.0)

    result = result.dropna(subset=["_timestamp"])
    result = _filter_time_window(result, hours)

    if result.empty:
        return []

    bucket_seconds = bucket_minutes * 60
    result["bucket_timestamp"] = (
        result["_timestamp"] // bucket_seconds
    ) * bucket_seconds

    # Telemetry contains repeated samples for each machine. Average each
    # machine inside the bucket first, then sum the machines. This avoids
    # multiplying factory power by the number of samples in the bucket.
    by_machine = (
        result.groupby(
            ["bucket_timestamp", "machine_id"],
            as_index=False,
        )
        .agg(power_kw=("_power_kw", "mean"))
    )

    grouped = (
        by_machine.groupby("bucket_timestamp", as_index=False)
        .agg(
            factory_power_kw=("power_kw", "sum"),
            active_machines=("machine_id", "nunique"),
        )
        .sort_values("bucket_timestamp")
    )

    grouped["timestamp"] = grouped["bucket_timestamp"]
    grouped["time_label"] = grouped["bucket_timestamp"].apply(
        lambda x: pd.to_datetime(x, unit="s").strftime("%H:%M")
    )

    grouped["factory_power_kw"] = grouped["factory_power_kw"].round(2)
    grouped = grouped.drop(columns=["bucket_timestamp"])
    return dataframe_records(grouped)


def _aggregate_machine_energy(
    df: pd.DataFrame,
    machine_id: Optional[str] = None,
    hours: int = 24,
    bucket_minutes: int = 15,
):
    """Aggregate telemetry for one machine or all machines."""
    if df.empty or "timestamp" not in df.columns:
        return []

    result = df.copy()
    if machine_id:
        result = result[
            result["machine_id"].astype(str) == str(machine_id)
        ]

    result = _filter_time_window(result, hours)
    if result.empty:
        return []

    result["_timestamp"] = pd.to_numeric(
        result["timestamp"],
        errors="coerce",
    )
    result["_power_kw"] = pd.to_numeric(
        result.get("power_kw", pd.Series(0.0, index=result.index)),
        errors="coerce",
    ).fillna(0.0)
    result = result.dropna(subset=["_timestamp"])

    bucket_seconds = bucket_minutes * 60
    result["bucket_timestamp"] = (
        result["_timestamp"] // bucket_seconds
    ) * bucket_seconds

    grouped = (
        result.groupby(
            "bucket_timestamp",
            as_index=False,
        )
        .agg(
            power_kw=("_power_kw", "mean"),
        )
        .sort_values("bucket_timestamp")
    )

    # Convert the average power in each bucket to an energy-equivalent value.
    # This is a dashboard aggregation, not a replacement for an energy meter.
    grouped["energy_kwh"] = (
        grouped["power_kw"] * (bucket_minutes / 60.0)
    )

    grouped["timestamp"] = grouped["bucket_timestamp"]
    grouped["time_label"] = grouped["bucket_timestamp"].apply(
        lambda x: pd.to_datetime(x, unit="s").strftime("%H:%M")
    )
    grouped["power_kw"] = grouped["power_kw"].round(2)
    grouped["energy_kwh"] = grouped["energy_kwh"].round(3)
    grouped = grouped.drop(columns=["bucket_timestamp"])

    return dataframe_records(grouped)


def _aggregate_machine_production_history(
    df: pd.DataFrame,
    machine_id: str,
    hours: int = 24,
    bucket_minutes: int = 15,
    reference_ts: Optional[float] = None,
):
    """Return dashboard-friendly production snapshots for one machine.

    The production logger writes repeated snapshots roughly every few seconds.
    For a graph we keep the latest production state in each time bucket rather
    than returning every duplicate snapshot.
    """
    if df.empty or "timestamp" not in df.columns or "machine_id" not in df.columns:
        return []

    result = df.copy()
    result = result[result["machine_id"].astype(str) == str(machine_id)].copy()
    if result.empty:
        return []

    result["_timestamp"] = pd.to_numeric(result["timestamp"], errors="coerce")
    result = result.dropna(subset=["_timestamp"])
    result = _filter_time_window_from_reference(result, hours, reference_ts)
    if result.empty:
        return []

    for column in [
        "target_units",
        "actual_units",
        "cycle_time_sec",
        "downtime_sec",
        "defect_count",
        "quality_percent",
    ]:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0.0)
        else:
            result[column] = 0.0

    bucket_seconds = int(bucket_minutes) * 60
    result["bucket_timestamp"] = (result["_timestamp"] // bucket_seconds) * bucket_seconds

    latest = (
        result.sort_values(["bucket_timestamp", "_timestamp"])
        .groupby("bucket_timestamp", as_index=False)
        .tail(1)
        .sort_values("bucket_timestamp")
        .copy()
    )

    latest["timestamp"] = latest["bucket_timestamp"]
    latest["time_label"] = latest["bucket_timestamp"].apply(
        lambda x: pd.to_datetime(x, unit="s").strftime("%H:%M")
    )

    keep = [
        "timestamp",
        "time_label",
        "production_line",
        "machine_id",
        "product_id",
        "target_units",
        "actual_units",
        "cycle_time_sec",
        "downtime_sec",
        "defect_count",
        "quality_percent",
    ]
    keep = [column for column in keep if column in latest.columns]
    latest = latest[keep]

    for column in [
        "target_units",
        "actual_units",
        "cycle_time_sec",
        "downtime_sec",
        "defect_count",
        "quality_percent",
    ]:
        if column in latest.columns:
            latest[column] = latest[column].round(2)

    return dataframe_records(latest)


def _build_status_summary():
    """Build live machine-state counts from latest telemetry."""
    telemetry = read_csv_file(TELEMETRY_FILE)
    latest = latest_per_machine(telemetry)

    counts = {
        "RUNNING": 0,
        "IDLE": 0,
        "MAINTENANCE": 0,
        "FAULT": 0,
    }

    if latest.empty or "state" not in latest.columns:
        return {
            "total": 0,
            "counts": counts,
        }

    states = latest["state"].astype(str).str.upper().str.strip()

    for state in states:
        if state in {"RUNNING", "ACTIVE"}:
            counts["RUNNING"] += 1
        elif state in {"IDLE", "STANDBY", "STOPPED"}:
            counts["IDLE"] += 1
        elif state in {"MAINTENANCE", "SERVICE"}:
            counts["MAINTENANCE"] += 1
        elif state in {"FAULT", "ERROR", "FAILED"}:
            counts["FAULT"] += 1
        else:
            # Unknown states are intentionally not forced into a category.
            pass

    return {
        "total": int(len(latest)),
        "counts": counts,
    }


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "project": "INDUS_TWIN",
        "status": "online",
        "service": (
            "industrial-energy-"
            "digital-twin"
        ),
        "version": "1.1.1",
    }


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health():

    files = {

        "metadata":
            METADATA_FILE,

        "constraints":
            CONSTRAINTS_FILE,

        "telemetry":
            TELEMETRY_FILE,

        "production":
            PRODUCTION_FILE,

        "quality":
            QUALITY_FILE,

        "maintenance":
            MAINTENANCE_FILE,

        "grid":
            GRID_FILE,

        "scenario":
            SCENARIO_FILE,

        "anomaly":
            ANOMALY_FILE,

        "maintenance_ai":
            MAINTENANCE_OUTPUT_FILE,

        "forecast":
            FORECAST_FILE,

        "production_impact":
            PRODUCTION_IMPACT_FILE,

        "flexibility":
            FLEXIBILITY_FILE,

        "final_decision":
            FINAL_DECISION_FILE,
    }

    availability = {
        name: path.exists()
        for name, path in files.items()
    }

    return {
        "status": "healthy",
        "project_root": str(
            PROJECT_ROOT
        ),
        "files": availability,
    }


# ============================================================
# FACTORY OVERVIEW
# ============================================================

@app.get("/api/factory")
def factory_overview():

    telemetry = read_csv_file(
        TELEMETRY_FILE
    )

    metadata = read_csv_file(
        METADATA_FILE
    )

    production = read_csv_file(
        PRODUCTION_FILE
    )

    grid = read_csv_file(
        GRID_FILE
    )

    flexibility = read_csv_file(
        FLEXIBILITY_FILE
    )

    final_decision = read_csv_file(
        FINAL_DECISION_FILE
    )

    latest_machine_data = latest_per_machine(
        telemetry
    )

    # --------------------------------------------------------
    # Factory power
    # --------------------------------------------------------

    factory_power_kw = 0.0

    if (
        not latest_machine_data.empty
        and "power_kw"
        in latest_machine_data.columns
    ):

        factory_power_kw = float(
            pd.to_numeric(
                latest_machine_data[
                    "power_kw"
                ],
                errors="coerce"
            )
            .fillna(0.0)
            .sum()
        )

    # --------------------------------------------------------
    # Running machines
    # --------------------------------------------------------

    running_machines = 0

    if (
        not latest_machine_data.empty
        and "state"
        in latest_machine_data.columns
    ):

        running_machines = int(
            latest_machine_data[
                "state"
            ]
            .astype(str)
            .str.upper()
            .isin(
                [
                    "RUNNING",
                    "ACTIVE",
                ]
            )
            .sum()
        )

    # --------------------------------------------------------
    # Latest grid state
    # --------------------------------------------------------

    latest_grid = latest_record(
        grid
    )

    # --------------------------------------------------------
    # Latest final decision
    # --------------------------------------------------------

    latest_decision = latest_record(
        final_decision
    )

    # --------------------------------------------------------
    # Required reduction
    # --------------------------------------------------------

    required_reduction_kw = 0.0

    try:

        value = latest_grid.get(
            "required_reduction_kw"
        )

        if value is not None:
            required_reduction_kw = float(
                value
            )

    except (
        ValueError,
        TypeError,
    ):

        required_reduction_kw = 0.0

    # --------------------------------------------------------
    # AUTHORITATIVE FLEXIBILITY VALUE
    # --------------------------------------------------------
    #
    # Use flexibility_output.csv as the authoritative
    # source for total deployable flexibility.
    #
    # The file contains machine-level values, so sum them.
    # --------------------------------------------------------

    deployable_flexibility_kw = 0.0

    if (
        not flexibility.empty
        and "deployable_flexibility_kw"
        in flexibility.columns
    ):

        deployable_flexibility_kw = float(
            pd.to_numeric(
                flexibility[
                    "deployable_flexibility_kw"
                ],
                errors="coerce"
            )
            .fillna(0.0)
            .sum()
        )

    # --------------------------------------------------------
    # Reserve margin
    # --------------------------------------------------------

    reserve_margin_kw = (
        deployable_flexibility_kw
        - required_reduction_kw
    )

    # --------------------------------------------------------
    # Reserve status
    # --------------------------------------------------------

    if required_reduction_kw <= 0:

        reserve_status = (
            "NO_GRID_REDUCTION_REQUIRED"
        )

    elif (
        deployable_flexibility_kw
        >= required_reduction_kw
    ):

        reserve_status = (
            "RESERVE_SUFFICIENT"
        )

    else:

        reserve_status = (
            "RESERVE_INSUFFICIENT"
        )

    # --------------------------------------------------------
    # Timestamp
    # --------------------------------------------------------

    factory_timestamp = None

    if (
        not latest_machine_data.empty
        and "timestamp"
        in latest_machine_data.columns
    ):

        factory_timestamp = safe_value(
            latest_machine_data[
                "timestamp"
            ].max()
        )

    # --------------------------------------------------------
    # Machine count
    # --------------------------------------------------------

    if not metadata.empty:

        machine_count = int(
            metadata[
                "machine_id"
            ].nunique()
        )

    elif not latest_machine_data.empty:

        machine_count = int(
            latest_machine_data[
                "machine_id"
            ].nunique()
        )

    else:

        machine_count = 0

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return {

        "timestamp":
            factory_timestamp,

        "factory_power_kw":
            round(
                factory_power_kw,
                2
            ),

        "machine_count":
            machine_count,

        "running_machines":
            running_machines,

        "grid_status":
            safe_value(
                latest_grid.get(
                    "grid_status"
                )
            ),

        "grid_stress_level":
            safe_value(
                latest_grid.get(
                    "grid_stress_level"
                )
            ),

        "available_grid_power_kw":
            safe_value(
                latest_grid.get(
                    "available_grid_power_kw"
                )
            ),

        "required_reduction_kw":
            round(
                required_reduction_kw,
                2
            ),

        "deployable_flexibility_kw":
            round(
                deployable_flexibility_kw,
                2
            ),

        "reserve_margin_kw":
            round(
                reserve_margin_kw,
                2
            ),

        "reserve_status":
            reserve_status,

        "system_action":
            safe_value(
                latest_decision.get(
                    "system_action"
                )
            ),

        "production_records":
            int(len(production)),
    }


# ============================================================
# MACHINE DATA
# ============================================================

@app.get("/api/machines")
def machines():

    telemetry = read_csv_file(
        TELEMETRY_FILE
    )

    metadata = read_csv_file(
        METADATA_FILE
    )

    constraints = read_csv_file(
        CONSTRAINTS_FILE
    )

    anomaly = read_csv_file(
        ANOMALY_FILE
    )

    maintenance = read_csv_file(
        MAINTENANCE_OUTPUT_FILE
    )

    flexibility = read_csv_file(
        FLEXIBILITY_FILE
    )

    latest_telemetry = latest_per_machine(
        telemetry
    )

    latest_anomaly = latest_per_machine(
        anomaly
    )

    latest_maintenance = latest_per_machine(
        maintenance
    )

    # --------------------------------------------------------
    # Base machine list
    # --------------------------------------------------------

    if not metadata.empty:

        machines_df = metadata.copy()

    elif not latest_telemetry.empty:

        machines_df = (
            latest_telemetry[
                ["machine_id"]
            ]
            .drop_duplicates()
        )

    else:

        machines_df = pd.DataFrame(
            columns=[
                "machine_id"
            ]
        )

    # --------------------------------------------------------
    # Telemetry
    # --------------------------------------------------------

    if not latest_telemetry.empty:

        columns = [
            "machine_id",
            "timestamp",
            "state",
            "power_kw",
            "energy_kwh",
            "load_percent",
            "temperature_c",
            "vibration_mm_s",
            "rpm",
            "production_rate",
            "units_produced",
        ]

        columns = [
            column
            for column in columns
            if column
            in latest_telemetry.columns
        ]

        machines_df = machines_df.merge(
            latest_telemetry[
                columns
            ],
            on="machine_id",
            how="left",
        )

    # --------------------------------------------------------
    # Anomaly
    # --------------------------------------------------------

    if not latest_anomaly.empty:

        columns = [
            "machine_id",
            "anomaly",
            "anomaly_type",
            "severity",
            "confidence",
            "detection_reason",
        ]

        columns = [
            column
            for column in columns
            if column
            in latest_anomaly.columns
        ]

        machines_df = machines_df.merge(
            latest_anomaly[
                columns
            ],
            on="machine_id",
            how="left",
            suffixes=(
                "",
                "_anomaly",
            ),
        )

    # --------------------------------------------------------
    # Maintenance health
    # --------------------------------------------------------

    if not latest_maintenance.empty:

        columns = [
            "machine_id",
            "maintenance_risk",
            "maintenance_label",
            "maintenance_trigger",
            "maintenance_confidence",
            "maintenance_reason",
        ]

        columns = [
            column
            for column in columns
            if column
            in latest_maintenance.columns
        ]

        machines_df = machines_df.merge(
            latest_maintenance[
                columns
            ],
            on="machine_id",
            how="left",
            suffixes=(
                "",
                "_maintenance",
            ),
        )

    # --------------------------------------------------------
    # Flexibility
    # --------------------------------------------------------

    if not flexibility.empty:

        columns = [
            "machine_id",
            "physical_flexibility_kw",
            "safe_flexibility_kw",
            "deployable_flexibility_kw",
            "flexible_energy_reserve_kwh",
            "deployment_status",
        ]

        columns = [
            column
            for column in columns
            if column
            in flexibility.columns
        ]

        machines_df = machines_df.merge(
            flexibility[
                columns
            ],
            on="machine_id",
            how="left",
        )

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    if not constraints.empty:

        columns = [
            "machine_id",
            "min_operating_power_kw",
            "max_reduction_kw",
            "max_curtailment_duration_min",
            "ramp_rate_kw_per_min",
            "minimum_runtime_min",
            "minimum_shutdown_min",
            "can_curtail",
            "can_shift",
        ]

        columns = [
            column
            for column in columns
            if column
            in constraints.columns
        ]

        machines_df = machines_df.merge(
            constraints[
                columns
            ],
            on="machine_id",
            how="left",
            suffixes=(
                "",
                "_constraint",
            ),
        )

    return {
        "count":
            int(len(machines_df)),

        "machines":
            dataframe_records(
                machines_df
            ),
    }


# ============================================================
# SINGLE MACHINE
# ============================================================

@app.get(
    "/api/machines/{machine_id}"
)
def machine_detail(
    machine_id: str
):

    result = machines()

    for machine in result[
        "machines"
    ]:

        if str(
            machine.get(
                "machine_id"
            )
        ) == machine_id:

            return machine

    raise HTTPException(
        status_code=404,
        detail=(
            f"Machine "
            f"{machine_id} not found"
        ),
    )


# ============================================================
# TELEMETRY
# ============================================================

@app.get("/api/telemetry")
def telemetry(
    machine_id: Optional[str] = None,
    limit: int = 100,
):

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    df = read_csv_file(
        TELEMETRY_FILE
    )

    if (
        machine_id
        and not df.empty
    ):

        df = df[
            df[
                "machine_id"
            ]
            .astype(str)
            == machine_id
        ]

    if (
        not df.empty
        and "timestamp"
        in df.columns
    ):

        df = df.sort_values(
            "timestamp"
        )

    return {
        "count":
            int(
                min(
                    len(df),
                    limit
                )
            ),

        "data":
            dataframe_records(
                df.tail(limit)
            ),
    }


# ============================================================
# PRODUCTION
# ============================================================

@app.get("/api/production")
def production(
    machine_id: Optional[str] = None,
    limit: int = 100,
):

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    df = read_csv_file(
        PRODUCTION_FILE
    )

    if (
        machine_id
        and not df.empty
    ):

        df = df[
            df[
                "machine_id"
            ]
            .astype(str)
            == machine_id
        ]

    if (
        not df.empty
        and "timestamp"
        in df.columns
    ):

        df = df.sort_values(
            "timestamp"
        )

    return {
        "count":
            int(
                min(
                    len(df),
                    limit
                )
            ),

        "data":
            dataframe_records(
                df.tail(limit)
            ),
    }


# ============================================================
# GRID
# ============================================================

@app.get("/api/grid")
def grid(
    limit: int = 100,
):

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    df = read_csv_file(
        GRID_FILE
    )

    if (
        not df.empty
        and "timestamp"
        in df.columns
    ):

        df = df.sort_values(
            "timestamp"
        )

    return {
        "count":
            int(
                min(
                    len(df),
                    limit
                )
            ),

        "latest":
            latest_record(df),

        "data":
            dataframe_records(
                df.tail(limit)
            ),
    }


# ============================================================
# SCENARIO
# ============================================================

@app.get("/api/scenario")
def scenario():

    df = read_csv_file(
        SCENARIO_FILE
    )

    return {
        "count":
            int(len(df)),

        "latest":
            latest_record(df),

        "data":
            dataframe_records(
                df.tail(50)
            ),
    }


# ============================================================
# ANOMALIES
# ============================================================

@app.get("/api/anomalies")
def anomalies(
    machine_id: Optional[str] = None,
    limit: int = 100,
):

    limit = max(
        1,
        min(
            int(limit),
            5000
        )
    )

    df = read_csv_file(
        ANOMALY_FILE
    )

    if (
        machine_id
        and not df.empty
    ):

        df = df[
            df[
                "machine_id"
            ]
            .astype(str)
            == machine_id
        ]

    if (
        not df.empty
        and "timestamp"
        in df.columns
    ):

        df = df.sort_values(
            "timestamp"
        )

    return {
        "count":
            int(
                min(
                    len(df),
                    limit
                )
            ),

        "data":
            dataframe_records(
                df.tail(limit)
            ),
    }


# ============================================================
# MAINTENANCE HEALTH
# ============================================================

@app.get(
    "/api/maintenance/health"
)
def maintenance_health(
    machine_id: Optional[str] = None,
):

    df = read_csv_file(
        MAINTENANCE_OUTPUT_FILE
    )

    if (
        machine_id
        and not df.empty
    ):

        df = df[
            df[
                "machine_id"
            ]
            .astype(str)
            == machine_id
        ]

    latest = latest_per_machine(
        df
    )

    return {
        "count":
            int(len(latest)),

        "data":
            dataframe_records(
                latest
            ),
    }


# ============================================================
# MAINTENANCE EVENTS
# ============================================================

@app.get(
    "/api/maintenance/events"
)
def maintenance_events():

    df = read_csv_file(
        MAINTENANCE_FILE
    )

    return {
        "count":
            int(len(df)),

        "events":
            dataframe_records(
                df
            ),
    }


# ============================================================
# MAINTENANCE STATUS UPDATE
# ============================================================

class MaintenanceStatusUpdate(
    BaseModel
):

    status: str


@app.patch(
    "/api/maintenance/events/{event_id}"
)
def update_maintenance_status(
    event_id: str,
    update: MaintenanceStatusUpdate,
):

    allowed_statuses = {
        "SUBMITTED",
        "ONGOING",
        "COMPLETED",
    }

    status = (
        update.status
        .strip()
        .upper()
    )

    if status not in allowed_statuses:

        raise HTTPException(
            status_code=400,
            detail=(
                "Status must be one of: "
                "SUBMITTED, ONGOING, COMPLETED"
            ),
        )

    df = read_csv_file(
        MAINTENANCE_FILE
    )

    if df.empty:

        raise HTTPException(
            status_code=404,
            detail=(
                "No maintenance "
                "events found"
            ),
        )

    if "event_id" not in df.columns:

        raise HTTPException(
            status_code=500,
            detail=(
                "maintenance_events.csv "
                "does not contain event_id"
            ),
        )

    mask = (
        df["event_id"]
        .astype(str)
        == event_id
    )

    if not mask.any():

        raise HTTPException(
            status_code=404,
            detail=(
                f"Maintenance event "
                f"{event_id} not found"
            ),
        )

    # --------------------------------------------------------
    # Capture the event and previous status before updating.
    # --------------------------------------------------------

    event_row = df.loc[mask].iloc[0].to_dict()
    previous_status = str(
        event_row.get("status", "")
    ).strip().upper()

    machine_id = str(
        event_row.get("machine_id", "")
    ).strip()

    # --------------------------------------------------------
    # Synchronize maintenance status with the live ROS Twin.
    #
    # ONGOING  -> MAINTENANCE_START
    # COMPLETED -> MAINTENANCE_COMPLETE
    #
    # Do not publish again when the same status is submitted twice.
    # This prevents duplicate ROS control commands from UI refreshes.
    # --------------------------------------------------------

    maintenance_command = {
        "ONGOING": "MAINTENANCE_START",
        "COMPLETED": "MAINTENANCE_COMPLETE",
    }.get(status)

    ros_result = None

    if (
        maintenance_command
        and status != previous_status
    ):

        if not machine_id:
            raise HTTPException(
                status_code=500,
                detail="Maintenance event has no machine_id",
            )

        ros_payload = {
            "timestamp": int(time.time()),
            "source": "MAINTENANCE_UI",
            "machine_id": machine_id,
            "command": maintenance_command,
        }

        ros_result = _publish_ros_string(
            CONTROL_COMMAND_TOPIC,
            ros_payload,
        )

    # --------------------------------------------------------
    # Persist the operator status after ROS accepts the command.
    # --------------------------------------------------------

    df.loc[
        mask,
        "status"
    ] = status

    df.loc[
        mask,
        "last_updated"
    ] = pd.Timestamp.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    df.to_csv(
        MAINTENANCE_FILE,
        index=False
    )

    updated = df[
        mask
    ].iloc[0].to_dict()

    response = {
        "success": True,
        "event": {
            key: safe_value(value)
            for key, value
            in updated.items()
        },
    }

    if ros_result is not None:
        response["ros"] = ros_result

    return response


# ============================================================
# FORECAST
# ============================================================

@app.get("/api/forecast")
def forecast():

    df = read_csv_file(
        FORECAST_FILE
    )

    return {
        "count":
            int(len(df)),

        "data":
            dataframe_records(
                df
            ),
    }


# ============================================================
# PRODUCTION IMPACT
# ============================================================

@app.get(
    "/api/production-impact"
)
def production_impact():

    df = read_csv_file(
        PRODUCTION_IMPACT_FILE
    )

    return {
        "count":
            int(len(df)),

        "data":
            dataframe_records(
                df
            ),
    }


# ============================================================
# FLEXIBILITY / VIRTUAL RESERVE
# ============================================================

@app.get("/api/flexibility")
def flexibility():

    df = read_csv_file(
        FLEXIBILITY_FILE
    )

    return {
        "count":
            int(len(df)),

        "data":
            dataframe_records(
                df
            ),
    }


# ============================================================
# FINAL DECISION
# ============================================================

@app.get("/api/decision")
def final_decision():

    df = read_csv_file(
        FINAL_DECISION_FILE
    )

    return {
        "count":
            int(len(df)),

        "latest":
            latest_record(df),

        "data":
            dataframe_records(
                df
            ),
    }


# ============================================================
# FACTORY STATUS COUNTS
# ============================================================

@app.get("/api/factory/status")
def factory_status():
    """Return live RUNNING / IDLE / MAINTENANCE / FAULT counts."""
    return _build_status_summary()


# ============================================================
# ENERGY HISTORY / TIME RANGE ANALYTICS
# ============================================================

@app.get("/api/analytics/energy")
def energy_analytics(
    hours: int = 24,
    bucket_minutes: int = 15,
):
    """
    Factory energy history for the requested simulation-time window.

    Supported dashboard ranges are 12 hours and 24 hours, while the endpoint
    remains configurable for future views.
    """
    if hours not in {12, 24}:
        raise HTTPException(
            status_code=400,
            detail="hours must be 12 or 24",
        )

    bucket_minutes = max(1, min(int(bucket_minutes), 60))
    telemetry = read_csv_file(TELEMETRY_FILE)
    history = _aggregate_energy_history(
        telemetry,
        hours,
        bucket_minutes,
    )

    latest_machine_data = latest_per_machine(telemetry)
    machine_summary = []

    if not latest_machine_data.empty and "machine_id" in latest_machine_data.columns:
        temp = latest_machine_data.copy()
        temp["power_kw"] = pd.to_numeric(
            temp.get("power_kw", 0),
            errors="coerce",
        ).fillna(0.0)
        machine_summary_df = (
            temp.groupby("machine_id", as_index=False)
            .agg(power_kw=("power_kw", "sum"))
            .sort_values("power_kw", ascending=False)
        )
        machine_summary_df["power_kw"] = machine_summary_df["power_kw"].round(2)
        machine_summary = dataframe_records(machine_summary_df)

    return {
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "count": len(history),
        "history": history,
        "latest_machine_power": machine_summary,
    }


# ============================================================
# MACHINE ENERGY HISTORY
# ============================================================

@app.get("/api/machines/{machine_id}/history")
def machine_history(
    machine_id: str,
    hours: int = 24,
    bucket_minutes: int = 15,
):
    """Return time-series telemetry for a selected machine."""
    if hours not in {12, 24}:
        raise HTTPException(
            status_code=400,
            detail="hours must be 12 or 24",
        )

    bucket_minutes = max(1, min(int(bucket_minutes), 60))

    telemetry = read_csv_file(TELEMETRY_FILE)
    filtered = telemetry[
        telemetry["machine_id"].astype(str) == str(machine_id)
    ] if (
        not telemetry.empty and "machine_id" in telemetry.columns
    ) else pd.DataFrame()

    if filtered.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No telemetry found for machine {machine_id}",
        )

    history = _aggregate_machine_energy(
        telemetry,
        machine_id=machine_id,
        hours=hours,
        bucket_minutes=bucket_minutes,
    )

    return {
        "machine_id": machine_id,
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "count": len(history),
        "history": history,
    }


# ============================================================
# PRODUCTION HISTORY / TIME RANGE ANALYTICS
# ============================================================

@app.get("/api/analytics/production")
def production_analytics(
    hours: int = 24,
    bucket_minutes: int = 15,
):
    """
    Return production history and high-level production metrics.

    Production CSV rows are periodic snapshots, not independent production
    transactions. Therefore, repeated snapshots must not be summed across
    time. For each machine and time bucket, the latest snapshot is retained;
    machine values are then aggregated to the factory/line level.
    """
    if hours not in {12, 24}:
        raise HTTPException(
            status_code=400,
            detail="hours must be 12 or 24",
        )

    bucket_minutes = max(1, min(int(bucket_minutes), 60))

    production_df = read_csv_file(PRODUCTION_FILE)

    if production_df.empty or "timestamp" not in production_df.columns:
        return {
            "hours": hours,
            "bucket_minutes": bucket_minutes,
            "count": 0,
            "history": [],
            "summary": {
                "target_units": 0.0,
                "actual_units": 0.0,
                "defect_count": 0.0,
                "good_units": 0.0,
                "quality_percent": 0.0,
                "completion_percent": 0.0,
            },
        }

    df = production_df.copy()
    df["_timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="coerce",
    )
    df = df.dropna(subset=["_timestamp"])
    df = _filter_time_window(df, hours)

    if df.empty:
        return {
            "hours": hours,
            "bucket_minutes": bucket_minutes,
            "count": 0,
            "history": [],
            "summary": {
                "target_units": 0.0,
                "actual_units": 0.0,
                "defect_count": 0.0,
                "good_units": 0.0,
                "quality_percent": 0.0,
                "completion_percent": 0.0,
            },
        }

    for column in ["target_units", "actual_units", "defect_count"]:
        if column in df.columns:
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce",
            ).fillna(0.0)
        else:
            df[column] = 0.0

    # The production logger periodically repeats the current cumulative
    # production snapshot. Keep only production-relevant machine rows.
    # Utility/support machines with target=0 and actual=0 do not contribute.
    production_rows = df[
        (df["target_units"] > 0)
        | (df["actual_units"] > 0)
        | (df["defect_count"] > 0)
    ].copy()

    if production_rows.empty:
        return {
            "hours": hours,
            "bucket_minutes": bucket_minutes,
            "count": 0,
            "history": [],
            "summary": {
                "target_units": 0.0,
                "actual_units": 0.0,
                "defect_count": 0.0,
                "good_units": 0.0,
                "quality_percent": 0.0,
                "completion_percent": 0.0,
            },
        }

    bucket_seconds = bucket_minutes * 60
    production_rows["bucket_timestamp"] = (
        production_rows["_timestamp"] // bucket_seconds
    ) * bucket_seconds

    # Keep the latest snapshot for every machine within each bucket. This
    # prevents the repeated 10-second logger snapshots from inflating totals.
    latest_bucket = (
        production_rows
        .sort_values(["machine_id", "_timestamp"])
        .groupby(
            ["bucket_timestamp", "machine_id"],
            as_index=False,
        )
        .tail(1)
        .copy()
    )

    history_df = (
        latest_bucket
        .groupby("bucket_timestamp", as_index=False)
        .agg(
            target_units=("target_units", "sum"),
            actual_units=("actual_units", "sum"),
            defect_count=("defect_count", "sum"),
            active_production_machines=("machine_id", "nunique"),
        )
        .sort_values("bucket_timestamp")
    )

    history_df["good_units"] = (
        history_df["actual_units"] - history_df["defect_count"]
    ).clip(lower=0.0)

    history_df["quality_percent"] = history_df.apply(
        lambda row: (
            (row["good_units"] / row["actual_units"]) * 100.0
            if row["actual_units"] > 0
            else 0.0
        ),
        axis=1,
    )
    history_df["completion_percent"] = history_df.apply(
        lambda row: (
            (row["actual_units"] / row["target_units"]) * 100.0
            if row["target_units"] > 0
            else 0.0
        ),
        axis=1,
    )

    history_df["timestamp"] = history_df["bucket_timestamp"]
    history_df["time_label"] = history_df["bucket_timestamp"].apply(
        lambda x: pd.to_datetime(x, unit="s").strftime("%H:%M")
    )

    for column in [
        "target_units",
        "actual_units",
        "defect_count",
        "good_units",
        "quality_percent",
        "completion_percent",
    ]:
        history_df[column] = history_df[column].round(2)

    history_df = history_df.drop(columns=["bucket_timestamp"])
    history = dataframe_records(history_df)

    # Current production state for the selected window: take the latest
    # snapshot of each production machine, then sum machine totals once.
    latest_machine = (
        production_rows
        .sort_values(["machine_id", "_timestamp"])
        .groupby("machine_id", as_index=False)
        .tail(1)
    )

    target_units = float(latest_machine["target_units"].sum())
    actual_units = float(latest_machine["actual_units"].sum())
    defect_count = float(latest_machine["defect_count"].sum())
    good_units = max(0.0, actual_units - defect_count)

    quality_percent = (
        (good_units / actual_units) * 100.0
        if actual_units > 0
        else 0.0
    )
    completion_percent = (
        (actual_units / target_units) * 100.0
        if target_units > 0
        else 0.0
    )

    return {
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "count": len(history),
        "history": history,
        "summary": {
            "target_units": round(target_units, 2),
            "actual_units": round(actual_units, 2),
            "defect_count": round(defect_count, 2),
            "good_units": round(good_units, 2),
            "quality_percent": round(
                max(0.0, min(100.0, quality_percent)),
                2,
            ),
            "completion_percent": round(
                max(0.0, completion_percent),
                2,
            ),
        },
    }


# ============================================================
# QUALITY INSPECTION
# ============================================================

class QualityInspectionCreate(BaseModel):
    """Payload for creating a post-production quality inspection record."""

    machine_id: str
    batch_id: str
    part_id: str
    inspected_units: int
    result: str
    rejection_reason: Optional[str] = None
    inspector: str = "AI_INSPECTION"
    timestamp: Optional[int] = None


def _quality_result(value: str) -> str:
    """Normalize supported quality outcomes to GOOD or REJECT."""
    result = str(value).strip().upper()

    aliases = {
        "PASS": "GOOD",
        "ACCEPT": "GOOD",
        "ACCEPTED": "GOOD",
        "GOOD": "GOOD",
        "FAIL": "REJECT",
        "REJECTED": "REJECT",
        "REJECT": "REJECT",
    }

    return aliases.get(result, "")


@app.get("/api/quality")
def quality(
    machine_id: Optional[str] = None,
    limit: int = 100,
):
    """Return post-production inspection records and unit-level quality metrics."""
    limit = max(1, min(int(limit), 5000))
    df = read_csv_file(QUALITY_FILE)

    if machine_id and not df.empty and "machine_id" in df.columns:
        df = df[
            df["machine_id"].astype(str) == str(machine_id)
        ]

    if not df.empty and "timestamp" in df.columns:
        df = df.sort_values("timestamp")

    result = df.tail(limit) if not df.empty else df

    inspected_units = 0
    good_units = 0
    rejected_units = 0

    if not df.empty:
        inspected_source = (
            df["inspected_units"]
            if "inspected_units" in df.columns
            else pd.Series(0.0, index=df.index)
        )
        inspected_series = pd.to_numeric(
            inspected_source,
            errors="coerce",
        ).fillna(0.0).clip(lower=0.0)
        inspected_units = int(inspected_series.sum())

        if "result" in df.columns:
            results = df["result"].astype(str).str.upper().str.strip()
            good_mask = results.isin({"GOOD", "PASS", "ACCEPT", "ACCEPTED"})
            reject_mask = results.isin({"REJECT", "REJECTED", "FAIL"})
            good_units = int(inspected_series.where(good_mask, 0.0).sum())
            rejected_units = int(inspected_series.where(reject_mask, 0.0).sum())

    classified_units = good_units + rejected_units
    quality_percent = (
        (good_units / classified_units) * 100.0
        if classified_units > 0
        else 0.0
    )

    return {
        "count": int(len(df)),
        "summary": {
            "inspected_units": inspected_units,
            "good_units": good_units,
            "rejected_units": rejected_units,
            "good_records": int(
                (
                    df["result"].astype(str).str.upper().str.strip()
                    .isin({"GOOD", "PASS", "ACCEPT", "ACCEPTED"})
                ).sum()
                if not df.empty and "result" in df.columns
                else 0
            ),
            "reject_records": int(
                (
                    df["result"].astype(str).str.upper().str.strip()
                    .isin({"REJECT", "REJECTED", "FAIL"})
                ).sum()
                if not df.empty and "result" in df.columns
                else 0
            ),
            "quality_percent": round(quality_percent, 2),
        },
        "data": dataframe_records(result),
    }


@app.post("/api/quality")
def create_quality_inspection(inspection: QualityInspectionCreate):
    """Create one post-production quality inspection record."""

    machine_id = str(inspection.machine_id).strip()
    batch_id = str(inspection.batch_id).strip()
    part_id = str(inspection.part_id).strip()
    inspector = str(inspection.inspector).strip() or "AI_INSPECTION"

    if not machine_id or not batch_id or not part_id:
        raise HTTPException(
            status_code=400,
            detail="machine_id, batch_id and part_id are required",
        )

    inspected_units = int(inspection.inspected_units)
    if inspected_units <= 0:
        raise HTTPException(
            status_code=400,
            detail="inspected_units must be greater than 0",
        )

    normalized_result = _quality_result(inspection.result)
    if normalized_result not in {"GOOD", "REJECT"}:
        raise HTTPException(
            status_code=400,
            detail="result must be GOOD or REJECT",
        )

    rejection_reason = (
        str(inspection.rejection_reason).strip()
        if inspection.rejection_reason is not None
        else ""
    )

    if normalized_result == "REJECT" and not rejection_reason:
        raise HTTPException(
            status_code=400,
            detail="rejection_reason is required when result is REJECT",
        )

    if normalized_result == "GOOD":
        rejection_reason = ""

    metadata = read_csv_file(METADATA_FILE)
    if not metadata.empty and "machine_id" in metadata.columns:
        known_machines = set(metadata["machine_id"].astype(str))
        if machine_id not in known_machines:
            raise HTTPException(
                status_code=404,
                detail=f"Machine {machine_id} not found",
            )

    timestamp = int(inspection.timestamp) if inspection.timestamp is not None else int(_latest_operational_timestamp() or time.time())
    inspection_id = f"QI_{timestamp}_{uuid.uuid4().hex[:8].upper()}"

    columns = [
        "timestamp",
        "inspection_id",
        "machine_id",
        "batch_id",
        "part_id",
        "inspected_units",
        "result",
        "rejection_reason",
        "inspector",
    ]

    new_row = {
        "timestamp": timestamp,
        "inspection_id": inspection_id,
        "machine_id": machine_id,
        "batch_id": batch_id,
        "part_id": part_id,
        "inspected_units": inspected_units,
        "result": normalized_result,
        "rejection_reason": rejection_reason,
        "inspector": inspector,
    }

    existing = read_csv_file(QUALITY_FILE)
    if existing.empty and not QUALITY_FILE.exists():
        existing = pd.DataFrame(columns=columns)
    else:
        for column in columns:
            if column not in existing.columns:
                existing[column] = ""
        existing = existing[columns]

    updated = pd.concat(
        [existing, pd.DataFrame([new_row], columns=columns)],
        ignore_index=True,
    )
    updated.to_csv(QUALITY_FILE, index=False)

    return {
        "success": True,
        "message": "Quality inspection recorded",
        "inspection": safe_value(new_row),
    }



# ============================================================
# ENERGY / PRODUCTION / QUALITY EFFICIENCY ANALYTICS
# ============================================================

def _latest_operational_timestamp():
    """Return the latest simulation timestamp used by operational data."""
    candidates = []

    for path in (PRODUCTION_FILE, TELEMETRY_FILE):
        df = read_csv_file(path)
        if not df.empty and "timestamp" in df.columns:
            ts = pd.to_numeric(df["timestamp"], errors="coerce")
            if ts.notna().any():
                candidates.append(float(ts.max()))

    return max(candidates) if candidates else None


def _filter_time_window_from_reference(
    df: pd.DataFrame,
    hours: int,
    reference_ts: Optional[float] = None,
) -> pd.DataFrame:
    """Filter timestamped data using a shared operational reference time."""
    if df.empty or "timestamp" not in df.columns:
        return df

    result = df.copy()
    ts = _numeric_timestamp_series(result)
    valid = ts.notna()
    result = result[valid].copy()
    ts = ts[valid]

    if result.empty:
        return result

    if reference_ts is None:
        reference_ts = float(ts.max())

    start_ts = float(reference_ts) - (hours * 60 * 60)
    mask = (ts >= start_ts) & (ts <= float(reference_ts))
    return result[mask].copy()


def _quality_summary_for_window(
    machine_id: Optional[str] = None,
    hours: int = 24,
    reference_ts: Optional[float] = None,
):
    """Return inspection-based quality statistics for the latest data window."""
    df = read_csv_file(QUALITY_FILE)

    if df.empty or "timestamp" not in df.columns:
        return {
            "inspected_units": 0,
            "good_units": 0,
            "rejected_units": 0,
            "quality_percent": None,
            "inspection_records": 0,
        }

    if machine_id and "machine_id" in df.columns:
        df = df[
            df["machine_id"].astype(str) == str(machine_id)
        ]

    df = _filter_time_window_from_reference(df, hours, reference_ts)
    if df.empty:
        return {
            "inspected_units": 0,
            "good_units": 0,
            "rejected_units": 0,
            "quality_percent": None,
            "inspection_records": 0,
        }

    inspected = pd.to_numeric(
        df.get(
            "inspected_units",
            pd.Series(0.0, index=df.index),
        ),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)

    results = (
        df.get(
            "result",
            pd.Series("", index=df.index),
        )
        .astype(str)
        .str.upper()
        .str.strip()
    )

    good_mask = results.isin({
        "GOOD",
        "PASS",
        "ACCEPT",
        "ACCEPTED",
    })
    reject_mask = results.isin({
        "REJECT",
        "REJECTED",
        "FAIL",
    })

    good_units = int(inspected.where(good_mask, 0.0).sum())
    rejected_units = int(inspected.where(reject_mask, 0.0).sum())
    classified_units = good_units + rejected_units

    quality_percent = (
        (good_units / classified_units) * 100.0
        if classified_units > 0
        else None
    )

    return {
        "inspected_units": int(inspected.sum()),
        "good_units": good_units,
        "rejected_units": rejected_units,
        "quality_percent": round(quality_percent, 2)
        if quality_percent is not None
        else None,
        "inspection_records": int(len(df)),
    }


def _telemetry_efficiency_rows(
    telemetry: pd.DataFrame,
    hours: int,
    bucket_minutes: int,
    reference_ts: Optional[float] = None,
):
    """Calculate observed energy by machine using telemetry buckets."""
    if telemetry.empty or "timestamp" not in telemetry.columns:
        return pd.DataFrame(), 0, 0

    df = telemetry.copy()
    df["_timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="coerce",
    )
    df = df.dropna(subset=["_timestamp"])
    df = _filter_time_window_from_reference(
        df,
        hours,
        reference_ts,
    )

    if df.empty or "machine_id" not in df.columns:
        return pd.DataFrame(), 0, 0

    df["_power_kw"] = pd.to_numeric(
        df.get("power_kw", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)

    bucket_seconds = bucket_minutes * 60
    df["bucket_timestamp"] = (
        df["_timestamp"] // bucket_seconds
    ) * bucket_seconds

    by_machine = (
        df.groupby(
            ["bucket_timestamp", "machine_id"],
            as_index=False,
        )
        .agg(power_kw=("_power_kw", "mean"))
    )

    grouped = (
        by_machine.groupby("machine_id", as_index=False)
        .agg(
            observed_energy_kwh=("power_kw", lambda s: float(s.sum()) * (bucket_minutes / 60.0)),
            average_power_kw=("power_kw", "mean"),
            observed_buckets=("bucket_timestamp", "nunique"),
        )
    )

    expected_buckets = max(
        1,
        int((hours * 60) / bucket_minutes),
    )
    grouped["coverage_percent"] = (
        grouped["observed_buckets"]
        / expected_buckets
        * 100.0
    ).clip(upper=100.0)

    observed_bucket_count = int(
        by_machine["bucket_timestamp"].nunique()
    )

    return grouped, expected_buckets, observed_bucket_count


def _efficiency_bucket_data(
    telemetry: pd.DataFrame,
    production: pd.DataFrame,
    hours: int,
    bucket_minutes: int,
    reference_ts: Optional[float] = None,
    machine_id: Optional[str] = None,
):
    """Build aligned energy and production buckets for efficiency metrics.

    Energy is preserved as observed history, while energy-per-unit metrics use
    only buckets in which production observations actually exist. This avoids
    dividing energy collected across large telemetry gaps by output from a
    much shorter production window.
    """
    bucket_seconds = int(bucket_minutes) * 60
    bucket_hours = float(bucket_minutes) / 60.0

    # ---------------------------
    # Telemetry buckets
    # ---------------------------
    t = telemetry.copy()
    if t.empty or "timestamp" not in t.columns or "machine_id" not in t.columns:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 0

    t["_timestamp"] = pd.to_numeric(t["timestamp"], errors="coerce")
    t = t.dropna(subset=["_timestamp"])
    t = _filter_time_window_from_reference(t, hours, reference_ts)
    if machine_id:
        t = t[t["machine_id"].astype(str) == str(machine_id)]

    if t.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 0

    t["_power_kw"] = pd.to_numeric(
        t.get("power_kw", pd.Series(0.0, index=t.index)),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    t["bucket_timestamp"] = (t["_timestamp"] // bucket_seconds) * bucket_seconds

    telemetry_machine = (
        t.groupby(["bucket_timestamp", "machine_id"], as_index=False)
        .agg(power_kw=("_power_kw", "mean"))
    )

    telemetry_factory = (
        telemetry_machine.groupby("bucket_timestamp", as_index=False)
        .agg(factory_power_kw=("power_kw", "sum"))
    )

    # ---------------------------
    # Production buckets
    # ---------------------------
    pr = production.copy()
    if not pr.empty and "timestamp" in pr.columns and "machine_id" in pr.columns:
        pr["_timestamp"] = pd.to_numeric(pr["timestamp"], errors="coerce")
        pr = pr.dropna(subset=["_timestamp"])
        pr = _filter_time_window_from_reference(pr, hours, reference_ts)
        if machine_id:
            pr = pr[pr["machine_id"].astype(str) == str(machine_id)]

        if not pr.empty:
            for column in ["target_units", "actual_units", "defect_count"]:
                pr[column] = pd.to_numeric(
                    pr.get(column, pd.Series(0.0, index=pr.index)),
                    errors="coerce",
                ).fillna(0.0).clip(lower=0.0)

            # Only finished-product production contributes to output.
            pr = pr[
                (pr["target_units"] > 0.0)
                | (pr["actual_units"] > 0.0)
                | (pr["defect_count"] > 0.0)
            ].copy()

        if not pr.empty:
            pr["bucket_timestamp"] = (
                pr["_timestamp"] // bucket_seconds
            ) * bucket_seconds

            production_machine = (
                pr.sort_values(["machine_id", "_timestamp"])
                .groupby(["bucket_timestamp", "machine_id"], as_index=False)
                .tail(1)
                .copy()
            )
            production_machine["output_units"] = (
                production_machine["actual_units"] * bucket_hours
            )
            production_machine = production_machine[
                production_machine["output_units"] > 0.0
            ].copy()
        else:
            production_machine = pd.DataFrame(
                columns=["bucket_timestamp", "machine_id", "actual_units", "output_units"]
            )
    else:
        production_machine = pd.DataFrame(
            columns=["bucket_timestamp", "machine_id", "actual_units", "output_units"]
        )

    if production_machine.empty:
        production_summary = pd.DataFrame(
            columns=[
                "machine_id",
                "estimated_output_units",
                "average_production_rate_units_hr",
                "production_buckets",
            ]
        )
    else:
        production_summary = (
            production_machine.groupby("machine_id", as_index=False)
            .agg(
                estimated_output_units=("output_units", "sum"),
                average_production_rate_units_hr=("actual_units", "mean"),
                production_buckets=("bucket_timestamp", "nunique"),
            )
        )

    expected_buckets = max(
        1,
        int((hours * 60) / bucket_minutes),
    )

    return (
        telemetry_machine,
        telemetry_factory,
        production_machine,
        production_summary,
        expected_buckets,
    )


@app.get("/api/analytics/efficiency")
def efficiency_analytics(
    hours: int = 24,
    bucket_minutes: int = 15,
    machine_id: Optional[str] = None,
):
    """Link energy, production and inspection quality with aligned windows."""
    if hours not in {12, 24}:
        raise HTTPException(
            status_code=400,
            detail="hours must be 12 or 24",
        )

    bucket_minutes = max(1, min(int(bucket_minutes), 60))
    reference_ts = _latest_operational_timestamp()

    telemetry = read_csv_file(TELEMETRY_FILE)
    production = read_csv_file(PRODUCTION_FILE)

    telemetry_machine, telemetry_factory, production_machine, production_summary, expected_buckets = (
        _efficiency_bucket_data(
            telemetry,
            production,
            hours,
            bucket_minutes,
            reference_ts,
            machine_id,
        )
    )

    quality = _quality_summary_for_window(
        machine_id=machine_id,
        hours=hours,
        reference_ts=reference_ts,
    )

    observed_bucket_count = int(
        telemetry_factory["bucket_timestamp"].nunique()
    ) if not telemetry_factory.empty else 0

    production_bucket_count = int(
        production_machine["bucket_timestamp"].nunique()
    ) if not production_machine.empty else 0

    coverage_percent = round(
        min(100.0, (observed_bucket_count / expected_buckets) * 100.0),
        2,
    )
    production_coverage_percent = round(
        min(100.0, (production_bucket_count / expected_buckets) * 100.0),
        2,
    )

    if telemetry_factory.empty:
        return {
            "hours": hours,
            "bucket_minutes": bucket_minutes,
            "machine_id": machine_id,
            "coverage": {
                "expected_buckets": expected_buckets,
                "observed_buckets": 0,
                "coverage_percent": coverage_percent,
                "production_observed_buckets": production_bucket_count,
                "production_coverage_percent": production_coverage_percent,
            },
            "quality": quality,
            "summary": {
                "observed_energy_kwh": 0.0,
                "production_aligned_energy_kwh": 0.0,
                "estimated_output_units": 0.0,
                "average_factory_power_kw": 0.0,
                "energy_per_produced_unit_kwh": None,
                "estimated_good_units": None,
                "estimated_energy_per_good_unit_kwh": None,
                "good_unit_estimation_status": "NO_ENERGY_DATA",
            },
            "machines": [],
        }

    # All observed energy is kept for reporting.
    bucket_hours = bucket_minutes / 60.0
    all_energy = telemetry_machine.copy()
    all_energy["energy_kwh"] = all_energy["power_kw"] * bucket_hours

    observed_energy_by_machine = (
        all_energy.groupby("machine_id", as_index=False)
        .agg(
            observed_energy_kwh=("energy_kwh", "sum"),
            average_power_kw=("power_kw", "mean"),
            observed_buckets=("bucket_timestamp", "nunique"),
        )
    )

    # Align energy-per-unit with production buckets for the same machine.
    if production_machine.empty:
        aligned_by_machine = pd.DataFrame(
            columns=["machine_id", "production_aligned_energy_kwh"]
        )
    else:
        aligned = telemetry_machine.merge(
            production_machine[
                ["bucket_timestamp", "machine_id", "output_units", "actual_units"]
            ],
            on=["bucket_timestamp", "machine_id"],
            how="inner",
        )
        if aligned.empty:
            aligned_by_machine = pd.DataFrame(
                columns=["machine_id", "production_aligned_energy_kwh"]
            )
        else:
            aligned["energy_kwh"] = aligned["power_kw"] * bucket_hours
            aligned_by_machine = (
                aligned.groupby("machine_id", as_index=False)
                .agg(production_aligned_energy_kwh=("energy_kwh", "sum"))
            )

    machine_df = observed_energy_by_machine.merge(
        production_summary,
        on="machine_id",
        how="left",
    ).merge(
        aligned_by_machine,
        on="machine_id",
        how="left",
    )

    for column in [
        "estimated_output_units",
        "average_production_rate_units_hr",
        "production_buckets",
        "production_aligned_energy_kwh",
    ]:
        machine_df[column] = pd.to_numeric(
            machine_df.get(column, pd.Series(0.0, index=machine_df.index)),
            errors="coerce",
        ).fillna(0.0)

    # Factory-level production-aligned energy uses only periods in which some
    # production output was observed.
    if production_machine.empty:
        production_aligned_factory_energy = 0.0
    else:
        production_buckets = set(
            production_machine.loc[
                production_machine["output_units"] > 0,
                "bucket_timestamp",
            ].tolist()
        )
        aligned_factory = telemetry_factory[
            telemetry_factory["bucket_timestamp"].isin(production_buckets)
        ]
        production_aligned_factory_energy = float(
            aligned_factory["factory_power_kw"].sum() * bucket_hours
        ) if not aligned_factory.empty else 0.0

    factory_observed_energy = float(
        telemetry_factory["factory_power_kw"].sum() * bucket_hours
    )
    factory_output = float(machine_df["estimated_output_units"].sum())
    average_factory_power = float(telemetry_factory["factory_power_kw"].mean())

    energy_per_produced = (
        production_aligned_factory_energy / factory_output
        if factory_output > 0 and production_aligned_factory_energy > 0
        else None
    )

    good_unit_status = (
        "NO_INSPECTIONS"
        if quality["inspection_records"] == 0
        else "INSPECTION_SAMPLE_ONLY"
    )

    machine_records = []
    for _, row in machine_df.sort_values(
        "observed_energy_kwh",
        ascending=False,
    ).iterrows():
        machine = str(row["machine_id"])
        machine_quality = _quality_summary_for_window(
            machine_id=machine,
            hours=hours,
            reference_ts=reference_ts,
        )

        output_units = float(row["estimated_output_units"])
        aligned_energy = float(row["production_aligned_energy_kwh"])
        energy_per_unit = (
            aligned_energy / output_units
            if output_units > 0 and aligned_energy > 0
            else None
        )

        machine_records.append({
            "machine_id": machine,
            "production_contributing": bool(output_units > 0),
            "observed_energy_kwh": round(float(row["observed_energy_kwh"]), 3),
            "production_aligned_energy_kwh": round(aligned_energy, 3),
            "estimated_output_units": round(output_units, 3),
            "average_power_kw": round(float(row["average_power_kw"]), 2),
            "average_production_rate_units_hr": round(
                float(row["average_production_rate_units_hr"]),
                2,
            ),
            "energy_per_produced_unit_kwh": (
                round(energy_per_unit, 4)
                if energy_per_unit is not None
                else None
            ),
            "quality_percent": machine_quality["quality_percent"],
            "inspected_units": machine_quality["inspected_units"],
            "good_units_inspected": machine_quality["good_units"],
            "rejected_units_inspected": machine_quality["rejected_units"],
            "quality_status": (
                "INSPECTION_SAMPLE"
                if machine_quality["inspection_records"] > 0
                else "NO_INSPECTION"
            ),
            "production_buckets": int(row["production_buckets"]),
            "coverage_percent": coverage_percent,
        })

    return {
        "hours": hours,
        "bucket_minutes": bucket_minutes,
        "machine_id": machine_id,
        "coverage": {
            "expected_buckets": expected_buckets,
            "observed_buckets": observed_bucket_count,
            "coverage_percent": coverage_percent,
            "production_observed_buckets": production_bucket_count,
            "production_coverage_percent": production_coverage_percent,
        },
        "quality": quality,
        "summary": {
            "observed_energy_kwh": round(factory_observed_energy, 3),
            "production_aligned_energy_kwh": round(
                production_aligned_factory_energy,
                3,
            ),
            "estimated_output_units": round(factory_output, 3),
            "average_factory_power_kw": round(average_factory_power, 2),
            "energy_per_produced_unit_kwh": (
                round(float(energy_per_produced), 4)
                if energy_per_produced is not None
                else None
            ),
            "estimated_good_units": None,
            "estimated_energy_per_good_unit_kwh": None,
            "good_unit_estimation_status": good_unit_status,
        },
        "machines": machine_records,
    }


# ============================================================
# COMBINED MACHINE DETAIL FOR DASHBOARD
# ============================================================

@app.get("/api/machines/{machine_id}/dashboard")
def machine_dashboard_detail(
    machine_id: str,
    hours: int = 24,
):
    """Return one selected machine plus history, production, quality and health."""
    if hours not in {12, 24}:
        raise HTTPException(
            status_code=400,
            detail="hours must be 12 or 24",
        )

    machine = machine_detail(machine_id)

    telemetry = read_csv_file(TELEMETRY_FILE)
    history = _aggregate_machine_energy(
        telemetry,
        machine_id=machine_id,
        hours=hours,
        bucket_minutes=15,
    )

    reference_ts = _latest_operational_timestamp()

    production_df = read_csv_file(PRODUCTION_FILE)
    production_history = _aggregate_machine_production_history(
        production_df,
        machine_id=machine_id,
        hours=hours,
        bucket_minutes=15,
        reference_ts=reference_ts,
    )

    quality_df = read_csv_file(QUALITY_FILE)
    quality_filtered = pd.DataFrame()
    if (
        not quality_df.empty
        and "machine_id" in quality_df.columns
    ):
        quality_filtered = quality_df[
            quality_df["machine_id"].astype(str) == str(machine_id)
        ].copy()
        quality_filtered = _filter_time_window_from_reference(
            quality_filtered,
            hours,
            reference_ts,
        )

    return {
        "machine": machine,
        "energy_history": history,
        "production_history": production_history,
        "quality_history": dataframe_records(quality_filtered),
        "efficiency": efficiency_analytics(
            hours=hours,
            machine_id=machine_id,
        ),
    }


# ============================================================
# MASTER DASHBOARD ENDPOINT
# ============================================================

@app.get("/api/dashboard")
def dashboard():

    return {

        "factory":
            factory_overview(),

        "machines":
            machines(),

        "status":
            factory_status(),

        "energy_12h":
            energy_analytics(hours=12),

        "energy_24h":
            energy_analytics(hours=24),

        "production_12h":
            production_analytics(hours=12),

        "production_24h":
            production_analytics(hours=24),

        "quality":
            quality(limit=100),

        "efficiency_12h":
            efficiency_analytics(hours=12),

        "efficiency_24h":
            efficiency_analytics(hours=24),

        "grid":
            grid(
                limit=100
            ),

        "scenario":
            scenario(),

        "maintenance":
            maintenance_events(),

        "maintenance_health":
            maintenance_health(),

        "anomalies":
            anomalies(
                limit=100
            ),

        "forecast":
            forecast(),

        "production_impact":
            production_impact(),

        "flexibility":
            flexibility(),

        "decision":
            final_decision(),
    }

# ============================================================
# CONTROL / SCENARIO / WHAT-IF LAYER
# ============================================================

SUPPORTED_SCENARIOS = {
    "NORMAL": "Return the factory to normal operating conditions.",
    "GRID_STRESS": "Grid stress requiring demand reduction.",
    "PEAK_DEMAND": "Peak-demand response scenario.",
    "LOW_RENEWABLE": "Reduced renewable availability scenario.",
    "CRITICAL_GRID": "Severe grid-stress scenario.",
    "EQUIPMENT_ANOMALY": "Machine anomaly / degraded-equipment scenario.",
}

CONTROL_COMMAND_TOPIC = "/factory/control_command"
SCENARIO_COMMAND_TOPIC = "/factory/scenario_command"


def _publish_ros_string(topic: str, payload: dict) -> dict:
    """Publish a std_msgs/msg/String JSON payload through the ROS 2 CLI."""
    message_json = json.dumps(payload, separators=(",", ":"))
    ros_command = (
        "source /opt/ros/jazzy/setup.bash && "
        "source ~/INDUS_TWIN/install/setup.bash 2>/dev/null || true; "
        f"ros2 topic pub --once {shlex.quote(topic)} std_msgs/msg/String "
        f"{shlex.quote('{data: ' + json.dumps(message_json) + '}')}"
    )

    try:
        completed = subprocess.run(
            ["bash", "-lc", ros_command],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="ROS 2 command timed out",
        )

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "ROS 2 publish failed").strip()
        raise HTTPException(status_code=502, detail=detail)

    return {
        "published": True,
        "topic": topic,
        "payload": payload,
    }


def _latest_machine_row(machine_id: str) -> dict:
    telemetry = read_csv_file(TELEMETRY_FILE)
    if telemetry.empty or "machine_id" not in telemetry.columns:
        raise HTTPException(status_code=404, detail="Telemetry unavailable")

    rows = telemetry[
        telemetry["machine_id"].astype(str).str.strip() == machine_id
    ]
    if rows.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Machine {machine_id} not found in telemetry",
        )
    return dataframe_records(rows.tail(1))[0]


def _machine_metadata(machine_id: str) -> dict:
    metadata = read_csv_file(METADATA_FILE)
    if metadata.empty or "machine_id" not in metadata.columns:
        raise HTTPException(status_code=500, detail="Machine metadata unavailable")
    rows = metadata[
        metadata["machine_id"].astype(str).str.strip() == machine_id
    ]
    if rows.empty:
        raise HTTPException(status_code=404, detail=f"Machine {machine_id} not found")
    return dataframe_records(rows.tail(1))[0]


def _latest_maintenance_label(machine_id: str) -> str:
    maintenance = read_csv_file(MAINTENANCE_OUTPUT_FILE)
    if maintenance.empty or "machine_id" not in maintenance.columns:
        return "UNKNOWN"
    rows = maintenance[
        maintenance["machine_id"].astype(str).str.strip() == machine_id
    ]
    if rows.empty:
        return "UNKNOWN"
    return str(rows.tail(1).iloc[0].get("maintenance_label", "UNKNOWN")).upper()


def _latest_production_safety(machine_id: str) -> dict:
    production = read_csv_file(PRODUCTION_IMPACT_FILE)
    if production.empty or "machine_id" not in production.columns:
        return {
            "safe_to_reduce": False,
            "production_safe": False,
            "production_loss_percent": 0.0,
            "reason": "PRODUCTION_IMPACT_UNAVAILABLE",
        }

    rows = production[
        production["machine_id"].astype(str).str.strip() == machine_id
    ]
    if rows.empty:
        return {
            "safe_to_reduce": False,
            "production_safe": False,
            "production_loss_percent": 0.0,
            "reason": "NO_PRODUCTION_IMPACT_RECORD",
        }

    row = rows.tail(1).iloc[0]
    safe_value = row.get("safe_to_reduce", False)
    production_safe = row.get("production_safe", safe_value)
    return {
        "safe_to_reduce": str(safe_value).strip().lower() in {"true", "1", "yes"},
        "production_safe": str(production_safe).strip().lower() in {"true", "1", "yes"},
        "production_loss_percent": float(pd.to_numeric(row.get("production_loss_percent", 0.0), errors="coerce") or 0.0),
        "reason": str(row.get("recommendation", "UNKNOWN")),
    }


def _validate_control_reduction(machine_id: str, target_kw: float) -> dict:
    """Apply conservative validation before a web control reaches ROS 2."""
    current = _latest_machine_row(machine_id)
    metadata = _machine_metadata(machine_id)

    current_kw = float(pd.to_numeric(current.get("power_kw", 0.0), errors="coerce") or 0.0)
    controllability = str(metadata.get("controllability", "")).upper()
    criticality = str(metadata.get("criticality", "")).upper()

    try:
        min_power = float(metadata.get("min_operating_power_kw", 0.0))
    except (TypeError, ValueError):
        min_power = 0.0

    if controllability == "FIXED":
        return {"allowed": False, "reason": "FIXED_MACHINE_PROTECTED"}

    maintenance_label = _latest_maintenance_label(machine_id)
    if maintenance_label in {"HIGH", "CRITICAL"}:
        return {"allowed": False, "reason": "HIGH_MAINTENANCE_RISK_PROTECTED"}

    production = _latest_production_safety(machine_id)
    if not (production["safe_to_reduce"] and production["production_safe"]):
        return {"allowed": False, "reason": production["reason"]}

    if target_kw >= current_kw:
        return {"allowed": False, "reason": "TARGET_NOT_BELOW_CURRENT_POWER"}

    if target_kw < min_power:
        return {"allowed": False, "reason": "TARGET_BELOW_MIN_OPERATING_POWER"}

    return {
        "allowed": True,
        "reason": "VALIDATED",
        "current_power_kw": round(current_kw, 3),
        "target_power_kw": round(target_kw, 3),
        "reduction_kw": round(current_kw - target_kw, 3),
        "criticality": criticality,
        "controllability": controllability,
        "maintenance_label": maintenance_label,
        "production_loss_percent": round(production["production_loss_percent"], 3),
    }


class ControlCommandCreate(BaseModel):
    machine_id: str
    action: str
    target_kw: Optional[float] = None
    duration_sec: int = 900
    load_percent: Optional[float] = None
    temperature_offset_c: float = 0.0
    vibration_offset_mm_s: float = 0.0
    source: str = "DASHBOARD"


class ScenarioCommandCreate(BaseModel):
    action: str = "START"
    scenario_id: str
    source: str = "DASHBOARD"


class WhatIfRequest(BaseModel):
    scenario_id: str = "GRID_STRESS"
    required_reduction_kw: Optional[float] = None
    duration_min: int = 15
    apply: bool = False


@app.get("/api/control/status")
def control_status():
    """Return the current machine control state as observed from telemetry."""
    telemetry = read_csv_file(TELEMETRY_FILE)
    latest = latest_per_machine(telemetry)
    records = []
    if not latest.empty:
        for row in dataframe_records(latest):
            state = str(row.get("state", "UNKNOWN")).upper()
            records.append({
                "machine_id": row.get("machine_id"),
                "state": state,
                "power_kw": row.get("power_kw"),
                "load_percent": row.get("load_percent"),
                "control_active": state in {"REDUCED", "CURTAILED", "SHIFTED", "CONTROLLED"},
                "timestamp": row.get("timestamp"),
            })
    return {"count": len(records), "machines": records}


@app.post("/api/control")
def control(command: ControlCommandCreate):
    """Validate and publish a machine control command to ROS 2."""
    machine_id = str(command.machine_id).strip()
    action = str(command.action).strip().upper()
    duration_sec = max(1, min(int(command.duration_sec), 3600))
    source = str(command.source).strip() or "DASHBOARD"

    _machine_metadata(machine_id)

    if action == "REDUCE_LOAD":
        if command.target_kw is None:
            raise HTTPException(status_code=400, detail="target_kw is required for REDUCE_LOAD")
        target_kw = float(command.target_kw)
        validation = _validate_control_reduction(machine_id, target_kw)
        if not validation["allowed"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": validation["reason"],
                    "machine_id": machine_id,
                },
            )
        payload = {
            "timestamp": int(time.time()),
            "source": source,
            "machine_id": machine_id,
            "command": "REDUCE_LOAD",
            "target_kw": round(target_kw, 2),
            "duration_sec": duration_sec,
        }

    elif action == "RESTORE_NORMAL":
        payload = {
            "timestamp": int(time.time()),
            "source": source,
            "machine_id": machine_id,
            "command": "RESTORE_NORMAL",
        }
        validation = {"allowed": True, "reason": "RESTORE_REQUESTED"}

    elif action == "SET_LOAD":
        if command.load_percent is None:
            raise HTTPException(status_code=400, detail="load_percent is required for SET_LOAD")
        load_percent = max(0.0, min(float(command.load_percent), 130.0))
        payload = {
            "timestamp": int(time.time()),
            "source": source,
            "machine_id": machine_id,
            "command": "SET_LOAD",
            "load_percent": round(load_percent, 2),
            "temperature_offset_c": float(command.temperature_offset_c),
            "vibration_offset_mm_s": float(command.vibration_offset_mm_s),
            "duration_sec": duration_sec,
        }
        validation = {"allowed": True, "reason": "ANOMALY_INJECTION_REQUESTED"}

    else:
        raise HTTPException(
            status_code=400,
            detail="action must be REDUCE_LOAD, RESTORE_NORMAL or SET_LOAD",
        )

    published = _publish_ros_string(CONTROL_COMMAND_TOPIC, payload)
    return {
        "success": True,
        "action": action,
        "validation": validation,
        **published,
    }


@app.get("/api/scenarios")
def scenarios():
    """Return supported scenario controls and latest scenario state."""
    latest = scenario()
    return {
        "supported": [
            {"scenario_id": key, "description": value}
            for key, value in SUPPORTED_SCENARIOS.items()
        ],
        "latest": latest.get("latest", {}),
    }


@app.post("/api/scenario")
def scenario_command(command: ScenarioCommandCreate):
    """Start/stop a scenario through the ROS 2 scenario manager."""
    action = str(command.action).strip().upper()
    scenario_id = str(command.scenario_id).strip().upper()

    if action not in {"START", "STOP"}:
        raise HTTPException(status_code=400, detail="action must be START or STOP")
    if scenario_id not in SUPPORTED_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported scenario_id: {scenario_id}",
        )

    payload = {
        "action": action,
        "scenario_id": scenario_id,
        "source": str(command.source).strip() or "DASHBOARD",
        "timestamp": int(time.time()),
    }
    published = _publish_ros_string(SCENARIO_COMMAND_TOPIC, payload)
    return {
        "success": True,
        "scenario_id": scenario_id,
        "action": action,
        **published,
    }


@app.post("/api/what-if")
def what_if(request: WhatIfRequest):
    """
    Run a non-destructive what-if flexibility simulation.

    The default behaviour is analysis only. When apply=true, only reductions
    that pass the same conservative validation used by /api/control are sent
    to ROS 2.
    """
    scenario_id = str(request.scenario_id).strip().upper()
    duration_min = max(1, min(int(request.duration_min), 120))

    if scenario_id not in SUPPORTED_SCENARIOS:
        raise HTTPException(status_code=400, detail=f"Unsupported scenario_id: {scenario_id}")

    grid_df = read_csv_file(GRID_FILE)
    required = 0.0
    if request.required_reduction_kw is not None:
        required = max(0.0, float(request.required_reduction_kw))
    elif not grid_df.empty and "required_reduction_kw" in grid_df.columns:
        latest_grid = latest_record(grid_df)
        try:
            required = max(0.0, float(latest_grid.get("required_reduction_kw", 0.0)))
        except (TypeError, ValueError):
            required = 0.0

    if scenario_id == "NORMAL":
        required = 0.0

    flex = read_csv_file(FLEXIBILITY_FILE)
    optimizer = read_csv_file(AI_DIR / "optimization_output.csv")
    machine_rows = []

    if not flex.empty and "machine_id" in flex.columns:
        flex_latest = latest_per_machine(flex)
        for row in dataframe_records(flex_latest):
            machine_id = str(row.get("machine_id", "")).strip()
            deployable = float(pd.to_numeric(row.get("deployable_flexibility_kw", 0.0), errors="coerce") or 0.0)
            if deployable <= 0.0 or not machine_id:
                continue

            maint = _latest_maintenance_label(machine_id)
            metadata = _machine_metadata(machine_id)
            controllability = str(metadata.get("controllability", "")).upper()
            criticality = str(metadata.get("criticality", "")).upper()
            if controllability == "FIXED" or maint in {"HIGH", "CRITICAL"}:
                continue

            machine_rows.append({
                "machine_id": machine_id,
                "deployable_flexibility_kw": deployable,
                "criticality": criticality,
                "controllability": controllability,
                "maintenance_label": maint,
            })

    # Read optimizer decisions only as optional refinements. The optimizer CSV
    # can contain interleaved scenario runs or zero-reduction rows; the what-if
    # calculation must not let such a row erase safe flexibility identified by
    # the scenario-aware flexibility stage.
    optimizer_actions = {}
    optimizer_scenario_matches = False
    if not optimizer.empty and "machine_id" in optimizer.columns:
        # Filter optimizer rows by the requested scenario BEFORE selecting the
        # latest row for each machine. A global scenario check is unsafe because
        # optimization_output.csv may contain interleaved NORMAL and scenario
        # runs; one matching row must not cause unrelated NORMAL rows to be used.
        scenario_opt = optimizer.copy()
        if "scenario_id" in scenario_opt.columns:
            scenario_opt["_scenario_norm"] = (
                scenario_opt["scenario_id"].fillna("").astype(str).str.strip().str.upper()
            )
            scenario_opt = scenario_opt[scenario_opt["_scenario_norm"] == scenario_id].copy()
        else:
            scenario_opt = pd.DataFrame()

        latest_opt = latest_per_machine(scenario_opt) if not scenario_opt.empty else pd.DataFrame()
        optimizer_scenario_matches = not latest_opt.empty
        if optimizer_scenario_matches:
            for row in dataframe_records(latest_opt):
                optimizer_actions[str(row.get("machine_id", "")).strip()] = row

    for item in machine_rows:
        opt = optimizer_actions.get(item["machine_id"], {})

        # The flexibility stage is the authoritative source for a non-destructive
        # what-if calculation because it already encodes controllability,
        # criticality, maintenance risk, production safety, and scenario context.
        # Optimizer output is used only as a refinement when it contains a
        # positive scenario-specific reduction. A zero-reduction optimizer row
        # must never erase a valid safe flexibility value.
        safe_flex = float(item["deployable_flexibility_kw"])
        optimized = pd.to_numeric(
            opt.get("optimized_reduction_kw", 0.0),
            errors="coerce",
        ) if opt else 0.0
        optimized_value = float(optimized) if pd.notna(optimized) else 0.0

        if optimizer_scenario_matches and opt and optimized_value > 0.0:
            item["optimizer_action"] = str(opt.get("optimization_action", "REDUCE")).upper()
            item["optimized_reduction_kw"] = min(safe_flex, optimized_value)
        else:
            item["optimizer_action"] = "CANDIDATE"
            item["optimized_reduction_kw"] = safe_flex

    priority = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    machine_rows.sort(
        key=lambda x: (
            x["optimizer_action"] != "REDUCE",
            priority.get(x["criticality"], 1),
            -x["deployable_flexibility_kw"],
        )
    )

    selected = []
    reduction = 0.0
    for item in machine_rows:
        available = min(
            item["deployable_flexibility_kw"],
            max(0.0, item["optimized_reduction_kw"]),
        )
        if available <= 0.0 or reduction >= required:
            continue
        take = min(available, required - reduction)
        selected.append({
            **item,
            "selected_reduction_kw": round(take, 3),
        })
        reduction += take

    current_demand = 0.0
    telemetry = read_csv_file(TELEMETRY_FILE)
    latest_telemetry = latest_per_machine(telemetry)
    if not latest_telemetry.empty and "power_kw" in latest_telemetry.columns:
        current_demand = float(
            pd.to_numeric(latest_telemetry["power_kw"], errors="coerce")
            .fillna(0.0).sum()
        )

    protected = []
    if not latest_telemetry.empty:
        for row in dataframe_records(latest_telemetry):
            machine_id = str(row.get("machine_id", "")).strip()
            if machine_id not in {x["machine_id"] for x in selected}:
                protected.append(machine_id)

    shortfall = max(0.0, required - reduction)
    projected_demand = max(0.0, current_demand - reduction)
    reserve_status = "SUFFICIENT" if reduction >= required and required > 0 else (
        "NO_REDUCTION_REQUIRED" if required <= 0 else "INSUFFICIENT"
    )

    apply_results = []
    if request.apply and selected:
        for item in selected:
            machine_id = item["machine_id"]
            current = _latest_machine_row(machine_id)
            current_kw = float(pd.to_numeric(current.get("power_kw", 0.0), errors="coerce") or 0.0)
            target_kw = current_kw - item["selected_reduction_kw"]
            validation = _validate_control_reduction(machine_id, target_kw)
            if validation.get("allowed"):
                payload = {
                    "timestamp": int(time.time()),
                    "source": "WHAT_IF",
                    "machine_id": machine_id,
                    "command": "REDUCE_LOAD",
                    "target_kw": round(target_kw, 2),
                    "duration_sec": duration_min * 60,
                }
                _publish_ros_string(CONTROL_COMMAND_TOPIC, payload)
                apply_results.append({
                    "machine_id": machine_id,
                    "applied": True,
                    "target_kw": round(target_kw, 2),
                })
            else:
                apply_results.append({
                    "machine_id": machine_id,
                    "applied": False,
                    "reason": validation.get("reason"),
                })

    return {
        "success": True,
        "scenario_id": scenario_id,
        "analysis_only": not request.apply,
        "duration_min": duration_min,
        "current_factory_power_kw": round(current_demand, 2),
        "required_reduction_kw": round(required, 2),
        "safe_deployable_flexibility_kw": round(
            sum(x["deployable_flexibility_kw"] for x in machine_rows), 2
        ),
        "simulated_selected_reduction_kw": round(reduction, 2),
        "projected_factory_power_kw": round(projected_demand, 2),
        "shortfall_kw": round(shortfall, 2),
        "reserve_status": reserve_status,
        "selected_loads": selected,
        "protected_machines": protected,
        "recommendation": (
            "DEPLOY_SELECTED_FLEXIBILITY"
            if reduction > 0 and shortfall == 0
            else "DEPLOY_AVAILABLE_FLEXIBILITY_AND_REPORT_GAP"
            if reduction > 0
            else "NO_SAFE_FLEXIBILITY_SELECTED"
        ),
        "apply_results": apply_results,
    }
