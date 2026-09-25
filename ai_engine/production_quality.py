#!/usr/bin/env python3

"""
INDUS_TWIN Production + Quality Engine

Production machines:
    CNC_01
    CNC_02
    CNC_03

Other factory assets:
    COMP_01
    PUMP_01
    HVAC_01
    FURNACE_01

Data sources:
    data/02_operations/production_data.csv
    data/02_operations/machine_telemetry.csv
    data/02_operations/machine_metadata.csv
    data/02_operations/quality_inspection.csv

Outputs:
    ai_engine/production_quality_output.csv
    ai_engine/production_summary_output.csv
    ai_engine/quality_rejection_summary.csv

QUALITY SEMANTICS
-----------------
Production quality describes the production stream.

Inspection quality describes only inspected parts.

PARTIAL_INSPECTION:
    inspection quality is reported separately and does not replace
    production quality.

FULL_INSPECTION:
    inspection quality may become the authoritative quality value.

OVER_COVERAGE:
    inspected units exceed completed units by more than the tolerance.
    Inspection is marked invalid for quality substitution.

This prevents a small inspected sample from being incorrectly treated as
the quality of the entire production stream.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

OPERATIONS_DIR = ROOT / "data" / "02_operations"

PRODUCTION_PATH = (
    OPERATIONS_DIR / "production_data.csv"
)

TELEMETRY_PATH = (
    OPERATIONS_DIR / "machine_telemetry.csv"
)

METADATA_PATH = (
    OPERATIONS_DIR / "machine_metadata.csv"
)

INSPECTION_PATH = (
    OPERATIONS_DIR / "quality_inspection.csv"
)

AI_DIR = ROOT / "ai_engine"

PRODUCTION_OUTPUT_PATH = (
    AI_DIR / "production_quality_output.csv"
)

SUMMARY_OUTPUT_PATH = (
    AI_DIR / "production_summary_output.csv"
)

REJECTION_OUTPUT_PATH = (
    AI_DIR / "quality_rejection_summary.csv"
)


# ============================================================================
# FACTORY MODEL
# ============================================================================

ALL_MACHINES = [
    "CNC_01",
    "CNC_02",
    "CNC_03",
    "COMP_01",
    "PUMP_01",
    "HVAC_01",
    "FURNACE_01",
]

PRODUCTION_MACHINES = [
    "CNC_01",
    "CNC_02",
    "CNC_03",
]

WINDOW_HOURS = 12.0

INSPECTION_MATCH_TOLERANCE = 0.05

EPS = 1e-9


# ============================================================================
# HELPERS
# ============================================================================

def require_file(path: Path):

    if not path.exists():

        raise FileNotFoundError(
            f"Required file not found:\n{path}"
        )


def read_csv(path: Path):

    require_file(path)

    return pd.read_csv(path)


def numeric(
    df: pd.DataFrame,
    column: str,
    default=0.0,
):

    if column not in df.columns:
        df[column] = default

    df[column] = pd.to_numeric(
        df[column],
        errors="coerce",
    ).fillna(default)

    return df


def safe_divide(
    numerator,
    denominator,
    default=0.0,
):

    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except (TypeError, ValueError):
        return default

    if abs(denominator) <= EPS:
        return default

    return numerator / denominator


def clip_percent(value):

    return max(
        0.0,
        min(
            100.0,
            float(value),
        ),
    )


def weighted_average(
    values,
    weights,
):

    values = pd.to_numeric(
        values,
        errors="coerce",
    ).fillna(0.0)

    weights = pd.to_numeric(
        weights,
        errors="coerce",
    ).fillna(0.0)

    total_weight = float(
        weights.sum()
    )

    if total_weight <= EPS:

        if values.empty:
            return 0.0

        return float(
            values.mean()
        )

    return float(
        (values * weights).sum()
        / total_weight
    )


# ============================================================================
# INSPECTION FILE
# ============================================================================

def ensure_inspection_file():

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

    if not INSPECTION_PATH.exists():

        INSPECTION_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        pd.DataFrame(
            columns=columns
        ).to_csv(
            INSPECTION_PATH,
            index=False,
        )

        return pd.DataFrame(
            columns=columns
        )


    df = pd.read_csv(
        INSPECTION_PATH
    )


    for column in columns:

        if column not in df.columns:
            df[column] = pd.NA


    df = df[
        columns
    ].copy()


    numeric(
        df,
        "timestamp",
        0.0,
    )

    numeric(
        df,
        "inspected_units",
        0.0,
    )


    df["machine_id"] = (
        df["machine_id"]
        .astype("string")
        .str.strip()
        .str.upper()
    )


    df["result"] = (
        df["result"]
        .astype("string")
        .str.strip()
        .str.upper()
    )


    df["rejection_reason"] = (
        df["rejection_reason"]
        .fillna("")
        .astype(str)
        .str.strip()
    )


    return df


# ============================================================================
# LOAD DATA
# ============================================================================

def load_data():

    production = read_csv(
        PRODUCTION_PATH
    )

    telemetry = read_csv(
        TELEMETRY_PATH
    )

    metadata = read_csv(
        METADATA_PATH
    )

    inspection = ensure_inspection_file()


    production_columns = [
        "timestamp",
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


    for column in production_columns:

        if column not in production.columns:
            production[column] = pd.NA


    production = production[
        production_columns
    ].copy()


    for column in [
        "timestamp",
        "target_units",
        "actual_units",
        "cycle_time_sec",
        "downtime_sec",
        "defect_count",
        "quality_percent",
    ]:

        numeric(
            production,
            column,
            0.0,
        )


    production["machine_id"] = (
        production["machine_id"]
        .astype("string")
        .str.strip()
        .str.upper()
    )


    telemetry_columns = [
        "timestamp",
        "machine_id",
        "state",
        "power_kw",
    ]


    for column in telemetry_columns:

        if column not in telemetry.columns:

            telemetry[column] = (
                "NORMAL"
                if column == "state"
                else 0.0
            )


    telemetry = telemetry[
        telemetry_columns
    ].copy()


    numeric(
        telemetry,
        "timestamp",
        0.0,
    )

    numeric(
        telemetry,
        "power_kw",
        0.0,
    )


    telemetry["machine_id"] = (
        telemetry["machine_id"]
        .astype("string")
        .str.strip()
        .str.upper()
    )


    production = production[
        production["machine_id"].isin(
            ALL_MACHINES
        )
    ].copy()


    telemetry = telemetry[
        telemetry["machine_id"].isin(
            ALL_MACHINES
        )
    ].copy()


    metadata["machine_id"] = (
        metadata["machine_id"]
        .astype("string")
        .str.strip()
        .str.upper()
    )


    return (
        production,
        telemetry,
        metadata,
        inspection,
    )


# ============================================================================
# TIME WINDOW
# ============================================================================

def determine_window(
    production,
    telemetry,
):

    timestamps = pd.concat(
        [
            production["timestamp"],
            telemetry["timestamp"],
        ],
        ignore_index=True,
    )


    timestamps = pd.to_numeric(
        timestamps,
        errors="coerce",
    ).dropna()


    if timestamps.empty:

        raise ValueError(
            "No valid timestamps found."
        )


    end_timestamp = float(
        timestamps.max()
    )


    start_timestamp = (
        end_timestamp
        -
        WINDOW_HOURS * 3600.0
    )


    return (
        start_timestamp,
        end_timestamp,
    )


# ============================================================================
# INTERVALS
# ============================================================================

def add_intervals(
    df: pd.DataFrame,
):

    if df.empty:
        return df.copy()


    output = []


    for machine_id, group in df.groupby(
        "machine_id"
    ):

        work = (
            group
            .sort_values(
                "timestamp"
            )
            .reset_index(
                drop=True
            )
            .copy()
        )


        if len(work) <= 1:

            work["interval_sec"] = 10.0

            output.append(work)

            continue


        differences = (
            work["timestamp"]
            .diff()
        )


        valid = differences[
            (differences > 0)
            &
            (differences <= 3600)
        ]


        fallback = (
            float(valid.median())
            if not valid.empty
            else 10.0
        )


        work["interval_sec"] = (
            differences
            .where(
                (differences > 0)
                &
                (differences <= 3600)
            )
            .fillna(fallback)
            .clip(
                lower=0.1,
                upper=3600.0,
            )
        )


        output.append(work)


    return pd.concat(
        output,
        ignore_index=True,
    )


# ============================================================================
# ENERGY
# ============================================================================

def calculate_energy(
    telemetry_window,
):

    columns = [
        "machine_id",
        "energy_kwh",
        "average_power_kw",
        "observed_hours",
    ]


    if telemetry_window.empty:

        return pd.DataFrame(
            columns=columns
        )


    telemetry_window = add_intervals(
        telemetry_window
    )


    telemetry_window[
        "interval_energy_kwh"
    ] = (
        telemetry_window["power_kw"]
        *
        telemetry_window["interval_sec"]
        /
        3600.0
    )


    rows = []


    for machine_id, group in (
        telemetry_window.groupby(
            "machine_id"
        )
    ):

        observed_hours = (
            group["interval_sec"].sum()
            /
            3600.0
        )


        energy = float(
            group[
                "interval_energy_kwh"
            ].sum()
        )


        average_power = weighted_average(
            group["power_kw"],
            group["interval_sec"],
        )


        rows.append(
            {
                "machine_id": machine_id,
                "energy_kwh": energy,
                "average_power_kw":
                    average_power,
                "observed_hours":
                    observed_hours,
            }
        )


    return pd.DataFrame(
        rows
    )


# ============================================================================
# PRODUCTION
# ============================================================================

def calculate_production(
    production_window,
):

    columns = [
        "machine_id",
        "production_line",
        "product_id",
        "observed_hours",
        "target_rate_units_per_hour",
        "actual_rate_units_per_hour",
        "target_units",
        "completed_units",
        "modeled_rejected_units",
        "modeled_good_units",
        "completion_percent",
        "downtime_sec",
        "availability_percent",
        "performance_percent",
        "production_quality_percent",
        "oee_percent",
        "average_cycle_time_sec",
    ]


    production_window = production_window[
        production_window["machine_id"].isin(
            PRODUCTION_MACHINES
        )
    ].copy()


    if production_window.empty:

        return pd.DataFrame(
            columns=columns
        )


    production_window = add_intervals(
        production_window
    )


    rows = []


    for machine_id, group in (
        production_window.groupby(
            "machine_id"
        )
    ):

        observed_hours = (
            group["interval_sec"].sum()
            /
            3600.0
        )


        target_rate = weighted_average(
            group["target_units"],
            group["interval_sec"],
        )


        actual_rate = weighted_average(
            group["actual_units"],
            group["interval_sec"],
        )


        target_units = (
            target_rate
            *
            observed_hours
        )


        completed_units = (
            actual_rate
            *
            observed_hours
        )


        rejected = max(
            0.0,
            float(
                group[
                    "defect_count"
                ].sum()
            ),
        )


        rejected = min(
            rejected,
            completed_units,
        )


        good = max(
            0.0,
            completed_units
            -
            rejected,
        )


        planned_seconds = float(
            group[
                "interval_sec"
            ].sum()
        )


        downtime_sec = max(
            0.0,
            float(
                group[
                    "downtime_sec"
                ].sum()
            ),
        )


        availability = clip_percent(
            safe_divide(
                max(
                    0.0,
                    planned_seconds
                    -
                    downtime_sec,
                ),
                planned_seconds,
                0.0,
            )
            *
            100.0
        )


        performance = clip_percent(
            safe_divide(
                actual_rate,
                target_rate,
                0.0,
            )
            *
            100.0
        )


        production_quality = clip_percent(
            safe_divide(
                good,
                completed_units,
                0.0,
            )
            *
            100.0
        )


        oee = (
            availability
            *
            performance
            *
            production_quality
            /
            10000.0
        )


        product_values = (
            group[
                "product_id"
            ]
            .dropna()
            .astype(str)
            .replace(
                "nan",
                "",
            )
        )


        product_id = (
            product_values.iloc[-1]
            if not product_values.empty
            else ""
        )


        production_line = str(
            group[
                "production_line"
            ].iloc[-1]
        )


        rows.append(
            {
                "machine_id":
                    machine_id,

                "production_line":
                    production_line,

                "product_id":
                    product_id,

                "observed_hours":
                    observed_hours,

                "target_rate_units_per_hour":
                    target_rate,

                "actual_rate_units_per_hour":
                    actual_rate,

                "target_units":
                    target_units,

                "completed_units":
                    completed_units,

                "modeled_rejected_units":
                    rejected,

                "modeled_good_units":
                    good,

                "completion_percent":
                    clip_percent(
                        safe_divide(
                            completed_units,
                            target_units,
                            0.0,
                        )
                        *
                        100.0
                    ),

                "downtime_sec":
                    downtime_sec,

                "availability_percent":
                    availability,

                "performance_percent":
                    performance,

                "production_quality_percent":
                    production_quality,

                "oee_percent":
                    oee,

                "average_cycle_time_sec":
                    weighted_average(
                        group[
                            "cycle_time_sec"
                        ],
                        group[
                            "interval_sec"
                        ],
                    ),
            }
        )


    return pd.DataFrame(
        rows
    )


# ============================================================================
# INSPECTION
# ============================================================================

def calculate_inspection(
    inspection_window,
):

    columns = [
        "machine_id",
        "inspected_units",
        "verified_good_units",
        "verified_rejected_units",
        "verified_quality_percent",
        "inspection_records",
    ]


    if inspection_window.empty:

        return pd.DataFrame(
            columns=columns
        )


    rows = []


    for machine_id, group in (
        inspection_window.groupby(
            "machine_id"
        )
    ):

        good = float(
            group.loc[
                group["result"].eq("GOOD"),
                "inspected_units",
            ].sum()
        )


        rejected = float(
            group.loc[
                group["result"].eq("REJECT"),
                "inspected_units",
            ].sum()
        )


        inspected = (
            good
            +
            rejected
        )


        verified_quality = (
            safe_divide(
                good,
                inspected,
                0.0,
            )
            *
            100.0
        )


        rows.append(
            {
                "machine_id":
                    machine_id,

                "inspected_units":
                    inspected,

                "verified_good_units":
                    good,

                "verified_rejected_units":
                    rejected,

                "verified_quality_percent":
                    clip_percent(
                        verified_quality
                    ),

                "inspection_records":
                    len(group),
            }
        )


    return pd.DataFrame(
        rows
    )


# ============================================================================
# INSPECTION INTEGRITY
# ============================================================================

def apply_inspection_integrity(
    production_df,
    inspection_df,
):

    if production_df.empty:

        return production_df


    output = production_df.merge(
        inspection_df,
        on="machine_id",
        how="left",
    )


    inspection_columns = [
        "inspected_units",
        "verified_good_units",
        "verified_rejected_units",
        "verified_quality_percent",
        "inspection_records",
    ]


    for column in inspection_columns:

        if column not in output.columns:
            output[column] = 0.0

        output[column] = pd.to_numeric(
            output[column],
            errors="coerce",
        ).fillna(0.0)


    # ------------------------------------------------------------------------
    # COVERAGE
    # ------------------------------------------------------------------------

    output[
        "inspection_coverage_percent"
    ] = output.apply(
        lambda row:
            clip_percent(
                safe_divide(
                    row["inspected_units"],
                    row["completed_units"],
                    0.0,
                )
                *
                100.0
            ),
        axis=1,
    )


    # ------------------------------------------------------------------------
    # OVER-COVERAGE
    # ------------------------------------------------------------------------

    output[
        "inspection_excess_units"
    ] = (
        output["inspected_units"]
        -
        output["completed_units"]
    ).clip(
        lower=0.0
    )


    over_coverage = (
        output["inspected_units"]
        >
        output["completed_units"]
        +
        INSPECTION_MATCH_TOLERANCE
    )


    # ------------------------------------------------------------------------
    # INSPECTION STATUS
    # ------------------------------------------------------------------------

    output["inspection_status"] = (
        "NOT_INSPECTED"
    )


    has_inspection = (
        output["inspected_units"]
        > EPS
    )


    output.loc[
        has_inspection,
        "inspection_status",
    ] = "PARTIAL_INSPECTION"


    full_inspection = (
        has_inspection
        &
        (
            (
                output["inspected_units"]
                -
                output["completed_units"]
            ).abs()
            <= INSPECTION_MATCH_TOLERANCE
        )
    )


    output.loc[
        full_inspection,
        "inspection_status",
    ] = "FULL_INSPECTION"


    output.loc[
        over_coverage,
        "inspection_status",
    ] = "OVER_COVERAGE"


    # ------------------------------------------------------------------------
    # PRODUCTION QUALITY
    # ------------------------------------------------------------------------
    #
    # Production quality remains independent for partial inspection.
    # ------------------------------------------------------------------------

    output["quality_basis"] = (
        "PRODUCTION_MODEL"
    )


    output["quality_percent"] = (
        output[
            "production_quality_percent"
        ]
    )


    # ------------------------------------------------------------------------
    # FULL INSPECTION
    # ------------------------------------------------------------------------
    #
    # Only a valid full inspection can replace the production quality value.
    # ------------------------------------------------------------------------

    valid_full = (
        full_inspection
        &
        ~over_coverage
    )


    output.loc[
        valid_full,
        "quality_basis",
    ] = "FULL_INSPECTION"


    output.loc[
        valid_full,
        "quality_percent",
    ] = output.loc[
        valid_full,
        "verified_quality_percent",
    ]


    # ------------------------------------------------------------------------
    # PARTIAL INSPECTION
    # ------------------------------------------------------------------------

    partial = (
        has_inspection
        &
        ~full_inspection
        &
        ~over_coverage
    )


    output.loc[
        partial,
        "quality_basis",
    ] = "PRODUCTION_MODEL_PARTIAL_INSPECTION"


    # ------------------------------------------------------------------------
    # INVALID INSPECTION
    # ------------------------------------------------------------------------

    output.loc[
        over_coverage,
        "quality_basis",
    ] = (
        "PRODUCTION_MODEL_INSPECTION_INVALID"
    )


    # ------------------------------------------------------------------------
    # GOOD / REJECTED COUNTS
    # ------------------------------------------------------------------------
    #
    # Production stream remains authoritative unless every produced part is
    # covered by a valid full inspection.
    # ------------------------------------------------------------------------

    output["good_units"] = (
        output[
            "modeled_good_units"
        ]
    )


    output["rejected_units"] = (
        output[
            "modeled_rejected_units"
        ]
    )


    output.loc[
        valid_full,
        "good_units",
    ] = output.loc[
        valid_full,
        "verified_good_units",
    ]


    output.loc[
        valid_full,
        "rejected_units",
    ] = output.loc[
        valid_full,
        "verified_rejected_units",
    ]


    # ------------------------------------------------------------------------
    # OEE QUALITY
    # ------------------------------------------------------------------------
    #
    # Partial inspection does not replace production quality.
    # Full valid inspection can.
    # ------------------------------------------------------------------------

    output[
        "oee_quality_percent"
    ] = (
        output[
            "production_quality_percent"
        ]
    )


    output.loc[
        valid_full,
        "oee_quality_percent",
    ] = output.loc[
        valid_full,
        "verified_quality_percent",
    ]


    output["oee_percent"] = (
        output[
            "availability_percent"
        ]
        *
        output[
            "performance_percent"
        ]
        *
        output[
            "oee_quality_percent"
        ]
        /
        10000.0
    )


    return output


# ============================================================================
# ENERGY METRICS
# ============================================================================

def add_energy_metrics(
    production_df,
    energy_df,
):

    if production_df.empty:

        return production_df


    output = production_df.merge(
        energy_df,
        on="machine_id",
        how="left",
    )


    for column in [
        "energy_kwh",
        "average_power_kw",
        "observed_hours",
    ]:

        if column in output.columns:

            output[column] = pd.to_numeric(
                output[column],
                errors="coerce",
            ).fillna(0.0)


    if "energy_kwh" not in output.columns:

        output["energy_kwh"] = 0.0


    output[
        "energy_per_completed_part_kwh"
    ] = output.apply(
        lambda row:
            safe_divide(
                row["energy_kwh"],
                row["completed_units"],
                0.0,
            ),
        axis=1,
    )


    output[
        "energy_per_good_part_kwh"
    ] = output.apply(
        lambda row:
            safe_divide(
                row["energy_kwh"],
                row["good_units"],
                0.0,
            ),
        axis=1,
    )


    return output


# ============================================================================
# REJECTION REASONS
# ============================================================================

def build_rejection_summary(
    inspection_window,
):

    columns = [
        "rejection_reason",
        "rejected_units",
        "inspection_records",
    ]


    if inspection_window.empty:

        return pd.DataFrame(
            columns=columns
        )


    rejected = inspection_window[
        inspection_window[
            "result"
        ].eq(
            "REJECT"
        )
    ].copy()


    if rejected.empty:

        return pd.DataFrame(
            columns=columns
        )


    summary = (
        rejected
        .groupby(
            "rejection_reason",
            dropna=False,
        )
        .agg(
            rejected_units=(
                "inspected_units",
                "sum",
            ),
            inspection_records=(
                "inspection_id",
                "count",
            ),
        )
        .reset_index()
    )


    summary[
        "rejection_reason"
    ] = (
        summary[
            "rejection_reason"
        ]
        .fillna("Other")
        .replace(
            "",
            "Other",
        )
    )


    return summary


# ============================================================================
# OVERALL SUMMARY
# ============================================================================

def build_overall_summary(
    machine_df,
    start_timestamp,
    end_timestamp,
):

    if machine_df.empty:

        return pd.DataFrame(
            [
                {
                    "start_timestamp":
                        int(start_timestamp),

                    "end_timestamp":
                        int(end_timestamp),

                    "window_hours":
                        WINDOW_HOURS,

                    "production_machine_count":
                        len(PRODUCTION_MACHINES),

                    "factory_asset_count":
                        len(ALL_MACHINES),
                }
            ]
        )


    total_target = float(
        machine_df[
            "target_units"
        ].sum()
    )


    total_completed = float(
        machine_df[
            "completed_units"
        ].sum()
    )


    total_good = float(
        machine_df[
            "good_units"
        ].sum()
    )


    total_rejected = float(
        machine_df[
            "rejected_units"
        ].sum()
    )


    total_energy = float(
        machine_df[
            "energy_kwh"
        ].sum()
    )


    total_downtime = float(
        machine_df[
            "downtime_sec"
        ].sum()
    )


    inspected_units = float(
        machine_df[
            "inspected_units"
        ].sum()
    )


    verified_good = float(
        machine_df[
            "verified_good_units"
        ].sum()
    )


    verified_rejected = float(
        machine_df[
            "verified_rejected_units"
        ].sum()
    )


    inspection_excess = float(
        machine_df[
            "inspection_excess_units"
        ].sum()
    )


    completion = clip_percent(
        safe_divide(
            total_completed,
            total_target,
            0.0,
        )
        *
        100.0
    )


    # IMPORTANT:
    # Overall quality uses production-stream good/completed quantities.
    total_quality = clip_percent(
        safe_divide(
            total_good,
            total_completed,
            0.0,
        )
        *
        100.0
    )


    verified_quality = clip_percent(
        safe_divide(
            verified_good,
            verified_good
            +
            verified_rejected,
            0.0,
        )
        *
        100.0
    )


    inspection_coverage = clip_percent(
        safe_divide(
            inspected_units,
            total_completed,
            0.0,
        )
        *
        100.0
    )


    energy_per_completed = safe_divide(
        total_energy,
        total_completed,
        0.0,
    )


    energy_per_good = safe_divide(
        total_energy,
        total_good,
        0.0,
    )


    full_count = int(
        machine_df[
            "inspection_status"
        ]
        .eq(
            "FULL_INSPECTION"
        )
        .sum()
    )


    partial_count = int(
        machine_df[
            "inspection_status"
        ]
        .eq(
            "PARTIAL_INSPECTION"
        )
        .sum()
    )


    invalid_count = int(
        machine_df[
            "inspection_status"
        ]
        .eq(
            "OVER_COVERAGE"
        )
        .sum()
    )


    return pd.DataFrame(
        [
            {
                "start_timestamp":
                    int(start_timestamp),

                "end_timestamp":
                    int(end_timestamp),

                "window_hours":
                    WINDOW_HOURS,

                "production_machine_count":
                    len(PRODUCTION_MACHINES),

                "factory_asset_count":
                    len(ALL_MACHINES),

                "target_units":
                    total_target,

                "completed_units":
                    total_completed,

                "good_units":
                    total_good,

                "rejected_units":
                    total_rejected,

                "completion_percent":
                    completion,

                "quality_percent":
                    total_quality,

                "inspected_units":
                    inspected_units,

                "verified_good_units":
                    verified_good,

                "verified_rejected_units":
                    verified_rejected,

                "inspection_quality_percent":
                    verified_quality,

                "inspection_coverage_percent":
                    inspection_coverage,

                "full_inspection_machine_count":
                    full_count,

                "partial_inspection_machine_count":
                    partial_count,

                "invalid_overcoverage_machine_count":
                    invalid_count,

                "inspection_excess_units":
                    inspection_excess,

                "total_energy_kwh":
                    total_energy,

                "energy_per_completed_part_kwh":
                    energy_per_completed,

                "energy_per_good_part_kwh":
                    energy_per_good,

                "total_downtime_sec":
                    total_downtime,

                "total_downtime_hours":
                    total_downtime / 3600.0,
            }
        ]
    )


# ============================================================================
# SAVE
# ============================================================================

def save_outputs(
    machine_df,
    summary_df,
    rejection_df,
):

    AI_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )


    machine_df.to_csv(
        PRODUCTION_OUTPUT_PATH,
        index=False,
    )


    summary_df.to_csv(
        SUMMARY_OUTPUT_PATH,
        index=False,
    )


    rejection_df.to_csv(
        REJECTION_OUTPUT_PATH,
        index=False,
    )


# ============================================================================
# MAIN
# ============================================================================

def main():

    print()
    print("=" * 70)
    print(
        "INDUS_TWIN PRODUCTION + QUALITY ENGINE"
    )
    print("=" * 70)


    (
        production,
        telemetry,
        metadata,
        inspection,
    ) = load_data()


    start_timestamp, end_timestamp = (
        determine_window(
            production,
            telemetry,
        )
    )


    production_window = production[
        (
            production[
                "timestamp"
            ]
            >= start_timestamp
        )
        &
        (
            production[
                "timestamp"
            ]
            <= end_timestamp
        )
    ].copy()


    telemetry_window = telemetry[
        (
            telemetry[
                "timestamp"
            ]
            >= start_timestamp
        )
        &
        (
            telemetry[
                "timestamp"
            ]
            <= end_timestamp
        )
    ].copy()


    inspection_window = inspection[
        (
            inspection[
                "timestamp"
            ]
            >= start_timestamp
        )
        &
        (
            inspection[
                "timestamp"
            ]
            <= end_timestamp
        )
        &
        (
            inspection[
                "machine_id"
            ].isin(
                PRODUCTION_MACHINES
            )
        )
    ].copy()


    # ------------------------------------------------------------------------
    # Production
    # ------------------------------------------------------------------------

    production_df = calculate_production(
        production_window
    )


    # ------------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------------

    inspection_df = calculate_inspection(
        inspection_window
    )


    production_df = (
        apply_inspection_integrity(
            production_df,
            inspection_df,
        )
    )


    # ------------------------------------------------------------------------
    # Energy
    # ------------------------------------------------------------------------

    energy_df = calculate_energy(
        telemetry_window
    )


    production_df = add_energy_metrics(
        production_df,
        energy_df,
    )


    # ------------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------------

    metadata_columns = [
        "machine_id",
        "machine_name",
        "machine_type",
    ]


    metadata_keep = [
        column
        for column in metadata_columns
        if column in metadata.columns
    ]


    production_df = production_df.merge(
        metadata[
            metadata_keep
        ],
        on="machine_id",
        how="left",
    )


    # ------------------------------------------------------------------------
    # Stable order
    # ------------------------------------------------------------------------

    order = {
        machine_id: i
        for i, machine_id
        in enumerate(
            PRODUCTION_MACHINES
        )
    }


    if not production_df.empty:

        production_df["_order"] = (
            production_df[
                "machine_id"
            ]
            .map(order)
            .fillna(999)
        )


        production_df = (
            production_df
            .sort_values(
                "_order"
            )
            .drop(
                columns="_order"
            )
            .reset_index(
                drop=True
            )
        )


    # ------------------------------------------------------------------------
    # Overall summary
    # ------------------------------------------------------------------------

    overall = (
        build_overall_summary(
            production_df,
            start_timestamp,
            end_timestamp,
        )
    )


    # ------------------------------------------------------------------------
    # Rejections
    # ------------------------------------------------------------------------

    rejection_summary = (
        build_rejection_summary(
            inspection_window
        )
    )


    # ------------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------------

    save_outputs(
        production_df,
        overall,
        rejection_summary,
    )


    # ------------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------------

    print()
    print(
        f"Window: "
        f"{int(start_timestamp)} → "
        f"{int(end_timestamp)}"
    )


    print(
        f"Factory assets: "
        f"{len(ALL_MACHINES)}"
    )


    print(
        f"Production machines: "
        f"{len(PRODUCTION_MACHINES)}"
    )


    print(
        f"Inspection records in window: "
        f"{len(inspection_window)}"
    )


    print()
    print(
        "=== PRODUCTION + QUALITY ==="
    )


    if production_df.empty:

        print(
            "No manufacturing production records "
            "were found in the current window."
        )

    else:

        columns = [
            "machine_id",
            "completed_units",
            "good_units",
            "rejected_units",
            "completion_percent",
            "production_quality_percent",
            "quality_percent",
            "quality_basis",
            "inspection_status",
            "inspected_units",
            "inspection_coverage_percent",
            "availability_percent",
            "performance_percent",
            "oee_percent",
            "energy_kwh",
            "energy_per_completed_part_kwh",
            "energy_per_good_part_kwh",
        ]


        print(
            production_df[
                [
                    column
                    for column in columns
                    if column
                    in production_df.columns
                ]
            ].to_string(
                index=False
            )
        )


    print()
    print(
        "=== OVERALL SUMMARY ==="
    )


    print(
        overall.to_string(
            index=False
        )
    )


    print()
    print(
        "=== REJECTION SUMMARY ==="
    )


    if rejection_summary.empty:

        print(
            "No rejected inspection records "
            "in the current window."
        )

    else:

        print(
            rejection_summary.to_string(
                index=False
            )
        )


    print()
    print(
        f"Production output -> "
        f"{PRODUCTION_OUTPUT_PATH}"
    )


    print(
        f"Overall summary -> "
        f"{SUMMARY_OUTPUT_PATH}"
    )


    print(
        f"Rejection summary -> "
        f"{REJECTION_OUTPUT_PATH}"
    )


    print(
        f"Inspection input -> "
        f"{INSPECTION_PATH}"
    )


    print("=" * 70)


if __name__ == "__main__":

    main()
