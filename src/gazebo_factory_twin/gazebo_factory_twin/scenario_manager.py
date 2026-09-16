from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ScenarioManager(Node):

    def __init__(self):
        super().__init__("scenario_manager")

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

        self.topic = "/factory/scenario"

        self.publisher = self.create_publisher(
            String,
            self.topic,
            10
        )

        self.scenarios = self.load_scenarios()

        self.get_logger().info(
            f"Loaded {len(self.scenarios)} scenarios"
        )

        self.active_scenario = None
        self.active_until = 0.0

        self.timer = self.create_timer(
            1.0,
            self.check_active_scenario
        )

    def load_scenarios(self):

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
                encoding="utf-8"
            ) as file:

                data = json.load(file)

            return data

        except (
            json.JSONDecodeError,
            OSError
        ) as error:

            self.get_logger().error(
                f"Failed to load scenarios: {error}"
            )

            return {}

    def append_history(
        self,
        scenario_id: str,
        scenario: dict,
        status: str
    ):

        self.history_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        fields = [
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
            "status"
        ]

        file_exists = self.history_file.exists()
        file_empty = (
            not file_exists
            or self.history_file.stat().st_size == 0
        )

        with open(
            self.history_file,
            "a",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fields
            )

            if file_empty:
                writer.writeheader()

            writer.writerow({
                "timestamp": int(time.time()),
                "scenario_id": scenario_id,
                "scenario_name": scenario.get(
                    "scenario_name",
                    ""
                ),
                "scenario_type": scenario.get(
                    "scenario_type",
                    ""
                ),
                "duration_min": scenario.get(
                    "duration_min",
                    0
                ),
                "grid_available_power_kw": scenario.get(
                    "grid_available_power_kw",
                    0
                ),
                "solar_available_power_kw": scenario.get(
                    "solar_available_power_kw",
                    0
                ),
                "required_reduction_kw": scenario.get(
                    "required_reduction_kw",
                    0
                ),
                "minimum_production_percent": scenario.get(
                    "minimum_production_percent",
                    0
                ),
                "battery_available_kwh": scenario.get(
                    "battery_available_kwh",
                    0
                ),
                "status": status
            })

    def publish_scenario(
        self,
        scenario_id: str,
        scenario: dict,
        status: str
    ):

        payload = {
            "timestamp": int(time.time()),
            "scenario_id": scenario_id,
            **scenario,
            "status": status
        }

        message = String()

        message.data = json.dumps(
            payload
        )

        self.publisher.publish(
            message
        )

    def start_scenario(
        self,
        scenario_id: str
    ) -> bool:

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
                1
            )
        )

        self.active_scenario = scenario_id

        self.active_until = (
            time.time()
            + duration_min * 60.0
        )

        self.publish_scenario(
            scenario_id,
            scenario,
            "STARTED"
        )

        self.append_history(
            scenario_id,
            scenario,
            "STARTED"
        )

        self.get_logger().info(
            f"SCENARIO STARTED: "
            f"{scenario_id} | "
            f"{scenario.get('scenario_name', '')} | "
            f"{duration_min:g} min"
        )

        return True

    def stop_scenario(self):

        if self.active_scenario is None:
            return

        scenario_id = self.active_scenario
        scenario = self.scenarios[
            scenario_id
        ]

        self.publish_scenario(
            scenario_id,
            scenario,
            "COMPLETED"
        )

        self.append_history(
            scenario_id,
            scenario,
            "COMPLETED"
        )

        self.get_logger().info(
            f"SCENARIO COMPLETED: {scenario_id}"
        )

        self.active_scenario = None
        self.active_until = 0.0

        # Return the factory to NORMAL
        if "NORMAL" in self.scenarios:

            normal = self.scenarios["NORMAL"]

            self.publish_scenario(
                "NORMAL",
                normal,
                "ACTIVE"
            )

    def check_active_scenario(self):

        if self.active_scenario is None:
            return

        if time.time() >= self.active_until:
            self.stop_scenario()

    def command_callback(self, message: String):

        try:

            data = json.loads(
                message.data
            )

            action = data.get(
                "action"
            )

            scenario_id = data.get(
                "scenario_id"
            )

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
            KeyError
        ) as error:

            self.get_logger().error(
                f"Invalid scenario command: "
                f"{error}"
            )


def main():

    rclpy.init()

    node = ScenarioManager()

    command_subscription = node.create_subscription(
        String,
        "/factory/scenario_command",
        node.command_callback,
        10
    )

    # Keep the subscription alive.
    node.command_subscription = command_subscription

    # Start with NORMAL scenario automatically.
    if "NORMAL" in node.scenarios:
        node.start_scenario("NORMAL")

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
