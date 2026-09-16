from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# PROJECT PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"

OPS_DIR = DATA_DIR / "02_operations"
FACTORY_DIR = DATA_DIR / "01_factory"
AI_DIR = DATA_DIR / "06_ai"

TELEMETRY_FILE = OPS_DIR / "machine_telemetry.csv"
PRODUCTION_FILE = OPS_DIR / "production_data.csv"
MACHINE_METADATA_FILE = FACTORY_DIR / "machine_metadata.csv"

OUT_FILE = BASE_DIR / "baseline_output.csv"


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


def to_numeric(
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


# ============================================================
# BASELINE CALCULATION
# ============================================================

def compute_baseline(
    telemetry_df: pd.DataFrame | None = None,
    production_df: pd.DataFrame | None = None
) -> pd.DataFrame:

    # --------------------------------------------------------
    # 1. Load telemetry
    # --------------------------------------------------------

    if telemetry_df is None:
        telemetry_df = load_csv(
            TELEMETRY_FILE
        )

    if telemetry_df.empty:
        print("Telemetry file missing or empty.")

        return pd.DataFrame(
            columns=[
                "machine_id",
                "state",
                "expected_power_kw",
                "sample_count",
                "baseline_method",
                "machine_expected_power_kw"
            ]
        )

    telemetry_df = telemetry_df.copy()

    telemetry_df.columns = [
        str(c).strip()
        for c in telemetry_df.columns
    ]

    # --------------------------------------------------------
    # 2. Validate required fields
    # --------------------------------------------------------

    if "machine_id" not in telemetry_df.columns:
        raise KeyError(
            "Telemetry is missing 'machine_id'."
        )

    if "power_kw" not in telemetry_df.columns:
        raise KeyError(
            "Telemetry is missing 'power_kw'."
        )

    # --------------------------------------------------------
    # 3. Normalize fields
    # --------------------------------------------------------

    telemetry_df["machine_id"] = (
        telemetry_df["machine_id"]
        .astype(str)
        .str.strip()
    )

    telemetry_df["power_kw"] = to_numeric(
        telemetry_df,
        "power_kw"
    )

    if "timestamp" in telemetry_df.columns:

        telemetry_df["timestamp"] = pd.to_numeric(
            telemetry_df["timestamp"],
            errors="coerce"
        )

    else:

        telemetry_df["timestamp"] = np.nan

    if "state" not in telemetry_df.columns:

        telemetry_df["state"] = "UNKNOWN"

    else:

        telemetry_df["state"] = (
            telemetry_df["state"]
            .fillna("UNKNOWN")
            .astype(str)
            .str.strip()
            .str.upper()
        )

    # --------------------------------------------------------
    # 4. Load production data
    #
    # Production is optional context at this stage.
    # The baseline remains machine + state based so it remains
    # compatible with anomaly.py.
    # --------------------------------------------------------

    if production_df is None:
        production_df = load_csv(
            PRODUCTION_FILE
        )

    if not production_df.empty:

        production_df = production_df.copy()

        production_df.columns = [
            str(c).strip()
            for c in production_df.columns
        ]

        if (
            "machine_id" in production_df.columns
            and "timestamp" in production_df.columns
        ):

            production_df["machine_id"] = (
                production_df["machine_id"]
                .astype(str)
                .str.strip()
            )

            production_df["timestamp"] = pd.to_numeric(
                production_df["timestamp"],
                errors="coerce"
            )

            # Production data is deliberately not used as a
            # direct baseline target yet. It can be incorporated
            # into a more advanced production-aware baseline later.

    # --------------------------------------------------------
    # 5. Load machine metadata
    #
    # Rated power is used to identify obvious overload values
    # that should not normally define the baseline.
    # --------------------------------------------------------

    metadata = load_csv(
        MACHINE_METADATA_FILE
    )

    if (
        not metadata.empty
        and "machine_id" in metadata.columns
        and "rated_power_kw" in metadata.columns
    ):

        metadata["machine_id"] = (
            metadata["machine_id"]
            .astype(str)
            .str.strip()
        )

        metadata["rated_power_kw"] = pd.to_numeric(
            metadata["rated_power_kw"],
            errors="coerce"
        )

        metadata = (
            metadata[
                [
                    "machine_id",
                    "rated_power_kw"
                ]
            ]
            .drop_duplicates(
                subset=["machine_id"],
                keep="last"
            )
        )

        telemetry_df = telemetry_df.merge(
            metadata,
            on="machine_id",
            how="left"
        )

    else:

        telemetry_df["rated_power_kw"] = np.nan

    # --------------------------------------------------------
    # 6. Remove invalid measurements
    # --------------------------------------------------------

    telemetry_df = telemetry_df[
        telemetry_df["power_kw"].notna()
        &
        (telemetry_df["power_kw"] >= 0)
        &
        telemetry_df["machine_id"].notna()
    ].copy()

    if telemetry_df.empty:

        return pd.DataFrame(
            columns=[
                "machine_id",
                "state",
                "expected_power_kw",
                "sample_count",
                "baseline_method",
                "machine_expected_power_kw"
            ]
        )

    # --------------------------------------------------------
    # 7. Identify obvious overload observations
    #
    # If rated power is known, observations above 110% of
    # rated power are treated as abnormal for baseline
    # purposes.
    # --------------------------------------------------------

    telemetry_df["is_obvious_overload"] = False

    rated_available = (
        telemetry_df["rated_power_kw"].notna()
        &
        (telemetry_df["rated_power_kw"] > 0)
    )

    telemetry_df.loc[
        rated_available,
        "is_obvious_overload"
    ] = (
        telemetry_df.loc[
            rated_available,
            "power_kw"
        ]
        >
        telemetry_df.loc[
            rated_available,
            "rated_power_kw"
        ] * 1.10
    )

    # --------------------------------------------------------
    # 8. Normal reference dataset
    # --------------------------------------------------------

    normal_df = telemetry_df[
        ~telemetry_df["is_obvious_overload"]
    ].copy()

    # Safety fallback if everything was filtered.
    if normal_df.empty:

        normal_df = telemetry_df.copy()

    # --------------------------------------------------------
    # 9. Machine + state baseline
    #
    # Median is more robust than mean when there are occasional
    # abnormal measurements.
    # --------------------------------------------------------

    baseline = (
        normal_df
        .groupby(
            [
                "machine_id",
                "state"
            ],
            dropna=False
        )
        .agg(
            expected_power_kw=(
                "power_kw",
                "median"
            ),
            sample_count=(
                "power_kw",
                "count"
            )
        )
        .reset_index()
    )

    baseline["baseline_method"] = (
        "MACHINE_STATE_MEDIAN"
    )

    # --------------------------------------------------------
    # 10. Ensure all observed machine/state combinations exist
    # --------------------------------------------------------

    all_groups = (
        telemetry_df[
            [
                "machine_id",
                "state"
            ]
        ]
        .drop_duplicates()
    )

    baseline = all_groups.merge(
        baseline,
        on=[
            "machine_id",
            "state"
        ],
        how="left"
    )

    # --------------------------------------------------------
    # 11. Fallback for machine/state groups with no normal
    # observations
    # --------------------------------------------------------

    missing_baseline = (
        baseline["expected_power_kw"].isna()
    )

    if missing_baseline.any():

        fallback = (
            telemetry_df
            .groupby(
                [
                    "machine_id",
                    "state"
                ],
                dropna=False
            )
            .agg(
                fallback_power_kw=(
                    "power_kw",
                    "median"
                ),
                fallback_sample_count=(
                    "power_kw",
                    "count"
                )
            )
            .reset_index()
        )

        baseline = baseline.merge(
            fallback,
            on=[
                "machine_id",
                "state"
            ],
            how="left"
        )

        baseline.loc[
            missing_baseline,
            "expected_power_kw"
        ] = baseline.loc[
            missing_baseline,
            "fallback_power_kw"
        ]

        baseline.loc[
            missing_baseline,
            "sample_count"
        ] = baseline.loc[
            missing_baseline,
            "fallback_sample_count"
        ]

        baseline.loc[
            missing_baseline,
            "baseline_method"
        ] = (
            "FALLBACK_ALL_VALID_MEDIAN"
        )

        baseline = baseline.drop(
            columns=[
                "fallback_power_kw",
                "fallback_sample_count"
            ],
            errors="ignore"
        )

    # --------------------------------------------------------
    # 12. Machine-level fallback baseline
    #
    # Used later if a machine appears in an unfamiliar state.
    # --------------------------------------------------------

    machine_fallback = (
        normal_df
        .groupby(
            "machine_id"
        )["power_kw"]
        .median()
        .reset_index()
        .rename(
            columns={
                "power_kw":
                "machine_expected_power_kw"
            }
        )
    )

    baseline = baseline.merge(
        machine_fallback,
        on="machine_id",
        how="left"
    )

    # --------------------------------------------------------
    # 13. Final cleanup
    # --------------------------------------------------------

    baseline["expected_power_kw"] = pd.to_numeric(
        baseline["expected_power_kw"],
        errors="coerce"
    )

    baseline["sample_count"] = pd.to_numeric(
        baseline["sample_count"],
        errors="coerce"
    ).fillna(0).astype(int)

    baseline["machine_expected_power_kw"] = pd.to_numeric(
        baseline["machine_expected_power_kw"],
        errors="coerce"
    )

    baseline = baseline.sort_values(
        [
            "machine_id",
            "state"
        ]
    ).reset_index(drop=True)

    return baseline[
        [
            "machine_id",
            "state",
            "expected_power_kw",
            "sample_count",
            "baseline_method",
            "machine_expected_power_kw"
        ]
    ]


# ============================================================
# SAVE BASELINE
# ============================================================

def save_baseline(
    out_file: Path = OUT_FILE
) -> pd.DataFrame:

    baseline = compute_baseline()

    Path(out_file).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    baseline.to_csv(
        out_file,
        index=False
    )

    print(
        f"\nSaved baseline -> {out_file}"
    )

    print(
        f"Baseline rows: {len(baseline)}"
    )

    if not baseline.empty:

        print(
            "\n=== BASELINE ==="
        )

        print(
            baseline[
                [
                    "machine_id",
                    "state",
                    "expected_power_kw",
                    "sample_count",
                    "baseline_method"
                ]
            ].to_string(
                index=False
            )
        )

    return baseline


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    save_baseline()