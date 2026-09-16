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
GRID_DIR = DATA_DIR / "04_grid"
SCENARIO_DIR = DATA_DIR / "05_scenarios"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
GRID_FILE = GRID_DIR / "grid_data.csv"
SCENARIO_FILE = SCENARIO_DIR / "scenario_data.csv"

OUT_FILE = BASE_DIR / "forecast_output.csv"


# ============================================================
# SETTINGS
# ============================================================

DEFAULT_HORIZONS_MIN = [15, 30, 60]
MAX_HISTORY = 30
MIN_POINTS_FOR_TREND = 5
EPS = 1e-6


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        return df

    except Exception as exc:
        print(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def numeric(
    df: pd.DataFrame,
    column: str,
    default: float = np.nan
) -> pd.Series:

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


# ============================================================
# MACHINE FORECAST
# ============================================================

def forecast_for_machine(
    df_machine: pd.DataFrame,
    horizons_min: list[int] | None = None
) -> dict:

    if horizons_min is None:
        horizons_min = DEFAULT_HORIZONS_MIN

    if df_machine.empty:
        return {
            f"pred_{m}min": 0.0
            for m in horizons_min
        }

    dfm = df_machine.copy()

    dfm.columns = [
        str(c).strip()
        for c in dfm.columns
    ]

    if "power_kw" not in dfm.columns:
        return {
            f"pred_{m}min": 0.0
            for m in horizons_min
        }

    if "timestamp" not in dfm.columns:
        last_power = float(
            pd.to_numeric(
                dfm["power_kw"],
                errors="coerce"
            )
            .dropna()
            .iloc[-1]
        )

        return {
            f"pred_{m}min": last_power
            for m in horizons_min
        }

    dfm["timestamp"] = pd.to_numeric(
        dfm["timestamp"],
        errors="coerce"
    )

    dfm["power_kw"] = pd.to_numeric(
        dfm["power_kw"],
        errors="coerce"
    )

    dfm = (
        dfm
        .dropna(subset=["timestamp", "power_kw"])
        .sort_values("timestamp")
        .tail(MAX_HISTORY)
        .reset_index(drop=True)
    )

    if dfm.empty:
        return {
            f"pred_{m}min": 0.0
            for m in horizons_min
        }

    last_power = float(
        dfm["power_kw"].iloc[-1]
    )

    # --------------------------------------------------------
    # Not enough data for a reliable trend
    # --------------------------------------------------------

    if len(dfm) < MIN_POINTS_FOR_TREND:

        return {
            f"pred_{m}min": last_power
            for m in horizons_min
        }

    x = dfm["timestamp"].to_numpy(
        dtype=float
    )

    y = dfm["power_kw"].to_numpy(
        dtype=float
    )

    if np.allclose(
        x,
        x[0]
    ):

        return {
            f"pred_{m}min": last_power
            for m in horizons_min
        }

    # --------------------------------------------------------
    # Center timestamps for numerical stability
    # --------------------------------------------------------

    x0 = x[-1]

    x_relative = (
        x - x0
    )

    # --------------------------------------------------------
    # Linear trend
    # --------------------------------------------------------

    try:

        slope, intercept = np.polyfit(
            x_relative,
            y,
            1
        )

    except Exception:

        return {
            f"pred_{m}min": last_power
            for m in horizons_min
        }

    # --------------------------------------------------------
    # Limit extreme trends.
    #
    # This is a prototype safeguard so that one noisy sample
    # doesn't create an absurd 60-minute prediction.
    # --------------------------------------------------------

    max_rate_per_min = max(
        1.0,
        abs(last_power) * 0.05
    )

    slope_per_min = (
        slope * 60.0
    )

    slope_per_min = np.clip(
        slope_per_min,
        -max_rate_per_min,
        max_rate_per_min
    )

    slope = (
        slope_per_min / 60.0
    )

    # --------------------------------------------------------
    # Predictions
    # --------------------------------------------------------

    predictions = {}

    for minutes in horizons_min:

        future_seconds = (
            minutes * 60.0
        )

        predicted = (
            intercept
            + slope
            * future_seconds
        )

        # Prevent negative power.
        predicted = max(
            0.0,
            float(predicted)
        )

        predictions[
            f"pred_{minutes}min"
        ] = predicted

    return predictions


# ============================================================
# OPTIONAL GRID CONTEXT
# ============================================================

def load_latest_grid_context() -> dict:

    grid = load_csv(
        GRID_FILE
    )

    if grid.empty or "timestamp" not in grid.columns:
        return {
            "grid_status": "UNKNOWN",
            "factory_demand_kw": np.nan,
            "available_grid_power_kw": np.nan,
            "grid_stress_level": np.nan,
            "required_reduction_kw": np.nan
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
            "factory_demand_kw": np.nan,
            "available_grid_power_kw": np.nan,
            "grid_stress_level": np.nan,
            "required_reduction_kw": np.nan
        }

    latest = grid.iloc[-1]

    return {
        "grid_status": latest.get(
            "grid_status",
            "UNKNOWN"
        ),
        "factory_demand_kw": pd.to_numeric(
            latest.get(
                "factory_demand_kw"
            ),
            errors="coerce"
        ),
        "available_grid_power_kw": pd.to_numeric(
            latest.get(
                "available_grid_power_kw"
            ),
            errors="coerce"
        ),
        "grid_stress_level": pd.to_numeric(
            latest.get(
                "grid_stress_level"
            ),
            errors="coerce"
        ),
        "required_reduction_kw": pd.to_numeric(
            latest.get(
                "required_reduction_kw"
            ),
            errors="coerce"
        )
    }


# ============================================================
# LATEST SCENARIO
# ============================================================

def load_latest_scenario() -> dict:

    scenario = load_csv(
        SCENARIO_FILE
    )

    if scenario.empty or "timestamp" not in scenario.columns:

        return {
            "scenario_id": "UNKNOWN",
            "scenario_type": "UNKNOWN",
            "scenario_name": "Unknown"
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
            "scenario_type": "UNKNOWN",
            "scenario_name": "Unknown"
        }

    latest = scenario.iloc[-1]

    return {
        "scenario_id": latest.get(
            "scenario_id",
            "UNKNOWN"
        ),
        "scenario_type": latest.get(
            "scenario_type",
            "UNKNOWN"
        ),
        "scenario_name": latest.get(
            "scenario_name",
            "Unknown"
        )
    }


# ============================================================
# MAIN FORECAST
# ============================================================

def run_forecast(
    telemetry_df: pd.DataFrame | None = None,
    horizons_min: list[int] | None = None
) -> pd.DataFrame:

    if horizons_min is None:
        horizons_min = DEFAULT_HORIZONS_MIN

    # --------------------------------------------------------
    # Load telemetry
    # --------------------------------------------------------

    if telemetry_df is None:

        telemetry_df = load_csv(
            TELEMETRY_FILE
        )

    if telemetry_df.empty:

        print(
            "Telemetry file not found or empty."
        )

        return pd.DataFrame()

    telemetry_df = telemetry_df.copy()

    telemetry_df.columns = [
        str(c).strip()
        for c in telemetry_df.columns
    ]

    if "machine_id" not in telemetry_df.columns:

        raise KeyError(
            "Telemetry missing 'machine_id'."
        )

    if "power_kw" not in telemetry_df.columns:

        raise KeyError(
            "Telemetry missing 'power_kw'."
        )

    telemetry_df["machine_id"] = (
        telemetry_df["machine_id"]
        .astype(str)
        .str.strip()
    )

    telemetry_df["timestamp"] = pd.to_numeric(
        telemetry_df["timestamp"],
        errors="coerce"
    )

    telemetry_df["power_kw"] = pd.to_numeric(
        telemetry_df["power_kw"],
        errors="coerce"
    )

    telemetry_df = (
        telemetry_df
        .dropna(
            subset=[
                "machine_id",
                "timestamp",
                "power_kw"
            ]
        )
        .sort_values(
            [
                "machine_id",
                "timestamp"
            ]
        )
    )

    # --------------------------------------------------------
    # Latest external context
    # --------------------------------------------------------

    grid_context = load_latest_grid_context()
    scenario_context = load_latest_scenario()

    # --------------------------------------------------------
    # Forecast every machine
    # --------------------------------------------------------

    rows = []

    for machine_id, group in telemetry_df.groupby(
        "machine_id"
    ):

        group = group.sort_values(
            "timestamp"
        )

        last_row = group.iloc[-1]

        predictions = forecast_for_machine(
            group,
            horizons_min
        )

        row = {
            "timestamp": int(
                last_row["timestamp"]
            ),
            "machine_id": machine_id,
            "last_power_kw": float(
                last_row["power_kw"]
            )
        }

        row.update(
            predictions
        )

        # External grid context is included for downstream
        # decision-making, but is NOT artificially added to
        # the machine power prediction.
        row.update(
            grid_context
        )

        row.update(
            scenario_context
        )

        rows.append(row)

    out = pd.DataFrame(
        rows
    )

    # --------------------------------------------------------
    # Add forecast trend
    # --------------------------------------------------------

    if (
        "pred_15min" in out.columns
        and "last_power_kw" in out.columns
    ):

        out["forecast_change_15min_kw"] = (
            out["pred_15min"]
            - out["last_power_kw"]
        )

    if (
        "pred_60min" in out.columns
        and "last_power_kw" in out.columns
    ):

        out["forecast_change_60min_kw"] = (
            out["pred_60min"]
            - out["last_power_kw"]
        )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print(
        f"\nSaved forecast -> {OUT_FILE}"
    )

    print(
        f"Machines forecast: "
        f"{len(out)}"
    )

    if not out.empty:

        print(
            "\n=== FORECAST ==="
        )

        display_columns = [
            "machine_id",
            "last_power_kw",
            "pred_15min",
            "pred_30min",
            "pred_60min",
            "forecast_change_60min_kw"
        ]

        display_columns = [
            c
            for c in display_columns
            if c in out.columns
        ]

        print(
            out[
                display_columns
            ].to_string(
                index=False
            )
        )

        print(
            "\n=== GRID CONTEXT ==="
        )

        print(
            f"Status: "
            f"{grid_context['grid_status']}"
        )

        print(
            f"Factory demand: "
            f"{grid_context['factory_demand_kw']}"
        )

        print(
            f"Available grid: "
            f"{grid_context['available_grid_power_kw']}"
        )

        print(
            f"Grid stress: "
            f"{grid_context['grid_stress_level']}"
        )

        print(
            f"Required reduction: "
            f"{grid_context['required_reduction_kw']}"
        )

        print(
            "\n=== SCENARIO ==="
        )

        print(
            f"{scenario_context['scenario_id']} | "
            f"{scenario_context['scenario_type']} | "
            f"{scenario_context['scenario_name']}"
        )

    return out


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    run_forecast()