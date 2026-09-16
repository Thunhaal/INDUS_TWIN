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
CONSTRAINTS_FILE = FACTORY_DIR / "machine_constraints.csv"
METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"
PRODUCTION_IMPACT_FILE = BASE_DIR / "production_impact_output.csv"
GRID_FILE = GRID_DIR / "grid_data.csv"
SCENARIO_FILE = SCENARIO_DIR / "scenario_data.csv"

OUT_FILE = BASE_DIR / "flexibility_output.csv"


# ============================================================
# SETTINGS
# ============================================================

EPS = 1e-6

DEFAULT_MIN_PRODUCTION_PERCENT = 95.0

# Production-impact output is considered deployable only when
# its own safety assessment says it is safe.
SAFE_PRODUCTION_MIN = 95.0

# Criticality is used as a deployment preference/safety factor.
CRITICALITY_FACTOR = {
    "HIGH": 0.25,
    "MEDIUM": 0.75,
    "LOW": 1.00,
    "UNKNOWN": 0.50,
}


# ============================================================
# HELPERS
# ============================================================

def load_csv(path: Path) -> pd.DataFrame:
    """Safely load a CSV and normalize column names."""

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
    """Return a numeric series, creating the column if required."""

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


def latest_per_machine(
    df: pd.DataFrame
) -> pd.DataFrame:

    if df.empty:
        return pd.DataFrame()

    df = df.copy()

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

        df = (
            df
            .dropna(
                subset=["timestamp"]
            )
            .sort_values(
                [
                    "machine_id",
                    "timestamp"
                ]
            )
        )

    return (
        df
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .reset_index(drop=True)
    )


# ============================================================
# MAIN FLEXIBILITY
# ============================================================

def compute_flexibility(
    telemetry_df: pd.DataFrame | None = None,
    constraints_df: pd.DataFrame | None = None,
    production_impact_df: pd.DataFrame | None = None,
    metadata_df: pd.DataFrame | None = None
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

    telemetry_df = telemetry_df.copy()

    telemetry_df.columns = [
        str(c).strip()
        for c in telemetry_df.columns
    ]

    if "machine_id" not in telemetry_df.columns:
        raise KeyError(
            "Telemetry missing 'machine_id'."
        )

    if "timestamp" not in telemetry_df.columns:
        raise KeyError(
            "Telemetry missing 'timestamp'."
        )

    if "power_kw" not in telemetry_df.columns:
        raise KeyError(
            "Telemetry missing 'power_kw'."
        )

    latest = latest_per_machine(
        telemetry_df
    )

    latest["power_kw"] = numeric(
        latest,
        "power_kw",
        default=0.0
    ).fillna(0.0)

    # --------------------------------------------------------
    # 2. Constraints
    # --------------------------------------------------------

    if constraints_df is None:

        constraints_df = load_csv(
            CONSTRAINTS_FILE
        )

    constraints = constraints_df.copy()

    if not constraints.empty:

        constraints.columns = [
            str(c).strip()
            for c in constraints.columns
        ]

        constraints["machine_id"] = (
            constraints["machine_id"]
            .astype(str)
            .str.strip()
        )

        for col in [
            "min_operating_power_kw",
            "max_reduction_kw",
            "max_curtailment_duration_min"
        ]:

            if col in constraints.columns:

                constraints[col] = pd.to_numeric(
                    constraints[col],
                    errors="coerce"
                )

        constraints = (
            constraints
            .drop_duplicates(
                "machine_id",
                keep="last"
            )
        )

    # --------------------------------------------------------
    # 3. Machine metadata
    # --------------------------------------------------------

    if metadata_df is None:

        metadata_df = load_csv(
            METADATA_FILE
        )

    metadata = metadata_df.copy()

    if not metadata.empty:

        metadata.columns = [
            str(c).strip()
            for c in metadata.columns
        ]

        metadata["machine_id"] = (
            metadata["machine_id"]
            .astype(str)
            .str.strip()
        )

        metadata = (
            metadata
            .drop_duplicates(
                "machine_id",
                keep="last"
            )
        )

        metadata_columns = [
            "machine_id",
            "machine_type",
            "machine_name",
            "criticality",
            "controllability",
            "production_line",
            "primary_process"
        ]

        metadata_columns = [
            c
            for c in metadata_columns
            if c in metadata.columns
        ]

        metadata = metadata[
            metadata_columns
        ]

    # --------------------------------------------------------
    # 4. Merge machine constraints
    # --------------------------------------------------------

    if not constraints.empty:

        constraint_columns = [
            "machine_id",
            "min_operating_power_kw",
            "max_reduction_kw",
            "max_curtailment_duration_min"
        ]

        constraint_columns = [
            c
            for c in constraint_columns
            if c in constraints.columns
        ]

        latest = latest.merge(
            constraints[
                constraint_columns
            ],
            on="machine_id",
            how="left"
        )

    # --------------------------------------------------------
    # 5. Merge machine metadata
    # --------------------------------------------------------

    if not metadata.empty:

        latest = latest.merge(
            metadata,
            on="machine_id",
            how="left"
        )

    # --------------------------------------------------------
    # 6. Defaults for missing constraints
    # --------------------------------------------------------

    if "min_operating_power_kw" not in latest.columns:
        latest["min_operating_power_kw"] = 0.0

    if "max_reduction_kw" not in latest.columns:
        latest["max_reduction_kw"] = 0.0

    if "max_curtailment_duration_min" not in latest.columns:
        latest["max_curtailment_duration_min"] = np.nan

    latest["min_operating_power_kw"] = numeric(
        latest,
        "min_operating_power_kw",
        default=0.0
    ).fillna(0.0).clip(lower=0.0)

    latest["max_reduction_kw"] = numeric(
        latest,
        "max_reduction_kw",
        default=0.0
    ).fillna(0.0).clip(lower=0.0)

    latest["max_curtailment_duration_min"] = numeric(
        latest,
        "max_curtailment_duration_min"
    )

    # --------------------------------------------------------
    # 7. Defaults for metadata
    # --------------------------------------------------------

    if "criticality" not in latest.columns:
        latest["criticality"] = "UNKNOWN"

    if "controllability" not in latest.columns:
        latest["controllability"] = "UNKNOWN"

    if "machine_type" not in latest.columns:
        latest["machine_type"] = "UNKNOWN"

    latest["criticality"] = (
        latest["criticality"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    latest["controllability"] = (
        latest["controllability"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    latest["machine_type"] = (
        latest["machine_type"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.strip()
    )

    # --------------------------------------------------------
    # 8. Physical flexibility
    # --------------------------------------------------------

    latest["power_above_min_operating_kw"] = (
        latest["power_kw"]
        - latest["min_operating_power_kw"]
    ).clip(
        lower=0.0
    )

    latest["physical_flexibility_kw"] = np.minimum(
        latest["power_above_min_operating_kw"],
        latest["max_reduction_kw"]
    )

    # --------------------------------------------------------
    # 9. Prevent fixed machines from being automatically
    #    considered deployable.
    # --------------------------------------------------------

    fixed_mask = (
        latest["controllability"]
        == "FIXED"
    )

    latest["controllability_factor"] = 1.0

    latest.loc[
        fixed_mask,
        "controllability_factor"
    ] = 0.0

    latest["controllability_adjusted_kw"] = (
        latest["physical_flexibility_kw"]
        * latest["controllability_factor"]
    )

    # --------------------------------------------------------
    # 10. Production impact
    # --------------------------------------------------------

    if production_impact_df is None:

        production_impact_df = load_csv(
            PRODUCTION_IMPACT_FILE
        )

    impact = production_impact_df.copy()

    if not impact.empty:

        impact.columns = [
            str(c).strip()
            for c in impact.columns
        ]

        impact["machine_id"] = (
            impact["machine_id"]
            .astype(str)
            .str.strip()
        )

        impact = (
            impact
            .drop_duplicates(
                "machine_id",
                keep="last"
            )
        )

        impact_columns = [
            "machine_id",
            "feasible_reduce_kw",
            "production_loss_percent",
            "remaining_production_percent",
            "estimated_energy_saved_kwh",
            "production_safe",
            "safe_to_reduce",
            "recommendation"
        ]

        impact_columns = [
            c
            for c in impact_columns
            if c in impact.columns
        ]

        latest = latest.merge(
            impact[
                impact_columns
            ],
            on="machine_id",
            how="left",
            suffixes=("", "_impact")
        )

    # --------------------------------------------------------
    # 11. Fill production-impact defaults
    # --------------------------------------------------------

    if "feasible_reduce_kw" not in latest.columns:
        latest["feasible_reduce_kw"] = 0.0

    if "production_loss_percent" not in latest.columns:
        latest["production_loss_percent"] = np.nan

    if "remaining_production_percent" not in latest.columns:
        latest["remaining_production_percent"] = np.nan

    if "production_safe" not in latest.columns:
        latest["production_safe"] = False

    if "safe_to_reduce" not in latest.columns:
        latest["safe_to_reduce"] = False

    latest["feasible_reduce_kw"] = numeric(
        latest,
        "feasible_reduce_kw",
        default=0.0
    ).fillna(0.0).clip(
        lower=0.0
    )

    latest["production_loss_percent"] = numeric(
        latest,
        "production_loss_percent"
    )

    latest["remaining_production_percent"] = numeric(
        latest,
        "remaining_production_percent"
    )

    latest["production_safe"] = (
        latest["production_safe"]
        .fillna(False)
        .astype(bool)
    )

    latest["safe_to_reduce"] = (
        latest["safe_to_reduce"]
        .fillna(False)
        .astype(bool)
    )

    # --------------------------------------------------------
    # 12. Safe deployable flexibility
    #
    # Start with physical flexibility and constrain it by
    # production-impact analysis.
    # --------------------------------------------------------

    latest["safe_flexibility_kw"] = np.minimum(
        latest["controllability_adjusted_kw"],
        latest["feasible_reduce_kw"]
    )

    # If production analysis explicitly says unsafe,
    # do not deploy this flexibility automatically.
    unsafe_mask = (
        ~latest["production_safe"]
    )

    latest.loc[
        unsafe_mask,
        "safe_flexibility_kw"
    ] = 0.0

    # Fixed machines remain protected.
    latest.loc[
        fixed_mask,
        "safe_flexibility_kw"
    ] = 0.0

    # --------------------------------------------------------
    # 13. Criticality protection
    #
    # HIGH criticality remains technically visible but is
    # heavily restricted for automated demand response.
    # --------------------------------------------------------

    latest["criticality_factor"] = (
        latest["criticality"]
        .map(CRITICALITY_FACTOR)
        .fillna(
            CRITICALITY_FACTOR["UNKNOWN"]
        )
    )

    latest["deployable_flexibility_kw"] = (
        latest["safe_flexibility_kw"]
        * latest["criticality_factor"]
    )

    # For LOW-criticality machines, the factor remains 1.
    # For HIGH-criticality machines, only a conservative
    # fraction is considered automatically deployable.

    # --------------------------------------------------------
    # 14. Curtailment duration
    # --------------------------------------------------------

    latest["effective_curtailment_duration_min"] = (
        latest["max_curtailment_duration_min"]
    )

    # --------------------------------------------------------
    # 15. Energy reserve contribution
    #
    # kWh available if deployable flexibility is applied for
    # the allowed duration.
    # --------------------------------------------------------

    duration_hours = (
        latest["effective_curtailment_duration_min"]
        / 60.0
    )

    duration_hours = duration_hours.fillna(
        15.0 / 60.0
    )

    latest["flexible_energy_reserve_kwh"] = (
        latest["deployable_flexibility_kw"]
        * duration_hours
    )

    # --------------------------------------------------------
    # 16. Current grid requirement
    # --------------------------------------------------------

    grid = load_csv(
        GRID_FILE
    )

    required_reduction = 0.0
    grid_stress = np.nan
    grid_status = "UNKNOWN"

    if (
        not grid.empty
        and "timestamp" in grid.columns
    ):

        grid["timestamp"] = pd.to_numeric(
            grid["timestamp"],
            errors="coerce"
        )

        grid = (
            grid
            .dropna(subset=["timestamp"])
            .sort_values("timestamp")
        )

        if not grid.empty:

            latest_grid = grid.iloc[-1]

            grid_status = str(
                latest_grid.get(
                    "grid_status",
                    "UNKNOWN"
                )
            )

            grid_stress = pd.to_numeric(
                latest_grid.get(
                    "grid_stress_level"
                ),
                errors="coerce"
            )

            if "required_reduction_kw" in grid.columns:

                required_reduction = pd.to_numeric(
                    latest_grid.get(
                        "required_reduction_kw"
                    ),
                    errors="coerce"
                )

                if pd.isna(
                    required_reduction
                ):
                    required_reduction = 0.0

    latest["grid_status"] = grid_status

    latest["grid_stress_level"] = (
        grid_stress
    )

    latest["required_reduction_kw"] = (
        float(required_reduction)
    )

    # --------------------------------------------------------
    # 17. Reserve status
    # --------------------------------------------------------

    total_deployable = (
        latest["deployable_flexibility_kw"]
        .sum()
    )

    reserve_margin = (
        total_deployable
        - float(required_reduction)
    )

    if required_reduction <= EPS:

        reserve_status = (
            "NO_GRID_REDUCTION_REQUIRED"
        )

    elif total_deployable + EPS >= required_reduction:

        reserve_status = (
            "RESERVE_SUFFICIENT"
        )

    else:

        reserve_status = (
            "RESERVE_INSUFFICIENT"
        )

    latest["total_deployable_flexibility_kw"] = (
        total_deployable
    )

    latest["reserve_margin_kw"] = (
        reserve_margin
    )

    latest["reserve_status"] = (
        reserve_status
    )

    # --------------------------------------------------------
    # 18. Machine deployment status
    # --------------------------------------------------------

    def deployment_status(row: pd.Series) -> str:

        if row["controllability"] == "FIXED":
            return "PROTECTED"

        if row["deployable_flexibility_kw"] > EPS:
            return "DEPLOYABLE"

        if row["safe_flexibility_kw"] > EPS:
            return "PRODUCTION_LIMITED"

        if row["physical_flexibility_kw"] > EPS:
            return "CONSTRAINT_LIMITED"

        return "NO_FLEXIBILITY"

    latest["deployment_status"] = (
        latest.apply(
            deployment_status,
            axis=1
        )
    )

    # --------------------------------------------------------
    # 19. Recommended maximum reduction
    # --------------------------------------------------------

    latest["recommended_reduction_kw"] = (
        latest["deployable_flexibility_kw"]
    )

    # --------------------------------------------------------
    # 20. Final output
    # --------------------------------------------------------

    output_columns = [
        "timestamp",
        "machine_id",

        "machine_type",
        "criticality",
        "controllability",

        "power_kw",

        "min_operating_power_kw",
        "max_reduction_kw",
        "max_curtailment_duration_min",

        "physical_flexibility_kw",
        "controllability_adjusted_kw",

        "feasible_reduce_kw",
        "production_loss_percent",
        "remaining_production_percent",
        "production_safe",
        "safe_to_reduce",

        "safe_flexibility_kw",
        "criticality_factor",
        "deployable_flexibility_kw",

        "flexible_energy_reserve_kwh",

        "grid_status",
        "grid_stress_level",
        "required_reduction_kw",

        "total_deployable_flexibility_kw",
        "reserve_margin_kw",
        "reserve_status",

        "recommended_reduction_kw",
        "deployment_status"
    ]

    output_columns = [
        col
        for col in output_columns
        if col in latest.columns
    ]

    out = latest[
        output_columns
    ].copy()

    # --------------------------------------------------------
    # 21. Save
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
    # 22. Summary
    # --------------------------------------------------------

    print(
        f"\nSaved flexibility -> "
        f"{OUT_FILE}"
    )

    print(
        f"Machines analysed: "
        f"{len(out)}"
    )

    print(
        f"Total deployable flexibility: "
        f"{total_deployable:.2f} kW"
    )

    print(
        f"Required grid reduction: "
        f"{float(required_reduction):.2f} kW"
    )

    print(
        f"Reserve margin: "
        f"{reserve_margin:.2f} kW"
    )

    print(
        f"Reserve status: "
        f"{reserve_status}"
    )

    if not out.empty:

        print(
            "\n=== MACHINE FLEXIBILITY ==="
        )

        print(
            out[
                [
                    "machine_id",
                    "criticality",
                    "controllability",
                    "physical_flexibility_kw",
                    "safe_flexibility_kw",
                    "deployable_flexibility_kw",
                    "flexible_energy_reserve_kwh",
                    "deployment_status"
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
    compute_flexibility()