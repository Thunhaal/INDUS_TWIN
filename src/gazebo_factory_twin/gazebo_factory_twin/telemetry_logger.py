#!/usr/bin/env python3

import csv
import json
import os
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TelemetryLogger(Node):

    def __init__(self):
        super().__init__("telemetry_logger")

        # ============================================================
        # PATHS
        # ============================================================

        self.csv_path = os.path.expanduser(
            "~/INDUS_TWIN/data/02_operations/machine_telemetry.csv"
        )

        # ============================================================
        # CSV SCHEMA
        # ============================================================

        self.fields = [
            # Core telemetry.
            "timestamp",
            "machine_id",
            "state",
            "power_kw",
            "energy_kwh",
            "load_percent",
            "temperature_c",
            "vibration_mm_s",
            "rpm",
            "production_rate",
            "units_produced",

            # Fault information.
            "faulted",
            "fault_code",
            "fault_reason",
            "fault_timestamp",

            # Maintenance information.
            "maintenance_mode",
            "maintenance_started_at",
            "maintenance_required",

            # Persistence / escalation information.
            "persistence_count",
            "persistence_window",
            "persistence_threshold",
            "persistence_ratio",
            "persistence_escalated",
            "escalation_state",
            "damage_level",

            # Anomaly information.
            "anomaly",
            "anomaly_type",
            "anomaly_severity",
            "anomaly_started_at",
            "anomaly_source",
            "manual_anomaly_active",

            # Scenario information.
            "scenario_id",
            "scenario_type",
        ]

        os.makedirs(
            os.path.dirname(self.csv_path),
            exist_ok=True,
        )

        # ============================================================
        # LIVE TELEMETRY CACHE
        # ============================================================

        self.latest = {}

        # Write every 10 seconds so that the AI engine, which also
        # runs every 10 seconds, always receives recent telemetry.
        self.write_interval_sec = 10.0

        self.last_write_time = 0.0

        # ============================================================
        # FILE
        # ============================================================

        self._prepare_csv_file()

        self.file = open(
            self.csv_path,
            "a",
            newline="",
            buffering=1,
        )

        self.writer = csv.DictWriter(
            self.file,
            fieldnames=self.fields,
            extrasaction="ignore",
        )

        if os.path.getsize(self.csv_path) == 0:
            self.writer.writeheader()

        # ============================================================
        # ROS SUBSCRIPTION
        # ============================================================

        self.subscription = self.create_subscription(
            String,
            "/factory/machine_state",
            self.telemetry_callback,
            50,
        )

        # ============================================================
        # WRITE TIMER
        # ============================================================

        self.timer = self.create_timer(
            1.0,
            self.check_write,
        )

        # ============================================================
        # STARTUP
        # ============================================================

        self.get_logger().info(
            "=========================================="
        )

        self.get_logger().info(
            "INDUS_TWIN TELEMETRY LOGGER STARTED"
        )

        self.get_logger().info(
            f"Output: {self.csv_path}"
        )

        self.get_logger().info(
            "Source: /factory/machine_state"
        )

        self.get_logger().info(
            f"Write interval: "
            f"{self.write_interval_sec:.0f} seconds"
        )

        self.get_logger().info(
            "Persistence telemetry enabled"
        )

        self.get_logger().info(
            "=========================================="
        )

    # ================================================================
    # CSV FILE PREPARATION / MIGRATION
    # ================================================================

    def _prepare_csv_file(self):
        """
        Ensure the existing telemetry CSV uses the current schema.

        Older versions of the logger wrote only the original 12
        columns. If such a file exists, migrate its historical rows
        into the expanded schema before appending new telemetry.
        """

        if not os.path.exists(self.csv_path):
            return

        try:
            if os.path.getsize(self.csv_path) == 0:
                return

            with open(
                self.csv_path,
                "r",
                newline="",
            ) as existing_file:

                reader = csv.DictReader(existing_file)

                existing_fields = reader.fieldnames or []

                # Already using the current schema.
                if existing_fields == self.fields:
                    return

                old_rows = list(reader)

            temp_path = self.csv_path + ".migration_tmp"

            with open(
                temp_path,
                "w",
                newline="",
            ) as migrated_file:

                writer = csv.DictWriter(
                    migrated_file,
                    fieldnames=self.fields,
                    extrasaction="ignore",
                )

                writer.writeheader()

                for old_row in old_rows:

                    migrated_row = {}

                    for field in self.fields:
                        migrated_row[field] = old_row.get(
                            field,
                            "",
                        )

                    writer.writerow(migrated_row)

            os.replace(
                temp_path,
                self.csv_path,
            )

            self.get_logger().info(
                "Migrated existing machine_telemetry.csv "
                "to the expanded telemetry schema."
            )

        except Exception as error:

            self.get_logger().error(
                f"Failed to migrate telemetry CSV: {error}"
            )

            temp_path = self.csv_path + ".migration_tmp"

            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

            raise

    # ================================================================
    # ROS TELEMETRY CALLBACK
    # ================================================================

    def telemetry_callback(self, message):

        try:

            data = json.loads(message.data)

            machine_id = data["machine_id"]

            # Store the newest observation for each machine.
            self.latest[machine_id] = data

        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as error:

            self.get_logger().error(
                f"Invalid telemetry message: {error}"
            )

    # ================================================================
    # WRITE TELEMETRY
    # ================================================================

    def check_write(self):

        now = time.time()

        # Wait until the next 10-second write interval.
        if (
            self.last_write_time > 0
            and now - self.last_write_time < self.write_interval_sec
        ):
            return

        # Don't write an empty snapshot.
        if not self.latest:
            return

        timestamp = int(now)

        records_written = 0

        for machine_id, data in sorted(
            self.latest.items()
        ):

            row = {
                # ----------------------------------------------------
                # Core telemetry.
                # ----------------------------------------------------

                "timestamp":
                    timestamp,

                "machine_id":
                    machine_id,

                "state":
                    data.get(
                        "state",
                        "UNKNOWN",
                    ),

                "power_kw":
                    data.get(
                        "power_kw",
                        0.0,
                    ),

                "energy_kwh":
                    data.get(
                        "energy_kwh",
                        0.0,
                    ),

                "load_percent":
                    data.get(
                        "load_percent",
                        0.0,
                    ),

                "temperature_c":
                    data.get(
                        "temperature",
                        0.0,
                    ),

                "vibration_mm_s":
                    data.get(
                        "vibration",
                        0.0,
                    ),

                "rpm":
                    data.get(
                        "rpm",
                        0.0,
                    ),

                "production_rate":
                    data.get(
                        "production_rate",
                        0.0,
                    ),

                "units_produced":
                    data.get(
                        "units_produced",
                        0.0,
                    ),

                # ----------------------------------------------------
                # Fault information.
                # ----------------------------------------------------

                "faulted":
                    data.get(
                        "faulted",
                        False,
                    ),

                "fault_code":
                    data.get(
                        "fault_code",
                        "",
                    ),

                "fault_reason":
                    data.get(
                        "fault_reason",
                        "",
                    ),

                "fault_timestamp":
                    data.get(
                        "fault_timestamp",
                        0.0,
                    ),

                # ----------------------------------------------------
                # Maintenance information.
                # ----------------------------------------------------

                "maintenance_mode":
                    data.get(
                        "maintenance_mode",
                        False,
                    ),

                "maintenance_started_at":
                    data.get(
                        "maintenance_started_at",
                        0.0,
                    ),

                "maintenance_required":
                    data.get(
                        "maintenance_required",
                        False,
                    ),

                # ----------------------------------------------------
                # Persistence / escalation information.
                # ----------------------------------------------------

                "persistence_count":
                    data.get(
                        "persistence_count",
                        0,
                    ),

                "persistence_window":
                    data.get(
                        "persistence_window",
                        0,
                    ),

                "persistence_threshold":
                    data.get(
                        "persistence_threshold",
                        0,
                    ),

                "persistence_ratio":
                    data.get(
                        "persistence_ratio",
                        0.0,
                    ),

                "persistence_escalated":
                    data.get(
                        "persistence_escalated",
                        False,
                    ),

                "escalation_state":
                    data.get(
                        "escalation_state",
                        "NORMAL",
                    ),

                "damage_level":
                    data.get(
                        "damage_level",
                        0.0,
                    ),

                # ----------------------------------------------------
                # Anomaly information.
                # ----------------------------------------------------

                "anomaly":
                    data.get(
                        "anomaly",
                        False,
                    ),

                "anomaly_type":
                    data.get(
                        "anomaly_type",
                        "NORMAL",
                    ),

                "anomaly_severity":
                    data.get(
                        "anomaly_severity",
                        "NONE",
                    ),

                "anomaly_started_at":
                    data.get(
                        "anomaly_started_at",
                        0.0,
                    ),

                "anomaly_source":
                    data.get(
                        "anomaly_source",
                        "",
                    ),

                "manual_anomaly_active":
                    data.get(
                        "manual_anomaly_active",
                        False,
                    ),

                # ----------------------------------------------------
                # Scenario information.
                # ----------------------------------------------------

                "scenario_id":
                    data.get(
                        "scenario_id",
                        "NORMAL",
                    ),

                "scenario_type":
                    data.get(
                        "scenario_type",
                        "NORMAL",
                    ),
            }

            self.writer.writerow(row)

            records_written += 1

        self.file.flush()

        self.last_write_time = now

        self.get_logger().info(
            f"Wrote live telemetry snapshot: "
            f"{records_written} machines"
        )

    # ================================================================
    # SHUTDOWN
    # ================================================================

    def destroy_node(self):

        try:
            self.file.flush()
            self.file.close()

        except Exception:
            pass

        super().destroy_node()


# ====================================================================
# MAIN
# ====================================================================

def main():

    rclpy.init()

    node = TelemetryLogger()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
