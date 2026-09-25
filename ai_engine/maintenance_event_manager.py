#!/usr/bin/env python3

import os
import uuid
from datetime import datetime

import pandas as pd


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

MAINTENANCE_OUTPUT = os.path.join(
    PROJECT_ROOT,
    "ai_engine",
    "maintenance_output.csv"
)

ANOMALY_OUTPUT = os.path.join(
    PROJECT_ROOT,
    "ai_engine",
    "anomaly_output.csv"
)

EVENT_FILE = os.path.join(
    PROJECT_ROOT,
    "data",
    "03_maintenance",
    "maintenance_events.csv"
)


# ============================================================
# MAINTENANCE EVENT SCHEMA
# ============================================================

EVENT_COLUMNS = [
    "event_id",
    "timestamp",
    "machine_id",
    "event_type",
    "severity",
    "fault_code",
    "downtime_min",
    "maintenance_required",
    "description",
    "status",
    "last_updated",
]


# ============================================================
# LOAD EXISTING EVENTS
# ============================================================

def load_events():
    """
    Load existing maintenance events.

    Existing operator statuses are preserved.
    """

    if not os.path.exists(EVENT_FILE):
        return pd.DataFrame(columns=EVENT_COLUMNS)

    try:
        df = pd.read_csv(EVENT_FILE)

    except Exception as exc:
        print(
            f"[WARNING] Could not read maintenance events: {exc}"
        )

        return pd.DataFrame(columns=EVENT_COLUMNS)

    # Add missing columns if required.
    for column in EVENT_COLUMNS:

        if column not in df.columns:

            if column == "status":
                df[column] = "SUBMITTED"

            elif column == "last_updated":
                df[column] = ""

            else:
                df[column] = ""

    # Default empty statuses to SUBMITTED.
    if "status" in df.columns:
        df["status"] = (
            df["status"]
            .fillna("SUBMITTED")
            .astype(str)
            .replace("", "SUBMITTED")
        )

    return df[EVENT_COLUMNS]


# ============================================================
# SAVE EVENTS
# ============================================================

def save_events(df):
    """
    Save maintenance events to CSV.
    """

    os.makedirs(
        os.path.dirname(EVENT_FILE),
        exist_ok=True
    )

    df.to_csv(
        EVENT_FILE,
        index=False
    )


# ============================================================
# TIMESTAMP HELPERS
# ============================================================

def normalize_timestamp(timestamp):
    """
    Convert timestamps safely.

    Supported:
        - Unix epoch seconds
        - Unix epoch milliseconds
        - normal datetime strings
        - pandas timestamps

    Returns a pandas Timestamp or None.
    """

    if timestamp is None:
        return None

    try:

        # Handle pandas NaN.
        if pd.isna(timestamp):
            return None

    except Exception:
        pass

    try:

        # Numeric timestamp.
        if isinstance(timestamp, (int, float)):

            value = float(timestamp)

            # Epoch milliseconds.
            if value > 100_000_000_000:
                return pd.to_datetime(
                    value,
                    unit="ms"
                )

            # Epoch seconds.
            if value > 1_000_000_000:
                return pd.to_datetime(
                    value,
                    unit="s"
                )

            # Otherwise treat as a normal numeric value.
            return pd.to_datetime(
                value,
                unit="s"
            )

        value = str(timestamp).strip()

        if not value:
            return None

        # Numeric value stored as CSV text.
        try:

            numeric_value = float(value)

            if numeric_value > 100_000_000_000:

                return pd.to_datetime(
                    numeric_value,
                    unit="ms"
                )

            if numeric_value > 1_000_000_000:

                return pd.to_datetime(
                    numeric_value,
                    unit="s"
                )

        except ValueError:
            pass

        # Normal datetime string.
        return pd.to_datetime(value)

    except Exception:
        return None


def get_event_timestamp(row):
    """
    Extract timestamp from AI output.
    """

    possible_columns = [
        "timestamp",
        "detected_at",
        "time",
    ]

    for column in possible_columns:

        if column in row.index:

            value = row[column]

            if pd.notna(value):

                value = str(value).strip()

                if value:
                    return value

    # Fallback to current time.
    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# EVENT ID
# ============================================================

def generate_event_id(
    machine_id,
    event_type,
    timestamp
):
    """
    Generate a unique readable maintenance event ID.

    Handles Unix timestamps correctly.
    """

    dt = normalize_timestamp(timestamp)

    if dt is not None:

        ts = dt.strftime(
            "%Y%m%d%H%M%S"
        )

    else:

        ts = datetime.now().strftime(
            "%Y%m%d%H%M%S"
        )

    machine_clean = (
        str(machine_id)
        .strip()
        .replace(" ", "_")
    )

    event_clean = (
        str(event_type)
        .strip()
        .replace(" ", "_")
    )

    unique_id = uuid.uuid4().hex[:6].upper()

    return (
        f"ME-"
        f"{machine_clean}-"
        f"{event_clean}-"
        f"{ts}-"
        f"{unique_id}"
    )


# ============================================================
# BOOLEAN NORMALIZATION
# ============================================================

def normalize_bool(value):
    """
    Convert common boolean representations to True/False.
    """

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    try:

        if pd.isna(value):
            return False

    except Exception:
        pass

    value = str(value).strip().lower()

    return value in {
        "true",
        "1",
        "yes",
        "y",
        "trigger",
        "triggered",
        "anomaly",
    }


# ============================================================
# TEXT / NUMERIC HELPERS
# ============================================================

def get_numeric_value(
    row,
    column,
    default=0.0
):
    """
    Safely read a numeric field from a telemetry/AI row.
    """

    if column not in row.index:
        return default

    value = row[column]

    if pd.isna(value):
        return default

    try:
        return float(value)

    except (ValueError, TypeError):
        return default


def get_valid_text(
    row,
    column,
    invalid_values=None
):
    """
    Safely read a non-empty text field.
    """

    if invalid_values is None:
        invalid_values = {
            "",
            "NORMAL",
            "NONE",
            "NAN",
            "NO_ANOMALY",
            "NO_FAULT",
        }

    if column not in row.index:
        return ""

    value = row[column]

    if pd.isna(value):
        return ""

    value = str(value).strip()

    invalid_upper = {
        str(item).upper()
        for item in invalid_values
    }

    if value.upper() in invalid_upper:
        return ""

    return value


def is_persistent_anomaly(row):
    """
    Detect whether the Factory Twin has reached its persistence
    escalation condition.

    The Factory Twin defines the persistence threshold. This helper
    only reads that existing telemetry; it does not recalculate
    persistence.
    """

    persistence_count = get_numeric_value(
        row,
        "persistence_count",
        default=0.0
    )

    persistence_window = get_numeric_value(
        row,
        "persistence_window",
        default=0.0
    )

    persistence_threshold = get_numeric_value(
        row,
        "persistence_threshold",
        default=0.0
    )

    persistence_escalated = (
        "persistence_escalated" in row.index
        and normalize_bool(
            row["persistence_escalated"]
        )
    )

    # Prefer the explicit escalation flag when available.
    if persistence_escalated:
        return True

    if (
        persistence_window > 0
        and persistence_threshold > 0
        and persistence_count >= persistence_threshold
    ):
        return True

    return False


# ============================================================
# EVENT TYPE
# ============================================================

def get_event_type(row):
    """
    Return the most specific maintenance condition represented by
    the latest AI observation.

    Faults/trips have priority over predictive-risk labels.

    The Factory Twin anomaly_type is preferred over a generic
    maintenance-risk label because it represents the actual
    injected/detected machine condition.
    """

    # --------------------------------------------------------
    # 1. Hard machine fault / trip has highest priority.
    # --------------------------------------------------------

    state = ""
    if "state" in row.index and pd.notna(row["state"]):
        state = str(row["state"]).strip().upper()

    faulted = (
        "faulted" in row.index
        and normalize_bool(row["faulted"])
    )

    if state == "FAULT" or faulted:

        for column in (
            "fault_code",
            "fault_reason",
        ):

            if column not in row.index:
                continue

            value = row[column]

            if pd.isna(value):
                continue

            reason = str(value).strip()

            if reason.upper() not in {
                "",
                "NORMAL",
                "NONE",
                "NAN",
                "NO_FAULT",
            }:
                return reason

        return "EQUIPMENT_FAILURE"

    # --------------------------------------------------------
    # 2. Explicit Factory Twin anomaly type.
    # --------------------------------------------------------

    anomaly_type = get_valid_text(
        row,
        "anomaly_type"
    )

    if anomaly_type:
        return anomaly_type

    # --------------------------------------------------------
    # 3. Persistent condition without a named anomaly type.
    # --------------------------------------------------------

    if is_persistent_anomaly(row):

        fault_code = get_valid_text(
            row,
            "fault_code"
        )

        if fault_code:
            return fault_code

    # --------------------------------------------------------
    # 4. Predictive maintenance reason.
    # --------------------------------------------------------

    maintenance_reason = get_valid_text(
        row,
        "maintenance_reason"
    )

    if maintenance_reason:
        return maintenance_reason

    # --------------------------------------------------------
    # 5. Existing event type, when supplied.
    # --------------------------------------------------------

    event_type = get_valid_text(
        row,
        "event_type"
    )

    if event_type:
        return event_type

    # --------------------------------------------------------
    # 6. Derive from sensor anomaly flags.
    # --------------------------------------------------------

    faults = []

    if (
        "temperature_anomaly" in row.index
        and normalize_bool(row["temperature_anomaly"])
    ):
        faults.append("TEMPERATURE_DEVIATION")

    if (
        "vibration_anomaly" in row.index
        and normalize_bool(row["vibration_anomaly"])
    ):
        faults.append("VIBRATION_DEVIATION")

    if (
        "rpm_anomaly" in row.index
        and normalize_bool(row["rpm_anomaly"])
    ):
        faults.append("RPM_DEVIATION")

    if faults:
        return " + ".join(faults)

    return "MAINTENANCE_REQUIRED"


# ============================================================
# SEVERITY
# ============================================================

def get_severity(row):
    """
    Determine work-order severity.

    A confirmed machine fault/trip is always CRITICAL, regardless of
    the predictive-maintenance risk label calculated for the same row.
    """

    state = ""
    if "state" in row.index and pd.notna(row["state"]):
        state = str(row["state"]).strip().upper()

    faulted = (
        "faulted" in row.index
        and normalize_bool(row["faulted"])
    )

    if state == "FAULT" or faulted:
        return "CRITICAL"

    if "anomaly_severity" in row.index:

        value = row["anomaly_severity"]

        if pd.notna(value):

            label = str(value).strip().upper()

            if label in {
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
            }:
                return label

    if "maintenance_label" in row.index:

        value = row["maintenance_label"]

        if pd.notna(value):

            label = str(value).strip().upper()

            if label in {
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
            }:
                return label

    # Fallback to explicit severity label.
    if "severity" in row.index:

        value = row["severity"]

        if pd.notna(value):

            label = str(value).strip().upper()

            if label in {
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
            }:
                return label

    # Fallback to risk score.
    if "maintenance_risk" in row.index:

        try:

            risk = float(
                row["maintenance_risk"]
            )

            if risk >= 0.90:
                return "CRITICAL"

            if risk >= 0.75:
                return "HIGH"

            if risk >= 0.50:
                return "MEDIUM"

            return "LOW"

        except (ValueError, TypeError):
            pass

    return "MEDIUM"


# ============================================================
# FAULT CODE
# ============================================================

def get_fault_code(row):
    """
    Return the most useful engineering-style fault code.

    For a confirmed machine trip, preserve a concrete fault code supplied
    by the Factory Twin when available.

    For a persistent/manual anomaly that has not yet become a hard FAULT,
    use the Factory Twin anomaly_type as the fallback engineering code.
    """

    state = ""
    if "state" in row.index and pd.notna(row["state"]):
        state = str(row["state"]).strip().upper()

    faulted = (
        "faulted" in row.index
        and normalize_bool(row["faulted"])
    )

    # --------------------------------------------------------
    # Hard fault.
    # --------------------------------------------------------

    if state == "FAULT" or faulted:

        fault_code = get_valid_text(
            row,
            "fault_code"
        )

        if fault_code:
            return fault_code

        reason = get_valid_text(
            row,
            "fault_reason"
        )

        if reason:
            return reason

        return "EQUIP-FAULT"

    # --------------------------------------------------------
    # Persistent anomaly.
    # --------------------------------------------------------

    if is_persistent_anomaly(row):

        fault_code = get_valid_text(
            row,
            "fault_code"
        )

        if fault_code:
            return fault_code

        anomaly_type = get_valid_text(
            row,
            "anomaly_type"
        )

        if anomaly_type:
            return anomaly_type

    # --------------------------------------------------------
    # General anomaly fallback.
    # --------------------------------------------------------

    anomaly_type = get_valid_text(
        row,
        "anomaly_type"
    )

    mapping = {

        "SEVERE_OVERLOAD":
            "PWR-OVERLOAD-SEV",

        "OVERLOAD":
            "PWR-OVERLOAD",

        "ENERGY_WHILE_IDLE":
            "ENERGY-IDLE",

        "TEMPERATURE_DEVIATION":
            "TEMP-DEVIATION",

        "SEVERE_TEMPERATURE_DEVIATION":
            "TEMP-SEVERE",

        "SEVERE_VIBRATION_DEVIATION":
            "VIB-SEVERE",

        "VIBRATION_DEVIATION":
            "VIB-DEVIATION",

        "RPM_DEVIATION":
            "RPM-DEVIATION",
    }

    if anomaly_type:
        return mapping.get(
            anomaly_type.upper(),
            anomaly_type
        )

    event_type = (
        get_event_type(row)
        .upper()
        .strip()
    )

    fallback_mapping = {

        "HIGH_MAINTENANCE_RISK":
            "MAINT-RISK-HIGH",

        "MEDIUM_MAINTENANCE_RISK":
            "MAINT-RISK-MED",

        "EQUIPMENT_FAILURE":
            "EQUIP-FAULT",
    }

    return fallback_mapping.get(
        event_type,
        "AI-DETECTED"
    )


# ============================================================
# DESCRIPTION
# ============================================================

def get_description(row):
    """
    Create a human-readable maintenance description.

    Persistent anomalies get a dedicated description using the
    Factory Twin's actual persistence telemetry.

    This prevents a maintenance ticket from incorrectly describing
    a persistent 6/8 anomaly as only an instantaneous sensor event.
    """

    state = ""
    if "state" in row.index and pd.notna(row["state"]):
        state = str(row["state"]).strip().upper()

    faulted = (
        "faulted" in row.index
        and normalize_bool(row["faulted"])
    )

    # ========================================================
    # 1. Persistent anomaly
    # ========================================================

    if is_persistent_anomaly(row):

        persistence_count = int(
            round(
                get_numeric_value(
                    row,
                    "persistence_count",
                    default=0.0
                )
            )
        )

        persistence_window = int(
            round(
                get_numeric_value(
                    row,
                    "persistence_window",
                    default=0.0
                )
            )
        )

        anomaly_type = get_valid_text(
            row,
            "anomaly_type"
        )

        fault_code = get_fault_code(row)

        severity = get_severity(row)

        lines = [
            (
                "Persistent anomaly detected: "
                f"{persistence_count}/{persistence_window} "
                "readings abnormal."
            )
        ]

        if anomaly_type:
            lines.append(
                f"Anomaly Type: {anomaly_type}."
            )

        if fault_code:
            lines.append(
                f"Fault Code: {fault_code}."
            )

        lines.append(
            f"Severity: {severity}."
        )

        if state == "FAULT" or faulted:

            lines.append(
                "Machine entered FAULT state. "
                "Production is stopped and "
                "maintenance is required before restart."
            )

        elif state == "IDLE":

            lines.append(
                "Machine entered IDLE state. "
                "Maintenance is required before "
                "return to production."
            )

        else:

            lines.append(
                f"Machine state: {state or 'UNKNOWN'}. "
                "Maintenance review is required."
            )

        return " ".join(lines)

    # ========================================================
    # 2. Confirmed machine fault / trip
    # ========================================================

    if state == "FAULT" or faulted:

        reason = ""

        for column in (
            "fault_reason",
            "fault_code",
        ):

            candidate = get_valid_text(
                row,
                column
            )

            if candidate:
                reason = candidate
                break

        fault_code = get_fault_code(row)

        severity = get_severity(row)

        if reason:

            return (
                f"Machine entered FAULT state due to "
                f"{reason}. "
                f"Fault Code: {fault_code}. "
                f"Severity: {severity}. "
                f"Production is stopped and maintenance "
                f"is required before restart."
            )

        return (
            "Machine entered FAULT state. "
            f"Fault Code: {fault_code}. "
            f"Severity: {severity}. "
            "Production is stopped and maintenance "
            "is required before restart."
        )

    # ========================================================
    # 3. Predictive maintenance description
    # ========================================================

    possible_columns = [
        "reason",
        "maintenance_reason",
        "description",
    ]

    for column in possible_columns:

        value = get_valid_text(
            row,
            column,
            invalid_values={
                "",
                "NORMAL",
                "NONE",
                "NAN",
            }
        )

        if value:
            return value

    # ========================================================
    # 4. Generic fallback
    # ========================================================

    event_type = get_event_type(row)
    severity = get_severity(row)

    return (
        f"AI detected {severity} "
        f"{event_type} condition requiring "
        f"maintenance review."
    )


# ============================================================
# SHOULD CREATE EVENT
# ============================================================

def should_create_event(row):
    """
    Decide whether the latest AI observation represents
    a real maintenance condition.

    A ticket requires a concrete machine condition.

    Ticket creation occurs for:
        - FAULT state
        - IDLE state
        - factory maintenance_required flag
        - persistent/escalated anomaly
        - explicit sensor anomalies
        - explicit anomaly flag
        - explicit non-normal anomaly type

    Standalone LOW/MEDIUM/HIGH predictive-risk labels do NOT create
    tickets by themselves.
    """

    # ========================================================
    # 0. Confirmed machine fault / trip / idle
    # ========================================================

    state = ""
    if "state" in row.index and pd.notna(row["state"]):
        state = str(row["state"]).strip().upper()

    # --------------------------------------------------------
    # A machine already in MAINTENANCE is already being serviced.
    # Do not create a second ticket for the maintenance state itself.
    # --------------------------------------------------------

    if state == "MAINTENANCE":
        return False

    faulted = (
        "faulted" in row.index
        and normalize_bool(row["faulted"])
    )

    if state in {
        "FAULT",
        "IDLE",
    } or faulted:
        return True

    # ========================================================
    # 1. Factory Twin explicitly requires maintenance.
    # ========================================================

    if "maintenance_required" in row.index:

        if normalize_bool(
            row["maintenance_required"]
        ):
            return True

    # ========================================================
    # 2. Persistent / escalated anomaly.
    # ========================================================

    if is_persistent_anomaly(row):
        return True

    # ========================================================
    # 3. Explicit sensor anomalies.
    # ========================================================

    anomaly_columns = [
        "temperature_anomaly",
        "vibration_anomaly",
        "rpm_anomaly",
    ]

    for column in anomaly_columns:

        if column not in row.index:
            continue

        if normalize_bool(row[column]):
            return True

    # ========================================================
    # 4. Explicit anomaly flag.
    # ========================================================

    if "is_anomaly" in row.index:

        if normalize_bool(row["is_anomaly"]):
            return True

    if "anomaly" in row.index:

        if normalize_bool(row["anomaly"]):
            return True

    # ========================================================
    # 5. Explicit Factory Twin anomaly type.
    #
    # This catches injected/manual conditions even when the
    # analytics risk score itself has not crossed a threshold.
    # ========================================================

    anomaly_type = get_valid_text(
        row,
        "anomaly_type"
    )

    if anomaly_type:
        return True

    # ========================================================
    # 6. Maintenance reason.
    #
    # Only accept concrete sensor/engineering reasons here.
    # Do NOT create a ticket from generic risk labels.
    # ========================================================

    maintenance_reason = get_valid_text(
        row,
        "maintenance_reason"
    )

    if maintenance_reason:

        ignored_risk_reasons = {
            "LOW_MAINTENANCE_RISK",
            "MEDIUM_MAINTENANCE_RISK",
            "HIGH_MAINTENANCE_RISK",
            "CRITICAL_MAINTENANCE_RISK",
        }

        if maintenance_reason.upper() not in ignored_risk_reasons:
            return True

    return False


# ============================================================
# DUPLICATE ACTIVE EVENT CHECK
# ============================================================

def event_already_exists(
    events,
    machine_id,
    event_type
):
    """
    Prevent duplicate active events for the same machine.

    The event type is intentionally NOT part of the duplicate key.
    When maintenance starts, the Factory Twin changes its current
    anomaly_type to MAINTENANCE. Without a machine-level active-ticket
    check, an existing HIGH_LOAD/other ticket can be followed by a
    second MAINTENANCE ticket while the first ticket is still ONGOING.

    SUBMITTED and ONGOING events are considered active.
    COMPLETED events may generate a new event only after the machine
    leaves the previous maintenance episode and a new condition occurs.
    """

    if events.empty:
        return False

    machine_mask = (
        events["machine_id"]
        .astype(str)
        .str.strip()
        ==
        str(machine_id).strip()
    )

    status_mask = (
        events["status"]
        .astype(str)
        .str.strip()
        .str.upper()
        .isin(
            [
                "SUBMITTED",
                "ONGOING",
            ]
        )
    )

    return bool(
        (
            machine_mask
            & status_mask
        ).any()
    )


# ============================================================
# DOWNTIME
# ============================================================

def get_downtime(row):
    """
    Extract downtime safely.
    """

    if "downtime_min" not in row.index:
        return 0

    value = row["downtime_min"]

    if pd.isna(value):
        return 0

    try:
        return float(value)

    except (ValueError, TypeError):
        return 0


# ============================================================
# PROCESS EVENTS
# ============================================================

def process_maintenance_events():
    """
    Convert only the latest AI observation for each machine
    into a maintenance event.

    Historical observations are not converted into new tickets.
    """

    print()
    print("=" * 55)
    print("MAINTENANCE EVENT MANAGER")
    print("=" * 55)

    events = load_events()

    # --------------------------------------------------------
    # Find AI output
    # --------------------------------------------------------

    source_file = None

    if os.path.exists(MAINTENANCE_OUTPUT):
        source_file = MAINTENANCE_OUTPUT

    elif os.path.exists(ANOMALY_OUTPUT):
        source_file = ANOMALY_OUTPUT

    if source_file is None:

        print(
            "[INFO] No AI maintenance/anomaly output found."
        )

        print(
            "       No maintenance events created."
        )

        return events

    print(
        f"[INFO] Reading AI output:\n"
        f"       {source_file}"
    )

    try:
        ai_df = pd.read_csv(source_file)

    except Exception as exc:

        print(
            f"[ERROR] Could not read AI output: {exc}"
        )

        return events

    if ai_df.empty:

        print(
            "[INFO] AI output is empty."
        )

        return events

    if "machine_id" not in ai_df.columns:

        print(
            "[ERROR] AI output does not contain machine_id."
        )

        return events

    # ========================================================
    # CONVERT TIMESTAMP
    # ========================================================

    if "timestamp" in ai_df.columns:

        def timestamp_for_sort(value):

            dt = normalize_timestamp(value)

            if dt is None:
                return pd.Timestamp.min

            return dt

        ai_df["_sort_timestamp"] = (
            ai_df["timestamp"]
            .apply(timestamp_for_sort)
        )

    else:

        ai_df["_sort_timestamp"] = pd.Timestamp.now()

    # ========================================================
    # LATEST OBSERVATION PER MACHINE
    # ========================================================

    latest_df = (
        ai_df
        .sort_values("_sort_timestamp")
        .groupby(
            "machine_id",
            as_index=False
        )
        .tail(1)
        .copy()
    )

    print(
        f"[INFO] AI observations : {len(ai_df)}"
    )

    print(
        f"[INFO] Latest machines  : {len(latest_df)}"
    )

    # ========================================================
    # PROCESS LATEST OBSERVATION ONLY
    # ========================================================

    created = 0
    skipped = 0

    for _, row in latest_df.iterrows():

        machine_id = str(
            row["machine_id"]
        ).strip()

        if (
            not machine_id
            or machine_id.lower() == "nan"
        ):
            continue

        # ----------------------------------------------------
        # Check maintenance condition
        # ----------------------------------------------------

        if not should_create_event(row):

            print(
                f"[NORMAL] "
                f"{machine_id} -> no maintenance event"
            )

            skipped += 1
            continue

        # ----------------------------------------------------
        # Determine actual fault
        # ----------------------------------------------------

        event_type = get_event_type(row)

        # ----------------------------------------------------
        # Avoid duplicate active ticket
        # ----------------------------------------------------

        if event_already_exists(
            events,
            machine_id,
            event_type
        ):

            print(
                f"[EXISTING] "
                f"{machine_id} | "
                f"{event_type} -> "
                f"active event already exists"
            )

            skipped += 1
            continue

        # ----------------------------------------------------
        # Event details
        # ----------------------------------------------------

        timestamp = get_event_timestamp(row)

        now = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        new_event = {

            "event_id":
                generate_event_id(
                    machine_id,
                    event_type,
                    timestamp
                ),

            "timestamp":
                timestamp,

            "machine_id":
                machine_id,

            "event_type":
                event_type,

            "severity":
                get_severity(row),

            "fault_code":
                get_fault_code(row),

            "downtime_min":
                get_downtime(row),

            "maintenance_required":
                True,

            "description":
                get_description(row),

            "status":
                "SUBMITTED",

            "last_updated":
                now,
        }

        # ----------------------------------------------------
        # Add event
        # ----------------------------------------------------

        events = pd.concat(
            [
                events,
                pd.DataFrame(
                    [new_event]
                )
            ],
            ignore_index=True
        )

        created += 1

        print(
            f"[NEW EVENT] "
            f"{new_event['event_id']} | "
            f"{machine_id} | "
            f"{event_type} | "
            f"{new_event['severity']} | "
            f"SUBMITTED"
        )

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    save_events(
        events[EVENT_COLUMNS]
    )

    print()
    print("-" * 55)

    print(
        f"AI observations : {len(ai_df)}"
    )

    print(
        f"Latest machines  : {len(latest_df)}"
    )

    print(
        f"Events created   : {created}"
    )

    print(
        f"Events skipped   : {skipped}"
    )

    print(
        f"Total events     : {len(events)}"
    )

    print("-" * 55)

    return events


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    process_maintenance_events()
