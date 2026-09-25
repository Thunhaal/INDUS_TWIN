#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
)
from std_msgs.msg import String


class ScenarioManager(Node):

    # ============================================================
    # HISTORY CSV SCHEMA
    # ============================================================

    HISTORY_FIELDS = [
        "timestamp",
        "scenario_id",
        "scenario_name",
        "scenario_type",
        "duration_min",
        "grid_available_power_kw",
        "solar_available_power_kw",
        "required_reduction_kw",
        "minimum_production_percent",
        "battery_available_kwh",
        "status",
    ]

    # ============================================================
    # SETTINGS
    # ============================================================

    # Broadcast the current scenario every few seconds.
    # This makes the topic usable by late-joining subscribers
    # even without depending entirely on DDS retained history.
    STATE_BROADCAST_INTERVAL_SEC = 2.0

    def __init__(self):
        super().__init__("scenario_manager")

        # ========================================================
        # PROJECT PATHS
        # ========================================================

        self.project_dir = Path(
            os.path.expanduser("~/INDUS_TWIN")
        )

        self.config_file = (
            self.project_dir
            / "config"
            / "scenarios.json"
        )

        self.history_file = (
            self.project_dir
            / "data"
            / "05_scenarios"
            / "scenario_data.csv"
        )

        # ========================================================
        # TOPICS
        # ========================================================

        self.scenario_topic = "/factory/scenario"
        self.command_topic = "/factory/scenario_command"

        # ========================================================
        # SCENARIO STATE QoS
        # ========================================================

        scenario_qos = QoSProfile(
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
            durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
        )

        self.publisher = self.create_publisher(
            String,
            self.scenario_topic,
            scenario_qos,
        )

        # Commands are transient events, so normal QoS is correct.
        self.command_subscription = self.create_subscription(
            String,
            self.command_topic,
            self.command_callback,
            10,
        )

        # ========================================================
        # LOAD SCENARIOS
        # ========================================================

        self.scenarios = self.load_scenarios()

        self.get_logger().info(
            f"Loaded {len(self.scenarios)} scenarios"
        )

        # ========================================================
        # ACTIVE STATE
        # ========================================================

        self.active_scenario: str | None = None
        self.active_until = 0.0

        self.last_state_broadcast = 0.0

        # ========================================================
        # HISTORY
        # ========================================================

        self.prepare_history_file()

        # ========================================================
        # TIMER
        # ========================================================

        self.timer = self.create_timer(
            1.0,
            self.timer_callback,
        )

        # ========================================================
        # STARTUP
        # ========================================================

        self.get_logger().info(
            "=========================================="
        )

        self.get_logger().info(
            "INDUS_TWIN SCENARIO MANAGER STARTED"
        )

        self.get_logger().info(
            f"Config: {self.config_file}"
        )

        self.get_logger().info(
            f"History: {self.history_file}"
        )

        self.get_logger().info(
            "Scenario QoS: TRANSIENT_LOCAL / KEEP_LAST(1)"
        )

        self.get_logger().info(
            "Continuous state broadcast: "
            f"{self.STATE_BROADCAST_INTERVAL_SEC:.1f}s"
        )

        self.get_logger().info(
            "=========================================="
        )

        # ========================================================
        # INITIAL STATE
        # ========================================================

        if "NORMAL" in self.scenarios:

            self.activate_normal()

        else:

            self.get_logger().error(
                "NORMAL scenario is missing from scenarios.json"
            )

    # ============================================================
    # LOAD CONFIGURATION
    # ============================================================

    def load_scenarios(self) -> dict:

        if not self.config_file.exists():

            self.get_logger().error(
                f"Scenario config not found: "
                f"{self.config_file}"
            )

            return {}

        try:

            with open(
                self.config_file,
                "r",
                encoding="utf-8",
            ) as file:

                data = json.load(file)

            if not isinstance(data, dict):

                self.get_logger().error(
                    "Scenario configuration must "
                    "be a JSON object."
                )

                return {}

            return data

        except (
            json.JSONDecodeError,
            OSError,
        ) as error:

            self.get_logger().error(
                f"Failed to load scenarios: {error}"
            )

            return {}

    # ============================================================
    # HISTORY FILE PREPARATION
    # ============================================================

    def prepare_history_file(self):

        self.history_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if not self.history_file.exists():

            self.write_history_header()

            return

        if self.history_file.stat().st_size == 0:

            self.write_history_header()

            return

        try:

            with open(
                self.history_file,
                "r",
                newline="",
                encoding="utf-8",
            ) as file:

                reader = csv.reader(file)

                header = next(
                    reader,
                    [],
                )

            normalized_header = [
                str(value).strip()
                for value in header
            ]

            if normalized_header == self.HISTORY_FIELDS:

                return

            self.get_logger().warning(
                "Scenario history header is malformed. "
                "Repairing..."
            )

            self.repair_history_file()

        except Exception as error:

            self.get_logger().error(
                f"Could not validate scenario history: {error}"
            )

            self.repair_history_file()

    # ============================================================
    # WRITE HEADER
    # ============================================================

    def write_history_header(self):

        with open(
            self.history_file,
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=self.HISTORY_FIELDS,
            )

            writer.writeheader()

    # ============================================================
    # REPAIR LEGACY HISTORY
    # ============================================================

    def repair_history_file(self):

        try:

            backup_index = 0

            while True:

                if backup_index == 0:

                    backup_file = (
                        self.history_file.parent
                        / "scenario_data.legacy.csv"
                    )

                else:

                    backup_file = (
                        self.history_file.parent
                        / (
                            f"scenario_data.legacy_"
                            f"{backup_index}.csv"
                        )
                    )

                if not backup_file.exists():
                    break

                backup_index += 1

            self.history_file.replace(
                backup_file
            )

            self.get_logger().warning(
                f"Backed up old scenario history to "
                f"{backup_file}"
            )

            self.write_history_header()

            migrated_rows = []

            with open(
                backup_file,
                "r",
                newline="",
                encoding="utf-8",
            ) as file:

                reader = csv.reader(file)

                next(
                    reader,
                    None,
                )

                for row in reader:

                    row = [
                        str(value).strip()
                        for value in row
                    ]

                    if len(row) != len(
                        self.HISTORY_FIELDS
                    ):
                        continue

                    migrated_rows.append(
                        dict(
                            zip(
                                self.HISTORY_FIELDS,
                                row,
                            )
                        )
                    )

            if migrated_rows:

                with open(
                    self.history_file,
                    "a",
                    newline="",
                    encoding="utf-8",
                ) as file:

                    writer = csv.DictWriter(
                        file,
                        fieldnames=self.HISTORY_FIELDS,
                    )

                    writer.writerows(
                        migrated_rows
                    )

                self.get_logger().info(
                    f"Migrated {len(migrated_rows)} "
                    f"scenario history records."
                )

        except Exception as error:

            self.get_logger().error(
                f"Scenario history repair failed: {error}"
            )

    # ============================================================
    # APPEND HISTORY
    # ============================================================

    def append_history(
        self,
        scenario_id: str,
        scenario: dict,
        status: str,
    ):

        self.prepare_history_file()

        row = {
            "timestamp": int(time.time()),

            "scenario_id": scenario_id,

            "scenario_name": scenario.get(
                "scenario_name",
                "",
            ),

            "scenario_type": scenario.get(
                "scenario_type",
                scenario_id,
            ),

            "duration_min": scenario.get(
                "duration_min",
                0,
            ),

            "grid_available_power_kw": scenario.get(
                "grid_available_power_kw",
                0,
            ),

            "solar_available_power_kw": scenario.get(
                "solar_available_power_kw",
                0,
            ),

            "required_reduction_kw": scenario.get(
                "required_reduction_kw",
                0,
            ),

            "minimum_production_percent": scenario.get(
                "minimum_production_percent",
                0,
            ),

            "battery_available_kwh": scenario.get(
                "battery_available_kwh",
                0,
            ),

            "status": status,
        }

        with open(
            self.history_file,
            "a",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=self.HISTORY_FIELDS,
            )

            writer.writerow(row)

    # ============================================================
    # BUILD SCENARIO PAYLOAD
    # ============================================================

    def build_payload(
        self,
        scenario_id: str,
        scenario: dict,
        status: str,
    ) -> dict:

        payload = {
            "timestamp": int(time.time()),

            "scenario_id": scenario_id,

            "scenario_name": scenario.get(
                "scenario_name",
                "",
            ),

            "scenario_type": scenario.get(
                "scenario_type",
                scenario_id,
            ),

            "duration_min": scenario.get(
                "duration_min",
                0,
            ),

            "grid_available_power_kw": scenario.get(
                "grid_available_power_kw",
                0,
            ),

            "solar_available_power_kw": scenario.get(
                "solar_available_power_kw",
                0,
            ),

            "required_reduction_kw": scenario.get(
                "required_reduction_kw",
                0,
            ),

            "minimum_production_percent": scenario.get(
                "minimum_production_percent",
                0,
            ),

            "battery_available_kwh": scenario.get(
                "battery_available_kwh",
                0,
            ),

            "demand_multiplier": scenario.get(
                "demand_multiplier",
                1.0,
            ),

            "status": status,
        }

        # Preserve scenario-specific configuration such as:
        #
        # anomaly_machine_id
        # anomaly_load_percent
        # anomaly_temperature_offset_c
        # anomaly_vibration_offset_mm_s
        #
        for key, value in scenario.items():

            if key not in payload:

                payload[key] = value

        return payload

    # ============================================================
    # PUBLISH SCENARIO
    # ============================================================

    def publish_scenario(
        self,
        scenario_id: str,
        scenario: dict,
        status: str,
    ):

        payload = self.build_payload(
            scenario_id,
            scenario,
            status,
        )

        message = String()

        message.data = json.dumps(
            payload
        )

        self.publisher.publish(
            message
        )

        self.last_state_broadcast = time.time()

    # ============================================================
    # BROADCAST CURRENT STATE
    # ============================================================

    def broadcast_current_state(self):

        if (
            self.active_scenario is None
            or self.active_scenario not in self.scenarios
        ):
            return

        elapsed = (
            time.time()
            - self.last_state_broadcast
        )

        if elapsed < self.STATE_BROADCAST_INTERVAL_SEC:

            return

        scenario = self.scenarios[
            self.active_scenario
        ]

        # Use ACTIVE for the persistent current state.
        #
        # STARTED is an event recorded once in history.
        # ACTIVE means this is the current live scenario.
        self.publish_scenario(
            self.active_scenario,
            scenario,
            "ACTIVE",
        )

    # ============================================================
    # ACTIVATE NORMAL
    # ============================================================

    def activate_normal(self):

        if "NORMAL" not in self.scenarios:

            self.get_logger().error(
                "Cannot activate NORMAL."
            )

            return False

        normal = self.scenarios[
            "NORMAL"
        ]

        duration_min = float(
            normal.get(
                "duration_min",
                60,
            )
        )

        self.active_scenario = "NORMAL"

        self.active_until = (
            time.time()
            + duration_min * 60.0
        )

        self.publish_scenario(
            "NORMAL",
            normal,
            "ACTIVE",
        )

        self.append_history(
            "NORMAL",
            normal,
            "ACTIVE",
        )

        self.get_logger().info(
            "SCENARIO ACTIVE: NORMAL | "
            f"{normal.get('scenario_name', '')}"
        )

        return True

    # ============================================================
    # START SCENARIO
    # ============================================================

    def start_scenario(
        self,
        scenario_id: str,
    ) -> bool:

        scenario_id = str(
            scenario_id or ""
        ).strip().upper()

        if not scenario_id:

            self.get_logger().error(
                "Scenario ID is empty."
            )

            return False

        if scenario_id not in self.scenarios:

            self.get_logger().error(
                f"Unknown scenario: {scenario_id}"
            )

            return False

        scenario = self.scenarios[
            scenario_id
        ]

        duration_min = float(
            scenario.get(
                "duration_min",
                1,
            )
        )

        # --------------------------------------------------------
        # Complete currently active scenario if different.
        # --------------------------------------------------------

        if (
            self.active_scenario is not None
            and self.active_scenario != scenario_id
            and self.active_scenario in self.scenarios
        ):

            previous_id = (
                self.active_scenario
            )

            previous = self.scenarios[
                previous_id
            ]

            self.publish_scenario(
                previous_id,
                previous,
                "COMPLETED",
            )

            self.append_history(
                previous_id,
                previous,
                "COMPLETED",
            )

        # --------------------------------------------------------
        # Activate requested scenario.
        # --------------------------------------------------------

        self.active_scenario = scenario_id

        self.active_until = (
            time.time()
            + duration_min * 60.0
        )

        self.publish_scenario(
            scenario_id,
            scenario,
            "STARTED",
        )

        self.append_history(
            scenario_id,
            scenario,
            "STARTED",
        )

        self.get_logger().info(
            f"SCENARIO STARTED: "
            f"{scenario_id} | "
            f"{scenario.get('scenario_name', '')} | "
            f"{duration_min:g} min"
        )

        return True

    # ============================================================
    # STOP SCENARIO
    # ============================================================

    def stop_scenario(self):

        if self.active_scenario is None:

            return

        scenario_id = (
            self.active_scenario
        )

        scenario = self.scenarios.get(
            scenario_id
        )

        if scenario is not None:

            self.publish_scenario(
                scenario_id,
                scenario,
                "COMPLETED",
            )

            self.append_history(
                scenario_id,
                scenario,
                "COMPLETED",
            )

            self.get_logger().info(
                f"SCENARIO COMPLETED: "
                f"{scenario_id}"
            )

        self.active_scenario = None
        self.active_until = 0.0

        # Return to NORMAL.
        self.activate_normal()

    # ============================================================
    # TIMER
    # ============================================================

    def timer_callback(self):

        # --------------------------------------------------------
        # Check scenario expiry.
        # --------------------------------------------------------

        if (
            self.active_scenario is not None
            and time.time() >= self.active_until
        ):

            expired = self.active_scenario

            self.get_logger().info(
                f"Scenario duration expired: {expired}"
            )

            self.stop_scenario()

            return

        # --------------------------------------------------------
        # Continuously broadcast current state.
        # --------------------------------------------------------

        self.broadcast_current_state()

    # ============================================================
    # COMMAND CALLBACK
    # ============================================================

    def command_callback(
        self,
        message: String,
    ):

        try:

            data = json.loads(
                message.data
            )

            if not isinstance(data, dict):

                raise TypeError(
                    "Scenario command must "
                    "be a JSON object."
                )

            action = str(
                data.get(
                    "action",
                    "",
                )
            ).strip().upper()

            scenario_id = str(
                data.get(
                    "scenario_id",
                    "",
                )
            ).strip().upper()

            if action == "START":

                self.start_scenario(
                    scenario_id
                )

            elif action == "STOP":

                self.stop_scenario()

            else:

                self.get_logger().error(
                    f"Unknown scenario action: "
                    f"{action}"
                )

        except (
            json.JSONDecodeError,
            TypeError,
            KeyError,
        ) as error:

            self.get_logger().error(
                f"Invalid scenario command: {error}"
            )


# ====================================================================
# MAIN
# ====================================================================

def main():

    rclpy.init()

    node = ScenarioManager()

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
