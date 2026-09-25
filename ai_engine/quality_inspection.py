#!/usr/bin/env python3

"""
INDUS_TWIN Quality Inspection Backend

Purpose
-------
Create and validate post-production inspection records.

Output:
    data/02_operations/quality_inspection.csv

Supported results:
    GOOD
    REJECT

Supported rejection reasons:
    Dimensional deviation
    Surface defect
    Incorrect component
    Machine defect
    Process deviation
    Other

This module can be used directly from the command line and later by FastAPI.
"""

from __future__ import annotations

import argparse
import csv
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


# ============================================================================
# PATHS
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]

INSPECTION_PATH = (
    ROOT
    / "data"
    / "02_operations"
    / "quality_inspection.csv"
)


# ============================================================================
# FACTORY RULES
# ============================================================================

VALID_MACHINES = {
    "CNC_01",
    "CNC_02",
    "CNC_03",
}

VALID_RESULTS = {
    "GOOD",
    "REJECT",
}

VALID_REJECTION_REASONS = {
    "Dimensional deviation",
    "Surface defect",
    "Incorrect component",
    "Machine defect",
    "Process deviation",
    "Other",
}


FIELDS = [
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


# ============================================================================
# FILE INITIALIZATION
# ============================================================================

def ensure_file():

    INSPECTION_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not INSPECTION_PATH.exists():

        with INSPECTION_PATH.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=FIELDS,
            )

            writer.writeheader()

        return


    # Validate existing header.
    with INSPECTION_PATH.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:

        reader = csv.reader(file)

        header = next(
            reader,
            None,
        )


    if header != FIELDS:

        raise RuntimeError(
            "quality_inspection.csv has an invalid header.\n"
            f"Expected: {FIELDS}\n"
            f"Found:    {header}"
        )


# ============================================================================
# VALIDATION
# ============================================================================

def validate_inspection(
    machine_id: str,
    batch_id: str,
    part_id: str,
    inspected_units: float,
    result: str,
    rejection_reason: str,
    inspector: str,
):

    machine_id = machine_id.strip().upper()
    result = result.strip().upper()
    rejection_reason = rejection_reason.strip()

    if machine_id not in VALID_MACHINES:

        raise ValueError(
            f"Invalid machine_id: {machine_id}. "
            f"Valid machines: {sorted(VALID_MACHINES)}"
        )


    if not batch_id.strip():

        raise ValueError(
            "batch_id cannot be empty."
        )


    if not part_id.strip():

        raise ValueError(
            "part_id cannot be empty."
        )


    try:

        inspected_units = float(
            inspected_units
        )

    except (
        TypeError,
        ValueError,
    ):

        raise ValueError(
            "inspected_units must be numeric."
        )


    if inspected_units <= 0:

        raise ValueError(
            "inspected_units must be greater than zero."
        )


    if inspected_units > 100000:

        raise ValueError(
            "inspected_units is unrealistically large."
        )


    if result not in VALID_RESULTS:

        raise ValueError(
            f"Invalid result: {result}. "
            f"Valid results: {sorted(VALID_RESULTS)}"
        )


    if result == "REJECT":

        if rejection_reason not in VALID_REJECTION_REASONS:

            raise ValueError(
                "A REJECT inspection requires a valid "
                "rejection_reason.\n"
                f"Valid reasons: "
                f"{sorted(VALID_REJECTION_REASONS)}"
            )

    else:

        # GOOD parts must not carry a rejection reason.
        rejection_reason = ""


    if not inspector.strip():

        inspector = "SYSTEM"


    return {
        "machine_id": machine_id,
        "batch_id": batch_id.strip(),
        "part_id": part_id.strip(),
        "inspected_units": inspected_units,
        "result": result,
        "rejection_reason": rejection_reason,
        "inspector": inspector.strip(),
    }


# ============================================================================
# APPEND INSPECTION
# ============================================================================

def add_inspection(
    machine_id: str,
    batch_id: str,
    part_id: str,
    inspected_units: float,
    result: str,
    rejection_reason: str = "",
    inspector: str = "SYSTEM",
):

    ensure_file()


    record = validate_inspection(
        machine_id=machine_id,
        batch_id=batch_id,
        part_id=part_id,
        inspected_units=inspected_units,
        result=result,
        rejection_reason=rejection_reason,
        inspector=inspector,
    )


    timestamp = int(
        datetime.now(
            timezone.utc
        ).timestamp()
    )


    inspection_id = (
        f"QI-"
        f"{record['machine_id']}-"
        f"{timestamp}-"
        f"{uuid.uuid4().hex[:8].upper()}"
    )


    row = {
        "timestamp": timestamp,
        "inspection_id": inspection_id,
        **record,
    }


    with INSPECTION_PATH.open(
        "a",
        newline="",
        encoding="utf-8",
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )

        writer.writerow(row)


    return row


# ============================================================================
# SUMMARY
# ============================================================================

def summarize():

    ensure_file()


    import pandas as pd

    df = pd.read_csv(
        INSPECTION_PATH
    )


    if df.empty:

        return {
            "total_inspected_units": 0.0,
            "good_units": 0.0,
            "rejected_units": 0.0,
            "quality_percent": 0.0,
            "inspection_records": 0,
        }


    df["inspected_units"] = pd.to_numeric(
        df["inspected_units"],
        errors="coerce",
    ).fillna(0.0)


    good_units = float(
        df.loc[
            df["result"].eq("GOOD"),
            "inspected_units",
        ].sum()
    )


    rejected_units = float(
        df.loc[
            df["result"].eq("REJECT"),
            "inspected_units",
        ].sum()
    )


    total_units = (
        good_units
        +
        rejected_units
    )


    quality_percent = (
        0.0
        if total_units <= 0
        else (
            good_units
            /
            total_units
            *
            100.0
        )
    )


    return {
        "total_inspected_units": total_units,
        "good_units": good_units,
        "rejected_units": rejected_units,
        "quality_percent": quality_percent,
        "inspection_records": len(df),
    }


# ============================================================================
# CLI
# ============================================================================

def main():

    parser = argparse.ArgumentParser(
        description="INDUS_TWIN Quality Inspection Backend"
    )


    subparsers = parser.add_subparsers(
        dest="command"
    )


    # ------------------------------------------------------------------------
    # ADD
    # ------------------------------------------------------------------------

    add_parser = subparsers.add_parser(
        "add",
        help="Add a quality inspection record.",
    )


    add_parser.add_argument(
        "--machine",
        required=True,
    )

    add_parser.add_argument(
        "--batch",
        required=True,
    )

    add_parser.add_argument(
        "--part",
        required=True,
    )

    add_parser.add_argument(
        "--units",
        required=True,
        type=float,
    )

    add_parser.add_argument(
        "--result",
        required=True,
        choices=sorted(
            VALID_RESULTS
        ),
    )

    add_parser.add_argument(
        "--reason",
        default="",
    )

    add_parser.add_argument(
        "--inspector",
        default="SYSTEM",
    )


    # ------------------------------------------------------------------------
    # SUMMARY
    # ------------------------------------------------------------------------

    subparsers.add_parser(
        "summary",
        help="Show current inspection summary.",
    )


    args = parser.parse_args()


    if args.command == "add":

        row = add_inspection(

            machine_id=args.machine,

            batch_id=args.batch,

            part_id=args.part,

            inspected_units=args.units,

            result=args.result,

            rejection_reason=args.reason,

            inspector=args.inspector,
        )


        print("=" * 70)
        print("QUALITY INSPECTION RECORDED")
        print("=" * 70)

        for key, value in row.items():

            print(
                f"{key}: {value}"
            )


        print()
        print(
            f"Saved -> {INSPECTION_PATH}"
        )

        print("=" * 70)


    elif args.command == "summary":

        result = summarize()


        print("=" * 70)
        print("QUALITY INSPECTION SUMMARY")
        print("=" * 70)

        for key, value in result.items():

            if key == "quality_percent":

                print(
                    f"{key}: {value:.2f}%"
                )

            else:

                print(
                    f"{key}: {value}"
                )

        print("=" * 70)


    else:

        parser.print_help()


if __name__ == "__main__":

    main()
