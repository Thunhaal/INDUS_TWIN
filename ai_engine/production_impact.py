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

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = OPS_DIR / "production_data.csv"
CONSTRAINTS_FILE = FACTORY_DIR / "machine_constraints.csv"
METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"

OUT_FILE = BASE_DIR / "production_impact_output.csv"


# ============================================================
# DEFAULTS
# ============================================================

DEFAULT_REDUCE_KW = 5.0
DEFAULT_DURATION_MIN = 15.0
DEFAULT_MIN_PRODUCTION_PERCENT = 95.0

EPS = 1e-6


# ============================================================
# PROTOTYPE PRODUCTION SENSITIVITY
# ============================================================
#
# These are engineering assumptions for the prototype.
# They are NOT trained industrial values.
#
# Lower value = smaller direct production impact from
# temporary power reduction.
#
# This allows utility/support machines to behave differently
# from fixed critical production machines.
# ============================================================

MACHINE_TYPE_SENSITIVITY = {
    "cnc": 0.80,
    "furnace": 0.95,
    "rolling_mill": 0.90,
    "compressor": 0.30,
    "pump": 0.30,
    "fan": 0.15,
    "hvac": 0.10,
    "conveyor": 0.50,
    "auxiliary_motor": 0.20,
    "other": 0.50,
}

CONTROLLABILITY_FACTOR = {
    "FIXED": 0.05,
    "MODULATING": 0.50,
    "CURTAILABLE": 0.85,
    "SHIFTABLE": 0.70,
    "UNKNOWN": 0.50,
}

CRITICALITY_FACTOR = {
    "HIGH": 1.25,
    "MEDIUM": 1.00,
    "LOW": 0.80,
    "UNKNOWN": 1.00,
}


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Safely load a CSV."""

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
    """Convert a column to numeric."""

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


def normalize_text(value, default="UNKNOWN") -> str:
    if value is None or pd.isna(value):
        return default

    text = str(value).strip()

    if not text:
        return default

    return text.upper()


# ============================================================
# LATEST TELEMETRY
# ============================================================

def get_latest_telemetry(
    telemetry_df: pd.DataFrame
) -> pd.DataFrame:

    df = telemetry_df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    required = {
        "machine_id",
        "timestamp",
        "power_kw"
    }

    missing = required - set(df.columns)

    if missing:
        raise KeyError(
            "Telemetry missing required columns: "
            + ", ".join(sorted(missing))
        )

    df["machine_id"] = (
        df["machine_id"]
        .astype(str)
        .str.strip()
    )

    df["timestamp"] = pd.to_numeric(
        df["timestamp"],
        errors="coerce"
    )

    df["power_kw"] = numeric(
        df,
        "power_kw",
        default=0.0
    )

    if "production_rate" in df.columns:
        df["production_rate"] = numeric(
            df,
            "production_rate",
            default=0.0
        )

    if "units_produced" in df.columns:
        df["units_produced"] = numeric(
            df,
            "units_produced",
            default=0.0
        )

    df = (
        df
        .dropna(
            subset=[
                "machine_id",
                "timestamp"
            ]
        )
        .sort_values(
            [
                "machine_id",
                "timestamp"
            ]
    ))

    latest = (
        df
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .reset_index(drop=True)
    )

    return latest


# ============================================================
# LATEST PRODUCTION
# ============================================================

def get_latest_production(
    production_df: pd.DataFrame
) -> pd.DataFrame:

    if production_df is None or production_df.empty:
        return pd.DataFrame()

    df = production_df.copy()

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    if "machine_id" not in df.columns:
        return pd.DataFrame()

    df["machine_id"] = (
        df["machine_id"]
        .astype(str)
        .str.strip()
    )

    if "timestamp" in df.columns:

        df["timestamp"] = pd.to_numeric(
            df["timestamp"],
            errors="coerce"
        )

    for col in [
        "target_units",
        "actual_units",
        "cycle_time_sec",
        "downtime_sec",
        "defect_count",
        "quality_percent"
    ]:

        if col in df.columns:

            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

    if "timestamp" in df.columns:

        df =(
            df
            .dropna(
                subset=[
                    "machine_id",
                    "timestamp"
                ]
            )
            .sort_values(
                [
                    "machine_id",
                    "timestamp"
                ]
        ))

    latest = (
        df
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .reset_index(drop=True)
    )

    return latest


# ============================================================
# MACHINE PROFILE
# ============================================================

def build_machine_profiles(
    metadata_df: pd.DataFrame,
    constraints_df: pd.DataFrame
) -> dict:

    profiles = {}

    # --------------------------------------------------------
    # Metadata
    # --------------------------------------------------------

    if (
        metadata_df is not None
        and not metadata_df.empty
        and "machine_id" in metadata_df.columns
    ):

        md = metadata_df.copy()

        md.columns = [
            str(c).strip()
            for c in md.columns
        ]

        md["machine_id"] = (
            md["machine_id"]
            .astype(str)
            .str.strip()
        )

        md = md.drop_duplicates(
            subset=["machine_id"],
            keep="last"
        )

        for _, row in md.iterrows():

            mid = str(
                row["machine_id"]
            )

            machine_type = normalize_text(
                row.get(
                    "machine_type"
                ),
                "OTHER"
            ).lower()

            controllability = normalize_text(
                row.get(
                    "controllability"
                ),
                "UNKNOWN"
            )

            criticality = normalize_text(
                row.get(
                    "criticality"
                ),
                "UNKNOWN"
            )

            profiles[mid] = {
                "machine_name": row.get(
                    "machine_name",
                    ""
                ),
                "machine_type": machine_type,
                "production_line": row.get(
                    "production_line",
                    ""
                ),
                "rated_power_kw": pd.to_numeric(
                    row.get(
                        "rated_power_kw"
                    ),
                    errors="coerce"
                ),
                "efficiency_percent": pd.to_numeric(
                    row.get(
                        "efficiency_percent"
                    ),
                    errors="coerce"
                ),
                "criticality": criticality,
                "controllability": controllability,
                "primary_process": row.get(
                    "primary_process",
                    ""
                ),
            }

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    if (
        constraints_df is not None
        and not constraints_df.empty
        and "machine_id" in constraints_df.columns
    ):

        cs = constraints_df.copy()

        cs.columns = [
            str(c).strip()
            for c in cs.columns
        ]

        cs["machine_id"] = (
            cs["machine_id"]
            .astype(str)
            .str.strip()
        )

        cs = cs.drop_duplicates(
            subset=["machine_id"],
            keep="last"
        )

        for _, row in cs.iterrows():

            mid = str(
                row["machine_id"]
            )

            if mid not in profiles:
                profiles[mid] = {}

            profiles[mid].update({

                "min_operating_power_kw":
                    pd.to_numeric(
                        row.get(
                            "min_operating_power_kw"
                        ),
                        errors="coerce"
                    ),

                "max_reduction_kw":
                    pd.to_numeric(
                        row.get(
                            "max_reduction_kw"
                        ),
                        errors="coerce"
                    ),

                "max_curtailment_duration_min":
                    pd.to_numeric(
                        row.get(
                            "max_curtailment_duration_min"
                        ),
                        errors="coerce"
                    ),
            })

    return profiles


# ============================================================
# PRODUCTION SENSITIVITY
# ============================================================

def determine_sensitivity(
    profile: dict
) -> float:

    machine_type = str(
        profile.get(
            "machine_type",
            "other"
        )
    ).lower()

    controllability = normalize_text(
        profile.get(
            "controllability"
        ),
        "UNKNOWN"
    )

    criticality = normalize_text(
        profile.get(
            "criticality"
        ),
        "UNKNOWN"
    )

    base = MACHINE_TYPE_SENSITIVITY.get(
        machine_type,
        MACHINE_TYPE_SENSITIVITY["other"]
    )

    control_factor = CONTROLLABILITY_FACTOR.get(
        controllability,
        CONTROLLABILITY_FACTOR["UNKNOWN"]
    )

    criticality_factor = CRITICALITY_FACTOR.get(
        criticality,
        CRITICALITY_FACTOR["UNKNOWN"]
    )

    # Fixed equipment must not be treated as freely flexible.
    if controllability == "FIXED":

        return min(
            1.0,
            base * 1.50
        )

    sensitivity = (
        base
        * (
            1.0
            -
            0.35 * control_factor
        )
        * criticality_factor
    )

    return float(
        np.clip(
            sensitivity,
            0.05,
            1.0
        )
    )


# ============================================================
# SINGLE MACHINE IMPACT
# ============================================================

def estimate_single_machine_impact(
    actual_power_kw: float,
    production_rate: float,
    reduce_kw: float,
    duration_min: float,
    production_sensitivity: float,
    minimum_production_percent: float
) -> dict:

    actual_power_kw = max(
        0.0,
        float(actual_power_kw)
    )

    production_rate = max(
        0.0,
        float(production_rate)
    )

    reduce_kw = max(
        0.0,
        min(
            float(reduce_kw),
            actual_power_kw
        )
    )

    duration_min = max(
        0.0,
        float(duration_min)
    )

    production_sensitivity = float(
        np.clip(
            production_sensitivity,
            0.0,
            1.0
        )
    )

    # --------------------------------------------------------
    # Power reduction
    # --------------------------------------------------------

    if actual_power_kw <= EPS:

        power_reduction_percent = 0.0

    else:

        power_reduction_percent = (
            reduce_kw
            / actual_power_kw
        ) * 100.0

    # --------------------------------------------------------
    # Estimated production impact
    #
    # Prototype engineering model:
    # production impact =
    # power reduction × machine sensitivity
    # --------------------------------------------------------

    production_loss_percent = (
        power_reduction_percent
        * production_sensitivity
    )

    production_loss_percent = float(
        np.clip(
            production_loss_percent,
            0.0,
            100.0
        )
    )

    remaining_production_percent = max(
        0.0,
        100.0
        - production_loss_percent
    )

    # --------------------------------------------------------
    # Expected production during curtailment
    #
    # Current logger values behave as a production-rate-like
    # value, so treat them as units/hour.
    # --------------------------------------------------------

    expected_units = (
        production_rate
        * duration_min
        / 60.0
    )

    estimated_units_lost = (
        expected_units
        * production_loss_percent
        / 100.0
    )

    estimated_units_remaining = max(
        0.0,
        expected_units
        - estimated_units_lost
    )

    # --------------------------------------------------------
    # Energy reduction
    # --------------------------------------------------------

    estimated_energy_saved_kwh = (
        reduce_kw
        * duration_min
        / 60.0
    )

    production_safe = (
        remaining_production_percent
        >= minimum_production_percent
    )

    return {
        "power_reduction_percent":
            power_reduction_percent,

        "production_loss_percent":
            production_loss_percent,

        "remaining_production_percent":
            remaining_production_percent,

        "expected_production_units":
            expected_units,

        "estimated_units_lost":
            estimated_units_lost,

        "estimated_units_remaining":
            estimated_units_remaining,

        "estimated_energy_saved_kwh":
            estimated_energy_saved_kwh,

        "production_safe":
            production_safe
    }


# ============================================================
# MAIN
# ============================================================

def estimate_production_impact(
    telemetry_df: pd.DataFrame | None = None,
    production_df: pd.DataFrame | None = None,
    constraints_df: pd.DataFrame | None = None,
    metadata_df: pd.DataFrame | None = None,
    reduce_kw: float = DEFAULT_REDUCE_KW,
    duration_min: float = DEFAULT_DURATION_MIN,
    minimum_production_percent:
        float = DEFAULT_MIN_PRODUCTION_PERCENT
) -> pd.DataFrame:

    # --------------------------------------------------------
    # Load telemetry
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

    latest = get_latest_telemetry(
        telemetry_df
    )

    # --------------------------------------------------------
    # Load production
    # --------------------------------------------------------

    if production_df is None:

        production_df = load_csv(
            PRODUCTION_FILE
        )

    latest_production = get_latest_production(
        production_df
    )

    # --------------------------------------------------------
    # Load constraints
    # --------------------------------------------------------

    if constraints_df is None:

        constraints_df = load_csv(
            CONSTRAINTS_FILE
        )

    # --------------------------------------------------------
    # Load metadata
    # --------------------------------------------------------

    if metadata_df is None:

        metadata_df = load_csv(
            METADATA_FILE
        )

    profiles = build_machine_profiles(
        metadata_df,
        constraints_df
    )

    # --------------------------------------------------------
    # Production lookup
    # --------------------------------------------------------

    production_lookup = {}

    if not latest_production.empty:

        production_lookup = (
            latest_production
            .set_index("machine_id")
            .to_dict(
                orient="index"
            )
        )

    # --------------------------------------------------------
    # Evaluate machines
    # --------------------------------------------------------

    rows = []

    for _, telemetry_row in latest.iterrows():

        machine_id = str(
            telemetry_row["machine_id"]
        )

        profile = profiles.get(
            machine_id,
            {}
        )

        actual_power = float(
            telemetry_row.get(
                "power_kw",
                0.0
            )
            or 0.0
        )

        # ----------------------------------------------------
        # Production rate
        # ----------------------------------------------------

        production_rate = 0.0

        if "production_rate" in telemetry_row.index:

            value = telemetry_row.get(
                "production_rate"
            )

            if pd.notna(value):

                production_rate = max(
                    0.0,
                    float(value)
                )

        if (
            production_rate <= EPS
            and
            "units_produced"
            in telemetry_row.index
        ):

            value = telemetry_row.get(
                "units_produced"
            )

            if pd.notna(value):

                production_rate = max(
                    0.0,
                    float(value)
                )

        # Production logger data
        production_row = production_lookup.get(
            machine_id
        )

        if (
            production_rate <= EPS
            and production_row is not None
        ):

            value = production_row.get(
                "actual_units"
            )

            if value is not None and pd.notna(value):

                production_rate = max(
                    0.0,
                    float(value)
                )

        # ----------------------------------------------------
        # Constraints
        # ----------------------------------------------------

        min_operating = profile.get(
            "min_operating_power_kw",
            0.0
        )

        max_reduction = profile.get(
            "max_reduction_kw",
            0.0
        )

        max_duration = profile.get(
            "max_curtailment_duration_min",
            np.nan
        )

        if pd.isna(min_operating):
            min_operating = 0.0

        if pd.isna(max_reduction):
            max_reduction = 0.0

        if pd.isna(max_duration):

            allowable_duration = float(
                duration_min
            )

        else:

            allowable_duration = min(
                float(duration_min),
                float(max_duration)
            )

        min_operating = max(
            0.0,
            float(min_operating)
        )

        max_reduction = max(
            0.0,
            float(max_reduction)
        )

        # ----------------------------------------------------
        # Physical flexibility
        # ----------------------------------------------------

        physical_reduction = max(
            0.0,
            actual_power
            - min_operating
        )

        feasible_reduction = min(
            float(reduce_kw),
            physical_reduction,
            max_reduction
        )

        # ----------------------------------------------------
        # Machine behaviour
        # ----------------------------------------------------

        machine_type = str(
            profile.get(
                "machine_type",
                "unknown"
            )
        )

        controllability = normalize_text(
            profile.get(
                "controllability"
            ),
            "UNKNOWN"
        )

        criticality = normalize_text(
            profile.get(
                "criticality"
            ),
            "UNKNOWN"
        )

        sensitivity = determine_sensitivity(
            profile
        )

        # ----------------------------------------------------
        # Fixed machines
        #
        # A fixed machine may have physical reduction headroom,
        # but the system should not automatically treat it as
        # deployable flexibility.
        # ----------------------------------------------------

        if controllability == "FIXED":

            feasible_reduction = 0.0

        # ----------------------------------------------------
        # Impact calculation
        # ----------------------------------------------------

        impact = estimate_single_machine_impact(
            actual_power_kw=actual_power,
            production_rate=production_rate,
            reduce_kw=feasible_reduction,
            duration_min=allowable_duration,
            production_sensitivity=sensitivity,
            minimum_production_percent=
                minimum_production_percent
        )

        # ----------------------------------------------------
        # Safe deployment decision
        # ----------------------------------------------------

        safe_to_reduce = (
            feasible_reduction > EPS
            and
            impact["production_safe"]
        )

        if safe_to_reduce:

            recommendation = (
                "SAFE_TO_REDUCE"
            )

        elif (
            controllability == "FIXED"
        ):

            recommendation = (
                "PROTECTED_FIXED_MACHINE"
            )

        elif feasible_reduction <= EPS:

            recommendation = (
                "NO_FLEXIBILITY"
            )

        else:

            recommendation = (
                "PRODUCTION_CONSTRAINT"
            )

        rows.append(
            {
                "timestamp":
                    telemetry_row.get(
                        "timestamp"
                    ),

                "machine_id":
                    machine_id,

                "machine_type":
                    machine_type,

                "criticality":
                    criticality,

                "controllability":
                    controllability,

                "actual_power_kw":
                    actual_power,

                "production_rate":
                    production_rate,

                "requested_reduce_kw":
                    float(reduce_kw),

                "feasible_reduce_kw":
                    feasible_reduction,

                "duration_min":
                    allowable_duration,

                "min_operating_power_kw":
                    min_operating,

                "max_reduction_kw":
                    max_reduction,

                "production_sensitivity":
                    sensitivity,

                "power_reduction_percent":
                    impact[
                        "power_reduction_percent"
                    ],

                "production_loss_percent":
                    impact[
                        "production_loss_percent"
                    ],

                "remaining_production_percent":
                    impact[
                        "remaining_production_percent"
                    ],

                "expected_production_units":
                    impact[
                        "expected_production_units"
                    ],

                "estimated_units_lost":
                    impact[
                        "estimated_units_lost"
                    ],

                "estimated_units_remaining":
                    impact[
                        "estimated_units_remaining"
                    ],

                "estimated_energy_saved_kwh":
                    impact[
                        "estimated_energy_saved_kwh"
                    ],

                "minimum_production_percent":
                    minimum_production_percent,

                "production_safe":
                    impact[
                        "production_safe"
                    ],

                "safe_to_reduce":
                    safe_to_reduce,

                "recommendation":
                    recommendation
            }
        )

    out = pd.DataFrame(
        rows
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
        f"\nSaved production impact -> "
        f"{OUT_FILE}"
    )

    print(
        f"Machines analysed: "
        f"{len(out)}"
    )

    if not out.empty:

        print(
            "\n=== PRODUCTION IMPACT ==="
        )

        print(
            out[
                [
                    "machine_id",
                    "machine_type",
                    "criticality",
                    "controllability",
                    "actual_power_kw",
                    "feasible_reduce_kw",
                    "production_loss_percent",
                    "estimated_units_lost",
                    "estimated_energy_saved_kwh",
                    "safe_to_reduce",
                    "recommendation"
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

    estimate_production_impact()