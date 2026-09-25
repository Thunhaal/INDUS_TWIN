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

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
OUT_FILE = BASE_DIR / "maintenance_output.csv"


# ============================================================
# SETTINGS
# ============================================================

TEMPERATURE_WEIGHT = 0.50
VIBRATION_WEIGHT = 0.40
RPM_WEIGHT = 0.10

LOW_RISK_THRESHOLD = 0.15
MEDIUM_RISK_THRESHOLD = 0.40
HIGH_RISK_THRESHOLD = 0.70

Z_MEDIUM = 3.0
Z_HIGH = 4.0

ROLLING_WINDOW = 30

EPS = 1e-6


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV safely and normalize column names."""

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
    """Return a numeric column, creating it if necessary."""

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


def past_rolling_mean(
    series: pd.Series,
    window: int = ROLLING_WINDOW
) -> pd.Series:
    """
    Calculate a past-only rolling mean.

    shift(1) prevents the current observation from
    influencing its own baseline.
    """

    return (
        series
        .shift(1)
        .rolling(
            window=window,
            min_periods=3
        )
        .mean()
    )


def past_rolling_std(
    series: pd.Series,
    window: int = ROLLING_WINDOW
) -> pd.Series:
    """
    Calculate a past-only rolling standard deviation.
    """

    return (
        series
        .shift(1)
        .rolling(
            window=window,
            min_periods=3
        )
        .std(ddof=0)
    )


def fill_stat_fallback(
    current: pd.Series,
    series: pd.Series
) -> pd.Series:
    """
    Fill unavailable rolling statistics with expanding
    past-only statistics, then a safe constant.
    """

    fallback = (
        series
        .shift(1)
        .expanding(
            min_periods=2
        )
        .mean()
    )

    result = current.fillna(fallback)

    return result


def fill_std_fallback(
    current: pd.Series,
    series: pd.Series
) -> pd.Series:
    """
    Fill unavailable rolling standard deviation with
    expanding past-only standard deviation.
    """

    fallback = (
        series
        .shift(1)
        .expanding(
            min_periods=2
        )
        .std(ddof=0)
    )

    result = current.fillna(
        fallback
    )

    return (
        result
        .replace(
            [np.inf, -np.inf],
            np.nan
        )
        .replace(
            0,
            np.nan
        )
        .fillna(1.0)
    )


def add_past_zscore(
    df: pd.DataFrame,
    value_column: str,
    mean_column: str,
    std_column: str,
    z_column: str
) -> pd.DataFrame:
    """
    Add machine-specific past-only mean, std and z-score.

    This function works group-by-group explicitly so that
    pandas receives one-dimensional Series at every step.
    """

    means = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    stds = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    zscores = pd.Series(
        np.nan,
        index=df.index,
        dtype=float
    )

    for machine_id, indices in df.groupby(
        "machine_id"
    ).groups.items():

        values = df.loc[
            indices,
            value_column
        ].copy()

        mean_series = past_rolling_mean(
            values
        )

        std_series = past_rolling_std(
            values
        )

        mean_series = fill_stat_fallback(
            mean_series,
            values
        )

        # For very early observations, use a fixed safe value.
        mean_series = mean_series.fillna(
            values.iloc[0]
            if len(values) > 0
            else 0.0
        )

        std_series = fill_std_fallback(
            std_series,
            values
        )

        z_series = (
            values
            - mean_series
        ) / (
            std_series
            + EPS
        )

        means.loc[indices] = mean_series.values
        stds.loc[indices] = std_series.values
        zscores.loc[indices] = z_series.values

    df[mean_column] = means
    df[std_column] = stds
    df[z_column] = zscores

    return df


# ============================================================
# MAIN MAINTENANCE RISK
# ============================================================

def compute_maintenance_risk(
    telemetry_df: pd.DataFrame | None = None
) -> pd.DataFrame:

    # --------------------------------------------------------
    # 1. Load telemetry
    # --------------------------------------------------------

    if telemetry_df is None:
        telemetry_df = load_csv(
            TELEMETRY_FILE
        )

    if telemetry_df.empty:
        print(
            "Telemetry file missing or empty."
        )
        return pd.DataFrame()

    df = telemetry_df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    # --------------------------------------------------------
    # 2. Validate required columns
    # --------------------------------------------------------

    required = {
        "timestamp",
        "machine_id"
    }

    missing = required - set(
        df.columns
    )

    if missing:
        raise KeyError(
            "Telemetry missing required columns: "
            + ", ".join(sorted(missing))
        )

    # --------------------------------------------------------
    # 3. Normalize identity/time
    # --------------------------------------------------------

    df["machine_id"] = (
        df["machine_id"]
        .astype(str)
        .str.strip()
    )

    df["timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="coerce"
    )

    # --------------------------------------------------------
    # 4. Health measurements
    # --------------------------------------------------------

    df["temperature_c"] = numeric(
        df,
        "temperature_c",
        default=0.0
    )

    df["vibration_mm_s"] = numeric(
        df,
        "vibration_mm_s",
        default=0.0
    )

    df["rpm"] = numeric(
        df,
        "rpm",
        default=0.0
    )

    # --------------------------------------------------------
    # 5. Sort chronologically within machine
    # --------------------------------------------------------

    df = (
        df
        .dropna(
            subset=[
                "timestamp",
                "machine_id"
            ]
        )
        .sort_values(
            [
                "machine_id",
                "timestamp"
            ]
        )
        .reset_index(drop=True)
    )

    if df.empty:
        return pd.DataFrame()

    # --------------------------------------------------------
    # 6. Temperature statistics
    # --------------------------------------------------------

    df = add_past_zscore(
        df,
        value_column="temperature_c",
        mean_column="temperature_baseline_c",
        std_column="temperature_std_c",
        z_column="temperature_zscore"
    )

    df["temperature_deviation_c"] = (
        df["temperature_c"]
        - df["temperature_baseline_c"]
    )

    # --------------------------------------------------------
    # 7. Vibration statistics
    # --------------------------------------------------------

    df = add_past_zscore(
        df,
        value_column="vibration_mm_s",
        mean_column="vibration_baseline_mm_s",
        std_column="vibration_std_c",
        z_column="vibration_zscore"
    )

    df["vibration_deviation_mm_s"] = (
        df["vibration_mm_s"]
        - df["vibration_baseline_mm_s"]
    )

    # --------------------------------------------------------
    # 8. RPM statistics
    # --------------------------------------------------------

    df = add_past_zscore(
        df,
        value_column="rpm",
        mean_column="rpm_baseline",
        std_column="rpm_std",
        z_column="rpm_zscore"
    )

    df["rpm_deviation"] = (
        df["rpm"]
        - df["rpm_baseline"]
    )

    # --------------------------------------------------------
    # 9. Sensor anomaly flags
    # --------------------------------------------------------

    df["temperature_anomaly"] = (
        df["temperature_zscore"].abs()
        >= Z_MEDIUM
    )

    df["vibration_anomaly"] = (
        df["vibration_zscore"].abs()
        >= Z_MEDIUM
    )

    df["rpm_anomaly"] = (
        df["rpm_zscore"].abs()
        >= Z_MEDIUM
    )

    df["severe_temperature_anomaly"] = (
        df["temperature_zscore"].abs()
        >= Z_HIGH
    )

    df["severe_vibration_anomaly"] = (
        df["vibration_zscore"].abs()
        >= Z_HIGH
    )

    df["severe_rpm_anomaly"] = (
        df["rpm_zscore"].abs()
        >= Z_HIGH
    )

    # --------------------------------------------------------
    # 10. Normalized sensor strengths
    # --------------------------------------------------------

    temperature_strength = (
        df["temperature_zscore"].abs()
        / Z_HIGH
    ).clip(
        0.0,
        1.0
    )

    vibration_strength = (
        df["vibration_zscore"].abs()
        / Z_HIGH
    ).clip(
        0.0,
        1.0
    )

    rpm_strength = (
        df["rpm_zscore"].abs()
        / Z_HIGH
    ).clip(
        0.0,
        1.0
    )

    # --------------------------------------------------------
    # 11. Weighted maintenance risk
    # --------------------------------------------------------

    df["risk_raw"] = (
        temperature_strength
        * TEMPERATURE_WEIGHT
        +
        vibration_strength
        * VIBRATION_WEIGHT
        +
        rpm_strength
        * RPM_WEIGHT
    )

    df["maintenance_risk"] = (
        np.tanh(
            df["risk_raw"] * 2.0
        )
        .clip(
            0.0,
            1.0
        )
    )

    # --------------------------------------------------------
    # 12. Maintenance label
    # --------------------------------------------------------

    def risk_label(
        risk: float
    ) -> str:

        if risk >= HIGH_RISK_THRESHOLD:
            return "HIGH"

        if risk >= MEDIUM_RISK_THRESHOLD:
            return "MEDIUM"

        if risk >= LOW_RISK_THRESHOLD:
            return "LOW"

        return "NONE"

    df["maintenance_label"] = (
        df["maintenance_risk"]
        .apply(risk_label)
    )

    # --------------------------------------------------------
    # 13. Maintenance trigger
    #
    # This indicates that an event may need to be created.
    # It does NOT create/update maintenance_events.csv.
    #
    # A trigger is raised for:
    #   - medium/high computed maintenance risk, OR
    #   - any severe sensor anomaly.
    # --------------------------------------------------------

    df["maintenance_trigger"] = (
        (
            df["maintenance_risk"]
            >= MEDIUM_RISK_THRESHOLD
        )
        |
        df["severe_temperature_anomaly"]
        |
        df["severe_vibration_anomaly"]
        |
        df["severe_rpm_anomaly"]
    )

    # --------------------------------------------------------
    # 14. Maintenance reason
    #
    # IMPORTANT CONSISTENCY FIX
    #
    # Previously, maintenance_trigger could be TRUE because the
    # composite maintenance risk crossed MEDIUM, while
    # maintenance_reason still returned NORMAL because no single
    # sensor crossed the anomaly z-score threshold.
    #
    # The reason now always explains every triggered event:
    #   sensor anomaly reasons when present
    #   otherwise the composite maintenance-risk level.
    # --------------------------------------------------------

    def build_reason(
        row: pd.Series
    ) -> str:

        reasons = []

        if row["severe_temperature_anomaly"]:
            reasons.append(
                "SEVERE_TEMPERATURE_DEVIATION"
            )
        elif row["temperature_anomaly"]:
            reasons.append(
                "TEMPERATURE_DEVIATION"
            )

        if row["severe_vibration_anomaly"]:
            reasons.append(
                "SEVERE_VIBRATION_DEVIATION"
            )
        elif row["vibration_anomaly"]:
            reasons.append(
                "VIBRATION_DEVIATION"
            )

        if row["severe_rpm_anomaly"]:
            reasons.append(
                "SEVERE_RPM_DEVIATION"
            )
        elif row["rpm_anomaly"]:
            reasons.append(
                "RPM_DEVIATION"
            )

        if reasons:
            return " + ".join(reasons)

        risk = float(
            row["maintenance_risk"]
        )

        if risk >= HIGH_RISK_THRESHOLD:
            return "HIGH_MAINTENANCE_RISK"

        if risk >= MEDIUM_RISK_THRESHOLD:
            return "MEDIUM_MAINTENANCE_RISK"

        if (
            row["severe_temperature_anomaly"]
            or row["severe_vibration_anomaly"]
            or row["severe_rpm_anomaly"]
        ):
            return "SEVERE_SENSOR_ANOMALY"

        return "NORMAL"

    df["maintenance_reason"] = (
        df.apply(
            build_reason,
            axis=1
        )
    )

    # --------------------------------------------------------
    # 15. Multi-sensor confidence
    # --------------------------------------------------------

    active_indicators = (
        df["temperature_anomaly"].astype(int)
        +
        df["vibration_anomaly"].astype(int)
        +
        df["rpm_anomaly"].astype(int)
    )

    df["maintenance_confidence"] = (
        df["maintenance_risk"] * 0.80
        +
        (
            active_indicators / 3.0
        ) * 0.20
    ).clip(
        0.0,
        1.0
    )

    # --------------------------------------------------------
    # 16. Optional production/state context
    # --------------------------------------------------------

    if "state" not in df.columns:
        df["state"] = "UNKNOWN"

    df["state"] = (
        df["state"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.strip()
        .str.upper()
    )

    # --------------------------------------------------------
    # 17. Final output
    #
    # Preserve the original maintenance-analysis columns AND
    # carry through the factory twin's existing machine-state,
    # fault, persistence, escalation, anomaly, and scenario data.
    #
    # No persistence logic is recalculated here.
    # --------------------------------------------------------

    output_columns = [
        # Core identity/state.
        "timestamp",
        "machine_id",
        "state",

        # Factory fault state.
        "faulted",
        "fault_code",
        "fault_reason",
        "fault_timestamp",

        # Factory maintenance state.
        "maintenance_mode",
        "maintenance_started_at",
        "maintenance_required",

        # 6/8 persistence telemetry.
        "persistence_count",
        "persistence_window",
        "persistence_threshold",
        "persistence_ratio",
        "persistence_escalated",
        "escalation_state",
        "damage_level",

        # Factory anomaly state.
        "anomaly",
        "anomaly_type",
        "anomaly_severity",
        "anomaly_started_at",
        "anomaly_source",
        "manual_anomaly_active",

        # Scenario state.
        "scenario_id",
        "scenario_type",

        # Maintenance-analysis measurements.
        "temperature_c",
        "temperature_baseline_c",
        "temperature_deviation_c",
        "temperature_zscore",

        "vibration_mm_s",
        "vibration_baseline_mm_s",
        "vibration_deviation_mm_s",
        "vibration_zscore",

        "rpm",
        "rpm_baseline",
        "rpm_deviation",
        "rpm_zscore",

        "temperature_anomaly",
        "vibration_anomaly",
        "rpm_anomaly",

        "risk_raw",
        "maintenance_risk",
        "maintenance_label",

        "maintenance_trigger",
        "maintenance_confidence",
        "maintenance_reason"
    ]

    output_columns = [
        col
        for col in output_columns
        if col in df.columns
    ]

    out = df[
        output_columns
    ].copy()

    # --------------------------------------------------------
    # 18. Clean numeric output
    # --------------------------------------------------------

    out = out.replace(
        [np.inf, -np.inf],
        np.nan
    )

    # --------------------------------------------------------
    # 19. Save
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
    # 20. Summary
    # --------------------------------------------------------

    high_count = int(
        (
            out["maintenance_label"]
            == "HIGH"
        ).sum()
    )

    medium_count = int(
        (
            out["maintenance_label"]
            == "MEDIUM"
        ).sum()
    )

    trigger_count = int(
        out["maintenance_trigger"].sum()
    )

    print(
        f"\nSaved maintenance analysis -> "
        f"{OUT_FILE}"
    )

    print(
        f"Rows analysed: {len(out)}"
    )

    print(
        f"Machines: "
        f"{out['machine_id'].nunique()}"
    )

    print(
        f"High-risk observations: "
        f"{high_count}"
    )

    print(
        f"Medium-risk observations: "
        f"{medium_count}"
    )

    print(
        f"Maintenance triggers: "
        f"{trigger_count}"
    )

    print(
        "\n=== LATEST MACHINE HEALTH ==="
    )

    latest = (
        out
        .sort_values("timestamp")
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .sort_values("machine_id")
    )

    if not latest.empty:

        print(
            latest[
                [
                    "machine_id",
                    "maintenance_risk",
                    "maintenance_label",
                    "maintenance_trigger",
                    "maintenance_reason"
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
    compute_maintenance_risk()
