#!/usr/bin/env python3

"""
INDUS_TWIN Constrained Energy Optimizer

Purpose
-------
Optimize safe factory load reduction during grid stress while protecting:

- critical production machines
- fixed loads
- machines already under control
- machines already below normal operating level
- machines with high/critical maintenance risk
- machines that are not production-safe to curtail

IMPORTANT CONTROL CONTRACT
--------------------------
factory_twin_node.py accepts:

    REDUCE_LOAD
    {
        "machine_id": "...",
        "command": "REDUCE_LOAD",
        "target_kw": ...,
        "duration_sec": ...
    }

target_kw is an ABSOLUTE machine power target.

The optimizer therefore uses:

    optimized_target_kw
        =
    normal_target_kw - optimized_reduction_kw

It must NOT use:

    current_power_kw - optimized_reduction_kw

because that causes cumulative reduction across repeated AI cycles.
"""


from __future__ import annotations

import math
import time
from pathlib import Path

import pandas as pd
from ortools.linear_solver import pywraplp


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

TELEMETRY_PATH = (
    ROOT
    / "data"
    / "02_operations"
    / "machine_telemetry.csv"
)

SCENARIO_PATH = (
    ROOT
    / "data"
    / "05_scenarios"
    / "scenario_data.csv"
)

GRID_PATH = (
    ROOT
    / "data"
    / "04_grid"
    / "grid_data.csv"
)

MAINTENANCE_PATH = (
    ROOT
    / "ai_engine"
    / "maintenance_output.csv"
)

FLEXIBILITY_PATH = (
    ROOT
    / "ai_engine"
    / "flexibility_output.csv"
)

OUTPUT_PATH = (
    ROOT
    / "ai_engine"
    / "optimization_output.csv"
)


EPS = 1e-6


# ============================================================================
# FACTORY REFERENCE MODEL
# Must remain aligned with factory_twin_node.py
# ============================================================================

MACHINE_ORDER = [
    "CNC_01",
    "CNC_02",
    "CNC_03",
    "COMP_01",
    "FURNACE_01",
    "HVAC_01",
    "PUMP_01",
]


RATED_POWER_KW = {
    "CNC_01": 30.0,
    "CNC_02": 30.0,
    "CNC_03": 30.0,
    "COMP_01": 37.0,
    "PUMP_01": 15.0,
    "HVAC_01": 22.0,
    "FURNACE_01": 75.0,
}


NORMAL_LOAD_PERCENT = {
    "CNC_01": 90.0,
    "CNC_02": 90.0,
    "CNC_03": 88.0,
    "COMP_01": 85.0,
    "PUMP_01": 82.0,
    "HVAC_01": 76.0,
    "FURNACE_01": 93.0,
}


# ============================================================================
# HELPERS
# ============================================================================

def to_float(value, default=0.0):
    try:
        value = float(value)

        if math.isfinite(value):
            return value

    except (TypeError, ValueError):
        pass

    return default


def to_bool(value):
    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def clean_state(value):
    return (
        str(value if value is not None else "")
        .strip()
        .upper()
        .replace(" ", "_")
    )


def normal_target_kw(machine_id: str) -> float:

    rated = RATED_POWER_KW.get(
        machine_id,
        0.0,
    )

    percentage = NORMAL_LOAD_PERCENT.get(
        machine_id,
        100.0,
    )

    return (
        rated
        * percentage
        / 100.0
    )


def require_file(path: Path, description: str):

    if not path.exists():

        raise FileNotFoundError(
            f"{description} not found:\n"
            f"{path}"
        )


def read_csv(path: Path, description: str):

    require_file(
        path,
        description,
    )

    df = pd.read_csv(path)

    if df.empty:

        raise ValueError(
            f"{description} is empty:\n"
            f"{path}"
        )

    return df


def latest_per_machine(df: pd.DataFrame):

    if "machine_id" not in df.columns:

        return df.copy()

    work = df.copy()

    if "timestamp" in work.columns:

        work["_sort_ts"] = pd.to_numeric(
            work["timestamp"],
            errors="coerce",
        ).fillna(-1)

        work = work.sort_values(
            [
                "machine_id",
                "_sort_ts",
            ]
        )

    work = work.drop_duplicates(
        "machine_id",
        keep="last",
    )

    return work.drop(
        columns=["_sort_ts"],
        errors="ignore",
    )


def latest_row(df: pd.DataFrame):

    if "timestamp" in df.columns:

        ts = pd.to_numeric(
            df["timestamp"],
            errors="coerce",
        )

        valid = df.loc[
            ts.notna()
        ].copy()

        if not valid.empty:

            valid["_sort_ts"] = ts.loc[
                valid.index
            ]

            row = valid.sort_values(
                "_sort_ts"
            ).iloc[-1]

            return row.drop(
                labels=["_sort_ts"],
                errors="ignore",
            )

    return df.iloc[-1]


# ============================================================================
# LOAD INPUTS
# ============================================================================

def load_inputs():

    telemetry = latest_per_machine(
        read_csv(
            TELEMETRY_PATH,
            "Machine telemetry file",
        )
    )

    scenario = latest_row(
        read_csv(
            SCENARIO_PATH,
            "Scenario data file",
        )
    )

    grid = latest_row(
        read_csv(
            GRID_PATH,
            "Grid data file",
        )
    )

    maintenance = latest_per_machine(
        read_csv(
            MAINTENANCE_PATH,
            "Maintenance output file",
        )
    )

    flexibility = latest_per_machine(
        read_csv(
            FLEXIBILITY_PATH,
            "Flexibility output file",
        )
    )

    # Machine metadata and constraints are searched by filename so the
    # optimizer remains compatible if their exact folder changes.
    metadata_path = None
    constraints_path = None

    for candidate in ROOT.rglob(
        "machine_metadata.csv"
    ):

        metadata_path = candidate
        break

    for candidate in ROOT.rglob(
        "machine_constraints.csv"
    ):

        constraints_path = candidate
        break

    if metadata_path is None:

        raise FileNotFoundError(
            "machine_metadata.csv was not found "
            f"under {ROOT}"
        )

    if constraints_path is None:

        raise FileNotFoundError(
            "machine_constraints.csv was not found "
            f"under {ROOT}"
        )

    metadata = read_csv(
        metadata_path,
        "Machine metadata file",
    )

    constraints = read_csv(
        constraints_path,
        "Machine constraints file",
    )

    return (
        telemetry,
        metadata,
        constraints,
        maintenance,
        flexibility,
        grid,
        scenario,
    )


# ============================================================================
# SCENARIO / GRID CONTEXT
# ============================================================================

def build_context(
    telemetry: pd.DataFrame,
    grid: pd.Series,
    scenario: pd.Series,
):

    scenario_id = str(
        scenario.get(
            "scenario_id",
            "UNKNOWN",
        )
    )

    scenario_name = str(
        scenario.get(
            "scenario_name",
            "Unknown Scenario",
        )
    )

    scenario_type = str(
        scenario.get(
            "scenario_type",
            scenario_id,
        )
    )

    scenario_status = str(
        scenario.get(
            "status",
            scenario.get(
                "scenario_status",
                "UNKNOWN",
            ),
        )
    )


    grid_status = str(
        grid.get(
            "grid_status",
            grid.get(
                "status",
                "NORMAL",
            ),
        )
    ).upper()


    required_reduction = to_float(
        scenario.get(
            "required_reduction_kw",
            grid.get(
                "required_reduction_kw",
                0.0,
            ),
        )
    )


    factory_demand = to_float(
        grid.get(
            "factory_demand_kw",
            grid.get(
                "total_power_kw",
                0.0,
            ),
        )
    )


    if (
        factory_demand <= 0
        and "power_kw" in telemetry.columns
    ):

        factory_demand = float(
            pd.to_numeric(
                telemetry["power_kw"],
                errors="coerce",
            )
            .fillna(0.0)
            .sum()
        )


    available_grid_power = to_float(
        grid.get(
            "available_grid_power_kw",
            grid.get(
                "grid_available_power_kw",
                0.0,
            ),
        )
    )


    stress_level = to_float(
        grid.get(
            "grid_stress_level",
            grid.get(
                "stress_level",
                0.0,
            ),
        )
    )


    return {

        "scenario_id":
            scenario_id,

        "scenario_name":
            scenario_name,

        "scenario_type":
            scenario_type,

        "scenario_status":
            scenario_status,

        "grid_status":
            grid_status,

        "grid_stress_level":
            stress_level,

        "required_reduction_kw":
            max(
                0.0,
                required_reduction,
            ),

        "factory_demand_kw":
            max(
                0.0,
                factory_demand,
            ),

        "available_grid_power_kw":
            max(
                0.0,
                available_grid_power,
            ),
    }


# ============================================================================
# BUILD MACHINE DATASET
# ============================================================================

def prepare_table(
    telemetry: pd.DataFrame,
    metadata: pd.DataFrame,
    constraints: pd.DataFrame,
    maintenance: pd.DataFrame,
    flexibility: pd.DataFrame,
):

    if "machine_id" not in telemetry.columns:

        raise ValueError(
            "machine_telemetry.csv must contain machine_id"
        )

    if "power_kw" not in telemetry.columns:

        raise ValueError(
            "machine_telemetry.csv must contain power_kw"
        )


    base_columns = [
        c
        for c in [
            "machine_id",
            "power_kw",
            "state",
        ]
        if c in telemetry.columns
    ]


    df = telemetry[
        base_columns
    ].copy()


    if "state" not in df.columns:

        df["state"] = "NORMAL"


    # ------------------------------------------------------------------------
    # METADATA
    # ------------------------------------------------------------------------

    metadata_columns = [
        "machine_id",
        "machine_name",
        "machine_type",
        "production_line",
        "rated_power_kw",
        "criticality",
        "controllability",
    ]


    keep = [
        c
        for c in metadata_columns
        if c in metadata.columns
    ]


    df = df.merge(
        metadata[keep],
        on="machine_id",
        how="left",
    )


    # ------------------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------------------

    constraint_columns = [
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


    keep = [
        c
        for c in constraint_columns
        if c in constraints.columns
    ]


    df = df.merge(
        constraints[keep],
        on="machine_id",
        how="left",
    )


    # ------------------------------------------------------------------------
    # MAINTENANCE
    # ------------------------------------------------------------------------

    if (
        not maintenance.empty
        and "machine_id" in maintenance.columns
    ):

        columns = [
            "machine_id",
            "maintenance_risk",
            "maintenance_label",
            "maintenance_trigger",
            "maintenance_reason",
        ]

        keep = [
            c
            for c in columns
            if c in maintenance.columns
        ]

        df = df.merge(
            maintenance[keep],
            on="machine_id",
            how="left",
        )


    # ------------------------------------------------------------------------
    # FLEXIBILITY
    # ------------------------------------------------------------------------

    if (
        not flexibility.empty
        and "machine_id" in flexibility.columns
    ):

        columns = [
            "machine_id",
            "deployable_flexibility_kw",
            "safe_flexibility_kw",
            "feasible_reduction_kw",
            "allowed_reduction_kw",
            "physical_flexibility_kw",
            "production_safe_reduction_kw",
            "controllability_adjusted_flexibility_kw",
        ]

        keep = [
            c
            for c in columns
            if c in flexibility.columns
        ]

        df = df.merge(
            flexibility[keep],
            on="machine_id",
            how="left",
        )


    # ------------------------------------------------------------------------
    # ENSURE SEVEN-MACHINE ORDER
    # ------------------------------------------------------------------------

    ordered = pd.DataFrame(
        {
            "machine_id":
                MACHINE_ORDER
        }
    )


    df = ordered.merge(
        df,
        on="machine_id",
        how="left",
    )


    # ------------------------------------------------------------------------
    # NUMERIC COLUMNS
    # ------------------------------------------------------------------------

    numeric_defaults = {

        "power_kw":
            0.0,

        "rated_power_kw":
            0.0,

        "min_operating_power_kw":
            0.0,

        "max_reduction_kw":
            0.0,

        "maintenance_risk":
            0.0,
    }


    for column, default in numeric_defaults.items():

        if column not in df.columns:

            df[column] = default

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce",
        ).fillna(default)


    # Use known reference rating if metadata is missing.
    for machine_id in MACHINE_ORDER:

        mask = df[
            "machine_id"
        ].eq(machine_id)

        df.loc[
            mask,
            "rated_power_kw",
        ] = RATED_POWER_KW[
            machine_id
        ]


    # ------------------------------------------------------------------------
    # NORMAL TARGET
    # ------------------------------------------------------------------------

    df["normal_target_kw"] = (
        df["machine_id"]
        .map(normal_target_kw)
        .astype(float)
    )


    # ------------------------------------------------------------------------
    # CATEGORICAL DATA
    # ------------------------------------------------------------------------

    defaults = {

        "state":
            "NORMAL",

        "criticality":
            "MEDIUM",

        "controllability":
            "FIXED",

        "maintenance_label":
            "NONE",

        "maintenance_reason":
            "NORMAL",
    }


    for column, default in defaults.items():

        if column not in df.columns:

            df[column] = default

        df[column] = (
            df[column]
            .fillna(default)
            .astype(str)
            .map(clean_state)
        )


    if "maintenance_trigger" not in df.columns:

        df["maintenance_trigger"] = False

    df["maintenance_trigger"] = (
        df["maintenance_trigger"]
        .map(to_bool)
    )


    # ------------------------------------------------------------------------
    # FLEXIBILITY ENGINE OUTPUT
    # ------------------------------------------------------------------------

    flexibility_column = None

    for column in [
        "deployable_flexibility_kw",
        "safe_flexibility_kw",
        "production_safe_reduction_kw",
        "feasible_reduction_kw",
        "controllability_adjusted_flexibility_kw",
        "allowed_reduction_kw",
        "physical_flexibility_kw",
    ]:

        if column in df.columns:

            flexibility_column = column
            break


    if flexibility_column is None:

        df["flexibility_engine_kw"] = 0.0

    else:

        df["flexibility_engine_kw"] = (
            pd.to_numeric(
                df[flexibility_column],
                errors="coerce",
            )
            .fillna(0.0)
            .clip(lower=0.0)
        )


    # ------------------------------------------------------------------------
    # PHYSICAL LIMIT
    # ------------------------------------------------------------------------

    df["current_above_min_kw"] = (
        df["power_kw"]
        - df["min_operating_power_kw"]
    ).clip(lower=0.0)


    df["physical_allowed_kw"] = df[
        [
            "current_above_min_kw",
            "max_reduction_kw",
        ]
    ].min(axis=1)


    df["allowed_reduction_kw"] = df[
        [
            "flexibility_engine_kw",
            "physical_allowed_kw",
        ]
    ].min(axis=1).clip(
        lower=0.0
    )


    # =========================================================================
    # SAFETY FLAGS
    # =========================================================================

    active_states = {
        "REDUCED",
        "CURTAILED",
        "SHIFTED",
        "CONTROLLED",
    }


    df["control_active"] = (
        df["state"].isin(
            active_states
        )
    )


    # A machine below its normal operating target must not be commanded to
    # another reduction.
    df["below_normal_baseline"] = (
        df["power_kw"]
        < (
            df["normal_target_kw"]
            - EPS
        )
    )


    # Already controlled → no additional reduction.
    df.loc[
        df["control_active"],
        "allowed_reduction_kw",
    ] = 0.0


    # Already below normal → hold.
    df.loc[
        df["below_normal_baseline"],
        "allowed_reduction_kw",
    ] = 0.0


    # Fixed machine → protect.
    df.loc[
        df["controllability"].eq(
            "FIXED"
        ),
        "allowed_reduction_kw",
    ] = 0.0


    # Maintenance protection.
    df.loc[
        df["maintenance_label"].isin(
            [
                "HIGH",
                "CRITICAL",
            ]
        ),
        "allowed_reduction_kw",
    ] = 0.0


    return df


# ============================================================================
# OPTIMIZER
# ============================================================================

def run_optimizer(
    df: pd.DataFrame,
    required_reduction_kw: float,
):

    # ------------------------------------------------------------------------
    # RESET OUTPUT COLUMNS
    # ------------------------------------------------------------------------

    df["active_reduction_estimate_kw"] = 0.0

    df["optimized_reduction_kw"] = 0.0

    # Default target = current power.
    # This means NO control command.
    df["optimized_target_kw"] = (
        df["power_kw"]
    )

    df["optimization_action"] = (
        "NO_ACTION"
    )

    df["optimization_status"] = (
        "PROTECTED"
    )

    df["recommended_command"] = (
        "NO_ACTION"
    )

    df["objective_cost"] = 0.0


    # ------------------------------------------------------------------------
    # ESTIMATE CURRENTLY ACTIVE REDUCTION
    # ------------------------------------------------------------------------

    active = df[
        "control_active"
    ]


    df.loc[
        active,
        "active_reduction_estimate_kw",
    ] = (
        df.loc[
            active,
            "normal_target_kw",
        ]
        -
        df.loc[
            active,
            "power_kw",
        ]
    ).clip(
        lower=0.0
    )


    active_reduction = float(
        df[
            "active_reduction_estimate_kw"
        ].sum()
    )


    # Only the remaining grid requirement must be optimized.
    remaining_required = max(
        0.0,
        required_reduction_kw
        - active_reduction,
    )


    # ------------------------------------------------------------------------
    # AVAILABLE CANDIDATES
    # ------------------------------------------------------------------------

    candidates_mask = (

        (df["allowed_reduction_kw"] > EPS)

        & (~df["control_active"])

        & (~df["below_normal_baseline"])

        & (~df["controllability"].eq(
            "FIXED"
        ))

        & (~df["maintenance_label"].isin(
            [
                "HIGH",
                "CRITICAL",
            ]
        ))
    )


    candidates = df.loc[
        candidates_mask
    ].copy()


    solver_status = "NOT_REQUIRED"


    # ------------------------------------------------------------------------
    # SOLVE
    # ------------------------------------------------------------------------

    if remaining_required <= EPS:

        solver_status = "NOT_REQUIRED"


    elif candidates.empty:

        solver_status = "NO_CANDIDATES"


    else:

        solver = pywraplp.Solver.CreateSolver(
            "CBC"
        )

        if solver is None:

            raise RuntimeError(
                "OR-Tools CBC solver is unavailable."
            )


        variables = {}


        for idx, row in candidates.iterrows():

            allowed = to_float(
                row[
                    "allowed_reduction_kw"
                ]
            )


            # Cannot reduce below minimum operating power.
            max_from_min = max(
                0.0,
                to_float(
                    row[
                        "power_kw"
                    ]
                )
                -
                to_float(
                    row[
                        "min_operating_power_kw"
                    ]
                ),
            )


            allowed = min(
                allowed,
                max_from_min,
            )


            # Must also remain within the normal target relationship.
            max_from_normal = max(
                0.0,
                to_float(
                    row[
                        "normal_target_kw"
                    ]
                )
                -
                to_float(
                    row[
                        "min_operating_power_kw"
                    ]
                ),
            )


            allowed = min(
                allowed,
                max_from_normal,
            )


            if allowed <= EPS:
                continue


            variables[idx] = solver.NumVar(
                0.0,
                allowed,
                f"reduce_{row['machine_id']}",
            )


        if not variables:

            solver_status = "NO_CANDIDATES"

        else:

            total = solver.Sum(
                variables.values()
            )


            # Never command more than the remaining requirement.
            solver.Add(
                total
                <= remaining_required
            )


            objective = solver.Objective()


            criticality_penalty = {

                "LOW":
                    0.0,

                "MEDIUM":
                    5.0,

                "HIGH":
                    20.0,

                "CRITICAL":
                    40.0,
            }


            for idx, variable in variables.items():

                row = df.loc[idx]


                production_loss = 0.0


                # The current production-impact pipeline may add this field
                # later. Missing values remain safe at zero for now.
                if (
                    "production_loss_percent"
                    in row.index
                ):

                    production_loss = max(
                        0.0,
                        to_float(
                            row[
                                "production_loss_percent"
                            ]
                        ),
                    )


                maintenance_risk = min(
                    1.0,
                    max(
                        0.0,
                        to_float(
                            row[
                                "maintenance_risk"
                            ]
                        ),
                    ),
                )


                criticality = str(
                    row[
                        "criticality"
                    ]
                ).upper()


                penalty = (

                    production_loss
                    * 20.0

                    +

                    maintenance_risk
                    * 10.0

                    +

                    criticality_penalty.get(
                        criticality,
                        10.0,
                    )
                )


                # Very large primary coefficient ensures reduction amount
                # dominates the secondary penalties.
                coefficient = (
                    100000.0
                    - penalty
                )


                objective.SetCoefficient(
                    variable,
                    coefficient,
                )


                df.at[
                    idx,
                    "objective_cost",
                ] = penalty


            objective.SetMaximization()


            status = solver.Solve()


            if status == pywraplp.Solver.OPTIMAL:

                solver_status = "OPTIMAL"

            elif status == pywraplp.Solver.FEASIBLE:

                solver_status = "FEASIBLE"

            else:

                solver_status = (
                    f"SOLVER_STATUS_{status}"
                )


            if status in (
                pywraplp.Solver.OPTIMAL,
                pywraplp.Solver.FEASIBLE,
            ):

                for idx, variable in variables.items():

                    value = max(
                        0.0,
                        float(
                            variable.solution_value()
                        ),
                    )


                    df.at[
                        idx,
                        "optimized_reduction_kw",
                    ] = value


    # =========================================================================
    # ABSOLUTE TARGET
    # =========================================================================

    selected = (
        df[
            "optimized_reduction_kw"
        ]
        > EPS
    )


    # THE CRITICAL FORMULA:
    #
    # normal target - optimized reduction
    #
    # Example:
    #
    # COMP_01:
    #     normal = 31.45
    #     reduction = 3.75
    #     target = 27.70
    #
    # This prevents cumulative reduction on future AI cycles.
    df.loc[
        selected,
        "optimized_target_kw",
    ] = (
        df.loc[
            selected,
            "normal_target_kw",
        ]
        -
        df.loc[
            selected,
            "optimized_reduction_kw",
        ]
    )


    # Never below minimum operating power.
    df.loc[
        selected,
        "optimized_target_kw",
    ] = df.loc[
        selected,
        [
            "optimized_target_kw",
            "min_operating_power_kw",
        ]
    ].max(
        axis=1
    )


    # =========================================================================
    # FINAL COMMAND SAFETY VALIDATION
    # =========================================================================

    for idx in df.index:

        reduction = to_float(
            df.at[
                idx,
                "optimized_reduction_kw",
            ]
        )

        current = to_float(
            df.at[
                idx,
                "power_kw",
            ]
        )

        target = to_float(
            df.at[
                idx,
                "optimized_target_kw",
            ]
        )

        minimum = to_float(
            df.at[
                idx,
                "min_operating_power_kw",
            ]
        )

        maximum_reduction = to_float(
            df.at[
                idx,
                "max_reduction_kw",
            ]
        )

        normal = to_float(
            df.at[
                idx,
                "normal_target_kw",
            ]
        )


        invalid = False


        # A reduction command must actually reduce the present measured power.
        if reduction > EPS:

            if target >= (
                current - EPS
            ):

                invalid = True


        # Do not exceed configured max reduction.
        actual_reduction_from_normal = (
            normal - target
        )

        if (
            actual_reduction_from_normal
            >
            maximum_reduction + EPS
        ):

            invalid = True


        # Do not go below minimum operating power.
        if target < (
            minimum - EPS
        ):

            invalid = True


        # Do not issue new reduction to already-controlled machines.
        if (
            df.at[
                idx,
                "control_active"
            ]
            and
            reduction > EPS
        ):

            invalid = True


        # Do not issue new reduction below normal baseline.
        if (
            df.at[
                idx,
                "below_normal_baseline"
            ]
            and
            reduction > EPS
        ):

            invalid = True


        if invalid:

            df.at[
                idx,
                "optimized_reduction_kw",
            ] = 0.0

            df.at[
                idx,
                "optimized_target_kw",
            ] = current

            df.at[
                idx,
                "optimization_action",
            ] = "NO_ACTION"


    # ------------------------------------------------------------------------
    # FINAL SELECTED MASK
    # ------------------------------------------------------------------------

    selected = (
        df[
            "optimized_reduction_kw"
        ]
        > EPS
    )


    # ------------------------------------------------------------------------
    # STATUS
    # ------------------------------------------------------------------------

    # Initially available machines.
    available = (

        (df["allowed_reduction_kw"] > EPS)

        & (~df["control_active"])

        & (~df["below_normal_baseline"])

        & (~df["controllability"].eq(
            "FIXED"
        ))

        & (~df["maintenance_label"].isin(
            [
                "HIGH",
                "CRITICAL",
            ]
        ))
    )


    df.loc[
        available,
        "optimization_status",
    ] = (
        "AVAILABLE_NOT_REQUIRED"
    )


    # Already under AI control.
    df.loc[
        df["control_active"],
        "optimization_status",
    ] = (
        "ACTIVE_HOLD"
    )


    # Below baseline.
    df.loc[
        df["below_normal_baseline"]
        &
        ~df["control_active"],
        "optimization_status",
    ] = (
        "HOLD_BELOW_BASELINE"
    )


    # Maintenance protection.
    df.loc[
        df["maintenance_label"].isin(
            [
                "HIGH",
                "CRITICAL",
            ]
        ),
        "optimization_status",
    ] = (
        "PROTECTED_MAINTENANCE"
    )


    # Fixed load.
    df.loc[
        df["controllability"].eq(
            "FIXED"
        ),
        "optimization_status",
    ] = (
        "PROTECTED"
    )


    # Selected for new reduction.
    df.loc[
        selected,
        "optimization_action",
    ] = "REDUCE"


    df.loc[
        selected,
        "optimization_status",
    ] = "SELECTED"


    # Recommended ROS command.
    for idx in df.index[selected]:

        machine_id = df.at[
            idx,
            "machine_id",
        ]

        target = to_float(
            df.at[
                idx,
                "optimized_target_kw",
            ]
        )


        df.at[
            idx,
            "recommended_command",
        ] = (
            f'REDUCE_LOAD '
            f'machine_id={machine_id} '
            f'target_kw={target:.2f}'
        )


    # =========================================================================
    # SYSTEM METRICS
    # =========================================================================

    selected_additional = float(
        df[
            "optimized_reduction_kw"
        ].sum()
    )


    projected_total = (
        active_reduction
        +
        selected_additional
    )


    remaining_gap = max(
        0.0,
        required_reduction_kw
        -
        projected_total,
    )


    if required_reduction_kw <= EPS:

        final_solver_status = (
            "NOT_REQUIRED"
        )

    elif projected_total + EPS >= (
        required_reduction_kw
    ):

        final_solver_status = (
            "OPTIMAL"
        )

    else:

        final_solver_status = (
            "OPTIMAL_MAX_REDUCTION"
        )


    summary = {

        "solver_status":
            final_solver_status,

        "already_active_reduction_kw":
            active_reduction,

        "additional_achievable_kw":
            float(
                df[
                    "allowed_reduction_kw"
                ].sum()
            ),

        "additional_selected_reduction_kw":
            selected_additional,

        "projected_reduction_kw":
            projected_total,

        "remaining_gap_kw":
            remaining_gap,
    }


    return df, summary


# ============================================================================
# SAVE OUTPUT
# ============================================================================

def save_output(
    df,
    context,
    summary,
):

    timestamp = int(
        time.time()
    )


    output = pd.DataFrame({

        "timestamp":
            timestamp,

        "machine_id":
            df["machine_id"],

        "state":
            df["state"],

        "current_power_kw":
            df["power_kw"].round(4),

        "normal_target_kw":
            df["normal_target_kw"].round(4),

        "min_operating_power_kw":
            df[
                "min_operating_power_kw"
            ].round(4),

        "allowed_reduction_kw":
            df[
                "allowed_reduction_kw"
            ].round(4),

        "optimized_reduction_kw":
            df[
                "optimized_reduction_kw"
            ].round(6),

        "optimized_target_kw":
            df[
                "optimized_target_kw"
            ].round(6),

        "maintenance_risk":
            df[
                "maintenance_risk"
            ].round(6),

        "maintenance_label":
            df[
                "maintenance_label"
            ],

        "maintenance_trigger":
            df[
                "maintenance_trigger"
            ],

        "maintenance_reason":
            df[
                "maintenance_reason"
            ],

        "criticality":
            df[
                "criticality"
            ],

        "controllability":
            df[
                "controllability"
            ],

        "control_active":
            df[
                "control_active"
            ],

        "below_normal_baseline":
            df[
                "below_normal_baseline"
            ],

        "active_reduction_estimate_kw":
            df[
                "active_reduction_estimate_kw"
            ].round(6),

        "optimization_action":
            df[
                "optimization_action"
            ],

        "optimization_status":
            df[
                "optimization_status"
            ],

        "objective_cost":
            df[
                "objective_cost"
            ].round(6),

        "recommended_command":
            df[
                "recommended_command"
            ],

        "grid_status":
            context[
                "grid_status"
            ],

        "grid_stress_level":
            context[
                "grid_stress_level"
            ],

        "required_reduction_kw":
            context[
                "required_reduction_kw"
            ],

        "factory_demand_kw":
            context[
                "factory_demand_kw"
            ],

        "available_grid_power_kw":
            context[
                "available_grid_power_kw"
            ],

        "system_already_active_reduction_kw":
            summary[
                "already_active_reduction_kw"
            ],

        "system_additional_achievable_reduction_kw":
            summary[
                "additional_achievable_kw"
            ],

        "system_selected_additional_reduction_kw":
            summary[
                "additional_selected_reduction_kw"
            ],

        "system_projected_reduction_kw":
            summary[
                "projected_reduction_kw"
            ],

        "system_remaining_reduction_kw":
            summary[
                "remaining_gap_kw"
            ],

        "solver_status":
            summary[
                "solver_status"
            ],

        "scenario_id":
            context[
                "scenario_id"
            ],

        "scenario_name":
            context[
                "scenario_name"
            ],

        "scenario_type":
            context[
                "scenario_type"
            ],

        "scenario_status":
            context[
                "scenario_status"
            ],
    })


    # Stable seven-machine order.
    order = {
        machine_id: index
        for index, machine_id
        in enumerate(MACHINE_ORDER)
    }


    output["_order"] = (
        output[
            "machine_id"
        ]
        .map(order)
        .fillna(999)
    )


    output = (
        output
        .sort_values("_order")
        .drop(columns="_order")
        .reset_index(drop=True)
    )


    OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )


    # Current optimizer state: overwrite rather than append.
    output.to_csv(
        OUTPUT_PATH,
        index=False,
    )


    return output


# ============================================================================
# PRINT
# ============================================================================

def print_results(
    output,
    context,
    summary,
):

    print()
    print("=" * 70)
    print(
        "INDUS_TWIN CONSTRAINED ENERGY OPTIMIZER"
    )
    print("=" * 70)


    print(
        f"Scenario: "
        f"{context['scenario_id']} | "
        f"{context['scenario_name']}"
    )


    print(
        f"Grid status: "
        f"{context['grid_status']}"
    )


    print(
        f"Required reduction: "
        f"{context['required_reduction_kw']:.2f} kW"
    )


    print(
        f"Already-active reduction estimate: "
        f"{summary['already_active_reduction_kw']:.2f} kW"
    )


    print(
        f"Additional achievable reduction: "
        f"{summary['additional_achievable_kw']:.2f} kW"
    )


    print(
        f"Selected additional reduction: "
        f"{summary['additional_selected_reduction_kw']:.2f} kW"
    )


    print(
        f"Projected total reduction: "
        f"{summary['projected_reduction_kw']:.2f} kW"
    )


    print(
        f"Remaining reduction gap: "
        f"{summary['remaining_gap_kw']:.2f} kW"
    )


    print(
        f"Solver status: "
        f"{summary['solver_status']}"
    )


    print()
    print(
        "=== OPTIMIZED ACTIONS ==="
    )


    columns = [

        "machine_id",

        "state",

        "current_power_kw",

        "normal_target_kw",

        "allowed_reduction_kw",

        "optimized_reduction_kw",

        "optimized_target_kw",

        "maintenance_label",

        "optimization_action",

        "optimization_status",
    ]


    print(
        output[
            columns
        ].to_string(
            index=False
        )
    )


    print()
    print(
        f"Saved optimizer output -> "
        f"{OUTPUT_PATH}"
    )

    print("=" * 70)


# ============================================================================
# MAIN
# ============================================================================

def main():

    (
        telemetry,
        metadata,
        constraints,
        maintenance,
        flexibility,
        grid,
        scenario,
    ) = load_inputs()


    context = build_context(
        telemetry,
        grid,
        scenario,
    )


    df = prepare_table(
        telemetry,
        metadata,
        constraints,
        maintenance,
        flexibility,
    )


    result, summary = run_optimizer(
        df,
        context[
            "required_reduction_kw"
        ],
    )


    output = save_output(
        result,
        context,
        summary,
    )


    print_results(
        output,
        context,
        summary,
    )


if __name__ == "__main__":
    main()
